"""Módulo 1 · Reclutamiento — liga pública del entrevistador (Lote 3).

Contraparte liviana de `entrevistas.py`/`capacitacion.py`: ahí el token abre una sesión
completa con el avatar (varios endpoints, conversación, transcript). Aquí no hay nada que
conversar — es un solo formulario (Resultado, Recomendación, Comentario) de un solo submit,
así que basta con GET (contexto de solo lectura) + POST (el único envío posible). El token es
la credencial, igual que en los otros dos: sin sesión, sin login.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Archivo, EntrevistaHumana, registrar
from ..serial import iso, nombre_empresa_candidato
from ..services import archivos as fs
from ..services import notificaciones

router = APIRouter(prefix="/entrevista-humana", tags=["entrevista-humana"])

RESULTADOS_ENTREVISTA_HUMANA = ("aprobado", "no_aprobado")
RECOMENDACIONES_ENTREVISTA_HUMANA = ("avanzar", "no_avanzar", "segunda_entrevista")


def _por_token(db: Session, token: str, permitir_evaluada: bool = False) -> EntrevistaHumana:
    """POST: si alguien más ya capturó el resultado, se trata como no encontrada — nunca sobreescribe
    (ver candidatos.registrar_resultado_entrevista_humana, el respaldo de RH, para la única vía que sí
    puede corregir). GET (2026-09-19): la liga sigue mostrando el expediente aunque ya esté evaluada."""
    eh = db.query(EntrevistaHumana).filter(EntrevistaHumana.token == token).first()
    if not eh or (eh.resultado_capturado_por and not permitir_evaluada):
        raise HTTPException(404, "Esta liga ya no está disponible.")
    return eh


def _expediente_para_entrevistador(db: Session, eh: EntrevistaHumana) -> dict:
    """2026-09-19: el entrevistador ve el proceso ANTES de evaluar — CV (datos extraídos y archivo),
    análisis de Luna, evaluación de la Entrevista Red Human y documentos del expediente. Solo lectura;
    nada de datos sensibles (ia.DATOS_SENSIBLES_PROHIBIDOS ya los excluye de todo lo generado)."""
    p = eh.postulacion
    c = eh.candidato
    v = p.vacante if p else None
    cv = dict((c.cv_datos or {}) if c else {})
    a = dict((p.analisis or {}) if p else {})
    ultima_ia = None
    for e in reversed(p.entrevistas if p else []):
        if e.estado == "evaluada" and e.evaluacion:
            ultima_ia = e.evaluacion
            break
    archivos = [{"id": x.id, "tipo": x.tipo, "nombre": x.nombre, "mime": x.mime} for x in (c.archivos if c else [])]
    exp = p.expediente if p else None
    documentos = [{"tipo": d.tipo, "estado": d.estado, "obligatorio": d.obligatorio} for d in (exp.documentos if exp else [])]
    return {
        "candidato": {"nombre": c.nombre if c else "", "telefono": (c.telefono if c else "") or "", "correo": (c.correo if c else "") or "", "fuente": (c.fuente if c else "") or ""},
        "vacante": {"titulo": v.titulo if v else "", "requisitos": (v.requisitos if v else "") or "", "perfilIdeal": (v.perfil_ideal if v else "") or "", "empresa": nombre_empresa_candidato(v) if v else ""},
        "etapa": p.etapa if p else "",
        "score": p.score if p else None,
        "cv": {
            "resumen": cv.get("resumen_profesional") or "", "habilidades": cv.get("habilidades") or [], "estudios": cv.get("estudios") or [],
            "idiomas": cv.get("idiomas") or [], "experiencia": cv.get("experiencia") or cv.get("experiencia_laboral") or [], "anosExperiencia": cv.get("anos_experiencia"),
        },
        "analisis": {
            "requisitosCumplidos": a.get("requisitos_cumplidos") or [], "brechas": a.get("brechas") or [], "fortalezas": a.get("fortalezas_cv") or [],
            "alertas": a.get("alertas") or [], "resumen": a.get("resumen") or "",
        },
        "entrevistaIA": {
            "matchPerfil": ultima_ia.get("match_perfil"), "recomendacion": ultima_ia.get("recomendacion") or "", "resumen": ultima_ia.get("resumen") or "",
            "fortalezas": ultima_ia.get("fortalezas") or [], "riesgos": ultima_ia.get("riesgos") or [], "faltante": ultima_ia.get("faltante") or [],
        } if ultima_ia else None,
        "capacitacion": a.get("capacitacion") or [],
        "archivos": archivos,
        "documentos": documentos,
    }


def _es_capacitacion(eh: EntrevistaHumana) -> bool:
    """Flujo operativo v2 (2026-09-30): en una Cuenta operativa la «Entrevista» es la capacitación en tienda y el
    entrevistador es el CAPACITADOR (asistencia + Apto / Requiere seguimiento / No apto)."""
    from ..services import flujo_operativo

    return bool(eh.postulacion and flujo_operativo.es_operativo(eh.postulacion))


@router.get("/publica/{token}")
def publica(token: str, db: Session = Depends(get_db)):
    from ..models import RESULTADOS_CAPACITACION

    eh = _por_token(db, token, permitir_evaluada=True)
    p = eh.postulacion
    if _es_capacitacion(eh):
        if eh.cancelada:
            raise HTTPException(410, "Esta entrevista fue cancelada o reprogramada.")
        return {
            "tipo": "capacitacion",
            "candidato": eh.candidato.nombre if eh.candidato else "",
            "puesto": p.vacante.titulo if p.vacante else "",
            "empresa": nombre_empresa_candidato(p.vacante) if p.vacante else "",
            "fecha": iso(eh.fecha),
            "tienda": eh.tienda,
            "direccion": eh.ubicacion or "",
            "capacitador": eh.entrevistador or "",
            "confirmada": bool(eh.confirmada_en),
            "yaEvaluada": bool(eh.asistencia),
            "realizadaEn": iso(eh.realizada_en),
            "asistencia": eh.asistencia or "",
            "resultado": eh.resultado or "",
            "resultadoEtiqueta": RESULTADOS_CAPACITACION.get(eh.resultado or "", ""),
            "comentario": eh.comentario or "",
            "resultados": [{"valor": k, "texto": v} for k, v in RESULTADOS_CAPACITACION.items()],
        }
    return {
        "candidato": eh.candidato.nombre if eh.candidato else "",
        "puesto": p.vacante.titulo if p and p.vacante else "",
        "fecha": iso(eh.fecha),
        "entrevistador": eh.entrevistador or "",
        "modalidad": eh.modalidad or "",
        "yaEvaluada": bool(eh.resultado_capturado_por),
        "resultado": eh.resultado or "",
        "recomendacion": eh.recomendacion or "",
        "expediente": _expediente_para_entrevistador(db, eh),
    }


@router.get("/publica/{token}/archivo/{archivo_id}")
def archivo_publico(token: str, archivo_id: int, db: Session = Depends(get_db)):
    """CV u otro archivo del candidato para el entrevistador (la liga es la credencial)."""
    eh = _por_token(db, token, permitir_evaluada=True)
    arch = db.query(Archivo).filter(Archivo.id == archivo_id, Archivo.candidato_id == eh.candidato_id).first()
    if not arch or not arch.ruta or not fs.existe(arch.ruta):
        raise HTTPException(404, "Archivo no disponible.")
    return FileResponse(arch.ruta, media_type=arch.mime or "application/octet-stream", filename=arch.nombre or "archivo")


class ResultadoEntrevistaHumanaPublicaIn(BaseModel):
    resultado: str  # aprobado | no_aprobado
    recomendacion: str  # avanzar | no_avanzar | segunda_entrevista
    comentario: str = ""


@router.post("/publica/{token}")
async def enviar_resultado(token: str, datos: ResultadoEntrevistaHumanaPublicaIn, db: Session = Depends(get_db)):
    eh = _por_token(db, token)

    if datos.resultado not in RESULTADOS_ENTREVISTA_HUMANA:
        raise HTTPException(400, f"Resultado inválido. Usa uno de: {', '.join(RESULTADOS_ENTREVISTA_HUMANA)}")
    if datos.recomendacion not in RECOMENDACIONES_ENTREVISTA_HUMANA:
        raise HTTPException(400, f"Recomendación inválida. Usa una de: {', '.join(RECOMENDACIONES_ENTREVISTA_HUMANA)}")
    comentario = datos.comentario.strip()  # 2026-09-19: opcional (antes obligatorio en no_aprobado / segunda)

    # Autocierre (2026-09-19): la entrevista queda realizada y confirmada con evaluación; el ciclo se cierra aquí.
    eh.realizada = True
    eh.resultado = datos.resultado
    eh.recomendacion = datos.recomendacion
    eh.comentario = comentario
    eh.resultado_capturado_por = "entrevistador"
    eh.evaluada_en = datetime.now(timezone.utc)
    # Fase C: actualizar resultado_apto y ultima_actividad_en de la POSTULACIÓN (Fase 2: el
    # Kanban lee de ahí, no de la persona). Se importa aquí para evitar import circular.
    from .candidatos import _recalcular_resultado_apto_y_notificar, _actualizar_ultima_actividad
    p = eh.postulacion
    if not p:
        raise HTTPException(409, "Esta entrevista no está ligada a ninguna postulación (corre scripts/migrar_postulaciones.py).")
    _actualizar_ultima_actividad(p)
    await _recalcular_resultado_apto_y_notificar(db, p, "entrevistador-externo")
    resultados = await notificaciones.disparar(db, "recomendacion_final", p, "entrevistador-externo", eh=eh)
    # 2026-09-19: aviso HTML de «entrevista completada» al candidato/cliente (regla) y a RH (responsable).
    resultados += await notificaciones.disparar(db, "entrevista_completada", p, "entrevistador-externo", eh=eh)
    aviso_rh = await notificaciones.notificar_rh_entrevista_completada(db, p, eh)
    if aviso_rh:
        resultados.append(aviso_rh)
    registrar(
        db, "entrevistador-externo", "entrevista_humana_evaluada_por_liga", "postulacion", p.codigo,
        {"candidato": p.candidato.codigo, "resultado": datos.resultado, "recomendacion": datos.recomendacion, "comentario": comentario, "notificaciones": resultados, "estatus": "realizada_confirmada"},
    )
    db.commit()
    return {"ok": True, "estatus": "realizada", "notificaciones": resultados}


class ResultadoCapacitacionIn(BaseModel):
    asistio: bool
    resultado: str = ""  # favorable | con_observaciones | desfavorable (obligatorio si asistió)
    comentario: str = ""
    capacitador: str = ""  # quién captura (si no, el capacitador asignado)


@router.post("/publica/{token}/capacitacion")
def enviar_resultado_capacitacion(token: str, datos: ResultadoCapacitacionIn, db: Session = Depends(get_db)):
    """El CAPACITADOR registra asistencia + resultado de la capacitación en tienda (flujo operativo). Alimenta la
    MISMA entrevista que la captura manual de RH; una vez registrada, la liga ya no la sobreescribe (RH sí puede
    corregir desde la ficha). No mueve la tarjeta de etapa."""
    from ..services import flujo_operativo

    eh = _por_token(db, token, permitir_evaluada=True)
    if not _es_capacitacion(eh):
        raise HTTPException(404, "Esta liga no es de una entrevista en tienda.")
    if eh.cancelada:
        raise HTTPException(410, "Esta entrevista fue cancelada o reprogramada.")
    if eh.asistencia:
        raise HTTPException(409, "La asistencia ya quedó registrada.")
    quien = (datos.capacitador or eh.entrevistador).strip()
    if not quien:
        raise HTTPException(400, "Escribe tu nombre (queda registrado quién capturó la asistencia).")
    try:
        flujo_operativo.registrar_resultado(db, eh.postulacion, eh, datos.asistio, datos.resultado, datos.comentario,
                                            f"{quien} (entrevistador)", "entrevistador", entrevistador=quien)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return publica(token, db)
