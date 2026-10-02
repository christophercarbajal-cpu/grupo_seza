"""
2026-10-02 — Seguimiento de citas sin confirmar (flujo operativo SEZA).

`revisar_confirmaciones_pendientes` corre cada 15 min (lifespan, app/main.py). Una cita «Pendiente de confirmación»
(entrevista vigente, sin confirmar, sin resultado, fecha a futuro, candidato que no dijo «no puedo») cuyo chat lleva
`CITA_SEGUIMIENTO_HORAS` (default 4) sin movimiento recibe UNA vez: «¿Podrás asistir? Necesitamos tu confirmación».
El envío queda como fila `seguimiento` en `EntrevistaHumana.envios`; se registra ANTES de mandar para no repetirlo.
Reprogramar (nueva fecha) habilita un seguimiento nuevo.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import EntrevistaHumana, Postulacion, registrar
from . import flujo_operativo


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _fecha(fila: dict) -> Optional[datetime]:
    try:
        return _utc(datetime.fromisoformat(fila.get("fecha") or ""))
    except ValueError:
        return None


def necesita_seguimiento(p: Postulacion, eh: EntrevistaHumana, ahora: datetime, horas: float) -> bool:
    if not flujo_operativo.es_operativo(p) or p.etapa != flujo_operativo.ENTREVISTA or not p.activa:
        return False
    if eh.cancelada or eh.realizada or eh.asistencia or eh.confirmada_en or not eh.fecha or _utc(eh.fecha) <= ahora:
        return False
    if flujo_operativo.rechazo_cita(p, eh):
        return False
    filas = eh.envios or []
    citas = [f for f in (_fecha(x) for x in filas if x.get("destinatario") == "candidato" and x.get("canal") == "mensaje") if f]
    if not citas:
        return False
    ultima_cita = max(citas)
    if any((_fecha(x) or ultima_cita) >= ultima_cita for x in filas if x.get("canal") == "seguimiento"):
        return False  # ya se mandó el seguimiento de esta cita (o de su reprogramación)
    limite = ahora - timedelta(hours=horas)
    ultimo_mensaje = max((_utc(m.creado_en) for m in (p.mensajes or []) if m.creado_en), default=None)
    return ultima_cita <= limite and (ultimo_mensaje is None or ultimo_mensaje <= limite)


async def enviar_seguimiento(db: Session, p: Postulacion, eh: EntrevistaHumana) -> dict:
    from ..routers.candidatos import _enviar_whatsapp, guardar_mensaje

    texto = flujo_operativo.SEGUIMIENTO_CONFIRMACION
    fila = flujo_operativo._registrar_envio(eh, "candidato", "seguimiento", {"enviado": False, "detalle": "enviando"})
    db.commit()  # se reclama antes de enviar: si el envío truena no se repite en la siguiente corrida
    envio = await _enviar_whatsapp(p, texto)
    guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
    filas = [dict(x) for x in (eh.envios or [])]
    for x in filas:
        if x.get("canal") == "seguimiento" and x.get("fecha") == fila["fecha"]:
            x.update({"enviado": bool(envio.get("enviado")), "detalle": str(envio.get("detalle") or "")[:300],
                      "wa_id": str(envio.get("wa_id") or ""), "proveedor": str(envio.get("proveedor") or ""),
                      "estado": "enviado" if envio.get("enviado") else "fallido"})
    eh.envios = filas
    registrar(db, "sistema", "cita_seguimiento_confirmacion", "postulacion", p.codigo,
              {"entrevista_humana": eh.id, "enviado": bool(envio.get("enviado"))})
    db.commit()
    return envio


async def revisar_confirmaciones_pendientes() -> int:
    horas = float(settings.cita_seguimiento_horas or 0)
    if horas <= 0:
        return 0
    ahora = datetime.now(timezone.utc)
    enviados = 0
    with SessionLocal() as db:
        pendientes = (
            db.query(EntrevistaHumana)
            .join(Postulacion, Postulacion.id == EntrevistaHumana.postulacion_id)
            .filter(EntrevistaHumana.cancelada.is_(False), EntrevistaHumana.realizada.is_(False),
                    EntrevistaHumana.confirmada_en.is_(None), Postulacion.activa.is_(True))
            .all()
        )
        for eh in pendientes:
            p = eh.postulacion
            if p is None or flujo_operativo.entrevista_actual(p) is not eh or not necesita_seguimiento(p, eh, ahora, horas):
                continue
            try:
                await enviar_seguimiento(db, p, eh)
                enviados += 1
            except Exception as e:  # noqa: BLE001 — una cita con problema no frena las demás
                db.rollback()
                print(f"[citas] seguimiento de {p.codigo} falló: {e}", flush=True)
    if enviados:
        print(f"[citas] {enviados} seguimiento(s) de confirmación enviados.", flush=True)
    return enviados
