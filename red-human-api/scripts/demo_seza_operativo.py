"""Demo Grupo SEZA — puntos 5 a 8 (2026-09-29). Lo usa `cargar_demo_seza.py` (no se corre solo).

* Kanban operativo en la Cuenta (`Cuenta.flujo_candidatos = "operativo"`).
* «Inducción SEZA»: DUPLICADO de un curso existente (el primero con módulos de cualquier Cuenta; si la base no
  tiene ninguno se crea antes un curso base de inducción para choferes y se duplica ese).
* Sesiones de «Capacitación en tienda» por plaza: una ya realizada y una próxima, con cupo y supervisor.
* Candidatos FICTICIOS que recorren las 8 etapas con las funciones reales del flujo (prefiltro por reglas,
  fotos del vehículo, cita, asistencia del supervisor, documentos, referencias y alta), para probar el tablero y
  sus contadores. Sin teléfono y con correo `@demo.invalid`: ningún mensaje puede salir. Idempotente por correo.
"""

import asyncio
import struct
import zlib
from datetime import datetime, timedelta, timezone

from app.models import (
    Archivo, Candidato, Curso, Documento, ModuloCurso, Postulacion, SesionCapacitacion, registrar,
)
from app.routers.candidatos import _crear_candidato, cerrar_prefiltro_reglas, crear_postulacion
from app.routers.capacitacion import duplicar_curso
from app.services import archivos as fs
from app.services import flujo_operativo as flujo
from app.services import prefiltro_reglas as pr
from app.services import vehiculo as vehiculo_srv
from app.services.notificaciones import TZ_MEXICO

ACTOR = "script:cargar_demo_seza"
TITULO_INDUCCION = "Inducción SEZA"
DOMINIO = "demo.invalid"


def _png(color) -> bytes:
    """PNG liso de 320×240 (marcador de la foto del vehículo en la demo)."""
    ancho, alto = 320, 240
    fila = b"\x00" + bytes(color) * ancho
    crudo = fila * alto

    def bloque(tipo, datos):
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + bloque(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))
            + bloque(b"IDAT", zlib.compress(crudo, 9)) + bloque(b"IEND", b""))


PDF_DEMO = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n" + b"%" + b"0" * 600


# ------------------------------------------------------------ inducción


def _curso_base(db, cuenta, actor) -> Curso:
    c = Curso(codigo="TMP", cuenta_id=cuenta.id, titulo="Inducción para choferes de reparto", categoria="Inducción",
              duracion_horas=0.5, duracion_texto="30 min", modalidad="autoguiado", estado="Publicado", creado_por=actor,
              objetivo="Que el chofer conozca la operación de reparto, la seguridad en ruta y el uso de la aplicación.",
              evaluacion=[{"pregunta": "¿Qué haces al terminar cada entrega?", "tipo": "opcion_multiple",
                           "opciones": ["Nada", "La confirmo en la aplicación", "Llamo a la tienda"], "correcta": 1,
                           "explicacion": "Cada entrega se confirma en la aplicación del teléfono."}])
    db.add(c)
    db.flush()
    c.codigo = f"CUR-{100 + c.id}"
    modulos = [
        ("Bienvenida y operación", "Cómo funciona un día de reparto: recolección en tienda, ruta y confirmación de entregas.",
         ["Horario y punto de recolección", "Ruta del día", "Confirmación en la aplicación"]),
        ("Seguridad en ruta", "Manejo defensivo, cuidado del producto y qué hacer ante un incidente.",
         ["Respeta límites de velocidad", "Asegura la carga", "Reporta incidentes de inmediato"]),
        ("Uso de la aplicación", "Iniciar sesión, ver pedidos, marcar entregas y reportar problemas.",
         ["Mantén el teléfono cargado", "Confirma cada entrega", "Reporta direcciones incorrectas"]),
    ]
    for i, (titulo, contenido, puntos) in enumerate(modulos, start=1):
        db.add(ModuloCurso(curso_id=c.id, orden=i, titulo=titulo, contenido=contenido, resumen=contenido, puntos_clave=puntos))
    db.flush()
    db.refresh(c)
    registrar(db, actor, "curso_creado", "curso", c.codigo, {"titulo": c.titulo, "motivo": "base para duplicar Inducción SEZA"})
    return c


def induccion(db, cuenta, admin) -> Curso:
    existente = db.query(Curso).filter(Curso.cuenta_id == cuenta.id, Curso.titulo == TITULO_INDUCCION).first()
    if existente:
        print(f"  = Curso «{TITULO_INDUCCION}» ya existía ({existente.codigo})")
        return existente
    origen = next((c for c in db.query(Curso).filter(Curso.estado == "Publicado").order_by(Curso.id).all() if c.modulos), None)
    origen = origen or next((c for c in db.query(Curso).order_by(Curso.id).all() if c.modulos), None)
    if origen is None:
        origen = _curso_base(db, cuenta, ACTOR)
        print(f"  + Curso base «{origen.titulo}» ({origen.codigo}) — la base no tenía cursos")
    copia = duplicar_curso(db, origen, TITULO_INDUCCION, cuenta.id, admin.nombre)
    copia.estado = "Publicado"
    db.flush()
    print(f"  + Curso «{TITULO_INDUCCION}» ({copia.codigo}) duplicado de {origen.codigo} «{origen.titulo}»")
    return copia


# ------------------------------------------------------------ sesiones


SUPERVISORES = {"Puebla": ("Rocío Hernández", "Tienda SEZA Angelópolis", "Blvd. del Niño Poblano 2510, Puebla"),
                "San José del Cabo": ("Martín Castro", "Tienda SEZA San José", "Blvd. Mijares 1200, San José del Cabo"),
                "CDMX": ("Laura Méndez", "Tienda SEZA Iztapalapa", "Calz. Ermita Iztapalapa 3016, CDMX")}


def _nueva_sesion(db, cuenta, v, plaza, cuando, cupo, curso, estado) -> SesionCapacitacion:
    import secrets

    sup, tienda, direccion = SUPERVISORES[plaza]
    s = SesionCapacitacion(codigo="TMP", cuenta_id=cuenta.id, vacante_id=v.id, tienda=tienda, direccion=direccion, inicio=cuando,
                           duracion_min=180, cupo=cupo, supervisor_nombre=sup, curso_induccion_id=curso.id, token=secrets.token_urlsafe(24),
                           indicaciones="Llega 15 minutos antes con tu INE y licencia. Viste ropa cómoda y zapato cerrado.",
                           estado=estado, creada_por=ACTOR)
    db.add(s)
    db.flush()
    s.codigo = f"SES-{300 + s.id}"
    return s


def sesiones(db, cuenta, vacantes_por_plaza, curso) -> dict:
    """{plaza: (pasada, proxima)} — idempotente por vacante."""
    hoy = datetime.now(TZ_MEXICO).replace(hour=9, minute=0, second=0, microsecond=0)
    salida = {}
    for plaza, v in vacantes_por_plaza.items():
        previas = db.query(SesionCapacitacion).filter(SesionCapacitacion.cuenta_id == cuenta.id, SesionCapacitacion.vacante_id == v.id).order_by(SesionCapacitacion.inicio).all()
        if len(previas) >= 2:
            salida[plaza] = (previas[0], previas[-1])
            print(f"  = Sesiones de {plaza} ya existían ({previas[0].codigo}, {previas[-1].codigo})")
            continue
        pasada = _nueva_sesion(db, cuenta, v, plaza, (hoy - timedelta(days=3)).astimezone(timezone.utc), 12, curso, "cerrada")
        proxima = _nueva_sesion(db, cuenta, v, plaza, (hoy + timedelta(days=2)).astimezone(timezone.utc), 8, curso, "programada")
        salida[plaza] = (pasada, proxima)
        print(f"  + Sesiones {plaza}: {pasada.codigo} (realizada, cupo 12) y {proxima.codigo} (próxima, cupo 8)")
    return salida


# ------------------------------------------------------------ candidatos ficticios


RESP_OK = {
    "Puebla": {"municipio": "Puebla", "tipo_vehiculo": pr.SEDAN, "anio_vehiculo": "2019"},
    "San José del Cabo": {"municipio": "Los Cabos", "tipo_vehiculo": pr.SEDAN, "anio_vehiculo": "2021"},
    "CDMX": {"municipio": "Iztapalapa", "tipo_vehiculo": pr.KANGOO, "anio_vehiculo": "2012"},
}
BASE = {"jornada": "si", "experiencia": "si", "vehiculo_propio": "si", "taxi": "no", "circulacion": "Sí",
        "licencia": "si", "poliza": "si", "android": "si"}

# (nombre, plaza, etapa objetivo, variante, fuente)
FICTICIOS = [
    ("Jorge Luis Ramírez Soto", "Puebla", "Nuevo", "", "WhatsApp"),
    ("María Guadalupe Flores", "CDMX", "Nuevo", "", "Facebook"),
    ("Enrique Salazar Vega", "San José del Cabo", "Nuevo", "", "WhatsApp"),
    ("Óscar Martínez Luna", "CDMX", "Prefiltro", "en_curso", "WhatsApp"),
    ("Brenda Aguilar Ríos", "Puebla", "Prefiltro", "revision_anio", "Facebook"),
    ("Raúl Domínguez Paz", "CDMX", "Prefiltro", "revision_licencia", "Formulario"),
    ("Sergio Navarro Cruz", "San José del Cabo", "Prefiltro", "no_cumple", "Facebook"),
    ("Luis Fernando Ortega", "Puebla", "Revisión de vehículo", "sin_fotos", "Facebook"),
    ("Adriana Torres Mejía", "CDMX", "Revisión de vehículo", "por_revisar", "WhatsApp"),
    ("Carlos Eduardo Reyes", "San José del Cabo", "Revisión de vehículo", "correccion", "Formulario"),
    ("Daniel Herrera Campos", "CDMX", "Revisión de vehículo", "por_revisar", "Facebook"),
    ("Miguel Ángel Rosas", "Puebla", "Cita para capacitación", "confirmada", "Facebook"),
    ("Verónica Castillo Díaz", "CDMX", "Cita para capacitación", "por_confirmar", "WhatsApp"),
    ("Javier Morales Peña", "San José del Cabo", "Cita para capacitación", "confirmada", "Facebook"),
    ("Hugo Sánchez Ibarra", "CDMX", "Cita para capacitación", "por_confirmar", "Formulario"),
    ("Alejandro Vázquez Gil", "Puebla", "Capacitación realizada", "favorable", "Facebook"),
    ("Patricia León Trejo", "CDMX", "Capacitación realizada", "con_observaciones", "WhatsApp"),
    ("Fernando Ruiz Olvera", "San José del Cabo", "Capacitación realizada", "desfavorable", "Facebook"),
    ("Ricardo Jiménez Mora", "CDMX", "Documentos y referencias", "sin_nada", "Facebook"),
    ("Claudia Romero Estrada", "Puebla", "Documentos y referencias", "parcial", "WhatsApp"),
    ("Armando Gutiérrez Silva", "CDMX", "Documentos y referencias", "refs_sin_contactar", "Facebook"),
    ("Gabriela Medina Luján", "San José del Cabo", "Listo para alta", "", "Formulario"),
    ("Roberto Cervantes Paredes", "CDMX", "Listo para alta", "", "Facebook"),
    ("Iván Delgado Fuentes", "Puebla", "Alta realizada", "", "Facebook"),
    ("Tomás Guerrero Álvarez", "CDMX", "Alta realizada", "", "WhatsApp"),
]
REFS = [("Ana Soto", "Familiar"), ("Pedro Luna", "Exjefe o excompañero"), ("Rosa Vega", "Amistad")]


def _fotos(db, p, faltantes=0):
    r = vehiculo_srv.obtener_o_crear(db, p)
    colores = {"frente": (70, 110, 170), "atras": (90, 90, 100), "izquierdo": (120, 130, 140), "derecho": (140, 120, 110)}
    for lado in list(colores)[: 4 - faltantes]:
        ruta = fs.guardar_bytes(_png(colores[lado]), f"vehiculo/{p.codigo}", f"{lado}-demo.png")
        a = Archivo(candidato_id=p.candidato_id, tipo=f"vehiculo_{lado}", nombre=f"{lado}.png", ruta=ruta, mime="image/png",
                    tamano=len(_png(colores[lado])), subido_por="candidato (liga de vehículo)")
        db.add(a)
        db.flush()
        vehiculo_srv.registrar_foto(db, r, lado, a.id)
    return r


def _documentos(db, p, cuantos_aprobados):
    e = flujo.abrir_expediente(db, p, ACTOR)
    for i, d in enumerate([d for d in e.documentos if not d.interno]):
        if i >= cuantos_aprobados:
            break
        d.archivo = fs.guardar_bytes(PDF_DEMO, f"expedientes/{e.id}", f"{d.tipo[:30]}.pdf")
        d.estado, d.revisado_por = "recibido", "RH demo"
        if hasattr(d, "recibido_canal"):
            d.recibido_canal = "liga"
    db.flush()
    return e


def _referencias(db, p, contactadas, admin):
    e = p.expediente
    flujo.guardar_referencias(db, e, [{"nombre": n, "telefono": f"55{5000000 + i * 1111:08d}"[-10:], "parentesco": par} for i, (n, par) in enumerate(REFS, start=1)])
    for i in range(contactadas):
        flujo.marcar_referencia(e, i, True, "Confirma que lo conoce y lo recomienda.", admin.nombre, resultado="Favorable")


async def _llevar(db, p, plaza, etapa, variante, admin, sesion_pasada, sesion_proxima):
    orden = flujo.ETAPAS_OPERATIVO.index(etapa)
    if etapa == "Nuevo":
        return
    resp = {**BASE, **RESP_OK[plaza]}
    if variante == "en_curso":  # contestó las primeras 4 por WhatsApp
        p.analisis = {"prefiltro_reglas": {"respuestas": {k: resp[k] for k in ("municipio", "jornada", "experiencia", "vehiculo_propio")},
                                           "textos": {}, "pendiente": "tipo_vehiculo", "canal": "whatsapp"}}
        flujo.mover(db, p, flujo.PREFILTRO, "agente-ia", "El candidato empezó el prefiltro")
        return
    if variante == "revision_anio":
        resp["anio_vehiculo"] = "2015"
    elif variante == "revision_licencia":
        resp["licencia"] = "no"
    elif variante == "no_cumple":
        resp["jornada"] = "no"
    textos = {k: ({"si": "Sí", "no": "No"}.get(v, v)) for k, v in resp.items()}
    await cerrar_prefiltro_reglas(db, p, resp, textos, "web")
    if orden <= 1:
        return
    # Revisión de vehículo
    if variante == "sin_fotos":
        return
    _fotos(db, p)
    if variante == "correccion":
        vehiculo_srv.decidir(db, p, "correccion", admin.nombre, "La foto de atrás no muestra las placas.", ["atras"])
        return
    if orden == 2:
        return
    vehiculo_srv.decidir(db, p, "aprobar", admin.nombre)
    flujo.al_decidir_vehiculo(db, p, "aprobar", admin.nombre)
    # Cita
    sesion = sesion_proxima if orden == 3 else sesion_pasada
    await flujo.citar(db, p, sesion, admin.nombre)
    if orden == 3 and variante == "por_confirmar":
        return
    await flujo.confirmar_cita(db, p, "candidato")
    if orden == 3:
        return
    ev = flujo.evaluacion_capacitacion(db, p)
    resultado = variante if variante in ("favorable", "con_observaciones", "desfavorable") else "favorable"
    comentario = {"con_observaciones": "Buen manejo, pero le costó usar la aplicación; reforzar en su primera semana.",
                  "desfavorable": "Llegó 40 minutos tarde y no siguió las indicaciones de seguridad."}.get(resultado, "Muy buena actitud y manejo.")
    flujo.registrar_asistencia(db, ev, True, resultado, comentario, sesion.supervisor_nombre)
    if orden == 4:
        return
    await flujo.solicitar_documentos_referencias(db, p, admin.nombre)
    if variante == "sin_nada":
        return
    total_docs = len(flujo.DOCUMENTOS_OPERATIVO)
    _documentos(db, p, 4 if variante == "parcial" else total_docs)
    _referencias(db, p, 0 if variante in ("parcial", "refs_sin_contactar") else 3, admin)
    db.flush()  # (refresh(p) recargaría el expediente en cascada y perdería lo no escrito)
    flujo.revisar_listo(db, p, admin.nombre)
    if orden == 7:
        flujo.registrar_alta(db, p, admin, prueba=False)


def candidatos(db, cuenta, admin, vacantes_por_plaza, ses) -> int:
    creados = 0
    for i, (nombre, plaza, etapa, variante, fuente) in enumerate(FICTICIOS, start=1):
        correo = f"seza.demo.{i:02d}@{DOMINIO}"
        if db.query(Candidato).filter(Candidato.correo == correo).first():
            continue
        v = vacantes_por_plaza[plaza]
        c = _crear_candidato(db, cuenta.id, nombre, fuente, False, correo=correo)
        p = crear_postulacion(db, c, v, cuenta.id, "whatsapp" if fuente == "WhatsApp" else "formulario", consentimiento=True)
        pasada, proxima = ses[plaza]
        asyncio.run(_llevar(db, p, plaza, etapa, variante, admin, pasada, proxima))
        db.flush()
        if p.etapa != etapa:
            raise RuntimeError(f"{nombre}: quedó en «{p.etapa}», se esperaba «{etapa}» — faltan: {flujo.faltantes_para_alta(p)}")
        creados += 1
    registrar(db, ACTOR, "candidatos_ficticios_seza", "sistema", "demo-seza", {"creados": creados})
    return creados


def conteo_por_etapa(db, cuenta) -> dict:
    from app.services import conteos

    return conteos.por_etapa(db, cuenta.id)
