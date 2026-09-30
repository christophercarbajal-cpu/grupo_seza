"""Clientes y contactos — empresas para las que recluta una Cuenta (Fase B, punto 8) y sus
personas de contacto (Punto 10). Un contacto NO es un usuario del sistema: solo recibe las
notificaciones de Cliente configuradas en Fase D (services/notificaciones.py)."""

import re
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import masivo
from ..deps import cuenta_actual, usuario_actual, usuario_decisor
from ..models import Cliente, ClienteContacto, Cuenta, Usuario, registrar
from .auth import CORREO_RE

router = APIRouter(prefix="/clientes", tags=["clientes"])

ESTADOS = ("Activo", "Inactivo")


def _contacto_dict(k: ClienteContacto) -> dict:
    return {
        "id": k.id,
        "nombre": k.nombre,
        "apellidos": k.apellidos,
        "nombreCompleto": f"{k.nombre} {k.apellidos}".strip(),
        "puesto": k.puesto,
        "correo": k.correo,
        "telefono": k.telefono,
    }


def _cliente_dict(c: Cliente, detalle: bool = False) -> dict:
    base = {
        "id": c.id,
        "nombre": c.nombre,
        "razonSocial": c.razon_social,
        "nombreComercial": c.nombre_comercial,
        "nombreVisible": c.nombre_visible,
        "estado": c.estado,
        "color": c.color or "",
        "contactos": len(c.contactos),
        "creado": c.creado_en.isoformat(),
    }
    if detalle:
        base["listaContactos"] = [_contacto_dict(k) for k in c.contactos]
    return base


def _por_id(db: Session, cliente_id: int, cuenta_id: int) -> Cliente:
    c = db.query(Cliente).filter(Cliente.id == cliente_id, Cliente.cuenta_id == cuenta_id).first()
    if not c:
        raise HTTPException(404, "Cliente no encontrado")
    return c


def _contacto_por_id(c: Cliente, contacto_id: int) -> ClienteContacto:
    k = next((x for x in c.contactos if x.id == contacto_id), None)
    if not k:
        raise HTTPException(404, "Contacto no encontrado")
    return k


@router.get("")
def listar(
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(usuario_actual),
    cuenta: Cuenta = Depends(cuenta_actual),
):
    q = db.query(Cliente).filter(Cliente.cuenta_id == cuenta.id).order_by(Cliente.nombre)
    if estado:
        q = q.filter(Cliente.estado == estado)
    return [_cliente_dict(c) for c in q.all()]


@router.get("/{cliente_id}")
def detalle(
    cliente_id: int, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)
):
    """Ficha del cliente: datos generales + contactos."""
    return _cliente_dict(_por_id(db, cliente_id, cuenta.id), detalle=True)


class CrearIn(BaseModel):
    nombre: str
    razon_social: str = ""
    nombre_comercial: str = ""
    estado: str = "Activo"
    color: str = ""  # #RRGGBB de la marca (demo SEZA); vacío = color de Red Human


def _color(valor: str) -> str:
    """Color de marca validado (#RGB o #RRGGBB, en minúsculas); vacío se respeta."""
    valor = (valor or "").strip().lower()
    if valor and not re.fullmatch(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})", valor):
        raise HTTPException(400, "El color debe ser hexadecimal, por ejemplo #1d4ed8.")
    return valor


def _crear_cliente(db: Session, cuenta: Cuenta, u: Usuario, datos: CrearIn) -> Cliente:
    """Validaciones de POST /clientes — compartidas con la carga masiva (Fase 2). No hace commit."""
    nombre = datos.nombre.strip()
    if not nombre:
        raise HTTPException(400, "El nombre del Cliente es obligatorio.")
    if datos.estado not in ESTADOS:
        raise HTTPException(400, f"Estado inválido. Usa uno de: {', '.join(ESTADOS)}")
    existente = db.query(Cliente).filter(Cliente.cuenta_id == cuenta.id, Cliente.nombre.ilike(nombre)).first()
    if existente:
        raise HTTPException(409, f"Ya existe un Cliente llamado '{existente.nombre}' en esta Cuenta.")

    c = Cliente(
        cuenta_id=cuenta.id, nombre=nombre, razon_social=datos.razon_social.strip(),
        nombre_comercial=datos.nombre_comercial.strip(), estado=datos.estado, color=_color(datos.color),
    )
    db.add(c)
    db.flush()
    registrar(db, u.nombre, "cliente_creado", "cliente", str(c.id), {"nombre": c.nombre, "correo_rh": u.correo})
    return c


@router.post("", status_code=201)
def crear(
    datos: CrearIn,
    db: Session = Depends(get_db),
    u: Usuario = Depends(usuario_decisor),
    cuenta: Cuenta = Depends(cuenta_actual),
):
    c = _crear_cliente(db, cuenta, u, datos)
    db.commit()
    return _cliente_dict(c, detalle=True)


@router.post("/masivo", status_code=201)
async def crear_masivo(
    archivo: UploadFile = File(...), db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
    cuenta: Cuenta = Depends(cuenta_actual),
):
    """Fase 2 (2026-09-15) — alta masiva de Clientes desde CSV/Excel. Columnas: nombre, razon_social,
    nombre_comercial, estado y, opcionalmente, un primer contacto (contacto_nombre, contacto_apellidos,
    contacto_puesto, contacto_correo, contacto_telefono). Mismas reglas que POST /clientes; las filas
    con error se reportan y el resto se crea."""
    filas = await masivo.leer_tabla(archivo)
    resultado = masivo.Resultado()
    for numero, fila in filas:
        if not fila.get("nombre"):
            continue
        sp = db.begin_nested()
        try:
            estado = fila.get("estado") or "Activo"
            estado = "Inactivo" if estado.strip().lower().startswith("inact") else "Activo"
            c = _crear_cliente(db, cuenta, u, CrearIn(
                nombre=fila["nombre"], razon_social=fila.get("razon_social", ""),
                nombre_comercial=fila.get("nombre_comercial", ""), estado=estado,
            ))
            contacto_nombre = fila.get("contacto_nombre", "")
            if contacto_nombre:
                if not (fila.get("contacto_correo") or fila.get("contacto_telefono")):
                    raise HTTPException(400, "El contacto necesita correo o teléfono.")
                db.add(ClienteContacto(
                    cliente_id=c.id, nombre=contacto_nombre, apellidos=fila.get("contacto_apellidos", ""),
                    puesto=fila.get("contacto_puesto", ""), correo=fila.get("contacto_correo", "").lower(),
                    telefono=fila.get("contacto_telefono", ""),
                ))
                db.flush()
            sp.commit()
            resultado.ok(numero, {"id": c.id, "nombre": c.nombre, "contacto": bool(contacto_nombre)})
        except HTTPException as ex:
            sp.rollback()
            resultado.error(numero, str(ex.detail), fila.get("nombre", ""))
    registrar(db, u.nombre, "clientes_carga_masiva", "cuenta", str(cuenta.id), {"archivo": archivo.filename, **resultado.resumen()})
    db.commit()
    return resultado.dict()


@router.get("/masivo/plantilla")
def plantilla_masivo_clientes(_: Usuario = Depends(usuario_actual)):
    return masivo.csv_plantilla(
        "clientes",
        ["nombre", "razon_social", "nombre_comercial", "estado", "contacto_nombre", "contacto_apellidos", "contacto_puesto", "contacto_correo", "contacto_telefono"],
        [["Tiendas Sol", "Tiendas Sol SA de CV", "Sol Retail", "Activo", "Ana", "Pérez", "Gerente RH", "ana@sol.mx", "5512345678"]],
    )


class ActualizarIn(BaseModel):
    nombre: Optional[str] = None
    razon_social: Optional[str] = None
    nombre_comercial: Optional[str] = None
    estado: Optional[str] = None
    color: Optional[str] = None


@router.patch("/{cliente_id}")
def actualizar(
    cliente_id: int,
    datos: ActualizarIn,
    db: Session = Depends(get_db),
    u: Usuario = Depends(usuario_decisor),
    cuenta: Cuenta = Depends(cuenta_actual),
):
    c = _por_id(db, cliente_id, cuenta.id)
    if datos.estado is not None and datos.estado not in ESTADOS:
        raise HTTPException(400, f"Estado inválido. Usa uno de: {', '.join(ESTADOS)}")

    cambios = []
    if datos.nombre is not None and datos.nombre.strip():
        nombre = datos.nombre.strip()
        otro = db.query(Cliente).filter(Cliente.cuenta_id == cuenta.id, Cliente.nombre.ilike(nombre), Cliente.id != c.id).first()
        if otro:
            raise HTTPException(409, f"Ya existe un Cliente llamado '{otro.nombre}' en esta Cuenta.")
        c.nombre = nombre
        cambios.append("nombre")
    if datos.razon_social is not None:
        c.razon_social = datos.razon_social.strip()
        cambios.append("razon_social")
    if datos.nombre_comercial is not None:
        c.nombre_comercial = datos.nombre_comercial.strip()
        cambios.append("nombre_comercial")
    if datos.estado is not None:
        c.estado = datos.estado
        cambios.append("estado")
    if datos.color is not None:
        c.color = _color(datos.color)
        cambios.append("color")

    if cambios:
        registrar(db, u.nombre, "cliente_editado", "cliente", str(c.id), {"campos": cambios, "correo_rh": u.correo})
        db.commit()
    return _cliente_dict(c, detalle=True)


# ------------------------------------------------------------
# Contactos del cliente (Punto 10) — nombre, apellidos, puesto, correo, WhatsApp/teléfono
# ------------------------------------------------------------


class ContactoIn(BaseModel):
    nombre: str
    apellidos: str = ""
    puesto: str = ""
    correo: str = ""
    telefono: str = ""


def _validar_contacto(datos: ContactoIn) -> None:
    if not datos.nombre.strip():
        raise HTTPException(400, "El nombre del contacto es obligatorio.")
    if datos.correo.strip() and not CORREO_RE.match(datos.correo.strip()):
        raise HTTPException(400, "El correo del contacto no tiene un formato válido.")
    if not datos.correo.strip() and not datos.telefono.strip():
        raise HTTPException(400, "Captura al menos un correo o un WhatsApp/teléfono para poder notificarlo.")


@router.post("/{cliente_id}/contactos", status_code=201)
def agregar_contacto(
    cliente_id: int, datos: ContactoIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
    cuenta: Cuenta = Depends(cuenta_actual),
):
    c = _por_id(db, cliente_id, cuenta.id)
    _validar_contacto(datos)
    k = ClienteContacto(
        nombre=datos.nombre.strip(), apellidos=datos.apellidos.strip(), puesto=datos.puesto.strip(),
        correo=datos.correo.strip().lower(), telefono=datos.telefono.strip(),
    )
    c.contactos.append(k)
    db.flush()
    registrar(db, u.nombre, "contacto_cliente_agregado", "cliente", str(c.id), {"contacto": k.id, "nombre": f"{k.nombre} {k.apellidos}".strip(), "correo_rh": u.correo})
    db.commit()
    return _cliente_dict(c, detalle=True)


@router.patch("/{cliente_id}/contactos/{contacto_id}")
def editar_contacto(
    cliente_id: int, contacto_id: int, datos: ContactoIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
    cuenta: Cuenta = Depends(cuenta_actual),
):
    c = _por_id(db, cliente_id, cuenta.id)
    k = _contacto_por_id(c, contacto_id)
    _validar_contacto(datos)
    k.nombre = datos.nombre.strip()
    k.apellidos = datos.apellidos.strip()
    k.puesto = datos.puesto.strip()
    k.correo = datos.correo.strip().lower()
    k.telefono = datos.telefono.strip()
    registrar(db, u.nombre, "contacto_cliente_editado", "cliente", str(c.id), {"contacto": k.id, "correo_rh": u.correo})
    db.commit()
    return _cliente_dict(c, detalle=True)


@router.delete("/{cliente_id}/contactos/{contacto_id}")
def eliminar_contacto(
    cliente_id: int, contacto_id: int, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
    cuenta: Cuenta = Depends(cuenta_actual),
):
    c = _por_id(db, cliente_id, cuenta.id)
    k = _contacto_por_id(c, contacto_id)
    registrar(db, u.nombre, "contacto_cliente_eliminado", "cliente", str(c.id), {"contacto": k.id, "nombre": f"{k.nombre} {k.apellidos}".strip(), "correo_rh": u.correo})
    c.contactos.remove(k)  # delete-orphan
    db.commit()
    return _cliente_dict(c, detalle=True)
