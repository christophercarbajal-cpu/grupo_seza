"""Difusión manual en Facebook (demo Grupo SEZA, 2026-09-29) y textos de publicación por canal (2026-09-30).

Textos (Plantillas y Nueva vacante): `textos_base` arma, SOLO con los datos finales capturados, el texto para chat
(WhatsApp/Telegram), bolsa/portal y Facebook (puesto, ubicación, pago, horario, requisitos; la liga se agrega al
copiar). Nunca regresa vacío: es el respaldo de la IA y lo que rellena cualquier texto vacío al guardar.

Por vacante se entregan TRES piezas listas para que RH las pegue a mano en Facebook: el copy, los datos
de la imagen (la dibuja el navegador con el color de la empresa y se descarga como PNG) y la liga única
de postulación. NO hay publicación automática: nada de aquí llama a la API de Meta.

Regla no negociable (Parte 3): nunca inventar condiciones. Si RH guardó un copy propio en
`Vacante.publicaciones["facebook"]` se respeta tal cual; si no, se arma SOLO con lo capturado en la
vacante (título, empresa visible, ubicación, sueldo derivado, requisitos y prestaciones).
"""

from typing import List, Optional

from ..config import settings
from ..models import Vacante, slugificar
from ..serial import nombre_empresa_candidato

PLATAFORMA = "facebook"
ORIGEN = "facebook"  # valor de ?origen= en la liga; /candidatos/postular lo registra como fuente
COLOR_DEFAULT = "#ee4444"  # rojo Red Human (mismo del wordmark) cuando la empresa no tiene color


def liga(v: Vacante) -> str:
    """Liga ÚNICA de la vacante para Facebook: la landing de siempre con la fuente marcada, así cada
    postulación que llegue por ahí queda atribuida a Facebook (Candidato.fuente)."""
    return f"{settings.app_url}/aplicar/{v.slug or slugificar(v.titulo)}?origen={ORIGEN}"


def _requisitos(v) -> List[str]:
    from ..routers.vacantes import requisitos_lista  # evita import circular

    return requisitos_lista(v.requisitos)


def horario_de(prefiltro_reglas: Optional[dict]) -> str:
    """Horario/jornada capturado (el prefiltro por reglas guarda las horas de la jornada). "" si no hay dato."""
    horas = (prefiltro_reglas or {}).get("jornada_horas")
    return f"Jornada de {horas} horas" if horas else ""


def datos_de(obj, empresa: str = "") -> dict:
    """Datos FINALES de una vacante o plantilla para armar sus textos."""
    sueldo = (getattr(obj, "sueldo", "") or "").strip()
    return {
        "titulo": (obj.titulo or "").strip(), "empresa": empresa, "ubicacion": (obj.ubicacion or "").strip(),
        "modalidad": (getattr(obj, "modalidad", "") or "").strip(), "sueldo": "" if sueldo == "A convenir" else sueldo,
        "horario": horario_de(getattr(obj, "prefiltro_reglas", None)), "requisitos": _requisitos(obj),
        "beneficios": [b for b in (getattr(obj, "beneficios", None) or []) if str(b).strip()],
        "resumen": (getattr(obj, "resumen", "") or getattr(obj, "descripcion", "") or "").strip(),
    }


def textos_base(d: dict) -> dict:
    """{whatsapp, bolsa, facebook} SOLO con lo capturado — nunca inventa y nunca regresa un texto vacío."""
    titulo = d.get("titulo") or "Vacante"
    empresa = d.get("empresa") or ""
    datos = [x for x in (
        f"📍 {d['ubicacion']}" if d.get("ubicacion") else "",
        f"💰 {d['sueldo']}" if d.get("sueldo") else "",
        f"🕘 {d['horario']}" if d.get("horario") else "",
        f"🏢 {d['modalidad']}" if d.get("modalidad") and d.get("modalidad") != "Presencial" else "",
    ) if x]
    requisitos = d.get("requisitos") or []
    beneficios = d.get("beneficios") or []

    whatsapp = "\n".join([f"¡Hola! {empresa + ' busca' if empresa else 'Buscamos'} *{titulo}*.", *datos,
                           *(["Requisitos: " + ", ".join(requisitos[:4]) + "."] if requisitos else []),
                           "¿Te interesa? Responde *Sí* y te contamos más. 🙂"])
    bolsa = "\n".join([f"{titulo}" + (f" — {empresa}" if empresa else ""), "",
                        *([d["resumen"], ""] if d.get("resumen") else []),
                        *([x[2:].strip() for x in datos]),
                        *(["", "Requisitos:"] + [f"- {r}" for r in requisitos] if requisitos else []),
                        *(["", "Ofrecemos:"] + [f"- {b}" for b in beneficios] if beneficios else []),
                        "", "Postúlate en línea en menos de 3 minutos."]).strip()
    facebook = "\n".join([f"🚚 ¡{empresa} está contratando!" if empresa else "¡Estamos contratando!", "", f"📌 {titulo}", *datos,
                           *(["", "Requisitos:"] + [f"✅ {r}" for r in requisitos] if requisitos else []),
                           *(["", "Te ofrecemos:"] + [f"⭐ {b}" for b in beneficios] if beneficios else [])]).strip()
    return {"whatsapp": whatsapp, "bolsa": bolsa, "facebook": facebook}


def completar_textos(obj, empresa: str = "") -> None:
    """Al guardar una vacante o plantilla, ningún texto de publicación queda vacío."""
    base = None
    for campo, canal in (("texto_whatsapp", "whatsapp"), ("texto_bolsa", "bolsa"), ("texto_facebook", "facebook")):
        if not (getattr(obj, campo, "") or "").strip():
            base = base or textos_base(datos_de(obj, empresa))
            setattr(obj, campo, base[canal])


def copy_base(v: Vacante) -> str:
    """Copy armado solo con lo capturado (nunca inventa)."""
    return textos_base(datos_de(v, nombre_empresa_candidato(v)))["facebook"]


def pieza(v: Vacante) -> dict:
    """Copy + datos de la imagen + liga única de la vacante."""
    bloque = (v.publicaciones or {}).get(PLATAFORMA) or {}
    url = liga(v)
    propio = (v.texto_facebook or "").strip() or (bloque.get("copy") or "").strip()
    copy = propio or copy_base(v)
    destacados = [d for d in (bloque.get("destacados") or []) if str(d).strip()] or _requisitos(v)[:3]
    color = (v.cliente.color if v.cliente else "") or COLOR_DEFAULT
    return {
        "vacante": v.codigo,
        "publicada": v.estado == "Publicada",
        "liga": url,
        "copy": copy,
        "copyConLiga": f"{copy}\n\n👉 Postúlate aquí: {url}",
        "copyPropio": bool(propio),
        "horario": horario_de(v.prefiltro_reglas),
        "imagen": {
            "empresa": nombre_empresa_candidato(v),
            "color": color,
            "titulo": v.titulo,
            "ubicacion": bloque.get("ubicacion") or v.ubicacion or "",
            "sueldo": v.sueldo if v.sueldo and v.sueldo != "A convenir" else "",
            "destacados": destacados[:4],
            "llamado": bloque.get("llamado") or "Postúlate hoy",
        },
    }

