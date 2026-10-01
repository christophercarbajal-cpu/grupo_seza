"""Regresión de textos de publicación y Facebook (2026-09-30). Base desechable, sin claves (texto base determinista).

    .venv/Scripts/python.exe scripts/verificar_textos_facebook.py

Generar textos (chat, bolsa/portal y Facebook) desde Nueva vacante o Plantilla con los datos FINALES, sin inventar
condiciones y sin dejar vacíos; guardar vacante/plantilla nunca deja un texto vacío; Facebook en las plataformas, texto
editable con generar/regenerar y guardar, liga con origen Facebook.
"""

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_dir = tempfile.mkdtemp(prefix="rh_textos_")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_dir) / "textos.db").replace("\\", "/")
for k in ("OPENAI_API_KEY", "WHATSAPP_PROVIDER", "META_WHATSAPP_TOKEN", "ANAM_API_KEY", "RESEND_API_KEY", "TELEGRAM_BOT_TOKEN"):
    os.environ[k] = ""
os.environ["ADMIN_PASSWORD"] = "prueba-textos"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.deps import cuenta_actual, usuario_actual, usuario_admin, usuario_decisor  # noqa: E402
from app.main import app  # noqa: E402
from app.models import PLATAFORMAS, Cuenta, Usuario, UsuarioCuenta  # noqa: E402

OK = 0


def check(cond, msg):
    global OK
    if not cond:
        print(f"❌ FALLO: {msg}")
        sys.exit(1)
    OK += 1
    print(f"✅ {msg}")


FICHA = {"titulo": "Chofer de reparto", "area": "Logística", "seniority": "Junior", "ubicacion_estado": "Puebla", "ubicacion_municipio": "Puebla",
         "modalidad": "Presencial", "sueldo_desde": 650, "sueldo_periodicidad": "dia_semanal",
         "requisitos_indispensables": ["Licencia vigente", "Vehículo propio"], "beneficios": ["Bono por entrega"], "jornada_horas": 10}

with TestClient(app) as client:
    db = SessionLocal()
    admin = db.query(Usuario).filter(Usuario.rol == "Administrador").first()
    cuenta = Cuenta(nombre="Textos", nombre_comercial="Reparto SA", razon_social="Reparto SA de CV", estado="Activa")
    db.add(cuenta)
    db.flush()
    db.add(UsuarioCuenta(usuario_id=admin.id, cuenta_id=cuenta.id))
    db.commit()
    for dep in (usuario_actual, usuario_decisor, usuario_admin):
        app.dependency_overrides[dep] = lambda: admin
    app.dependency_overrides[cuenta_actual] = lambda: cuenta

    print("\n--- 1. Generar textos con los datos finales (Nueva vacante / Plantilla) ---")
    r = client.post("/vacantes/textos", json=FICHA)
    t = r.json()["textos"]
    check(r.status_code == 200 and set(t) == {"whatsapp", "bolsa", "facebook"} and all(x.strip() for x in t.values()),
          "chat, bolsa/portal y Facebook — ninguno vacío")
    fb = t["facebook"]
    check(all(x in fb for x in ("Chofer de reparto", "Puebla", "$650", "10 horas", "Licencia vigente")),
          "Facebook trae puesto, ubicación, pago, horario y requisitos")
    check("http" not in fb, "el texto de Facebook no trae liga (se agrega al copiar con la liga de origen Facebook)")
    r = client.post("/vacantes/textos", json={**FICHA, "titulo": "Chofer nocturno", "sueldo_desde": None, "sueldo_periodicidad": "a_convenir", "jornada_horas": None})
    fb2 = r.json()["textos"]["facebook"]
    check("Chofer nocturno" in fb2 and "💰" not in fb2 and "🕘" not in fb2, "usa los cambios del formulario y no inventa pago ni horario si no se capturaron")
    check(client.post("/vacantes/textos", json={**FICHA, "titulo": " "}).status_code == 400, "sin puesto no se generan textos")

    print("\n--- 2. Guardar nunca deja textos vacíos ---")
    r = client.post("/vacantes", json={**FICHA, "descripcion": "Reparto en ruta", "generar_si_falta": False, "publicar": True, "plataformas": ["Portal", "Facebook"]})
    v = r.json()
    check(r.status_code in (200, 201) and v["textoWhatsapp"] and v["textoBolsa"] and v["textoFacebook"], "vacante guardada sin textos → se rellenan")
    check("Facebook" in PLATAFORMAS and "Facebook" in v["plataformas"], "Facebook está en las publicaciones")
    r = client.post("/plantillas", json={"nombre": "Chofer", "titulo": "Chofer de reparto", "ubicacion": "Puebla", "texto_facebook": "Mi texto propio"})
    p = r.json()
    check(r.status_code == 201 and p["textoFacebook"] == "Mi texto propio" and p["textoWhatsapp"] and p["textoBolsa"],
          "plantilla: respeta el texto editado y rellena los vacíos")
    r = client.patch(f"/plantillas/{p['id']}", json={"texto_whatsapp": ""})
    check(r.json()["textoWhatsapp"].strip() != "", "editar una plantilla dejando un texto vacío lo vuelve a armar")

    print("\n--- 3. Facebook en la vacante: generar / regenerar, editar, guardar, copiar, liga ---")
    pieza = client.get(f"/vacantes/{v['id']}/facebook").json()
    check(pieza["liga"].endswith("?origen=facebook") and pieza["copy"] == v["textoFacebook"], "la pieza usa el texto guardado y la liga de origen Facebook")
    check(pieza["copyConLiga"].endswith(pieza["liga"]) and pieza["copy"] in pieza["copyConLiga"], "«Copiar publicación» = texto + liga")
    r = client.post(f"/vacantes/{v['id']}/facebook/generar").json()
    check(r["sinGuardar"] and r["copy"] and "Chofer de reparto" in r["copy"], "regenerar devuelve un texto nuevo sin guardarlo")
    r = client.patch(f"/vacantes/{v['id']}/facebook", json={"texto": "¡Únete a nuestro equipo de reparto!"})
    check(r.json()["copy"] == "¡Únete a nuestro equipo de reparto!" and r.json()["copyPropio"], "guardar el texto editado")
    r = client.patch(f"/vacantes/{v['id']}/facebook", json={"texto": "   "})
    check(r.json()["copy"].strip() != "" and "Chofer de reparto" in r.json()["copy"], "guardar vacío → se vuelve a armar (nunca vacío)")
    check(r.json()["imagen"]["titulo"] == "Chofer de reparto" and r.json()["imagen"]["sueldo"], "datos para generar / descargar la imagen")

print(f"\n🎉 Textos y Facebook: {OK} verificaciones OK")
