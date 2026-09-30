"""Revisión de vehículo (demo Grupo SEZA, 2026-09-29).

Tras el prefiltro, el candidato recibe una liga pública (`/vehiculo/{token}`) para subir 4 fotos de su
vehículo: frente, atrás y ambos costados. RH las ve en la ficha («Prefiltro / Revisión de vehículo») y
decide: aprobar, pedir corrección (de ciertos lados, con comentario; se le reenvía la misma liga) o
marcar excepción (con motivo). La decisión la toma SIEMPRE una persona de RH con su nombre en bitácora.

Regla: no se cita al candidato (capacitación) mientras el vehículo no esté «aprobado» o «excepcion»
(`puede_citar`). Nada se envía si no hay teléfono; que WhatsApp falle nunca bloquea el flujo.
"""

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import ESTADOS_VEHICULO, LADOS_VEHICULO, Postulacion, RevisionVehiculo, registrar
from ..serial import iso, nombre_empresa_candidato
from . import prefiltro_reglas

ESTADOS_CITABLES = ("aprobado", "excepcion")


def requiere_fotos(p: Postulacion) -> bool:
    cfg = p.vacante.prefiltro_reglas if p.vacante else None
    return prefiltro_reglas.activo(cfg) and bool((cfg or {}).get("fotos_vehiculo", True))


def puede_citar(p: Postulacion) -> tuple[bool, str]:
    """(se puede citar, motivo si no). Vacantes sin revisión de vehículo nunca se bloquean aquí."""
    if not requiere_fotos(p):
        return True, ""
    r = p.revision_vehiculo
    if r and r.estado in ESTADOS_CITABLES:
        return True, ""
    estado = ESTADOS_VEHICULO.get(r.estado, "") if r else "Sin liga de fotos enviada"
    return False, f"Antes de citar, RH debe aprobar el vehículo (o marcar excepción). Estado actual: {estado}."


def liga(r: RevisionVehiculo) -> str:
    return f"{settings.app_url}/vehiculo/{r.token}"


def _nota(r: RevisionVehiculo, evento: str, texto: str, usuario: str) -> None:
    r.historial = [*(r.historial or []), {"evento": evento, "texto": texto, "usuario": usuario,
                                         "fecha": datetime.now(timezone.utc).isoformat()}]


def obtener_o_crear(db: Session, p: Postulacion) -> RevisionVehiculo:
    r = p.revision_vehiculo
    if r is None:
        r = RevisionVehiculo(postulacion_id=p.id, token=secrets.token_urlsafe(24), estado="pendiente", fotos={})
        db.add(r)
        p.revision_vehiculo = r
        db.flush()
    return r


def lados_faltantes(r: RevisionVehiculo) -> list:
    """Lados que el candidato aún debe subir: los que no tienen foto o los que RH pidió corregir."""
    if r.estado == "correccion":
        return [l for l in (r.lados_corregir or []) if l in LADOS_VEHICULO] or list(LADOS_VEHICULO)
    return [l for l in LADOS_VEHICULO if l not in (r.fotos or {})]


def texto_liga(p: Postulacion, r: RevisionVehiculo) -> str:
    nombre = (p.nombre or "").split(" ")[0] or "hola"
    vac = p.vacante
    empresa = nombre_empresa_candidato(vac) if vac else ""
    if r.estado == "correccion":
        lados = ", ".join(LADOS_VEHICULO[l].lower() for l in lados_faltantes(r))
        return (
            f"Hola {nombre}, revisamos las fotos de tu vehículo y necesitamos que vuelvas a subir: {lados}."
            + (f"\nComentario: {r.comentario}" if r.comentario else "")
            + f"\n\nUsa la misma liga: {liga(r)}"
        )
    return (
        f"¡Gracias, {nombre}! Para continuar con tu postulación a *{vac.titulo if vac else 'la vacante'}*"
        + (f" de {empresa}" if empresa else "")
        + ", sube 4 fotos de tu vehículo: frente, atrás y ambos costados. Toma cada foto completa y con buena luz."
        + f"\n\n📷 {liga(r)}"
    )


async def enviar_liga(db: Session, p: Postulacion, actor: str) -> dict:
    """Crea (o reutiliza) la revisión y manda la liga por WhatsApp. Regresa {liga, whatsapp}."""
    from ..routers.candidatos import _enviar_whatsapp, guardar_mensaje  # import local: evita ciclo

    r = obtener_o_crear(db, p)
    texto = texto_liga(p, r)
    envio = await _enviar_whatsapp(p, texto)
    guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
    r.liga_enviada_en = datetime.now(timezone.utc)
    r.envios = (r.envios or 0) + 1
    _nota(r, "liga_enviada", "Liga de fotos enviada" + ("" if envio.get("enviado") else " (WhatsApp no salió: compártela a mano)"), actor)
    registrar(db, actor, "vehiculo_liga_enviada", "postulacion", p.codigo, {"enviado": envio.get("enviado", False)})
    return {"liga": liga(r), "whatsapp": envio}


def registrar_foto(db: Session, r: RevisionVehiculo, lado: str, archivo_id: int) -> None:
    fotos = dict(r.fotos or {})
    fotos[lado] = {"archivo_id": archivo_id, "subida_en": datetime.now(timezone.utc).isoformat()}
    r.fotos = fotos
    if r.estado == "correccion":
        r.lados_corregir = [l for l in (r.lados_corregir or []) if l != lado]
    completo = all(l in fotos for l in LADOS_VEHICULO) and not (r.estado == "correccion" and r.lados_corregir)
    if completo and r.estado in ("pendiente", "correccion"):
        r.estado = "por_revisar"
        _nota(r, "fotos_completas", "El candidato subió todas las fotos", "candidato")
        registrar(db, "candidato", "vehiculo_fotos_completas", "postulacion", r.postulacion.codigo, {})


def decidir(db: Session, p: Postulacion, accion: str, usuario: str, comentario: str = "", lados: Optional[list] = None) -> RevisionVehiculo:
    """accion ∈ aprobar | correccion | excepcion. Valida en el router; aquí solo aplica."""
    r = obtener_o_crear(db, p)
    ahora = datetime.now(timezone.utc)
    if accion == "aprobar":
        r.estado, texto = "aprobado", "Vehículo aprobado"
    elif accion == "correccion":
        r.estado = "correccion"
        r.lados_corregir = [l for l in (lados or []) if l in LADOS_VEHICULO] or list(LADOS_VEHICULO)
        texto = "Corrección solicitada: " + ", ".join(LADOS_VEHICULO[l] for l in r.lados_corregir)
    else:
        r.estado, texto = "excepcion", "Aprobado por excepción"
    r.comentario = comentario.strip()
    r.decidido_por, r.decidido_en = usuario, ahora
    _nota(r, accion, texto + (f" — {r.comentario}" if r.comentario else ""), usuario)
    registrar(db, usuario, f"vehiculo_{accion}", "postulacion", p.codigo, {"comentario": r.comentario, "lados": r.lados_corregir})
    return r


def revision_dict(p: Postulacion, url_foto) -> Optional[dict]:
    """Para la ficha de RH. `url_foto(lado)` arma la ruta autenticada de cada foto."""
    if not requiere_fotos(p):
        return None
    r = p.revision_vehiculo
    citable, motivo = puede_citar(p)
    base = {"requerida": True, "puedeCitar": citable, "motivoBloqueo": motivo}
    if r is None:
        return {**base, "estado": "sin_liga", "etiqueta": "Liga de fotos sin enviar", "liga": "", "fotos": [], "historial": []}
    return {
        **base,
        "estado": r.estado,
        "etiqueta": ESTADOS_VEHICULO.get(r.estado, r.estado),
        "liga": liga(r),
        "ligaEnviadaEn": iso(r.liga_enviada_en),
        "envios": r.envios or 0,
        "comentario": r.comentario or "",
        "decididoPor": r.decidido_por or "",
        "decididoEn": iso(r.decidido_en),
        "ladosCorregir": r.lados_corregir or [],
        "fotos": [
            {"lado": l, "nombre": n, "cargada": l in (r.fotos or {}), "subidaEn": (r.fotos or {}).get(l, {}).get("subida_en", ""),
             "url": url_foto(l) if l in (r.fotos or {}) else ""}
            for l, n in LADOS_VEHICULO.items()
        ],
        "historial": list(reversed(r.historial or [])),
    }


def resumen_prefiltro(p: Postulacion) -> Optional[dict]:
    """Resultado del prefiltro por reglas + siguiente acción visible (tarjeta y ficha). None si la vacante
    no usa prefiltro por reglas."""
    cfg = p.vacante.prefiltro_reglas if p.vacante else None
    if not prefiltro_reglas.activo(cfg):
        return None
    estado = (p.analisis or {}).get("prefiltro_reglas") or {}
    ev = estado.get("evaluacion") if p.prefiltro_completo else None
    r = p.revision_vehiculo
    respuestas = estado.get("respuestas") or {}
    if not ev:
        total = len(prefiltro_reglas.aplicables(cfg, respuestas))
        accion = f"Esperando respuestas del candidato ({len(respuestas)}/{total})"
        return {"completo": False, "resultado": "pendiente", "etiqueta": "Prefiltro en curso", "motivos": [],
                "siguienteAccion": accion, "respondidas": len(respuestas), "total": total}
    # RH puede haber aprobado a mano un «Requiere revisión»: manda el estado vigente de la postulación
    resultado = p.estado if p.estado in prefiltro_reglas.RESULTADOS else ev["resultado"]
    if resultado == "no_cumple":
        accion = "Revisar motivos y, si procede, descartar (la decisión es de RH)"
    elif resultado == "revision":
        accion = "Revisar motivos: «Aprobar prefiltro» para pedir fotos del vehículo, o descartar"
    elif not requiere_fotos(p):
        accion = "Listo para citar"
    elif r is None:
        accion = "Enviar liga de fotos del vehículo"
    else:
        accion = {
            "pendiente": "Esperando fotos del vehículo",
            "correccion": "Esperando fotos corregidas del vehículo",
            "por_revisar": "Revisar fotos del vehículo: aprobar, pedir corrección o marcar excepción",
            "aprobado": "Listo para citar a capacitación",
            "excepcion": "Listo para citar a capacitación (vehículo por excepción)",
        }.get(r.estado, "")
    return {
        "completo": True,
        "resultado": resultado,
        "etiqueta": prefiltro_reglas.RESULTADOS.get(resultado, resultado),
        "resultadoOriginal": ev["resultado"],
        "motivos": ev.get("motivos") or [],
        "siguienteAccion": accion,
        "canal": estado.get("canal", ""),
        "completadoEn": estado.get("completado_en", ""),
        "aprobadoPorRH": estado.get("aprobado_por_rh") or None,
        "respuestas": [
            {**x, "respuesta": (estado.get("textos") or {}).get(x["id"]) or x["respuesta"]}
            for x in prefiltro_reglas.respuestas_legibles(cfg, respuestas) if x["id"] in respuestas
        ],
        "vehiculoEstado": ESTADOS_VEHICULO.get(r.estado, "") if r else ("" if not requiere_fotos(p) else "Liga sin enviar"),
    }
