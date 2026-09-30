"""Módulo 2 · Contratación e integración — liga pública para que el candidato suba sus
documentos (Lote 4).

Contraparte liviana de `entrevistas.py`/`capacitacion.py`, mismo espíritu que
`entrevista_humana.py`: sin sesión, el token es la credencial. Diferencia importante frente al
de `EntrevistaHumana` (un solo uso): este token NO se invalida tras la primera subida — el
candidato puede volver varias veces hasta completar todos los documentos obligatorios. Solo se
cierra cuando el expediente llega a `estado == "alta"` (ver `subir_documento_interno` en
`contratacion.py`, que ya rechaza cambios en ese estado — mismo guard para RH y para el
candidato, sin excepción de Modo Prueba).
"""

import re
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Expediente
from ..models import registrar
from ..services import flujo_operativo
from ..services.pdf import pdf_carta_intencion
from .contratacion import _datos_carta_intencion, subir_documento_interno

router = APIRouter(prefix="/expedientes", tags=["expedientes-publico"])


def _por_token(db: Session, token: str) -> Expediente:
    e = db.query(Expediente).filter(Expediente.token == token).first()
    if not e:
        raise HTTPException(404, "Esta liga no es válida.")
    return e


@router.get("/publica/{token}")
def publica(token: str, db: Session = Depends(get_db)):
    e = _por_token(db, token)
    return {
        "candidato": e.candidato.nombre if e.candidato else "",
        "puesto": e.puesto,
        "estado": e.estado,
        "documentos": [
            {"tipo": d.tipo, "estado": d.estado, "obligatorio": d.obligatorio,
             # qué debe corregir (lo escribió RH al pedir corrección) — solo en rechazados
             "motivo": (d.notas_ia or "")[:300] if d.estado == "rechazado" else ""} for d in e.documentos
            if d.estado != "no_aplica" and not d.interno  # Onboarding v2: ni «No aplica» ni documentos internos de RH
        ],
        # 2026-09-19: la carta de intención se descarga desde la misma liga (la comparte RH por WhatsApp)
        "cartaDisponible": bool(e.puesto and e.sueldo),
        # Demo SEZA (flujo operativo): 3 referencias personales que captura el propio candidato
        "pideReferencias": _pide_referencias(e),
        "referencias": [{k: r.get(k, "") for k in ("nombre", "telefono", "parentesco")} for r in (e.referencias or [])],
        "parentescos": flujo_operativo.PARENTESCOS,
        "referenciasRequeridas": flujo_operativo.REFERENCIAS_REQUERIDAS,
    }


def _pide_referencias(e: Expediente) -> bool:
    return bool(e.postulacion and flujo_operativo.es_operativo(e.postulacion))


class ReferenciaIn(BaseModel):
    nombre: str
    telefono: str
    parentesco: str


class ReferenciasIn(BaseModel):
    referencias: List[ReferenciaIn]


@router.post("/publica/{token}/referencias")
def guardar_referencias(token: str, datos: ReferenciasIn, db: Session = Depends(get_db)):
    """El candidato captura sus 3 referencias (nombre, teléfono a 10 dígitos, parentesco). RH después las
    marca como contactadas desde la ficha."""
    e = _por_token(db, token)
    if not _pide_referencias(e):
        raise HTTPException(404, "Este expediente no pide referencias.")
    if e.estado == "alta":
        raise HTTPException(409, "Tu expediente ya está cerrado.")
    n = flujo_operativo.REFERENCIAS_REQUERIDAS
    if len(datos.referencias) != n:
        raise HTTPException(400, f"Necesitamos exactamente {n} referencias.")
    limpias, telefonos = [], set()
    for i, r in enumerate(datos.referencias, start=1):
        tel = re.sub(r"\D", "", r.telefono)[-10:]
        if not r.nombre.strip() or len(tel) != 10:
            raise HTTPException(400, f"Referencia {i}: escribe el nombre completo y un teléfono de 10 dígitos.")
        if r.parentesco not in flujo_operativo.PARENTESCOS:
            raise HTTPException(400, f"Referencia {i}: elige el parentesco.")
        if tel in telefonos or (e.candidato and tel == (e.candidato.telefono or "")):
            raise HTTPException(400, f"Referencia {i}: cada referencia debe tener un teléfono distinto (y no el tuyo).")
        telefonos.add(tel)
        limpias.append({"nombre": r.nombre.strip()[:150], "telefono": tel, "parentesco": r.parentesco})
    flujo_operativo.guardar_referencias(db, e, limpias)
    p = e.postulacion
    registrar(db, "candidato", "referencias_capturadas", "postulacion", p.codigo, {"n": len(limpias)})
    flujo_operativo.nota(p, "referencias_capturadas", "El candidato capturó sus 3 referencias", "candidato")
    flujo_operativo.revisar_listo(db, p, "candidato")
    db.commit()
    return publica(token, db)


@router.get("/publica/{token}/carta-intencion")
def carta_publica(token: str, db: Session = Depends(get_db)):
    """PDF de la carta de intención para el candidato (la liga es la credencial)."""
    e = _por_token(db, token)
    if not (e.puesto and e.sueldo):
        raise HTTPException(404, "Tu carta todavía no está lista.")
    try:
        pdf = pdf_carta_intencion(_datos_carta_intencion(e))
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(503, f"No se pudo generar la carta: {ex}")
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="carta-intencion.pdf"'})


@router.post("/publica/{token}/documentos")
async def subir(
    token: str, tipo: str = Form(...), archivo: UploadFile = File(...), db: Session = Depends(get_db)
):
    e = _por_token(db, token)
    resultado = await subir_documento_interno(db, e, tipo, archivo, subido_por="candidato")
    if e.postulacion and flujo_operativo.es_operativo(e.postulacion):  # Modo Prueba aprueba solo: puede quedar listo
        db.refresh(e)
        flujo_operativo.revisar_listo(db, e.postulacion, "candidato")
        db.commit()
    return resultado
