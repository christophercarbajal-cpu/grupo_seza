"""Revisión de vehículo y decisiones del prefiltro por reglas (demo Grupo SEZA, 2026-09-29).

Liga pública (sin sesión, el token es el secreto): el candidato ve qué falta y lo sube uno por uno — 4 fotos
(frente, atrás y ambos costados) y 3 documentos (licencia vigente, tarjeta de circulación y póliza de seguro), que
quedan en el expediente de la postulación. Rutas de RH (con sesión y Cuenta): ver la revisión y las fotos,
reenviar la liga, aprobar / pedir corrección / marcar excepción, y aprobar a mano un prefiltro que quedó
en «Requiere revisión» o «No cumple». Toda decisión queda con el nombre de quien la tomó (HITL).
"""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import cuenta_actual, usuario_actual, usuario_decisor
from ..models import DOCUMENTOS_VEHICULO, LADOS_VEHICULO, Archivo, Cuenta, Postulacion, RevisionVehiculo, Usuario, registrar
from ..serial import nombre_empresa_candidato
from ..services import archivos as fs
from ..services import flujo_operativo
from ..services import prefiltro_reglas
from ..services import vehiculo as vehiculo_srv
from .candidatos import _por_codigo

router = APIRouter(tags=["vehiculo"])


# ------------------------------------------------------------ liga pública del candidato


def _por_token(db: Session, token: str) -> RevisionVehiculo:
    r = db.query(RevisionVehiculo).filter(RevisionVehiculo.token == token).first()
    if not r:
        raise HTTPException(404, "Esta liga no existe o ya no es válida.")
    if not r.postulacion.activa:
        raise HTTPException(410, "Esta postulación ya está cerrada.")
    return r


def _publica_dict(r: RevisionVehiculo) -> dict:
    p = r.postulacion
    faltan = vehiculo_srv.lados_faltantes(r)
    abierta = r.estado in ("pendiente", "correccion")
    return {
        "nombre": (p.nombre or "").split(" ")[0],
        "vacante": p.vacante.titulo if p.vacante else "",
        "empresa": nombre_empresa_candidato(p.vacante) if p.vacante else "",
        "estado": r.estado,
        "abierta": abierta,
        "comentario": r.comentario if r.estado == "correccion" else "",
        "lados": [
            {"clave": l, "nombre": n, "cargada": l in (r.fotos or {}), "pendiente": abierta and l in faltan}
            for l, n in LADOS_VEHICULO.items()
        ],
        "documentos": [
            {"clave": d["clave"], "nombre": d["tipo"], "cargado": d["cargado"], "estado": d["estadoSimple"],
             "motivo": d["notas"] if d["estadoSimple"] == "Requiere corrección" else "", "pendiente": abierta and d["pendiente"]}
            for d in vehiculo_srv.documentos_dict(p, r)
        ],
    }


@router.get("/vehiculo/publica/{token}")
def ver_publica(token: str, db: Session = Depends(get_db)):
    return _publica_dict(_por_token(db, token))


@router.post("/vehiculo/publica/{token}/foto")
async def subir_foto(token: str, lado: str = Form(...), archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    r = _por_token(db, token)
    if lado not in LADOS_VEHICULO:
        raise HTTPException(400, "Lado inválido.")
    if r.estado not in ("pendiente", "correccion"):
        raise HTTPException(409, "Tus fotos ya están en revisión. Si necesitas cambiar alguna, RH te lo pedirá por este medio.")
    if r.estado == "correccion" and lado not in vehiculo_srv.lados_faltantes(r):
        raise HTTPException(409, "Esa foto no necesita corrección.")
    val = await fs.validar(archivo, "foto")
    if not val.es_imagen:
        raise HTTPException(415, "Sube una foto (JPG, PNG o WEBP), no un PDF.")
    p = r.postulacion
    marca = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ruta = fs.guardar(val, f"vehiculo/{p.codigo}", f"{lado}-{marca}")
    a = Archivo(candidato_id=p.candidato_id, tipo=f"vehiculo_{lado}", nombre=val.nombre, ruta=ruta, mime=val.mime,
                tamano=val.tamano, subido_por="candidato (liga de vehículo)")
    db.add(a)
    db.flush()
    vehiculo_srv.registrar_foto(db, r, lado, a.id)
    db.commit()
    return _publica_dict(r)


@router.post("/vehiculo/publica/{token}/documento")
async def subir_documento(token: str, clave: str = Form(...), archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    """Licencia, tarjeta de circulación o póliza (foto o PDF): se guarda como Documento del expediente con la
    misma validación que la liga del expediente (Modo Prueba en el flujo operativo: queda «Recibido»)."""
    from .contratacion import subir_documento_interno

    r = _por_token(db, token)
    if clave not in DOCUMENTOS_VEHICULO:
        raise HTTPException(400, "Documento inválido.")
    if r.estado not in ("pendiente", "correccion"):
        raise HTTPException(409, "Tu información ya está en revisión. Si necesitas cambiar algo, RH te lo pedirá por este medio.")
    if r.estado == "correccion" and clave not in vehiculo_srv.documentos_faltantes(r):
        raise HTTPException(409, "Ese documento no necesita corrección.")
    p = r.postulacion
    vehiculo_srv.obtener_o_crear(db, p)  # asegura el expediente con los 3 documentos
    await subir_documento_interno(db, p.expediente, DOCUMENTOS_VEHICULO[clave], archivo, "candidato")
    vehiculo_srv.registrar_documento_subido(db, r, clave)
    db.commit()
    return _publica_dict(r)


def _archivo_de(db: Session, r: RevisionVehiculo, lado: str) -> FileResponse:
    dato = (r.fotos or {}).get(lado)
    a = db.get(Archivo, dato["archivo_id"]) if dato else None
    if not a or not fs.existe(a.ruta):
        raise HTTPException(404, "Foto no encontrada.")
    return FileResponse(a.ruta, media_type=a.mime or "image/jpeg", headers={"Cache-Control": "private, max-age=60"})


@router.get("/vehiculo/publica/{token}/foto/{lado}")
def ver_foto_publica(token: str, lado: str, db: Session = Depends(get_db)):
    return _archivo_de(db, _por_token(db, token), lado)


# ------------------------------------------------------------ RH


def _url_foto(p: Postulacion):
    marca = lambda l: ((p.revision_vehiculo.fotos or {}).get(l) or {}).get("archivo_id", "")  # noqa: E731
    return lambda lado: f"/candidatos/{p.codigo}/vehiculo/foto/{lado}?v={marca(lado)}"


def _salida(p: Postulacion) -> dict:
    return {"prefiltro": vehiculo_srv.resumen_prefiltro(p), "vehiculo": vehiculo_srv.revision_dict(p, _url_foto(p))}


def _con_reglas(p: Postulacion) -> Postulacion:
    if not (p.vacante and prefiltro_reglas.activo(p.vacante.prefiltro_reglas)):
        raise HTTPException(409, "La vacante de esta postulación no usa prefiltro por reglas ni revisión de vehículo.")
    return p


@router.get("/candidatos/{codigo}/vehiculo")
def ver_revision(codigo: str, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual),
                 cuenta: Cuenta = Depends(cuenta_actual)):
    return _salida(_por_codigo(db, codigo, cuenta.id))


@router.get("/candidatos/{codigo}/vehiculo/foto/{lado}")
def ver_foto(codigo: str, lado: str, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual),
             cuenta: Cuenta = Depends(cuenta_actual)):
    p = _por_codigo(db, codigo, cuenta.id)
    if not p.revision_vehiculo:
        raise HTTPException(404, "Sin fotos del vehículo.")
    return _archivo_de(db, p.revision_vehiculo, lado)


@router.post("/candidatos/{codigo}/vehiculo/enviar-liga")
async def enviar_liga(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                      cuenta: Cuenta = Depends(cuenta_actual)):
    p = _con_reglas(_por_codigo(db, codigo, cuenta.id))
    if not p.activa:
        raise HTTPException(409, "La postulación está cerrada.")
    if p.revision_vehiculo and p.revision_vehiculo.estado in vehiculo_srv.ESTADOS_CITABLES:
        raise HTTPException(409, "El vehículo ya está aprobado; no hace falta pedir fotos.")
    envio = await vehiculo_srv.enviar_liga(db, p, u.nombre)
    db.commit()
    return {**_salida(p), "envio": envio}


@router.post("/candidatos/{codigo}/vehiculo/generar-liga")
def generar_liga(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                 cuenta: Cuenta = Depends(cuenta_actual)):
    """Genera (o reutiliza) la liga del vehículo SIN enviarla: RH la abre, la copia o la manda después."""
    p = _con_reglas(_por_codigo(db, codigo, cuenta.id))
    vehiculo_srv.obtener_o_crear(db, p)
    registrar(db, u.nombre, "vehiculo_liga_generada", "postulacion", p.codigo, {})
    db.commit()
    return _salida(p)


@router.post("/candidatos/{codigo}/vehiculo/foto")
async def subir_foto_rh(codigo: str, lado: str = Form(...), archivo: UploadFile = File(...), db: Session = Depends(get_db),
                        u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Captura interna: RH sube una foto desde la ficha (alimenta la MISMA revisión que la liga del candidato)."""
    p = _con_reglas(_por_codigo(db, codigo, cuenta.id))
    if lado not in LADOS_VEHICULO:
        raise HTTPException(400, "Lado inválido.")
    r = vehiculo_srv.obtener_o_crear(db, p)
    val = await fs.validar(archivo, "foto")
    if not val.es_imagen:
        raise HTTPException(415, "Sube una foto (JPG, PNG o WEBP), no un PDF.")
    marca = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ruta = fs.guardar(val, f"vehiculo/{p.codigo}", f"{lado}-{marca}")
    a = Archivo(candidato_id=p.candidato_id, tipo=f"vehiculo_{lado}", nombre=val.nombre, ruta=ruta, mime=val.mime,
                tamano=val.tamano, subido_por=f"{u.nombre} (RH, ficha)")
    db.add(a)
    db.flush()
    vehiculo_srv.registrar_foto(db, r, lado, a.id)
    registrar(db, u.nombre, "vehiculo_foto_rh", "postulacion", p.codigo, {"lado": lado})
    db.commit()
    return _salida(p)


@router.post("/candidatos/{codigo}/vehiculo/documento")
async def subir_documento_rh(codigo: str, clave: str = Form(...), archivo: UploadFile = File(...), db: Session = Depends(get_db),
                             u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Captura interna: RH sube licencia, tarjeta o póliza desde la ficha (mismo expediente que la liga)."""
    from .contratacion import subir_documento_interno

    p = _con_reglas(_por_codigo(db, codigo, cuenta.id))
    if clave not in DOCUMENTOS_VEHICULO:
        raise HTTPException(400, "Documento inválido.")
    r = vehiculo_srv.obtener_o_crear(db, p)
    await subir_documento_interno(db, p.expediente, DOCUMENTOS_VEHICULO[clave], archivo, u.nombre)
    vehiculo_srv.registrar_documento_subido(db, r, clave)
    registrar(db, u.nombre, "vehiculo_documento_rh", "postulacion", p.codigo, {"documento": clave})
    db.commit()
    return _salida(p)


class DecisionIn(BaseModel):
    accion: str  # aprobar | correccion | excepcion
    comentario: str = ""
    lados: List[str] = []


@router.post("/candidatos/{codigo}/vehiculo/decision")
async def decidir(codigo: str, datos: DecisionIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
                  cuenta: Cuenta = Depends(cuenta_actual)):
    p = _con_reglas(_por_codigo(db, codigo, cuenta.id))
    r = p.revision_vehiculo
    if datos.accion not in ("aprobar", "correccion", "excepcion"):
        raise HTTPException(400, "Acción inválida: usa aprobar, correccion o excepcion.")
    if datos.accion == "aprobar" and not (r and all(l in (r.fotos or {}) for l in LADOS_VEHICULO)):
        raise HTTPException(409, "Faltan fotos del vehículo. Pide corrección o marca excepción con motivo.")
    if datos.accion == "aprobar" and vehiculo_srv.documentos_faltantes(r):
        faltan = ", ".join(DOCUMENTOS_VEHICULO[c] for c in vehiculo_srv.documentos_faltantes(r))
        raise HTTPException(409, f"Faltan documentos del vehículo ({faltan}). Pide corrección o marca excepción con motivo.")
    if datos.accion == "correccion":
        hay_docs = any(vehiculo_srv.documento(p, c) and vehiculo_srv.documento(p, c).archivo for c in DOCUMENTOS_VEHICULO)
        if not r or not (r.fotos or hay_docs):
            raise HTTPException(409, "Todavía no hay nada que corregir; reenvía la liga.")
        if not datos.comentario.strip():
            raise HTTPException(400, "Escribe qué debe corregir el candidato.")
    if datos.accion == "excepcion" and not datos.comentario.strip():
        raise HTTPException(400, "La excepción requiere un motivo.")
    vehiculo_srv.decidir(db, p, datos.accion, u.nombre, datos.comentario, datos.lados)
    flujo_operativo.al_decidir_vehiculo(db, p, datos.accion, u.nombre)
    envio = None
    if datos.accion == "correccion":  # se le reenvía la MISMA liga con lo que hay que corregir
        envio = await vehiculo_srv.enviar_liga(db, p, u.nombre)
    db.commit()
    return {**_salida(p), "envio": envio}


class AprobarPrefiltroIn(BaseModel):
    motivo: str


@router.post("/candidatos/{codigo}/prefiltro-reglas/aprobar")
async def aprobar_prefiltro(codigo: str, datos: AprobarPrefiltroIn, db: Session = Depends(get_db),
                            u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """RH aprueba un prefiltro que quedó en «Requiere revisión» o «No cumple» (con motivo) → queda como
    «Cumple perfil» y, si la vacante pide fotos, sale la liga del vehículo."""
    p = _con_reglas(_por_codigo(db, codigo, cuenta.id))
    if not p.prefiltro_completo:
        raise HTTPException(409, "El candidato todavía no termina el prefiltro.")
    if p.estado == "cumple":
        raise HTTPException(409, "El prefiltro ya está en «Cumple perfil».")
    if not datos.motivo.strip():
        raise HTTPException(400, "Escribe el motivo de la aprobación.")
    anterior = p.estado
    p.estado = "cumple"
    analisis = dict(p.analisis or {})
    estado = dict(analisis.get("prefiltro_reglas") or {})
    estado["aprobado_por_rh"] = {"usuario": u.nombre, "motivo": datos.motivo.strip(), "anterior": anterior,
                                 "fecha": datetime.now(timezone.utc).isoformat()}
    analisis["prefiltro_reglas"] = estado
    p.analisis = analisis
    p.historial = [*(p.historial or []), {"evento": "prefiltro_aprobado_rh", "usuario": u.nombre,
                                          "fecha": datetime.now(timezone.utc).isoformat(),
                                          "texto": f"Prefiltro aprobado por {u.nombre} (antes: {prefiltro_reglas.RESULTADOS.get(anterior, anterior)}) — {datos.motivo.strip()}"}]
    registrar(db, u.nombre, "prefiltro_reglas_aprobado_rh", "postulacion", p.codigo, {"anterior": anterior, "motivo": datos.motivo.strip()})
    flujo_operativo.al_aprobar_prefiltro(db, p, u.nombre, vehiculo_srv.requiere_fotos(p))
    envio = None
    if vehiculo_srv.requiere_fotos(p) and not (p.revision_vehiculo and p.revision_vehiculo.estado in vehiculo_srv.ESTADOS_CITABLES):
        envio = await vehiculo_srv.enviar_liga(db, p, u.nombre)
    db.commit()
    return {**_salida(p), "envio": envio}
