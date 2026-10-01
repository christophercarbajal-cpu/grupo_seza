"""Mensajería por Telegram (demo Grupo SEZA, 2026-09-30).

La demo corre por un bot de Telegram en lugar de WhatsApp (sin plantillas ni ventana de 24 h de Meta). Se
activa con `TELEGRAM_BOT_TOKEN` en el .env del servidor; `services/whatsapp.py` delega aquí todo envío, así
que ningún flujo (prefiltro, vehículo, cita, inducción, documentos, avisos de RH) cambia.

Identidad: un bot NO puede escribirle a un número; solo a un chat que ya le habló. En el primer mensaje el bot
pide «Compartir mi número» (botón nativo `request_contact`: Telegram lo verifica) y guarda la relación
chat ↔ teléfono en `ChatTelegram`. El resto de la plataforma sigue usando el teléfono a 10 dígitos, por eso
una persona que se postuló por la web queda ligada en cuanto comparte su número en el bot.

Handoff web → Telegram (2026-10-01): al postularse en /aplicar la postulación recibe `telegram_onboarding_token` y
el portal abre `tg://resolve?domain=<bot>&start=<token>`. `/start <token>` amarra el chat a ESA postulación (con su
teléfono, sin pedirlo otra vez) y lanza su evaluación; `/start` vacío = menú general de vacantes.

Webhook: `POST /api/webhooks/telegram`. Telegram manda el secreto que registramos con `setWebhook` en la
cabecera `X-Telegram-Bot-Api-Secret-Token`; sin ese secreto la petición se rechaza.
"""

import hashlib
import hmac
import html
import re
import secrets
from typing import Optional

import httpx

from ..config import settings

API_URL = "https://api.telegram.org"
TEXTO_BOTON_CONTACTO = "📱 Compartir mi número"


def activo() -> bool:
    return bool(settings.telegram_bot_token.strip())


def secreto_webhook() -> str:
    """Secreto de `setWebhook` (1-256 caracteres A-Z a-z 0-9 _ -). Si no se declaró TELEGRAM_WEBHOOK_SECRET,
    se deriva del token del bot: el servidor y el script de registro llegan al mismo valor sin otra variable."""
    if settings.telegram_webhook_secret.strip():
        return settings.telegram_webhook_secret.strip()
    return hmac.new(settings.telegram_bot_token.strip().encode(), b"redhuman-webhook-telegram", hashlib.sha256).hexdigest()


def secreto_valido(cabecera: str) -> bool:
    return activo() and hmac.compare_digest(secreto_webhook(), (cabecera or "").strip())


# --------------------------------------------------------------------------- #
# Handoff web → Telegram (deep link con /start <token>)
# --------------------------------------------------------------------------- #

RE_TOKEN_INICIO = re.compile(r"^[A-Za-z0-9_-]{8,64}$")  # el parámetro de /start admite solo esto (máx. 64)


def usuario_bot() -> str:
    return (settings.telegram_bot_username or "").strip().lstrip("@")


def asegurar_token_onboarding(p) -> str:
    """Token único de la postulación para el deep link. Se reutiliza si ya existe (reaplicar no rompe la liga que
    el candidato ya tenga)."""
    if not p.telegram_onboarding_token:
        p.telegram_onboarding_token = secrets.token_urlsafe(24)  # 32 caracteres [A-Za-z0-9_-]
    return p.telegram_onboarding_token


def liga_inicio(token: str) -> str:
    """Enlace nativo de Telegram (abre la app directo en el bot con /start <token>)."""
    return f"tg://resolve?domain={usuario_bot()}&start={token}" if token else ""


def postulacion_por_token(db, token: str):
    from ..models import Postulacion

    if not token or not RE_TOKEN_INICIO.match(token):
        return None
    return db.query(Postulacion).filter(Postulacion.telegram_onboarding_token == token).first()


def _resultado(enviado: bool, detalle, **extra) -> dict:
    return {"enviado": enviado, "proveedor": "telegram", "detalle": detalle, **extra}


async def llamar(metodo: str, json: Optional[dict] = None, data: Optional[dict] = None, files: Optional[dict] = None) -> dict:
    """POST a la Bot API. Regresa {ok, result | description, error_code}; nunca lanza (red caída = ok False)."""
    if not activo():
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN sin configurar"}
    url = f"{API_URL}/bot{settings.telegram_bot_token.strip()}/{metodo}"
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.post(url, json=json, data=data, files=files)
        cuerpo = r.json()
    except Exception as e:  # noqa: BLE001 — la mensajería nunca tumba el flujo de RH
        print(f"[telegram] Error de red en {metodo}: {e}")
        return {"ok": False, "description": f"error de red: {e}"}
    if not cuerpo.get("ok"):
        print(f"[telegram] {metodo} rechazado ({cuerpo.get('error_code')}): {cuerpo.get('description')}")
    return cuerpo


# --------------------------------------------------------------------------- #
# chat ↔ teléfono
# --------------------------------------------------------------------------- #


def telefono_10(telefono: str) -> str:
    """+52 1 55 1234 5678 / 5215512345678 / 525512345678 → 5512345678 (como Candidato.telefono)."""
    digitos = re.sub(r"\D", "", telefono or "")
    if digitos.startswith("521") and len(digitos) == 13:
        return digitos[3:]
    if digitos.startswith("52") and len(digitos) == 12:
        return digitos[2:]
    return digitos[-10:] if len(digitos) > 10 else digitos


def chat_de_telefono(telefono: str) -> Optional[str]:
    """Chat de Telegram de ese teléfono (el más reciente que lo compartió) o None si nunca habló con el bot."""
    from ..database import SessionLocal
    from ..models import ChatTelegram

    tel = telefono_10(telefono)
    if not tel:
        return None
    db = SessionLocal()
    try:
        fila = db.query(ChatTelegram).filter(ChatTelegram.telefono == tel).order_by(ChatTelegram.actualizado_en.desc()).first()
        return fila.chat_id if fila else None
    except Exception as e:  # noqa: BLE001 — tabla no creada (paso no fatal) → no hay a quién mandar
        print(f"[telegram] no se pudo leer chats_telegram: {e}")
        return None
    finally:
        db.close()


def guardar_chat(db, chat_id: str, telefono: str, nombre: str) -> str:
    from ..models import ChatTelegram, ahora

    tel = telefono_10(telefono)
    fila = db.get(ChatTelegram, str(chat_id))
    if fila is None:
        fila = ChatTelegram(chat_id=str(chat_id), telefono=tel, nombre=nombre[:200])
        db.add(fila)
    else:
        fila.telefono, fila.nombre, fila.actualizado_en = tel, (nombre or fila.nombre)[:200], ahora()
    db.flush()
    return tel


def telefono_de_chat(db, chat_id: str) -> Optional[str]:
    from ..models import ChatTelegram

    fila = db.get(ChatTelegram, str(chat_id))
    return fila.telefono if fila else None


# --------------------------------------------------------------------------- #
# Envío
# --------------------------------------------------------------------------- #


def _html(texto: str) -> str:
    """Los textos de la plataforma usan el formato de WhatsApp (*negritas*): se pasan a HTML de Telegram."""
    seguro = html.escape(texto or "", quote=False)
    return re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", seguro)


async def _enviar_a_chat(chat_id: str, texto: str, teclado: Optional[dict] = None) -> dict:
    cuerpo = {"chat_id": chat_id, "text": _html(texto)[:4096], "parse_mode": "HTML", "disable_web_page_preview": False}
    if teclado:
        cuerpo["reply_markup"] = teclado
    r = await llamar("sendMessage", json=cuerpo)
    if not r.get("ok") and "parse" in str(r.get("description", "")).lower():
        cuerpo.pop("parse_mode")
        cuerpo["text"] = (texto or "")[:4096]
        r = await llamar("sendMessage", json=cuerpo)
    if r.get("ok"):
        return _resultado(True, 200, wa_id=f"tg-msg-{(r.get('result') or {}).get('message_id', '')}")
    return _resultado(False, f"{r.get('error_code', '')}: {r.get('description', '')}".strip(": "), codigo=r.get("error_code"))


def _sin_chat(telefono: str) -> dict:
    return _resultado(
        False,
        f"El número {telefono_10(telefono) or '(vacío)'} no ha iniciado conversación con el bot de Telegram "
        "(o no compartió su número); Telegram no permite escribirle primero.",
        sin_chat=True,
    )


async def enviar_texto(telefono: str, texto: str) -> dict:
    chat = chat_de_telefono(telefono)
    if not chat:
        return _sin_chat(telefono)
    return await _enviar_a_chat(chat, texto)


async def enviar_lista(telefono: str, encabezado: str, cuerpo: str, opciones: list, secciones: Optional[list] = None) -> dict:
    """La lista interactiva de Meta como botones en línea: un botón por opción; al tocarlo llega un
    callback_query con el id (VAC-####, P-####, CTA-<id>) que el webhook trata igual que un list_reply."""
    chat = chat_de_telefono(telefono)
    if not chat:
        return _sin_chat(telefono)
    grupos = [s for s in (secciones or []) if s.get("opciones")] or [{"titulo": "", "opciones": opciones or []}]
    filas, lineas = [], [f"*{encabezado}*", cuerpo]
    for g in grupos:
        if len(grupos) > 1 and g.get("titulo"):
            lineas.append(f"\n*{g['titulo']}*")
        for o in g["opciones"][:30]:
            titulo = str(o.get("titulo") or o["id"])
            desc = str(o.get("descripcion") or "")
            if desc:
                lineas.append(f"• {titulo} — {desc}")
            filas.append([{"text": titulo[:60], "callback_data": str(o["id"])[:64]}])
    if not filas:
        return _resultado(False, "No hay opciones que mostrar")
    return await _enviar_a_chat(chat, "\n".join(lineas), {"inline_keyboard": filas})


async def enviar_documento(telefono: str, contenido: bytes, filename: str, caption: str = "") -> dict:
    chat = chat_de_telefono(telefono)
    if not chat:
        return _sin_chat(telefono)
    r = await llamar(
        "sendDocument",
        data={"chat_id": chat, "caption": _html(caption)[:1024], "parse_mode": "HTML"},
        files={"document": (filename, contenido, "application/pdf")},
    )
    if r.get("ok"):
        return _resultado(True, 200, wa_id=f"tg-msg-{(r.get('result') or {}).get('message_id', '')}", formato="documento")
    return _resultado(False, f"{r.get('error_code', '')}: {r.get('description', '')}".strip(": "))


async def pedir_contacto(chat_id: str, nombre: str = "") -> dict:
    saludo = f"¡Hola{', ' + nombre.split(' ')[0] if nombre else ''}! 👋 Soy el asistente de reclutamiento de *Red Human*."
    texto = (
        f"{saludo}\n\nPara darte seguimiento necesito tu número de celular. Toca el botón "
        f"*{TEXTO_BOTON_CONTACTO}* de abajo (Telegram lo comparte de forma segura)."
    )
    teclado = {"keyboard": [[{"text": TEXTO_BOTON_CONTACTO, "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True}
    return await _enviar_a_chat(chat_id, texto, teclado)


async def confirmar_contacto(chat_id: str) -> dict:
    return await _enviar_a_chat(chat_id, "¡Gracias! Ya tengo tu número ✅", {"remove_keyboard": True})


async def responder_callback(callback_id: str) -> None:
    if callback_id:
        await llamar("answerCallbackQuery", json={"callback_query_id": callback_id})


_EXT_POR_MIME = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}
_MIME_POR_EXT = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


async def descargar_archivo(file_id: str, mime: str = "") -> dict:
    """getFile → binario. Mismo contrato que `whatsapp.descargar_media` ({ok, contenido, mime, extension,
    filename, tamano, detalle}); nunca lanza."""
    if not file_id:
        return {"ok": False, "detalle": "sin file_id"}
    info = await llamar("getFile", json={"file_id": file_id})
    ruta = (info.get("result") or {}).get("file_path", "")
    if not info.get("ok") or not ruta:
        return {"ok": False, "detalle": f"getFile: {info.get('description', 'sin ruta')}"}
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(f"{API_URL}/file/bot{settings.telegram_bot_token.strip()}/{ruta}")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detalle": f"error de red: {e}"}
    if r.status_code >= 300:
        return {"ok": False, "detalle": f"descarga del archivo: HTTP {r.status_code}"}
    ext_ruta = ruta.rsplit(".", 1)[-1].lower() if "." in ruta else ""
    mime = (mime or _MIME_POR_EXT.get(ext_ruta, "")).lower()
    ext = _EXT_POR_MIME.get(mime, "")
    if not ext:
        return {"ok": False, "detalle": f"formato no admitido ({mime or 'desconocido'}); acepta PDF, JPG o PNG"}
    return {"ok": True, "contenido": r.content, "mime": mime, "extension": ext, "filename": f"telegram_{file_id[-12:]}.{ext}", "tamano": len(r.content)}


# --------------------------------------------------------------------------- #
# Recepción
# --------------------------------------------------------------------------- #


def parsear_update(update: dict) -> Optional[dict]:
    """Normaliza un Update de Telegram. Regresa None si no es un mensaje de una persona (ediciones, bots,
    grupos, etc.). Campos: chat_id, texto, nombre, update_id, tipo, media, id_seleccionado, callback_id,
    contacto {telefono, propio}."""
    cb = update.get("callback_query")
    if cb:
        m = cb.get("message") or {}
        chat = m.get("chat") or {}
        remitente = cb.get("from") or {}
        if remitente.get("is_bot") or chat.get("type", "private") != "private":
            return None
        # el texto visible del botón elegido (como el título de un list_reply de Meta)
        elegido = str(cb.get("data") or "")
        titulo = next((b.get("text", "") for fila in ((m.get("reply_markup") or {}).get("inline_keyboard") or [])
                       for b in fila if b.get("callback_data") == elegido), "")
        return {"chat_id": str(chat.get("id") or remitente.get("id") or ""), "texto": titulo or elegido,
                "nombre": _nombre(remitente), "update_id": update.get("update_id"), "tipo": "interactive",
                "media": None, "id_seleccionado": elegido, "callback_id": cb.get("id", ""), "contacto": None}

    m = update.get("message")
    if not m:
        return None  # edited_message, my_chat_member, etc.
    chat = m.get("chat") or {}
    remitente = m.get("from") or {}
    if remitente.get("is_bot") or chat.get("type") != "private":
        return None
    contacto = None
    if m.get("contact"):
        c = m["contact"]
        contacto = {"telefono": str(c.get("phone_number", "")), "propio": c.get("user_id") == remitente.get("id")}
    tipo, media = "text", None
    if m.get("photo"):
        mayor = sorted(m["photo"], key=lambda f: f.get("file_size") or 0)[-1]
        tipo, media = "image", {"id": mayor.get("file_id", ""), "mime_type": "image/jpeg", "filename": ""}
    elif m.get("document"):
        d = m["document"]
        tipo, media = "document", {"id": d.get("file_id", ""), "mime_type": d.get("mime_type", ""), "filename": d.get("file_name", "")}
    texto = m.get("text") or m.get("caption") or ""
    # /start [token]: vacío = «Iniciar» del bot (se trata como saludo → menú de vacantes); con token = handoff web
    start_token = ""
    partes = texto.strip().split(maxsplit=1)
    if partes and partes[0].lower().split("@")[0] == "/start":
        start_token = partes[1].strip() if len(partes) > 1 else ""
        texto = "Hola"
    return {"chat_id": str(chat.get("id", "")), "texto": texto, "nombre": _nombre(remitente), "update_id": update.get("update_id"),
            "tipo": tipo if (media or not contacto) else "contact", "media": media, "id_seleccionado": "", "callback_id": "",
            "contacto": contacto, "start_token": start_token}


def _nombre(u: dict) -> str:
    return " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x).strip()


def mensaje_para_agente(msg: dict, telefono: str) -> dict:
    """El mensaje normalizado con la MISMA forma que `whatsapp.parsear_webhook` (lo que procesa el agente)."""
    return {
        "telefono": "52" + telefono if len(telefono) == 10 else telefono,
        "texto": msg.get("texto", ""),
        "nombre": msg.get("nombre", ""),
        "wa_id": f"tg-{msg.get('update_id')}",
        "tipo": msg.get("tipo", "text"),
        "media": msg.get("media"),
        "id_seleccionado": msg.get("id_seleccionado", ""),
        "numero_receptor": "",
        "canal": "telegram",  # la persona nueva nace con fuente «Telegram» (origen en el tablero)
    }
