"""Flujo OPERATIVO de candidatos (demo Grupo SEZA) — v3 (2026-10-01), Kanban de 5 columnas:

    Prefiltro → Revisión de vehículo → Entrevista → Contratación → Onboarding

Lo usa la Cuenta con `Cuenta.flujo_candidatos == "operativo"`. Aquí viven TODAS las transiciones (nada de
Zero-Touch ni del agente conversacional) y sus candados:

* Todo candidato nuevo entra a Prefiltro: «Sin iniciar» → «En curso» → «Completado»; el RESULTADO (Cumple perfil /
  Requiere revisión / No cumple) se muestra aparte (`estado_prefiltro` vs `Postulacion.estado`).
* Prefiltro → Revisión de vehículo: «Cumple perfil» (o RH aprueba un «Requiere revisión»). El candidato sube 4 fotos
  + licencia, tarjeta de circulación y póliza (los 3 documentos quedan en el EXPEDIENTE).
* Revisión de vehículo → Entrevista: RH aprueba el vehículo o marca excepción.
* Entrevista = entrevista y capacitación en tienda sobre `EntrevistaHumana` (tienda y dirección, fecha/hora,
  entrevistador/capacitador; sin grupos ni cupos). Al agendar, el candidato recibe cita, ubicación y el PDF de
  inducción; el entrevistador, cita, datos y su liga. El envío se registra aparte: un fallo NO bloquea. «Registrar
  entrevista» (fecha realizada, entrevistador, asistió, resultado, observaciones) por la liga o por RH a mano (aunque
  no esté confirmada ni agendada), con autor, fecha y vía. Subestados: Sin agendar / Agendada / Confirmada /
  Realizada (Apto / No apto) / No asistió + «Evaluaciones pendientes».
* v3: ya NO hay columna «Evaluación». Desde Entrevista RH agrega «Entrevista humana o evaluación» (psicométrica,
  técnica, referencias, médico, socioeconómico, otra): ninguna mueve la tarjeta y cada una conserva su estado. La
  ÚNICA salida es «Avanzar a Contratación» (manual), habilitada con la entrevista en tienda Apta y todas las
  evaluaciones con resultado y revisadas (`requisitos_contratacion`).
* Contratación: condiciones (puesto, sueldo, tipo, fecha) + «Generar contrato» (ahora) o «Generar después de
  Onboarding». «Enviar a Onboarding» pide los 6 documentos personales y 3 referencias.
* Onboarding: documentos + referencias (registro de llamadas; contactada ≠ VALIDADA: validar es una decisión
  aparte) → «Dar de alta» crea el Colaborador y CIERRA la postulación (`contratado`).

Toda decisión la toma una persona (RH o el capacitador) y queda en `Postulacion.historial` + bitácora. Modo Prueba
se salta los candados, como el resto de la plataforma.
"""

import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    DOCUMENTOS_VEHICULO,
    ETAPAS_OPERATIVO,
    RESULTADOS_CAPACITACION,
    Cuenta,
    Documento,
    EntrevistaHumana,
    Postulacion,
    Usuario,
    registrar,
)

PREFILTRO, VEHICULO, ENTREVISTA, CONTRATACION, ONBOARDING = ETAPAS_OPERATIVO

# Lo que pide Onboarding. Los del vehículo (licencia, tarjeta, póliza) ya están en el expediente desde la
# revisión del vehículo: NO se vuelven a pedir.
DOCUMENTOS_ONBOARDING = [
    "Identificación oficial (INE)",
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
DOC_PENDIENTE_REVISION = "Pendiente de revisión"  # el archivo se guardó pero la validación automática falló

# Resultado de la llamada a una referencia: depende de si se logró contactar.
RESULTADOS_REFERENCIA = {
    True: ["Favorable", "Con observaciones", "Desfavorable"],
    False: ["No contestó", "Número equivocado", "Buzón o fuera de servicio"],
}

# Subestado del Prefiltro (columna), separado del resultado.
PREFILTRO_SIN_INICIAR, PREFILTRO_EN_CURSO, PREFILTRO_COMPLETADO = "Sin iniciar", "En curso", "Completado"

CONTRATO_GENERADO, CONTRATO_DESPUES = "generado", "despues"


def estado_documento(d: Documento) -> str:
    """Pendiente (sin archivo) → Recibido (subido, falta que RH lo revise) → Revisado (RH lo aprobó) |
    Requiere corrección (RH lo rechazó con motivo; el candidato lo vuelve a subir en la misma liga)."""
    if d.estado == "rechazado":
        return DOC_CORRECCION
    if d.aprobado:
        return DOC_REVISADO
    if d.estado == "revision" and (d.validacion or {}).get("fallo_sistema"):
        return DOC_PENDIENTE_REVISION  # 2026-10-01: la validación automática falló; RH lo revisa
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


def _indice(etapa: str) -> int:
    return ETAPAS_OPERATIVO.index(etapa) if etapa in ETAPAS_OPERATIVO else 0


# ------------------------------------------------------------ prefiltro y vehículo


def estado_prefiltro(p: Postulacion) -> str:
    """Sin iniciar / En curso / Completado (la columna). El resultado va aparte en `Postulacion.estado`."""
    if p.prefiltro_completo:
        return PREFILTRO_COMPLETADO
    respuestas = ((p.analisis or {}).get("prefiltro_reglas") or {}).get("respuestas") or {}
    agente = ((p.analisis or {}).get("preguntas_agente") or {}).get("respuestas") or []
    return PREFILTRO_EN_CURSO if (respuestas or agente) else PREFILTRO_SIN_INICIAR


# ------------------------------------------------------------ paso 2: preguntas secundarias del agente (Telegram)
# Arquitectura de dos pasos (2026-10-01): (1) el portal web EXIGE el prefiltro de la vacante; (2) en Telegram, tras
# `/start <token>`, el agente saluda («Hola X. Vi que estás interesado en la vacante Y.») y hace SUS preguntas — nunca
# repite las del prefiltro web. Respaldo si la vacante no configuró preguntas de WhatsApp (RH las cambia en la vacante,
# «Configuración avanzada → Prefiltro WhatsApp»):
PREGUNTAS_AGENTE_VEHICULO = [
    "¿Qué marca y modelo es tu vehículo?",
    "¿Cuáles son las placas de tu vehículo?",
    "¿A partir de qué fecha podrías empezar?",
]
PREGUNTAS_AGENTE_BASE = [
    "¿A partir de qué fecha podrías empezar?",
    "¿Hay algo más que quieras contarnos sobre tu experiencia para este puesto?",
]


def _norm(t: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(ch for ch in t if ch.isalnum())


def _texto_pregunta(x) -> str:
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, dict):
        return str(x.get("pregunta") or x.get("texto") or "").strip()
    return ""


def preguntas_web(v) -> List[str]:
    """Lo que el candidato YA contestó en el portal: el prefiltro por reglas o las preguntas web de la vacante."""
    from . import prefiltro_reglas

    if v and prefiltro_reglas.activo(v.prefiltro_reglas):
        return [q["texto"] for q in prefiltro_reglas.preguntas(v.prefiltro_reglas)]
    return [t for t in (_texto_pregunta(x) for x in ((v.preguntas_filtro if v else None) or [])) if t]


def preguntas_agente(v) -> List[str]:
    """Preguntas secundarias del agente para esta vacante: sus «preguntas de prefiltro por WhatsApp» SIN las que repitan
    el prefiltro web; si no queda ninguna, el respaldo (del vehículo si la vacante revisa vehículo). Una por mensaje."""
    from . import prefiltro_reglas

    web = {_norm(t) for t in preguntas_web(v)}
    propias = [t for t in (_texto_pregunta(x) for x in ((v.preguntas_filtro_whatsapp if v else None) or [])) if t and _norm(t) not in web]
    if propias:
        return propias
    con_vehiculo = bool(v and prefiltro_reglas.activo(v.prefiltro_reglas) and (v.prefiltro_reglas or {}).get("fotos_vehiculo", True))
    return list(PREGUNTAS_AGENTE_VEHICULO if con_vehiculo else PREGUNTAS_AGENTE_BASE)


def agente_en_curso(p: Postulacion) -> bool:
    estado = (p.analisis or {}).get("preguntas_agente")
    return bool(estado) and not estado.get("completado_en")


def al_iniciar_prefiltro(db: Session, p: Postulacion) -> None:
    """Gancho del primer turno del prefiltro (la tarjeta ya nace en Prefiltro: solo queda en historial)."""
    if es_operativo(p) and p.etapa == PREFILTRO and not (p.historial or []):
        nota(p, "prefiltro_iniciado", "El candidato empezó el prefiltro", "agente-ia")


def al_cerrar_prefiltro(db: Session, p: Postulacion, requiere_fotos: bool) -> None:
    if not es_operativo(p) or p.etapa != PREFILTRO:
        return
    if p.estado == "cumple":
        mover(db, p, VEHICULO if requiere_fotos else ENTREVISTA, "agente-ia", "Prefiltro: Cumple perfil")
    else:
        nota(p, "prefiltro_completado", "Prefiltro completado; RH revisa el resultado", "agente-ia")


def al_aprobar_prefiltro(db: Session, p: Postulacion, actor: str, requiere_fotos: bool) -> None:
    if es_operativo(p) and p.etapa == PREFILTRO:
        mover(db, p, VEHICULO if requiere_fotos else ENTREVISTA, actor, "Prefiltro aprobado por RH")


def al_decidir_vehiculo(db: Session, p: Postulacion, accion: str, actor: str) -> None:
    if not es_operativo(p):
        return
    if accion in ("aprobar", "excepcion") and p.etapa in (PREFILTRO, VEHICULO):
        mover(db, p, ENTREVISTA, actor, "Vehículo aprobado" if accion == "aprobar" else "Vehículo aprobado por excepción")
    elif accion == "correccion" and p.etapa == PREFILTRO:
        mover(db, p, VEHICULO, actor, "Corrección solicitada")


# ------------------------------------------------------------ expediente (vive desde la revisión del vehículo)


def expediente(db: Session, p: Postulacion, actor: str, tipos: Optional[List[str]] = None):
    """Expediente de la postulación (lo crea si no existe) con los documentos `tipos` (idempotente: solo agrega
    los que falten; nunca borra ni duplica)."""
    from ..models import Expediente

    e = p.expediente
    if e is None:
        e = Expediente(candidato_id=p.candidato_id, puesto=p.vacante.titulo if p.vacante else "", seleccionado_por=actor,
                       token=secrets.token_urlsafe(24), referencias=[])
        p.expediente = e
        db.add(e)
        db.flush()
        registrar(db, actor, "expediente_abierto", "postulacion", p.codigo, {"expediente": e.id, "flujo": "operativo"})
    existentes = {d.tipo for d in e.documentos}
    nuevos = [t for t in (tipos or []) if t not in existentes]
    for tipo in nuevos:
        db.add(Documento(expediente_id=e.id, tipo=tipo, obligatorio=True))
    if nuevos:
        db.flush()
        db.refresh(e)
    return e


def abrir_expediente(db: Session, p: Postulacion, actor: str):
    """Expediente completo de un chofer: documentos del vehículo + los de Onboarding."""
    return expediente(db, p, actor, [*DOCUMENTOS_VEHICULO.values(), *DOCUMENTOS_ONBOARDING])


def liga_expediente(e) -> str:
    return f"{settings.app_url}/expediente/{e.token}"


# ------------------------------------------------------------ Entrevista = capacitación en tienda (EntrevistaHumana)


def entrevista_actual(p: Postulacion) -> Optional[EntrevistaHumana]:
    """La entrevista vigente (la más reciente no cancelada) de la postulación."""
    vivas = [eh for eh in (p.entrevistas_humanas or []) if not eh.cancelada]
    return vivas[-1] if vivas else None


# 2026-10-02: la cita nace «Pendiente de confirmación» (clave interna «agendada») y el material de inducción sale SOLO al
# confirmar. Si el candidato dice que no puede ir queda «No podrá asistir» hasta que RH reprograme o cancele.
PENDIENTE_CONFIRMACION = "Pendiente de confirmación"
FILTROS_ENTREVISTA = {"sin_agendar": "Sin agendar", "agendada": PENDIENTE_CONFIRMACION, "no_podra": "No podrá asistir",
                      "confirmada": "Confirmada", "realizada": "Realizada", "no_asistio": "No asistió"}
PREGUNTA_CONFIRMACION = "¿Confirmas que vas a asistir?"
SEGUIMIENTO_CONFIRMACION = "¿Podrás asistir? Necesitamos tu confirmación"
PREGUNTA_REAGENDAR = "¿Necesitas reagendar tu entrevista? Responde *Sí* o *No*."
# v3: dentro de «Realizadas» → Todos / Aptos / No aptos; y «Evaluaciones pendientes» (cualquier subestado).
FILTRO_APTO, FILTRO_NO_APTO, FILTRO_EVAL_PENDIENTES = "apto", "no_apto", "evaluaciones_pendientes"
FILTROS_PREFILTRO = {"sin_iniciar": PREFILTRO_SIN_INICIAR, "en_curso": PREFILTRO_EN_CURSO, "completado": PREFILTRO_COMPLETADO}


def clave_entrevista(eh: Optional[EntrevistaHumana]) -> str:
    if eh is None:
        return "sin_agendar"
    if eh.asistencia == "no_asistio":
        return "no_asistio"
    if eh.asistencia == "asistio":
        return "realizada"
    if eh.confirmada_en:
        return "confirmada"
    return "no_podra" if rechazo_cita(eh.postulacion, eh) else "agendada"


def entrevista_apta(eh: Optional[EntrevistaHumana]) -> Optional[bool]:
    """True = Apto (incluye «Requiere seguimiento», igual que `Postulacion.resultado_apto`); False = No apto;
    None = sin resultado (no asistió, sin registrar o sin cita)."""
    if not (eh and eh.asistencia == "asistio" and eh.resultado in RESULTADOS_CAPACITACION):
        return None
    return eh.resultado != "desfavorable"


def estado_entrevista(eh: Optional[EntrevistaHumana]) -> Tuple[str, str]:
    """(etiqueta, tono) del subestado de la columna Entrevista."""
    clave = clave_entrevista(eh)
    if clave == "realizada":
        if eh.resultado in RESULTADOS_CAPACITACION:
            tono = {"favorable": "good", "con_observaciones": "warn", "desfavorable": "bad"}[eh.resultado]
            return f"Realizada · {RESULTADOS_CAPACITACION[eh.resultado]}", tono
        return "Realizada", "good"
    return FILTROS_ENTREVISTA[clave], {"sin_agendar": "neutral", "agendada": "warn", "no_podra": "bad", "confirmada": "brand",
                                       "no_asistio": "bad"}[clave]


def capacitador_de(eh: EntrevistaHumana, db: Session) -> dict:
    """Nombre, teléfono y correo del capacitador (interno = perfil del Usuario; externo = lo capturado)."""
    if eh.tipo == "interno" and eh.usuario_id:
        u = db.get(Usuario, eh.usuario_id)
        if u:
            return {"tipo": "interno", "usuarioId": u.id, "nombre": u.nombre, "telefono": u.telefono or "", "correo": u.correo or ""}
    return {"tipo": "externo", "usuarioId": None, "nombre": eh.entrevistador or "", "telefono": eh.whatsapp_externo or "", "correo": eh.correo_externo or ""}


def liga_capacitador(eh: EntrevistaHumana) -> str:
    return f"{settings.app_url}/entrevista-humana/{eh.token}"


def _cuando(eh: EntrevistaHumana) -> str:
    from .notificaciones import TZ_MEXICO

    if not eh.fecha:
        return "por confirmar"
    # 2026-10-01: una fecha releída SIN zona (p. ej. SQLite) es UTC; antes se tomaba como hora local y el reenvío
    # de la cita salía con otra hora
    f = eh.fecha if eh.fecha.tzinfo else eh.fecha.replace(tzinfo=timezone.utc)
    return f.astimezone(TZ_MEXICO).strftime("%d/%m/%Y a las %H:%M")


def fecha_hora(eh: EntrevistaHumana) -> Tuple[str, str]:
    """(«05/10/2026», «09:00») en hora de México."""
    from .notificaciones import TZ_MEXICO

    if not eh.fecha:
        return "por confirmar", "por confirmar"
    f = (eh.fecha if eh.fecha.tzinfo else eh.fecha.replace(tzinfo=timezone.utc)).astimezone(TZ_MEXICO)
    return f.strftime("%d/%m/%Y"), f.strftime("%H:%M")


def lugar_cita(eh: EntrevistaHumana) -> str:
    return (eh.tienda or "") + (f", {eh.ubicacion}" if eh.ubicacion else "")


def texto_confirmada(p: Postulacion, eh: EntrevistaHumana, db: Session) -> str:
    """Respuesta EXACTA al confirmar (2026-10-02). La frase del material solo va si la cita tiene curso de inducción:
    nunca se promete un material que no existe."""
    fecha, hora = fecha_hora(eh)
    cap = capacitador_de(eh, db)["nombre"]
    texto = f"Perfecto, te esperamos el {fecha} a las {hora} en {lugar_cita(eh)}."
    if cap:
        texto += f" Te recibirá {cap}."
    if eh.curso_induccion_id:
        texto += " Te compartimos el material de inducción para que lo revises antes de asistir"
    return texto


def rechazo_cita(p: Optional[Postulacion], eh: Optional[EntrevistaHumana]) -> Optional[dict]:
    """El «no puedo asistir» del candidato para ESTA cita (se guarda en `Postulacion.analisis.cita_rechazo`). Una cita
    reprogramada o nueva lo deja sin efecto."""
    if p is None or eh is None:
        return None
    r = (p.analisis or {}).get("cita_rechazo")
    if not r or r.get("entrevista") != eh.id or r.get("fecha_cita") != (eh.fecha.isoformat() if eh.fecha else ""):
        return None
    return r


def _guardar_rechazo(p: Postulacion, r: Optional[dict]) -> None:
    analisis = dict(p.analisis or {})
    if r is None:
        analisis.pop("cita_rechazo", None)
    else:
        analisis["cita_rechazo"] = r
    p.analisis = analisis


async def notificar_reclutador_cita(db: Session, p: Postulacion, eh: EntrevistaHumana, titulo: str, detalle: str) -> Optional[dict]:
    """Aviso INMEDIATO al reclutador: nota en la ficha + bitácora (siempre) y correo al responsable de la vacante (o al
    correo de comunicación de la Cuenta). Nunca lanza."""
    from ..models import Cuenta, NotificacionEnviada
    from .correo import enviar_correo
    from .plantillas_correo import html_aviso

    nota(p, "cita_aviso_reclutador", f"{titulo}: {detalle}", "candidato")
    v = p.vacante
    correo = (v.responsable.correo if v and v.responsable and v.responsable.correo else "") or ""
    if not correo and p.cuenta_id:
        cu = db.get(Cuenta, p.cuenta_id)
        correo = (cu.correo_comunicacion or "") if cu else ""
    if not correo:
        return None
    fecha, hora = fecha_hora(eh)
    try:
        asunto, html = html_aviso(
            titulo, detalle,
            filas=[("Candidato", p.nombre or ""), ("Vacante", v.titulo if v else ""), ("Cita", f"{fecha} a las {hora} h"),
                   ("Lugar", lugar_cita(eh))],
            cta=("Ver candidato", f"{settings.app_url}/dashboard/candidatos?abrir={p.codigo}"),
        )
        envio = await enviar_correo(correo, asunto, html)
    except Exception as e:  # noqa: BLE001
        envio = {"enviado": False, "detalle": str(e)[:200]}
    db.add(NotificacionEnviada(cuenta_id=p.cuenta_id, candidato_id=p.candidato_id, evento="cita_no_asistira", destinatario_tipo="rh",
                               canal="correo", destino=correo, enviado=bool(envio.get("enviado")), detalle=str(envio.get("detalle", ""))[:300]))
    return envio


async def candidato_no_asistira(db: Session, p: Postulacion, eh: EntrevistaHumana, texto: str) -> None:
    """Paso 5: el candidato dice que no puede ir → queda «No podrá asistir», se le pregunta si necesita reagendar y se avisa
    de inmediato al reclutador."""
    _guardar_rechazo(p, {"entrevista": eh.id, "fecha_cita": eh.fecha.isoformat() if eh.fecha else "", "en": _ahora().isoformat(),
                         "texto": (texto or "")[:300], "reagendar": None})
    registrar(db, "candidato", "cita_no_asistira", "postulacion", p.codigo, {"entrevista_humana": eh.id, "texto": (texto or "")[:300]})
    await notificar_reclutador_cita(db, p, eh, "El candidato no podrá asistir a su entrevista",
                                    f"{p.nombre} avisó que no podrá asistir («{(texto or '').strip()[:200]}»). Se le preguntó si necesita reagendar.")


async def respuesta_reagendar(db: Session, p: Postulacion, eh: EntrevistaHumana, quiere: bool) -> None:
    r = dict(rechazo_cita(p, eh) or {})
    r["reagendar"] = quiere
    _guardar_rechazo(p, r)
    registrar(db, "candidato", "cita_reagendar_solicitado" if quiere else "cita_reagendar_rechazado", "postulacion", p.codigo,
              {"entrevista_humana": eh.id})
    await notificar_reclutador_cita(
        db, p, eh, "El candidato pide reagendar su entrevista" if quiere else "El candidato no reagendará su entrevista",
        f"{p.nombre} " + ("pidió una nueva fecha: reprograma la entrevista desde su ficha." if quiere
                          else "indicó que no necesita reagendar. Decide en su ficha si cancelas la entrevista o lo descartas."))


def texto_cita(p: Postulacion, eh: EntrevistaHumana, db: Session) -> str:
    """La cita COMPLETA (candidato, empresa, vacante, entrevistador, fecha, hora y lugar). «Reenviar cita» manda
    exactamente este mismo texto de la misma `EntrevistaHumana` (Cambios ZESE). 2026-10-02: sin confirmar SIEMPRE cierra
    con «¿Confirmas que vas a asistir?» y ya no anuncia el material (sale hasta que confirma)."""
    from ..serial import nombre_empresa_candidato

    nombre = (p.nombre or "").split(" ")[0] or "hola"
    cap = capacitador_de(eh, db)
    vac = p.vacante
    empresa = nombre_empresa_candidato(vac) if vac else ""
    partes = [
        f"¡Hola {nombre}! Te citamos a tu *entrevista*" + (f" para *{vac.titulo}*" if vac else "") + (f" en {empresa}" if empresa else "") + ":",
        f"📅 {_cuando(eh)} h",
        f"📍 {eh.tienda}" + (f" — {eh.ubicacion}" if eh.ubicacion else ""),
    ]
    if cap["nombre"]:
        partes.append(f"👤 Te recibe: {cap['nombre']}")
    if eh.comentario:
        partes.append(f"📝 {eh.comentario}")
    partes.append("\n✅ Tu asistencia ya está confirmada." if eh.confirmada_en else f"\n{PREGUNTA_CONFIRMACION}")
    return "\n".join(partes)


def texto_capacitador(p: Postulacion, eh: EntrevistaHumana, db: Session) -> str:
    cap = capacitador_de(eh, db)
    vac = p.vacante.titulo if p.vacante else "la vacante"
    return (
        f"Hola {cap['nombre'].split(' ')[0] if cap['nombre'] else ''}, tienes una entrevista:\n"
        f"👤 {p.nombre} · {vac}\n📅 {_cuando(eh)} h\n📍 {eh.tienda}" + (f" — {eh.ubicacion}" if eh.ubicacion else "")
        + f"\n\nAl terminar registra la asistencia y el resultado aquí: {liga_capacitador(eh)}"
    )


def _registrar_envio(eh: EntrevistaHumana, destinatario: str, canal: str, envio: dict, detalle_extra: str = "") -> dict:
    """Fila por CANAL con estado visible (Pendiente / Enviado / Entregado / Fallido, ver services/entregas.py)."""
    from . import entregas

    fila = entregas.fila(destinatario, canal, envio, liga_capacitador(eh) if destinatario == "capacitador" else "", detalle_extra)
    eh.envios = [*(eh.envios or []), fila][-30:]
    return fila


async def enviar_cita_candidato(db: Session, p: Postulacion, eh: EntrevistaHumana) -> dict:
    """Manda la cita al candidato por mensaje (plantilla aprobada de Meta sin exigir que haya escrito antes, o
    Telegram) Y, aparte, por correo: un canal nunca depende del otro. Nunca lanza: cada resultado queda en
    `eh.envios`. Regresa la fila del mensaje (compatibilidad); la del correo va en `eh.envios`."""
    from ..routers.candidatos import guardar_mensaje
    from . import entregas, whatsapp

    texto = texto_cita(p, eh, db)
    if p.telefono:
        cap = capacitador_de(eh, db)
        try:
            envio = await whatsapp.enviar_notificacion(
                p.telefono, texto, settings.meta_plantilla_cita,
                [(p.nombre or "").split(" ")[0], f"{_cuando(eh)} h", eh.tienda + (f" — {eh.ubicacion}" if eh.ubicacion else ""), cap["nombre"]])
            guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
        except Exception as e:  # noqa: BLE001 — un fallo de envío nunca bloquea la cita
            envio = {"enviado": False, "detalle": str(e)}
    else:
        envio = {"enviado": False, "pendiente": True, "detalle": "El candidato no tiene teléfono registrado."}
    fila_msg = _registrar_envio(eh, "candidato", "mensaje", envio)
    from . import telegram as tg

    tok = tg.asegurar_token_onboarding(p)  # liga directa a la cita en Telegram (sin volver a pedir datos ni vacante)
    correo = await entregas.correo_candidato(
        p, "Tu entrevista", f"Hola {(p.nombre or '').split(' ')[0]}, te citamos a tu entrevista. Confírmala en Telegram o comunícate con RH si necesitas otra fecha.",
        [("Vacante", p.vacante.titulo if p.vacante else "—"), ("Fecha", f"{_cuando(eh)} h"), ("Lugar", eh.tienda + (f" — {eh.ubicacion}" if eh.ubicacion else "")),
         ("Te recibe", capacitador_de(eh, db)["nombre"] or "—")]
        + ([("Indicaciones", eh.comentario)] if eh.comentario else []),
        cta=("Confirmar en Telegram", tg.liga_inicio_web(tok, "cita")))
    _registrar_envio(eh, "candidato", "correo", correo)
    return fila_msg


async def enviar_aviso_capacitador(db: Session, p: Postulacion, eh: EntrevistaHumana) -> List[dict]:
    """Aviso al capacitador con su liga (mensaje y/o correo, lo que tenga). Nunca lanza."""
    from . import whatsapp
    from .correo import enviar_correo
    from .plantillas_correo import html_aviso

    cap = capacitador_de(eh, db)
    salida = []
    texto = texto_capacitador(p, eh, db)
    if cap["telefono"]:
        try:
            envio = await whatsapp.enviar_notificacion(cap["telefono"], texto)  # plantilla aprobada: no exige que haya escrito
        except Exception as e:  # noqa: BLE001
            envio = {"enviado": False, "detalle": str(e)}
        salida.append(_registrar_envio(eh, "capacitador", "mensaje", envio))
    if cap["correo"]:
        try:
            asunto, html = html_aviso(
                "Entrevista asignada",
                f"Tienes una entrevista con {p.nombre}. Al terminar registra la asistencia y el resultado.",
                filas=[("Candidato", p.nombre), ("Vacante", p.vacante.titulo if p.vacante else ""), ("Fecha", f"{_cuando(eh)} h"),
                       ("Tienda", eh.tienda), ("Dirección", eh.ubicacion or "—")],
                cta=("Registrar resultado", liga_capacitador(eh)),
            )
            envio = await enviar_correo(cap["correo"], asunto, html)
        except Exception as e:  # noqa: BLE001
            envio = {"enviado": False, "detalle": str(e)}
        salida.append(_registrar_envio(eh, "capacitador", "correo", envio))
    if not salida:
        salida.append(_registrar_envio(eh, "capacitador", "—", {"enviado": False},
                                       "El entrevistador no tiene teléfono ni correo: comparte su liga a mano."))
    return salida


def _datos_entrevista(db: Session, p: Postulacion, eh: EntrevistaHumana, datos: dict) -> None:
    """Valida y aplica tienda, fecha/hora, capacitador, curso de inducción e indicaciones. ValueError si falta algo."""
    from ..models import Curso
    from .notificaciones import TZ_MEXICO

    tienda = (datos.get("tienda") or "").strip()
    if not tienda:
        raise ValueError("Indica la tienda de la entrevista.")
    try:
        fecha = datetime.fromisoformat(f"{datos.get('fecha')}T{datos.get('hora')}").replace(tzinfo=TZ_MEXICO).astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("Fecha u hora inválida (fecha: 2026-10-02, hora: 09:00).")
    tipo = datos.get("capacitador_tipo") or "interno"
    if tipo == "interno":
        u = db.query(Usuario).filter(Usuario.id == datos.get("capacitador_usuario_id"), Usuario.activo.is_(True)).first()
        if not u:
            raise ValueError("Elige al entrevistador (usuario de la Cuenta) o captura uno externo.")
        eh.tipo, eh.usuario_id, eh.entrevistador = "interno", u.id, u.nombre
        eh.correo_externo, eh.whatsapp_externo = "", ""
    else:
        nombre = (datos.get("capacitador_nombre") or "").strip()
        if not nombre:
            raise ValueError("Escribe el nombre del entrevistador.")
        eh.tipo, eh.usuario_id, eh.entrevistador = "externo", None, nombre[:150]
        eh.whatsapp_externo = "".join(ch for ch in (datos.get("capacitador_telefono") or "") if ch.isdigit())[-10:]
        eh.correo_externo = (datos.get("capacitador_correo") or "").strip()[:200]
    curso_id = None
    if datos.get("curso_induccion"):
        c = db.query(Curso).filter(Curso.codigo == datos["curso_induccion"], Curso.cuenta_id == p.cuenta_id).first()
        if not c:
            raise ValueError("El curso de inducción no existe en esta Cuenta.")
        curso_id = c.id
    eh.tienda = tienda[:200]
    eh.ubicacion = (datos.get("direccion") or "").strip()[:300]
    eh.fecha = fecha
    eh.modalidad = "Presencial"
    eh.comentario = (datos.get("indicaciones") or "").strip()[:1000]
    eh.curso_induccion_id = curso_id


async def programar_entrevista(db: Session, p: Postulacion, datos: dict, actor: str) -> dict:
    """Cita a la capacitación en tienda (una EntrevistaHumana nueva; una cita anterior abierta se cancela). Mueve
    la tarjeta a Entrevista si venía de antes. El envío al candidato y el aviso al capacitador van APARTE y nunca
    bloquean: regresa {entrevista, envioCandidato, envioCapacitador}."""
    previa = entrevista_actual(p)
    if previa and not previa.realizada and not previa.asistencia:
        previa.cancelada = True
    eh = EntrevistaHumana(candidato_id=p.candidato_id, token=secrets.token_urlsafe(24), envios=[])
    _datos_entrevista(db, p, eh, datos)
    p.entrevistas_humanas.append(eh)
    db.flush()
    nota(p, "entrevista_programada", f"Entrevista: {eh.tienda}, {_cuando(eh)} h — entrevistador {eh.entrevistador}", actor)
    registrar(db, actor, "capacitacion_tienda_programada", "postulacion", p.codigo,
              {"tienda": eh.tienda, "fecha": eh.fecha.isoformat(), "capacitador": eh.entrevistador, "tipo": eh.tipo})
    if _indice(p.etapa) < _indice(ENTREVISTA):
        mover(db, p, ENTREVISTA, actor, "Citado a entrevista")
    envio_c = await enviar_cita_candidato(db, p, eh)
    # 2026-10-02: la cita queda «Pendiente de confirmación»; el material de inducción sale hasta que el candidato confirma
    envio_k = await enviar_aviso_capacitador(db, p, eh)
    return {"entrevista": eh, "envioCandidato": envio_c, "envioCapacitador": envio_k, "induccion": None}


async def reprogramar_entrevista(db: Session, p: Postulacion, datos: dict, actor: str) -> dict:
    eh = entrevista_actual(p)
    if eh is None:
        raise ValueError("No hay una entrevista programada.")
    if eh.resultado or eh.asistencia:
        raise ValueError("Esta entrevista ya tiene resultado; programa una nueva.")
    _datos_entrevista(db, p, eh, datos)
    eh.confirmada_en = None
    eh.confirmada_por = ""
    _guardar_rechazo(p, None)  # nueva fecha: vuelve a «Pendiente de confirmación»
    nota(p, "entrevista_reprogramada", f"Entrevista reprogramada: {eh.tienda}, {_cuando(eh)} h", actor)
    registrar(db, actor, "capacitacion_tienda_reprogramada", "postulacion", p.codigo, {"fecha": eh.fecha.isoformat(), "tienda": eh.tienda})
    envio_c = await enviar_cita_candidato(db, p, eh)
    envio_k = await enviar_aviso_capacitador(db, p, eh)
    return {"entrevista": eh, "envioCandidato": envio_c, "envioCapacitador": envio_k, "induccion": None}


def cancelar_entrevista(db: Session, p: Postulacion, motivo: str, actor: str) -> None:
    eh = entrevista_actual(p)
    if eh is None:
        raise ValueError("No hay una entrevista programada.")
    if eh.resultado or eh.asistencia:
        raise ValueError("Esta entrevista ya tiene resultado.")
    eh.cancelada = True
    nota(p, "entrevista_cancelada", "Entrevista cancelada" + (f" — {motivo}" if motivo else ""), actor)
    registrar(db, actor, "capacitacion_tienda_cancelada", "postulacion", p.codigo, {"motivo": motivo[:300]})


def induccion_enviada(eh: EntrevistaHumana) -> bool:
    return any(x.get("destinatario") == "candidato" and x.get("canal") == "induccion" and x.get("enviado") for x in (eh.envios or []))


async def enviar_material_una_vez(db: Session, p: Postulacion, eh: EntrevistaHumana, actor: str) -> Optional[dict]:
    """El material de inducción sale UNA sola vez por cita (2026-10-02: al confirmar)."""
    if induccion_enviada(eh):
        return None
    return await enviar_induccion(db, p, eh, actor)


async def confirmar_cita(db: Session, p: Postulacion, actor: str, enviar_material: bool = True) -> dict:
    """El candidato (por Telegram/WhatsApp) o RH por él confirma la cita → «Confirmada» y, en ese momento, sale el
    material de inducción (una sola vez). El chat pasa `enviar_material=False` para mandar primero la respuesta exacta y
    después el material (`enviar_material_una_vez`)."""
    eh = entrevista_actual(p)
    if eh is None or eh.realizada or eh.asistencia:
        raise ValueError("El candidato no tiene una cita de entrevista abierta.")
    if eh.confirmada_en:
        return {"entrevista": eh, "induccion": None, "ya_confirmada": True}
    eh.confirmada_en = _ahora()
    eh.confirmada_por = actor[:150]
    _guardar_rechazo(p, None)
    induccion = await enviar_material_una_vez(db, p, eh, actor) if enviar_material else None
    nota(p, "cita_confirmada", "Cita de entrevista confirmada", actor)
    return {"entrevista": eh, "induccion": induccion, "ya_confirmada": False}


async def enviar_induccion(db: Session, p: Postulacion, eh: EntrevistaHumana, actor: str) -> Optional[dict]:
    """Material de inducción (PDF) al candidato: se asigna el curso y sale su liga + el PDF (por Telegram como
    archivo; con otro proveedor queda simulado en el chat). Nunca bloquea la cita: un fallo queda en bitácora."""
    from ..models import Curso
    from ..routers.candidatos import _enviar_whatsapp, guardar_mensaje
    from ..routers.capacitacion import asignar_a_postulacion
    from . import whatsapp

    induccion = None
    curso = db.get(Curso, eh.curso_induccion_id) if eh.curso_induccion_id else None
    if curso:
        try:
            with db.begin_nested():
                a = await asignar_a_postulacion(db, p, curso, actor=actor, notificar=False)
                liga = f"{settings.app_url}/capacitacion/{a.token}"
                real = whatsapp.proveedor() == "telegram"  # por Telegram el PDF sale de verdad
                texto = (
                    ("" if real else "[Simulado · demo] ") + f"📄 {curso.titulo} (PDF)\n"
                    f"Antes de tu entrevista revisa este material. Descárgalo aquí: {liga}"
                )
                envio = {"enviado": False, "proveedor": "simulado"}
                if real:
                    envio = await _enviar_whatsapp(p, texto)
                    pdf = await _pdf_induccion(curso, a)
                    if pdf and p.telefono:
                        envio["pdf"] = await whatsapp.enviar_documento(p.telefono, pdf, f"{curso.titulo}.pdf", f"📄 {curso.titulo}")
                guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
                induccion = {"curso": curso.codigo, "titulo": curso.titulo, "asignacion": a.codigo, "liga": liga, "simulado": not real,
                             "enviado": bool(envio.get("enviado"))}
                _registrar_envio(eh, "candidato", "induccion", {**envio, "enviado": bool(envio.get("enviado")) or not real,
                                                                "detalle": envio.get("detalle") or ("simulado (demo)" if not real else "")})
                registrar(db, actor, "induccion_pdf_enviado" if real else "induccion_pdf_simulado", "postulacion", p.codigo, induccion)
                nota(p, "induccion_enviada", f"Material de inducción «{curso.titulo}» compartido", actor)
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            induccion = None
            registrar(db, actor, "induccion_pdf_fallido", "postulacion", p.codigo, {"curso": curso.codigo, "error": str(e)[:300]})
    return induccion


async def _pdf_induccion(curso, asignacion) -> Optional[bytes]:
    """PDF del curso de inducción (el mismo que se descarga de la liga); None si no se pudo generar."""
    try:
        from ..routers.capacitacion import _datos_pdf_curso
        from .pdf import pdf_curso

        return pdf_curso(_datos_pdf_curso(curso, asignacion))
    except Exception as e:  # noqa: BLE001 — el texto con la liga ya salió; el adjunto es extra
        print(f"[induccion] no se pudo generar el PDF de {curso.codigo}: {e}")
        return None


def validar_resultado(asistio: bool, resultado: str, comentario: str) -> None:
    if asistio and resultado not in RESULTADOS_CAPACITACION:
        raise ValueError("Elige el resultado: Apto, Requiere seguimiento o No apto.")
    if asistio and resultado in ("con_observaciones", "desfavorable") and not comentario.strip():
        raise ValueError("Escribe un comentario que explique el resultado.")


def registrar_resultado(db: Session, p: Postulacion, eh: Optional[EntrevistaHumana], asistio: bool, resultado: str, comentario: str,
                        quien: str, capturado_por: str, *, fecha_realizada: Optional[datetime] = None, entrevistador: str = "") -> EntrevistaHumana:
    """«Registrar entrevista»: fecha realizada, entrevistador, asistió/no asistió, resultado y observaciones. Por la
    liga del entrevistador o por RH a mano (aunque no esté confirmada, e incluso sin cita: entonces la crea). Guarda
    autor (`registrado_por`), fecha (`evaluada_en`) y vía (`resultado_capturado_por`: entrevistador | rh). No mueve
    la tarjeta: RH decide con «Avanzar a Contratación». «No asistió» deja la cita lista para reprogramar."""
    validar_resultado(asistio, resultado, comentario)
    if eh is None:
        eh = EntrevistaHumana(candidato_id=p.candidato_id, token=secrets.token_urlsafe(24), envios=[], modalidad="Presencial",
                              tipo="externo", entrevistador=(entrevistador or quien)[:150], fecha=fecha_realizada or _ahora())
        p.entrevistas_humanas.append(eh)
        db.flush()
    if entrevistador.strip():
        eh.entrevistador = entrevistador.strip()[:150]
    eh.asistencia = "asistio" if asistio else "no_asistio"
    eh.realizada = asistio
    eh.resultado = resultado if asistio else ""
    eh.comentario = comentario.strip()[:2000] or eh.comentario
    eh.resultado_capturado_por = capturado_por
    eh.registrado_por = quien[:150]
    eh.realizada_en = fecha_realizada or _ahora()
    eh.evaluada_en = _ahora()
    if asistio:
        texto = f"Entrevista: {RESULTADOS_CAPACITACION[resultado]}" + (f" — {comentario.strip()}" if comentario.strip() else "")
        p.resultado_apto = resultado != "desfavorable"
    else:
        texto = "No asistió a la entrevista" + (f": {comentario.strip()}" if comentario.strip() else "")
    nota(p, "capacitacion_resultado", texto + f" (vía {'liga del entrevistador' if capturado_por == 'entrevistador' else 'captura de RH'})", quien)
    registrar(db, quien, "capacitacion_tienda_resultado", "postulacion", p.codigo,
              {"asistio": asistio, "resultado": resultado, "capturado_por": capturado_por, "realizada_en": eh.realizada_en.isoformat()})
    return eh


# ------------------------------------------------------------ evaluaciones adicionales (sin columna propia)


def evaluaciones_vivas(db: Session, p: Postulacion) -> list:
    """Evaluaciones de la postulación que cuentan (sin canceladas ni la «Capacitación en tienda» de la v1, que ya vive
    en la Entrevista). [] si el módulo no está disponible."""
    from ..models import EvaluacionCandidato
    from . import evaluaciones as sev

    try:
        evs = db.query(EvaluacionCandidato).filter(EvaluacionCandidato.postulacion_id == p.id).order_by(EvaluacionCandidato.id).all()
    except Exception:  # noqa: BLE001 — tablas del paso NO fatal ausentes
        return []
    return [e for e in evs if e.estado != "fallida" and not sev.es_legado(e)]


def evaluaciones_pendientes(evs: list) -> list:
    """Solicitadas sin resultado o con resultado sin revisar."""
    return [e for e in evs if e.estado != "revisada"]


def requisitos_contratacion(db: Session, p: Postulacion) -> List[str]:
    """Lo que falta para «Avanzar a Contratación»: entrevista en tienda Apta y TODAS las evaluaciones (incluida la
    entrevista humana adicional) con resultado y revisadas; una entrevista humana adicional No apta también frena.
    Un dictamen desfavorable de otra evaluación ya revisada NO frena: RH lo vio y decide."""
    from ..models import ESTADOS_EVALUACION

    faltan = []
    apta = entrevista_apta(entrevista_actual(p))
    if apta is None:
        faltan.append("Registrar la entrevista (asistió y resultado)")
    elif apta is False:
        faltan.append("La entrevista quedó No apto")
    for e in evaluaciones_vivas(db, p):
        if e.estado == "resultado_recibido":
            faltan.append(f"{e.nombre}: resultado recibido, falta «Marcar como revisada»")
        elif e.estado != "revisada":
            faltan.append(f"{e.nombre}: {ESTADOS_EVALUACION.get(e.estado, e.estado)} (falta resultado y revisión)")
        elif e.tipo == "entrevista_humana" and e.dictamen == "no_apto":
            faltan.append(f"{e.nombre}: No apto")
    return faltan


def avanzar_a_contratacion(db: Session, p: Postulacion, actor: str, prueba: bool) -> None:
    """La ÚNICA forma de salir de Entrevista hacia adelante (manual, la ejecuta RH)."""
    if p.etapa != ENTREVISTA:
        raise ValueError("«Avanzar a Contratación» se usa desde la columna Entrevista.")
    faltan = requisitos_contratacion(db, p)
    if faltan and not prueba:
        raise ValueError("Antes de avanzar a Contratación: " + "; ".join(faltan) + ".")
    mover(db, p, CONTRATACION, actor, "Avanzar a Contratación" + (" (Modo Prueba)" if faltan else ""))


def resultados_tarjeta(p: Postulacion) -> List[dict]:
    """Resultados visibles en la tarjeta: Perfil (prefiltro), Vehículo y Entrevista. Solo los que ya existen."""
    salida = []
    if p.prefiltro_completo and p.estado in ("cumple", "no_cumple", "revision"):
        aprobado = ((p.analisis or {}).get("prefiltro_reglas") or {}).get("aprobado_por_rh")
        if p.estado == "cumple" or aprobado:
            salida.append({"clave": "perfil", "texto": "Perfil cumple", "tono": "good"})
        elif p.estado == "no_cumple":
            salida.append({"clave": "perfil", "texto": "Perfil no cumple", "tono": "bad"})
        else:
            salida.append({"clave": "perfil", "texto": "Perfil en revisión", "tono": "warn"})
    r = p.revision_vehiculo
    if r and r.estado in ("aprobado", "excepcion"):
        salida.append({"clave": "vehiculo", "texto": "Vehículo aprobado" + (" (excepción)" if r.estado == "excepcion" else ""), "tono": "good"})
    elif r and r.estado == "correccion":
        salida.append({"clave": "vehiculo", "texto": "Vehículo no aprobado", "tono": "bad"})
    eh = entrevista_actual(p)
    apta = entrevista_apta(eh)
    if apta is True:
        salida.append({"clave": "entrevista", "texto": "Entrevista apto" + (" · seguimiento" if eh.resultado == "con_observaciones" else ""), "tono": "good"})
    elif apta is False:
        salida.append({"clave": "entrevista", "texto": "Entrevista no apto", "tono": "bad"})
    elif eh and eh.asistencia == "no_asistio":
        salida.append({"clave": "entrevista", "texto": "Entrevista: no asistió", "tono": "bad"})
    return salida


def pendientes_de_etapa(db: Session, p: Postulacion) -> List[str]:
    """Lo que falta para avanzar desde la columna actual (lo mismo que validan los candados)."""
    from . import vehiculo as vehiculo_srv

    if p.etapa == PREFILTRO:
        if not p.prefiltro_completo:
            return ["El candidato debe terminar el prefiltro"]
        if p.estado != "cumple" and not ((p.analisis or {}).get("prefiltro_reglas") or {}).get("aprobado_por_rh"):
            return ["RH debe revisar el resultado del prefiltro (aprobar con motivo o descartar)"]
        return []
    if p.etapa == VEHICULO:
        citable, motivo = vehiculo_srv.puede_citar(p)
        return [] if citable else [motivo]
    if p.etapa == ENTREVISTA:
        return requisitos_contratacion(db, p)
    if p.etapa == CONTRATACION:
        return requisitos_onboarding(p)
    if p.etapa == ONBOARDING:
        return [] if (p.expediente and p.expediente.estado == "alta") else faltantes_para_alta(p)
    return []


def resumen_ficha(db: Session, p: Postulacion) -> dict:
    """Pestaña «Resumen» del flujo operativo (Zeze punto 7): etapa actual, resultado integral, estado de cada validación,
    observaciones relevantes y requisitos pendientes. Todo sale de los registros (nada inventado)."""
    from ..models import ESTADOS_EVALUACION
    from . import evaluaciones as sev
    from . import prefiltro_reglas

    validaciones, observaciones = [], []
    pr = (p.analisis or {}).get("prefiltro_reglas") or {}
    aprobado = pr.get("aprobado_por_rh")
    if p.prefiltro_completo:
        tono = "good" if p.estado == "cumple" or aprobado else "bad" if p.estado == "no_cumple" else "warn"
        validaciones.append({"nombre": "Prefiltro", "estado": prefiltro_reglas.RESULTADOS.get(p.estado, p.estado) + (" · aprobado por RH" if aprobado and p.estado != "cumple" else ""), "tono": tono})
        observaciones += [f"Prefiltro: {m.get('motivo')}" for m in ((pr.get("evaluacion") or {}).get("motivos") or [])[:3] if m.get("motivo")]
    else:
        validaciones.append({"nombre": "Prefiltro", "estado": estado_prefiltro(p), "tono": "neutral"})
    r = p.revision_vehiculo
    if r:
        from ..models import ESTADOS_VEHICULO

        validaciones.append({"nombre": "Vehículo", "estado": ESTADOS_VEHICULO.get(r.estado, r.estado),
                             "tono": {"aprobado": "good", "excepcion": "good", "correccion": "bad", "por_revisar": "warn"}.get(r.estado, "neutral")})
        if r.comentario:
            observaciones.append(f"Vehículo: {r.comentario}")
    else:
        validaciones.append({"nombre": "Vehículo", "estado": "Sin revisión", "tono": "neutral"})
    eh = entrevista_actual(p)
    texto_e, tono_e = estado_entrevista(eh)
    validaciones.append({"nombre": "Entrevista", "estado": texto_e, "tono": tono_e})
    if eh and eh.asistencia and eh.comentario:
        observaciones.append(f"Entrevista ({eh.entrevistador or 'entrevistador'}): {eh.comentario}")
    evs = evaluaciones_vivas(db, p)
    for e in evs:
        estado = sev.estado_visible(e)
        if e.estado == "revisada" and e.dictamen:
            estado += f" · {sev.dictamenes_de(e.tipo).get(e.dictamen, e.dictamen)}"
        tono = ("bad" if e.dictamen in sev.DICTAMENES_DESFAVORABLES else "good") if e.estado == "revisada" else "warn" if e.estado == "resultado_recibido" else "neutral"
        validaciones.append({"nombre": e.nombre, "estado": estado, "tono": tono, "evaluacion": e.codigo})
        if e.comentario_revision and not e.es_medico:
            observaciones.append(f"{e.nombre} (RH): {e.comentario_revision}")
    # resultado integral: No apto si algo salió desfavorable; Apto si todo está decidido y favorable; si no, En proceso
    apta = entrevista_apta(eh)
    negativo = (p.prefiltro_completo and p.estado == "no_cumple" and not aprobado) or (r and r.estado == "correccion") or apta is False         or any(e.estado == "revisada" and e.dictamen in sev.DICTAMENES_DESFAVORABLES for e in evs)
    positivo = (p.prefiltro_completo and (p.estado == "cumple" or aprobado)) and (r is None or r.estado in ("aprobado", "excepcion"))         and apta is True and all(e.estado == "revisada" for e in evs)
    integral = ({"texto": "No apto", "tono": "bad", "detalle": "Hay un resultado desfavorable; RH decide si descarta."} if negativo
                else {"texto": "Apto", "tono": "good", "detalle": "Validaciones completas y favorables."} if positivo
                else {"texto": "En proceso", "tono": "warn", "detalle": "Faltan validaciones por concluir."})
    agente = (p.analisis or {}).get("preguntas_agente") or {}
    if agente_en_curso(p):
        validaciones.insert(1, {"nombre": "Preguntas del agente (Telegram)", "estado": f"En curso · {len(agente.get('respuestas') or [])} respondida(s)", "tono": "warn"})
    elif agente.get("completado_en"):
        validaciones.insert(1, {"nombre": "Preguntas del agente (Telegram)", "estado": "Completadas", "tono": "good"})
    return {"etapa": p.etapa, "resultadoIntegral": integral, "validaciones": validaciones, "observaciones": observaciones[:8],
            "pendientes": pendientes_de_etapa(db, p),
            "respuestasAgente": [{"pregunta": x.get("pregunta", ""), "respuesta": x.get("respuesta", ""), "fecha": x.get("fecha")}
                                 for x in (agente.get("respuestas") or [])]}


def evaluacion_resumen(p: Postulacion) -> dict:
    """Lo que reúne la Evaluación del flujo operativo: resultado del prefiltro, revisión del vehículo y la entrevista en
    tienda. RH lo revisa y decide si pasa a Contratación."""
    from ..models import ESTADOS_VEHICULO
    from . import prefiltro_reglas

    pr = ((p.analisis or {}).get("prefiltro_reglas") or {}).get("evaluacion") or {}
    aprobado = ((p.analisis or {}).get("prefiltro_reglas") or {}).get("aprobado_por_rh")
    r = p.revision_vehiculo
    eh = entrevista_actual(p)
    return {
        "prefiltro": {
            "resultado": p.estado if p.prefiltro_completo else "",
            "etiqueta": prefiltro_reglas.RESULTADOS.get(p.estado, "") if p.prefiltro_completo else "Sin completar",
            "motivos": [m.get("motivo", "") for m in pr.get("motivos", [])],
            "aprobadoPorRH": aprobado,
        },
        "vehiculo": {
            "estado": r.estado if r else "",
            "etiqueta": ESTADOS_VEHICULO.get(r.estado, r.estado) if r else "Sin revisión",
            "decididoPor": (r.decidido_por or "") if r else "",
            "comentario": (r.comentario or "") if r else "",
        },
        "entrevista": {
            "estado": estado_entrevista(eh)[0],
            "resultado": eh.resultado if eh else "",
            "resultadoEtiqueta": RESULTADOS_CAPACITACION.get(eh.resultado or "", "") if eh else "",
            "observaciones": (eh.comentario or "") if eh else "",
            "entrevistador": (eh.entrevistador or "") if eh else "",
            "registradoPor": (eh.registrado_por or "") if eh else "",
            "via": (eh.resultado_capturado_por or "") if eh else "",
            "realizadaEn": eh.realizada_en.isoformat() if eh and eh.realizada_en else None,
        },
    }


# ------------------------------------------------------------ contratación


def condiciones_completas(e) -> bool:
    return bool(e and e.puesto and e.sueldo and e.tipo_contratacion and e.fecha_ingreso)


def requisitos_onboarding(p: Postulacion) -> List[str]:
    """Lo que falta para «Enviar a Onboarding»: condiciones guardadas + decisión del contrato + consentimiento."""
    e = p.expediente
    faltan = []
    if not condiciones_completas(e):
        faltan.append("Guardar condiciones (puesto, sueldo, tipo de contratación y fecha de ingreso)")
    if not (e and e.contrato_operativo in (CONTRATO_GENERADO, CONTRATO_DESPUES)):
        faltan.append("Elegir «Generar contrato» o «Generar después de Onboarding»")
    if not p.consentimiento:
        faltan.append("Consentimiento de privacidad del candidato")
    return faltan


def decidir_contrato(db: Session, p: Postulacion, cuando: str, actor: str) -> None:
    """«ahora» = el contrato se genera ya (vista previa del PDF); «despues» = queda pendiente para Onboarding."""
    if cuando not in ("ahora", "despues"):
        raise ValueError("Elige «ahora» o «despues».")
    e = expediente(db, p, actor)
    if cuando == "ahora" and not condiciones_completas(e):
        raise ValueError("Guarda primero las condiciones (puesto, sueldo, tipo y fecha de ingreso).")
    e.contrato_operativo = CONTRATO_GENERADO if cuando == "ahora" else CONTRATO_DESPUES
    e.contrato_operativo_por, e.contrato_operativo_en = actor, _ahora()
    texto = "Contrato generado" if cuando == "ahora" else "Contrato pendiente: se generará después de Onboarding"
    nota(p, "contrato_operativo", texto, actor)
    registrar(db, actor, "contrato_operativo_" + e.contrato_operativo, "postulacion", p.codigo, {"expediente": e.id})


# ------------------------------------------------------------ onboarding: documentos, referencias y alta


async def solicitar_documentos_referencias(db: Session, p: Postulacion, actor: str) -> dict:
    """Asegura los documentos de Onboarding y manda la liga (documentos + 3 referencias). Nunca lanza por el envío."""
    from ..routers.candidatos import _enviar_whatsapp, guardar_mensaje

    e = expediente(db, p, actor, DOCUMENTOS_ONBOARDING)
    liga = liga_expediente(e)
    nombre = (p.nombre or "").split(" ")[0] or "hola"
    texto = (
        f"¡Hola {nombre}! Para continuar con tu alta necesitamos tus documentos (INE, comprobante de domicilio, CURP, "
        f"constancia fiscal, NSS y cuenta bancaria) y 3 referencias personales (nombre, teléfono y parentesco). "
        f"Súbelos aquí, puedes volver las veces que necesites:\n📂 {liga}"
    )
    try:
        envio = await _enviar_whatsapp(p, texto)
        guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
    except Exception as ex:  # noqa: BLE001
        envio = {"enviado": False, "detalle": str(ex)}
    from . import entregas

    correo = await entregas.correo_candidato(  # aparte del mensaje: el correo nunca depende de WhatsApp
        p, "Documentos para tu alta", "Para continuar con tu alta sube tus documentos (INE, comprobante de domicilio, CURP, constancia "
        "fiscal, NSS y cuenta bancaria) y 3 referencias personales. Puedes volver a la liga las veces que necesites.",
        cta=("Subir documentos", liga))
    nota(p, "documentos_referencias_solicitados", "Se pidieron documentos y 3 referencias", actor)
    registrar(db, actor, "documentos_referencias_solicitados", "postulacion", p.codigo,
              {"expediente": e.id, "whatsapp": envio.get("enviado", False), "correo": correo.get("enviado", False)})
    return {"liga": liga, "whatsapp": envio, "correo": correo,
            "envios": [entregas.fila("candidato", "mensaje", envio if p.telefono else {**envio, "pendiente": True}, liga),
                       entregas.fila("candidato", "correo", correo, liga)]}


async def enviar_a_onboarding(db: Session, p: Postulacion, actor: str, prueba: bool) -> dict:
    faltan = requisitos_onboarding(p)
    if faltan and not prueba:
        raise ValueError("Antes de enviar a Onboarding: " + "; ".join(faltan) + ".")
    mover(db, p, ONBOARDING, actor, "Enviado a Onboarding")
    return await solicitar_documentos_referencias(db, p, actor)


def referencias_completas(e) -> bool:
    refs = [r for r in (e.referencias or []) if r.get("nombre") and r.get("telefono")]
    return len(refs) >= REFERENCIAS_REQUERIDAS


def faltantes_para_alta(p: Postulacion) -> List[str]:
    """Documentos (todos los del expediente, incluidos los del vehículo) Revisados + 3 referencias contactadas."""
    e = p.expediente
    if not e:
        return ["Pedir documentos y referencias"]
    faltan = [f"Documento: {t}" for t in e.no_aprobados]
    refs = [r for r in (e.referencias or []) if r.get("nombre") and r.get("telefono")]
    if len(refs) < REFERENCIAS_REQUERIDAS:
        faltan.append(f"Referencias capturadas: {len(refs)} de {REFERENCIAS_REQUERIDAS}")
    else:
        sin_validar = [r["nombre"] for r in refs if not r.get("validada")]
        if sin_validar:
            faltan.append("Referencias por validar: " + ", ".join(sin_validar))
    return faltan


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


def validar_referencias(referencias: List[dict], telefono_candidato: str = "") -> List[dict]:
    """Nombre completo, teléfono de 10 dígitos distinto (y no el del candidato) y relación del catálogo. ValueError si no."""
    import re

    if len(referencias) != REFERENCIAS_REQUERIDAS:
        raise ValueError(f"Necesitamos exactamente {REFERENCIAS_REQUERIDAS} referencias.")
    limpias, telefonos = [], set()
    for i, r in enumerate(referencias, start=1):
        tel = re.sub(r"\D", "", str(r.get("telefono") or ""))[-10:]
        nombre = str(r.get("nombre") or "").strip()
        if not nombre or len(tel) != 10:
            raise ValueError(f"Referencia {i}: escribe el nombre completo y un teléfono de 10 dígitos.")
        if r.get("parentesco") not in PARENTESCOS:
            raise ValueError(f"Referencia {i}: elige la relación.")
        if tel in telefonos or (telefono_candidato and tel == telefono_candidato):
            raise ValueError(f"Referencia {i}: cada referencia debe tener un teléfono distinto (y no el del candidato).")
        telefonos.add(tel)
        limpias.append({"nombre": nombre[:150], "telefono": tel, "parentesco": r["parentesco"]})
    return limpias


def validar_referencia(e, indice: int, validada: bool, nota_rh: str, usuario: str) -> dict:
    """VALIDAR es una decisión aparte de la llamada: solo se valida una referencia ya contactada."""
    refs = [dict(r) for r in (e.referencias or [])]
    r = refs[indice]
    if validada and not r.get("contactada"):
        raise ValueError("Primero registra una llamada en la que se haya contactado a la referencia.")
    r.update({"validada": validada, "validada_por": usuario if validada else "", "validada_en": _ahora().isoformat() if validada else "",
              "validacion_nota": nota_rh[:500]})
    e.referencias = refs
    return r


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


def registrar_alta(db: Session, p: Postulacion, u, prueba: bool) -> Tuple[object, object]:
    """«Dar de alta»: solo en Onboarding con documentos y referencias listos (Modo Prueba lo omite). Crea el
    Colaborador con la función de siempre y CIERRA la postulación como `contratado` (sale del Kanban activo)."""
    from ..routers.contratacion import _crear_colaborador

    e = p.expediente
    if e is None:
        e = abrir_expediente(db, p, u.nombre)
    if e.estado == "alta":
        raise ValueError(f"Ya se dio de alta (por {e.alta_autorizada_por}).")
    if not prueba:
        if p.etapa != ONBOARDING:
            raise ValueError("«Dar de alta» se habilita en Onboarding.")
        faltan = faltantes_para_alta(p)
        if faltan:
            raise ValueError("Aún no se puede dar de alta: " + "; ".join(faltan))
    v = p.vacante
    e.puesto = e.puesto or (v.titulo if v else "")
    e.sueldo = e.sueldo or (v.sueldo if v else "")
    e.ubicacion = e.ubicacion or (v.ubicacion if v else "")
    e.tipo_contratacion = e.tipo_contratacion or "Tiempo indeterminado"
    e.fecha_ingreso = e.fecha_ingreso or _ahora()
    e.estado, e.alta_autorizada_por, e.alta_fecha = "alta", u.nombre, _ahora()
    colaborador = _crear_colaborador(db, e, u)
    registrar(db, u.nombre, "alta_autorizada", "expediente", str(e.id), {"postulacion": p.codigo, "flujo": "operativo"})
    if p.etapa != ONBOARDING:
        mover(db, p, ONBOARDING, u.nombre, "Alta (Modo Prueba)")
    nota(p, "alta", f"Alta realizada ({colaborador.codigo if colaborador else ''}); proceso cerrado", u.nombre)
    p.estado = "cumple"
    p.resultado_apto = True
    p.cerrar("contratado")
    return e, colaborador


# ------------------------------------------------------------ subestado de la tarjeta y movimiento manual


def subestado(p: Postulacion) -> dict:
    """Lo que muestra la tarjeta del Kanban: {texto, tono, filtro, filtros, resultados}. `resultados` = Perfil /
    Vehículo / Entrevista (lo que ya se decidió); `filtros` = claves de los filtros de su columna."""
    base = _subestado(p)
    base["resultados"] = resultados_tarjeta(p)
    filtros = [base["filtro"]] if base.get("filtro") else []
    if p.etapa == ENTREVISTA:
        from sqlalchemy.orm import object_session

        apta = entrevista_apta(entrevista_actual(p))
        if apta is True:
            filtros.append(FILTRO_APTO)
        elif apta is False:
            filtros.append(FILTRO_NO_APTO)
        db = object_session(p)
        pendientes = evaluaciones_pendientes(evaluaciones_vivas(db, p)) if db is not None else []
        if pendientes:
            filtros.append(FILTRO_EVAL_PENDIENTES)
        base["evaluacionesPendientes"] = len(pendientes)
    base["filtros"] = filtros
    return base


def _subestado(p: Postulacion) -> dict:
    if p.etapa == PREFILTRO:
        texto = estado_prefiltro(p)
        clave = next(k for k, v in FILTROS_PREFILTRO.items() if v == texto)
        return {"texto": texto, "tono": {"Sin iniciar": "neutral", "En curso": "warn"}.get(texto, "brand"), "filtro": clave}
    if p.etapa == VEHICULO:
        from ..models import ESTADOS_VEHICULO

        r = p.revision_vehiculo
        return {"texto": ESTADOS_VEHICULO.get(r.estado, r.estado) if r else "Liga sin enviar",
                "tono": {"por_revisar": "warn", "correccion": "warn", "aprobado": "good", "excepcion": "good"}.get(r.estado if r else "", "neutral")}
    if p.etapa == ENTREVISTA:
        eh = entrevista_actual(p)
        texto, tono = estado_entrevista(eh)
        return {"texto": texto, "tono": tono, "filtro": clave_entrevista(eh)}
    e = p.expediente
    if p.etapa == CONTRATACION:
        if not condiciones_completas(e):
            return {"texto": "Condiciones pendientes", "tono": "warn"}
        if e.contrato_operativo == CONTRATO_GENERADO:
            return {"texto": "Contrato generado", "tono": "good"}
        if e.contrato_operativo == CONTRATO_DESPUES:
            return {"texto": "Contrato después de Onboarding", "tono": "brand"}
        return {"texto": "Falta decidir el contrato", "tono": "warn"}
    if p.etapa == ONBOARDING:
        if e and e.estado == "alta":
            return {"texto": "Alta realizada", "tono": "good"}
        faltan = faltantes_para_alta(p)
        if not faltan:
            return {"texto": "Listo para dar de alta", "tono": "good"}
        docs = [d for d in (e.obligatorios if e else [])]
        listos = sum(1 for d in docs if d.aprobado)
        refs = sum(1 for r in ((e.referencias if e else None) or []) if r.get("validada"))
        return {"texto": f"Docs {listos}/{len(docs)} · Refs {refs}/{REFERENCIAS_REQUERIDAS}", "tono": "warn"}
    return {"texto": "", "tono": "neutral"}


def validar_movimiento(db: Session, p: Postulacion, destino: str, prueba: bool) -> None:
    """Candados del Kanban operativo para mover a mano. Hacia atrás siempre se puede; hacia adelante no se brinca
    lo que exige una decisión humana registrada. Modo Prueba los omite."""
    from . import vehiculo as vehiculo_srv

    if destino not in ETAPAS_OPERATIVO:
        raise ValueError(f"Etapa inválida. Usa una de: {', '.join(ETAPAS_OPERATIVO)}")
    if prueba or _indice(destino) <= _indice(p.etapa):
        return
    orden = _indice(destino)
    if orden > _indice(VEHICULO):
        citable, motivo = vehiculo_srv.puede_citar(p)
        if not citable:
            raise ValueError(motivo)
    if orden > _indice(ENTREVISTA):
        faltan = requisitos_contratacion(db, p)
        if faltan:
            raise ValueError("Antes de avanzar a Contratación: " + "; ".join(faltan) + ".")
    if destino == ONBOARDING and requisitos_onboarding(p):
        raise ValueError("Antes de enviar a Onboarding: " + "; ".join(requisitos_onboarding(p)) + ".")
