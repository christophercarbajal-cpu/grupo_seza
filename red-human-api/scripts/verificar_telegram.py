"""Regresión de la mensajería por Telegram (demo Grupo SEZA, 2026-09-30) sobre una base DESECHABLE.

La API de Telegram se SIMULA (nada sale a internet): se registran las llamadas a la Bot API y se comprueba el
guion de la demo de punta a punta — /start → el bot pide el número (botón nativo) → menú de vacantes como
botones → aviso de privacidad → «Sí» → prefiltro de 11 preguntas → «Cumple perfil» con liga de fotos → RH cita →
al agendar sale la cita + PDF de «Inducción SEZA» como archivo → «Sí» confirma la cita. Además: el secreto del webhook es
obligatorio, los reintentos se deduplican por update_id, y un número que nunca habló con el bot no recibe nada.

Uso (desde red-human-api/):  python scripts/verificar_telegram.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASE = Path(tempfile.mkdtemp()) / "telegram.db"
os.environ["DATABASE_URL"] = f"sqlite:///{BASE.as_posix()}"
os.environ["ADMIN_PASSWORD"] = "Verificar123!"
os.environ["WHATSAPP_PROVIDER"] = "meta"  # el token de Telegram debe mandar sobre esto
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:token-de-prueba"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = ""
sys.path.insert(0, str(RAIZ))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import telegram, whatsapp  # noqa: E402

FALLAS = []
LLAMADAS = []


def check(cond, nombre):
    print(("✅ " if cond else "❌ ") + nombre)
    if not cond:
        FALLAS.append(nombre)


async def _llamar_falso(metodo, json=None, data=None, files=None):
    LLAMADAS.append({"metodo": metodo, "json": json or {}, "data": data or {}, "files": files or {}})
    return {"ok": True, "result": {"message_id": len(LLAMADAS)}}


telegram.llamar = _llamar_falso

CHAT, UID = 777001, 777001
_UPDATE = [1000]


def update_mensaje(texto="", contacto=None):
    _UPDATE[0] += 1
    m = {"message_id": _UPDATE[0], "chat": {"id": CHAT, "type": "private"}, "from": {"id": UID, "is_bot": False, "first_name": "Raúl", "last_name": "Prueba"}}
    if contacto:
        m["contact"] = contacto
    else:
        m["text"] = texto
    return {"update_id": _UPDATE[0], "message": m}


def update_boton(data, teclado):
    _UPDATE[0] += 1
    return {"update_id": _UPDATE[0], "callback_query": {
        "id": f"cb{_UPDATE[0]}", "from": {"id": UID, "is_bot": False, "first_name": "Raúl"}, "data": data,
        "message": {"message_id": 1, "chat": {"id": CHAT, "type": "private"}, "reply_markup": {"inline_keyboard": teclado}}}}


def enviados_desde(i):
    return [x for x in LLAMADAS[i:] if x["metodo"] in ("sendMessage", "sendDocument")]


def main():
    with TestClient(app):
        pass
    salida = subprocess.run([sys.executable, str(RAIZ / "scripts" / "cargar_demo_seza.py"), "--ejecutar"],
                            capture_output=True, text=True, encoding="utf-8", env=os.environ)
    check(salida.returncode == 0, "carga del ambiente SEZA")
    if salida.returncode:
        print(salida.stdout[-2000:], salida.stderr[-2000:])
        return

    check(whatsapp.proveedor() == "telegram", "con TELEGRAM_BOT_TOKEN el proveedor es Telegram (manda sobre WHATSAPP_PROVIDER=meta)")
    url = "/api/webhooks/telegram"
    sec = {"X-Telegram-Bot-Api-Secret-Token": telegram.secreto_webhook()}

    with TestClient(app) as c:
        check(c.post(url, json=update_mensaje("Hola")).status_code == 403, "webhook sin secreto → 403")
        check(c.post(url, json=update_mensaje("Hola"), headers={"X-Telegram-Bot-Api-Secret-Token": "otro"}).status_code == 403,
              "webhook con secreto incorrecto → 403")

        i = len(LLAMADAS)
        r = c.post(url, json=update_mensaje("/start"), headers=sec)
        env = enviados_desde(i)
        check(r.status_code == 200 and env and (env[-1]["json"].get("reply_markup") or {}).get("keyboard", [[{}]])[0][0].get("request_contact"),
              "/start sin número → el bot pide «Compartir mi número» (botón nativo)")

        i = len(LLAMADAS)
        up = update_mensaje(contacto={"phone_number": "+5215599990001", "user_id": UID, "first_name": "Raúl"})
        c.post(url, json=up, headers=sec)
        env = enviados_desde(i)
        menu = next((x for x in env if (x["json"].get("reply_markup") or {}).get("inline_keyboard")), None)
        teclado = (menu or {}).get("json", {}).get("reply_markup", {}).get("inline_keyboard", [])
        codigos = [b[0]["callback_data"] for b in teclado]
        check(menu is not None and len(codigos) == 3 and all(x.startswith("VAC-") for x in codigos),
              f"contacto compartido → menú de vacantes como botones ({codigos})")
        check(c.post(url, json=up, headers=sec).json().get("duplicado") is True, "reintento del mismo update_id → deduplicado")

        from app.database import SessionLocal
        from app.models import ChatTelegram, Postulacion, Vacante

        db = SessionLocal()
        check(db.get(ChatTelegram, str(CHAT)).telefono == "5599990001", "chat ↔ teléfono guardado a 10 dígitos")
        puebla = db.query(Vacante).filter(Vacante.slug.like("%puebla")).one()
        db.close()

        i = len(LLAMADAS)
        c.post(url, json=update_boton(puebla.codigo, teclado), headers=sec)
        env = enviados_desde(i)
        check(any(x["metodo"] == "answerCallbackQuery" for x in LLAMADAS[i:]) and any("privacidad" in x["json"].get("text", "").lower() for x in env),
              "elegir vacante con el botón → aviso de privacidad (elegir NO es consentimiento)")

        i = len(LLAMADAS)
        c.post(url, json=update_mensaje("Sí, acepto"), headers=sec)
        env = enviados_desde(i)
        check(any("<b>1/11</b>" in x["json"].get("text", "") for x in env), "«Sí» → arranca el prefiltro (pregunta 1/11, negritas en HTML)")

        respuestas = ["Puebla", "sí", "sí", "sí", "1", "2019", "no", "1", "si", "si", "si"]
        for t in respuestas:
            i = len(LLAMADAS)
            c.post(url, json=update_mensaje(t), headers=sec)
        env = enviados_desde(i)
        check(any("/vehiculo/" in x["json"].get("text", "") for x in env), "prefiltro completo «Cumple perfil» → liga de fotos del vehículo por Telegram")

        db = SessionLocal()
        p = db.query(Postulacion).join(Postulacion.candidato).filter_by(telefono="5599990001").order_by(Postulacion.id.desc()).first()
        codigo = p.codigo
        check(p.etapa == "Revisión de vehículo" and p.estado == "cumple", "la tarjeta queda en «Revisión de vehículo»")
        check(p.candidato.fuente == "Telegram", "la persona que llegó por el bot queda con fuente «Telegram»")
        db.close()

        # RH: vehículo por excepción + cita con curso de inducción
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        cuentas = c.get("/auth/yo").json().get("cuentas") or []
        h = {"X-Cuenta-Id": str(next(x["id"] for x in cuentas if "SEZA" in x.get("nombre", "")))}
        c.post(f"/candidatos/{codigo}/vehiculo/decision", json={"accion": "excepcion", "comentario": "Revisado en persona"}, headers=h)
        cursos = c.get("/capacitacion", headers=h).json()
        induccion = next(x for x in (cursos if isinstance(cursos, list) else cursos.get("cursos", [])) if x.get("titulo") == "Inducción SEZA")
        i = len(LLAMADAS)
        c.post(f"/candidatos/{codigo}/operativo/entrevista", json={"tienda": "Tienda TG", "fecha": "2030-03-01", "hora": "09:00",
                                                                     "capacitador_tipo": "externo", "capacitador_nombre": "Sup",
                                                                     "curso_induccion": induccion["id"]}, headers=h)
        env = enviados_desde(i)
        check(any("¿Confirmas tu asistencia?" in x["json"].get("text", "") and x["json"].get("chat_id") == str(CHAT) for x in env),
              "RH cita → el aviso sale al chat de Telegram del candidato (envío por teléfono → chat)")
        docs = [x for x in LLAMADAS[i:] if x["metodo"] == "sendDocument"]
        textos = [x["json"].get("text", "") for x in env if x["metodo"] == "sendMessage"]
        pdf = (docs[0]["files"].get("document") or (None, b""))[1] if docs else b""
        check(docs and pdf[:4] == b"%PDF" and docs[0]["data"]["chat_id"] == str(CHAT),
              "al agendar, el PDF de «Inducción SEZA» sale como archivo por Telegram junto con la cita")
        check(any("Inducción SEZA" in t and "[Simulado" not in t for t in textos), "el mensaje de inducción no va marcado como simulado")

        i = len(LLAMADAS)
        c.post(url, json=update_mensaje("Sí"), headers=sec)
        check(any("confirmada" in x["json"].get("text", "") for x in enviados_desde(i))
              and not [x for x in LLAMADAS[i:] if x["metodo"] == "sendDocument"], "«Sí» confirma la cita (sin reenviar el PDF)")

    # Un número que nunca habló con el bot: no se le puede escribir (Telegram no lo permite)
    import asyncio

    r = asyncio.run(whatsapp.enviar_mensaje("5511112222", "hola"))
    check(r["enviado"] is False and r.get("sin_chat") and r["proveedor"] == "telegram", "número sin chat → no enviado, con motivo claro")


if __name__ == "__main__":
    main()
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
