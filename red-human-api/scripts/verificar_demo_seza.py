"""Regresión de la demo Grupo SEZA (puntos 1-4, 2026-09-29) sobre una base DESECHABLE.

Carga el ambiente (`cargar_demo_seza.py`) y comprueba: sueldo por día, pieza de Facebook con liga única
y fuente «Facebook», prefiltro por reglas por la web (reglas distintas por plaza) y por WhatsApp
(cuestionario con repregunta), CV opcional, fotos del vehículo (subida, corrección, aprobación,
excepción) y que nadie salga de Prefiltro sin el vehículo aprobado.

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
        r = c.patch(f"/candidatos/{ana}/etapa", json={"etapa": "Entrevista Humana", "manual": True, "omitir_entrevista_ia": True}, headers=h)
        check(r.status_code == 409, "no sale de Prefiltro sin vehículo aprobado")

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
        r = c.patch(f"/candidatos/{ana}/etapa", json={"etapa": "Entrevista Humana", "manual": True, "omitir_entrevista_ia": True}, headers=h)
        check(r.status_code == 200, "con vehículo aprobado ya puede avanzar")

        check(c.post(f"/candidatos/{fer}/prefiltro-reglas/aprobar", json={"motivo": " "}, headers=h).status_code == 400, "aprobar prefiltro exige motivo")
        r = c.post(f"/candidatos/{fer}/prefiltro-reglas/aprobar", json={"motivo": "Póliza en trámite"}, headers=h).json()
        check(r["prefiltro"]["resultado"] == "cumple" and r["vehiculo"]["estado"] == "pendiente", "RH aprueba prefiltro → sale liga de fotos")
        check(c.post(f"/candidatos/{fer}/vehiculo/decision", json={"accion": "excepcion"}, headers=h).status_code == 400, "excepción exige motivo")
        r = c.post(f"/candidatos/{fer}/vehiculo/decision", json={"accion": "excepcion", "comentario": "Revisado en persona"}, headers=h).json()
        check(r["vehiculo"]["puedeCitar"], "excepción con motivo → se puede citar")

    asyncio.run(_whatsapp())


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


if __name__ == "__main__":
    main()
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
