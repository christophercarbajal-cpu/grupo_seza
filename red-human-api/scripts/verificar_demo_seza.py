"""Regresión de la demo Grupo SEZA (puntos 1-8, 2026-09-29) sobre una base DESECHABLE.

Carga el ambiente (`cargar_demo_seza.py`) y comprueba: sueldo por día, pieza de Facebook con liga única
y fuente «Facebook», prefiltro por reglas por la web (reglas distintas por plaza) y por WhatsApp
(cuestionario con repregunta), CV opcional, fotos del vehículo (subida, corrección, aprobación,
excepción), que nadie salga de Prefiltro sin el vehículo aprobado, y el flujo operativo: Kanban de 8 etapas y
sus contadores, sesión de capacitación con cupo, liga del supervisor (Apto / Requiere seguimiento / No apto),
inducción simulada, documentos + 3 referencias contactadas → Listo para alta → Alta realizada.

Uso (desde red-human-api/):  python scripts/verificar_demo_seza.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASE = Path(tempfile.mkdtemp()) / "demo_seza.db"
os.environ["DATABASE_URL"] = f"sqlite:///{BASE.as_posix()}"
os.environ["ADMIN_PASSWORD"] = "Verificar123!"
os.environ["WHATSAPP_PROVIDER"] = ""  # nada sale: modo demo
sys.path.insert(0, str(RAIZ))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

FALLAS = []


def check(cond, nombre):
    print(("✅ " if cond else "❌ ") + nombre)
    if not cond:
        FALLAS.append(nombre)


R_OK = {"municipio": "Puebla", "jornada": "Sí", "experiencia": "No", "vehiculo_propio": "Sí",
        "tipo_vehiculo": "Sedán de cuatro puertas", "anio_vehiculo": "2019", "taxi": "No", "circulacion": "Sí",
        "licencia": "Sí", "poliza": "Sí", "android": "Sí"}
SLUG = "chofer-de-reparto-con-unidad-propia-"
JPG = b"\xff\xd8\xff\xe0" + b"0" * 2000


def main():
    with TestClient(app) as c:  # arranque: crea tablas y administrador
        pass
    salida = subprocess.run([sys.executable, str(RAIZ / "scripts" / "cargar_demo_seza.py"), "--ejecutar"],
                            capture_output=True, text=True, encoding="utf-8", env=os.environ)
    check(salida.returncode == 0, "carga del ambiente SEZA")
    if salida.returncode:
        print(salida.stdout[-2000:], salida.stderr[-2000:])
        return

    with TestClient(app) as c:
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        cuentas = c.get("/auth/yo").json().get("cuentas") or []
        h = {"X-Cuenta-Id": str(next((x["id"] for x in cuentas if "SEZA" in x.get("nombre", "")), 1))}

        vacs = {v["ubicacionEstado"]: v for v in c.get("/vacantes", headers=h).json()}
        check(len(vacs) == 3, "3 vacantes de SEZA")
        check(vacs["Puebla"]["sueldo"] == "$650 MXN diarios, pago semanal", "sueldo por día con pago semanal")
        check(vacs["Puebla"]["clienteColor"] == "#1d4ed8", "color de marca de SEZA")

        fb = c.get(f"/vacantes/{vacs['Ciudad de México']['id']}/facebook", headers=h).json()
        check(fb["liga"].endswith("?origen=facebook") and "Kangoo" in fb["copy"], "pieza de Facebook (copy + liga única)")

        pub = c.get(f"/vacantes/slug/{SLUG}cdmx").json()
        textos = [q["texto"] for q in pub["prefiltroPreguntas"]]
        check("prefiltroReglas" not in pub and len(textos) == 11 and pub["cvObligatorio"] is False,
              "portal: 11 preguntas (sin zona definida se omite la 3), sin reglas expuestas, CV opcional")
        check(textos[1] == "Esta vacante requiere 14 horas de jornada en Ciudad de México. ¿Puedes cubrirla completa?",
              "pregunta de jornada con [horas] y [ubicación] de la vacante")

        def postular(plaza, nombre, tel, **cambios):
            r = c.post("/candidatos/postular", data={"vacante": SLUG + plaza, "nombre": nombre, "telefono": tel, "consentimiento": "true",
                                                     "origen": "facebook", "respuestas_reglas": json.dumps({**R_OK, **cambios})})
            d = r.json()
            return d, c.get(f"/candidatos/{d.get('postulacion')}", headers=h).json()

        d, det = postular("puebla", "Ana Cumple", "2221000001")
        check(det["prefiltroReglas"]["etiqueta"] == "Cumple perfil" and d["vehiculo"], "Puebla sedán 2019 → Cumple perfil + liga de fotos")
        check(det["fuente"] == "Facebook", "fuente Facebook por la liga única")
        ana = d["postulacion"]
        _, det = postular("puebla", "Beto", "2221000002", anio_vehiculo="2015")
        check(det["prefiltroReglas"]["resultado"] == "revision", "Puebla 2015 → Requiere revisión (fuera de parámetro, año mínimo 2018)")
        _, det = postular("san-jose-del-cabo", "Caro", "6241000003", anio_vehiculo="2019")
        check(det["prefiltroReglas"]["resultado"] == "revision", "San José del Cabo 2019 → Requiere revisión (año mínimo 2020)")
        _, det = postular("cdmx", "Dani", "5551000004", tipo_vehiculo="Kangoo", anio_vehiculo="2005")
        check(det["prefiltroReglas"]["resultado"] == "cumple", "CDMX Kangoo 2005 → Cumple (sin año mínimo)")
        _, det = postular("cdmx", "Eli", "5551000005", tipo_vehiculo="Otro")
        check(det["prefiltroReglas"]["resultado"] == "revision", "CDMX «Otro» vehículo → Requiere revisión (solo sedán o Kangoo)")
        _, det = postular("puebla", "Gus", "2221000010", jornada="No")
        check(det["prefiltroReglas"]["resultado"] == "no_cumple", "no cubre la jornada completa → No cumple (no hay medio turno)")
        _, det = postular("puebla", "Ivo", "2221000011", licencia="No")
        check(det["prefiltroReglas"]["resultado"] == "revision", "licencia pendiente → Requiere revisión (documento pendiente ≠ descarte)")
        _, det = postular("puebla", "Jo", "2221000012", taxi="Sí", circulacion="No estoy seguro")
        check(det["prefiltroReglas"]["resultado"] == "revision" and len(det["prefiltroReglas"]["motivos"]) == 2, "taxi «Sí» y circulación «No estoy seguro» → Requiere revisión")
        _, det = postular("puebla", "Kim", "2221000013", vehiculo_propio="No", tipo_vehiculo="", anio_vehiculo="", taxi="", circulacion="", poliza="")
        check(det["prefiltroReglas"]["resultado"] == "no_cumple", "sin vehículo propio → No cumple (indispensable)")
        d, det = postular("cdmx", "Fer", "5551000006", poliza="No")
        check(det["prefiltroReglas"]["resultado"] == "revision" and det["prefiltroReglas"]["siguienteAccion"], "sin póliza → Requiere revisión con siguiente acción")
        fer = d["postulacion"]
        r = c.post("/candidatos/postular", data={"vacante": SLUG + "cdmx", "nombre": "Falta", "telefono": "5551000009", "consentimiento": "true",
                                                 "respuestas_reglas": json.dumps({**R_OK, "licencia": ""})})
        check(r.status_code == 400, "respuestas incompletas → 400")

        # Bloqueo de citación
        check(c.get(f"/candidatos/{ana}", headers=h).json()["etapa"] == "Revisión de vehículo", "Cumple perfil → columna «Revisión de vehículo»")
        r = c.patch(f"/candidatos/{ana}/etapa", json={"etapa": "Cita para capacitación", "manual": True}, headers=h)
        check(r.status_code == 409, "no se puede citar sin vehículo aprobado (ni moviendo a mano)")

        # Fotos
        tok = c.get(f"/candidatos/{ana}/vehiculo", headers=h).json()["vehiculo"]["liga"].rsplit("/", 1)[1]
        for lado in ("frente", "atras", "izquierdo", "derecho"):
            r = c.post(f"/vehiculo/publica/{tok}/foto", data={"lado": lado}, files={"archivo": (f"{lado}.jpg", JPG, "image/jpeg")})
        check(r.json()["estado"] == "por_revisar", "4 fotos → por revisar")
        r = c.post(f"/candidatos/{ana}/vehiculo/decision", json={"accion": "correccion", "comentario": "Atrás borrosa", "lados": ["atras"]}, headers=h)
        check(r.json()["vehiculo"]["estado"] == "correccion", "pedir corrección")
        check(c.post(f"/vehiculo/publica/{tok}/foto", data={"lado": "frente"}, files={"archivo": ("x.jpg", JPG, "image/jpeg")}).status_code == 409,
              "en corrección solo se sube el lado pedido")
        r = c.post(f"/vehiculo/publica/{tok}/foto", data={"lado": "atras"}, files={"archivo": ("x.jpg", JPG, "image/jpeg")})
        check(r.json()["estado"] == "por_revisar", "lado corregido → por revisar")
        r = c.post(f"/candidatos/{ana}/vehiculo/decision", json={"accion": "aprobar"}, headers=h).json()
        check(r["vehiculo"]["puedeCitar"] and r["prefiltro"]["siguienteAccion"].startswith("Listo para citar"), "aprobar vehículo → listo para citar")
        check(c.get(f"/candidatos/{ana}", headers=h).json()["etapa"] == "Cita para capacitación", "vehículo aprobado → «Cita para capacitación»")

        check(c.post(f"/candidatos/{fer}/prefiltro-reglas/aprobar", json={"motivo": " "}, headers=h).status_code == 400, "aprobar prefiltro exige motivo")
        r = c.post(f"/candidatos/{fer}/prefiltro-reglas/aprobar", json={"motivo": "Póliza en trámite"}, headers=h).json()
        check(r["prefiltro"]["resultado"] == "cumple" and r["vehiculo"]["estado"] == "pendiente", "RH aprueba prefiltro → sale liga de fotos")
        check(c.post(f"/candidatos/{fer}/vehiculo/decision", json={"accion": "excepcion"}, headers=h).status_code == 400, "excepción exige motivo")
        r = c.post(f"/candidatos/{fer}/vehiculo/decision", json={"accion": "excepcion", "comentario": "Revisado en persona"}, headers=h).json()
        check(r["vehiculo"]["puedeCitar"], "excepción con motivo → se puede citar")

        _flujo_operativo(c, h, ana, fer)

    asyncio.run(_whatsapp())


def _flujo_operativo(c, h, ana, fer):
    from collections import Counter

    fl = c.get("/candidatos-flujo", headers=h).json()
    check(fl["flujo"] == "operativo" and fl["etapas"][0] == "Nuevo" and fl["etapas"][-1] == "Alta realizada" and len(fl["etapas"]) == 8,
          "Kanban operativo de 8 etapas (Nuevo → Alta realizada)")
    tarjetas = c.get("/candidatos", headers=h).json()
    lista = tarjetas if isinstance(tarjetas, list) else tarjetas.get("candidatos", [])
    por_etapa = Counter(t["etapa"] for t in lista)
    minimos = {"Nuevo": 3, "Prefiltro": 4, "Revisión de vehículo": 4, "Cita para capacitación": 4, "Capacitación realizada": 3,
               "Documentos y referencias": 3, "Listo para alta": 2, "Alta realizada": 2}
    check(all(por_etapa.get(e, 0) >= n for e, n in minimos.items()), f"candidatos ficticios en las 8 columnas {dict(por_etapa)}")
    vacs = c.get("/vacantes", headers=h).json()
    suma_vacantes = Counter()
    for v in vacs:
        for e, n in ((v.get("embudo") or {}).get("etapas") or {}).items():
            suma_vacantes[e] += n
    check(all(suma_vacantes.get(e, 0) == por_etapa.get(e, 0) for e in minimos), "contadores de las vacantes = columnas del Kanban")

    # Sesión con cupo 1 (Puebla) → citar a Ana; Fer (CDMX, vehículo por excepción) ya no cabe
    puebla = next(v for v in vacs if v["ubicacionEstado"] == "Puebla")
    s = c.post("/sesiones-capacitacion", json={"tienda": "Tienda prueba", "inicio": "2030-01-15T09:00", "cupo": 1,
                                              "supervisor_nombre": "Sup Prueba", "vacante": puebla["id"]}, headers=h).json()
    r = c.post(f"/candidatos/{ana}/operativo/citar", json={"sesion": s["codigo"]}, headers=h)
    check(r.status_code == 200 and r.json()["capacitacion"]["nombre"] == "Capacitación en tienda", "citar a sesión compartida (evaluación «Otra» · Capacitación en tienda)")
    r = c.post(f"/candidatos/{fer}/operativo/citar", json={"sesion": s["codigo"]}, headers=h)
    check(r.status_code == 409 and "cupo" in r.json()["detail"], "la sesión respeta el cupo")
    evs = c.get(f"/evaluaciones/postulaciones/{ana}", headers=h).json()
    lista_ev = evs if isinstance(evs, list) else evs.get("evaluaciones", [])
    check(any(e.get("tipo") == "otra" and e.get("nombre") == "Capacitación en tienda" for e in lista_ev), "aparece en Evaluaciones como tipo «Otra»")

    # Inducción SEZA: duplicada y enviada (simulada) al confirmar la cita
    cursos = c.get("/capacitacion", headers=h).json()
    lista_cursos = cursos if isinstance(cursos, list) else cursos.get("cursos", [])
    induccion = next((x for x in lista_cursos if x.get("titulo") == "Inducción SEZA"), None)
    check(induccion is not None, "curso «Inducción SEZA» duplicado de un curso existente")
    c.patch(f"/sesiones-capacitacion/{s['codigo']}", json={"tienda": "Tienda prueba", "inicio": "2030-01-15T09:00", "cupo": 1,
                                                          "supervisor_nombre": "Sup Prueba", "vacante": puebla["id"], "curso_induccion": induccion["id"]}, headers=h)
    r = c.post(f"/candidatos/{ana}/operativo/confirmar-cita", headers=h).json()
    check(r["capacitacion"]["confirmada"] and r["induccion"] and r["induccion"]["simulado"], "confirmar cita → PDF de inducción (simulado)")
    msgs = c.get(f"/candidatos/{ana}/mensajes", headers=h).json()
    lista_m = msgs if isinstance(msgs, list) else msgs.get("mensajes", [])
    check(any("[Simulado" in (m.get("texto") or "") and "Inducción SEZA" in (m.get("texto") or "") for m in lista_m), "el envío simulado queda en el chat de WhatsApp")

    # Liga del supervisor
    token = s["ligaSupervisor"].rsplit("/", 1)[1]
    pub = c.get(f"/sesiones-capacitacion/publica/{token}").json()
    check([x["nombre"] for x in pub["citados"]] == ["Ana Cumple"] and "telefono" not in pub["citados"][0], "el supervisor ve a sus citados (sin datos de contacto)")
    ev = pub["citados"][0]["evaluacion"]
    check(c.post(f"/sesiones-capacitacion/publica/{token}/asistencia", json={"evaluacion": ev, "asistio": True, "resultado": "con_observaciones"}).status_code == 400,
          "«Requiere seguimiento» exige comentario")
    c.post(f"/sesiones-capacitacion/publica/{token}/asistencia", json={"evaluacion": ev, "asistio": True, "resultado": "con_observaciones", "comentario": "Reforzar uso de la app"})
    panel = c.get(f"/candidatos/{ana}/operativo", headers=h).json()
    check(panel["etapa"] == "Capacitación realizada" and panel["capacitacion"]["resultadoEtiqueta"] == "Requiere seguimiento"
          and panel["capacitacion"]["dictamenInterno"] == "Con observaciones", "asistencia → «Capacitación realizada», Requiere seguimiento = Con observaciones")
    check(c.patch(f"/candidatos/{ana}/etapa", json={"etapa": "Listo para alta", "manual": True}, headers=h).status_code == 409, "no se brinca a «Listo para alta»")

    # Documentos + 3 referencias
    r = c.post(f"/candidatos/{ana}/operativo/solicitar-documentos", headers=h).json()
    check(r["etapa"] == "Documentos y referencias" and len(r["expediente"]["documentos"]) >= 9, "pedir documentos y referencias → columna y expediente de chofer")
    tok = r["liga"].rsplit("/", 1)[1]
    pub = c.get(f"/expedientes/publica/{tok}").json()
    check(pub["pideReferencias"] and pub["referenciasRequeridas"] == 3, "la liga del expediente pide 3 referencias")
    refs = [{"nombre": "Ref Uno", "telefono": "5511111111", "parentesco": "Familiar"}, {"nombre": "Ref Dos", "telefono": "5522222222", "parentesco": "Amistad"}]
    check(c.post(f"/expedientes/publica/{tok}/referencias", json={"referencias": refs}).status_code == 400, "exige exactamente 3 referencias")
    refs.append({"nombre": "Ref Tres", "telefono": "5533333333", "parentesco": "Exjefe o excompañero"})
    check(c.post(f"/expedientes/publica/{tok}/referencias", json={"referencias": refs}).status_code == 200, "el candidato captura sus 3 referencias")
    pdf = b"%PDF-1.4\n" + b"0" * 900

    def estado_doc(tipo):
        p_ = c.get(f"/candidatos/{ana}/operativo", headers=h).json()
        return next(x["estadoSimple"] for x in p_["expediente"]["documentos"] if x["tipo"] == tipo)

    # Estados del documento: Pendiente → Recibido → Requiere corrección (motivo + WhatsApp) → Recibido → Revisado
    ine = "Identificación oficial (INE)"
    check(estado_doc(ine) == "Pendiente", "documento sin archivo → «Pendiente»")
    c.post(f"/expedientes/publica/{tok}/documentos", data={"tipo": ine}, files={"archivo": ("ine.pdf", pdf, "application/pdf")})
    check(estado_doc(ine) == "Recibido", "el candidato lo sube → «Recibido» (falta revisión de RH)")
    check(c.post(f"/candidatos/{ana}/operativo/documentos", json={"tipo": ine, "estado": "rechazado"}, headers=h).status_code == 400,
          "pedir corrección exige motivo")
    r_corr = c.post(f"/candidatos/{ana}/operativo/documentos", json={"tipo": ine, "estado": "rechazado", "notas": "Falta el reverso"}, headers=h).json()
    msgs = c.get(f"/candidatos/{ana}/mensajes", headers=h).json()
    lista_m = msgs if isinstance(msgs, list) else msgs.get("mensajes", [])
    doc_pub = next(x for x in c.get(f"/expedientes/publica/{tok}").json()["documentos"] if x["tipo"] == ine)
    check(estado_doc(ine) == "Requiere corrección" and r_corr["whatsapp"] is not None
          and any("requiere corrección: Falta el reverso" in (m.get("texto") or "") for m in lista_m)
          and doc_pub["motivo"] == "Falta el reverso", "pedir corrección → «Requiere corrección», aviso por WhatsApp y motivo en la liga")
    c.post(f"/expedientes/publica/{tok}/documentos", data={"tipo": ine}, files={"archivo": ("ine2.pdf", pdf, "application/pdf")})
    check(estado_doc(ine) == "Recibido", "lo vuelve a subir → «Recibido» otra vez")
    c.post(f"/candidatos/{ana}/operativo/documentos", json={"tipo": ine, "estado": "aprobado"}, headers=h)
    check(estado_doc(ine) == "Revisado", "RH lo revisa → «Revisado»")

    # Modo Prueba en el flujo operativo: omite la IA pero NO auto-aprueba (RH opera la revisión a mano)
    from app.database import SessionLocal
    from app.services.configuracion import obtener as _cfg_obtener

    db = SessionLocal()
    cfg = _cfg_obtener(db)
    cfg.modo_prueba = True
    db.commit()
    lic = "Licencia de conducir vigente"
    c.post(f"/expedientes/publica/{tok}/documentos", data={"tipo": lic}, files={"archivo": ("lic.pdf", pdf, "application/pdf")})
    check(estado_doc(lic) == "Recibido", "Modo Prueba (flujo operativo): el documento subido queda «Recibido», no se auto-aprueba")
    cfg.modo_prueba = False
    db.commit()
    db.close()

    for d in r["expediente"]["documentos"]:
        if d["tipo"] == ine:
            continue
        c.post(f"/expedientes/publica/{tok}/documentos", data={"tipo": d["tipo"]}, files={"archivo": ("doc.pdf", pdf, "application/pdf")})
        c.post(f"/candidatos/{ana}/operativo/documentos", json={"tipo": d["tipo"], "estado": "aprobado"}, headers=h)
    panel = c.get(f"/candidatos/{ana}/operativo", headers=h).json()
    check(all(x["estadoSimple"] == "Revisado" for x in panel["expediente"]["documentos"]), "los 9 documentos del chofer quedan «Revisado»")
    check(panel["etapa"] == "Documentos y referencias" and any("Referencias por contactar" in f for f in panel["faltantesAlta"]),
          "con documentos aprobados aún faltan las referencias contactadas")

    # Registro manual de llamadas: fecha, contactada, resultado, observaciones
    url_ref = f"/candidatos/{ana}/operativo/referencias/0"
    check(c.post(url_ref, json={"contactada": True, "resultado": "No contestó"}, headers=h).status_code == 400,
          "llamada: el resultado debe corresponder a si se contactó")
    check(c.post(url_ref, json={"contactada": True, "resultado": "Favorable", "fecha": "2099-01-01T10:00"}, headers=h).status_code == 400,
          "llamada: la fecha no puede ser futura")
    panel = c.post(url_ref, json={"contactada": False, "resultado": "No contestó", "fecha": "2026-09-29T10:15", "nota": "Buzón"}, headers=h).json()
    ref0 = panel["expediente"]["referencias"][0]
    check(not ref0["contactada"] and ref0["resultado"] == "No contestó" and len(ref0["llamadas"]) == 1 and panel["etapa"] == "Documentos y referencias",
          "llamada sin contacto: queda registrada y la referencia sigue por contactar")
    panel = c.post(url_ref, json={"contactada": True, "resultado": "Favorable", "fecha": "2026-09-29T12:40", "nota": "Lo recomienda"}, headers=h).json()
    ref0 = panel["expediente"]["referencias"][0]
    check(ref0["contactada"] and [x["resultado"] for x in ref0["llamadas"]] == ["No contestó", "Favorable"]
          and ref0["llamadas"][1]["fecha"].startswith("2026-09-29T12:40") and ref0["llamadas"][1]["observaciones"] == "Lo recomienda"
          and ref0["llamadas"][1]["usuario"], "segunda llamada contactada: historial con fecha, resultado, observaciones y quién llamó")
    for i in (1, 2):
        panel = c.post(f"/candidatos/{ana}/operativo/referencias/{i}", json={"contactada": True, "resultado": "Favorable", "nota": "OK"}, headers=h).json()
    check(panel["etapa"] == "Listo para alta" and panel["listoParaAlta"], "3 referencias contactadas → «Listo para alta» automático")
    panel = c.post(f"/candidatos/{ana}/operativo/alta", headers=h).json()
    check(panel["etapa"] == "Alta realizada" and panel["alta"]["colaborador"], "registrar alta → «Alta realizada» + colaborador")
    check(c.get(f"/candidatos/{ana}", headers=h).json()["activa"] is True, "la tarjeta sigue en el Kanban (cuenta en «Alta realizada»)")


async def _whatsapp():
    from app.database import SessionLocal
    from app.models import Vacante
    from app.routers.candidatos import _crear_candidato, postulacion_para_vacante, procesar_prefiltro

    db = SessionLocal()
    v = db.query(Vacante).filter(Vacante.slug == SLUG + "cdmx").one()
    persona = _crear_candidato(db, v.cuenta_id, "Hugo WhatsApp", "WhatsApp", False)
    p, _ = postulacion_para_vacante(db, persona, v, v.cuenta_id, "whatsapp", consentimiento=True)
    db.commit()
    guion = ["Me interesa", "Iztapalapa", "si", "claro", "Sí", "tengo una kangoo", "no sé", "modelo 09", "nel", "no sé", "si", "no tengo", "sí"]
    ultima = {}
    for t in guion:
        ultima = await procesar_prefiltro(db, p, t, "whatsapp")
    db.refresh(p)
    ev = (p.analisis or {}).get("prefiltro_reglas", {}).get("evaluacion", {})
    check(p.prefiltro_completo and p.estado == "revision" and {m["id"] for m in ev.get("motivos", [])} == {"circulacion", "poliza"},
          "WhatsApp: preguntas con repregunta → Requiere revisión (circulación dudosa + póliza pendiente)")
    check(ultima.get("clasificacion", {}).get("etiqueta") == "Requiere revisión", "WhatsApp: cierre con etiqueta")
    db.close()


# ------------------------------------------------------------ 2026-09-30: punta a punta por WhatsApp


async def _whatsapp_por_plaza(nombre: str, plaza: str, cambios: dict):
    """Contesta el cuestionario completo por WhatsApp; regresa (codigo, respuestas del bot, postulación)."""
    from app.database import SessionLocal
    from app.models import Vacante
    from app.routers.candidatos import _crear_candidato, postulacion_para_vacante, procesar_prefiltro
    from app.services import prefiltro_reglas as pr

    db = SessionLocal()
    v = db.query(Vacante).filter(Vacante.slug == SLUG + plaza).one()
    persona = _crear_candidato(db, v.cuenta_id, nombre, "WhatsApp", False)
    p, _ = postulacion_para_vacante(db, persona, v, v.cuenta_id, "whatsapp", consentimiento=True)
    db.commit()
    base = {"municipio": "Puebla", "jornada": "sí", "zona": "sí", "experiencia": "sí", "vehiculo_propio": "sí",
            "tipo_vehiculo": "1", "anio_vehiculo": "2019", "taxi": "no", "circulacion": "1", "licencia": "si",
            "poliza": "si", "android": "si", **cambios}
    ids = [q["id"] for q in pr.preguntas(v.prefiltro_reglas)]
    salidas = [(await procesar_prefiltro(db, p, "Me interesa la vacante", "whatsapp"))["respuesta"]]
    for pid in ids:
        salidas.append((await procesar_prefiltro(db, p, base[pid], "whatsapp"))["respuesta"])
    db.refresh(p)
    return db, p, ids, salidas, v


async def _whatsapp_completo():
    from app.services import prefiltro_reglas as pr

    # Orden de las preguntas + «Cumple perfil» → columna «Revisión de vehículo» con liga de fotos
    db, p, ids, salidas, v = await _whatsapp_por_plaza("Lalo WhatsApp", "puebla", {})
    textos = [q["texto"] for q in pr.preguntas(v.prefiltro_reglas)]
    en_orden = all(textos[i] in salidas[i] and f"*{i + 1}/{len(ids)}*" in salidas[i] for i in range(len(ids)))
    check(en_orden and len(ids) >= 11, f"WhatsApp: las {len(ids)} preguntas del documento salen en orden, una por mensaje")
    check(p.estado == "cumple" and p.etapa == "Revisión de vehículo" and p.revision_vehiculo is not None
          and "/vehiculo/" in salidas[-1], "WhatsApp: «Cumple perfil» → «Revisión de vehículo» + liga de fotos")
    cumple = p.codigo
    db.close()

    # Vehículo fuera de parámetro → «Requiere revisión» con su motivo; se queda en Prefiltro para RH
    db, p, *_ = await _whatsapp_por_plaza("Memo WhatsApp", "puebla", {"anio_vehiculo": "2015"})
    ev = (p.analisis or {}).get("prefiltro_reglas", {}).get("evaluacion", {})
    check(p.estado == "revision" and ev.get("etiqueta") == "Requiere revisión" and p.etapa == "Prefiltro"
          and [m["id"] for m in ev.get("motivos", [])] == ["anio_vehiculo"],
          "WhatsApp: modelo 2015 en Puebla → «Requiere revisión» (motivo año del vehículo), sigue en Prefiltro")
    db.close()

    db, p, *_ = await _whatsapp_por_plaza("Nico WhatsApp", "cdmx", {"tipo_vehiculo": "un tsuru"})
    ev = (p.analisis or {}).get("prefiltro_reglas", {}).get("evaluacion", {})
    check(p.estado == "revision" and [m["id"] for m in ev.get("motivos", [])] == ["tipo_vehiculo"],
          "WhatsApp: «un tsuru» en CDMX → «Otro» → «Requiere revisión» (motivo tipo de vehículo)")
    db.close()
    return cumple


async def _whatsapp_confirma(codigo: str, texto: str) -> str:
    from app.database import SessionLocal
    from app.models import Postulacion
    from app.routers.candidatos import procesar_prefiltro

    db = SessionLocal()
    p = db.query(Postulacion).filter(Postulacion.codigo == codigo).one()
    r = await procesar_prefiltro(db, p, texto, "whatsapp")
    db.close()
    return r["respuesta"]


def _capacitacion_y_contadores(cumple: str):
    from collections import Counter
    from unittest import mock

    with TestClient(app) as c:
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        cuentas = c.get("/auth/yo").json().get("cuentas") or []
        h = {"X-Cuenta-Id": str(next((x["id"] for x in cuentas if "SEZA" in x.get("nombre", "")), 1))}

        def conteos():
            t = c.get("/candidatos", headers=h).json()
            kanban = Counter(x["etapa"] for x in (t if isinstance(t, list) else t.get("candidatos", [])))
            vac = Counter()
            for v in c.get("/vacantes", headers=h).json():
                vac.update((v.get("embudo") or {}).get("etapas") or {})
            return kanban, vac

        vacs = c.get("/vacantes", headers=h).json()
        puebla = next(v for v in vacs if v["ubicacionEstado"] == "Puebla")
        cursos = c.get("/capacitacion", headers=h).json()
        induccion = next(x for x in (cursos if isinstance(cursos, list) else cursos.get("cursos", [])) if x.get("titulo") == "Inducción SEZA")
        s = c.post("/sesiones-capacitacion", json={"tienda": "Tienda WA", "inicio": "2030-02-01T09:00", "cupo": 5, "supervisor_nombre": "Sup WA",
                                                  "vacante": puebla["id"], "curso_induccion": induccion["id"]}, headers=h).json()

        k0, v0 = conteos()
        r = c.post(f"/candidatos/{cumple}/vehiculo/decision", json={"accion": "excepcion", "comentario": "Revisado en persona"}, headers=h)
        check(r.status_code == 200 and r.json()["vehiculo"]["puedeCitar"], "vehículo del candidato de WhatsApp aprobado por excepción")
        c.post(f"/candidatos/{cumple}/operativo/citar", json={"sesion": s["codigo"]}, headers=h)
        k1, v1 = conteos()
        check(k1["Revisión de vehículo"] == k0["Revisión de vehículo"] - 1 and k1["Cita para capacitación"] == k0["Cita para capacitación"] + 1
              and v1 == k1, "contadores: la tarjeta pasa de «Revisión de vehículo» a «Cita» y Kanban = vacantes")

        # El candidato confirma con «Sí» por WhatsApp → PDF de Inducción SEZA (simulado) y descargable
        resp = asyncio.run(_whatsapp_confirma(cumple, "Sí, ahí estaré"))
        check("confirmada" in resp and "material de inducción" in resp, "WhatsApp «Sí» confirma la cita y avisa del material de inducción")
        panel = c.get(f"/candidatos/{cumple}/operativo", headers=h).json()
        msgs = c.get(f"/candidatos/{cumple}/mensajes", headers=h).json()
        liga = next((m["texto"].rsplit(" ", 1)[1] for m in (msgs if isinstance(msgs, list) else msgs.get("mensajes", []))
                     if "[Simulado" in (m.get("texto") or "")), "")
        pdf = c.get(f"/capacitacion/publica/{liga.rsplit('/', 1)[1]}/pdf") if liga else None
        check(panel["capacitacion"]["confirmada"] and pdf is not None and pdf.status_code == 200
              and pdf.content[:4] == b"%PDF", "el PDF de «Inducción SEZA» se descarga desde la liga enviada")

        # Supervisor: asistencia + resultado → «Capacitación realizada» y contadores al día
        token = s["ligaSupervisor"].rsplit("/", 1)[1]
        ev = next(x["evaluacion"] for x in c.get(f"/sesiones-capacitacion/publica/{token}").json()["citados"] if x["nombre"] == "Lalo WhatsApp")
        r = c.post(f"/sesiones-capacitacion/publica/{token}/asistencia", json={"evaluacion": ev, "asistio": True, "resultado": "favorable"})
        k2, v2 = conteos()
        check(r.status_code == 200 and k2["Cita para capacitación"] == k1["Cita para capacitación"] - 1
              and k2["Capacitación realizada"] == k1["Capacitación realizada"] + 1 and v2 == k2,
              "supervisor registra «Apto» → «Capacitación realizada»; contadores se recalculan")

        # Si la inducción truena, la cita se confirma igual y el supervisor puede capturar (no bloquea)
        otro = next(x["id"] for x in c.get("/candidatos", headers=h).json() if x["etapa"] == "Revisión de vehículo")
        c.post(f"/candidatos/{otro}/vehiculo/decision", json={"accion": "excepcion", "comentario": "Prueba"}, headers=h)
        c.post(f"/candidatos/{otro}/operativo/citar", json={"sesion": s["codigo"]}, headers=h)
        with mock.patch("app.routers.capacitacion.asignar_a_postulacion", side_effect=RuntimeError("falla simulada")):
            r = c.post(f"/candidatos/{otro}/operativo/confirmar-cita", headers=h)
        check(r.status_code == 200 and r.json()["capacitacion"]["confirmada"] and r.json()["induccion"] is None,
              "si falla el PDF de inducción, la cita queda confirmada igual")
        nombre = c.get(f"/candidatos/{otro}", headers=h).json()["nombre"]
        ev = next(x["evaluacion"] for x in c.get(f"/sesiones-capacitacion/publica/{token}").json()["citados"] if x["nombre"] == nombre)
        r = c.post(f"/sesiones-capacitacion/publica/{token}/asistencia", json={"evaluacion": ev, "asistio": False, "comentario": "No llegó"})
        check(r.status_code == 200 and c.get(f"/candidatos/{otro}", headers=h).json()["etapa"] == "Cita para capacitación",
              "«No asistió» deja la tarjeta en «Cita» para reprogramar")


if __name__ == "__main__":
    main()
    if not FALLAS:
        _capacitacion_y_contadores(asyncio.run(_whatsapp_completo()))
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
