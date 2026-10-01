"""Regresión de la demo Grupo SEZA (flujo operativo v2, 2026-09-30) sobre una base DESECHABLE.

Carga el ambiente (`cargar_demo_seza.py`) y comprueba: sueldo por día, pieza de Facebook con liga única y fuente
«Facebook», prefiltro por reglas por la web (reglas distintas por plaza) y por chat (cuestionario con repregunta),
CV opcional, revisión del vehículo (4 fotos + licencia, tarjeta y póliza; corrección, aprobación, excepción), que
nadie pase a Entrevista sin el vehículo aprobado, y el flujo operativo de 6 columnas: subestado del Prefiltro,
contadores, capacitación en tienda sobre la entrevista humana (sin cupos; envío aparte; liga del capacitador y
captura manual de RH), inducción, condiciones + tipos de contratación + contrato ahora/después, Onboarding con 6
documentos + 3 referencias (registro de llamadas) y «Dar de alta» que cierra el proceso.

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
        r = c.patch(f"/candidatos/{ana}/etapa", json={"etapa": "Entrevista", "manual": True}, headers=h)
        check(r.status_code == 409, "no se puede pasar a Entrevista sin vehículo aprobado (ni moviendo a mano)")

        # Fotos + documentos del vehículo
        veh = c.get(f"/candidatos/{ana}/vehiculo", headers=h).json()["vehiculo"]
        tok = veh["liga"].rsplit("/", 1)[1]
        check([d["clave"] for d in veh["documentos"]] == ["licencia", "tarjeta", "poliza"],
              "el vehículo pide licencia, tarjeta de circulación y póliza (sin comprobante de propiedad)")
        for lado in ("frente", "atras", "izquierdo", "derecho"):
            r = c.post(f"/vehiculo/publica/{tok}/foto", data={"lado": lado}, files={"archivo": (f"{lado}.jpg", JPG, "image/jpeg")})
        check(r.json()["estado"] == "pendiente" and all(d["pendiente"] for d in r.json()["documentos"]), "4 fotos sin documentos → sigue pendiente")
        check(c.post(f"/candidatos/{ana}/vehiculo/decision", json={"accion": "aprobar"}, headers=h).status_code == 409,
              "no se aprueba el vehículo sin los 3 documentos")
        for clave in ("licencia", "tarjeta", "poliza"):
            r = c.post(f"/vehiculo/publica/{tok}/documento", data={"clave": clave}, files={"archivo": (f"{clave}.pdf", PDF, "application/pdf")})
        check(r.json()["estado"] == "por_revisar", "4 fotos + 3 documentos → por revisar")
        r = c.post(f"/candidatos/{ana}/vehiculo/decision", json={"accion": "correccion", "comentario": "Atrás borrosa y póliza vencida", "lados": ["atras", "poliza"]}, headers=h)
        check(r.json()["vehiculo"]["estado"] == "correccion", "pedir corrección de una foto y un documento")
        pub = c.get(f"/vehiculo/publica/{tok}").json()
        pol = next(d for d in pub["documentos"] if d["clave"] == "poliza")
        check(pol["pendiente"] and pol["estado"] == "Requiere corrección" and pol["motivo"], "la liga muestra la póliza «Requiere corrección» con el motivo")
        check(c.post(f"/vehiculo/publica/{tok}/foto", data={"lado": "frente"}, files={"archivo": ("x.jpg", JPG, "image/jpeg")}).status_code == 409,
              "en corrección solo se sube lo pedido")
        c.post(f"/vehiculo/publica/{tok}/foto", data={"lado": "atras"}, files={"archivo": ("x.jpg", JPG, "image/jpeg")})
        r = c.post(f"/vehiculo/publica/{tok}/documento", data={"clave": "poliza"}, files={"archivo": ("poliza2.pdf", PDF, "application/pdf")})
        check(r.json()["estado"] == "por_revisar", "foto y documento corregidos → por revisar")
        r = c.post(f"/candidatos/{ana}/vehiculo/decision", json={"accion": "aprobar"}, headers=h).json()
        check(r["vehiculo"]["puedeCitar"] and all(d["estadoSimple"] == "Revisado" for d in r["vehiculo"]["documentos"]),
              "aprobar vehículo → los 3 documentos quedan «Revisado» y ya se puede citar")
        check(c.get(f"/candidatos/{ana}", headers=h).json()["etapa"] == "Entrevista", "vehículo aprobado → «Entrevista»")

        check(c.post(f"/candidatos/{fer}/prefiltro-reglas/aprobar", json={"motivo": " "}, headers=h).status_code == 400, "aprobar prefiltro exige motivo")
        r = c.post(f"/candidatos/{fer}/prefiltro-reglas/aprobar", json={"motivo": "Póliza en trámite"}, headers=h).json()
        check(r["prefiltro"]["resultado"] == "cumple" and r["vehiculo"]["estado"] == "pendiente", "RH aprueba prefiltro → sale liga del vehículo")
        check(c.post(f"/candidatos/{fer}/vehiculo/decision", json={"accion": "excepcion"}, headers=h).status_code == 400, "excepción exige motivo")
        r = c.post(f"/candidatos/{fer}/vehiculo/decision", json={"accion": "excepcion", "comentario": "Revisado en persona"}, headers=h).json()
        check(r["vehiculo"]["puedeCitar"], "excepción con motivo → se puede citar")

        _flujo_operativo(c, h, ana, fer)

    asyncio.run(_whatsapp())


PDF = b"%PDF-1.4\n" + b"0" * 900


def _flujo_operativo(c, h, ana, fer):
    from collections import Counter

    fl = c.get("/candidatos-flujo", headers=h).json()
    check(fl["flujo"] == "operativo" and fl["etapas"] == ["Prefiltro", "Revisión de vehículo", "Entrevista", "Evaluación", "Contratación", "Onboarding"],
          "Kanban operativo de 6 columnas (Prefiltro → Onboarding)")
    tarjetas = c.get("/candidatos", headers=h).json()
    lista = tarjetas if isinstance(tarjetas, list) else tarjetas.get("candidatos", [])
    por_etapa = Counter(t["etapa"] for t in lista)
    minimos = {"Prefiltro": 7, "Revisión de vehículo": 4, "Entrevista": 6, "Evaluación": 2, "Contratación": 2, "Onboarding": 3}
    check(all(por_etapa.get(e, 0) >= n for e, n in minimos.items()) and set(por_etapa) <= set(minimos),
          f"candidatos ficticios solo en las 6 columnas {dict(por_etapa)}")
    sub = Counter((t.get("operativo") or {}).get("texto") for t in lista if t["etapa"] == "Prefiltro")
    check(sub["Sin iniciar"] >= 3 and sub["En curso"] >= 1 and sub["Completado"] >= 3
          and {(t.get("operativo") or {}).get("filtro") for t in lista if t["etapa"] == "Prefiltro"} == {"sin_iniciar", "en_curso", "completado"},
          f"Prefiltro filtrable por Sin iniciar / En curso / Completado {dict(sub)}")
    filtros_ent = Counter((t.get("operativo") or {}).get("filtro") for t in lista if t["etapa"] == "Entrevista")
    check(set(filtros_ent) >= {"sin_agendar", "agendada", "confirmada", "realizada"},
          f"Entrevista filtrable por Sin agendar / Agendada / Confirmada / Realizada / No asistió {dict(filtros_ent)}")
    completados = [t for t in lista if (t.get("operativo") or {}).get("texto") == "Completado"]
    check({t["prefiltroReglas"]["resultado"] for t in completados} >= {"revision", "no_cumple"}, "el resultado del prefiltro se muestra aparte del subestado")
    cerradas = c.get("/candidatos?mostrar_cerradas=true", headers=h).json()
    lista_c = cerradas if isinstance(cerradas, list) else cerradas.get("candidatos", [])
    check(any(t["nombre"] == "Tomás Guerrero Álvarez" and t["activa"] is False and t["motivoCierre"] == "contratado" for t in lista_c),
          "el candidato dado de alta queda CERRADO como contratado (se ve con «Mostrar cerradas»)")
    vacs = c.get("/vacantes", headers=h).json()
    suma_vacantes = Counter()
    for v in vacs:
        for e, n in ((v.get("embudo") or {}).get("etapas") or {}).items():
            suma_vacantes[e] += n
    check(all(suma_vacantes.get(e, 0) == por_etapa.get(e, 0) for e in minimos), "contadores de las vacantes = columnas del Kanban")

    # Entrevista = capacitación en tienda (sin grupos ni cupos)
    cursos = c.get("/capacitacion", headers=h).json()
    induccion = next((x for x in (cursos if isinstance(cursos, list) else cursos.get("cursos", [])) if x.get("titulo") == "Inducción SEZA"), None)
    check(induccion is not None, "curso «Inducción SEZA» duplicado de un curso existente")
    cita = {"tienda": "Tienda prueba", "direccion": "Av. Prueba 1", "fecha": "2030-01-15", "hora": "09:00", "capacitador_tipo": "externo",
            "capacitador_nombre": "Capacitador Prueba", "curso_induccion": induccion["id"], "indicaciones": "Llega 15 min antes"}
    check(c.post(f"/candidatos/{ana}/operativo/entrevista", json={**cita, "tienda": ""}, headers=h).status_code == 400, "la cita exige tienda")
    r = c.post(f"/candidatos/{ana}/operativo/entrevista", json=cita, headers=h)
    d = r.json()
    check(r.status_code == 200 and d["entrevista"]["tienda"] == "Tienda prueba" and d["entrevista"]["capacitador"]["nombre"] == "Capacitador Prueba"
          and d["entrevista"]["estado"] == "Agendada", "programar capacitación: tienda, fecha/hora y capacitador")
    check(d["induccionEnviada"] and d["induccionEnviada"]["simulado"], "al agendar sale el material de inducción (PDF; simulado sin Telegram)")
    check(d["envioCandidato"]["enviado"] is False and d["envioCapacitador"][0]["enviado"] is False and d["entrevista"]["ligaCapacitador"],
          "el envío va por separado: aunque no salga, la cita y la liga del capacitador quedan creadas")
    r = c.post(f"/candidatos/{fer}/operativo/entrevista", json=cita, headers=h)
    check(r.status_code == 200, "otra cita en la misma tienda y hora: sin cupos")
    r = c.post(f"/candidatos/{ana}/operativo/confirmar-cita", headers=h).json()
    check(r["entrevista"]["confirmada"] and r["entrevista"]["estado"] == "Confirmada" and r["induccionEnviada"] is None,
          "confirmar la cita no vuelve a mandar el PDF (ya salió al agendar)")
    msgs = c.get(f"/candidatos/{ana}/mensajes", headers=h).json()
    lista_m = msgs if isinstance(msgs, list) else msgs.get("mensajes", [])
    check(any("[Simulado" in (m.get("texto") or "") and "Inducción SEZA" in (m.get("texto") or "") for m in lista_m), "el envío simulado queda en el chat")

    # Liga del capacitador (misma liga de la entrevista humana)
    token = r["entrevista"]["ligaCapacitador"].rsplit("/", 1)[1]
    pub = c.get(f"/entrevista-humana/publica/{token}").json()
    check(pub["tipo"] == "capacitacion" and pub["tienda"] == "Tienda prueba" and "telefono" not in pub, "el capacitador ve la capacitación (sin datos de contacto)")
    check(c.post(f"/entrevista-humana/publica/{token}/capacitacion", json={"asistio": True, "resultado": "con_observaciones"}).status_code == 400,
          "«Requiere seguimiento» exige comentario")
    c.post(f"/entrevista-humana/publica/{token}/capacitacion", json={"asistio": True, "resultado": "con_observaciones", "comentario": "Reforzar uso de la app"})
    panel = c.get(f"/candidatos/{ana}/operativo", headers=h).json()
    check(panel["etapa"] == "Entrevista" and panel["entrevista"]["resultadoEtiqueta"] == "Requiere seguimiento" and panel["entrevista"]["capturadoPor"] == "entrevistador",
          "el capacitador registra el resultado; la tarjeta NO se mueve sola")
    check(c.post(f"/entrevista-humana/publica/{token}/capacitacion", json={"asistio": True, "resultado": "favorable"}).status_code == 409,
          "la liga no sobreescribe un resultado ya capturado")
    r = c.post(f"/candidatos/{fer}/operativo/entrevista/resultado", json={"asistio": True, "resultado": "favorable", "fecha_realizada": "2026-09-29T10:00",
                                                                            "entrevistador": "Gerente de tienda", "comentario": "Muy puntual"}, headers=h)
    e_fer = r.json()["entrevista"]
    check(r.status_code == 200 and e_fer["capturadoPor"] == "rh" and e_fer["registradoPor"] and e_fer["realizadaEn"].startswith("2026-09-29")
          and e_fer["capacitador"]["nombre"] == "Gerente de tienda" and not e_fer["confirmada"],
          "«Registrar entrevista» manual aunque no esté confirmada: fecha realizada, entrevistador, resultado, autor y vía")
    ev_res = r.json()["evaluacionResumen"]
    check(ev_res["prefiltro"]["aprobadoPorRH"] and ev_res["vehiculo"]["etiqueta"] == "Aprobado por excepción" and ev_res["entrevista"]["resultadoEtiqueta"] == "Apto"
          and ev_res["entrevista"]["observaciones"] == "Muy puntual", "la Evaluación reúne prefiltro, vehículo y entrevista en tienda")

    # Captura manual desde la ficha (alimenta el mismo registro que las ligas)
    r = c.post(f"/candidatos/{fer}/vehiculo/generar-liga", headers=h)
    check(r.status_code == 200 and r.json()["vehiculo"]["liga"], "«Generar liga» del vehículo sin enviarla")
    r = c.post(f"/candidatos/{fer}/vehiculo/foto", data={"lado": "frente"}, files={"archivo": ("f.jpg", JPG, "image/jpeg")}, headers=h)
    check(r.status_code == 200 and next(x for x in r.json()["vehiculo"]["fotos"] if x["lado"] == "frente")["cargada"], "RH sube una foto del vehículo desde la ficha")
    r = c.post(f"/candidatos/{fer}/vehiculo/documento", data={"clave": "poliza"}, files={"archivo": ("p.pdf", PDF, "application/pdf")}, headers=h)
    check(r.status_code == 200 and next(x for x in r.json()["vehiculo"]["documentos"] if x["clave"] == "poliza")["cargado"], "RH sube la póliza desde la ficha")
    refs_rh = [{"nombre": "Ana Uno", "telefono": "5512340001", "parentesco": "Familiar"}, {"nombre": "Beto Dos", "telefono": "5512340002", "parentesco": "Amistad"},
               {"nombre": "Ceci Tres", "telefono": "5512340003", "parentesco": "Vecino(a)"}]
    check(c.post(f"/candidatos/{fer}/operativo/referencias", json={"referencias": refs_rh[:2]}, headers=h).status_code == 400, "captura manual exige 3 referencias")
    r = c.post(f"/candidatos/{fer}/operativo/referencias", json={"referencias": refs_rh}, headers=h)
    check(r.status_code == 200 and len(r.json()["expediente"]["referencias"]) == 3, "RH captura las 3 referencias desde la ficha")
    check(c.post(f"/candidatos/{fer}/operativo/referencias/0/validar", json={"validada": True}, headers=h).status_code == 409,
          "no se valida una referencia que no se ha contactado")
    check(c.patch(f"/candidatos/{ana}/etapa", json={"etapa": "Onboarding", "manual": True}, headers=h).status_code == 409,
          "no se brinca a Onboarding sin condiciones ni contrato")

    # Evaluación → Contratación
    check(c.patch(f"/candidatos/{ana}/etapa", json={"etapa": "Evaluación", "manual": True}, headers=h).status_code == 200, "RH pasa a Evaluación")
    check(c.patch(f"/candidatos/{ana}/etapa", json={"etapa": "Contratación", "manual": True}, headers=h).status_code == 200, "RH pasa a Contratación")
    panel = c.get(f"/candidatos/{ana}/operativo", headers=h).json()
    check({"Honorarios", "Prestación de servicios", "Comisión mercantil"} <= set(panel["contratacion"]["tiposContratacion"]),
          "tipos de contratación: Honorarios, Prestación de servicios, Comisión mercantil")
    check(c.post(f"/candidatos/{ana}/operativo/contrato", json={"cuando": "ahora"}, headers=h).status_code == 409, "generar contrato exige condiciones")
    r = c.patch(f"/candidatos/{ana}/condiciones-contratacion", json={"puesto": "Chofer de reparto", "sueldo": "$650 diarios", "tipo_contratacion": "Comisión mercantil",
                                                                      "fecha_ingreso": "2030-02-01"}, headers=h)
    check(r.status_code == 200, "guardar condiciones (Comisión mercantil)")
    check(c.post(f"/candidatos/{ana}/operativo/onboarding", headers=h).status_code == 409, "a Onboarding no se pasa sin decidir el contrato")
    panel = c.post(f"/candidatos/{ana}/operativo/contrato", json={"cuando": "despues"}, headers=h).json()
    check(panel["contratacion"]["contrato"] == "despues" and not panel["contratacion"]["requisitosOnboarding"], "«Generar después de Onboarding» deja el contrato pendiente")
    pdf = c.get(f"/contratacion/expedientes/{panel['expediente']['id']}/contrato", headers=h)
    check(pdf.status_code == 200 and pdf.content[:4] == b"%PDF", "el contrato se puede generar sin esperar los documentos de Onboarding")

    # Onboarding: 6 documentos personales (los del vehículo ya están) + 3 referencias
    r = c.post(f"/candidatos/{ana}/operativo/onboarding", headers=h).json()
    docs = {d["tipo"]: d for d in r["expediente"]["documentos"]}
    check(r["etapa"] == "Onboarding" and len(docs) == 9 and all(docs[t]["estadoSimple"] == "Revisado" for t in
          ("Licencia de conducir vigente", "Tarjeta de circulación", "Póliza de seguro vigente")),
          "Enviar a Onboarding → pide los 6 documentos; los 3 del vehículo ya están revisados")
    tok = r["liga"].rsplit("/", 1)[1]
    pub = c.get(f"/expedientes/publica/{tok}").json()
    check(pub["pideReferencias"] and pub["referenciasRequeridas"] == 3, "la liga del expediente pide 3 referencias")
    refs = [{"nombre": "Ref Uno", "telefono": "5511111111", "parentesco": "Familiar"}, {"nombre": "Ref Dos", "telefono": "5522222222", "parentesco": "Amistad"}]
    check(c.post(f"/expedientes/publica/{tok}/referencias", json={"referencias": refs}).status_code == 400, "exige exactamente 3 referencias")
    refs.append({"nombre": "Ref Tres", "telefono": "5533333333", "parentesco": "Exjefe o excompañero"})
    check(c.post(f"/expedientes/publica/{tok}/referencias", json={"referencias": refs}).status_code == 200, "el candidato captura sus 3 referencias")

    def estado_doc(tipo):
        p_ = c.get(f"/candidatos/{ana}/operativo", headers=h).json()
        return next(x["estadoSimple"] for x in p_["expediente"]["documentos"] if x["tipo"] == tipo)

    ine = "Identificación oficial (INE)"
    check(estado_doc(ine) == "Pendiente", "documento sin archivo → «Pendiente»")
    c.post(f"/expedientes/publica/{tok}/documentos", data={"tipo": ine}, files={"archivo": ("ine.pdf", PDF, "application/pdf")})
    check(estado_doc(ine) == "Recibido", "el candidato lo sube → «Recibido» (falta revisión de RH)")
    check(c.post(f"/candidatos/{ana}/operativo/documentos", json={"tipo": ine, "estado": "rechazado"}, headers=h).status_code == 400,
          "pedir corrección exige motivo")
    r_corr = c.post(f"/candidatos/{ana}/operativo/documentos", json={"tipo": ine, "estado": "rechazado", "notas": "Falta el reverso"}, headers=h).json()
    msgs = c.get(f"/candidatos/{ana}/mensajes", headers=h).json()
    lista_m = msgs if isinstance(msgs, list) else msgs.get("mensajes", [])
    doc_pub = next(x for x in c.get(f"/expedientes/publica/{tok}").json()["documentos"] if x["tipo"] == ine)
    check(estado_doc(ine) == "Requiere corrección" and r_corr["whatsapp"] is not None
          and any("requiere corrección: Falta el reverso" in (m.get("texto") or "") for m in lista_m)
          and doc_pub["motivo"] == "Falta el reverso", "pedir corrección → «Requiere corrección», aviso por chat y motivo en la liga")
    c.post(f"/expedientes/publica/{tok}/documentos", data={"tipo": ine}, files={"archivo": ("ine2.pdf", PDF, "application/pdf")})
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
    curp = "CURP"
    c.post(f"/expedientes/publica/{tok}/documentos", data={"tipo": curp}, files={"archivo": ("curp.pdf", PDF, "application/pdf")})
    check(estado_doc(curp) == "Recibido", "Modo Prueba (flujo operativo): el documento subido queda «Recibido», no se auto-aprueba")
    cfg.modo_prueba = False
    db.commit()
    db.close()

    for t in docs:
        if estado_doc(t) == "Revisado":
            continue
        c.post(f"/expedientes/publica/{tok}/documentos", data={"tipo": t}, files={"archivo": ("doc.pdf", PDF, "application/pdf")})
        c.post(f"/candidatos/{ana}/operativo/documentos", json={"tipo": t, "estado": "aprobado"}, headers=h)
    panel = c.get(f"/candidatos/{ana}/operativo", headers=h).json()
    check(all(x["estadoSimple"] == "Revisado" for x in panel["expediente"]["documentos"]), "los 9 documentos del chofer quedan «Revisado»")
    check(not panel["listoParaAlta"] and any("Referencias por validar" in f for f in panel["faltantesAlta"]),
          "con documentos revisados aún faltan las referencias validadas")
    check(c.post(f"/candidatos/{ana}/operativo/alta", headers=h).status_code == 409, "«Dar de alta» bloqueado sin referencias validadas")

    url_ref = f"/candidatos/{ana}/operativo/referencias/0"
    check(c.post(url_ref, json={"contactada": True, "resultado": "No contestó"}, headers=h).status_code == 400,
          "llamada: el resultado debe corresponder a si se contactó")
    check(c.post(url_ref, json={"contactada": True, "resultado": "Favorable", "fecha": "2099-01-01T10:00"}, headers=h).status_code == 400,
          "llamada: la fecha no puede ser futura")
    panel = c.post(url_ref, json={"contactada": False, "resultado": "No contestó", "fecha": "2026-09-29T10:15", "nota": "Buzón"}, headers=h).json()
    ref0 = panel["expediente"]["referencias"][0]
    check(not ref0["contactada"] and ref0["resultado"] == "No contestó" and len(ref0["llamadas"]) == 1,
          "llamada sin contacto: queda registrada y la referencia sigue por contactar")
    panel = c.post(url_ref, json={"contactada": True, "resultado": "Favorable", "fecha": "2026-09-29T12:40", "nota": "Lo recomienda"}, headers=h).json()
    ref0 = panel["expediente"]["referencias"][0]
    check(ref0["contactada"] and [x["resultado"] for x in ref0["llamadas"]] == ["No contestó", "Favorable"]
          and ref0["llamadas"][1]["fecha"].startswith("2026-09-29T12:40") and ref0["llamadas"][1]["observaciones"] == "Lo recomienda"
          and ref0["llamadas"][1]["usuario"], "segunda llamada contactada: historial con fecha, resultado, observaciones y quién llamó")
    for i in (1, 2):
        panel = c.post(f"/candidatos/{ana}/operativo/referencias/{i}", json={"contactada": True, "resultado": "Favorable", "nota": "OK"}, headers=h).json()
    check(not panel["listoParaAlta"] and all(r["contactada"] and not r.get("validada") for r in panel["expediente"]["referencias"]),
          "las llamadas contactadas NO validan solas")
    check(c.post(f"/candidatos/{ana}/operativo/referencias/0/validar", json={"validada": True}, headers=h).status_code == 200, "RH valida una referencia contactada")
    for i in (1, 2):
        panel = c.post(f"/candidatos/{ana}/operativo/referencias/{i}/validar", json={"validada": True, "nota": "Confirma relación"}, headers=h).json()
    check(panel["etapa"] == "Onboarding" and panel["listoParaAlta"] and panel["expediente"]["referencias"][2]["validada_por"],
          "documentos revisados y referencias VALIDADAS → se habilita «Dar de alta»")
    panel = c.post(f"/candidatos/{ana}/operativo/alta", headers=h).json()
    check(panel["alta"]["colaborador"] and panel["activa"] is False, "«Dar de alta» crea el colaborador y CIERRA el proceso")
    check(c.get(f"/candidatos/{ana}", headers=h).json()["motivoCierre"] == "contratado", "la postulación queda cerrada como contratado")


async def _whatsapp():
    from app.database import SessionLocal
    from app.models import Vacante
    from app.routers.candidatos import _crear_candidato, postulacion_para_vacante, procesar_prefiltro

    db = SessionLocal()
    v = db.query(Vacante).filter(Vacante.slug == SLUG + "cdmx").one()
    persona = _crear_candidato(db, v.cuenta_id, "Hugo WhatsApp", "WhatsApp", False)
    p, _ = postulacion_para_vacante(db, persona, v, v.cuenta_id, "whatsapp", consentimiento=True)
    db.commit()
    check(p.etapa == "Prefiltro", "todo candidato nuevo entra a Prefiltro")
    guion = ["Me interesa", "Iztapalapa", "si", "claro", "Sí", "tengo una kangoo", "no sé", "modelo 09", "nel", "no sé", "si", "no tengo", "sí"]
    ultima = {}
    for t in guion:
        ultima = await procesar_prefiltro(db, p, t, "whatsapp")
    db.refresh(p)
    ev = (p.analisis or {}).get("prefiltro_reglas", {}).get("evaluacion", {})
    check(p.prefiltro_completo and p.estado == "revision" and {m["id"] for m in ev.get("motivos", [])} == {"circulacion", "poliza"},
          "chat: preguntas con repregunta → Requiere revisión (circulación dudosa + póliza pendiente)")
    check(ultima.get("clasificacion", {}).get("etiqueta") == "Requiere revisión", "chat: cierre con etiqueta")
    db.close()


# ------------------------------------------------------------ punta a punta por chat


async def _whatsapp_por_plaza(nombre: str, plaza: str, cambios: dict):
    """Contesta el cuestionario completo por chat; regresa (db, postulación, ids, respuestas del bot, vacante)."""
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

    db, p, ids, salidas, v = await _whatsapp_por_plaza("Lalo WhatsApp", "puebla", {})
    textos = [q["texto"] for q in pr.preguntas(v.prefiltro_reglas)]
    en_orden = all(textos[i] in salidas[i] and f"*{i + 1}/{len(ids)}*" in salidas[i] for i in range(len(ids)))
    check(en_orden and len(ids) >= 11, f"chat: las {len(ids)} preguntas del documento salen en orden, una por mensaje")
    check(p.estado == "cumple" and p.etapa == "Revisión de vehículo" and p.revision_vehiculo is not None
          and "/vehiculo/" in salidas[-1] and "licencia" in salidas[-1], "chat: «Cumple perfil» → «Revisión de vehículo» + liga de fotos y documentos")
    cumple = p.codigo
    db.close()

    db, p, *_ = await _whatsapp_por_plaza("Memo WhatsApp", "puebla", {"anio_vehiculo": "2015"})
    ev = (p.analisis or {}).get("prefiltro_reglas", {}).get("evaluacion", {})
    check(p.estado == "revision" and ev.get("etiqueta") == "Requiere revisión" and p.etapa == "Prefiltro"
          and [m["id"] for m in ev.get("motivos", [])] == ["anio_vehiculo"],
          "chat: modelo 2015 en Puebla → «Requiere revisión» (motivo año del vehículo), sigue en Prefiltro")
    db.close()

    db, p, *_ = await _whatsapp_por_plaza("Nico WhatsApp", "cdmx", {"tipo_vehiculo": "un tsuru"})
    ev = (p.analisis or {}).get("prefiltro_reglas", {}).get("evaluacion", {})
    check(p.estado == "revision" and [m["id"] for m in ev.get("motivos", [])] == ["tipo_vehiculo"],
          "chat: «un tsuru» en CDMX → «Otro» → «Requiere revisión» (motivo tipo de vehículo)")
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

        cursos = c.get("/capacitacion", headers=h).json()
        induccion = next(x for x in (cursos if isinstance(cursos, list) else cursos.get("cursos", [])) if x.get("titulo") == "Inducción SEZA")
        cita = {"tienda": "Tienda WA", "fecha": "2030-02-01", "hora": "09:00", "capacitador_tipo": "externo", "capacitador_nombre": "Sup WA",
                "curso_induccion": induccion["id"]}

        k0, v0 = conteos()
        r = c.post(f"/candidatos/{cumple}/vehiculo/decision", json={"accion": "excepcion", "comentario": "Revisado en persona"}, headers=h)
        check(r.status_code == 200 and r.json()["vehiculo"]["puedeCitar"], "vehículo del candidato de chat aprobado por excepción")
        k1, v1 = conteos()
        check(k1["Revisión de vehículo"] == k0["Revisión de vehículo"] - 1 and k1["Entrevista"] == k0["Entrevista"] + 1
              and v1 == k1, "contadores: la tarjeta pasa de «Revisión de vehículo» a «Entrevista» y Kanban = vacantes")
        c.post(f"/candidatos/{cumple}/operativo/entrevista", json=cita, headers=h)

        resp = asyncio.run(_whatsapp_confirma(cumple, "Sí, ahí estaré"))
        check("confirmada" in resp, "chat «Sí» confirma la cita")
        panel = c.get(f"/candidatos/{cumple}/operativo", headers=h).json()
        msgs = c.get(f"/candidatos/{cumple}/mensajes", headers=h).json()
        liga = next((m["texto"].rsplit(" ", 1)[1] for m in (msgs if isinstance(msgs, list) else msgs.get("mensajes", []))
                     if "[Simulado" in (m.get("texto") or "")), "")
        pdf = c.get(f"/capacitacion/publica/{liga.rsplit('/', 1)[1]}/pdf") if liga else None
        check(panel["entrevista"]["confirmada"] and pdf is not None and pdf.status_code == 200
              and pdf.content[:4] == b"%PDF", "el PDF de «Inducción SEZA» se descarga desde la liga enviada")

        token = panel["entrevista"]["ligaCapacitador"].rsplit("/", 1)[1]
        r = c.post(f"/entrevista-humana/publica/{token}/capacitacion", json={"asistio": True, "resultado": "favorable"})
        k2, v2 = conteos()
        tarjeta = c.get(f"/candidatos/{cumple}", headers=h).json()
        check(r.status_code == 200 and k2 == k1 and v2 == k2 and tarjeta["operativo"]["texto"] == "Realizada · Apto",
              "capacitador registra «Apto» → subestado «Realizada · Apto»; la tarjeta no se mueve sola y los contadores cuadran")

        otro = next(x["id"] for x in c.get("/candidatos", headers=h).json() if x["etapa"] == "Revisión de vehículo")
        c.post(f"/candidatos/{otro}/vehiculo/decision", json={"accion": "excepcion", "comentario": "Prueba"}, headers=h)
        with mock.patch("app.routers.capacitacion.asignar_a_postulacion", side_effect=RuntimeError("falla simulada")):
            r = c.post(f"/candidatos/{otro}/operativo/entrevista", json=cita, headers=h)
        check(r.status_code == 200 and r.json()["entrevista"]["estado"] == "Agendada" and r.json()["induccionEnviada"] is None,
              "si falla el PDF de inducción, la cita queda agendada igual")
        r = c.post(f"/candidatos/{otro}/operativo/entrevista/resultado", json={"asistio": False, "comentario": "No llegó"}, headers=h)
        check(r.status_code == 200 and r.json()["etapa"] == "Entrevista" and r.json()["subestado"]["texto"] == "No asistió",
              "«No asistió» deja la tarjeta en «Entrevista» para reprogramar")
        r = c.post(f"/candidatos/{otro}/operativo/entrevista", json=cita, headers=h)
        check(r.status_code == 200 and r.json()["entrevista"]["estado"] == "Agendada" and r.json()["entrevistasAnteriores"] == 1,
              "reprogramar tras «No asistió» crea una cita nueva y conserva la anterior")


if __name__ == "__main__":
    main()
    if not FALLAS:
        _capacitacion_y_contadores(asyncio.run(_whatsapp_completo()))
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
