"""Estados de envío de las notificaciones (2026-10-01, cambios Zeze punto 4).

Cada aviso (cita, liga del entrevistador/evaluador, liga del vehículo, documentos) se registra POR CANAL
(mensaje y correo van por separado: uno nunca depende del otro) con un estado visible:

    Pendiente → Enviado → Entregado        |  Fallido (con el motivo)

* «Enviado» = el proveedor aceptó el mensaje (Meta regresó un `wamid`, Telegram lo publicó en el chat, Resend aceptó
  el correo). «Entregado» llega DESPUÉS por el webhook de estados de Meta (`statuses`: delivered / read) y se guarda en
  `EstadoEnvio` por `wamid`; «failed» lo marca Fallido. Así las filas JSON de cada envío no se reescriben: el estado
  vigente se resuelve al leer (`resolver`).
* «Pendiente» = el aviso quedó registrado pero no se intentó (sin teléfono / correo, o el envío corre aparte).
* Mensajería sin exigir que la persona escriba primero: `whatsapp.enviar_notificacion` usa plantilla aprobada de Meta
  (`META_PLANTILLA_CITA` / `META_PLANTILLA_AVISO`); con Telegram el bot escribe directo al chat ya vinculado.
"""

from datetime import datetime, timezone
from typing import Iterable, List, Optional

PENDIENTE, ENVIADO, ENTREGADO, FALLIDO = "pendiente", "enviado", "entregado", "fallido"
ETIQUETAS = {PENDIENTE: "Pendiente", ENVIADO: "Enviado", ENTREGADO: "Entregado", FALLIDO: "Fallido"}
_ORDEN = {PENDIENTE: 0, ENVIADO: 1, ENTREGADO: 2, FALLIDO: 3}
# Meta → nuestro estado
_META = {"sent": ENVIADO, "delivered": ENTREGADO, "read": ENTREGADO, "failed": FALLIDO}


def estado_inicial(envio: dict) -> str:
    if envio.get("pendiente"):
        return PENDIENTE
    return ENVIADO if envio.get("enviado") else FALLIDO


def fila(destinatario: str, canal: str, envio: dict, liga: str = "", detalle: str = "") -> dict:
    """Fila de envío con su estado. `canal` ∈ mensaje | correo | — ."""
    return {
        "destinatario": destinatario, "canal": canal, "liga": liga, "enviado": bool(envio.get("enviado")),
        "estado": estado_inicial(envio), "wa_id": str(envio.get("wa_id") or ""),
        "proveedor": str(envio.get("proveedor") or ""), "formato": str(envio.get("formato") or ""),
        "detalle": str(envio.get("detalle") or detalle or "")[:300], "fecha": datetime.now(timezone.utc).isoformat(),
    }


def resolver(db, filas: Iterable[dict]) -> List[dict]:
    """Agrega a cada fila su estado vigente (con lo que reportó Meta por webhook) y la etiqueta visible. Las filas
    viejas (antes de 2026-10-01) no traen `estado`: se deduce de `enviado`."""
    filas = [dict(x) for x in (filas or [])]
    ids = [x.get("wa_id") for x in filas if x.get("wa_id")]
    reportados = {}
    if ids and db is not None:
        try:
            from ..models import EstadoEnvio

            reportados = {e.wa_id: e for e in db.query(EstadoEnvio).filter(EstadoEnvio.wa_id.in_(ids)).all()}
        except Exception:  # noqa: BLE001 — tabla del paso NO fatal ausente: se muestra el estado inicial
            reportados = {}
    for x in filas:
        estado = x.get("estado") or (ENVIADO if x.get("enviado") else FALLIDO)
        rep = reportados.get(x.get("wa_id") or "")
        if rep and _ORDEN.get(rep.estado, 0) > _ORDEN.get(estado, 0):
            estado = rep.estado
            if rep.estado == FALLIDO and rep.detalle:
                x["detalle"] = rep.detalle
        x["estado"] = estado
        x["estadoTexto"] = ETIQUETAS.get(estado, estado)
    return filas


def registrar_estados_meta(db, payload: dict) -> int:
    """Webhook de Meta: `statuses` (sent / delivered / read / failed) → `EstadoEnvio` por wamid. Nunca baja de
    estado (un «sent» tardío no pisa un «delivered»). Regresa cuántos se actualizaron."""
    from ..models import EstadoEnvio

    n = 0
    if (payload or {}).get("object") != "whatsapp_business_account":
        return 0
    for entrada in payload.get("entry") or []:
        for cambio in entrada.get("changes") or []:
            for st in (cambio.get("value") or {}).get("statuses") or []:
                wamid, estado = str(st.get("id") or ""), _META.get(str(st.get("status") or ""))
                if not wamid or not estado:
                    continue
                detalle = "; ".join(f"{e.get('code', '')}: {e.get('title') or e.get('message', '')}" for e in st.get("errors") or [])[:300]
                fila_db = db.get(EstadoEnvio, wamid)
                if fila_db is None:
                    db.add(EstadoEnvio(wa_id=wamid, estado=estado, detalle=detalle))
                elif _ORDEN.get(estado, 0) > _ORDEN.get(fila_db.estado, 0):
                    fila_db.estado, fila_db.detalle, fila_db.actualizado_en = estado, detalle or fila_db.detalle, datetime.now(timezone.utc)
                else:
                    continue
                n += 1
    return n


async def correo_candidato(p, asunto_titulo: str, parrafo: str, filas: Optional[list] = None, cta: Optional[tuple] = None) -> dict:
    """Correo al candidato con el layout corporativo, INDEPENDIENTE de la mensajería. Sin correo → pendiente."""
    from ..serial import nombre_empresa_candidato
    from .correo import enviar_correo
    from .plantillas_correo import html_aviso

    if not getattr(p, "correo", ""):
        return {"enviado": False, "pendiente": True, "detalle": "El candidato no tiene correo registrado."}
    try:
        empresa = nombre_empresa_candidato(p.vacante) if p.vacante else ""
        asunto, html = html_aviso(asunto_titulo, parrafo, empresa, filas or [], cta)
        return await enviar_correo(p.correo, asunto, html)
    except Exception as e:  # noqa: BLE001 — un correo caído nunca tumba la acción
        return {"enviado": False, "detalle": str(e)[:200]}
