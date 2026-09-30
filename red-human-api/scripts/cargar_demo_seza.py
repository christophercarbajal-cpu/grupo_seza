"""Ambiente de demostración GRUPO SEZA — puntos 1 a 4 (2026-09-29).

Deja en la base (entorno aislado de la demo):
  * Cuenta «Grupo SEZA» con tres empresas (Clientes) y su color de marca:
    SEZA (azul), S (rojo) y G (guinda).
  * Plantilla general «Chofer de reparto con unidad propia».
  * 3 vacantes PUBLICADAS de SEZA creadas desde esa plantilla, con la función real del alta
    (`routers.vacantes.crear`, sin IA: el contenido va escrito aquí y nunca inventa condiciones):
      - Puebla ............ 10 h · $650 diarios, pago semanal · sedán 2018 o más reciente
      - San José del Cabo . 10 h · $800 diarios, pago quincenal · sedán 2020 o más reciente
      - CDMX .............. 14 h · $780 (sedán) o $850 (Kangoo) diarios, pago quincenal · sin año mínimo
    Cada una trae su prefiltro POR REGLAS (12 preguntas; jornada, tipos de vehículo y año mínimo de la
    plaza — services/prefiltro_reglas.py), revisión de fotos del vehículo y CV opcional.
    Cada una trae su pieza de Facebook (`publicaciones["facebook"]`: copy + destacados de la imagen); la
    liga única la arma `services/difusion.liga` (`/aplicar/{slug}?origen=facebook`).

Seguridad: sin `--ejecutar` es SIMULACRO (hace todo dentro de una transacción y la deshace). Idempotente:
la Cuenta se reconoce por su slug, los Clientes por nombre, la plantilla por nombre y cada vacante por
Cliente + título + Estado/Municipio; lo existente se ACTUALIZA, nunca se duplica. No envía nada (el alta
de vacante no notifica; la publicación se marca directo en el alta, sin `POST /publicar`).

Uso (desde red-human-api/, con la API arrancada al menos una vez para que exista el administrador):
    python scripts/cargar_demo_seza.py              # simulacro
    python scripts/cargar_demo_seza.py --ejecutar   # aplica
    --admin correo@dominio   administrador que queda como responsable (default: el primero activo)
"""

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:  # la consola de Windows (cp1252) no imprime ✅
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.migraciones import sincronizar  # noqa: E402
from app.models import Cliente, Cuenta, Plantilla, Usuario, UsuarioCuenta, Vacante, registrar  # noqa: E402
from app.routers.plantillas import PlantillaIn, _crear_plantilla  # noqa: E402
from app.routers.vacantes import SEPARADOR_REQUISITOS, CrearIn, _slug_unico, crear  # noqa: E402
from app.seed import slug_cuenta_unico  # noqa: E402
from app.services import difusion, prefiltro_reglas  # noqa: E402

ACTOR = "script:cargar_demo_seza"
SLUG_CUENTA = "grupo-seza"

EMPRESAS = [  # (nombre, color de marca)
    ("SEZA", "#1d4ed8"),  # azul
    ("S", "#dc2626"),     # rojo
    ("G", "#7b1e3a"),     # guinda
]

TITULO = "Chofer de reparto con unidad propia"
NOMBRE_PLANTILLA = TITULO

# Contenido común de la plantilla (condiciones reales por plaza van en cada vacante).
RESPONSABILIDADES = [
    "Recoger la mercancía en tienda o centro de distribución a la hora asignada",
    "Entregar los pedidos en la ruta del día cuidando tiempos y estado del producto",
    "Confirmar cada entrega en la aplicación del smartphone",
    "Mantener la unidad limpia, en buen estado y con documentos vigentes",
]
REQUISITOS_COMUNES = [
    "Licencia de conducir vigente",
    "Tarjeta de circulación vigente",
    "Póliza de seguro vigente del vehículo",
    "Smartphone Android con datos",
    "La unidad no debe ser taxi ni tener cromática de taxi",
]
DESEABLES = ["Experiencia previa en reparto o mensajería", "Conocimiento de las calles de la zona"]
PALABRAS_CLAVE = ["chofer", "reparto", "repartidor", "unidad propia", "auto propio", "entregas"]
DESCRIPCION_PLANTILLA = (
    "Buscamos choferes con vehículo propio para reparto de pedidos a domicilio. Pago por día trabajado; "
    "las condiciones (jornada, sueldo, periodicidad de pago y vehículo aceptado) dependen de la plaza."
)

VACANTES = [
    {
        "plaza": "Puebla",
        "ubicacion_imagen": "Puebla, Puebla",
        "estado": "Puebla",
        "municipio": "Puebla",
        "jornada": "Jornada de 10 horas",
        "reglas": prefiltro_reglas.configuracion(10, [prefiltro_reglas.SEDAN], 2018, ubicacion_texto="Puebla"),
        "desde": 650, "hasta": 650, "periodicidad": "dia_semanal",
        "vehiculo": "Vehículo propio tipo sedán modelo 2018 o más reciente",
        "sueldo_detalle": "$650 por día trabajado, con pago semanal.",
        "destacados": ["Jornada de 10 horas", "Pago semanal", "Sedán 2018 o más reciente"],
    },
    {
        "plaza": "San José del Cabo",
        "ubicacion_imagen": "San José del Cabo, B.C.S.",
        "estado": "Baja California Sur",
        "municipio": "Los Cabos",
        "jornada": "Jornada de 10 horas",
        "reglas": prefiltro_reglas.configuracion(10, [prefiltro_reglas.SEDAN], 2020, ubicacion_texto="San José del Cabo"),
        "desde": 800, "hasta": 800, "periodicidad": "dia_quincenal",
        "vehiculo": "Vehículo propio tipo sedán modelo 2020 o más reciente",
        "sueldo_detalle": "$800 por día trabajado, con pago quincenal.",
        "destacados": ["Jornada de 10 horas", "Pago quincenal", "Sedán 2020 o más reciente"],
    },
    {
        "plaza": "CDMX",
        "ubicacion_imagen": "Ciudad de México",
        "estado": "Ciudad de México",
        "municipio": "",
        "jornada": "Jornada de 14 horas",
        "reglas": prefiltro_reglas.configuracion(14, [prefiltro_reglas.SEDAN, prefiltro_reglas.KANGOO], None, ubicacion_texto="Ciudad de México"),  # sin año mínimo
        "desde": 780, "hasta": 850, "periodicidad": "dia_quincenal",
        "vehiculo": "Vehículo propio: sedán o Kangoo (sin año mínimo)",
        "sueldo_detalle": "$780 por día en sedán o $850 por día en Kangoo, con pago quincenal.",
        "destacados": ["Jornada de 14 horas", "Sedán $780 · Kangoo $850 al día", "Sin año mínimo del vehículo"],
    },
]


def _copy_facebook(d: dict) -> str:
    lineas = [
        "🚚 ¡SEZA está contratando choferes con unidad propia!",
        "",
        f"📍 {d['plaza']}",
        f"💰 {d['sueldo_detalle']}",
        f"⏰ {d['jornada']}",
        f"🚗 {d['vehiculo']}",
        "",
        "Requisitos:",
        *[f"✅ {r}" for r in REQUISITOS_COMUNES],
    ]
    return "\n".join(lineas)


def _descripcion(d: dict) -> str:
    return (
        f"SEZA busca choferes de reparto con unidad propia en {d['plaza']}. {d['jornada']}. "
        f"Sueldo: {d['sueldo_detalle']} Vehículo aceptado: {d['vehiculo'][0].lower()}{d['vehiculo'][1:]}.\n\n"
        "Tu día: recoges la mercancía, haces las entregas de la ruta y confirmas cada una en la aplicación."
    )


def _texto_whatsapp(d: dict) -> str:
    return (
        f"*{TITULO}* — {d['plaza']}\n{d['sueldo_detalle']}\n{d['jornada']}\n{d['vehiculo']}.\n"
        "¿Te interesa? Responde y te hacemos unas preguntas rápidas."
    )


def _admin(db, correo: str) -> Usuario:
    q = db.query(Usuario).filter(Usuario.rol == "Administrador", Usuario.activo.is_(True))
    if correo:
        q = q.filter(Usuario.correo == correo.strip().lower())
    u = q.order_by(Usuario.id).first()
    if not u:
        raise SystemExit("❌ No hay administrador activo. Arranca la API una vez (crea el primero) o revisa --admin.")
    return u


def _cuenta(db, admin: Usuario) -> Cuenta:
    c = db.query(Cuenta).filter(Cuenta.slug == SLUG_CUENTA).first()
    if not c:
        c = Cuenta(nombre="Grupo SEZA", nombre_comercial="Grupo SEZA", razon_social="Grupo SEZA",
                   slug=slug_cuenta_unico(db, "Grupo SEZA"), estado="Activa")
        db.add(c)
        db.flush()
        registrar(db, ACTOR, "cuenta_creada", "cuenta", str(c.id), {"nombre": c.nombre})
        print(f"  + Cuenta «{c.nombre}» (id {c.id}, slug {c.slug})")
    else:
        c.estado = "Activa"
        print(f"  = Cuenta «{c.nombre_visible}» ya existía (id {c.id})")
    if not db.query(UsuarioCuenta).filter_by(usuario_id=admin.id, cuenta_id=c.id).first():
        db.add(UsuarioCuenta(usuario_id=admin.id, cuenta_id=c.id))
        db.flush()
        print(f"  + Acceso de {admin.correo} a la Cuenta")
    return c


def _clientes(db, cuenta: Cuenta) -> dict:
    salida = {}
    for nombre, color in EMPRESAS:
        cl = db.query(Cliente).filter(Cliente.cuenta_id == cuenta.id, Cliente.nombre == nombre).first()
        if not cl:
            cl = Cliente(cuenta_id=cuenta.id, nombre=nombre, nombre_comercial=nombre, razon_social=nombre, color=color)
            db.add(cl)
            db.flush()
            registrar(db, ACTOR, "cliente_creado", "cliente", str(cl.id), {"nombre": nombre, "color": color})
            print(f"  + Empresa {nombre} ({color})")
        else:
            cl.color, cl.estado = color, "Activo"
            print(f"  = Empresa {nombre} ya existía → color {color}")
        salida[nombre] = cl
    return salida


def _plantilla(db, cuenta: Cuenta, admin: Usuario) -> Plantilla:
    datos = PlantillaIn(
        nombre=NOMBRE_PLANTILLA, titulo=TITULO, area="Logística y reparto", modalidad="Presencial",
        seniority="Sin experiencia", descripcion=DESCRIPCION_PLANTILLA,
        resumen="Reparto de pedidos con vehículo propio, pago por día trabajado.",
        requisitos=SEPARADOR_REQUISITOS.join(REQUISITOS_COMUNES), responsabilidades=RESPONSABILIDADES,
        requisitos_deseables=DESEABLES, palabras_clave=PALABRAS_CLAVE,
        # base de la plantilla: cada vacante fija su jornada, tipos de vehículo y año mínimo
        prefiltro_reglas=prefiltro_reglas.configuracion(None, [prefiltro_reglas.SEDAN], None), cv_obligatorio=False,
    )
    p = db.query(Plantilla).filter(Plantilla.cuenta_id == cuenta.id, Plantilla.nombre == NOMBRE_PLANTILLA).first()
    if p:
        for campo, valor in datos.model_dump(exclude={"nombre", "cliente_id"}).items():
            if campo in ("titulo", "area", "descripcion", "resumen", "requisitos", "responsabilidades",
                         "requisitos_deseables", "palabras_clave", "seniority", "prefiltro_reglas", "cv_obligatorio"):
                setattr(p, campo, valor)
        p.activa = True
        print(f"  = Plantilla «{p.nombre}» ya existía → contenido actualizado")
        return p
    p = _crear_plantilla(db, cuenta, admin, datos)
    print(f"  + Plantilla «{p.nombre}» (id {p.id})")
    return p


def _vacante(db, cuenta: Cuenta, admin: Usuario, seza: Cliente, plantilla: Plantilla, d: dict) -> Vacante:
    requisitos = [d["vehiculo"], d["jornada"].replace("Jornada", "Disponibilidad para jornada"), *REQUISITOS_COMUNES]
    facebook = {"titulo": f"{TITULO} — {d['plaza']}", "copy": _copy_facebook(d), "page": _copy_facebook(d),
                "etiquetas": [], "destacados": d["destacados"], "llamado": "Postúlate hoy",
                "ubicacion": d["ubicacion_imagen"]}
    whatsapp = _texto_whatsapp(d)
    publicaciones = {
        "facebook": facebook,
        "whatsapp": {"titulo": TITULO, "copy": whatsapp, "page": whatsapp, "etiquetas": []},
        "portal": {"titulo": f"{TITULO} — {d['plaza']}", "copy": _descripcion(d).split("\n")[0],
                   "page": _descripcion(d), "etiquetas": PALABRAS_CLAVE},
    }
    existente = (
        db.query(Vacante)
        .filter(Vacante.cuenta_id == cuenta.id, Vacante.cliente_id == seza.id, Vacante.titulo == TITULO,
                Vacante.ubicacion_estado == d["estado"], Vacante.ubicacion_municipio == d["municipio"],
                Vacante.estado != "Eliminada")
        .first()
    )
    if existente:
        existente.publicaciones = {**(existente.publicaciones or {}), **publicaciones}
        existente.descripcion = _descripcion(d)
        existente.texto_whatsapp = whatsapp
        existente.prefiltro_reglas = d["reglas"]
        existente.cv_obligatorio = False
        print(f"  = Vacante {existente.codigo} ({d['plaza']}) ya existía → contenido de Facebook actualizado")
        return existente

    datos = CrearIn(
        titulo=TITULO, area=plantilla.area, seniority=plantilla.seniority, modalidad="Presencial",
        ubicacion_estado=d["estado"], ubicacion_municipio=d["municipio"],
        sueldo_desde=d["desde"], sueldo_hasta=d["hasta"], sueldo_moneda="MXN", sueldo_periodicidad=d["periodicidad"],
        requisitos_indispensables=requisitos, requisitos_deseables=DESEABLES, beneficios=[],
        descripcion=_descripcion(d), resumen=f"Chofer con unidad propia en {d['plaza']} · {d['jornada'].lower()}.",
        responsabilidades=RESPONSABILIDADES, palabras_clave=PALABRAS_CLAVE, texto_whatsapp=whatsapp,
        publicaciones=publicaciones, publicar=True, plataformas=["Portal", "WhatsApp"], generar_si_falta=False,
        prefiltro_reglas=d["reglas"], cv_obligatorio=False,
        cliente_id=seza.id, responsable_id=admin.id, mostrar_cliente_candidato=True, plantilla_id=plantilla.id,
    )
    salida = crear(datos=datos, db=db, u=admin, cuenta=cuenta)
    v = db.query(Vacante).filter(Vacante.codigo == salida["id"]).one()
    v.slug = _slug_unico(db, f"{TITULO} {d['plaza']}", v.id)  # liga legible por plaza
    db.flush()
    print(f"  + Vacante {v.codigo} · {d['plaza']} · {v.sueldo} · slug {v.slug}")
    return v


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ejecutar", action="store_true", help="aplica la carga (sin esto es simulacro)")
    ap.add_argument("--admin", default="", help="correo del administrador responsable")
    args = ap.parse_args()

    Base.metadata.create_all(engine)  # base nueva: crea tablas; base existente: no toca nada
    sincronizar(engine)               # columnas nuevas (Cliente.color) sobre una base ya existente

    db = SessionLocal()
    commit_real = db.commit
    if not args.ejecutar:
        db.commit = db.flush  # `crear()` hace commit: en simulacro solo se vuelca a la transacción
    try:
        print("SIMULACRO (nada se guarda)" if not args.ejecutar else "EJECUTANDO carga del ambiente Grupo SEZA")
        admin = _admin(db, args.admin)
        cuenta = _cuenta(db, admin)
        clientes = _clientes(db, cuenta)
        plantilla = _plantilla(db, cuenta, admin)
        vacantes = [_vacante(db, cuenta, admin, clientes["SEZA"], plantilla, d) for d in VACANTES]

        print("\nLigas únicas de Facebook:")
        for v in vacantes:
            print(f"  {v.codigo} · {v.ubicacion:<32} {difusion.liga(v)}")
        registrar(db, ACTOR, "ambiente_seza_cargado", "sistema", "demo-seza",
                  {"cuenta": cuenta.id, "vacantes": [v.codigo for v in vacantes]})
        if args.ejecutar:
            commit_real()
            print(f"\n✅ Listo. Entra con {admin.correo} y cambia a la Cuenta «Grupo SEZA».")
        else:
            db.rollback()
            print("\n✅ Simulacro correcto. Corre con --ejecutar para aplicar.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
