"""Regresión: preguntas corregidas del prefiltro y confirmación de asistencia antes del material (2026-10-02), base DESECHABLE.

1. Prefiltro — residencia con selectores (tipo «municipio», Estado → Municipio; valor «Municipio, Estado»); «¿Tu vehículo
   está rotulado?» (Sí / No, criterio = rotulado); circulación según los días de operación de la vacante (Sí / No);
   «¿Qué tipo de licencia tienes?» con las opciones del Estado de la vacante (sin «licencia correspondiente»).
2. Cita — el aviso trae fecha, hora, lugar y quién lo recibe y cierra con «¿Confirmas que vas a asistir?»; queda «Pendiente
   de confirmación» SIN material; una pregunta se contesta y se vuelve a pedir la confirmación; sin movimiento sale UNA vez
   «¿Podrás asistir? Necesitamos tu confirmación»; «Sí» → «Confirmada» + respuesta exacta + material (una sola vez); «no
   puedo» → se pregunta si reagenda y se avisa al reclutador.

Uso (desde red-human-api/):  python scripts/verificar_prefiltro_citas.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
BASE = Path(tempfile.mkdtemp()) / "citas.db"
os.environ["DATABASE_URL"] = f"sqlite:///{BASE.as_posix()}"
os.environ["ADMIN_PASSWORD"] = "Verificar123!"
os.environ["WHATSAPP_PROVIDER"] = ""  # nada sale: modo demo
sys.path.insert(0, str(RAIZ))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

FALLAS = []
SLUG = "chofer-de-reparto-con-unidad-propia-"
R_OK = {"municipio": "Puebla, Puebla", "jornada": "Sí", "experiencia": "No", "vehiculo_propio": "Sí", "tipo_vehiculo": "Sedán de cuatro puertas",
        "anio_vehiculo": "2019", "taxi": "No", "circulacion": "Sí", "licencia": "Automovilista", "poliza": "Sí", "android": "Sí"}


def check(cond, nombre):
    print(("✅ " if cond else "❌ ") + nombre)
    if not cond:
        FALLAS.append(nombre)


def prefiltro_unitario():
    from app.services import prefiltro_reglas as pr

    puebla = pr.configuracion(10, [pr.SEDAN], 2018, ubicacion_texto="Puebla")
    cdmx = pr.configuracion(14, [pr.SEDAN], None, ubicacion_texto="Ciudad de México", dias_operacion="lunes_sabado")
    por_id = {q["id"]: q for q in pr.preguntas(puebla)}
    todo = " ".join(q["texto"] for q in pr.preguntas(puebla) + pr.preguntas(cdmx)).lower()

    check(por_id["municipio"]["tipo"] == "municipio" and por_id["municipio"]["estado"] == "Puebla",
          "1 · residencia = selector (tipo «municipio») que arranca en el Estado de la vacante")
    check(por_id["taxi"]["texto"] == "¿Tu vehículo está rotulado?" and por_id["taxi"]["opciones"] == ["Sí", "No"],
          "1 · rotulado: «¿Tu vehículo está rotulado?» con Sí / No")
    check("registrado" not in todo and "taxi" not in todo.replace("tipo b (taxi)", ""), "1 · ya no se pregunta «rotulado o registrado como taxi»")
    check(por_id["circulacion"]["texto"] == "¿Tu vehículo puede circular todos los días?" and por_id["circulacion"]["opciones"] == ["Sí", "No"],
          "1 · circulación (vacante diaria): «¿Tu vehículo puede circular todos los días?» Sí / No")
    circ_cdmx = next(q for q in pr.preguntas(cdmx) if q["id"] == "circulacion")
    check(circ_cdmx["texto"] == "¿Tu vehículo puede circular de lunes a sábado?", "1 · circulación dinámica según los días de operación de la vacante")
    check("correspondiente" not in todo and por_id["licencia"]["texto"] == "¿Qué tipo de licencia tienes?",
          "1 · licencia: «¿Qué tipo de licencia tienes?» sin «licencia correspondiente»")
    lic_cdmx = next(q for q in pr.preguntas(cdmx) if q["id"] == "licencia")["opciones"]
    check(por_id["licencia"]["opciones"][0] == "Automovilista" and "Tipo A (automovilista)" in lic_cdmx
          and por_id["licencia"]["opciones"][-1] == pr.SIN_LICENCIA == lic_cdmx[-1],
          "1 · las opciones de licencia salen del Estado de la vacante (Puebla ≠ CDMX) + «No tengo licencia vigente»")
    cabos = pr.configuracion(10, [pr.SEDAN], 2020, ubicacion_texto="San José del Cabo")
    check(pr.estado_de(cabos) == "Baja California Sur" and pr.estado_de({"ubicacion_texto": "Mérida"}) == ""
          and next(q for q in pr.preguntas({"ubicacion_texto": "Mérida"}) if q["id"] == "licencia")["opciones"][:-1] == pr.LICENCIAS_GENERICAS,
          "1 · Estado deducido de la ubicación (configs previas); sin Estado conocido = licencias genéricas")

    ok = pr.evaluar(puebla, R_OK)
    check(ok["resultado"] == "cumple", "1 · respuestas en parámetro → Cumple perfil")
    ev = pr.evaluar(puebla, {**R_OK, "taxi": "Sí"})
    check(ev["resultado"] == "revision" and ev["motivos"][0]["motivo"] == "El vehículo está rotulado", "1 · rotulado «Sí» → revisión con motivo «El vehículo está rotulado»")
    ev = pr.evaluar(cdmx, {**R_OK, "municipio": "Iztapalapa, Ciudad de México", "circulacion": "No", "licencia": "Tipo A (automovilista)"})
    check(ev["resultado"] == "revision" and ev["motivos"][0]["motivo"] == "Su vehículo no puede circular de lunes a sábado",
          "1 · circulación «No» → revisión con los días de la vacante en el motivo")
    ev = pr.evaluar(puebla, {**R_OK, "licencia": pr.SIN_LICENCIA})
    check(ev["resultado"] == "revision" and ev["motivos"][0]["motivo"] == "Licencia vigente pendiente", "1 · sin licencia → revisión (documento pendiente ≠ descarte)")
    ev = pr.evaluar(puebla, {**R_OK, "licencia": "Motociclista"})
    check(ev["resultado"] == "revision" and "Motociclista" in ev["motivos"][0]["motivo"], "1 · licencia de otro tipo (motociclista) → revisión")
    solo_chofer = {**puebla, "licencias_aceptadas": ["Chofer particular"]}
    check(pr.evaluar(solo_chofer, R_OK)["resultado"] == "revision" and pr.evaluar(solo_chofer, {**R_OK, "licencia": "Chofer particular"})["resultado"] == "cumple",
          "1 · RH decide qué licencias acepta la vacante")
    con_cob = {**puebla, "cobertura": ["Puebla"]}
    check(pr.evaluar(con_cob, R_OK)["resultado"] == "cumple" and pr.evaluar(con_cob, {**R_OK, "municipio": "San Andrés Cholula, Puebla"})["resultado"] == "revision",
          "1 · con el valor «Municipio, Estado» la cobertura compara solo el municipio")
    lic = por_id["licencia"]
    check(pr.interpretar(lic, "chofer particular") == "Chofer particular" and pr.interpretar(lic, "no tengo") == pr.SIN_LICENCIA
          and pr.interpretar(lic, "1") == "Automovilista" and pr.interpretar(next(q for q in pr.preguntas(cdmx) if q["id"] == "licencia"), "tipo a")
          == "Tipo A (automovilista)", "1 · por chat la licencia se entiende por número o por nombre")
    check(pr.interpretar(por_id["circulacion"], "sí") == "si" and pr.interpretar(por_id["taxi"], "no") == "no", "1 · rotulado y circulación por chat = Sí / No")
    try:
        pr.normalizar({"activo": True, "dias_operacion": "a veces"})
        check(False, "1 · días de operación inválidos → error")
    except ValueError:
        check(True, "1 · días de operación inválidos → error")


def main():
    prefiltro_unitario()
    with TestClient(app):
        pass
    salida = subprocess.run([sys.executable, str(RAIZ / "scripts" / "cargar_demo_seza.py"), "--ejecutar"],
                            capture_output=True, text=True, encoding="utf-8", env=os.environ)
    check(salida.returncode == 0, "carga del ambiente SEZA")
    if salida.returncode:
        print(salida.stdout[-2000:], salida.stderr[-2000:])
        return

    from app.database import SessionLocal
    from app.models import Bitacora, NotificacionEnviada, Postulacion, Vacante
    from app.routers.candidatos import procesar_prefiltro
    from app.services import flujo_operativo, ia, seguimiento_citas

    def chat(codigo, texto):
        async def _uno():
            with SessionLocal() as db:
                p = db.query(Postulacion).filter(Postulacion.codigo == codigo).one()
                return (await procesar_prefiltro(db, p, texto, "whatsapp"))["respuesta"]
        return asyncio.run(_uno())

    with TestClient(app) as c, mock.patch.object(ia, "ia_activa", return_value=False):
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        cuentas = c.get("/cuentas").json()
        h = {"X-Cuenta-Id": str(next((x["id"] for x in cuentas if "SEZA" in x.get("nombre", "")), 1))}

        # ---------- 1 · API: configuración de la vacante y portal ----------
        with SessionLocal() as db:
            vac = db.query(Vacante).filter(Vacante.slug == SLUG + "puebla").first()
            VAC, cfg = vac.codigo, dict(vac.prefiltro_reglas)
        r = c.patch(f"/vacantes/{VAC}", json={"prefiltro_reglas": {**cfg, "dias_operacion": "lunes_viernes", "licencias_aceptadas": ["Automovilista", "Chofer particular"]}}, headers=h)
        pub = c.get(f"/vacantes/slug/{SLUG}puebla").json()
        qs = {q["id"]: q for q in pub["prefiltroPreguntas"]}
        check(r.status_code == 200 and qs["circulacion"]["texto"] == "¿Tu vehículo puede circular de lunes a viernes?"
              and qs["municipio"]["tipo"] == "municipio" and qs["municipio"]["estado"] == "Puebla" and "Chofer particular" in qs["licencia"]["opciones"]
              and "prefiltroReglas" not in pub, "1 · RH guarda días de operación y licencias; el portal recibe las preguntas nuevas sin las reglas")
        check(c.patch(f"/vacantes/{VAC}", json={"prefiltro_reglas": {**cfg, "dias_operacion": "x"}}, headers=h).status_code == 400,
              "1 · días de operación inválidos → 400")
        c.patch(f"/vacantes/{VAC}", json={"prefiltro_reglas": cfg}, headers=h)

        d = c.post("/candidatos/postular", data={"vacante": SLUG + "puebla", "nombre": "Rosa Cita", "telefono": "2221009001", "consentimiento": "true",
                                                 "respuestas_reglas": json.dumps(R_OK)}).json()
        rosa = d["postulacion"]
        det = c.get(f"/candidatos/{rosa}", headers=h).json()
        check(det["prefiltroReglas"]["etiqueta"] == "Cumple perfil", "1 · postulación web con residencia por selector y licencia por tipo → Cumple perfil")

        # ---------- 2 · cita pendiente de confirmación ----------
        cursos = c.get("/capacitacion", headers=h).json()
        induccion = next(x for x in (cursos if isinstance(cursos, list) else cursos.get("cursos", [])) if x.get("titulo") == "Inducción SEZA")
        cita = {"tienda": "Tienda Centro", "direccion": "Av. Reforma 10", "fecha": "2030-04-02", "hora": "10:30", "capacitador_tipo": "externo",
                "capacitador_nombre": "Laura Pérez", "curso_induccion": induccion["id"], "indicaciones": "Trae tu INE"}

        def citar(codigo):
            c.post(f"/candidatos/{codigo}/vehiculo/decision", json={"accion": "excepcion", "comentario": "Revisado en persona"}, headers=h)
            return c.post(f"/candidatos/{codigo}/operativo/entrevista", json=cita, headers=h).json()

        r = citar(rosa)
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == rosa).one()
            eh = flujo_operativo.entrevista_actual(p)
            aviso = flujo_operativo.texto_cita(p, eh, db)
            mensajes = [m.texto for m in p.mensajes if m.rol == "assistant"]
        check(all(x in aviso for x in ("02/04/2030", "10:30", "Tienda Centro", "Av. Reforma 10", "Laura Pérez"))
              and aviso.rstrip().endswith("¿Confirmas que vas a asistir?") and "material" not in aviso.lower(),
              "2.1 · aviso con fecha, hora, lugar y quién lo recibe; cierra con «¿Confirmas que vas a asistir?»")
        check(r["entrevista"]["estado"] == "Pendiente de confirmación" and r["induccionEnviada"] is None and not flujo_operativo.induccion_enviada(eh)
              and not any("Inducción SEZA" in m for m in mensajes), "2.2 · la cita queda «Pendiente de confirmación» y NO sale el material")

        resp = chat(rosa, "¿Dónde queda la tienda?")
        check("Tienda Centro" in resp and resp.rstrip().endswith("¿Confirmas que vas a asistir?"), "2.3 · una pregunta se responde y se vuelve a pedir la confirmación")
        resp = chat(rosa, "¿va a ser en la mañana?")
        with SessionLocal() as db:
            eh = flujo_operativo.entrevista_actual(db.query(Postulacion).filter(Postulacion.codigo == rosa).one())
            check(eh.confirmada_en is None and resp.rstrip().endswith("¿Confirmas que vas a asistir?"), "2.3 · una pregunta nunca cuenta como «Sí»")
        with mock.patch.object(ia, "_client") as cliente:
            cliente.return_value.responses.parse.return_value.output_parsed = ia.RespuestaCita(respuesta="Sí, lleva ropa cómoda.")
            resp = chat(rosa, "¿puedo ir de tenis?")
        check(resp == "Sí, lleva ropa cómoda.\n\n¿Confirmas que vas a asistir?", "2.3 · con IA la respuesta es natural y se vuelve a pedir la confirmación")

        # seguimiento por inactividad
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == rosa).one()
            eh = flujo_operativo.entrevista_actual(p)
            ahora = datetime.now(timezone.utc)
            check(not seguimiento_citas.necesita_seguimiento(p, eh, ahora, 4), "2.3 · con conversación reciente no se manda seguimiento")
            hace = (ahora - timedelta(hours=6)).isoformat()
            eh.envios = [{**x, "fecha": hace} for x in (eh.envios or [])]
            for m in p.mensajes:
                m.creado_en = ahora - timedelta(hours=6)
            db.commit()
        with mock.patch.object(seguimiento_citas.settings, "cita_seguimiento_horas", 4):
            n1 = asyncio.run(seguimiento_citas.revisar_confirmaciones_pendientes())
            n2 = asyncio.run(seguimiento_citas.revisar_confirmaciones_pendientes())
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == rosa).one()
            ultimo = [m.texto for m in p.mensajes if m.rol == "assistant"][-1]
        check(n1 == 1 and n2 == 0 and ultimo == "¿Podrás asistir? Necesitamos tu confirmación",
              "2.3 · inactivo → UN seguimiento «¿Podrás asistir? Necesitamos tu confirmación» (no se repite)")

        # confirmación
        resp = chat(rosa, "Sí, ahí estaré")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == rosa).one()
            eh = flujo_operativo.entrevista_actual(p)
            asist = [m.texto for m in p.mensajes if m.rol == "assistant"]
            estado = flujo_operativo.estado_entrevista(eh)[0]
        check(resp == "Perfecto, te esperamos el 02/04/2030 a las 10:30 en Tienda Centro, Av. Reforma 10. Te recibirá Laura Pérez. "
                      "Te compartimos el material de inducción para que lo revises antes de asistir",
              "2.4 · «Sí» → respuesta EXACTA con fecha, hora, lugar y quién lo recibe")
        check(eh.confirmada_en and eh.confirmada_por == "candidato" and estado == "Confirmada", "2.4 · la cita queda «Confirmada» en la base")
        check(flujo_operativo.induccion_enviada(eh) and asist.index(resp) < max(i for i, m in enumerate(asist) if "Inducción SEZA" in m),
              "2.4 · el material de inducción sale al confirmar, después de la respuesta")
        chat(rosa, "Sí")
        r = c.post(f"/candidatos/{rosa}/operativo/confirmar-cita", headers=h).json()
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == rosa).one()
            eh = flujo_operativo.entrevista_actual(p)
            n_mat = sum(1 for x in eh.envios if x.get("canal") == "induccion")
        check(n_mat == 1 and not r.get("induccionEnviada"), "2.4 · el material sale UNA sola vez")

        # ---------- 2.5 · no puede asistir → reagendar ----------
        d = c.post("/candidatos/postular", data={"vacante": SLUG + "puebla", "nombre": "Beto Reagenda", "telefono": "2221009002", "consentimiento": "true",
                                                 "respuestas_reglas": json.dumps(R_OK)}).json()
        beto = d["postulacion"]
        citar(beto)
        with SessionLocal() as db:
            n0 = db.query(Bitacora).filter(Bitacora.accion == "cita_no_asistira").count()
        resp = chat(beto, "No puedo ese día, tengo otro compromiso")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == beto).one()
            eh = flujo_operativo.entrevista_actual(p)
            avisos = [x for x in (p.historial or []) if x.get("evento") == "cita_aviso_reclutador"]
            n1 = db.query(Bitacora).filter(Bitacora.accion == "cita_no_asistira").count()
            estado = flujo_operativo.estado_entrevista(eh)[0]
        check("¿Necesitas reagendar tu entrevista?" in resp and eh.confirmada_en is None, "2.5 · «no puedo» → se le pregunta si necesita reagendar")
        check(avisos and n1 == n0 + 1 and estado == "No podrá asistir", "2.5 · el reclutador queda notificado de inmediato (ficha + bitácora) y la cita «No podrá asistir»")
        panel = c.get(f"/candidatos/{beto}/operativo", headers=h).json()
        check(panel["entrevista"]["noPodra"] and panel["entrevista"]["noPodra"]["reagendar"] is None, "2.5 · el panel de RH lo muestra")
        resp = chat(beto, "Sí")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == beto).one()
            eh = flujo_operativo.entrevista_actual(p)
            r_ = flujo_operativo.rechazo_cita(p, eh)
            avisos = [x for x in (p.historial or []) if x.get("evento") == "cita_aviso_reclutador"]
        check(eh.confirmada_en is None and r_ and r_["reagendar"] is True and len(avisos) == 2 and "otra fecha" in resp,
              "2.5 · el «Sí» a «¿reagendar?» NO confirma la cita: pide otra fecha y vuelve a avisar al reclutador")
        with mock.patch.object(seguimiento_citas.settings, "cita_seguimiento_horas", 4):
            with SessionLocal() as db:
                p = db.query(Postulacion).filter(Postulacion.codigo == beto).one()
                check(not seguimiento_citas.necesita_seguimiento(p, flujo_operativo.entrevista_actual(p), datetime.now(timezone.utc) + timedelta(hours=8), 4),
                      "2.5 · a quien dijo que no puede no se le manda el seguimiento de confirmación")
        r = c.patch(f"/candidatos/{beto}/operativo/entrevista", json={**cita, "fecha": "2030-04-05"}, headers=h)
        check(r.status_code == 200 and r.json()["entrevista"]["estado"] == "Pendiente de confirmación" and not r.json()["entrevista"]["noPodra"],
              "2.5 · al reprogramar vuelve a «Pendiente de confirmación»")

        # con correo de RH configurado, el aviso también sale por correo
        d = c.post("/candidatos/postular", data={"vacante": SLUG + "puebla", "nombre": "Ciro NoVa", "telefono": "2221009003", "consentimiento": "true",
                                                 "respuestas_reglas": json.dumps(R_OK)}).json()
        ciro = d["postulacion"]
        citar(ciro)
        with SessionLocal() as db:
            from app.models import Cuenta
            p = db.query(Postulacion).filter(Postulacion.codigo == ciro).one()
            db.get(Cuenta, p.cuenta_id).correo_comunicacion = "rh@seza.demo.invalid"
            db.commit()
        with mock.patch("app.services.correo.enviar_correo", mock.AsyncMock(return_value={"enviado": True, "detalle": "ok"})) as correo:
            chat(ciro, "no voy a poder ir")
            chat(ciro, "no")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == ciro).one()
            r_ = flujo_operativo.rechazo_cita(p, flujo_operativo.entrevista_actual(p))
            notifs = db.query(NotificacionEnviada).filter(NotificacionEnviada.evento == "cita_no_asistira", NotificacionEnviada.candidato_id == p.candidato_id).count()
        check(correo.await_count == 2 and notifs == 2 and r_["reagendar"] is False, "2.5 · el reclutador recibe correo al «no puedo» y a la respuesta de reagendar")


if __name__ == "__main__":
    main()
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
