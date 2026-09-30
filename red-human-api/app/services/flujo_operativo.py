"""Flujo OPERATIVO de candidatos (demo Grupo SEZA, 2026-09-29) — el Kanban de 8 etapas:

    Nuevo → Prefiltro → Revisión de vehículo → Cita para capacitación → Capacitación realizada
          → Documentos y referencias → Listo para alta → Alta realizada

Lo usa la Cuenta con `Cuenta.flujo_candidatos == "operativo"`. Aquí viven TODAS las transiciones (nada
de Zero-Touch ni del agente conversacional) y sus candados:

* Nuevo → Prefiltro: el candidato empieza a contestar (WhatsApp) o manda el formulario web.
* Prefiltro → Revisión de vehículo: «Cumple perfil» (o RH aprueba un «Requiere revisión»).
* Revisión de vehículo → Cita para capacitación: RH aprueba el vehículo o marca excepción.
* Cita → Capacitación realizada: el SUPERVISOR registra asistencia y resultado en su liga. El resultado se
  ve como Apto / Requiere seguimiento / No apto y se guarda como dictamen Favorable / Con observaciones /
  Desfavorable de la evaluación unificada «Otra» llamada «Capacitación en tienda».
* → Documentos y referencias: RH pide documentos + 3 referencias (liga pública del expediente).
* → Listo para alta: automático cuando los documentos están Aprobados y las 3 referencias contactadas.
* → Alta realizada: RH registra el alta (crea el Colaborador). La postulación sigue ACTIVA en esa columna.

Toda decisión la toma una persona (RH o el supervisor) y queda en `Postulacion.historial` + bitácora. Modo
Prueba se salta los candados, como el resto de la plataforma.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ETAPAS_OPERATIVO,
    NOMBRE_CAPACITACION_TIENDA,
    RESULTADOS_CAPACITACION,
    Cuenta,
    Documento,
    EvaluacionCandidato,
    Postulacion,
    SesionCapacitacion,
    registrar,
)
from . import evaluaciones as sev

NUEVO, PREFILTRO, VEHICULO, CITA, CAPACITADO, DOCUMENTOS, LISTO, ALTA = ETAPAS_OPERATIVO

# Expediente de un chofer con unidad propia (se abre al pedir documentos y referencias)
DOCUMENTOS_OPERATIVO = [
    "Identificación oficial (INE)",
    "Licencia de conducir vigente",
    "Tarjeta de circulación",
    "Póliza de seguro vigente",
    "Comprobante de domicilio",
    "CURP",
    "Constancia de Situación Fiscal / RFC",
    "Número de Seguridad Social",
    "Cuenta bancaria / CLABE",
]
REFERENCIAS_REQUERIDAS = 3
PARENTESCOS = ["Familiar", "Amistad", "Exjefe o excompañero", "Vecino(a)", "Otro"]

# Estados del documento como los nombra el documento de requerimientos (se LEEN de los valores de siempre).
DOC_PENDIENTE, DOC_RECIBIDO, DOC_REVISADO, DOC_CORRECCION = "Pendiente", "Recibido", "Revisado", "Requiere corrección"

# Resultado de la llamada a una referencia: depende de si se logró contactar.
RESULTADOS_REFERENCIA = {
    True: ["Favorable", "Con observaciones", "Desfavorable"],
    False: ["No contestó", "Número equivocado", "Buzón o fuera de servicio"],
}


def estado_documento(d: Documento) -> str:
    """Pendiente (sin archivo) → Recibido (subido, falta que RH lo revise) → Revisado (RH lo aprobó) |
    Requiere corrección (RH lo rechazó con motivo; el candidato lo vuelve a subir en la misma liga)."""
    if d.estado == "rechazado":
        return DOC_CORRECCION
    if d.aprobado:
        return DOC_REVISADO
    if d.archivo or d.estado == "recibido":
        return DOC_RECIBIDO
    return DOC_PENDIENTE


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def es_operativa(cuenta: Optional[Cuenta]) -> bool:
    return bool(cuenta and cuenta.flujo_candidatos == "operativo")


def es_operativo(p: Postulacion) -> bool:
    return es_operativa(p.cuenta)


def etapas_de(cuenta: Optional[Cuenta]) -> List[str]:
    from ..models import ETAPAS_CANDIDATO

    return list(ETAPAS_OPERATIVO) if es_operativa(cuenta) else list(ETAPAS_CANDIDATO)


def nota(p: Postulacion, evento: str, texto: str, usuario: str) -> None:
    """Historial legible de la postulación (solo se agrega)."""
    p.historial = [*(p.historial or []), {"evento": evento, "texto": texto, "usuario": usuario, "fecha": _ahora().isoformat()}]


def mover(db: Session, p: Postulacion, etapa: str, actor: str, motivo: str = "") -> None:
    if p.etapa == etapa:
        return
    anterior = p.etapa
    p.etapa = etapa
    p.ultima_actividad_en = _ahora()
    nota(p, "etapa", f"{anterior} → {etapa}" + (f" — {motivo}" if motivo else ""), actor)
    registrar(db, actor, "etapa_operativa", "postulacion", p.codigo, {"de": anterior, "a": etapa, "motivo": motivo[:300]})


# ------------------------------------------------------------ ganchos del prefiltro y del vehículo


def al_iniciar_prefiltro(db: Session, p: Postulacion) -> None:
    if es_operativo(p) and p.etapa == NUEVO:
        mover(db, p, PREFILTRO, "agente-ia", "El candidato empezó el prefiltro")


def al_cerrar_prefiltro(db: Session, p: Postulacion, requiere_fotos: bool) -> None:
    if not es_operativo(p) or p.etapa not in (NUEVO, PREFILTRO):
        return
    if p.estado == "cumple":
        mover(db, p, VEHICULO if requiere_fotos else CITA, "agente-ia", "Prefiltro: Cumple perfil")
    else:
        mover(db, p, PREFILTRO, "agente-ia", "Prefiltro terminado; RH revisa el resultado")


def al_aprobar_prefiltro(db: Session, p: Postulacion, actor: str, requiere_fotos: bool) -> None:
    if es_operativo(p) and p.etapa in (NUEVO, PREFILTRO):
        mover(db, p, VEHICULO if requiere_fotos else CITA, actor, "Prefiltro aprobado por RH")


def al_decidir_vehiculo(db: Session, p: Postulacion, accion: str, actor: str) -> None:
    if not es_operativo(p):
        return
    if accion in ("aprobar", "excepcion") and p.etapa in (NUEVO, PREFILTRO, VEHICULO):
        mover(db, p, CITA, actor, "Vehículo aprobado" if accion == "aprobar" else "Vehículo aprobado por excepción")
    elif accion == "correccion" and p.etapa in (NUEVO, PREFILTRO):
        mover(db, p, VEHICULO, actor, "Corrección de fotos solicitada")


# ------------------------------------------------------------ capacitación en tienda (evaluación unificada «Otra»)


def evaluacion_capacitacion(db: Session, p: Postulacion) -> Optional[EvaluacionCandidato]:
    """La evaluación «Capacitación en tienda» más reciente de la postulación."""
    return (
        db.query(EvaluacionCandidato)
        .filter(EvaluacionCandidato.postulacion_id == p.id, EvaluacionCandidato.tipo == "otra",
                EvaluacionCandidato.nombre == NOMBRE_CAPACITACION_TIENDA)
        .order_by(EvaluacionCandidato.id.desc())
        .first()
    )


def inscritos(db: Session, s: SesionCapacitacion) -> List[EvaluacionCandidato]:
    """Citados vigentes de la sesión (una cita cancelada o «no asistió» libera el lugar para otra sesión,
    pero sigue ocupando el suyo en la lista de asistencia de ESTA sesión)."""
    return (
        db.query(EvaluacionCandidato)
        .filter(EvaluacionCandidato.sesion_id == s.id)
        .order_by(EvaluacionCandidato.id)
        .all()
    )


def lugares_ocupados(db: Session, s: SesionCapacitacion) -> int:
    return sum(1 for ev in inscritos(db, s) if not (ev.estado == "fallida" and ev.asistencia != "no_asistio"))


def texto_cita(p: Postulacion, s: SesionCapacitacion) -> str:
    from .notificaciones import TZ_MEXICO

    nombre = (p.nombre or "").split(" ")[0] or "hola"
    cuando = s.inicio.astimezone(TZ_MEXICO).strftime("%d/%m/%Y a las %H:%M") if s.inicio else "por confirmar"
    partes = [
        f"¡Hola {nombre}! Tu vehículo quedó aprobado 🚗. Te citamos a la *{s.nombre}*:",
        f"📅 {cuando} h",
        f"📍 {s.tienda}" + (f" — {s.direccion}" if s.direccion else ""),
    ]
    if s.supervisor_nombre:
        partes.append(f"👤 Te recibe: {s.supervisor_nombre}")
    if s.indicaciones:
        partes.append(f"📝 {s.indicaciones}")
    partes.append("\n¿Confirmas tu asistencia? Responde *Sí*.")
    return "\n".join(partes)


async def citar(db: Session, p: Postulacion, s: SesionCapacitacion, actor: str) -> dict:
    """Cita al candidato a una sesión compartida (respeta el cupo) con la evaluación «Capacitación en tienda»
    (tipo «Otra»). Si ya tenía una cita abierta se REPROGRAMA a la nueva sesión (misma evaluación)."""
    from ..routers.candidatos import _enviar_whatsapp, guardar_mensaje

    ev = evaluacion_capacitacion(db, p)
    if ev and ev.estado == "revisada":
        ev = None  # ya se capacitó: una nueva cita es una evaluación nueva
    if ev is None or ev.estado == "fallida":
        ev = EvaluacionCandidato(
            codigo="TMP", cuenta_id=p.cuenta_id, postulacion_id=p.id, tipo="otra", nombre=NOMBRE_CAPACITACION_TIENDA,
            modo="manual", asignada_por=actor, estado="en_espera_consentimiento", historial=[],
        )
        db.add(ev)
        db.flush()
        ev.codigo = f"EVA-{7000 + ev.id}"
        sev.mover(ev, "en_espera_consentimiento", actor, "Asignada")
        sev.refrescar_consentimiento(ev, p, actor)
    anterior = ev.sesion_id
    ev.sesion_id, ev.cita_confirmada_en, ev.asistencia = s.id, None, ""
    sev.mover(ev, ev.estado, actor, f"Citado a {s.codigo} ({s.tienda})" + (" — reprogramada" if anterior and anterior != s.id else ""))
    texto = texto_cita(p, s)
    envio = await _enviar_whatsapp(p, texto)
    guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
    nota(p, "cita_capacitacion", f"Citado a {s.nombre} {s.codigo} ({s.tienda})", actor)
    registrar(db, actor, "cita_capacitacion", "postulacion", p.codigo, {"sesion": s.codigo, "evaluacion": ev.codigo, "whatsapp": envio.get("enviado", False)})
    if p.etapa in (NUEVO, PREFILTRO, VEHICULO):
        mover(db, p, CITA, actor, f"Citado a {s.codigo}")
    return {"evaluacion": ev, "whatsapp": envio}


async def confirmar_cita(db: Session, p: Postulacion, actor: str) -> dict:
    """El candidato (o RH por él) confirma la cita → se asigna el curso de inducción de la sesión y se SIMULA
    el envío de su PDF por WhatsApp (queda en el chat marcado como simulado; no sale por Meta)."""
    from ..models import Curso
    from ..routers.candidatos import guardar_mensaje
    from ..routers.capacitacion import asignar_a_postulacion

    ev = evaluacion_capacitacion(db, p)
    if not ev or not ev.sesion_id or ev.estado in ("revisada", "fallida"):
        raise ValueError("El candidato no tiene una cita de capacitación abierta.")
    if ev.cita_confirmada_en:
        return {"evaluacion": ev, "induccion": None, "ya_confirmada": True}
    ev.cita_confirmada_en = _ahora()
    sev.mover(ev, "en_proceso" if ev.estado == "pendiente" else ev.estado, actor, "Cita confirmada")
    s = db.get(SesionCapacitacion, ev.sesion_id)
    induccion = None
    curso = db.get(Curso, s.curso_induccion_id) if s and s.curso_induccion_id else None
    if curso:
        # La inducción es material de apoyo: si su asignación truena, la cita queda confirmada igual y el
        # supervisor puede registrar la asistencia (savepoint para no dejar la sesión de BD rota).
        try:
            with db.begin_nested():
                a = await asignar_a_postulacion(db, p, curso, actor=actor, notificar=False)
                liga = f"{settings.app_url}/capacitacion/{a.token}"
                texto = (
                    f"[Simulado · demo] 📄 {curso.titulo} (PDF)\n"
                    f"Antes de tu capacitación revisa este material. Descárgalo aquí: {liga}"
                )
                guardar_mensaje(db, p, "assistant", texto, "whatsapp", {"enviado": False, "proveedor": "simulado"})
                induccion = {"curso": curso.codigo, "titulo": curso.titulo, "asignacion": a.codigo, "liga": liga, "simulado": True}
                registrar(db, actor, "induccion_pdf_simulado", "postulacion", p.codigo, induccion)
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            induccion = None
            registrar(db, actor, "induccion_pdf_fallido", "postulacion", p.codigo, {"curso": curso.codigo, "error": str(e)[:300]})
    nota(p, "cita_confirmada", "Cita de capacitación confirmada" + (f"; se simuló el envío del PDF «{curso.titulo}»" if induccion else ""), actor)
    return {"evaluacion": ev, "induccion": induccion, "ya_confirmada": False}


def registrar_asistencia(db: Session, ev: EvaluacionCandidato, asistio: bool, resultado: str, comentario: str, supervisor: str) -> None:
    """Lo captura el SUPERVISOR en su liga. Asistió → dictamen (Apto / Requiere seguimiento / No apto =
    Favorable / Con observaciones / Desfavorable) y la postulación pasa a «Capacitación realizada». No asistió →
    la evaluación queda Fallida con motivo y la postulación sigue en «Cita para capacitación» para reprogramar."""
    p = db.get(Postulacion, ev.postulacion_id)
    quien = f"{supervisor} (supervisor)"
    if not asistio:
        ev.asistencia = "no_asistio"
        ev.motivo_fallida = "No asistió a la capacitación" + (f": {comentario}" if comentario else "")
        sev.mover(ev, "fallida", quien, ev.motivo_fallida)
        if p:
            nota(p, "capacitacion_no_asistio", ev.motivo_fallida, quien)
            registrar(db, quien, "capacitacion_no_asistio", "postulacion", p.codigo, {"evaluacion": ev.codigo})
        return
    ev.asistencia = "asistio"
    ev.resultado_resumen = f"Asistió · {RESULTADOS_CAPACITACION[resultado]}" + (f" — {comentario}" if comentario else "")
    ev.resultado_cargado_por, ev.resultado_cargado_en = quien, _ahora()
    sev.mover(ev, "resultado_recibido", quien, "Asistencia registrada")
    ev.dictamen, ev.comentario_revision = resultado, comentario[:2000]
    ev.revisada_por, ev.revisada_en = quien, _ahora()
    sev.mover(ev, "revisada", quien, f"Resultado: {RESULTADOS_CAPACITACION[resultado]}")
    if p:
        nota(p, "capacitacion_realizada", f"Capacitación: {RESULTADOS_CAPACITACION[resultado]}" + (f" — {comentario}" if comentario else ""), quien)
        registrar(db, quien, "capacitacion_resultado", "postulacion", p.codigo, {"evaluacion": ev.codigo, "resultado": resultado})
        if es_operativo(p) and p.etapa in (NUEVO, PREFILTRO, VEHICULO, CITA):
            mover(db, p, CAPACITADO, quien, RESULTADOS_CAPACITACION[resultado])


# ------------------------------------------------------------ documentos y referencias


def abrir_expediente(db: Session, p: Postulacion, actor: str):
    """Expediente de la postulación con los documentos de un chofer (idempotente: agrega los que falten)."""
    import secrets

    from ..models import Expediente

    e = p.expediente
    if e is None:
        e = Expediente(candidato_id=p.candidato_id, puesto=p.vacante.titulo if p.vacante else "", seleccionado_por=actor,
                       token=secrets.token_urlsafe(24), referencias=[])
        p.expediente = e
        db.add(e)
        db.flush()
        registrar(db, actor, "expediente_abierto", "postulacion", p.codigo, {"expediente": e.id, "flujo": "operativo"})
    tipos = {d.tipo for d in e.documentos}
    for tipo in DOCUMENTOS_OPERATIVO:
        if tipo not in tipos:
            db.add(Documento(expediente_id=e.id, tipo=tipo, obligatorio=True))
    db.flush()
    db.refresh(e)
    return e


def liga_expediente(e) -> str:
    return f"{settings.app_url}/expediente/{e.token}"


async def solicitar_documentos_referencias(db: Session, p: Postulacion, actor: str) -> dict:
    from ..routers.candidatos import _enviar_whatsapp, guardar_mensaje

    e = abrir_expediente(db, p, actor)
    liga = liga_expediente(e)
    nombre = (p.nombre or "").split(" ")[0] or "hola"
    texto = (
        f"¡Hola {nombre}! Para continuar con tu alta necesitamos tus documentos y 3 referencias personales "
        f"(nombre, teléfono y parentesco). Súbelos aquí, puedes volver las veces que necesites:\n📂 {liga}"
    )
    envio = await _enviar_whatsapp(p, texto)
    guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
    nota(p, "documentos_referencias_solicitados", "Se pidieron documentos y 3 referencias", actor)
    registrar(db, actor, "documentos_referencias_solicitados", "postulacion", p.codigo, {"expediente": e.id, "whatsapp": envio.get("enviado", False)})
    if p.etapa in (CAPACITADO,):
        mover(db, p, DOCUMENTOS, actor, "Documentos y referencias solicitados")
    return {"liga": liga, "whatsapp": envio}


def referencias_completas(e) -> bool:
    refs = [r for r in (e.referencias or []) if r.get("nombre") and r.get("telefono")]
    return len(refs) >= REFERENCIAS_REQUERIDAS


def faltantes_para_alta(p: Postulacion) -> List[str]:
    e = p.expediente
    if not e:
        return ["Pedir documentos y referencias"]
    faltan = [f"Documento: {t}" for t in e.no_aprobados]
    refs = [r for r in (e.referencias or []) if r.get("nombre") and r.get("telefono")]
    if len(refs) < REFERENCIAS_REQUERIDAS:
        faltan.append(f"Referencias capturadas: {len(refs)} de {REFERENCIAS_REQUERIDAS}")
    else:
        sin_contactar = [r["nombre"] for r in refs if not r.get("contactada")]
        if sin_contactar:
            faltan.append("Referencias por contactar: " + ", ".join(sin_contactar))
    return faltan


def revisar_listo(db: Session, p: Postulacion, actor: str) -> bool:
    """Si ya no falta nada, pasa sola a «Listo para alta» (y regresa a «Documentos y referencias» si algo
    dejó de cumplirse, p. ej. RH rechazó un documento)."""
    if not es_operativo(p) or p.etapa not in (DOCUMENTOS, LISTO):
        return False
    listo = not faltantes_para_alta(p)
    if listo and p.etapa == DOCUMENTOS:
        mover(db, p, LISTO, actor, "Documentos aprobados y 3 referencias contactadas")
    elif not listo and p.etapa == LISTO:
        mover(db, p, DOCUMENTOS, actor, "Falta algo del expediente")
    return listo


def guardar_referencias(db: Session, e, referencias: List[dict]) -> None:
    previas = {(r.get("telefono") or ""): r for r in (e.referencias or [])}
    nuevas = []
    for r in referencias[:REFERENCIAS_REQUERIDAS]:
        tel = r["telefono"]
        base = previas.get(tel) or {}
        nuevas.append({**base, "nombre": r["nombre"], "telefono": tel, "parentesco": r["parentesco"],
                       "capturada_en": base.get("capturada_en") or _ahora().isoformat(),
                       "contactada": bool(base.get("contactada"))})
    e.referencias = nuevas


def marcar_referencia(e, indice: int, contactada: bool, nota_rh: str, usuario: str, *, resultado: str = "",
                      fecha: Optional[datetime] = None) -> dict:
    """Registra una LLAMADA a la referencia (fecha, si se contactó, resultado y observaciones). Cada llamada se
    agrega a `llamadas` (nunca se borra); el estado de la referencia es el de la última llamada."""
    if resultado and resultado not in RESULTADOS_REFERENCIA[contactada]:
        raise ValueError(f"Resultado inválido. Usa uno de: {', '.join(RESULTADOS_REFERENCIA[contactada])}")
    fecha = fecha or _ahora()
    refs = [dict(r) for r in (e.referencias or [])]
    r = refs[indice]
    llamada = {"fecha": fecha.isoformat(), "contactada": contactada, "resultado": resultado,
               "observaciones": nota_rh[:500], "usuario": usuario, "registrada_en": _ahora().isoformat()}
    r.update({"contactada": contactada, "resultado": resultado, "nota": nota_rh[:500], "fecha_llamada": fecha.isoformat(),
              "contactada_por": usuario if contactada else "", "contactada_en": fecha.isoformat() if contactada else "",
              "llamadas": [*(r.get("llamadas") or []), llamada]})
    e.referencias = refs
    return r


# ------------------------------------------------------------ alta


def registrar_alta(db: Session, p: Postulacion, u, prueba: bool) -> Tuple[object, object]:
    """Crea el Colaborador con la función de siempre (`contratacion._crear_colaborador`) y deja la tarjeta en
    «Alta realizada» (la postulación NO se cierra: así la columna cuenta a quienes ya se dieron de alta)."""
    from ..routers.contratacion import _crear_colaborador

    e = p.expediente
    if e is None:
        e = abrir_expediente(db, p, u.nombre)
    if e.estado == "alta":
        raise ValueError(f"Ya se dio de alta (por {e.alta_autorizada_por}).")
    if not prueba and p.etapa != LISTO:
        raise ValueError("Primero debe estar en «Listo para alta»: " + "; ".join(faltantes_para_alta(p) or ["mueve la tarjeta"]))
    v = p.vacante
    e.puesto = e.puesto or (v.titulo if v else "")
    e.sueldo = e.sueldo or (v.sueldo if v else "")
    e.ubicacion = e.ubicacion or (v.ubicacion if v else "")
    e.tipo_contratacion = e.tipo_contratacion or "Tiempo indeterminado"
    e.fecha_ingreso = e.fecha_ingreso or _ahora()
    e.estado, e.alta_autorizada_por, e.alta_fecha = "alta", u.nombre, _ahora()
    colaborador = _crear_colaborador(db, e, u)
    registrar(db, u.nombre, "alta_autorizada", "expediente", str(e.id), {"postulacion": p.codigo, "flujo": "operativo"})
    mover(db, p, ALTA, u.nombre, f"Alta registrada ({colaborador.codigo if colaborador else ''})")
    p.estado = "cumple"
    p.resultado_apto = True
    return e, colaborador


# ------------------------------------------------------------ movimiento manual (Kanban)


def validar_movimiento(db: Session, p: Postulacion, destino: str, prueba: bool) -> None:
    """Candados del Kanban operativo para mover a mano. Hacia atrás siempre se puede; hacia adelante no se
    brinca lo que exige una decisión humana registrada. Modo Prueba los omite."""
    from . import vehiculo as vehiculo_srv

    if destino not in ETAPAS_OPERATIVO:
        raise ValueError(f"Etapa inválida. Usa una de: {', '.join(ETAPAS_OPERATIVO)}")
    if destino == ALTA:
        raise ValueError("A «Alta realizada» solo se llega con «Registrar alta».")
    if prueba or ETAPAS_OPERATIVO.index(destino) <= ETAPAS_OPERATIVO.index(p.etapa if p.etapa in ETAPAS_OPERATIVO else NUEVO):
        return
    orden = ETAPAS_OPERATIVO.index(destino)
    if orden > ETAPAS_OPERATIVO.index(VEHICULO):
        citable, motivo = vehiculo_srv.puede_citar(p)
        if not citable:
            raise ValueError(motivo)
    if orden > ETAPAS_OPERATIVO.index(CITA):
        ev = evaluacion_capacitacion(db, p)
        if not (ev and ev.estado == "revisada"):
            raise ValueError("Antes, el supervisor debe registrar la asistencia y el resultado de la capacitación.")
    if destino == LISTO and faltantes_para_alta(p):
        raise ValueError("Aún no está listo para alta: " + "; ".join(faltantes_para_alta(p)))
