"""Ligas de ENTRADA por vacante (2026-10-01, rutas paralelas Web / Chat).

Cada vacante tiene una liga por canal y cada una es una ruta COMPLETA e independiente que alimenta el mismo tablero:
* Web      → `/aplicar/{slug}`: datos, prefiltro, fotos y documentos en la web (Telegram solo avisa, si lo conecta).
* Telegram → `https://t.me/<bot>?start=vac_<VAC-####>`: el bot abre la postulación a ESA vacante y hace todo en el chat.
* WhatsApp → `https://wa.me/52<número>?text=…VAC-####`: solo si el canal está habilitado (Meta/WAHA/Evolution con un
  número público); con Telegram activo no se ofrece.
"""

from urllib.parse import quote

from ..config import settings
from . import telegram


def whatsapp_habilitado() -> bool:
    return settings.whatsapp_provider in ("meta", "waha", "evolution")


def _numero_whatsapp(cuenta) -> str:
    numero = "".join(ch for ch in ((getattr(cuenta, "whatsapp_comunicacion", "") or "") or settings.whatsapp_numero_publico or "") if ch.isdigit())
    return numero[-10:] if len(numero) >= 10 else ""


def ligas_entrada(v, cuenta=None) -> dict:
    """{web, telegram, whatsapp} de la vacante; "" en los canales que no aplican. Solo vacantes con slug/código."""
    web = f"{settings.app_url}/aplicar/{v.slug}" if v.slug else ""
    tg = telegram.liga_vacante(v.codigo)
    numero = _numero_whatsapp(cuenta) if whatsapp_habilitado() else ""
    wa = f"https://wa.me/52{numero}?text={quote(f'Hola, me interesa la vacante {v.codigo}')}" if numero else ""
    return {"web": web, "telegram": tg, "whatsapp": wa, "whatsappHabilitado": bool(wa)}
