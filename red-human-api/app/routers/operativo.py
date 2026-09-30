"""Flujo operativo (demo Grupo SEZA, 2026-09-29) — rutas de RH y del supervisor. La lógica vive en
services/flujo_operativo.py.

* Kanban: `GET /candidatos-flujo` → etapas del Kanban de la Cuenta actual.
* Sesiones de «Capacitación en tienda» con cupo (RH): listar, crear, editar/cancelar, detalle con citados.
* Liga del SUPERVISOR (pública, el token es la credencial): ver la sesión y registrar asistencia + resultado
  (Apto / Requiere seguimiento / No apto) de cada citado.
* Ficha del candidato (RH): citar a una sesión, confirmar la cita, pedir documentos y referencias, aprobar o
  rechazar documentos, marcar referencias como contactadas y registrar el alta.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import cuenta_actual, usuario_actual, usuario_decisor
from ..models import (
    RESULTADOS_CAPACITACION,
    Cuenta,
    Curso,
    Postulacion,
    SesionCapacitacion,
    Usuario,
    Vacante,
    registrar,
)
from ..serial import iso, nombre_empresa_candidato
from ..services import flujo_operativo as flujo
from ..services import modulos_rh
from ..services.configuracion import modo_prueba_activo
from ..services.notificaciones import TZ_MEXICO
from .candidatos import _por_codigo

router = APIRouter(tags=["operativo"])


def _requiere_tablas() -> None:
    modulos_rh.requiere_modulos_rh()


# ------------------------------------------------------------ Kanban


@router.get("/candidatos-flujo")
def flujo_de_la_cuenta(_: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    return {"flujo": cuenta.flujo_candidatos or "rh", "etapas": flujo.etapas_de(cuenta)}


# ------------------------------------------------------------ sesiones (RH)


def _sesion(db: Session, codigo: str, cuenta_id: int) -> SesionCapacitacion:
    s = db.query(SesionCapacitacion).filter(SesionCapacitacion.codigo == codigo, SesionCapacitacion.cuenta_id == cuenta_id).first()
    if not s:
        raise HTTPException(404, "Sesión no encontrada.")
    return s


def _cuando(s: SesionCapacitacion) -> str:
    return s.inicio.astimezone(TZ_MEXICO).strftime("%d/%m/%Y %H:%M") if s.inicio else ""


def _citado_dict(db: Session, ev) -> dict:
    p = db.get(Postulacion, ev.postulacion_id)
    return {
        "evaluacion": ev.codigo,
        "postulacion": p.codigo if p else "",
        "nombre": p.nombre if p else "",
        "vacante": p.vacante.titulo if p and p.vacante else "",
        "confirmada": bool(ev.cita_confirmada_en),
        "asistencia": ev.asistencia or "",
        "resultado": ev.dictamen or "",
        "resultadoEtiqueta": RESULTADOS_CAPACITACION.get(ev.dictamen, ""),
        "comentario": ev.comentario_revision or "",
        "estado": ev.estado,
    }


def sesion_dict(db: Session, s: SesionCapacitacion, detalle: bool = False) -> dict:
    from ..config import settings

    curso = db.get(Curso, s.curso_induccion_id) if s.curso_induccion_id else None
    vac = db.get(Vacante, s.vacante_id) if s.vacante_id else None
    ocupados = flujo.lugares_ocupados(db, s)
    base = {
        "codigo": s.codigo,
        "nombre": s.nombre,
        "tienda": s.tienda,
        "direccion": s.direccion,
        "inicio": iso(s.inicio),
        "inicioTexto": _cuando(s),
        "duracionMin": s.duracion_min,
        "cupo": s.cupo,
        "ocupados": ocupados,
        "disponibles": max(0, s.cupo - ocupados),
        "supervisorNombre": s.supervisor_nombre,
        "supervisorTelefono": s.supervisor_telefono,
        "indicaciones": s.indicaciones,
        "vacante": vac.codigo if vac else None,
        "vacanteTitulo": f"{vac.titulo} · {vac.ubicacion}" if vac else "",
        "cursoInduccion": curso.codigo if curso else None,
        "cursoInduccionTitulo": curso.titulo if curso else "",
        "estado": s.estado,
        "ligaSupervisor": f"{settings.app_url}/sesion/{s.token}",
    }
    if detalle:
        base["citados"] = [_citado_dict(db, ev) for ev in flujo.inscritos(db, s)]
    return base


class SesionIn(BaseModel):
    tienda: str
    direccion: str = ""
    inicio: str  # ISO local de México (2026-10-02T09:00) o con zona
    duracion_min: int = 120
    cupo: int = 10
    supervisor_nombre: str = ""
    supervisor_telefono: str = ""
    indicaciones: str = ""
    vacante: Optional[str] = None  # VAC-#### (opcional)
    curso_induccion: Optional[str] = None  # CUR-#### (opcional)


def _fecha(valor: str) -> datetime:
    try:
        dt = datetime.fromisoformat(valor)
    except ValueError:
        raise HTTPException(400, "Fecha y hora inválidas (usa 2026-10-02T09:00).")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_MEXICO)
    return dt.astimezone(timezone.utc)


def _aplicar(db: Session, s: SesionCapacitacion, datos: SesionIn, cuenta_id: int) -> None:
    if not datos.tienda.strip():
        raise HTTPException(400, "Indica la tienda o lugar de la capacitación.")
    if datos.cupo < 1 or datos.cupo > 200:
        raise HTTPException(400, "El cupo debe estar entre 1 y 200.")
    s.tienda, s.direccion = datos.tienda.strip()[:200], datos.direccion.strip()[:300]
    s.inicio = _fecha(datos.inicio)
    s.duracion_min = max(15, min(datos.duracion_min, 720))
    s.cupo = datos.cupo
    s.supervisor_nombre, s.supervisor_telefono = datos.supervisor_nombre.strip()[:150], re.sub(r"\D", "", datos.supervisor_telefono)[-10:]
    s.indicaciones = datos.indicaciones.strip()[:1000]
    s.vacante_id = None
    if datos.vacante:
        v = db.query(Vacante).filter(Vacante.codigo == datos.vacante, Vacante.cuenta_id == cuenta_id).first()
        if not v:
            raise HTTPException(400, "La vacante no existe en esta Cuenta.")
        s.vacante_id = v.id
    s.curso_induccion_id = None
    if datos.curso_induccion:
        c = db.query(Curso).filter(Curso.codigo == datos.curso_induccion, Curso.cuenta_id == cuenta_id).first()
        if not c:
            raise HTTPException(400, "El curso de inducción no existe en esta Cuenta.")
        s.curso_induccion_id = c.id


@router.get("/sesiones-capacitacion", dependencies=[Depends(_requiere_tablas)])
def listar_sesiones(incluir_pasadas: bool = False, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual),
                    cuenta: Cuenta = Depends(cuenta_actual)):
    q = db.query(SesionCapacitacion).filter(SesionCapacitacion.cuenta_id == cuenta.id)
    if not incluir_pasadas:
        q = q.filter(SesionCapacitacion.estado == "programada")
    return [sesion_dict(db, s) for s in q.order_by(SesionCapacitacion.inicio).all()]


@router.post("/sesiones-capacitacion", status_code=201, dependencies=[Depends(_requiere_tablas)])
def crear_sesion(datos: SesionIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                 cuenta: Cuenta = Depends(cuenta_actual)):
    s = SesionCapacitacion(codigo="TMP", cuenta_id=cuenta.id, token=secrets.token_urlsafe(24), creada_por=u.nombre)
    _aplicar(db, s, datos, cuenta.id)
    db.add(s)
    db.flush()
    s.codigo = f"SES-{300 + s.id}"
    registrar(db, u.nombre, "sesion_capacitacion_creada", "sesion", s.codigo, {"tienda": s.tienda, "cupo": s.cupo})
    db.commit()
    return sesion_dict(db, s, detalle=True)


@router.get("/sesiones-capacitacion/{codigo}", dependencies=[Depends(_requiere_tablas)])
def ver_sesion(codigo: str, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    return sesion_dict(db, _sesion(db, codigo, cuenta.id), detalle=True)


@router.patch("/sesiones-capacitacion/{codigo}", dependencies=[Depends(_requiere_tablas)])
def editar_sesion(codigo: str, datos: SesionIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                  cuenta: Cuenta = Depends(cuenta_actual)):
    s = _sesion(db, codigo, cuenta.id)
    _aplicar(db, s, datos, cuenta.id)
    if s.cupo < flujo.lugares_ocupados(db, s):
        raise HTTPException(409, "El cupo no puede ser menor que el número de citados.")
    registrar(db, u.nombre, "sesion_capacitacion_editada", "sesion", s.codigo, {})
    db.commit()
    return sesion_dict(db, s, detalle=True)


class EstadoSesionIn(BaseModel):
    estado: str  # programada | cerrada | cancelada


@router.post("/sesiones-capacitacion/{codigo}/estado", dependencies=[Depends(_requiere_tablas)])
def estado_sesion(codigo: str, datos: EstadoSesionIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                  cuenta: Cuenta = Depends(cuenta_actual)):
    s = _sesion(db, codigo, cuenta.id)
    if datos.estado not in ("programada", "cerrada", "cancelada"):
        raise HTTPException(400, "Estado inválido.")
    s.estado = datos.estado
    registrar(db, u.nombre, f"sesion_capacitacion_{datos.estado}", "sesion", s.codigo, {})
    db.commit()
    return sesion_dict(db, s, detalle=True)


# ------------------------------------------------------------ liga del supervisor (pública)


def _por_token(db: Session, token: str) -> SesionCapacitacion:
    s = db.query(SesionCapacitacion).filter(SesionCapacitacion.token == token).first()
    if not s:
        raise HTTPException(404, "Esta liga no es válida.")
    if s.estado == "cancelada":
        raise HTTPException(410, "Esta sesión fue cancelada.")
    return s


@router.get("/sesiones-capacitacion/publica/{token}", dependencies=[Depends(_requiere_tablas)])
def ver_sesion_supervisor(token: str, db: Session = Depends(get_db)):
    s = _por_token(db, token)
    cuenta = db.get(Cuenta, s.cuenta_id)
    vac = db.get(Vacante, s.vacante_id) if s.vacante_id else None
    return {
        "nombre": s.nombre, "tienda": s.tienda, "direccion": s.direccion, "inicioTexto": _cuando(s),
        "supervisor": s.supervisor_nombre, "empresa": nombre_empresa_candidato(vac) if vac else (cuenta.nombre_comercial if cuenta else ""),
        "cupo": s.cupo, "estado": s.estado,
        "resultados": [{"valor": k, "texto": v} for k, v in RESULTADOS_CAPACITACION.items()],
        # el supervisor solo ve nombre, vacante y lo que él registra (nada de teléfonos ni documentos)
        "citados": [{k: c[k] for k in ("evaluacion", "nombre", "vacante", "confirmada", "asistencia", "resultado", "resultadoEtiqueta", "comentario")}
                    for c in (_citado_dict(db, ev) for ev in flujo.inscritos(db, s))],
    }


class AsistenciaIn(BaseModel):
    evaluacion: str
    asistio: bool
    resultado: str = ""  # favorable | con_observaciones | desfavorable (obligatorio si asistió)
    comentario: str = ""
    supervisor: str = ""


@router.post("/sesiones-capacitacion/publica/{token}/asistencia", dependencies=[Depends(_requiere_tablas)])
def registrar_asistencia(token: str, datos: AsistenciaIn, db: Session = Depends(get_db)):
    from ..models import EvaluacionCandidato

    s = _por_token(db, token)
    ev = db.query(EvaluacionCandidato).filter(EvaluacionCandidato.codigo == datos.evaluacion, EvaluacionCandidato.sesion_id == s.id).first()
    if not ev:
        raise HTTPException(404, "Esa persona no está citada a esta sesión.")
    if ev.estado == "revisada" or ev.asistencia:
        raise HTTPException(409, "La asistencia de esta persona ya quedó registrada.")
    supervisor = (datos.supervisor or s.supervisor_nombre).strip()
    if not supervisor:
        raise HTTPException(400, "Escribe tu nombre (queda registrado quién capturó la asistencia).")
    if datos.asistio and datos.resultado not in RESULTADOS_CAPACITACION:
        raise HTTPException(400, "Elige el resultado: Apto, Requiere seguimiento o No apto.")
    if datos.asistio and datos.resultado in ("con_observaciones", "desfavorable") and not datos.comentario.strip():
        raise HTTPException(400, "Escribe un comentario que explique el resultado.")
    flujo.registrar_asistencia(db, ev, datos.asistio, datos.resultado, datos.comentario.strip(), supervisor)
    db.commit()
    return ver_sesion_supervisor(token, db)


# ------------------------------------------------------------ ficha del candidato (RH)


def _operativo(db: Session, codigo: str, cuenta_id: int) -> Postulacion:
    p = _por_codigo(db, codigo, cuenta_id)
    if not flujo.es_operativo(p):
        raise HTTPException(409, "Esta postulación no usa el flujo operativo.")
    return p


def panel_dict(db: Session, p: Postulacion) -> dict:
    ev = flujo.evaluacion_capacitacion(db, p)
    s = db.get(SesionCapacitacion, ev.sesion_id) if ev and ev.sesion_id else None
    induccion = next((h for h in reversed(p.historial or []) if h.get("evento") == "cita_confirmada"), None)
    e = p.expediente
    faltan = flujo.faltantes_para_alta(p)
    col = None
    if e and e.estado == "alta":
        from ..models import Colaborador

        c = db.query(Colaborador).filter(Colaborador.expediente_id == e.id).first()
        col = {"codigo": c.codigo, "nombre": c.nombre} if c else None
    return {
        "etapa": p.etapa,
        "etapas": flujo.etapas_de(p.cuenta),
        "capacitacion": {
            "evaluacion": ev.codigo if ev else None,
            "nombre": ev.nombre if ev else "Capacitación en tienda",
            "estado": ev.estado if ev else None,
            "confirmada": bool(ev and ev.cita_confirmada_en),
            "confirmadaEn": iso(ev.cita_confirmada_en) if ev else None,
            "asistencia": ev.asistencia if ev else "",
            "resultado": ev.dictamen if ev else "",
            "resultadoEtiqueta": RESULTADOS_CAPACITACION.get(ev.dictamen, "") if ev else "",
            "dictamenInterno": {"favorable": "Favorable", "con_observaciones": "Con observaciones", "desfavorable": "Desfavorable"}.get(ev.dictamen, "") if ev else "",
            "comentario": (ev.comentario_revision or ev.motivo_fallida) if ev else "",
            "registradoPor": ev.revisada_por if ev else "",
            "sesion": sesion_dict(db, s) if s else None,
            "induccion": induccion["texto"] if induccion else "",
        },
        "expediente": {
            "id": e.id,
            "liga": flujo.liga_expediente(e),
            "progreso": e.progreso,
            "documentos": [
                {"tipo": d.tipo, "estado": d.estado, "aprobado": d.aprobado, "archivo": bool(d.archivo), "notas": d.notas_ia or "",
                 "estadoSimple": flujo.estado_documento(d), "revisadoPor": d.revisado_por or ""}
                for d in e.documentos if not d.interno and d.estado != "no_aplica"
            ],
            "referencias": e.referencias or [],
            "resultadosReferencia": {"contactada": flujo.RESULTADOS_REFERENCIA[True], "noContactada": flujo.RESULTADOS_REFERENCIA[False]},
        } if e else None,
        "faltantesAlta": faltan,
        "listoParaAlta": not faltan,
        "alta": {"por": e.alta_autorizada_por, "en": iso(e.alta_fecha), "colaborador": col} if e and e.estado == "alta" else None,
    }


@router.get("/candidatos/{codigo}/operativo", dependencies=[Depends(_requiere_tablas)])
def ver_panel(codigo: str, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    return panel_dict(db, _operativo(db, codigo, cuenta.id))


class CitarIn(BaseModel):
    sesion: str


@router.post("/candidatos/{codigo}/operativo/citar", dependencies=[Depends(_requiere_tablas)])
async def citar(codigo: str, datos: CitarIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                cuenta: Cuenta = Depends(cuenta_actual)):
    from ..services import vehiculo as vehiculo_srv

    p = _operativo(db, codigo, cuenta.id)
    if not p.activa:
        raise HTTPException(409, "La postulación está cerrada.")
    citable, motivo = vehiculo_srv.puede_citar(p)
    if not citable and not modo_prueba_activo(db):
        raise HTTPException(409, motivo)
    s = _sesion(db, datos.sesion, cuenta.id)
    if s.estado != "programada":
        raise HTTPException(409, "Esa sesión ya no está programada.")
    ev = flujo.evaluacion_capacitacion(db, p)
    ya_en_esta = bool(ev and ev.sesion_id == s.id and ev.estado not in ("revisada", "fallida"))
    if not ya_en_esta and flujo.lugares_ocupados(db, s) >= s.cupo:
        raise HTTPException(409, f"La sesión {s.codigo} ya no tiene cupo ({s.cupo} lugares).")
    r = await flujo.citar(db, p, s, u.nombre)
    db.commit()
    return {**panel_dict(db, p), "whatsapp": r["whatsapp"]}


@router.post("/candidatos/{codigo}/operativo/confirmar-cita", dependencies=[Depends(_requiere_tablas)])
async def confirmar_cita(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                         cuenta: Cuenta = Depends(cuenta_actual)):
    """RH confirma por el candidato (p. ej. confirmó por llamada). Mismo efecto que su «Sí» por WhatsApp."""
    p = _operativo(db, codigo, cuenta.id)
    try:
        r = await flujo.confirmar_cita(db, p, u.nombre)
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return {**panel_dict(db, p), "induccion": r["induccion"]}


@router.post("/candidatos/{codigo}/operativo/solicitar-documentos", dependencies=[Depends(_requiere_tablas)])
async def solicitar_documentos(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                               cuenta: Cuenta = Depends(cuenta_actual)):
    p = _operativo(db, codigo, cuenta.id)
    ev = flujo.evaluacion_capacitacion(db, p)
    prueba = modo_prueba_activo(db)
    if not prueba and not (ev and ev.estado == "revisada"):
        raise HTTPException(409, "Primero el supervisor debe registrar la capacitación.")
    if not prueba and ev and ev.dictamen == "desfavorable":
        raise HTTPException(409, "La capacitación quedó como «No apto»: RH decide si descarta o reprograma; no se piden documentos.")
    if not p.consentimiento:
        raise HTTPException(409, "Falta el consentimiento de privacidad del candidato.")
    r = await flujo.solicitar_documentos_referencias(db, p, u.nombre)
    db.commit()
    return {**panel_dict(db, p), "liga": r["liga"], "whatsapp": r["whatsapp"]}


class DocumentoIn(BaseModel):
    tipo: str
    estado: str  # aprobado | rechazado
    notas: str = ""


@router.post("/candidatos/{codigo}/operativo/documentos", dependencies=[Depends(_requiere_tablas)])
async def revisar_documento(codigo: str, datos: DocumentoIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                            cuenta: Cuenta = Depends(cuenta_actual)):
    """Revisar (aprobar) / pedir corrección (rechazar con motivo) reutiliza la revisión de siempre
    (`contratacion.marcar_documento`) y después revisa si ya está «Listo para alta». Al pedir corrección se le
    avisa al candidato por WhatsApp con el motivo y su misma liga (best-effort: si el envío falla, la revisión
    queda guardada y el resultado viaja en `whatsapp`)."""
    from .candidatos import _enviar_whatsapp, guardar_mensaje
    from .contratacion import EstadoDocIn, marcar_documento

    p = _operativo(db, codigo, cuenta.id)
    if not p.expediente:
        raise HTTPException(409, "Primero pide documentos y referencias.")
    if datos.estado == "rechazado" and not datos.notas.strip():
        raise HTTPException(400, "Indica qué debe corregir el candidato.")
    marcar_documento(p.expediente.id, EstadoDocIn(tipo=datos.tipo, estado=datos.estado, notas=datos.notas), db, u, cuenta)
    db.refresh(p)
    envio = None
    if datos.estado == "rechazado":
        nombre = (p.nombre or "").split(" ")[0] or "hola"
        texto = (f"Hola {nombre}, tu documento «{datos.tipo}» requiere corrección: {datos.notas.strip()}\n"
                 f"Vuelve a subirlo aquí, por favor: {flujo.liga_expediente(p.expediente)}")
        try:
            envio = await _enviar_whatsapp(p, texto)
            guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
        except Exception as e:  # noqa: BLE001
            envio = {"enviado": False, "detalle": str(e)[:300]}
        flujo.nota(p, "documento_correccion", f"«{datos.tipo}» requiere corrección: {datos.notas.strip()}", u.nombre)
    flujo.revisar_listo(db, p, u.nombre)
    db.commit()
    return {**panel_dict(db, p), "whatsapp": envio}


class ReferenciaIn(BaseModel):
    contactada: bool
    resultado: str = ""
    fecha: Optional[str] = None  # fecha y hora de la llamada (hora de México si viene sin zona); vacía = ahora
    nota: str = ""  # observaciones


@router.post("/candidatos/{codigo}/operativo/referencias/{indice}", dependencies=[Depends(_requiere_tablas)])
def marcar_referencia(codigo: str, indice: int, datos: ReferenciaIn, db: Session = Depends(get_db),
                      u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """El reclutador registra a mano una llamada a la referencia: fecha, si se contactó, resultado y
    observaciones. Queda en el historial de llamadas de la referencia, en la postulación y en bitácora."""
    p = _operativo(db, codigo, cuenta.id)
    e = p.expediente
    if not e or not (0 <= indice < len(e.referencias or [])):
        raise HTTPException(404, "Referencia no encontrada.")
    fecha = None
    if datos.fecha:
        try:
            fecha = datetime.fromisoformat(datos.fecha)
        except ValueError:
            raise HTTPException(400, "La fecha de la llamada no es válida.")
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=TZ_MEXICO)
        if fecha > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise HTTPException(400, "La fecha de la llamada no puede ser futura.")
    nota = datos.nota.strip()
    try:
        r = flujo.marcar_referencia(e, indice, datos.contactada, nota, u.nombre, resultado=datos.resultado.strip(), fecha=fecha)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    resumen = "contactada" if datos.contactada else "NO contactada"
    if r["resultado"]:
        resumen += f" · {r['resultado']}"
    flujo.nota(p, "referencia_contactada" if datos.contactada else "referencia_pendiente",
               f"Llamada a referencia {r['nombre']} ({r['parentesco']}): {resumen}" + (f" — {nota}" if nota else ""), u.nombre)
    registrar(db, u.nombre, "referencia_llamada", "postulacion", p.codigo,
              {"indice": indice, "contactada": datos.contactada, "resultado": r["resultado"], "fecha": r["fecha_llamada"]})
    flujo.revisar_listo(db, p, u.nombre)
    db.commit()
    return panel_dict(db, p)


@router.post("/candidatos/{codigo}/operativo/alta", dependencies=[Depends(_requiere_tablas)])
def registrar_alta(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                   cuenta: Cuenta = Depends(cuenta_actual)):
    p = _operativo(db, codigo, cuenta.id)
    try:
        flujo.registrar_alta(db, p, u, modo_prueba_activo(db))
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return panel_dict(db, p)
