"""Evaluaciones y verificaciones del candidato + catálogo de Pruebas psicométricas (2026-09-28).

* Catálogo (Configuración → Pruebas psicométricas): identificador interno, nombre visible, descripción, puestos
  sugeridos, modo (Integrada / Enlace externo / Carga manual), proveedor, identificador en el proveedor y estado.
* Ficha → «…» → «Agregar evaluación o verificación»: Psicométrica, Técnica o caso práctico, Referencias, Médico,
  Socioeconómico u Otra. Se cuelga de la POSTULACIÓN y nunca mueve la columna del pipeline.
* Consentimientos antes de enviar/asignar (ver services/evaluaciones.py). El estudio médico exige consentimiento
  EXPRESO y POR ESCRITO por medio electrónico: liga pública `/consentimiento/{token}` donde la persona lee el texto,
  escribe su nombre y acepta; se guarda el texto exacto, la aceptación y la evidencia (y la bitácora hash-encadenada).
* Informe médico COMPLETO solo para quien tiene permiso (`Usuario.puede_ver_informe_medico`); el resto ve estado y
  dictamen. Sin conexiones a proveedores todavía: el modo Integrada se avanza a mano (simulado).
* 2026-09-30: evaluador asignado (interno = Usuario de la Cuenta | externo con sus datos) y cita opcional. Su liga
  pública `/evaluacion/{token}` (o la captura manual de RH, siempre disponible) registra el resultado de la MISMA
  evaluación. Toda liga se genera al crear la evaluación y se muestra aunque el envío falle.
"""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import cuenta_actual, usuario_actual, usuario_decisor
from ..models import (
    MODOS_PRUEBA,
    TEXTO_CONSENTIMIENTO_MEDICO,
    TIPOS_EVALUACION,
    Cuenta,
    EvaluacionCandidato,
    Postulacion,
    PruebaPsicometrica,
    Usuario,
    registrar,
)
from ..serial import evaluacion_candidato_dict, nombre_empresa_candidato, prueba_psicometrica_dict
from ..services import evaluaciones as sev
from ..services.modulos_rh import requiere_modulos_rh

router = APIRouter(prefix="/evaluaciones", tags=["evaluaciones"], dependencies=[Depends(requiere_modulos_rh)])


def _norm(s: str) -> str:
    from ..services.onboarding import norm

    return norm(s)


# ---------------- Catálogo: Pruebas psicométricas ----------------

def _prueba(db: Session, pid: int, cuenta_id: int) -> PruebaPsicometrica:
    pr = db.query(PruebaPsicometrica).filter(PruebaPsicometrica.id == pid, PruebaPsicometrica.cuenta_id == cuenta_id).first()
    if not pr:
        raise HTTPException(404, "Prueba psicométrica no encontrada.")
    return pr


class PruebaIn(BaseModel):
    clave: str
    nombre: str
    descripcion: str = ""
    puestos: List[str] = []
    modo: str = "manual"
    proveedor: str = ""
    id_proveedor: str = ""
    url: str = ""
    activa: bool = True


class EditarPruebaIn(BaseModel):
    clave: Optional[str] = None
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    puestos: Optional[List[str]] = None
    modo: Optional[str] = None
    proveedor: Optional[str] = None
    id_proveedor: Optional[str] = None
    url: Optional[str] = None
    activa: Optional[bool] = None


def _validar_prueba(db: Session, cuenta_id: int, pr: PruebaPsicometrica) -> None:
    pr.clave = (pr.clave or "").strip()[:60]
    pr.nombre = (pr.nombre or "").strip()[:200]
    if not pr.clave:
        raise HTTPException(400, "Captura el identificador interno de la prueba.")
    if not pr.nombre:
        raise HTTPException(400, "Captura el nombre visible de la prueba.")
    if pr.modo not in MODOS_PRUEBA:
        raise HTTPException(400, "Modo inválido: usa integrada, enlace o manual.")
    if pr.modo == "enlace" and not (pr.url or "").strip().lower().startswith(("http://", "https://")):
        raise HTTPException(400, "El modo «Enlace externo» necesita la liga de la prueba (https://…).")
    if pr.modo == "integrada" and not (pr.proveedor or "").strip():
        raise HTTPException(400, "El modo «Integrada» necesita el proveedor.")
    pr.puestos = [p.strip()[:200] for p in (pr.puestos or []) if p and p.strip()]
    otra = (
        db.query(PruebaPsicometrica)
        .filter(PruebaPsicometrica.cuenta_id == cuenta_id, PruebaPsicometrica.id != (pr.id or 0))
        .all()
    )
    if any(_norm(o.clave) == _norm(pr.clave) for o in otra):
        raise HTTPException(409, f"Ya existe una prueba con el identificador «{pr.clave}».")


@router.get("/pruebas")
def listar_pruebas(incluir_inactivas: bool = False, puesto: str = "", db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    """Con `puesto` las sugeridas para ese puesto van primero (`sugerida=true`)."""
    q = db.query(PruebaPsicometrica).filter(PruebaPsicometrica.cuenta_id == cuenta.id)
    if not incluir_inactivas:
        q = q.filter(PruebaPsicometrica.activa.is_(True))
    np_ = _norm(puesto)
    salida = []
    for pr in q.all():
        d = prueba_psicometrica_dict(pr)
        d["sugerida"] = bool(np_) and any(_norm(x) == np_ for x in pr.puestos or [])
        salida.append(d)
    return sorted(salida, key=lambda d: (not d["sugerida"], _norm(d["nombre"])))


@router.post("/pruebas", status_code=201)
def crear_prueba(datos: PruebaIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    pr = PruebaPsicometrica(cuenta_id=cuenta.id, creado_por=u.nombre, **datos.model_dump())
    _validar_prueba(db, cuenta.id, pr)
    db.add(pr)
    db.flush()
    registrar(db, u.nombre, "prueba_psicometrica_creada", "evaluaciones", str(pr.id), {"clave": pr.clave, "modo": pr.modo, "correo_rh": u.correo})
    db.commit()
    return prueba_psicometrica_dict(pr)


@router.patch("/pruebas/{pid}")
def editar_prueba(pid: int, datos: EditarPruebaIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    pr = _prueba(db, pid, cuenta.id)
    for campo, valor in datos.model_dump(exclude_none=True).items():
        setattr(pr, campo, valor)
    try:
        _validar_prueba(db, cuenta.id, pr)
    except HTTPException:
        db.rollback()
        raise
    registrar(db, u.nombre, "prueba_psicometrica_editada", "evaluaciones", str(pr.id), {"clave": pr.clave, "correo_rh": u.correo})
    db.commit()
    return prueba_psicometrica_dict(pr)


@router.delete("/pruebas/{pid}")
def inactivar_prueba(pid: int, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Baja lógica: queda Inactiva; las evaluaciones ya asignadas con ella no cambian."""
    pr = _prueba(db, pid, cuenta.id)
    pr.activa = False
    registrar(db, u.nombre, "prueba_psicometrica_inactivada", "evaluaciones", str(pr.id), {"clave": pr.clave, "correo_rh": u.correo})
    db.commit()
    return prueba_psicometrica_dict(pr)


# ---------------- Evaluaciones de una postulación ----------------

def _postulacion(db: Session, codigo: str, cuenta_id: int) -> Postulacion:
    from .candidatos import _por_codigo

    return _por_codigo(db, codigo, cuenta_id)


def _evaluacion(db: Session, codigo: str, cuenta_id: int) -> EvaluacionCandidato:
    ev = db.query(EvaluacionCandidato).filter(EvaluacionCandidato.codigo == codigo, EvaluacionCandidato.cuenta_id == cuenta_id).first()
    if not ev:
        raise HTTPException(404, "Evaluación no encontrada.")
    return ev


def _post_de(db: Session, ev: EvaluacionCandidato) -> Optional[Postulacion]:
    return db.get(Postulacion, ev.postulacion_id)


def evaluaciones_de(db: Session, p: Postulacion) -> List[EvaluacionCandidato]:
    return db.query(EvaluacionCandidato).filter(EvaluacionCandidato.postulacion_id == p.id).order_by(EvaluacionCandidato.id).all()


@router.get("/postulaciones/{codigo}")
def listar_evaluaciones(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    p = _postulacion(db, codigo, cuenta.id)
    evs = evaluaciones_de(db, p)
    cambio = [sev.refrescar_consentimiento(ev, p) for ev in evs]  # el consentimiento pudo llegar por otro medio
    cambio += [sev.asegurar_token(ev) for ev in evs]  # registros previos reciben su liga de evaluador
    if any(cambio):
        db.commit()
    return [evaluacion_candidato_dict(ev, u, db) for ev in evs]


class EvaluadorIn(BaseModel):
    evaluador_tipo: str = ""  # "" (sin asignar) | interno | externo
    evaluador_usuario_id: Optional[int] = None
    evaluador_nombre: str = ""
    evaluador_telefono: str = ""
    evaluador_correo: str = ""
    cita_fecha: str = ""  # 2026-10-02 (opcional)
    cita_hora: str = ""  # 09:00
    cita_lugar: str = ""


class AgregarEvaluacionIn(EvaluadorIn):
    tipo: str
    nombre: str = ""  # psicométrica sin catálogo: «Nombre de prueba»
    prueba_id: Optional[int] = None  # psicométrica del catálogo (opcional)
    modo: str = ""  # vacío = el de la prueba o «manual»
    proveedor: str = ""
    id_proveedor: str = ""
    url: str = ""
    notas: str = ""


def _aplicar_evaluador(db: Session, ev: EvaluacionCandidato, datos: EvaluadorIn, cuenta_id: int) -> None:
    """Evaluador (interno: Usuario activo; externo: nombre + teléfono/correo) y cita opcional."""
    import re

    from ..services.notificaciones import TZ_MEXICO

    tipo = (datos.evaluador_tipo or "").strip()
    if tipo not in ("", "interno", "externo"):
        raise HTTPException(400, "Tipo de evaluador inválido: interno o externo.")
    ev.evaluador_tipo = tipo
    ev.evaluador_usuario_id = None
    ev.evaluador_nombre = ev.evaluador_telefono = ev.evaluador_correo = ""
    if tipo == "interno":
        u = db.query(Usuario).filter(Usuario.id == datos.evaluador_usuario_id, Usuario.activo.is_(True)).first()
        if not u:
            raise HTTPException(400, "Elige al evaluador (usuario activo de la Cuenta).")
        ev.evaluador_usuario_id, ev.evaluador_nombre = u.id, u.nombre
    elif tipo == "externo":
        if not datos.evaluador_nombre.strip():
            raise HTTPException(400, "Escribe el nombre del evaluador externo.")
        ev.evaluador_nombre = datos.evaluador_nombre.strip()[:150]
        ev.evaluador_telefono = re.sub(r"\D", "", datos.evaluador_telefono)[-10:]
        ev.evaluador_correo = datos.evaluador_correo.strip()[:200]
    ev.cita_en, ev.cita_lugar = None, datos.cita_lugar.strip()[:300]
    if datos.cita_fecha:
        try:
            ev.cita_en = datetime.fromisoformat(f"{datos.cita_fecha}T{datos.cita_hora or '09:00'}").replace(tzinfo=TZ_MEXICO).astimezone(timezone.utc)
        except ValueError:
            raise HTTPException(400, "Fecha u hora de la cita inválida (2026-10-02 / 09:00).")


@router.post("/postulaciones/{codigo}", status_code=201)
def agregar_evaluacion(codigo: str, datos: AgregarEvaluacionIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """«Agregar evaluación o verificación» desde la ficha. NO toca la etapa de la postulación. Comprueba los
    consentimientos: si falta alguno queda «En espera de consentimiento» (y no se puede enviar)."""
    p = _postulacion(db, codigo, cuenta.id)
    if not p.activa:
        raise HTTPException(409, "La postulación está cerrada.")
    if datos.tipo not in TIPOS_EVALUACION:
        raise HTTPException(400, f"Tipo inválido. Usa uno de: {', '.join(TIPOS_EVALUACION)}.")
    nombre, modo, proveedor, id_prov, url = datos.nombre.strip(), datos.modo.strip(), datos.proveedor.strip(), datos.id_proveedor.strip(), datos.url.strip()
    prueba = None
    if datos.tipo == "psicometrica" and not datos.prueba_id and not nombre:
        raise HTTPException(400, "Escribe el nombre de la prueba (o elígela del catálogo).")
    if datos.tipo == "psicometrica" and datos.prueba_id:
        prueba = _prueba(db, datos.prueba_id, cuenta.id)
        if not prueba.activa:
            raise HTTPException(409, "Esa prueba psicométrica está inactiva.")
        nombre = nombre or prueba.nombre
        modo = modo or prueba.modo
        proveedor, id_prov, url = proveedor or prueba.proveedor, id_prov or prueba.id_proveedor, url or prueba.url
    nombre = (nombre or TIPOS_EVALUACION[datos.tipo])[:200]
    modo = modo or "manual"
    if modo not in MODOS_PRUEBA:
        raise HTTPException(400, "Modo inválido: usa integrada, enlace o manual.")
    if modo == "enlace" and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "El modo «Enlace externo» necesita la liga (https://…).")
    ev = EvaluacionCandidato(
        codigo="TMP", cuenta_id=cuenta.id, postulacion_id=p.id, tipo=datos.tipo, nombre=nombre, prueba_id=prueba.id if prueba else None,
        modo=modo, proveedor=proveedor[:150], id_proveedor=id_prov[:150], url=url[:500], notas=datos.notas.strip()[:2000],
        requiere_consentimiento_expreso=datos.tipo == "medico", asignada_por=u.nombre, estado="en_espera_consentimiento", historial=[],
    )
    if ev.requiere_consentimiento_expreso:
        ev.consentimiento_token = secrets.token_urlsafe(24)
    sev.asegurar_token(ev)  # la liga del evaluador existe desde ya (regla universal de ligas)
    _aplicar_evaluador(db, ev, datos, cuenta.id)
    db.add(ev)
    db.flush()
    ev.codigo = f"EVA-{7000 + ev.id}"
    sev.mover(ev, "en_espera_consentimiento", u.nombre, "Asignada" + (f" · evaluador {ev.evaluador_nombre}" if ev.evaluador_nombre else ""))
    sev.refrescar_consentimiento(ev, p, u.nombre)
    registrar(db, u.nombre, "evaluacion_asignada", "postulacion", p.codigo,
              {"evaluacion": ev.codigo, "tipo": ev.tipo, "nombre": ev.nombre, "modo": ev.modo, "estado": ev.estado,
               "evaluador": ev.evaluador_nombre, "correo_rh": u.correo})
    db.commit()
    return evaluacion_candidato_dict(ev, u, db)


def _exigir_consentimiento(ev: EvaluacionCandidato, p: Optional[Postulacion]) -> None:
    sev.refrescar_consentimiento(ev, p)
    falta = sev.falta_consentimiento(ev, p)
    if falta:
        raise HTTPException(409, f"En espera de consentimiento: {falta}")


def _abierta(ev: EvaluacionCandidato) -> None:
    if ev.estado in ("revisada", "fallida"):
        raise HTTPException(409, f"La evaluación ya está {'revisada' if ev.estado == 'revisada' else 'fallida/cancelada'}.")


@router.post("/{codigo}/enviar")
def enviar(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Envía/asigna la evaluación: Pendiente → En proceso (en modo Integrada: Asignada → Enviada). Bloqueado sin
    consentimiento. Todavía sin conexión al proveedor: solo registra el envío."""
    ev = _evaluacion(db, codigo, cuenta.id)
    p = _post_de(db, ev)
    _abierta(ev)
    _exigir_consentimiento(ev, p)
    if ev.estado != "pendiente":
        raise HTTPException(409, "Solo se envía una evaluación pendiente.")
    from ..services import psicometricas as psi

    if sev.usa_psicometricas(ev) and psi.configurado():
        # 2026-09-29: envío REAL a Psicométricas.mx (agregaCandidato). Si falla, nada cambia (502 con el motivo).
        if not (p and p.correo):
            raise HTTPException(409, "Psicométricas.mx necesita el correo del candidato para mandarle su liga.")
        try:
            tests = psi.tests_de(ev.id_proveedor)
            clave = psi.agregar_candidato(p.nombre, p.correo, p.vacante.titulo if p.vacante else ev.nombre, tests)
        except psi.PsicometricasError as ex:
            raise HTTPException(400 if ex.status == 400 else 502, str(ex))
        ev.clave_proveedor = clave
        sev.aplicar_paso(ev, "enviada", u.nombre, "Psicométricas.mx")
    elif ev.modo == "integrada":
        sev.aplicar_paso(ev, "enviada", u.nombre)
    else:
        sev.mover(ev, "en_proceso", u.nombre, "Enviada" + (f" ({ev.url})" if ev.url else ""))
    registrar(db, u.nombre, "evaluacion_enviada", "postulacion", p.codigo if p else "",
              {"evaluacion": ev.codigo, "modo": ev.modo, "proveedor": ev.proveedor, "clave_proveedor": ev.clave_proveedor, "correo_rh": u.correo})
    db.commit()
    return evaluacion_candidato_dict(ev, u, db)


@router.post("/{codigo}/integracion/avanzar")
def avanzar_integrada(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Modo Integrada SIMULADO (hasta conectar proveedores): avanza un paso Asignada → Enviada → Iniciada →
    Completada → Resultado recibido. Cuando se conecte el proveedor, su webhook llamará a `sev.aplicar_paso`."""
    ev = _evaluacion(db, codigo, cuenta.id)
    p = _post_de(db, ev)
    if ev.modo != "integrada":
        raise HTTPException(409, "Solo las evaluaciones en modo Integrada avanzan por pasos.")
    if ev.clave_proveedor:
        raise HTTPException(409, "Esta evaluación está conectada a Psicométricas.mx: su avance llega del proveedor (usa «Consultar resultado»).")
    _abierta(ev)
    _exigir_consentimiento(ev, p)
    paso = sev.siguiente_paso(ev)
    if not paso:
        raise HTTPException(409, "La evaluación ya tiene su resultado; ahora se revisa.")
    sev.aplicar_paso(ev, paso, u.nombre)
    registrar(db, u.nombre, "evaluacion_paso_simulado", "postulacion", p.codigo if p else "", {"evaluacion": ev.codigo, "paso": paso, "correo_rh": u.correo})
    db.commit()
    return evaluacion_candidato_dict(ev, u, db)


@router.post("/{codigo}/sincronizar")
def sincronizar(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """«Consultar resultado» en Psicométricas.mx (por si el webhook no llegó). Solo guarda si su API confirma que terminó."""
    from ..services import psicometricas as psi

    ev = _evaluacion(db, codigo, cuenta.id)
    if not ev.clave_proveedor:
        raise HTTPException(409, "Esta evaluación no está conectada a Psicométricas.mx.")
    try:
        r = sev.sincronizar_psicometricas(db, ev)
    except psi.PsicometricasError as ex:
        raise HTTPException(502, str(ex))
    registrar(db, u.nombre, "evaluacion_sincronizada", "evaluaciones", ev.codigo, {"resultado": r, "correo_rh": u.correo})
    db.commit()
    return {**evaluacion_candidato_dict(ev, u, db), "sincronizacion": r}


@router.post("/{codigo}/resultado")
async def cargar_resultado(
    codigo: str, resumen: str = Form(""), archivo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual),
):
    """Adjuntar el informe/resultado manualmente (quién y cuándo). Exige los consentimientos."""
    from ..services import archivos as fs

    ev = _evaluacion(db, codigo, cuenta.id)
    p = _post_de(db, ev)
    _abierta(ev)
    _exigir_consentimiento(ev, p)
    if not archivo and not resumen.strip():
        raise HTTPException(400, "Adjunta el informe o escribe el resultado.")
    if ev.es_medico and not u.puede_ver_informe_medico():
        raise HTTPException(403, "Cargar el informe médico requiere el permiso de informes médicos.")
    if archivo is not None and archivo.filename:
        validado = await fs.validar(archivo, f"informe «{ev.nombre}»")
        ev.archivo = fs.guardar(validado, f"evaluaciones/{ev.id}", f"informe_{ev.codigo}")
        ev.nombre_archivo, ev.mime = validado.nombre, validado.mime
    if resumen.strip():
        ev.resultado_resumen = resumen.strip()[:5000]
    ev.resultado_cargado_por, ev.resultado_cargado_en = u.nombre, datetime.now(timezone.utc)
    ev.resultado_origen = "rh"
    if ev.modo == "integrada":
        ev.paso_integrada = "resultado_recibido"
    sev.mover(ev, "resultado_recibido", u.nombre, "Resultado cargado manualmente por RH" + (" (con informe)" if ev.archivo else ""))
    registrar(db, u.nombre, "evaluacion_resultado_cargado", "postulacion", p.codigo if p else "",
              {"evaluacion": ev.codigo, "con_archivo": bool(ev.archivo), "correo_rh": u.correo})
    db.commit()
    return evaluacion_candidato_dict(ev, u, db)


class RevisarIn(BaseModel):
    dictamen: str
    comentario: str = ""
    conclusion: str = ""  # 2026-09-30: «Marcar como revisada» guarda usuario, fecha y conclusión (= comentario)


@router.post("/{codigo}/revisar")
def revisar(codigo: str, datos: RevisarIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """RH marca «Revisada» y elige el dictamen: Favorable / Con observaciones / Desfavorable; en el estudio médico
    transcribe Apto / Apto con restricciones / No apto. Siempre una persona (HITL)."""
    ev = _evaluacion(db, codigo, cuenta.id)
    p = _post_de(db, ev)
    if ev.estado != "resultado_recibido":
        raise HTTPException(409, "Se revisa cuando ya hay resultado recibido.")
    if ev.es_medico and not u.puede_ver_informe_medico():
        raise HTTPException(403, "Transcribir el dictamen médico requiere el permiso de informes médicos.")
    opciones = sev.dictamenes_de(ev.tipo)
    if datos.dictamen not in opciones:
        raise HTTPException(400, f"Dictamen inválido para {ev.nombre}: usa {', '.join(opciones.values())}.")
    ev.dictamen, ev.comentario_revision = datos.dictamen, (datos.conclusion or datos.comentario).strip()[:2000]
    ev.revisada_por, ev.revisada_en = u.nombre, datetime.now(timezone.utc)
    sev.mover(ev, "revisada", u.nombre, f"Dictamen: {opciones[datos.dictamen]}")
    registrar(db, u.nombre, "evaluacion_revisada", "postulacion", p.codigo if p else "",
              {"evaluacion": ev.codigo, "tipo": ev.tipo, "dictamen": datos.dictamen, "correo_rh": u.correo})
    db.commit()
    return evaluacion_candidato_dict(ev, u, db)


class CancelarIn(BaseModel):
    motivo: str = ""


@router.post("/{codigo}/cancelar")
def cancelar(codigo: str, datos: CancelarIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Fallida/Cancelada: siempre con motivo."""
    ev = _evaluacion(db, codigo, cuenta.id)
    p = _post_de(db, ev)
    _abierta(ev)
    motivo = datos.motivo.strip()
    if not motivo:
        raise HTTPException(400, "Indica el motivo (fallida o cancelada).")
    ev.motivo_fallida = motivo[:1000]
    sev.mover(ev, "fallida", u.nombre, motivo)
    registrar(db, u.nombre, "evaluacion_fallida", "postulacion", p.codigo if p else "", {"evaluacion": ev.codigo, "motivo": motivo[:300], "correo_rh": u.correo})
    db.commit()
    return evaluacion_candidato_dict(ev, u, db)


@router.get("/{codigo}/informe")
def descargar_informe(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    from ..services import archivos as fs

    ev = _evaluacion(db, codigo, cuenta.id)
    if ev.es_medico and not u.puede_ver_informe_medico():
        registrar(db, u.nombre, "informe_medico_acceso_denegado", "evaluaciones", ev.codigo, {"correo_rh": u.correo})
        db.commit()
        raise HTTPException(403, "El informe médico completo solo lo ven usuarios con permiso; tú ves el estado y el dictamen.")
    if not fs.existe(ev.archivo):
        raise HTTPException(404, "Esta evaluación no tiene informe adjunto.")
    if ev.es_medico:
        registrar(db, u.nombre, "informe_medico_consultado", "evaluaciones", ev.codigo, {"correo_rh": u.correo})
        db.commit()
    return FileResponse(ev.archivo, media_type=ev.mime or "application/octet-stream", filename=ev.nombre_archivo or f"informe-{ev.codigo}")


@router.post("/{codigo}/consentimiento/enviar")
async def enviar_liga_consentimiento(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Manda al candidato la liga del consentimiento expreso (WhatsApp y correo con lo que tenga). Un canal caído
    nunca rompe la acción: el resultado de cada envío regresa a RH."""
    from ..config import settings
    from ..services import plantillas_correo
    from ..services.correo import enviar_correo
    from ..services.whatsapp import enviar_mensaje

    ev = _evaluacion(db, codigo, cuenta.id)
    p = _post_de(db, ev)
    if not ev.requiere_consentimiento_expreso or not ev.consentimiento_token:
        raise HTTPException(409, "Esta evaluación no requiere consentimiento expreso.")
    if ev.consentimiento_aceptado_en:
        raise HTTPException(409, "El candidato ya otorgó su consentimiento.")
    liga = f"{settings.app_url}/consentimiento/{ev.consentimiento_token}"
    nombre = p.nombre if p else ""
    empresa = nombre_empresa_candidato(p.vacante) if p and p.vacante else cuenta.nombre_visible
    texto = (f"Hola {nombre}. Para continuar con tu proceso en {empresa} necesitamos tu consentimiento por escrito para el estudio "
             f"médico. Léelo y, si estás de acuerdo, acéptalo aquí: {liga}")
    resultados = []
    if p and p.telefono:
        try:
            r = await enviar_mensaje(p.telefono, texto)
        except Exception as ex:  # noqa: BLE001
            r = {"enviado": False, "detalle": str(ex)[:200]}
        resultados.append({"destinatario": "candidato", "canal": "whatsapp", "destino": p.telefono, "enviado": bool(r.get("enviado")), "detalle": str(r.get("detalle") or "")})
    if p and p.correo:
        try:
            asunto, html = plantillas_correo.html_aviso("Consentimiento para tu estudio médico", texto.replace(liga, "").strip(), empresa, [], ("Leer y aceptar", liga))
            r = await enviar_correo(p.correo, asunto, html)
        except Exception as ex:  # noqa: BLE001
            r = {"enviado": False, "detalle": str(ex)[:200]}
        resultados.append({"destinatario": "candidato", "canal": "correo", "destino": p.correo, "enviado": bool(r.get("enviado")), "detalle": str(r.get("detalle") or "")})
    registrar(db, u.nombre, "consentimiento_medico_solicitado", "postulacion", p.codigo if p else "", {"evaluacion": ev.codigo, "envios": resultados, "correo_rh": u.correo})
    db.commit()
    return {"liga": liga, "resultados": resultados}


# ---------------- 2026-09-30: evaluador, en curso y envío de ligas ----------------


@router.patch("/{codigo}/evaluador")
def asignar_evaluador(codigo: str, datos: EvaluadorIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Asigna o cambia al evaluador (interno o externo) y la cita opcional. La liga del evaluador no cambia."""
    ev = _evaluacion(db, codigo, cuenta.id)
    _abierta(ev)
    _aplicar_evaluador(db, ev, datos, cuenta.id)
    sev.asegurar_token(ev)
    sev.mover(ev, ev.estado, u.nombre, f"Evaluador: {ev.evaluador_nombre or 'sin asignar'}" + (f" · cita {ev.cita_en.isoformat()}" if ev.cita_en else ""))
    registrar(db, u.nombre, "evaluacion_evaluador_asignado", "evaluaciones", ev.codigo, {"evaluador": ev.evaluador_nombre, "tipo": ev.evaluador_tipo})
    db.commit()
    return evaluacion_candidato_dict(ev, u, db)


@router.post("/{codigo}/en-curso")
def marcar_en_curso(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Enviada → En curso (el candidato ya empezó o la cita se realizó)."""
    ev = _evaluacion(db, codigo, cuenta.id)
    _abierta(ev)
    _exigir_consentimiento(ev, _post_de(db, ev))
    if ev.estado == "pendiente":
        sev.mover(ev, "en_proceso", u.nombre, "Enviada")
    if ev.estado != "en_proceso":
        raise HTTPException(409, "Solo una evaluación enviada pasa a «En curso».")
    ev.paso_integrada = "iniciada"
    sev.mover(ev, "en_proceso", u.nombre, "En curso")
    db.commit()
    return evaluacion_candidato_dict(ev, u, db)


async def _mandar(destino_tel: str, destino_correo: str, texto: str, titulo: str, liga: str, cta: str, empresa: str) -> list:
    from ..services import plantillas_correo
    from ..services.correo import enviar_correo
    from ..services.whatsapp import enviar_mensaje

    salida = []
    if destino_tel:
        try:
            r = await enviar_mensaje(destino_tel, texto)
        except Exception as ex:  # noqa: BLE001 — un canal caído nunca rompe la acción
            r = {"enviado": False, "detalle": str(ex)[:200]}
        salida.append(("mensaje", r))
    if destino_correo:
        try:
            asunto, html = plantillas_correo.html_aviso(titulo, texto.replace(liga, "").strip(), empresa, [], (cta, liga))
            r = await enviar_correo(destino_correo, asunto, html)
        except Exception as ex:  # noqa: BLE001
            r = {"enviado": False, "detalle": str(ex)[:200]}
        salida.append(("correo", r))
    return salida


def liga_evaluador(ev: EvaluacionCandidato) -> str:
    from ..config import settings

    return f"{settings.app_url}/evaluacion/{ev.evaluador_token}" if ev.evaluador_token else ""


@router.post("/{codigo}/evaluador/enviar")
async def enviar_liga_evaluador(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Manda al evaluador (médico, socioeconómico, proveedor…) su liga de captura. La liga siempre regresa, salga o no
    el mensaje. Médico: solo cuando el candidato ya aceptó el consentimiento expreso."""
    ev = _evaluacion(db, codigo, cuenta.id)
    p = _post_de(db, ev)
    _abierta(ev)
    sev.asegurar_token(ev)
    if not sev.evaluador_habilitado(ev, p):
        raise HTTPException(409, f"En espera de consentimiento: {sev.falta_consentimiento(ev, p)}")
    ev_dato = sev.evaluador_de(ev, db)
    liga = liga_evaluador(ev)
    empresa = nombre_empresa_candidato(p.vacante) if p and p.vacante else cuenta.nombre_visible
    cita = ""
    if ev.cita_en:
        from ..services.notificaciones import TZ_MEXICO

        cita = f" Cita: {ev.cita_en.astimezone(TZ_MEXICO).strftime('%d/%m/%Y %H:%M')} h" + (f" en {ev.cita_lugar}" if ev.cita_lugar else "") + "."
    texto = (f"Hola {ev_dato['nombre'].split(' ')[0] if ev_dato['nombre'] else ''}, tienes asignada la evaluación «{ev.nombre}» de "
             f"{p.nombre if p else 'un candidato'} ({empresa}).{cita} Registra el resultado aquí: {liga}")
    resultados = [sev.registrar_envio(ev, liga, "evaluador", canal, r)
                  for canal, r in await _mandar(ev_dato["telefono"], ev_dato["correo"], texto, f"Evaluación asignada: {ev.nombre}", liga, "Registrar resultado", empresa)]
    if not resultados:
        resultados = [sev.registrar_envio(ev, liga, "evaluador", "—", {"enviado": False, "detalle": "El evaluador no tiene teléfono ni correo: copia la liga."})]
    registrar(db, u.nombre, "evaluacion_liga_evaluador_enviada", "evaluaciones", ev.codigo, {"envios": resultados})
    db.commit()
    return {**evaluacion_candidato_dict(ev, u, db), "envios": resultados}


@router.post("/{codigo}/enlace/enviar")
async def enviar_enlace_candidato(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Manda al candidato la liga del proveedor (modo «Enlace externo»). La liga siempre regresa."""
    ev = _evaluacion(db, codigo, cuenta.id)
    p = _post_de(db, ev)
    _abierta(ev)
    _exigir_consentimiento(ev, p)
    if not ev.url:
        raise HTTPException(409, "Esta evaluación no tiene enlace externo.")
    empresa = nombre_empresa_candidato(p.vacante) if p and p.vacante else cuenta.nombre_visible
    texto = f"Hola {p.nombre.split(' ')[0] if p and p.nombre else ''}, para continuar con tu proceso en {empresa} realiza «{ev.nombre}» aquí: {ev.url}"
    resultados = [sev.registrar_envio(ev, ev.url, "candidato", canal, r)
                  for canal, r in await _mandar(p.telefono if p else "", p.correo if p else "", texto, ev.nombre, ev.url, "Abrir evaluación", empresa)]
    if not resultados:
        resultados = [sev.registrar_envio(ev, ev.url, "candidato", "—", {"enviado": False, "detalle": "El candidato no tiene teléfono ni correo: copia la liga."})]
    if ev.estado == "pendiente":
        sev.mover(ev, "en_proceso", u.nombre, "Enviada (enlace al candidato)")
    registrar(db, u.nombre, "evaluacion_enlace_enviado", "evaluaciones", ev.codigo, {"envios": resultados})
    db.commit()
    return {**evaluacion_candidato_dict(ev, u, db), "envios": resultados}


# ---------------- Pública: liga del evaluador ----------------


def _por_token_evaluador(db: Session, token: str) -> EvaluacionCandidato:
    ev = db.query(EvaluacionCandidato).filter(EvaluacionCandidato.evaluador_token == token).first() if token else None
    if not ev:
        raise HTTPException(404, "Esta liga no es válida.")
    return ev


@router.get("/publica/evaluador/{token}")
def ver_evaluacion_evaluador(token: str, db: Session = Depends(get_db)):
    ev = _por_token_evaluador(db, token)
    p = _post_de(db, ev)
    return {
        "candidato": p.nombre if p else "",
        "empresa": nombre_empresa_candidato(p.vacante) if p and p.vacante else "",
        "puesto": p.vacante.titulo if p and p.vacante else "",
        "evaluacion": ev.nombre,
        "tipo": ev.tipo,
        "tipoTexto": TIPOS_EVALUACION.get(ev.tipo, ev.tipo),
        "evaluador": ev.evaluador_nombre or "",
        "cita": ev.cita_en.isoformat() if ev.cita_en else None,
        "citaLugar": ev.cita_lugar or "",
        "habilitada": sev.evaluador_habilitado(ev, p),
        "motivo": sev.falta_consentimiento(ev, p) if ev.estado not in ("revisada", "fallida") else "",
        "yaRegistrado": ev.estado in ("resultado_recibido", "revisada"),
        "cancelada": ev.estado == "fallida",
    }


@router.post("/publica/evaluador/{token}/resultado")
async def registrar_resultado_evaluador(
    token: str, resumen: str = Form(""), evaluador: str = Form(""), archivo: Optional[UploadFile] = File(None), db: Session = Depends(get_db),
):
    """El evaluador registra el resultado (resumen y/o informe). Alimenta la MISMA evaluación que la captura de RH;
    la revisión y el dictamen siguen siendo de RH. Nunca mueve la etapa del candidato."""
    from ..services import archivos as fs

    ev = _por_token_evaluador(db, token)
    p = _post_de(db, ev)
    if ev.estado == "fallida":
        raise HTTPException(409, "Esta evaluación fue cancelada.")
    if ev.estado in ("resultado_recibido", "revisada"):
        raise HTTPException(409, "El resultado ya quedó registrado. Si hay que corregirlo, avisa a RH.")
    if not sev.evaluador_habilitado(ev, p):
        raise HTTPException(409, f"Aún no se puede registrar: {sev.falta_consentimiento(ev, p)}")
    quien = " ".join((evaluador or ev.evaluador_nombre).split())
    if len(quien) < 3:
        raise HTTPException(400, "Escribe tu nombre (queda registrado quién capturó el resultado).")
    if not archivo and not resumen.strip():
        raise HTTPException(400, "Adjunta el informe o escribe el resultado.")
    if archivo is not None and archivo.filename:
        validado = await fs.validar(archivo, f"informe «{ev.nombre}»")
        ev.archivo = fs.guardar(validado, f"evaluaciones/{ev.id}", f"informe_{ev.codigo}")
        ev.nombre_archivo, ev.mime = validado.nombre, validado.mime
    if resumen.strip():
        ev.resultado_resumen = resumen.strip()[:5000]
    ev.resultado_cargado_por, ev.resultado_cargado_en = f"{quien[:120]} (evaluador)", datetime.now(timezone.utc)
    ev.resultado_origen = "evaluador"
    if ev.modo == "integrada":
        ev.paso_integrada = "resultado_recibido"
    sev.mover(ev, "resultado_recibido", f"{quien[:120]} (evaluador)", "Resultado registrado en la liga del evaluador" + (" (con informe)" if ev.archivo else ""))
    registrar(db, f"{quien[:120]} (evaluador)", "evaluacion_resultado_evaluador", "postulacion", p.codigo if p else "",
              {"evaluacion": ev.codigo, "con_archivo": bool(ev.archivo)})
    db.commit()
    return ver_evaluacion_evaluador(token, db)


# ---------------- Pública: consentimiento expreso del estudio médico ----------------

def _por_token(db: Session, token: str) -> EvaluacionCandidato:
    ev = db.query(EvaluacionCandidato).filter(EvaluacionCandidato.consentimiento_token == token).first() if token else None
    if not ev:
        raise HTTPException(404, "Esta liga no es válida.")
    return ev


def _texto_consentimiento(db: Session, ev: EvaluacionCandidato) -> str:
    p = _post_de(db, ev)
    empresa = nombre_empresa_candidato(p.vacante) if p and p.vacante else "la empresa"
    return TEXTO_CONSENTIMIENTO_MEDICO.format(nombre=(p.nombre if p else "la persona candidata"), empresa=empresa, puesto=(p.vacante.titulo if p and p.vacante else "el puesto"))


@router.get("/publica/consentimiento/{token}")
def ver_consentimiento(token: str, db: Session = Depends(get_db)):
    ev = _por_token(db, token)
    p = _post_de(db, ev)
    return {
        "candidato": p.nombre if p else "",
        "empresa": nombre_empresa_candidato(p.vacante) if p and p.vacante else "",
        "puesto": p.vacante.titulo if p and p.vacante else "",
        "evaluacion": ev.nombre,
        "texto": ev.consentimiento_texto or _texto_consentimiento(db, ev),
        "aceptado": bool(ev.consentimiento_aceptado_en),
        "aceptadoEn": ev.consentimiento_aceptado_en.isoformat() if ev.consentimiento_aceptado_en else None,
        "cancelada": ev.estado == "fallida",
    }


class AceptarConsentimientoIn(BaseModel):
    nombre: str
    acepto: bool = False


@router.post("/publica/consentimiento/{token}/aceptar")
def aceptar_consentimiento(token: str, datos: AceptarConsentimientoIn, request: Request, db: Session = Depends(get_db)):
    """Consentimiento EXPRESO y POR ESCRITO por medio electrónico: la persona escribe su nombre completo como firma y
    marca «Acepto». Se guarda el texto exacto, la aceptación y la evidencia (nombre, IP, navegador, huella SHA-256) y
    queda en la bitácora hash-encadenada. Nunca se acepta en nombre de la persona."""
    ev = _por_token(db, token)
    if ev.estado == "fallida":
        raise HTTPException(409, "Esta evaluación fue cancelada.")
    if ev.consentimiento_aceptado_en:
        raise HTTPException(409, "Ya habías otorgado tu consentimiento. Gracias.")
    firma = " ".join((datos.nombre or "").split())
    if not datos.acepto:
        raise HTTPException(400, "Para otorgar tu consentimiento marca «Acepto».")
    if len(firma) < 5:
        raise HTTPException(400, "Escribe tu nombre completo como firma.")
    ahora = datetime.now(timezone.utc)
    texto = _texto_consentimiento(db, ev)
    huella = hashlib.sha256(f"{texto}|{firma}|{ahora.isoformat()}|{ev.codigo}".encode("utf-8")).hexdigest()
    ev.consentimiento_texto = texto
    ev.consentimiento_aceptado_en = ahora
    ev.consentimiento_evidencia = {
        "nombre_escrito": firma[:200],
        "ip": (request.client.host if request.client else "")[:64],
        "navegador": (request.headers.get("user-agent") or "")[:300],
        "medio": "electronico",
        "huella_sha256": huella,
    }
    p = _post_de(db, ev)
    sev.refrescar_consentimiento(ev, p, "candidato")
    registrar(db, "candidato", "consentimiento_medico_otorgado", "postulacion", p.codigo if p else "",
              {"evaluacion": ev.codigo, "huella_sha256": huella, "nombre_escrito": firma[:200]})
    db.commit()
    return {"ok": True, "aceptadoEn": ahora.isoformat(), "estado": ev.estado}
