"""
Servicio de correo — notificaciones de Entrevista Humana vía Resend.

`RESEND_API_KEY` en .env; sin ella, modo demo: el envío se registra como "no enviado"
en la bitácora, igual que WHATSAPP_PROVIDER sin configurar en services/whatsapp.py.
"""

import base64
from typing import List, Optional

import httpx

from ..config import settings

RESEND_URL = "https://api.resend.com/emails"
DOMINIO_REMITENTE = "redhuman.mx"
REMITENTE_DEFAULT = "Red Human AI <notificaciones@redhuman.mx>"


def remitente() -> str:
    """Remitente efectivo (2026-09-18): estrictamente una dirección @redhuman.mx. Si RESEND_FROM trae otro
    dominio (p. ej. el sandbox onboarding@resend.dev) se ignora con warning y se usa el default."""
    valor = (settings.resend_from or "").strip()
    direccion = valor[valor.rfind("<") + 1 : valor.rfind(">")] if "<" in valor and ">" in valor else valor
    if direccion.lower().endswith("@" + DOMINIO_REMITENTE):
        return valor
    if valor:
        print(f"[correo] ⚠️ RESEND_FROM «{valor}» no es del dominio @{DOMINIO_REMITENTE}; se usa {REMITENTE_DEFAULT}.", flush=True)
    return REMITENTE_DEFAULT


def correo_activo() -> bool:
    return bool(settings.resend_api_key)


def _resultado(enviado: bool, detalle, **extra) -> dict:
    return {"enviado": enviado, "proveedor": "resend" if settings.resend_api_key else "demo", "detalle": detalle, **extra}


async def enviar_correo(destinatario: str, asunto: str, cuerpo_html: str, adjuntos: Optional[List[dict]] = None) -> dict:
    """Manda un correo transaccional vía Resend. Regresa {enviado, proveedor, detalle}.
    `adjuntos` (2026-09-19): [{"filename": "carta.pdf", "content": <bytes>}] → Resend los recibe en base64."""
    if not destinatario:
        return _resultado(False, "Sin dirección de correo")
    # 2026-10-01: TODO correo sale con la plantilla HTML corporativa de Red Human; lo que llegue sin ella se envuelve
    from .plantillas_correo import MARCA_LAYOUT, envolver

    if MARCA_LAYOUT not in (cuerpo_html or ""):
        cuerpo_html = envolver(asunto, cuerpo_html)
    if not settings.resend_api_key:
        print("[correo] ⚠️ RESEND_API_KEY sin configurar: el correo no sale (se registra como no enviado).", flush=True)
        return _resultado(False, "RESEND_API_KEY sin configurar")
    desde = remitente()

    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(
                RESEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": desde,
                    "to": [destinatario],
                    "subject": asunto,
                    "html": cuerpo_html,
                    **({"attachments": [{"filename": a["filename"], "content": base64.b64encode(a["content"]).decode()} for a in adjuntos]} if adjuntos else {}),
                },
            )
        if r.status_code < 300:
            return _resultado(True, r.status_code, id=(r.json() or {}).get("id"))
        print(f"[correo] ⚠️ Resend rechazó el envío a {destinatario} ({r.status_code}): {r.text[:200]}", flush=True)
        detalle = r.text[:300]
        if r.status_code in (401, 403):
            detalle = f"API Key inválida o sin permiso ({r.status_code}): {detalle}"
        elif "domain" in r.text.lower() or r.status_code == 422:
            detalle = f"Dominio del remitente no verificado en Resend ({desde}): {detalle}"
        return _resultado(False, detalle, codigo=r.status_code)
    except Exception as e:  # que Resend falle no debe tumbar el flujo que lo llama
        print(f"[correo] ⚠️ Resend no disponible ({e}); el flujo continúa sin correo.", flush=True)
        return _resultado(False, str(e))
