"""Validación básica de documentos y fotos (2026-10-01).

Aplica a TODA carga de archivo de un requisito: ligas web (expediente y vehículo), captura de RH desde la ficha y
adjuntos que llegan por Telegram/WhatsApp. El ÚNICO objetivo es identificar el TIPO de archivo con el servicio de
visión ya configurado (OpenAI, `ia.clasificar_tipo_archivo`). NO valida vigencia, coincidencia de nombre/datos,
autenticidad ni condiciones físicas del vehículo. Lo capturado como texto (referencias, NSS o CLABE tecleados) no pasa
por aquí.

Resultados → estado del requisito:
* «coincide»     → el archivo se guarda y el requisito queda «Recibido».
* «no_coincide»  → NO se guarda; `ArchivoNoValido`: «El archivo no corresponde a [requisito]. Carga el archivo solicitado.»
* «ilegible»     → NO se guarda; `ArchivoNoValido` pidiendo una imagen más clara (se puede reintentar).
* «pendiente_revision» (el servicio falló o tardó) → se guarda con estado «Pendiente de revisión» y el requisito NO
  queda completo.
Sin OPENAI_API_KEY (modo demo) no hay validación automática: queda para revisión humana como siempre.
"""

import unicodedata
from typing import Optional, Tuple

from fastapi import HTTPException

COINCIDE, NO_COINCIDE, ILEGIBLE, PENDIENTE = "coincide", "no_coincide", "ilegible", "pendiente_revision"
SIN_IA = "sin_ia"
FOTO_VEHICULO = "Fotos del vehículo"
ETIQUETA_PENDIENTE = "Pendiente de revisión"

# Mapeo requisito → qué debe contener el archivo (palabras clave del nombre del requisito, sin acentos).
_MAPEO = [
    (("fotos del vehiculo", "foto del vehiculo", "foto", "fotos"), "Fotografía de un automóvil (el vehículo)"),
    (("licencia",), "Licencia de conducir"),
    (("tarjeta de circulacion", "circulacion"), "Tarjeta de circulación vehicular"),
    (("poliza",), "Póliza de seguro vehicular"),
    (("ine", "identificacion"), "Credencial INE (identificación oficial)"),
    (("domicilio",), "Documento utilizado como comprobante de domicilio (recibo de luz, agua, teléfono, predial o estado de cuenta)"),
    (("curp",), "Constancia de CURP"),
    (("situacion fiscal", "rfc", "fiscal"), "Constancia de Situación Fiscal o documento de RFC"),
    (("seguridad social", "nss"), "Documento que muestre el Número de Seguridad Social (NSS)"),
    (("bancaria", "clabe", "cuenta"), "Documento bancario que muestre la cuenta o la CLABE (estado de cuenta, carátula o captura del banco)"),
]


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def descripcion(requisito: str) -> str:
    """Qué debe verse en el archivo para ESTE requisito (para la IA). Sin mapeo: el nombre del requisito tal cual."""
    import re

    n = _norm(requisito)
    for claves, desc in _MAPEO:
        if any(re.search(rf"\b{re.escape(c)}\b", n) for c in claves):
            return desc
    return requisito


class ArchivoNoValido(HTTPException):
    """El archivo NO se guarda: no corresponde al requisito o no se pudo leer. 422 con el mensaje para el candidato."""

    def __init__(self, resultado: str, requisito: str):
        self.resultado = resultado
        if resultado == NO_COINCIDE:
            mensaje = f"El archivo no corresponde a {requisito}. Carga el archivo solicitado."
        else:
            mensaje = (f"No pudimos identificar el archivo como {requisito}. Carga una imagen más clara (completa, enfocada y "
                       "con buena luz) e inténtalo de nuevo.")
        super().__init__(422, mensaje)


def clasificar(contenido_b64: str, extension: str, requisito: str) -> Tuple[str, str, Optional[str]]:
    """→ (resultado, observaciones, tipo_detectado). Nunca lanza: un fallo/timeout del servicio = «pendiente_revision»."""
    from . import ia

    if not ia.ia_activa():
        return SIN_IA, "Validación automática no configurada: RH revisa el archivo.", None
    try:
        r = ia.clasificar_tipo_archivo(contenido_b64, extension, descripcion(requisito))
    except Exception as e:  # noqa: BLE001 — caída, timeout o respuesta inválida del servicio de visión
        print(f"[validacion] el servicio de visión falló al revisar «{requisito}»: {e}", flush=True)
        return PENDIENTE, "El servicio de validación no respondió: RH revisa el archivo.", None
    if r.resultado not in (COINCIDE, NO_COINCIDE, ILEGIBLE):
        return PENDIENTE, "Respuesta de validación inesperada: RH revisa el archivo.", r.tipo_detectado
    return r.resultado, r.observaciones or "", r.tipo_detectado


def exigir(resultado: str, requisito: str) -> None:
    """Rechazo e ilegible cortan la carga (el archivo no se guarda y el requisito queda como estaba)."""
    if resultado in (NO_COINCIDE, ILEGIBLE):
        raise ArchivoNoValido(resultado, requisito)
