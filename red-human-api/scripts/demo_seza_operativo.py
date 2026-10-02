"""Demo Grupo SEZA — flujo operativo v2 (2026-09-30). Lo usa `cargar_demo_seza.py` (no se corre solo).

* Kanban operativo en la Cuenta (`Cuenta.flujo_candidatos = "operativo"`), 5 columnas (v3): Prefiltro → Revisión de
  vehículo → Entrevista → Contratación → Onboarding.
* «Inducción SEZA»: DUPLICADO de un curso existente (el primero con módulos de cualquier Cuenta; si la base no
  tiene ninguno se crea antes un curso base de inducción para choferes y se duplica ese).
* Candidatos FICTICIOS que recorren las 5 columnas con las funciones reales del flujo (prefiltro por reglas, fotos
  y documentos del vehículo, capacitación en tienda con su capacitador, condiciones y contrato, documentos,
  referencias y alta). Sin teléfono y con correo `@demo.invalid`: ningún mensaje puede salir. Idempotente por
  correo. Uno queda dado de alta (postulación cerrada como `contratado`: se ve con «Mostrar cerradas»).
"""

import asyncio
import struct
import zlib
from datetime import datetime, timedelta, timezone

from app.models import DOCUMENTOS_VEHICULO, Archivo, Candidato, Curso, ModuloCurso, registrar
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


# ------------------------------------------------------------ capacitadores por plaza


CAPACITADORES = {"Puebla": ("Rocío Hernández", "Tienda SEZA Angelópolis", "Blvd. del Niño Poblano 2510, Puebla"),
                 "San José del Cabo": ("Martín Castro", "Tienda SEZA San José", "Blvd. Mijares 1200, San José del Cabo"),
                 "CDMX": ("Laura Méndez", "Tienda SEZA Iztapalapa", "Calz. Ermita Iztapalapa 3016, CDMX")}


# ------------------------------------------------------------ candidatos ficticios


RESP_OK = {
    "Puebla": {"municipio": "Puebla", "tipo_vehiculo": pr.SEDAN, "anio_vehiculo": "2019"},
    "San José del Cabo": {"municipio": "Los Cabos", "tipo_vehiculo": pr.SEDAN, "anio_vehiculo": "2021"},
    "CDMX": {"municipio": "Iztapalapa", "tipo_vehiculo": pr.KANGOO, "anio_vehiculo": "2012"},
}
BASE = {"jornada": "si", "experiencia": "si", "vehiculo_propio": "si", "taxi": "no", "circulacion": "Sí",
        "licencia": "Automovilista", "poliza": "si", "android": "si"}

# (nombre, plaza, etapa objetivo, variante, fuente)
FICTICIOS = [
    ("Jorge Luis Ramírez Soto", "Puebla", "Prefiltro", "sin_iniciar", "WhatsApp"),
    ("María Guadalupe Flores", "CDMX", "Prefiltro", "sin_iniciar", "Facebook"),
    ("Enrique Salazar Vega", "San José del Cabo", "Prefiltro", "sin_iniciar", "Telegram"),
    ("Óscar Martínez Luna", "CDMX", "Prefiltro", "en_curso", "Telegram"),
    ("Brenda Aguilar Ríos", "Puebla", "Prefiltro", "revision_anio", "Facebook"),
    ("Raúl Domínguez Paz", "CDMX", "Prefiltro", "revision_licencia", "Formulario"),
    ("Sergio Navarro Cruz", "San José del Cabo", "Prefiltro", "no_cumple", "Facebook"),
    ("Luis Fernando Ortega", "Puebla", "Revisión de vehículo", "sin_fotos", "Facebook"),
    ("Adriana Torres Mejía", "CDMX", "Revisión de vehículo", "por_revisar", "Telegram"),
    ("Carlos Eduardo Reyes", "San José del Cabo", "Revisión de vehículo", "correccion", "Formulario"),
    ("Daniel Herrera Campos", "CDMX", "Revisión de vehículo", "por_revisar", "Facebook"),
    ("Miguel Ángel Rosas", "Puebla", "Entrevista", "por_citar", "Facebook"),
    ("Verónica Castillo Díaz", "CDMX", "Entrevista", "por_confirmar", "Telegram"),
    ("Javier Morales Peña", "San José del Cabo", "Entrevista", "confirmada", "Facebook"),
    ("Hugo Sánchez Ibarra", "CDMX", "Entrevista", "favorable", "Formulario"),
    ("Alejandro Vázquez Gil", "Puebla", "Entrevista", "con_observaciones", "Facebook"),
    ("Patricia León Trejo", "CDMX", "Entrevista", "desfavorable", "Telegram"),
    ("Fernando Ruiz Olvera", "San José del Cabo", "Entrevista", "eval_pendiente", "Facebook"),
    ("Ricardo Jiménez Mora", "CDMX", "Entrevista", "eval_revisada", "Facebook"),
    ("Claudia Romero Estrada", "Puebla", "Contratación", "sin_condiciones", "Telegram"),
    ("Armando Gutiérrez Silva", "CDMX", "Contratación", "contrato_despues", "Facebook"),
    ("Gabriela Medina Luján", "San José del Cabo", "Onboarding", "sin_nada", "Formulario"),
    ("Roberto Cervantes Paredes", "CDMX", "Onboarding", "refs_sin_contactar", "Facebook"),
    ("Iván Delgado Fuentes", "Puebla", "Onboarding", "listo", "Facebook"),
    ("Tomás Guerrero Álvarez", "CDMX", "Onboarding", "alta", "Telegram"),
]
REFS = [("Ana Soto", "Familiar"), ("Pedro Luna", "Exjefe o excompañero"), ("Rosa Vega", "Amistad")]
SUELDOS = {"Puebla": "$650 MXN diarios, pago semanal", "San José del Cabo": "$800 MXN diarios, pago quincenal",
           "CDMX": "$780 MXN diarios, pago quincenal"}


def _fotos(db, p, faltantes=0):
    """4 fotos + los 3 documentos del vehículo (Recibidos, falta que RH los revise)."""
    r = vehiculo_srv.obtener_o_crear(db, p)
    colores = {"frente": (70, 110, 170), "atras": (90, 90, 100), "izquierdo": (120, 130, 140), "derecho": (140, 120, 110)}
    for lado in list(colores)[: 4 - faltantes]:
        ruta = fs.guardar_bytes(_png(colores[lado]), f"vehiculo/{p.codigo}", f"{lado}-demo.png")
        a = Archivo(candidato_id=p.candidato_id, tipo=f"vehiculo_{lado}", nombre=f"{lado}.png", ruta=ruta, mime="image/png",
                    tamano=len(_png(colores[lado])), subido_por="candidato (liga de vehículo)")
        db.add(a)
        db.flush()
        vehiculo_srv.registrar_foto(db, r, lado, a.id)
    for clave in DOCUMENTOS_VEHICULO:
        d = vehiculo_srv.documento(p, clave)
        d.archivo = fs.guardar_bytes(PDF_DEMO, f"expedientes/{p.expediente.id}", f"{clave}.pdf")
        d.estado, d.revisado_por, d.recibido_canal = "recibido", "", "liga"
        vehiculo_srv.registrar_documento_subido(db, r, clave)
    db.flush()
    return r


def _documentos(db, p, cuantos):
    """Sube y aprueba los primeros `cuantos` documentos PENDIENTES del expediente (los de Onboarding)."""
    e = p.expediente
    pendientes = [d for d in e.documentos if not d.interno and not d.aprobado]
    for d in pendientes[:cuantos]:
        d.archivo = fs.guardar_bytes(PDF_DEMO, f"expedientes/{e.id}", f"{d.tipo[:30]}.pdf")
        d.estado, d.revisado_por = "recibido", "RH demo"
        d.recibido_canal = "liga"
    db.flush()
    return e


def _referencias(db, p, contactadas, admin):
    e = p.expediente
    flujo.guardar_referencias(db, e, [{"nombre": n, "telefono": f"55{5000000 + i * 1111:08d}"[-10:], "parentesco": par} for i, (n, par) in enumerate(REFS, start=1)])
    for i in range(contactadas):
        flujo.marcar_referencia(e, i, True, "Confirma que lo conoce y lo recomienda.", admin.nombre, resultado="Favorable")
        flujo.validar_referencia(e, i, True, "Relación confirmada", admin.nombre)


def _evaluacion_adicional(db, p, admin, revisada: bool):
    """Psicométrica (captura manual) agregada con la función real del router: nunca mueve la tarjeta."""
    from app.routers import evaluaciones as rev

    ev = rev.agregar_evaluacion(p.codigo, rev.AgregarEvaluacionIn(tipo="psicometrica", nombre="Cleaver"), db=db, u=admin, cuenta=p.cuenta)
    if revisada:
        from app.models import EvaluacionCandidato
        from app.services import evaluaciones as sev

        e = db.query(EvaluacionCandidato).filter(EvaluacionCandidato.codigo == ev["id"]).first()
        e.resultado_resumen, e.resultado_cargado_por, e.resultado_origen = "Perfil estable y orientado a resultados.", admin.nombre, "rh"
        e.resultado_cargado_en = datetime.now(timezone.utc)
        sev.mover(e, "resultado_recibido", admin.nombre, "Resultado cargado (demo)")
        e.dictamen, e.comentario_revision, e.revisada_por, e.revisada_en = "favorable", "Sin observaciones.", admin.nombre, datetime.now(timezone.utc)
        sev.mover(e, "revisada", admin.nombre, "Dictamen: Favorable")


async def _llevar(db, p, plaza, etapa, variante, admin, curso):
    orden = flujo.ETAPAS_OPERATIVO.index(etapa)
    resp = {**BASE, **RESP_OK[plaza]}
    if variante == "sin_iniciar":
        return
    if variante == "en_curso":  # contestó las primeras 4 por chat
        p.analisis = {"prefiltro_reglas": {"respuestas": {k: resp[k] for k in ("municipio", "jornada", "experiencia", "vehiculo_propio")},
                                           "textos": {}, "pendiente": "tipo_vehiculo", "canal": "whatsapp"}}
        return
    if variante == "revision_anio":
        resp["anio_vehiculo"] = "2015"
    elif variante == "revision_licencia":
        resp["licencia"] = "No tengo licencia vigente"
    elif variante == "no_cumple":
        resp["jornada"] = "no"
    textos = {k: ({"si": "Sí", "no": "No"}.get(v, v)) for k, v in resp.items()}
    await cerrar_prefiltro_reglas(db, p, resp, textos, "web")
    if orden == 0:
        return
    # Revisión de vehículo
    if variante == "sin_fotos":
        vehiculo_srv.obtener_o_crear(db, p)
        return
    _fotos(db, p)
    if variante == "correccion":
        vehiculo_srv.decidir(db, p, "correccion", admin.nombre, "La foto de atrás no muestra las placas.", ["atras"])
        return
    if orden == 1:
        return
    vehiculo_srv.decidir(db, p, "aprobar", admin.nombre)
    flujo.al_decidir_vehiculo(db, p, "aprobar", admin.nombre)
    # Entrevista (capacitación en tienda)
    if variante == "por_citar":
        return
    sup, tienda, direccion = CAPACITADORES[plaza]
    hoy = datetime.now(TZ_MEXICO)
    pasada = variante in ("favorable", "con_observaciones", "desfavorable", "eval_pendiente", "eval_revisada") or orden > 2
    cuando = (hoy - timedelta(days=3)) if pasada else (hoy + timedelta(days=2))
    await flujo.programar_entrevista(db, p, {
        "tienda": tienda, "direccion": direccion, "fecha": cuando.strftime("%Y-%m-%d"), "hora": "09:00",
        "capacitador_tipo": "externo", "capacitador_nombre": sup, "curso_induccion": curso.codigo,
        "indicaciones": "Llega 15 minutos antes con tu INE y licencia. Viste ropa cómoda y zapato cerrado.",
    }, admin.nombre)
    if variante == "por_confirmar":
        return
    await flujo.confirmar_cita(db, p, "candidato")
    if variante == "confirmada":
        return
    resultado = variante if variante in ("favorable", "con_observaciones", "desfavorable") else "favorable"
    comentario = {"con_observaciones": "Buen manejo, pero le costó usar la aplicación; reforzar en su primera semana.",
                  "desfavorable": "Llegó 40 minutos tarde y no siguió las indicaciones de seguridad."}.get(resultado, "Muy buena actitud y manejo.")
    flujo.registrar_resultado(db, p, flujo.entrevista_actual(p), True, resultado, comentario, f"{sup} (capacitador)", "entrevistador")
    if variante in ("eval_pendiente", "eval_revisada"):  # v3: evaluación adicional desde la columna Entrevista
        _evaluacion_adicional(db, p, admin, revisada=variante == "eval_revisada")
    if orden == 2:
        return
    flujo.avanzar_a_contratacion(db, p, admin.nombre, prueba=False)
    if variante == "sin_condiciones":
        return
    e = p.expediente
    e.puesto = p.vacante.titulo
    e.sueldo = SUELDOS[plaza]
    e.tipo_contratacion = "Prestación de servicios"
    e.fecha_ingreso = (datetime.now(timezone.utc) + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    e.ubicacion = p.vacante.ubicacion or ""
    e.condiciones_guardadas_en = datetime.now(timezone.utc)
    flujo.decidir_contrato(db, p, "despues" if variante == "contrato_despues" else "ahora", admin.nombre)
    if orden == 3:
        return
    await flujo.enviar_a_onboarding(db, p, admin.nombre, prueba=False)
    if variante == "sin_nada":
        return
    _documentos(db, p, len(flujo.DOCUMENTOS_ONBOARDING))
    _referencias(db, p, 0 if variante == "refs_sin_contactar" else 3, admin)
    db.flush()
    if variante == "alta":
        flujo.registrar_alta(db, p, admin, prueba=False)


def candidatos(db, cuenta, admin, vacantes_por_plaza, curso) -> int:
    creados = 0
    for i, (nombre, plaza, etapa, variante, fuente) in enumerate(FICTICIOS, start=1):
        correo = f"seza.demo.{i:02d}@{DOMINIO}"
        if db.query(Candidato).filter(Candidato.correo == correo).first():
            continue
        v = vacantes_por_plaza[plaza]
        c = _crear_candidato(db, cuenta.id, nombre, fuente, False, correo=correo)
        p = crear_postulacion(db, c, v, cuenta.id, "whatsapp" if fuente in ("WhatsApp", "Telegram") else "formulario", consentimiento=True)
        asyncio.run(_llevar(db, p, plaza, etapa, variante, admin, curso))
        db.flush()
        if p.etapa != etapa:
            raise RuntimeError(f"{nombre}: quedó en «{p.etapa}», se esperaba «{etapa}» — faltan: {flujo.faltantes_para_alta(p)}")
        creados += 1
    registrar(db, ACTOR, "candidatos_ficticios_seza", "sistema", "demo-seza", {"creados": creados})
    return creados


def conteo_por_etapa(db, cuenta) -> dict:
    from app.services import conteos

    return conteos.por_etapa(db, cuenta.id)
