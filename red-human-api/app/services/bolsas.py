"""Bolsas de empleo externas (2026-09-26) — ver docs/arquitectura_bolsas_empleo.md.

Aquí vive la traducción de una `Vacante` a los formatos de cada destino, para que ningún portal tenga
reglas de negocio propias. Regla no negociable (Parte 3): NUNCA inventar condiciones — lo que RH no
capturó se omite (sueldo sin montos o sin periodicidad → sin `baseSalary`).

Destinos: Google Empleos (`JobPosting` de Schema.org, `jobposting`) y los feeds XML de Jooble y
Talent.com (`datos_publicos` + `vacantes_para`, los arma routers/feeds.py).
"""

from datetime import datetime, timezone
from html import escape
from typing import List, Optional

from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import Vacante, texto_sueldo
from ..serial import nombre_empresa_candidato

GOOGLE_EMPLEOS = "Google Empleos"
JOOBLE = "Jooble"
TALENT = "Talent.com"

# periodicidad capturada → (unitText de Schema.org, factor). Quincenal = medio mes: en México una
# quincena es exactamente la mitad del mes, así que ×2 a MONTH es aritmética, no una estimación.
UNIDAD_SALARIO = {
    "mensual": ("MONTH", 1), "quincenal": ("MONTH", 2), "semanal": ("WEEK", 1), "anual": ("YEAR", 1),
    "dia_semanal": ("DAY", 1), "dia_quincenal": ("DAY", 1),  # pago por día: el monto ya es diario
}


def publicable_en(v: Vacante, plataforma: str) -> bool:
    """Una vacante sale a un destino externo SOLO si está Publicada, su Cuenta está activa y RH marcó
    ese destino en `Vacante.plataformas`."""
    return (
        v.estado == "Publicada"
        and plataforma in (v.plataformas or [])
        and (v.cuenta is None or v.cuenta.estado == "Activa")
    )


def _lista_html(titulo: str, elementos: List[str]) -> str:
    items = [e.strip() for e in elementos if e and e.strip()]
    if not items:
        return ""
    return f"<p><strong>{escape(titulo)}</strong></p><ul>" + "".join(f"<li>{escape(e)}</li>" for e in items) + "</ul>"


def descripcion_html(v: Vacante) -> str:
    """Resumen (o la descripción si no hay resumen) + responsabilidades + requisitos, en HTML escapado."""
    from ..routers.vacantes import requisitos_lista  # import tardío: el router importa este módulo

    partes = []
    intro = (v.resumen or v.descripcion or "").strip()
    if intro:
        partes.append("".join(f"<p>{escape(p.strip())}</p>" for p in intro.split("\n") if p.strip()))
    partes.append(_lista_html("Responsabilidades", v.responsabilidades or []))
    partes.append(_lista_html("Requisitos", requisitos_lista(v.requisitos or "")))
    return "".join(p for p in partes if p) or f"<p>{escape(v.titulo)}</p>"


def _fecha(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite regresa fechas sin zona; se guardan en UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _salario(v: Vacante) -> Optional[dict]:
    unidad = UNIDAD_SALARIO.get(v.sueldo_periodicidad or "")
    if not unidad or not (v.sueldo_desde or v.sueldo_hasta):
        return None  # a convenir, sin montos o sin periodicidad: no se inventa
    unit_text, factor = unidad
    desde = v.sueldo_desde * factor if v.sueldo_desde else None
    hasta = v.sueldo_hasta * factor if v.sueldo_hasta else None
    if desde and hasta and hasta != desde:
        valor = {"@type": "QuantitativeValue", "minValue": desde, "maxValue": hasta, "unitText": unit_text}
    else:
        valor = {"@type": "QuantitativeValue", "value": desde or hasta, "unitText": unit_text}
    return {"@type": "MonetaryAmount", "currency": (v.sueldo_moneda or "MXN").upper(), "value": valor}


def jobposting(v: Vacante) -> dict:
    """`JobPosting` de Schema.org para Google Empleos. La empresa sale de la regla única
    `nombre_empresa_candidato` (Cliente visible solo con «mostrar cliente al candidato»)."""
    direccion = {"@type": "PostalAddress", "addressCountry": "MX"}
    if (v.ubicacion_municipio or "").strip():
        direccion["addressLocality"] = v.ubicacion_municipio.strip()
    elif (v.ubicacion or "").strip() and not (v.ubicacion_estado or "").strip():
        direccion["addressLocality"] = v.ubicacion.strip()  # vacante previa a la ubicación estructurada
    if (v.ubicacion_estado or "").strip():
        direccion["addressRegion"] = v.ubicacion_estado.strip()

    dato = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": v.titulo,
        "description": descripcion_html(v),
        # publicada_en existe desde Fase C; las publicadas antes caen a la fecha de creación
        "datePosted": _fecha(v.publicada_en or v.creada_en),
        "hiringOrganization": {"@type": "Organization", "name": nombre_empresa_candidato(v)},
        "jobLocation": {"@type": "Place", "address": direccion},
    }
    if v.modalidad == "Remoto":
        dato["jobLocationType"] = "TELECOMMUTE"
        dato["applicantLocationRequirements"] = {"@type": "Country", "name": "MX"}
    salario = _salario(v)
    if salario:
        dato["baseSalary"] = salario
    return dato


# ============================================================
# Feeds XML (Jooble, Talent.com)
# ============================================================


def url_publica(v: Vacante, fuente: str = "") -> str:
    """Landing pública de postulación. `fuente` va como `utm_source` para medir de qué portal llegó."""
    base = f"{settings.app_url.rstrip('/')}/aplicar/{v.slug}"
    return f"{base}?utm_source={fuente}" if fuente else base


def vacantes_para(db: Session, plataforma: str) -> List[Vacante]:
    """Vacantes que salen a `plataforma`: Publicadas, de una Cuenta activa y con esa plataforma marcada
    por RH (misma regla que `publicable_en`). `plataformas` es JSON: el filtro fino se hace en Python."""
    candidatas = (
        db.query(Vacante)
        .options(selectinload(Vacante.cuenta), selectinload(Vacante.cliente))
        .filter(Vacante.estado == "Publicada", Vacante.slug != "")
        .order_by(Vacante.id.desc())
        .all()
    )
    return [v for v in candidatas if publicable_en(v, plataforma)]


def datos_publicos(v: Vacante) -> dict:
    """Vacante normalizada para los feeds: solo lo que RH capturó (nada inventado). `sueldo` es None
    cuando no hay montos o es «a convenir»; en ese caso ningún feed lleva salario."""
    hay_sueldo = bool(v.sueldo_desde or v.sueldo_hasta) and v.sueldo_periodicidad != "a_convenir"
    return {
        "id": v.codigo,
        "titulo": v.titulo,
        "url": url_publica(v),
        "descripcion_html": descripcion_html(v),
        "empresa": nombre_empresa_candidato(v),
        "estado": (v.ubicacion_estado or "").strip(),
        "municipio": (v.ubicacion_municipio or "").strip(),
        "ubicacion": (v.ubicacion or "").strip(),  # texto derivado (o libre en vacantes previas)
        "pais": "MX",
        "modalidad": v.modalidad or "",
        "remoto": v.modalidad == "Remoto",
        "area": v.area or "",
        "sueldo": {
            "desde": v.sueldo_desde, "hasta": v.sueldo_hasta,
            "moneda": (v.sueldo_moneda or "MXN").upper(), "periodicidad": v.sueldo_periodicidad or "",
            "texto": texto_sueldo(v.sueldo_desde, v.sueldo_hasta, v.sueldo_moneda, v.sueldo_periodicidad),
        } if hay_sueldo else None,
        "publicada_en": _fecha_utc(v.publicada_en or v.creada_en),
        "actualizada_en": _fecha_utc(v.actualizada_en or v.publicada_en or v.creada_en),
    }


def _fecha_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
