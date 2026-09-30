"""Prefiltro POR REGLAS (demo Grupo SEZA, 2026-09-29).

Un cuestionario fijo (el LITERAL del documento del cliente) que se contesta igual por la web (/aplicar) y
por WhatsApp, y se evalúa SIN IA contra las reglas guardadas en la vacante (`Vacante.prefiltro_reglas`).
Cada plaza decide lo suyo: Puebla pide sedán 2018+, San José del Cabo sedán 2020+ y CDMX sedán o Kangoo
sin año mínimo — el código no conoce ninguna plaza.

Regla estricta del documento: «fuera de parámetro o posible excepción = revisión humana; documento
pendiente no es descarte». Por eso solo descarta lo que la vacante declara indispensable (jornada completa,
zona, vehículo propio, Android y —si se configuró— experiencia); tipo o año del vehículo fuera de la
vacante, taxi, circulación, licencia y póliza van a revisión.

Forma de `Vacante.prefiltro_reglas`:
    {
      "activo": true,
      "jornada_horas": 10,
      "ubicacion_texto": "Puebla",            # [ubicación] de la pregunta 2 (default: la de la vacante)
      "zona": "",                             # [zona] de la pregunta 3; vacía = la pregunta se omite
      "cobertura": [],                        # municipios atendidos; vacía = el municipio nunca descarta
      "experiencia_indispensable": false,
      "vehiculo": {"tipos_permitidos": ["Sedán de cuatro puertas"], "anio_minimo": 2018},  # null = sin mínimo
      "reglas": {"<id>": {"<valor>": "ok" | "revision" | "no_cumple"}},   # encima de REGLAS_BASE
      "fotos_vehiculo": true
    }

Resultado (lo que ve RH): «Cumple perfil» / «Requiere revisión» / «No cumple», con cada motivo y la
siguiente acción. Mapea a `Postulacion.estado` = cumple | revision | no_cumple. La IA NUNCA descarta: un
«No cumple» es una recomendación y la postulación sigue activa hasta que RH decide (LFPDPPP).
"""

import re
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional

OK, REVISION, NO_CUMPLE = "ok", "revision", "no_cumple"
EFECTOS = (OK, REVISION, NO_CUMPLE)
_GRAVEDAD = {OK: 0, REVISION: 1, NO_CUMPLE: 2}

RESULTADOS = {"cumple": "Cumple perfil", "revision": "Requiere revisión", "no_cumple": "No cumple"}

SEDAN, KANGOO, OTRO = "Sedán de cuatro puertas", "Kangoo", "Otro"
TIPOS_VEHICULO = [SEDAN, KANGOO, OTRO]
NO_SEGURO = "No estoy seguro"

# Las 12 preguntas, en orden y con el texto del documento. {horas}, {ubicacion} y {zona} salen de la vacante.
PREGUNTAS: List[dict] = [
    {"id": "municipio", "tipo": "abierta", "texto": "¿En qué municipio o alcaldía vives?"},
    {"id": "jornada", "tipo": "si_no", "texto": "Esta vacante requiere {horas} horas de jornada en {ubicacion}. ¿Puedes cubrirla completa?"},
    {"id": "zona", "tipo": "si_no", "texto": "¿Puedes realizar entregas en {zona}?"},
    {"id": "experiencia", "tipo": "si_no", "texto": "¿Has trabajado como chofer o repartidor?"},
    {"id": "vehiculo_propio", "tipo": "si_no", "texto": "¿Tienes vehículo propio para trabajar?"},
    {"id": "tipo_vehiculo", "tipo": "opcion", "texto": "¿Qué vehículo tienes?", "opciones": TIPOS_VEHICULO},
    {"id": "anio_vehiculo", "tipo": "anio", "texto": "¿De qué año es?"},
    {"id": "taxi", "tipo": "si_no", "texto": "¿Está rotulado o registrado como taxi?"},
    {"id": "circulacion", "tipo": "opcion", "texto": "¿Puede circular todos los días que requiere la operación?", "opciones": ["Sí", "No", NO_SEGURO]},
    {"id": "licencia", "tipo": "si_no", "texto": "¿Tienes licencia vigente correspondiente al vehículo?"},
    {"id": "poliza", "tipo": "si_no", "texto": "¿Tienes póliza de seguro vigente?"},
    {"id": "android", "tipo": "si_no", "texto": "¿Tienes teléfono Android para usar las aplicaciones de reparto?"},
]
IDS = [p["id"] for p in PREGUNTAS]

# Sin vehículo propio estas ya no se preguntan (y no cuentan como faltantes).
VEHICULARES = ("tipo_vehiculo", "anio_vehiculo", "taxi", "circulacion", "poliza")

# Efecto por respuesta (clave = valor normalizado: «si», «no», «no estoy seguro»). Lo que no aparece es «ok».
# Tipo y año del vehículo se evalúan contra `vehiculo` (fuera de la vacante = revisión, ver evaluar()).
REGLAS_BASE: Dict[str, Dict[str, str]] = {
    "jornada": {"no": NO_CUMPLE},  # no hay medio turno
    "zona": {"no": NO_CUMPLE},
    "vehiculo_propio": {"no": NO_CUMPLE},  # indispensable en estas vacantes
    "taxi": {"si": REVISION},
    "circulacion": {"no": REVISION, "no estoy seguro": REVISION},
    "licencia": {"no": REVISION},  # documento pendiente ≠ descarte
    "poliza": {"no": REVISION},    # documento pendiente ≠ descarte
    "android": {"no": NO_CUMPLE},
}

MOTIVOS = {  # (pregunta, valor) → motivo legible para RH
    ("jornada", "no"): "No puede cubrir la jornada completa de {horas} horas",
    ("zona", "no"): "No puede realizar entregas en {zona}",
    ("experiencia", "no"): "Sin experiencia como chofer o repartidor (indispensable en esta vacante)",
    ("vehiculo_propio", "no"): "No tiene vehículo propio",
    ("taxi", "si"): "El vehículo está rotulado o registrado como taxi",
    ("circulacion", "no"): "No puede circular todos los días de la operación",
    ("circulacion", "no estoy seguro"): "No está seguro de poder circular todos los días de la operación",
    ("licencia", "no"): "Licencia vigente pendiente",
    ("poliza", "no"): "Póliza de seguro vigente pendiente",
    ("android", "no"): "No tiene teléfono Android para las aplicaciones de reparto",
}


def configuracion(jornada_horas: Optional[int], tipos_permitidos: List[str], anio_minimo: Optional[int], *,
                  ubicacion_texto: str = "", zona: str = "", cobertura: Optional[List[str]] = None,
                  experiencia_indispensable: bool = False, reglas: Optional[dict] = None) -> dict:
    """Config lista para guardar en `Vacante.prefiltro_reglas`."""
    return {
        "activo": True,
        "jornada_horas": jornada_horas,
        "ubicacion_texto": ubicacion_texto,
        "zona": zona,
        "cobertura": list(cobertura or []),
        "experiencia_indispensable": experiencia_indispensable,
        "vehiculo": {"tipos_permitidos": list(tipos_permitidos), "anio_minimo": anio_minimo},
        "reglas": reglas or {},
        "fotos_vehiculo": True,
    }


def activo(config: Optional[dict]) -> bool:
    return bool(config and config.get("activo"))


def _texto(p: dict, config: dict) -> str:
    return (
        p["texto"]
        .replace("{horas}", str(config.get("jornada_horas") or "las"))
        .replace("{ubicacion}", (config.get("ubicacion_texto") or "la plaza").strip())
        .replace("{zona}", (config.get("zona") or "").strip())
    )


def preguntas(config: dict) -> List[dict]:
    """Las preguntas de ESTA vacante con su texto final (sin reglas: esto sí lo ve el candidato). La de
    zona se omite si la vacante no definió zona."""
    salida = []
    for p in PREGUNTAS:
        if p["id"] == "zona" and not (config.get("zona") or "").strip():
            continue
        opciones = list(p.get("opciones") or (["Sí", "No"] if p["tipo"] == "si_no" else []))
        salida.append({**p, "texto": _texto(p, config), "opciones": opciones})
    return salida


def aplicables(config: dict, respuestas: Dict[str, str]) -> List[str]:
    """Ids que hay que contestar dadas las respuestas previas (sin vehículo propio se saltan las del vehículo)."""
    ids = [p["id"] for p in preguntas(config)]
    if _clave(respuestas.get("vehiculo_propio")) == "no":
        return [i for i in ids if i not in VEHICULARES]
    return ids


# ------------------------------------------------------------ interpretación de respuestas


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def _clave(valor) -> str:
    """Clave de regla para un valor ya interpretado: «Sí» → «si», «No estoy seguro» → «no estoy seguro»."""
    return _norm(str(valor or ""))


_SI = {"si", "sip", "claro", "afirmativo", "correcto", "yes", "simon", "s"}
_NO = {"no", "nel", "negativo", "nop", "n", "tampoco", "ninguno", "ninguna"}
_DUDA = re.compile(r"\b(no se|no estoy segur[oa]|tal vez|quiza[s]?|a veces|depende|creo|no lo se)\b")


def _si_no(texto: str) -> Optional[str]:
    t = re.sub(r"[^a-z ]", " ", _norm(texto)).split()
    if not t:
        return None
    if t[0] in _SI or " ".join(t[:2]) in ("por supuesto", "si claro"):
        return "si"
    if t[0] in _NO:
        return "no"
    return None


def _opcion(pid: str, texto: str, opciones: List[str]) -> Optional[str]:
    t = _norm(texto)
    num = re.fullmatch(r"\s*(\d{1,2})[.)]?\s*", t)
    if num and 1 <= int(num.group(1)) <= len(opciones):
        return opciones[int(num.group(1)) - 1]
    if pid == "circulacion":
        if _DUDA.search(t) or t == _norm(NO_SEGURO):
            return NO_SEGURO
        sn = _si_no(texto)
        return {"si": "Sí", "no": "No"}.get(sn or "")
    if pid == "tipo_vehiculo":
        if re.search(r"\bkangoo\b", t):
            return KANGOO
        if re.search(r"\bsedan\b", t):
            return SEDAN
        # Cualquier otra descripción («un Tsuru», «pick-up») es «Otro»: no se adivina, RH lo revisa.
        return OTRO if len(t) >= 2 else None
    for o in sorted(opciones, key=len, reverse=True):  # la opción más larga primero («No estoy seguro» antes que «No»)
        if re.search(rf"\b{re.escape(_norm(o))}\b", t):
            return o
    return None


def _anio(texto: str) -> Optional[int]:
    t = _norm(texto)
    m = re.search(r"\b(19[5-9]\d|20\d{2})\b", t)
    if m:
        anio = int(m.group(1))
    else:
        m = re.fullmatch(r"\s*(?:modelo\s*)?'?(\d{2})\s*", t)
        if not m:
            return None
        corto = int(m.group(1))
        actual = datetime.now(timezone.utc).year % 100
        anio = 2000 + corto if corto <= actual + 1 else 1900 + corto
    return anio if 1950 <= anio <= datetime.now(timezone.utc).year + 1 else None


def interpretar(pregunta: dict, texto: str) -> Optional[str]:
    """Valor normalizado de la respuesta o None si no se entiende (el agente vuelve a preguntar)."""
    texto = (texto or "").strip()
    if not texto:
        return None
    tipo = pregunta["tipo"]
    if tipo == "abierta":
        return texto[:150]
    if tipo == "si_no":
        return _si_no(texto)
    if tipo == "opcion":
        return _opcion(pregunta["id"], texto, pregunta.get("opciones") or [])
    if tipo == "anio":
        anio = _anio(texto)
        return str(anio) if anio else None
    return None


def ayuda(pregunta: dict) -> str:
    """Cómo contestar (para repreguntar por WhatsApp cuando no se entendió)."""
    tipo = pregunta["tipo"]
    if tipo == "si_no":
        return "Responde *Sí* o *No*, por favor."
    if tipo == "opcion":
        return "Responde con el número de la opción:\n" + "\n".join(f"{i}. {o}" for i, o in enumerate(pregunta["opciones"], 1))
    if tipo == "anio":
        return "Escribe el año del modelo con 4 dígitos, por ejemplo *2019*."
    return "Escríbeme tu respuesta, por favor."


def texto_pregunta_whatsapp(config: dict, indice: int) -> str:
    lista = preguntas(config)
    p = lista[indice]
    cuerpo = f"*{indice + 1}/{len(lista)}* {p['texto']}"
    if p["tipo"] == "opcion":
        cuerpo += "\n" + "\n".join(f"{i}. {o}" for i, o in enumerate(p["opciones"], 1))
    elif p["tipo"] == "si_no":
        cuerpo += " (Sí / No)"
    return cuerpo


# ------------------------------------------------------------ evaluación


def reglas_efectivas(config: dict) -> Dict[str, Dict[str, str]]:
    reglas = {k: dict(v) for k, v in REGLAS_BASE.items()}
    if config.get("experiencia_indispensable"):
        reglas["experiencia"] = {"no": NO_CUMPLE}
    for pid, mapa in (config.get("reglas") or {}).items():
        reglas.setdefault(pid, {}).update({_clave(k): v for k, v in (mapa or {}).items() if v in EFECTOS})
    return reglas


def evaluar(config: dict, respuestas: Dict[str, str]) -> dict:
    """Aplica las reglas de la vacante a las respuestas {id: valor normalizado}.

    Regresa {resultado, etiqueta, motivos: [{id, pregunta, respuesta, efecto, motivo}], faltantes}. Una
    respuesta que falta o que no se pudo leer nunca descarta: manda a revisión."""
    reglas = reglas_efectivas(config)
    veh = config.get("vehiculo") or {}
    textos = {p["id"]: p["texto"] for p in preguntas(config)}
    horas, zona = config.get("jornada_horas") or "", (config.get("zona") or "").strip()
    motivos: List[dict] = []

    def marcar(pid: str, efecto: str, motivo: str) -> None:
        if efecto != OK:
            motivos.append({"id": pid, "pregunta": textos.get(pid, pid), "respuesta": respuestas.get(pid, ""),
                            "efecto": efecto, "motivo": motivo})

    faltantes = [pid for pid in aplicables(config, respuestas) if not str(respuestas.get(pid) or "").strip()]
    for pid in faltantes:
        marcar(pid, REVISION, "Sin respuesta legible")

    for pid, mapa in reglas.items():
        if pid not in textos:
            continue  # pregunta omitida en esta vacante (p. ej. zona sin definir)
        valor = _clave(respuestas.get(pid))
        if valor and valor in mapa:
            motivo = MOTIVOS.get((pid, valor), f"Respuesta «{respuestas.get(pid)}»")
            marcar(pid, mapa[valor], motivo.replace("{horas}", str(horas)).replace("{zona}", zona))

    # Municipio: solo cuenta si la vacante configuró cobertura; fuera de ella = revisión (nunca descarte)
    cobertura = [_norm(m) for m in (config.get("cobertura") or []) if str(m).strip()]
    municipio = _norm(respuestas.get("municipio") or "")
    if cobertura and municipio and not any(m in municipio or municipio in m for m in cobertura):
        marcar("municipio", (config.get("reglas") or {}).get("municipio", {}).get("fuera_cobertura", REVISION),
               f"Vive en «{respuestas.get('municipio')}», fuera de la cobertura configurada")

    # Vehículo: tipo y año contra la vacante (solo si tiene vehículo propio). Fuera de parámetro = revisión.
    tiene_vehiculo = _clave(respuestas.get("vehiculo_propio")) != "no"
    permitidos = [t for t in (veh.get("tipos_permitidos") or []) if t]
    tipo = respuestas.get("tipo_vehiculo") or ""
    if tiene_vehiculo and tipo and permitidos and tipo not in permitidos:
        marcar("tipo_vehiculo", (config.get("reglas") or {}).get("tipo_vehiculo", {}).get("no_permitido", REVISION),
               f"Vehículo «{tipo}»; esta vacante pide: {', '.join(permitidos)}")
    minimo = veh.get("anio_minimo")
    anio = respuestas.get("anio_vehiculo") or ""
    if tiene_vehiculo and minimo and anio:
        try:
            if int(anio) < int(minimo):
                marcar("anio_vehiculo", (config.get("reglas") or {}).get("anio_vehiculo", {}).get("menor_al_minimo", REVISION),
                       f"Modelo {anio}; esta vacante pide {minimo} o más reciente")
        except ValueError:
            marcar("anio_vehiculo", REVISION, f"Año ilegible: «{anio}»")

    peor = max((_GRAVEDAD[m["efecto"]] for m in motivos), default=0)
    resultado = {0: "cumple", 1: "revision", 2: "no_cumple"}[peor]
    motivos.sort(key=lambda m: -_GRAVEDAD[m["efecto"]])
    return {"resultado": resultado, "etiqueta": RESULTADOS[resultado], "motivos": motivos, "faltantes": faltantes}


def evidencia(ev: dict) -> str:
    """Texto corto para `Postulacion.evidencia`."""
    if ev["resultado"] == "cumple":
        return "Prefiltro por reglas: cumple todos los criterios de la vacante."
    return f"Prefiltro por reglas — {ev['etiqueta']}: " + "; ".join(m["motivo"] for m in ev["motivos"][:4])


def respuestas_legibles(config: dict, respuestas: Dict[str, str]) -> List[dict]:
    return [{"id": p["id"], "pregunta": p["texto"], "respuesta": respuestas.get(p["id"], "")} for p in preguntas(config)]


def normalizar(cfg: Optional[dict], ubicacion_default: str = "") -> dict:
    """Valida lo que RH guarda en `Vacante.prefiltro_reglas` (vacío = sin prefiltro por reglas)."""
    if not cfg:
        return {}
    veh = cfg.get("vehiculo") or {}
    tipos = [t for t in (veh.get("tipos_permitidos") or []) if t in TIPOS_VEHICULO]
    anio = veh.get("anio_minimo")
    try:
        anio = int(anio) if anio not in (None, "", 0) else None
    except (TypeError, ValueError):
        raise ValueError("El año mínimo del vehículo debe ser un número (o vacío = sin año mínimo).")
    if anio is not None and not 1950 <= anio <= datetime.now(timezone.utc).year + 1:
        raise ValueError("El año mínimo del vehículo está fuera de rango.")
    horas = cfg.get("jornada_horas")
    try:
        horas = int(horas) if horas not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("La jornada debe indicarse en horas.")
    reglas = {}
    for pid, mapa in (cfg.get("reglas") or {}).items():
        if pid in IDS and isinstance(mapa, dict):
            reglas[pid] = {str(k).lower(): v for k, v in mapa.items() if v in EFECTOS}
    return {
        "activo": bool(cfg.get("activo", True)),
        "jornada_horas": horas,
        "ubicacion_texto": str(cfg.get("ubicacion_texto") or ubicacion_default or "").strip()[:120],
        "zona": str(cfg.get("zona") or "").strip()[:120],
        "cobertura": [str(m).strip()[:80] for m in (cfg.get("cobertura") or []) if str(m).strip()][:60],
        "experiencia_indispensable": bool(cfg.get("experiencia_indispensable")),
        "vehiculo": {"tipos_permitidos": tipos, "anio_minimo": anio},
        "reglas": reglas,
        "fotos_vehiculo": bool(cfg.get("fotos_vehiculo", True)),
    }
