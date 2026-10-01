"""Flujo operativo (demo Grupo SEZA) v3 (2026-10-01: sin columna Evaluación; «Avanzar a Contratación») — rutas de RH de la ficha del candidato. La lógica vive en
services/flujo_operativo.py.

* Kanban: `GET /candidatos-flujo` → etapas del Kanban de la Cuenta actual.
* Entrevista (capacitación en tienda sobre EntrevistaHumana): programar (tienda, fecha/hora, capacitador), reprogramar,
  cancelar, reenviar la cita o el aviso del capacitador, confirmar por el candidato y capturar el resultado a mano
  (el capacitador lo hace desde su liga `/entrevista-humana/{token}`; las dos vías alimentan lo MISMO).
* Contratación: decisión del contrato («Generar contrato» ahora o «Generar después de Onboarding») y «Enviar a
  Onboarding» (pide los 6 documentos personales y 3 referencias).
* Onboarding: revisar documentos, registrar llamadas a referencias y «Dar de alta» (cierra la postulación).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import cuenta_actual, usuario_actual, usuario_decisor
from ..models import RESULTADOS_CAPACITACION, TIPOS_CONTRATACION, Cuenta, Curso, Postulacion, Usuario, plantilla_contrato, registrar
from ..serial import iso
from ..services import flujo_operativo as flujo
from ..services.configuracion import modo_prueba_activo
from ..services.notificaciones import TZ_MEXICO
from .candidatos import _por_codigo

router = APIRouter(tags=["operativo"])


# ------------------------------------------------------------ Kanban


@router.get("/candidatos-flujo")
def flujo_de_la_cuenta(_: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    return {"flujo": cuenta.flujo_candidatos or "rh", "etapas": flujo.etapas_de(cuenta)}


# ------------------------------------------------------------ ficha del candidato (RH)


def _operativo(db: Session, codigo: str, cuenta_id: int) -> Postulacion:
    p = _por_codigo(db, codigo, cuenta_id)
    if not flujo.es_operativo(p):
        raise HTTPException(409, "Esta postulación no usa el flujo operativo.")
    return p


def _abierta(p: Postulacion) -> Postulacion:
    if not p.activa:
        raise HTTPException(409, "La postulación está cerrada.")
    return p


def entrevista_dict(db: Session, eh) -> Optional[dict]:
    if eh is None:
        return None
    curso = db.get(Curso, eh.curso_induccion_id) if eh.curso_induccion_id else None
    etiqueta, tono = flujo.estado_entrevista(eh)
    fecha_mx = eh.fecha.astimezone(TZ_MEXICO) if eh.fecha else None
    return {
        "id": eh.id,
        "tienda": eh.tienda,
        "direccion": eh.ubicacion or "",
        "fecha": iso(eh.fecha),
        "fechaLocal": fecha_mx.strftime("%Y-%m-%d") if fecha_mx else "",
        "horaLocal": fecha_mx.strftime("%H:%M") if fecha_mx else "",
        "fechaTexto": fecha_mx.strftime("%d/%m/%Y %H:%M") if fecha_mx else "",
        "indicaciones": eh.comentario or "",
        "capacitador": flujo.capacitador_de(eh, db),
        "ligaCapacitador": flujo.liga_capacitador(eh),
        "confirmada": bool(eh.confirmada_en),
        "confirmadaEn": iso(eh.confirmada_en),
        "asistencia": eh.asistencia or "",
        "resultado": eh.resultado or "",
        "resultadoEtiqueta": RESULTADOS_CAPACITACION.get(eh.resultado or "", ""),
        "capturadoPor": eh.resultado_capturado_por or "",
        "registradoPor": eh.registrado_por or "",
        "realizadaEn": iso(eh.realizada_en),
        "evaluadaEn": iso(eh.evaluada_en),
        "estado": etiqueta,
        "tono": tono,
        "clave": flujo.clave_entrevista(eh),
        "cursoInduccion": {"codigo": curso.codigo, "titulo": curso.titulo} if curso else None,
        "envios": list(reversed(eh.envios or [])),
    }


def panel_dict(db: Session, p: Postulacion) -> dict:
    eh = flujo.entrevista_actual(p)
    e = p.expediente
    faltan = flujo.faltantes_para_alta(p)
    col = None
    if e and e.estado == "alta":
        from ..models import Colaborador

        c = db.query(Colaborador).filter(Colaborador.expediente_id == e.id).first()
        col = {"codigo": c.codigo, "nombre": c.nombre} if c else None
    induccion = next((h for h in reversed(p.historial or []) if h.get("evento") == "cita_confirmada"), None)
    return {
        "etapa": p.etapa,
        "etapas": flujo.etapas_de(p.cuenta),
        "activa": p.activa,
        "estadoPrefiltro": flujo.estado_prefiltro(p),
        "subestado": flujo.subestado(p),
        "entrevista": entrevista_dict(db, eh),
        "entrevistasAnteriores": sum(1 for x in (p.entrevistas_humanas or []) if x is not eh),
        "induccion": induccion["texto"] if induccion else "",
        "resultadosCapacitacion": [{"valor": k, "texto": v} for k, v in RESULTADOS_CAPACITACION.items()],
        "evaluacionResumen": flujo.evaluacion_resumen(p),
        # v3: lo que falta para «Avanzar a Contratación» (entrevista Apta + evaluaciones con resultado y revisadas)
        "requisitosContratacion": flujo.requisitos_contratacion(db, p),
        "evaluacionesPendientes": len(flujo.evaluaciones_pendientes(flujo.evaluaciones_vivas(db, p))),
        "contratacion": {
            "condiciones": {
                "puesto": e.puesto if e else "", "sueldo": e.sueldo if e else "", "tipoContratacion": e.tipo_contratacion if e else "",
                "fechaIngreso": iso(e.fecha_ingreso) if e else None, "ubicacion": e.ubicacion if e else "",
                "jefeDirecto": e.jefe_directo if e else "", "instruccionesIngreso": e.instrucciones_ingreso if e else "",
                "duracionContrato": e.duracion_contrato if e else None, "duracionUnidad": e.duracion_unidad if e else "",
            },
            # el tipo de contratación define la plantilla del contrato y cómo se llama el pago
            "plantillas": {t: {"titulo": plantilla_contrato(t)["titulo"], "pago": plantilla_contrato(t)["pago"]} for t in TIPOS_CONTRATACION},
            "cartaDisponible": bool(e and e.puesto and e.sueldo),
            "completas": flujo.condiciones_completas(e),
            "contrato": (e.contrato_operativo or "") if e else "",
            "contratoPor": (e.contrato_operativo_por or "") if e else "",
            "contratoEn": iso(e.contrato_operativo_en) if e else None,
            "requisitosOnboarding": flujo.requisitos_onboarding(p),
            "tiposContratacion": TIPOS_CONTRATACION,
        },
        "expediente": {
            "id": e.id,
            "liga": flujo.liga_expediente(e),
            "progreso": e.progreso,
            "documentos": [
                {"tipo": d.tipo, "estado": d.estado, "aprobado": d.aprobado, "archivo": bool(d.archivo), "notas": d.notas_ia or "",
                 "estadoSimple": flujo.estado_documento(d), "revisadoPor": d.revisado_por or "",
                 "delVehiculo": d.tipo in flujo.DOCUMENTOS_VEHICULO.values()}
                for d in e.documentos if not d.interno and d.estado != "no_aplica"
            ],
            "referencias": e.referencias or [],
            "resultadosReferencia": {"contactada": flujo.RESULTADOS_REFERENCIA[True], "noContactada": flujo.RESULTADOS_REFERENCIA[False]},
        } if e else None,
        "faltantesAlta": faltan,
        "listoParaAlta": not faltan and p.etapa == flujo.ONBOARDING,
        "alta": {"por": e.alta_autorizada_por, "en": iso(e.alta_fecha), "colaborador": col} if e and e.estado == "alta" else None,
    }


@router.get("/candidatos/{codigo}/operativo")
def ver_panel(codigo: str, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    return panel_dict(db, _operativo(db, codigo, cuenta.id))


# ------------------------------------------------------------ Entrevista (capacitación en tienda)


class EntrevistaIn(BaseModel):
    tienda: str
    direccion: str = ""
    fecha: str  # 2026-10-02 (hora de México)
    hora: str  # 09:00
    capacitador_tipo: str = "interno"  # interno | externo
    capacitador_usuario_id: Optional[int] = None
    capacitador_nombre: str = ""
    capacitador_telefono: str = ""
    capacitador_correo: str = ""
    curso_induccion: Optional[str] = None  # CUR-#### (opcional): su PDF sale al confirmar la cita
    indicaciones: str = ""


def _salida_entrevista(db: Session, p: Postulacion, r: dict) -> dict:
    return {**panel_dict(db, p), "envioCandidato": r["envioCandidato"], "envioCapacitador": r["envioCapacitador"],
            "induccionEnviada": r.get("induccion")}


@router.post("/candidatos/{codigo}/operativo/entrevista")
async def programar_entrevista(codigo: str, datos: EntrevistaIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                               cuenta: Cuenta = Depends(cuenta_actual)):
    from ..services import vehiculo as vehiculo_srv

    p = _abierta(_operativo(db, codigo, cuenta.id))
    citable, motivo = vehiculo_srv.puede_citar(p)
    if not citable and not modo_prueba_activo(db):
        raise HTTPException(409, motivo)
    try:
        r = await flujo.programar_entrevista(db, p, datos.model_dump(), u.nombre)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return _salida_entrevista(db, p, r)


@router.patch("/candidatos/{codigo}/operativo/entrevista")
async def reprogramar_entrevista(codigo: str, datos: EntrevistaIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                                 cuenta: Cuenta = Depends(cuenta_actual)):
    p = _abierta(_operativo(db, codigo, cuenta.id))
    try:
        r = await flujo.reprogramar_entrevista(db, p, datos.model_dump(), u.nombre)
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return _salida_entrevista(db, p, r)


class MotivoIn(BaseModel):
    motivo: str = ""


@router.post("/candidatos/{codigo}/operativo/entrevista/cancelar")
def cancelar_entrevista(codigo: str, datos: MotivoIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                        cuenta: Cuenta = Depends(cuenta_actual)):
    p = _operativo(db, codigo, cuenta.id)
    try:
        flujo.cancelar_entrevista(db, p, datos.motivo.strip(), u.nombre)
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return panel_dict(db, p)


class ReenviarIn(BaseModel):
    destinatario: str  # candidato | capacitador


@router.post("/candidatos/{codigo}/operativo/entrevista/reenviar")
async def reenviar_entrevista(codigo: str, datos: ReenviarIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                              cuenta: Cuenta = Depends(cuenta_actual)):
    """Reenvía la cita al candidato o la liga al capacitador. El resultado del envío se registra aparte."""
    p = _operativo(db, codigo, cuenta.id)
    eh = flujo.entrevista_actual(p)
    if eh is None:
        raise HTTPException(409, "No hay una capacitación programada.")
    if datos.destinatario == "candidato":
        envio = [await flujo.enviar_cita_candidato(db, p, eh)]
    elif datos.destinatario == "capacitador":
        envio = await flujo.enviar_aviso_capacitador(db, p, eh)
    else:
        raise HTTPException(400, "destinatario debe ser candidato o capacitador.")
    registrar(db, u.nombre, "capacitacion_tienda_reenviada", "postulacion", p.codigo, {"destinatario": datos.destinatario,
                                                                                         "enviado": any(x["enviado"] for x in envio)})
    db.commit()
    return {**panel_dict(db, p), "envios": envio}


@router.post("/candidatos/{codigo}/operativo/confirmar-cita")
async def confirmar_cita(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                         cuenta: Cuenta = Depends(cuenta_actual)):
    """RH confirma por el candidato (p. ej. confirmó por llamada). Mismo efecto que su «Sí» por chat."""
    p = _operativo(db, codigo, cuenta.id)
    try:
        r = await flujo.confirmar_cita(db, p, u.nombre)
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return {**panel_dict(db, p), "induccionEnviada": r["induccion"]}


class ResultadoIn(BaseModel):
    asistio: bool
    resultado: str = ""  # favorable | con_observaciones | desfavorable (obligatorio si asistió)
    comentario: str = ""  # observaciones
    fecha_realizada: Optional[str] = None  # 2026-10-02T09:30 (hora de México); vacía = ahora
    entrevistador: str = ""  # quién la hizo (si no, el asignado)


@router.post("/candidatos/{codigo}/operativo/entrevista/resultado")
def resultado_entrevista(codigo: str, datos: ResultadoIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                         cuenta: Cuenta = Depends(cuenta_actual)):
    """«Registrar entrevista» — captura MANUAL de RH: siempre disponible (aunque no esté confirmada, e incluso sin
    cita) y corrige una captura previa. Queda autor, fecha y vía."""
    p = _abierta(_operativo(db, codigo, cuenta.id))
    fecha = None
    if datos.fecha_realizada:
        try:
            fecha = datetime.fromisoformat(datos.fecha_realizada)
        except ValueError:
            raise HTTPException(400, "La fecha realizada no es válida.")
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=TZ_MEXICO)
        if fecha > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise HTTPException(400, "La fecha realizada no puede ser futura.")
    eh = flujo.entrevista_actual(p)
    if eh is None and flujo._indice(p.etapa) < flujo._indice(flujo.ENTREVISTA) and not modo_prueba_activo(db):
        from ..services import vehiculo as vehiculo_srv

        citable, motivo = vehiculo_srv.puede_citar(p)
        if not citable:
            raise HTTPException(409, motivo)
    try:
        flujo.registrar_resultado(db, p, eh, datos.asistio, datos.resultado, datos.comentario, u.nombre, "rh",
                                  fecha_realizada=fecha, entrevistador=datos.entrevistador)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if flujo._indice(p.etapa) < flujo._indice(flujo.ENTREVISTA):
        flujo.mover(db, p, flujo.ENTREVISTA, u.nombre, "Entrevista registrada")
    db.commit()
    return panel_dict(db, p)


# ------------------------------------------------------------ Contratación


class AvanzarIn(BaseModel):
    motivo: str = ""


@router.post("/candidatos/{codigo}/operativo/avanzar-contratacion")
def avanzar_contratacion(codigo: str, datos: AvanzarIn = AvanzarIn(), db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                         cuenta: Cuenta = Depends(cuenta_actual)):
    """«Avanzar a Contratación» (v3): la ÚNICA salida de Entrevista, siempre manual. Exige la entrevista Apta y todas
    las evaluaciones con resultado y revisadas (Modo Prueba lo omite). Agregar/recibir/revisar evaluaciones nunca mueve."""
    p = _abierta(_operativo(db, codigo, cuenta.id))
    try:
        flujo.avanzar_a_contratacion(db, p, u.nombre, modo_prueba_activo(db))
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return panel_dict(db, p)


class ContratoIn(BaseModel):
    cuando: str  # ahora | despues


@router.post("/candidatos/{codigo}/operativo/contrato")
def decidir_contrato(codigo: str, datos: ContratoIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                     cuenta: Cuenta = Depends(cuenta_actual)):
    """«Generar contrato» (el PDF se abre con GET /contratacion/expedientes/{id}/contrato) o «Generar después de
    Onboarding» (queda pendiente para esa etapa)."""
    p = _abierta(_operativo(db, codigo, cuenta.id))
    try:
        flujo.decidir_contrato(db, p, datos.cuando, u.nombre)
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return panel_dict(db, p)


@router.post("/candidatos/{codigo}/operativo/onboarding")
async def enviar_a_onboarding(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                              cuenta: Cuenta = Depends(cuenta_actual)):
    p = _abierta(_operativo(db, codigo, cuenta.id))
    if p.etapa == flujo.ONBOARDING:
        raise HTTPException(409, "Ya está en Onboarding.")
    try:
        r = await flujo.enviar_a_onboarding(db, p, u.nombre, modo_prueba_activo(db))
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return {**panel_dict(db, p), "liga": r["liga"], "whatsapp": r["whatsapp"]}


# ------------------------------------------------------------ Onboarding


@router.post("/candidatos/{codigo}/operativo/solicitar-documentos")
async def solicitar_documentos(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                               cuenta: Cuenta = Depends(cuenta_actual)):
    """Reenvía la liga de documentos y referencias (Onboarding). El envío nunca bloquea: la liga siempre regresa."""
    p = _abierta(_operativo(db, codigo, cuenta.id))
    if p.etapa != flujo.ONBOARDING and not modo_prueba_activo(db):
        raise HTTPException(409, "Los documentos y referencias se piden en Onboarding.")
    if not p.consentimiento:
        raise HTTPException(409, "Falta el consentimiento de privacidad del candidato.")
    r = await flujo.solicitar_documentos_referencias(db, p, u.nombre)
    db.commit()
    return {**panel_dict(db, p), "liga": r["liga"], "whatsapp": r["whatsapp"]}


class DocumentoIn(BaseModel):
    tipo: str
    estado: str  # aprobado | rechazado
    notas: str = ""


@router.post("/candidatos/{codigo}/operativo/documentos")
async def revisar_documento(codigo: str, datos: DocumentoIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                            cuenta: Cuenta = Depends(cuenta_actual)):
    """Revisar (aprobar) / pedir corrección (rechazar con motivo) reutiliza la revisión de siempre
    (`contratacion.marcar_documento`). Al pedir corrección se le avisa al candidato con el motivo y su misma liga
    (best-effort: si el envío falla, la revisión queda guardada y el resultado viaja en `whatsapp`)."""
    from .candidatos import _enviar_whatsapp, guardar_mensaje
    from .contratacion import EstadoDocIn, marcar_documento

    p = _operativo(db, codigo, cuenta.id)
    if not p.expediente:
        raise HTTPException(409, "Este candidato todavía no tiene expediente.")
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
    db.commit()
    return {**panel_dict(db, p), "whatsapp": envio}


class ReferenciaIn(BaseModel):
    contactada: bool
    resultado: str = ""
    fecha: Optional[str] = None  # fecha y hora de la llamada (hora de México si viene sin zona); vacía = ahora
    nota: str = ""  # observaciones


@router.post("/candidatos/{codigo}/operativo/referencias/{indice}")
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
    db.commit()
    return panel_dict(db, p)


class ReferenciaCapturaIn(BaseModel):
    nombre: str
    telefono: str
    parentesco: str  # relación


class ReferenciasIn(BaseModel):
    referencias: list[ReferenciaCapturaIn]


@router.post("/candidatos/{codigo}/operativo/referencias")
def capturar_referencias(codigo: str, datos: ReferenciasIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                         cuenta: Cuenta = Depends(cuenta_actual)):
    """Captura manual de las 3 referencias desde la ficha: alimenta el MISMO registro que la liga del candidato
    (se conservan las llamadas y validaciones de una referencia con el mismo teléfono)."""
    p = _abierta(_operativo(db, codigo, cuenta.id))
    e = flujo.expediente(db, p, u.nombre)
    try:
        limpias = flujo.validar_referencias([r.model_dump() for r in datos.referencias], (p.candidato.telefono if p.candidato else "") or "")
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    flujo.guardar_referencias(db, e, limpias)
    flujo.nota(p, "referencias_capturadas", "RH capturó las 3 referencias", u.nombre)
    registrar(db, u.nombre, "referencias_capturadas_rh", "postulacion", p.codigo, {"n": len(limpias)})
    db.commit()
    return panel_dict(db, p)


class ValidarReferenciaIn(BaseModel):
    validada: bool
    nota: str = ""


@router.post("/candidatos/{codigo}/operativo/referencias/{indice}/validar")
def validar_referencia(codigo: str, indice: int, datos: ValidarReferenciaIn, db: Session = Depends(get_db),
                       u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Validar (o retirar la validación de) una referencia ya contactada. Una llamada nunca valida sola."""
    p = _operativo(db, codigo, cuenta.id)
    e = p.expediente
    if not e or not (0 <= indice < len(e.referencias or [])):
        raise HTTPException(404, "Referencia no encontrada.")
    try:
        r = flujo.validar_referencia(e, indice, datos.validada, datos.nota.strip(), u.nombre)
    except ValueError as ex:
        raise HTTPException(409, str(ex))
    flujo.nota(p, "referencia_validada" if datos.validada else "referencia_no_validada",
               f"Referencia {r['nombre']} " + ("VALIDADA" if datos.validada else "sin validar") + (f" — {datos.nota.strip()}" if datos.nota.strip() else ""), u.nombre)
    registrar(db, u.nombre, "referencia_validada", "postulacion", p.codigo, {"indice": indice, "validada": datos.validada})
    db.commit()
    return panel_dict(db, p)


@router.post("/candidatos/{codigo}/operativo/alta")
def registrar_alta(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                   cuenta: Cuenta = Depends(cuenta_actual)):
    """«Dar de alta»: solo con documentos y referencias listos; crea el colaborador y CIERRA el proceso."""
    p = _operativo(db, codigo, cuenta.id)
    try:
        flujo.registrar_alta(db, p, u, modo_prueba_activo(db))
    except ValueError as e:
        raise HTTPException(409, str(e))
    db.commit()
    return panel_dict(db, p)
