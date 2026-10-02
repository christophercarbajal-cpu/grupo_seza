"""Revisión de vehículo (demo Grupo SEZA, 2026-09-29; v2 2026-09-30).

Tras el prefiltro, el candidato recibe una liga pública (`/vehiculo/{token}`) para subir 4 fotos de su
vehículo (frente, atrás y ambos costados) y 3 documentos: licencia vigente, tarjeta de circulación y póliza de
seguro (`DOCUMENTOS_VEHICULO`). Los documentos se guardan como `Documento` del EXPEDIENTE de la postulación, así ya
están ahí en Onboarding y no se vuelven a pedir. RH ve todo en la ficha («Prefiltro / Vehículo») y decide: aprobar
(revisa también los 3 documentos), pedir corrección (de ciertas fotos o documentos, con comentario; se le reenvía
la misma liga) o marcar excepción (con motivo). La decisión es SIEMPRE de una persona de RH, con su nombre.

Regla: no se cita al candidato (capacitación) mientras el vehículo no esté «aprobado» o «excepcion»
(`puede_citar`). Nada se envía si no hay teléfono; que WhatsApp falle nunca bloquea el flujo.
"""

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import DOCUMENTOS_VEHICULO, ESTADOS_VEHICULO, LADOS_VEHICULO, Documento, Postulacion, RevisionVehiculo, registrar
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
    """La revisión del vehículo de la postulación + su expediente con los 3 documentos del vehículo."""
    from . import flujo_operativo

    r = p.revision_vehiculo
    if r is None:
        r = RevisionVehiculo(postulacion_id=p.id, token=secrets.token_urlsafe(24), estado="pendiente", fotos={})
        db.add(r)
        p.revision_vehiculo = r
        db.flush()
    flujo_operativo.expediente(db, p, "sistema", list(DOCUMENTOS_VEHICULO.values()))
    return r


def documento(p: Postulacion, clave: str) -> Optional[Documento]:
    """Documento del expediente para la clave del vehículo (licencia | tarjeta | poliza)."""
    tipo = DOCUMENTOS_VEHICULO.get(clave)
    e = p.expediente
    return next((d for d in (e.documentos if e else []) if d.tipo == tipo), None) if tipo else None


def _doc_cargado(d: Optional[Documento]) -> bool:
    """Cargado = con archivo, no rechazado y sin fallo de la validación automática (2026-10-01: «Pendiente de revisión»
    no completa el requisito hasta que RH lo revise)."""
    return bool(d and d.archivo and d.estado != "rechazado" and (d.aprobado or not (d.validacion or {}).get("fallo_sistema")))


def foto_pendiente(dato: Optional[dict]) -> bool:
    return bool(dato and dato.get("validacion") == "pendiente_revision")


def lados_faltantes(r: RevisionVehiculo) -> list:
    """Fotos que el candidato aún debe subir: las que no tiene o las que RH pidió corregir."""
    if r.estado == "correccion":
        pedidos = [l for l in (r.lados_corregir or []) if l in LADOS_VEHICULO]
        if pedidos or any(l in DOCUMENTOS_VEHICULO for l in (r.lados_corregir or [])):
            return pedidos
        return list(LADOS_VEHICULO)
    return [l for l in LADOS_VEHICULO if l not in (r.fotos or {})]


def documentos_faltantes(r: RevisionVehiculo) -> list:
    """Documentos (claves) que faltan: sin archivo, rechazados o pedidos en la corrección."""
    p = r.postulacion
    pedidos = [l for l in (r.lados_corregir or []) if l in DOCUMENTOS_VEHICULO] if r.estado == "correccion" else []
    return [c for c in DOCUMENTOS_VEHICULO if c in pedidos or not _doc_cargado(documento(p, c))]


def completo(r: RevisionVehiculo) -> bool:
    fotos = r.fotos or {}
    return (all(l in fotos and not foto_pendiente(fotos[l]) for l in LADOS_VEHICULO) and not lados_faltantes_corr(r)
            and not documentos_faltantes(r))


def lados_faltantes_corr(r: RevisionVehiculo) -> list:
    return [l for l in (r.lados_corregir or []) if l in LADOS_VEHICULO] if r.estado == "correccion" else []


# --------------------------------------------------------------------------- #
# Cada archivo del vehículo: cómo se nombra ante el candidato y cómo corregirlo (2026-10-01, rutas paralelas)
# --------------------------------------------------------------------------- #

# clave → (frase completa, nombre corto para botones, «foto» | «documento», instrucción de cómo tomarlo)
_INSTR_DOC = "Tómale una foto completa, enfocada y con buena luz (o súbelo en PDF), que se lean todos los datos."
ARCHIVOS = {
    "frente": ("la foto del frente de tu vehículo", "foto del frente", "foto",
               "Tómala de frente, con buena luz, mostrando el vehículo completo y las placas."),
    "atras": ("la foto de la parte de atrás de tu vehículo", "foto de atrás", "foto",
              "Tómala por detrás, con buena luz, mostrando el vehículo completo y las placas."),
    "izquierdo": ("la foto del costado del conductor de tu vehículo", "foto del costado del conductor", "foto",
                  "Tómala del lado del conductor, con buena luz, de extremo a extremo del vehículo."),
    "derecho": ("la foto del costado del copiloto de tu vehículo", "foto del costado del copiloto", "foto",
                "Tómala del lado del copiloto, con buena luz, de extremo a extremo del vehículo."),
    "licencia": ("tu licencia de conducir vigente", "licencia", "documento", _INSTR_DOC),
    "tarjeta": ("tu tarjeta de circulación", "tarjeta de circulación", "documento", _INSTR_DOC),
    "poliza": ("tu póliza de seguro vigente", "póliza de seguro", "documento", _INSTR_DOC),
}
ORDEN_ARCHIVOS = [*LADOS_VEHICULO, *DOCUMENTOS_VEHICULO]


def es_foto(clave: str) -> bool:
    return clave in LADOS_VEHICULO


def instruccion(clave: str) -> str:
    return ARCHIVOS[clave][3] if clave in ARCHIVOS else ""


def boton_corregir(claves: list) -> str:
    """Un archivo → «Corregir foto del frente»; varios → «Corregir archivos»."""
    return f"Corregir {ARCHIVOS[claves[0]][1]}" if len(claves) == 1 and claves[0] in ARCHIVOS else "Corregir archivos"


def mensaje_reemplazo(clave: str) -> str:
    """Lo que ve/recibe el candidato al reemplazar con éxito un archivo pedido en la corrección."""
    return "Recibimos tu nueva foto. Está pendiente de revisión." if es_foto(clave) else "Recibimos tu nuevo documento. Está pendiente de revisión."


def canal_chat(p: Postulacion) -> bool:
    """La postulación nació en el chat (Telegram/WhatsApp): fotos, documentos y correcciones se piden y se reciben
    AHÍ. Si nació en la web, todo se pide por la liga web (Telegram, si lo conectó, solo avisa)."""
    return (p.origen or "") == "whatsapp"


def pendientes(r: RevisionVehiculo) -> list:
    """Claves (fotos y documentos) que el candidato debe mandar todavía, en orden."""
    if r.estado not in ("pendiente", "correccion"):
        return []
    faltan = set(lados_faltantes(r)) | set(documentos_faltantes(r))
    return [c for c in ORDEN_ARCHIVOS if c in faltan]


def motivos_correccion(r: RevisionVehiculo) -> dict:
    """{clave: motivo} de TODO lo pedido en la ÚLTIMA corrección de RH (queda en el historial; nunca se reescribe). Lo que
    sigue pendiente lo dice `pendientes(r)`; lo ya reemplazado se queda aquí para mostrarlo como recibido."""
    if r.estado != "correccion":
        return {}
    ultima = next((h for h in reversed(r.historial or []) if h.get("evento") == "correccion"), None) or {}
    motivos = dict(ultima.get("motivos") or {})
    if motivos:
        return {c: motivos[c] for c in ORDEN_ARCHIVOS if c in motivos}
    return {c: r.comentario or "" for c in (r.lados_corregir or [])}  # correcciones previas a 2026-10-01


def _motivo_frase(motivo: str) -> str:
    """«No se distingue.» → «no se distingue» (para «…porque no se distingue»)."""
    m = (motivo or "").strip().rstrip(".").strip()
    if m.lower().startswith("porque "):
        m = m[7:]
    if m[:1].isupper() and not m[:2].isupper():
        m = m[:1].lower() + m[1:]
    return m


def texto_correccion(p: Postulacion, r: RevisionVehiculo) -> str:
    """Mensaje claro de la corrección: QUÉ reemplazar, POR QUÉ (motivo de RH por archivo) y CÓMO hacerlo."""
    from ..routers.candidatos import nombre_ficha  # import local: evita ciclo

    nombre = nombre_ficha(p)
    motivos = motivos_correccion(r)
    faltan = pendientes(r)
    claves = [c for c in ORDEN_ARCHIVOS if c in motivos and c in faltan] or [c for c in ORDEN_ARCHIVOS if c in motivos]
    recibidos_resto = all(c in claves or c in (r.fotos or {}) if es_foto(c) else c in claves or _doc_cargado(documento(p, c))
                          for c in ORDEN_ARCHIVOS)
    if len(claves) == 1:
        c = claves[0]
        frase, _corto, tipo, instr = ARCHIVOS[c]
        motivo = _motivo_frase(motivos[c])
        texto = (f"Hola, {nombre}. Necesitamos que reemplaces {frase}" + (f" porque {motivo}" if motivo else "") + f". {instr}")
        if recibidos_resto:
            texto += f" Las demás fotos y documentos están recibidos; solo necesitamos que reemplaces {'esta foto' if tipo == 'foto' else 'este documento'}."
    else:
        lineas = []
        for c in claves:
            frase, _corto, _tipo, instr = ARCHIVOS[c]
            motivo = _motivo_frase(motivos[c])
            lineas.append(f"• {frase[:1].upper() + frase[1:]}" + (f": {motivo}." if motivo else ".") + f" {instr}")
        texto = f"Hola, {nombre}. Necesitamos que reemplaces estos archivos:\n\n" + "\n".join(lineas)
        if recibidos_resto:
            texto += "\n\nLas demás fotos y documentos están recibidos; solo necesitamos que reemplaces estos archivos."
    if canal_chat(p):
        texto += "\n\nEnvíamel" + ("a" if len(claves) == 1 and es_foto(claves[0]) else "o" if len(claves) == 1 else "os") + " por aquí, uno por mensaje."
    return texto


def texto_pedir_archivo(p: Postulacion, clave: str, prefijo: str = "") -> str:
    """Ruta de chat: pide UN archivo (el siguiente pendiente) con su instrucción."""
    frase, _c, tipo, instr = ARCHIVOS[clave]
    motivo = motivos_correccion(p.revision_vehiculo).get(clave) if p.revision_vehiculo else ""
    texto = f"{prefijo}Envíame por aquí {frase}" + (f" ({_motivo_frase(motivo)})" if motivo else "") + f". {instr}"
    if tipo == "documento":
        texto += " Puede ser foto o PDF."
    return texto


def clave_por_texto(texto: str) -> str:
    """Qué archivo menciona el pie de foto («la de atrás», «mi licencia»…). "" si no menciona ninguno."""
    import re
    import unicodedata

    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    pistas = [("frente", ("frente", "frontal", "delantera")), ("atras", ("atras", "trasera", "detras")),
              ("izquierdo", ("izquierd", "conductor", "piloto")), ("derecho", ("derech", "copiloto")),
              ("licencia", ("licencia",)), ("tarjeta", ("tarjeta", "circulacion")), ("poliza", ("poliza", "seguro"))]
    for clave, palabras in pistas:
        if any(re.search(rf"\b{p}", t) for p in palabras) and not (clave == "izquierdo" and "copiloto" in t):
            return clave
    return ""


def texto_liga(p: Postulacion, r: RevisionVehiculo) -> str:
    """Lo que se le manda al candidato para pedir lo del vehículo. Ruta de CHAT: se pide por el chat, un archivo por
    mensaje (nunca la liga web). Ruta WEB: la liga `/vehiculo/{token}` (si conectó Telegram, solo le avisa)."""
    nombre = (p.nombre or "").split(" ")[0] or "hola"
    vac = p.vacante
    empresa = nombre_empresa_candidato(vac) if vac else ""
    if r.estado == "correccion":
        texto = texto_correccion(p, r)
        return texto if canal_chat(p) else texto + f"\n\nCorrígelo aquí: {liga(r)}?corregir=1"
    if canal_chat(p):
        faltan = pendientes(r)
        if not faltan:
            return f"Gracias, {nombre}. Ya tengo las fotos y los documentos de tu vehículo; RH los revisa y te avisa por aquí."
        enviados = len(ORDEN_ARCHIVOS) - len(faltan)
        intro = (f"¡Gracias, {nombre}! Para continuar con tu postulación a *{vac.titulo if vac else 'la vacante'}*"
                 + (f" de {empresa}" if empresa else "")
                 + ", necesito 4 fotos de tu vehículo (frente, atrás y ambos costados) y una foto o PDF de tu licencia vigente, "
                 "tarjeta de circulación y póliza de seguro. Mándamelos por aquí, uno por mensaje.\n\n") if not enviados else ""
        return texto_pedir_archivo(p, faltan[0], intro)
    return (
        f"¡Gracias, {nombre}! Para continuar con tu postulación a *{vac.titulo if vac else 'la vacante'}*"
        + (f" de {empresa}" if empresa else "")
        + ", sube 4 fotos de tu vehículo (frente, atrás y ambos costados) y una foto o PDF de tu licencia vigente, "
        "tarjeta de circulación y póliza de seguro. Toma cada foto completa y con buena luz."
        + f"\n\n📷 {liga(r)}"
    )


async def enviar_correccion(db: Session, p: Postulacion, actor: str) -> dict:
    """Corrección pedida por RH → mensaje claro (qué, por qué, cómo) con UN botón: «Corregir foto del frente» si es un solo
    archivo, «Corregir archivos» si son varios. Ruta de chat: el botón pide el archivo ahí mismo; ruta web: abre la liga
    directo en los archivos pendientes. El correo sale aparte con el mismo texto."""
    from ..routers.candidatos import guardar_mensaje  # import local: evita ciclo
    from . import entregas
    from .whatsapp import enviar_con_boton

    r = obtener_o_crear(db, p)
    claves = [c for c in ORDEN_ARCHIVOS if c in motivos_correccion(r) and c in pendientes(r)] or [c for c in ORDEN_ARCHIVOS if c in motivos_correccion(r)]
    texto = texto_correccion(p, r)
    boton = boton_corregir(claves)
    url = f"{liga(r)}?corregir=1"
    envio = {"enviado": False, "proveedor": "demo"}
    if p.telefono:
        try:
            if canal_chat(p):
                envio = await enviar_con_boton(p.telefono, texto, boton, callback=f"CORR-{claves[0] if len(claves) == 1 else 'todos'}")
            else:
                envio = await enviar_con_boton(p.telefono, texto, boton, url=url)
        except Exception as e:  # noqa: BLE001 — la mensajería nunca bloquea la decisión de RH
            envio = {"enviado": False, "proveedor": "error", "detalle": str(e)}
    guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
    correo = await entregas.correo_candidato(p, "Corrección de fotos o documentos de tu vehículo", texto, cta=(boton, url))
    r.liga_enviada_en = datetime.now(timezone.utc)
    r.envios = (r.envios or 0) + 1
    _nota(r, "correccion_enviada", f"Corrección enviada al candidato ({boton})" + ("" if envio.get("enviado") else " — el mensaje no salió"), actor)
    registrar(db, actor, "vehiculo_correccion_enviada", "postulacion", p.codigo,
              {"archivos": claves, "enviado": envio.get("enviado", False), "correo": correo.get("enviado", False), "canal": "chat" if canal_chat(p) else "web"})
    return {"liga": url, "whatsapp": envio, "correo": correo, "texto": texto, "boton": boton,
            "envios": [entregas.fila("candidato", "mensaje", envio if p.telefono else {**envio, "pendiente": True}, url),
                       entregas.fila("candidato", "correo", correo, url)]}


def guardar_foto(db: Session, p: Postulacion, r: RevisionVehiculo, lado: str, val, quien: str, subido_por: str) -> str:
    """Valida (¿es la foto de un automóvil?) y guarda una foto del vehículo — misma lógica para la liga web, la captura de
    RH y la foto que llega por el chat. No es un automóvil / ilegible → `ArchivoNoValido` (no se guarda); el servicio
    falla → se guarda «Pendiente de revisión». Modo Prueba omite la IA. Regresa el resultado de la validación."""
    from ..models import Archivo
    from . import archivos as fs
    from . import validacion_archivos as va
    from .configuracion import modo_prueba_activo

    if modo_prueba_activo(db):
        resultado = va.COINCIDE
    else:
        resultado, _obs, detectado = va.clasificar(val.b64, val.extension, va.FOTO_VEHICULO)
        if resultado in (va.NO_COINCIDE, va.ILEGIBLE):
            registrar(db, quien, "vehiculo_foto_no_valida", "postulacion", p.codigo, {"lado": lado, "resultado": resultado, "tipo_detectado": detectado})
            db.commit()
            va.exigir(resultado, f"la foto del vehículo ({LADOS_VEHICULO[lado].lower()})")
    marca = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ruta = fs.guardar(val, f"vehiculo/{p.codigo}", f"{lado}-{marca}")
    a = Archivo(candidato_id=p.candidato_id, tipo=f"vehiculo_{lado}", nombre=val.nombre, ruta=ruta, mime=val.mime,
                tamano=val.tamano, subido_por=subido_por)
    db.add(a)
    db.flush()
    registrar_foto(db, r, lado, a.id, resultado)
    return resultado


async def enviar_liga(db: Session, p: Postulacion, actor: str) -> dict:
    """Crea (o reutiliza) la revisión y manda la liga por WhatsApp. Regresa {liga, whatsapp}."""
    from ..routers.candidatos import _enviar_whatsapp, guardar_mensaje  # import local: evita ciclo

    from . import entregas

    r = obtener_o_crear(db, p)
    if r.estado == "correccion" and motivos_correccion(r):  # reenviar una corrección = el mismo mensaje con su botón
        return await enviar_correccion(db, p, actor)
    texto = texto_liga(p, r)
    envio = await _enviar_whatsapp(p, texto)
    guardar_mensaje(db, p, "assistant", texto, "whatsapp", envio)
    # el correo sale aparte (nunca depende de WhatsApp/Telegram)
    correo = await entregas.correo_candidato(p, "Fotos y documentos de tu vehículo", texto.split("\n\n")[0].replace("*", ""), cta=("Subir fotos y documentos", liga(r)))
    r.liga_enviada_en = datetime.now(timezone.utc)
    r.envios = (r.envios or 0) + 1
    _nota(r, "liga_enviada", "Liga del vehículo enviada" + ("" if envio.get("enviado") else " (el mensaje no salió: compártela a mano)"), actor)
    registrar(db, actor, "vehiculo_liga_enviada", "postulacion", p.codigo, {"enviado": envio.get("enviado", False), "correo": correo.get("enviado", False)})
    return {"liga": liga(r), "whatsapp": envio, "correo": correo,
            "envios": [entregas.fila("candidato", "mensaje", envio if p.telefono else {**envio, "pendiente": True}, liga(r)),
                       entregas.fila("candidato", "correo", correo, liga(r))]}


def registrar_foto(db: Session, r: RevisionVehiculo, lado: str, archivo_id: int, validacion: str = "") -> None:
    """`validacion` (2026-10-01): «coincide», «sin_ia» o «pendiente_revision» (el servicio falló: la foto se guarda pero
    no completa el requisito hasta que RH la revise)."""
    fotos = dict(r.fotos or {})
    fotos[lado] = {"archivo_id": archivo_id, "subida_en": datetime.now(timezone.utc).isoformat(), "validacion": validacion}
    r.fotos = fotos
    if r.estado == "correccion":
        r.lados_corregir = [l for l in (r.lados_corregir or []) if l != lado]
    revisar_completo(db, r)


def registrar_documento_subido(db: Session, r: RevisionVehiculo, clave: str) -> None:
    if r.estado == "correccion":
        r.lados_corregir = [l for l in (r.lados_corregir or []) if l != clave]
    revisar_completo(db, r)


def revisar_completo(db: Session, r: RevisionVehiculo) -> None:
    """Con las 4 fotos y los 3 documentos cargados (y nada pendiente de corregir) pasa a «por revisar»."""
    if r.estado in ("pendiente", "correccion") and completo(r):
        r.estado = "por_revisar"
        _nota(r, "fotos_completas", "El candidato subió las 4 fotos y los 3 documentos", "candidato")
        registrar(db, "candidato", "vehiculo_fotos_completas", "postulacion", r.postulacion.codigo, {})


def decidir(db: Session, p: Postulacion, accion: str, usuario: str, comentario: str = "", lados: Optional[list] = None,
            motivos: Optional[dict] = None) -> RevisionVehiculo:
    """accion ∈ aprobar | correccion | excepcion. Valida en el router; aquí solo aplica. En la corrección, `motivos`
    ({clave: motivo}, 2026-10-01) es el motivo de RH POR ARCHIVO; si no viene, cada archivo lleva el comentario."""
    r = obtener_o_crear(db, p)
    ahora = datetime.now(timezone.utc)
    motivos = {k: (v or "").strip()[:500] for k, v in (motivos or {}).items() if (v or "").strip()}
    if accion == "correccion" and motivos:
        lados = [c for c in ORDEN_ARCHIVOS if c in motivos]
        if not comentario.strip():
            comentario = "; ".join(f"{ARCHIVOS[c][1][:1].upper() + ARCHIVOS[c][1][1:]}: {motivos[c]}" for c in lados)
    if accion == "aprobar":
        r.estado, texto = "aprobado", "Vehículo aprobado (fotos, licencia, tarjeta y póliza revisadas)"
        r.fotos = {k: {**v, "validacion": "revisada_rh"} for k, v in (r.fotos or {}).items()}  # RH revisó también las pendientes
        for c in DOCUMENTOS_VEHICULO:  # RH revisó los 3 documentos en el mismo panel
            d = documento(p, c)
            if d and d.archivo and not d.aprobado:
                d.estado, d.revisado_por = "recibido", usuario
    elif accion == "correccion":
        r.estado = "correccion"
        validos = {**LADOS_VEHICULO, **DOCUMENTOS_VEHICULO}
        r.lados_corregir = [l for l in (lados or []) if l in validos] or list(LADOS_VEHICULO)
        motivos = {c: motivos.get(c) or comentario.strip()[:500] for c in r.lados_corregir}
        for c in r.lados_corregir:
            d = documento(p, c) if c in DOCUMENTOS_VEHICULO else None
            if d:  # el candidato lo ve como «Requiere corrección» con SU motivo
                d.estado, d.revisado_por, d.notas_ia = "rechazado", usuario, motivos[c][:1000]
        texto = "Corrección solicitada: " + ", ".join(validos[l] for l in r.lados_corregir)
    else:
        r.estado, texto = "excepcion", "Aprobado por excepción"
    r.comentario = comentario.strip()
    r.decidido_por, r.decidido_en = usuario, ahora
    _nota(r, accion, texto + (f" — {r.comentario}" if r.comentario else ""), usuario)
    if accion == "correccion":  # el motivo por archivo vive en la entrada del historial (solo se agrega)
        r.historial = [*r.historial[:-1], {**r.historial[-1], "motivos": motivos}]
    registrar(db, usuario, f"vehiculo_{accion}", "postulacion", p.codigo, {"comentario": r.comentario, "lados": r.lados_corregir})
    return r


def documentos_dict(p: Postulacion, r: Optional[RevisionVehiculo]) -> list:
    from .flujo_operativo import estado_documento

    salida = []
    for c, tipo in DOCUMENTOS_VEHICULO.items():
        d = documento(p, c)
        salida.append({"clave": c, "tipo": tipo, "cargado": bool(d and d.archivo), "estadoSimple": estado_documento(d) if d else "Pendiente",
                       "notas": (d.notas_ia or "") if d else "", "revisadoPor": (d.revisado_por or "") if d else "",
                       "pendiente": bool(r) and c in documentos_faltantes(r)})
    return salida


def revision_dict(p: Postulacion, url_foto) -> Optional[dict]:
    """Para la ficha de RH. `url_foto(lado)` arma la ruta autenticada de cada foto."""
    if not requiere_fotos(p):
        return None
    r = p.revision_vehiculo
    citable, motivo = puede_citar(p)
    base = {"requerida": True, "puedeCitar": citable, "motivoBloqueo": motivo}
    if r is None:
        return {**base, "estado": "sin_liga", "etiqueta": "Liga del vehículo sin enviar", "liga": "", "fotos": [], "documentos": documentos_dict(p, None),
                "motivosCorreccion": {}, "canal": "chat" if canal_chat(p) else "web",
                "expedienteId": p.expediente.id if p.expediente else None, "historial": []}
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
        "motivosCorreccion": motivos_correccion(r),
        "canal": "chat" if canal_chat(p) else "web",
        "fotos": [
            {"lado": l, "nombre": n, "cargada": l in (r.fotos or {}), "subidaEn": (r.fotos or {}).get(l, {}).get("subida_en", ""),
             "url": url_foto(l) if l in (r.fotos or {}) else "",
             "pendienteRevision": foto_pendiente((r.fotos or {}).get(l))}  # 2026-10-01: la validación automática falló
            for l, n in LADOS_VEHICULO.items()
        ],
        "documentos": documentos_dict(p, r),
        "expedienteId": p.expediente.id if p.expediente else None,
        "completo": completo(r),
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
        sin_iniciar = not respuestas
        accion = "Esperando que el candidato empiece el prefiltro" if sin_iniciar else f"Esperando respuestas del candidato ({len(respuestas)}/{total})"
        return {"completo": False, "resultado": "pendiente", "etiqueta": "Sin resultado", "motivos": [],
                "estadoPrefiltro": "Sin iniciar" if sin_iniciar else "En curso",
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
        accion = "Enviar liga del vehículo (fotos y documentos)"
    else:
        accion = {
            "pendiente": "Esperando fotos y documentos del vehículo",
            "correccion": "Esperando la corrección del candidato",
            "por_revisar": "Revisar fotos y documentos: aprobar, pedir corrección o marcar excepción",
            "aprobado": "Listo para citar a la entrevista",
            "excepcion": "Listo para citar a la entrevista (vehículo por excepción)",
        }.get(r.estado, "")
    return {
        "completo": True,
        "estadoPrefiltro": "Completado",
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
