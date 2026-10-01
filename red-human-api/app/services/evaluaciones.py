"""Evaluaciones y verificaciones del candidato (2026-09-28) — lógica interna, sin proveedores externos todavía.

* Consentimientos ANTES de enviar/asignar: el general de la postulación (LFPDPPP) para todo; para el estudio
  MÉDICO además uno expreso y por escrito por medio electrónico (texto exacto + aceptación + evidencia). Sin él la
  evaluación queda «En espera de consentimiento» y no se puede enviar ni cargar resultado.
* Seguimiento: Pendiente → En proceso → Resultado recibido → Revisada; Fallida/Cancelada siempre con motivo.
* Modo Integrada simulado: Asignada → Enviada → Iniciada → Completada → Resultado recibido (a mano por ahora).
* Nada de aquí escribe `Postulacion.etapa` (no hay columnas nuevas en el pipeline) ni usa IA: RH revisa y dictamina.
* 2026-09-30 — regla universal de ligas: toda liga (consentimiento, evaluador/médico/proveedor, enlace externo) EXISTE
  desde que se crea la evaluación y se muestra con «Abrir / Copiar / Enviar o reenviar»; el envío automático es aparte
  y nunca la condiciona. La liga del evaluador y la captura manual de RH alimentan la MISMA evaluación. Médico: primero
  el consentimiento; la liga del médico se habilita al aceptarlo. Estados visibles: Pendiente → Enviada → En curso →
  Resultado recibido → Revisada.
"""

import secrets
from datetime import datetime, timezone
from typing import List, Optional

from ..models import (
    DICTAMENES_ENTREVISTA,
    DICTAMENES_GENERALES,
    DICTAMENES_MEDICOS,
    NOMBRE_CAPACITACION_TIENDA,
    ESTADO_POR_PASO,
    ESTADOS_EVALUACION,
    MODOS_PRUEBA,
    PASOS_INTEGRADA,
    TIPOS_EVALUACION,
    EvaluacionCandidato,
    Postulacion,
)

ESTADOS_ABIERTOS = ("en_espera_consentimiento", "pendiente", "en_proceso", "resultado_recibido")


DICTAMENES_DESFAVORABLES = ("desfavorable", "no_apto")


def dictamenes_de(tipo: str) -> dict:
    if tipo == "entrevista_humana":
        return DICTAMENES_ENTREVISTA
    return DICTAMENES_MEDICOS if tipo == "medico" else DICTAMENES_GENERALES


def es_legado(ev: EvaluacionCandidato) -> bool:
    """«Capacitación en tienda» de la v1 (sesión con cupo): ya vive como la Entrevista de la postulación. Se conserva
    como historial pero no tiene liga, no cuenta como pendiente y no se captura (2026-10-01: su liga se confundía con
    la del médico en la ficha)."""
    return bool(ev.sesion_id) and ev.tipo == "otra" and ev.nombre == NOMBRE_CAPACITACION_TIENDA


def apto_del_evaluador(ev: EvaluacionCandidato) -> str:
    """Entrevista humana: Apto / No apto que registró el entrevistador con el resultado ("" si no hay)."""
    return str((ev.resultado_json or {}).get("apto") or "") if ev.tipo == "entrevista_humana" else ""


def archivo_opcional(contenido: bytes, nombre: str, etiqueta: str):
    """Valida el informe adjunto SIN tumbar la captura: un archivo vacío (p. ej. una captura en blanco usada como
    prueba) se ignora con un aviso — no se guarda, no se marca como falla y el texto se registra igual. Un formato
    no admitido sí regresa su error para que la persona lo corrija. → (validado | None, aviso)."""
    from fastapi import HTTPException

    from . import archivos as fs

    if not contenido or len(contenido) < fs.MIN_BYTES:
        return None, "El archivo adjunto estaba vacío y no se guardó; el resultado quedó registrado."
    try:
        return fs.validar_bytes(contenido, nombre, etiqueta), ""
    except HTTPException as ex:
        if ex.status_code == 422:
            return None, f"El archivo adjunto no se pudo leer y no se guardó ({ex.detail}); el resultado quedó registrado."
        raise


def consentimiento_ok(ev: EvaluacionCandidato, p: Optional[Postulacion]) -> bool:
    """General (postulación) para todas; el médico exige además el expreso por escrito ya aceptado."""
    if not (p and p.consentimiento):
        return False
    if ev.requiere_consentimiento_expreso:
        return bool(ev.consentimiento_aceptado_en)
    return True


def falta_consentimiento(ev: EvaluacionCandidato, p: Optional[Postulacion]) -> str:
    if not (p and p.consentimiento):
        return "Falta el consentimiento de privacidad del candidato (LFPDPPP)."
    if ev.requiere_consentimiento_expreso and not ev.consentimiento_aceptado_en:
        return "Falta el consentimiento expreso y por escrito del candidato para el estudio médico."
    return ""


def mover(ev: EvaluacionCandidato, estado: str, usuario: str, detalle: str = "") -> None:
    """Cambia el estado de seguimiento y lo deja en el historial de la evaluación."""
    if estado == ev.estado and not detalle:
        return
    ev.historial = list(ev.historial or []) + [
        {"fecha": datetime.now(timezone.utc).isoformat(), "usuario": usuario, "de": ev.estado, "a": estado, "detalle": detalle[:500]}
    ]
    ev.estado = estado


def refrescar_consentimiento(ev: EvaluacionCandidato, p: Optional[Postulacion], usuario: str = "sistema") -> bool:
    """«En espera de consentimiento» ↔ «Pendiente» según los consentimientos vigentes. Regresa si cambió."""
    ok = consentimiento_ok(ev, p)
    if ev.estado == "en_espera_consentimiento" and ok:
        mover(ev, "pendiente", usuario, "Consentimiento registrado")
        if ev.modo == "integrada" and not ev.paso_integrada:
            ev.paso_integrada = "asignada"
        return True
    if ev.estado == "pendiente" and not ok:
        mover(ev, "en_espera_consentimiento", usuario, falta_consentimiento(ev, p))
        return True
    return False


def siguiente_paso(ev: EvaluacionCandidato) -> Optional[str]:
    if ev.modo != "integrada":
        return None
    actual = ev.paso_integrada or "asignada"
    i = PASOS_INTEGRADA.index(actual) if actual in PASOS_INTEGRADA else 0
    return PASOS_INTEGRADA[i + 1] if i + 1 < len(PASOS_INTEGRADA) else None


def aplicar_paso(ev: EvaluacionCandidato, paso: str, usuario: str, origen: str = "simulado") -> None:
    """`origen`: «simulado» (RH a mano) o el nombre del proveedor cuando el paso lo reporta su API/webhook."""
    ev.paso_integrada = paso
    mover(ev, ESTADO_POR_PASO[paso], usuario, f"Modo integrada ({origen}): {paso}")


def normalizar_sugeridas(lista: List[dict], pruebas_validas: dict) -> List[dict]:
    """Sugerencias de la vacante: [{tipo, prueba_id?, nombre?}] sin duplicados; la prueba debe ser del catálogo."""
    salida, vistos = [], set()
    for x in lista or []:
        tipo = str((x or {}).get("tipo") or "").strip()
        if tipo not in TIPOS_EVALUACION:
            continue
        prueba_id = (x or {}).get("prueba_id")
        try:
            prueba_id = int(prueba_id) if prueba_id not in (None, "") else None
        except (TypeError, ValueError):
            prueba_id = None
        if prueba_id is not None and prueba_id not in pruebas_validas:
            prueba_id = None
        nombre = str((x or {}).get("nombre") or "").strip()[:200] or (pruebas_validas.get(prueba_id) if prueba_id else TIPOS_EVALUACION[tipo])
        clave = (tipo, prueba_id, nombre.lower())
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append({"tipo": tipo, "prueba_id": prueba_id, "nombre": nombre})
    return salida


def avisos_antes_onboarding(p: Postulacion, evaluaciones: List[EvaluacionCandidato]) -> List[str]:
    """Si la vacante pide «Avisar antes de Onboarding»: qué sugeridas faltan, cuáles no están revisadas y cuáles
    salieron desfavorables. Solo AVISA (RH decide); nunca bloquea."""
    v = p.vacante
    if not v or not v.avisar_evaluaciones_antes_onboarding:
        return []
    avisos = []
    vivas = [e for e in evaluaciones if e.estado != "fallida" and not es_legado(e)]
    for s in v.evaluaciones_sugeridas or []:
        hay = any(e.tipo == s.get("tipo") and (not s.get("prueba_id") or e.prueba_id == s.get("prueba_id")) for e in vivas)
        if not hay:
            avisos.append(f"Sugerida por la vacante y no asignada: {s.get('nombre') or TIPOS_EVALUACION.get(s.get('tipo'), '')}.")
    for e in vivas:
        if e.estado != "revisada":
            avisos.append(f"{e.nombre}: {ESTADOS_EVALUACION.get(e.estado, e.estado)} (sin revisar).")
        elif e.dictamen in ("desfavorable", "no_apto"):
            avisos.append(f"{e.nombre}: dictamen {dictamenes_de(e.tipo).get(e.dictamen, e.dictamen)}.")
    return avisos


def etiqueta_modo(modo: str) -> str:
    return MODOS_PRUEBA.get(modo, modo)


# ---------- 2026-09-30: estado visible, evaluador y ligas ----------


def estado_visible(ev: EvaluacionCandidato) -> str:
    """«En proceso» se muestra como Enviada (todavía no empieza) o En curso (ya empezó: paso iniciada/completada)."""
    if ev.estado == "en_proceso":
        return "En curso" if ev.paso_integrada in ("iniciada", "completada") else "Enviada"
    return ESTADOS_EVALUACION.get(ev.estado, ev.estado)


def asegurar_token(ev: EvaluacionCandidato) -> bool:
    """La liga del evaluador nace con la evaluación (registros previos la reciben al leerse). True si se creó."""
    if ev.evaluador_token:
        return False
    ev.evaluador_token = secrets.token_urlsafe(24)
    return True


def evaluador_habilitado(ev: EvaluacionCandidato, p: Optional[Postulacion]) -> bool:
    """La liga del evaluador sirve cuando hay consentimientos (médico: el expreso ya aceptado) y sigue abierta."""
    return ev.estado not in ("revisada", "fallida") and not es_legado(ev) and consentimiento_ok(ev, p)


def evaluador_de(ev: EvaluacionCandidato, db=None) -> dict:
    if ev.evaluador_tipo == "interno" and ev.evaluador_usuario_id and db is not None:
        from ..models import Usuario

        u = db.get(Usuario, ev.evaluador_usuario_id)
        if u:
            return {"tipo": "interno", "usuarioId": u.id, "nombre": u.nombre, "telefono": u.telefono or "", "correo": u.correo or ""}
    return {"tipo": ev.evaluador_tipo or "", "usuarioId": ev.evaluador_usuario_id, "nombre": ev.evaluador_nombre or "",
            "telefono": ev.evaluador_telefono or "", "correo": ev.evaluador_correo or ""}


def registrar_envio(ev: EvaluacionCandidato, liga: str, destinatario: str, canal: str, envio: dict) -> dict:
    fila = {"liga": liga, "destinatario": destinatario, "canal": canal, "enviado": bool(envio.get("enviado")),
            "detalle": str(envio.get("detalle") or "")[:300], "fecha": datetime.now(timezone.utc).isoformat()}
    ev.envios = [*(ev.envios or []), fila][-40:]
    return fila


# ---------- Psicométricas.mx (2026-09-29) ----------

def usa_psicometricas(ev: EvaluacionCandidato) -> bool:
    from . import psicometricas as psi

    return ev.modo == "integrada" and psi.es_psicometricas(ev.proveedor)


def resumen_resultado(datos) -> str:
    """Texto breve para RH a partir del JSON del proveedor (sin interpretar: lo revisa y dictamina una persona)."""
    import json as _json

    texto = _json.dumps(datos, ensure_ascii=False)
    return f"Resultado recibido de Psicométricas.mx ({len(texto)} caracteres). Revisa el informe PDF adjunto."


def sincronizar_psicometricas(db, ev: EvaluacionCandidato, por: str = "Psicométricas.mx (automático)") -> str:
    """Confirma con su API (consultaCandidato → fecha_fin) y, si ya terminó, descarga el resultado (JSON + PDF) y lo
    deja en la evaluación: Completada → Resultado recibido. Idempotente. Regresa: sin_clave | en_curso | ya_estaba |
    resultado_recibido."""
    from . import archivos as fs
    from . import psicometricas as psi

    if not ev.clave_proveedor:
        return "sin_clave"
    if ev.estado in ("resultado_recibido", "revisada", "fallida"):
        return "ya_estaba"
    filas = psi.consultar_candidato(ev.clave_proveedor)
    if not psi.terminado(filas):
        return "en_curso"
    datos = psi.resultado_json(ev.clave_proveedor)
    pdf = psi.resultado_pdf(ev.clave_proveedor)
    ev.resultado_json = datos if isinstance(datos, dict) else {"resultados": datos}
    ev.resultado_resumen = resumen_resultado(datos)
    if pdf:
        validado = fs.validar_bytes(pdf, f"psicometricas-{ev.clave_proveedor}.pdf", f"informe «{ev.nombre}»")
        ev.archivo = fs.guardar(validado, f"evaluaciones/{ev.id}", f"informe_{ev.codigo}")
        ev.nombre_archivo, ev.mime = validado.nombre, validado.mime
    ev.resultado_cargado_por, ev.resultado_cargado_en = por, datetime.now(timezone.utc)
    if ev.paso_integrada != "completada":
        aplicar_paso(ev, "completada", por, "Psicométricas.mx")
    aplicar_paso(ev, "resultado_recibido", por, "Psicométricas.mx")
    return "resultado_recibido"
