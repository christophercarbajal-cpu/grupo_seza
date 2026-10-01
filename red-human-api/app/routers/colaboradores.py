"""Colaboradores — roster de personas dadas de alta al cerrar el Onboarding.

El alta la hace `contratacion.alta` («Dar de alta como colaborador»). 2026-09-15: aquí viven el perfil
detallado (GET /{codigo}), la BAJA (activo=False, conserva historial; reversible) y la ELIMINACIÓN
lógica (limpieza de pruebas; desaparece de listados y conteos, la fila se conserva).
"""

import re
from typing import List, Optional

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import cuenta_actual, usuario_actual, usuario_decisor
from ..models import AsignacionCurso, Cliente, Colaborador, Cuenta, Usuario, registrar
from ..serial import colaborador_detalle_dict, colaborador_dict
from ..services import masivo

router = APIRouter(prefix="/colaboradores", tags=["colaboradores"])


@router.get("")
def listar(
    activo: Optional[bool] = None,
    cliente_id: Optional[int] = None,  # Fase 5: solo los contratados para ese Cliente (0 = sin Cliente / directo)
    db: Session = Depends(get_db),
    _: Usuario = Depends(usuario_actual),
    cuenta: Cuenta = Depends(cuenta_actual),
):
    q = (
        db.query(Colaborador)
        .filter(Colaborador.cuenta_id == cuenta.id, Colaborador.eliminado_en.is_(None))  # eliminados (lógico) nunca salen
        .order_by(Colaborador.id.desc())
    )
    if activo is not None:
        q = q.filter(Colaborador.activo.is_(activo))
    if cliente_id is not None:
        q = q.filter(Colaborador.cliente_id.is_(None)) if cliente_id == 0 else q.filter(Colaborador.cliente_id == cliente_id)
    return [colaborador_dict(c) for c in q.all()]


@router.get("/clientes")
def clientes_con_colaboradores(
    db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual),
):
    """Fase 5: opciones del filtro por Cliente — solo Clientes que ya tienen colaboradores, con conteo,
    más «Directo (sin Cliente)» si aplica."""
    filas = (
        db.query(Colaborador.cliente_id, func.count(Colaborador.id))
        .filter(Colaborador.cuenta_id == cuenta.id, Colaborador.eliminado_en.is_(None))
        .group_by(Colaborador.cliente_id)
        .all()
    )
    conteo = {cid: n for cid, n in filas}
    ids = [cid for cid in conteo if cid is not None]
    clientes = db.query(Cliente).filter(Cliente.id.in_(ids)).all() if ids else []
    salida = [{"id": c.id, "nombre": c.nombre, "colaboradores": conteo.get(c.id, 0)} for c in sorted(clientes, key=lambda c: c.nombre.lower())]
    if None in conteo:
        salida.append({"id": 0, "nombre": "Directo (sin Cliente)", "colaboradores": conteo[None]})
    return salida


def _por_codigo(db: Session, codigo: str, cuenta_id: int) -> Colaborador:
    col = db.query(Colaborador).filter(
        Colaborador.codigo == codigo, Colaborador.cuenta_id == cuenta_id, Colaborador.eliminado_en.is_(None)
    ).first()
    if not col:
        raise HTTPException(404, "Colaborador no encontrado")
    return col


# ------------------------------------------------------------
# Alta manual e importación básica (Desempeño v2 · Fase 4, 2026-09-27)
# Empleados que YA trabajan en la empresa entran al roster sin pasar por Vacantes, Contratación ni
# Onboarding. Sigue siendo la base maestra: Desempeño, Clima y Conocimiento toman de aquí empresa, área,
# puesto y jefe.
# ------------------------------------------------------------


def _norm_tel(t: str) -> str:
    digitos = re.sub(r"\D", "", t or "")
    return digitos[-10:] if len(digitos) >= 10 else digitos


def _roster(db: Session, cuenta_id: int) -> List[Colaborador]:
    return db.query(Colaborador).filter(Colaborador.cuenta_id == cuenta_id, Colaborador.eliminado_en.is_(None)).all()


def posibles_duplicados(roster: List[Colaborador], nombre: str, correo: str, telefono: str) -> List[dict]:
    """Coincidencias por correo, teléfono (10 dígitos) o nombre idéntico. Solo se muestran: RH decide."""
    salida = []
    correo_n, tel_n, nombre_n = (correo or "").strip().lower(), _norm_tel(telefono), " ".join((nombre or "").lower().split())
    for c in roster:
        motivos = []
        if correo_n and (c.correo or "").strip().lower() == correo_n:
            motivos.append("mismo correo")
        if tel_n and _norm_tel(c.telefono) == tel_n:
            motivos.append("mismo teléfono")
        if nombre_n and " ".join((c.nombre or "").lower().split()) == nombre_n:
            motivos.append("mismo nombre")
        if motivos:
            salida.append({"id": c.codigo, "nombre": c.nombre, "motivos": motivos})
    return salida


def _resolver_jefe(roster: List[Colaborador], ref: str) -> Optional[Colaborador]:
    """El jefe se indica con su código COL-####, su correo o su nombre exacto (del mismo roster)."""
    ref_n = (ref or "").strip().lower()
    if not ref_n:
        return None
    for c in roster:
        if c.codigo.lower() == ref_n or (c.correo and c.correo.strip().lower() == ref_n):
            return c
    por_nombre = [c for c in roster if " ".join(c.nombre.lower().split()) == " ".join(ref_n.split())]
    return por_nombre[0] if len(por_nombre) == 1 else None


class ColaboradorIn(BaseModel):
    nombre: str
    correo: str = ""
    telefono: str = ""
    puesto: str = ""
    area: str = ""
    empresa: str = ""
    ubicacion: str = ""
    jefe: str = ""               # COL-####, correo o nombre del jefe en el roster
    fecha_ingreso: str = ""      # AAAA-MM-DD
    tipo_contratacion: str = ""
    confirmar_duplicado: bool = False


def _crear(db: Session, cuenta: Cuenta, datos: ColaboradorIn, por: str, roster: List[Colaborador]) -> Colaborador:
    if not datos.nombre.strip():
        raise HTTPException(400, "El nombre es obligatorio.")
    fecha = None
    if datos.fecha_ingreso.strip():
        try:
            fecha = datetime.fromisoformat(datos.fecha_ingreso.strip()[:10]).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(400, f"Fecha de ingreso inválida «{datos.fecha_ingreso}» (usa AAAA-MM-DD).")
    jefe = _resolver_jefe(roster, datos.jefe)
    col = Colaborador(
        codigo="TMP", cuenta_id=cuenta.id, nombre=datos.nombre.strip(), correo=datos.correo.strip().lower(),
        telefono=datos.telefono.strip(), puesto=datos.puesto.strip(), area=datos.area.strip(),
        empresa=datos.empresa.strip() or (cuenta.razon_social or cuenta.nombre_visible), ubicacion=datos.ubicacion.strip(),
        jefe_id=jefe.id if jefe else None, jefe_directo=jefe.nombre if jefe else datos.jefe.strip(),
        fecha_ingreso=fecha, tipo_contratacion=datos.tipo_contratacion.strip(), activo=True, dado_de_alta_por=por,
    )
    db.add(col)
    db.flush()
    col.codigo = f"COL-{100 + col.id}"
    return col


@router.post("", status_code=201)
def alta_manual(datos: ColaboradorIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Alta manual de un empleado existente. Si parece duplicado (correo, teléfono o nombre), responde 409
    con las coincidencias; RH confirma con `confirmar_duplicado` si de verdad es otra persona."""
    roster = _roster(db, cuenta.id)
    dups = posibles_duplicados(roster, datos.nombre, datos.correo, datos.telefono)
    if dups and not datos.confirmar_duplicado:
        raise HTTPException(409, "Posible duplicado: " + "; ".join(f"{d['nombre']} ({d['id']}, {', '.join(d['motivos'])})" for d in dups)
                            + ". Confirma si es otra persona.")
    col = _crear(db, cuenta, datos, u.nombre, roster)
    registrar(db, u.nombre, "colaborador_alta_manual", "colaborador", col.codigo, {"nombre": col.nombre, "puesto": col.puesto, "correo_rh": u.correo})
    db.commit()
    return colaborador_dict(col)


ALIAS_IMPORTAR = {
    "nombre": ("nombre", "nombre_completo", "colaborador", "empleado"),
    "correo": ("correo", "email", "correo_electronico"),
    "telefono": ("telefono", "celular", "whatsapp", "telefono_celular"),
    "puesto": ("puesto", "cargo"),
    "area": ("area", "departamento"),
    "empresa": ("empresa", "razon_social"),
    "ubicacion": ("ubicacion", "sede", "sucursal"),
    "jefe": ("jefe", "jefe_directo", "jefe_inmediato", "correo_jefe"),
    "fecha_ingreso": ("fecha_ingreso", "ingreso", "fecha_de_ingreso"),
    "tipo_contratacion": ("tipo_contratacion", "contrato", "tipo_de_contrato"),
}


def _fila_importacion(f: dict) -> dict:
    return {campo: next((str(f[a]).strip() for a in alias if f.get(a) not in (None, "")), "") for campo, alias in ALIAS_IMPORTAR.items()}


@router.get("/importar/formato")
def formato_importacion(_: Usuario = Depends(usuario_actual)):
    return masivo.csv_plantilla("colaboradores.csv", list(ALIAS_IMPORTAR), [
        ["Sandra López Ruiz", "sandra.lopez@empresa.mx", "5512345678", "Gerente de proyectos", "PMO", "", "CDMX", "director.pmo@empresa.mx", "2024-03-01", "Tiempo indeterminado"],
    ])


@router.post("/importar/vista-previa")
async def vista_previa_importacion(archivo: UploadFile = File(...), db: Session = Depends(get_db), _: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Lee el archivo y muestra, por fila: datos normalizados, errores y POSIBLES DUPLICADOS (contra el roster
    y dentro del mismo archivo). NO guarda nada: RH revisa y confirma con /importar/confirmar."""
    filas = await masivo.leer_tabla(archivo)
    roster = _roster(db, cuenta.id)
    salida, vistos = [], []
    for n, f in filas:
        d = _fila_importacion(f)
        errores = []
        if not d["nombre"]:
            errores.append("Falta el nombre.")
        if d["correo"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", d["correo"]):
            errores.append(f"Correo inválido «{d['correo']}».")
        if d["fecha_ingreso"]:
            try:
                datetime.fromisoformat(d["fecha_ingreso"][:10])
            except ValueError:
                errores.append(f"Fecha de ingreso inválida «{d['fecha_ingreso']}» (usa AAAA-MM-DD).")
        dups = posibles_duplicados(roster, d["nombre"], d["correo"], d["telefono"])
        for otra in vistos:
            if (d["correo"] and d["correo"].lower() == otra["datos"]["correo"].lower()) or (d["telefono"] and _norm_tel(d["telefono"]) == _norm_tel(otra["datos"]["telefono"])):
                dups.append({"id": f"fila {otra['fila']}", "nombre": otra["datos"]["nombre"], "motivos": ["repetido en el archivo"]})
        fila = {"fila": n, "datos": d, "errores": errores, "duplicados": dups}
        vistos.append(fila)
        salida.append(fila)
    return {
        "filas": salida,
        "validas": sum(1 for x in salida if not x["errores"]),
        "conErrores": sum(1 for x in salida if x["errores"]),
        "posiblesDuplicados": sum(1 for x in salida if x["duplicados"]),
    }


class ConfirmarImportacionIn(BaseModel):
    filas: List[dict] = []               # los `datos` de la vista previa que RH aceptó
    incluir_duplicados: bool = False     # False = se omiten las filas con posible duplicado


@router.post("/importar/confirmar", status_code=201)
def confirmar_importacion(datos: ConfirmarImportacionIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Da de alta las filas confirmadas (vuelve a validar). El jefe puede venir en el mismo archivo: se
    enlaza en una segunda pasada. Una fila mala no tumba las demás (savepoint por fila)."""
    roster = _roster(db, cuenta.id)
    creados, omitidos, errores, pendientes_jefe = [], [], [], []
    for i, d in enumerate(datos.filas, start=1):
        entrada = ColaboradorIn(**{k: str(d.get(k) or "") for k in ALIAS_IMPORTAR})
        if posibles_duplicados(roster, entrada.nombre, entrada.correo, entrada.telefono) and not datos.incluir_duplicados:
            omitidos.append({"fila": i, "nombre": entrada.nombre, "motivo": "posible duplicado"})
            continue
        sp = db.begin_nested()
        try:
            col = _crear(db, cuenta, entrada, u.nombre, roster)
            sp.commit()
        except HTTPException as ex:
            sp.rollback()
            errores.append({"fila": i, "nombre": entrada.nombre, "error": ex.detail})
            continue
        roster.append(col)
        creados.append(col)
        if entrada.jefe and not col.jefe_id:
            pendientes_jefe.append((col, entrada.jefe))
    for col, ref in pendientes_jefe:
        jefe = _resolver_jefe(roster, ref)
        if jefe and jefe.id != col.id:
            col.jefe_id, col.jefe_directo = jefe.id, jefe.nombre
    registrar(db, u.nombre, "colaboradores_importados", "colaborador", str(len(creados)),
              {"creados": [c.codigo for c in creados], "omitidos": len(omitidos), "errores": len(errores), "correo_rh": u.correo})
    db.commit()
    return {"creados": [colaborador_dict(c) for c in creados], "omitidos": omitidos, "errores": errores}


class EditarColaboradorIn(BaseModel):
    correo: Optional[str] = None
    telefono: Optional[str] = None
    puesto: Optional[str] = None
    area: Optional[str] = None
    empresa: Optional[str] = None
    ubicacion: Optional[str] = None
    jefe: Optional[str] = None   # COL-#### / correo / nombre del roster; "" = sin jefe


@router.patch("/{codigo}")
def editar(codigo: str, datos: EditarColaboradorIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual)):
    """Datos base del roster (los que leen Desempeño, Clima y Conocimiento), incluido el jefe."""
    col = _por_codigo(db, codigo, cuenta.id)
    cambios = {}
    for campo in ("correo", "telefono", "puesto", "area", "empresa", "ubicacion"):
        valor = getattr(datos, campo)
        if valor is not None:
            setattr(col, campo, valor.strip().lower() if campo == "correo" else valor.strip())
            cambios[campo] = getattr(col, campo)
    if datos.jefe is not None:
        if not datos.jefe.strip():
            col.jefe_id, col.jefe_directo = None, ""
        else:
            jefe = _resolver_jefe(_roster(db, cuenta.id), datos.jefe)
            if not jefe or jefe.id == col.id:
                raise HTTPException(400, "No encontré a ese jefe en el roster (usa su código COL-####, correo o nombre exacto).")
            col.jefe_id, col.jefe_directo = jefe.id, jefe.nombre
        cambios["jefe"] = col.jefe_directo
    registrar(db, u.nombre, "colaborador_editado", "colaborador", col.codigo, {**cambios, "correo_rh": u.correo})
    db.commit()
    return colaborador_detalle_dict(col)


@router.get("/{codigo}")
def detalle(codigo: str, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    """Perfil completo: datos de alta, condiciones, expediente con documentos, candidato de origen."""
    return colaborador_detalle_dict(_por_codigo(db, codigo, cuenta.id))


class BajaIn(BaseModel):
    motivo: str = ""


def postulacion_origen(db: Session, col: Colaborador):
    """La postulación CONTRATADA de este colaborador: `postulacion_origen_id` (altas desde 2026-10-01); para altas
    previas, la del expediente con el que se dio de alta; si no, la última cerrada como «contratado» de su candidato."""
    from ..models import Expediente, Postulacion

    if col.postulacion_origen_id:
        p = db.get(Postulacion, col.postulacion_origen_id)
        if p:
            return p
    if col.expediente_id:
        e = db.get(Expediente, col.expediente_id)
        if e and e.postulacion:
            return e.postulacion
    if col.candidato_origen_id:
        return (db.query(Postulacion).filter(Postulacion.candidato_id == col.candidato_origen_id, Postulacion.motivo_cierre == "contratado")
                .order_by(Postulacion.id.desc()).first())
    return None


def expediente_completo_dict(db: Session, col: Colaborador, u: Usuario) -> dict:
    """«Ver expediente completo» (Cambios ZESE, 2026-10-01): TODO el historial previo del colaborador leído de sus
    registros ORIGINALES (postulación, vehículo, entrevistas, evaluaciones, expediente, onboarding, capacitación) — nada
    se copia ni se duplica; los archivos se abren con las rutas de siempre (visor interno de la ficha)."""
    from ..models import ESTADOS_VEHICULO, LADOS_VEHICULO, RESULTADOS_CAPACITACION, TareaOnboarding
    from ..serial import evaluacion_candidato_dict, iso
    from ..services import flujo_operativo, prefiltro_reglas
    from .evaluaciones import evaluaciones_de

    p = postulacion_origen(db, col)
    c = p.candidato if p else col.candidato_origen
    e = p.expediente if p else None
    vac = p.vacante if p else None
    a = (p.analisis or {}) if p else {}

    # respuestas de filtros (web, chat y agente), tal como quedaron
    pr = a.get("prefiltro_reglas") or {}
    preguntas = {q["id"]: q["texto"] for q in prefiltro_reglas.preguntas(vac.prefiltro_reglas)} if vac and prefiltro_reglas.activo(vac.prefiltro_reglas) else {}
    filtros = [{"pregunta": preguntas.get(k, k), "respuesta": (pr.get("textos") or {}).get(k) or v, "origen": pr.get("canal") or ""}
               for k, v in (pr.get("respuestas") or {}).items()]
    filtros += [{"pregunta": x.get("pregunta", ""), "respuesta": x.get("respuesta", ""), "origen": "web"} for x in (a.get("respuestas_web") or [])]
    filtros += [{"pregunta": x.get("pregunta", ""), "respuesta": x.get("respuesta", ""), "origen": "agente"}
                for x in ((a.get("preguntas_agente") or {}).get("respuestas") or [])]
    ev_pr = (pr.get("evaluacion") or {})

    r = p.revision_vehiculo if p else None
    vehiculo = {
        "estado": ESTADOS_VEHICULO.get(r.estado, r.estado), "decididoPor": r.decidido_por or "", "comentario": r.comentario or "",
        "fotos": [{"lado": lado, "nombre": nombre, "url": f"/candidatos/{p.codigo}/vehiculo/foto/{lado}"}
                  for lado, nombre in LADOS_VEHICULO.items() if lado in (r.fotos or {})],
    } if r else None

    entrevistas = []
    for eh in (p.entrevistas_humanas if p else []):
        entrevistas.append({
            "tipo": "Entrevista", "fecha": iso(eh.fecha), "lugar": " — ".join(x for x in (eh.tienda, eh.ubicacion) if x),
            "entrevistador": eh.entrevistador or "", "cancelada": bool(eh.cancelada),
            "confirmada": bool(eh.confirmada_en), "asistencia": eh.asistencia or "",
            "resultado": RESULTADOS_CAPACITACION.get(eh.resultado or "", "") or ({"aprobado": "Aprobado", "no_aprobado": "No aprobado"}.get(eh.resultado or "", eh.resultado or "")),
            "observaciones": eh.comentario or "", "registradoPor": eh.registrado_por or "",
        })
    for ent in (p.entrevistas if p else []):
        entrevistas.append({"tipo": "Entrevista Red Human", "fecha": iso(getattr(ent, "creada_en", None) or getattr(ent, "creado_en", None)), "lugar": "",
                            "entrevistador": "Red Human", "cancelada": False, "confirmada": False, "asistencia": ent.estado or "",
                            "resultado": str((ent.evaluacion or {}).get("recomendacion") or ""), "observaciones": str((ent.evaluacion or {}).get("resumen") or ""),
                            "registradoPor": ""})

    try:
        evaluaciones = [evaluacion_candidato_dict(ev, u, db) for ev in (evaluaciones_de(db, p) if p else [])]
    except Exception:  # noqa: BLE001 — módulo no disponible
        evaluaciones = []

    documentos = [{"tipo": d.tipo, "estado": flujo_operativo.estado_documento(d), "tieneArchivo": bool(d.archivo), "nombreArchivo": d.nombre_archivo or "",
                   "revisadoPor": d.revisado_por or "", "interno": bool(d.interno),
                   "url": f"/contratacion/expedientes/{e.id}/documentos/{d.tipo}/archivo" if d.archivo else None}
                  for d in (e.documentos if e else []) if d.estado != "no_aplica"]
    try:
        tareas = db.query(TareaOnboarding).filter(TareaOnboarding.expediente_id == e.id).order_by(TareaOnboarding.id).all() if e else []
    except Exception:  # noqa: BLE001
        tareas = []
    capacitacion = []
    from sqlalchemy import or_

    cond = [AsignacionCurso.colaborador_id == col.id] + ([AsignacionCurso.postulacion_id == p.id] if p else [])
    asignaciones = db.query(AsignacionCurso).filter(or_(*cond)).order_by(AsignacionCurso.id).all()
    for asg in asignaciones:
        capacitacion.append({"curso": asg.curso.titulo if asg.curso else "", "codigo": asg.codigo, "tipo": asg.tipo, "estado": asg.estado,
                             "calificacion": asg.calificacion, "aprobado": asg.aprobado, "completadoEn": iso(asg.completado_en),
                             "preguntas": len(asg.curso.preguntas_evaluacion) if asg.curso else 0})
    return {
        "colaborador": {"codigo": col.codigo, "nombre": col.nombre, "puesto": col.puesto, "fechaIngreso": iso(col.fecha_ingreso)},
        "candidato": {"codigo": c.codigo, "nombre": c.nombre, "fuente": c.fuente, "telefono": c.telefono, "correo": c.correo} if c else None,
        "postulacion": {"codigo": p.codigo, "vacante": vac.titulo if vac else "", "vacanteCodigo": vac.codigo if vac else "",
                        "etapa": p.etapa, "estadoPipeline": "Contratado" if p.motivo_cierre == "contratado" else ("Activa" if p.activa else (p.motivo_cierre or "Cerrada")),
                        "creada": iso(p.creado_en), "cerrada": iso(p.cerrada_en)} if p else None,
        "filtros": {"resultado": ev_pr.get("etiqueta") or "", "respuestas": filtros},
        "vehiculo": vehiculo,
        "referencias": (e.referencias or []) if e else [],
        "documentos": documentos,
        "entrevistas": entrevistas,
        "evaluaciones": evaluaciones,
        "onboarding": {
            "expedienteId": e.id if e else None,
            "condiciones": {"puesto": e.puesto, "sueldo": e.sueldo, "tipoContratacion": e.tipo_contratacion, "fechaIngreso": iso(e.fecha_ingreso),
                            "ubicacion": e.ubicacion, "jefeDirecto": e.jefe_directo} if e else None,
            "tareas": [{"nombre": t.nombre, "estado": t.estado, "responsable": t.responsable, "fechaLimite": iso(t.fecha_limite),
                        "realizadaPor": t.realizada_por, "realizadaEn": iso(t.realizada_en)} for t in tareas],
            "alta": {"por": e.alta_autorizada_por, "en": iso(e.alta_fecha)} if e and e.estado == "alta" else None,
        },
        "capacitacion": capacitacion,
        "historial": list((p.historial if p else None) or []),
    }


@router.get("/{codigo}/expediente-completo")
def expediente_completo(codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_actual), cuenta: Cuenta = Depends(cuenta_actual)):
    return expediente_completo_dict(db, _por_codigo(db, codigo, cuenta.id), u)


@router.post("/{codigo}/baja")
def dar_de_baja(
    codigo: str, datos: BajaIn, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor),
    cuenta: Cuenta = Depends(cuenta_actual),
):
    """Baja del colaborador: activo=False con fecha, motivo y quién. Conserva TODO el historial y se
    puede reactivar (POST /{codigo}/reactivar)."""
    col = _por_codigo(db, codigo, cuenta.id)
    if not col.activo:
        raise HTTPException(409, "El colaborador ya está dado de baja.")
    col.activo = False
    col.baja_en = datetime.now(timezone.utc)
    col.baja_motivo = datos.motivo.strip()[:300]
    col.baja_por = u.nombre
    registrar(db, u.nombre, "colaborador_baja", "colaborador", col.codigo, {"motivo": col.baja_motivo, "correo_rh": u.correo})
    db.commit()
    return colaborador_detalle_dict(col)


@router.post("/{codigo}/reactivar")
def reactivar(
    codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual),
):
    col = _por_codigo(db, codigo, cuenta.id)
    if col.activo:
        raise HTTPException(409, "El colaborador ya está activo.")
    col.activo = True
    col.baja_en = None
    col.baja_motivo = ""
    col.baja_por = ""
    registrar(db, u.nombre, "colaborador_reactivado", "colaborador", col.codigo, {"correo_rh": u.correo})
    db.commit()
    return colaborador_detalle_dict(col)


@router.delete("/{codigo}")
def eliminar(
    codigo: str, db: Session = Depends(get_db), u: Usuario = Depends(usuario_decisor), cuenta: Cuenta = Depends(cuenta_actual),
):
    """Eliminación LÓGICA (limpieza de pruebas / registros erróneos): la fila se conserva con fecha y
    quién, pero desaparece de listados, filtros y conteos, y su código deja de resolverse. El
    expediente y el candidato de origen no se tocan."""
    col = _por_codigo(db, codigo, cuenta.id)
    col.eliminado_en = datetime.now(timezone.utc)
    col.eliminado_por = u.nombre
    col.activo = False
    # 2026-09-18: sus asignaciones de capacitación se eliminan (dejaban «fantasmas» en Seguimiento y en los
    # contadores «X personas asignadas»).
    asignaciones = db.query(AsignacionCurso).filter(AsignacionCurso.colaborador_id == col.id).all()
    cursos = sorted({a.curso.codigo for a in asignaciones if a.curso})
    for a in asignaciones:
        db.delete(a)
    registrar(db, u.nombre, "colaborador_eliminado", "colaborador", col.codigo, {"nombre": col.nombre, "correo_rh": u.correo, "asignaciones_curso_eliminadas": len(asignaciones), "cursos": cursos})
    db.commit()
    return {"ok": True, "colaborador": col.codigo, "asignacionesCursoEliminadas": len(asignaciones)}
