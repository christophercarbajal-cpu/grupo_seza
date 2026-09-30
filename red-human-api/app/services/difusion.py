"""Difusión manual en Facebook (demo Grupo SEZA, 2026-09-29).

Por vacante se entregan TRES piezas listas para que RH las pegue a mano en Facebook: el copy, los datos
de la imagen (la dibuja el navegador con el color de la empresa y se descarga como PNG) y la liga única
de postulación. NO hay publicación automática: nada de aquí llama a la API de Meta.

Regla no negociable (Parte 3): nunca inventar condiciones. Si RH guardó un copy propio en
`Vacante.publicaciones["facebook"]` se respeta tal cual; si no, se arma SOLO con lo capturado en la
vacante (título, empresa visible, ubicación, sueldo derivado, requisitos y prestaciones).
"""

from typing import List

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


def _requisitos(v: Vacante) -> List[str]:
    from ..routers.vacantes import requisitos_lista  # evita import circular

    return requisitos_lista(v.requisitos)


def copy_base(v: Vacante) -> str:
    """Copy armado solo con lo capturado (nunca inventa)."""
    empresa = nombre_empresa_candidato(v)
    lineas = [f"🚚 ¡{empresa} está contratando!" if empresa else "¡Estamos contratando!", "", f"📌 {v.titulo}"]
    if v.ubicacion:
        lineas.append(f"📍 {v.ubicacion}")
    if v.sueldo and v.sueldo != "A convenir":
        lineas.append(f"💰 {v.sueldo}")
    requisitos = _requisitos(v)
    if requisitos:
        lineas += ["", "Requisitos:"] + [f"✅ {r}" for r in requisitos]
    if v.beneficios:
        lineas += ["", "Te ofrecemos:"] + [f"⭐ {b}" for b in v.beneficios]
    return "\n".join(lineas).strip()


def pieza(v: Vacante) -> dict:
    """Copy + datos de la imagen + liga única de la vacante."""
    bloque = (v.publicaciones or {}).get(PLATAFORMA) or {}
    url = liga(v)
    copy = (bloque.get("copy") or "").strip() or copy_base(v)
    destacados = [d for d in (bloque.get("destacados") or []) if str(d).strip()] or _requisitos(v)[:3]
    color = (v.cliente.color if v.cliente else "") or COLOR_DEFAULT
    return {
        "vacante": v.codigo,
        "publicada": v.estado == "Publicada",
        "liga": url,
        "copy": copy,
        "copyConLiga": f"{copy}\n\n👉 Postúlate aquí: {url}",
        "copyPropio": bool((bloque.get("copy") or "").strip()),
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

