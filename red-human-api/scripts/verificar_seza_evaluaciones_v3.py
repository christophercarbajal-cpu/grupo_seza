"""Regresión del flujo operativo v3 de Grupo SEZA (2026-10-01) sobre una base DESECHABLE.

Comprueba los 10 puntos del ajuste «chofer de reparto con unidad propia»:
  1. Tarjetas: resultados identificados (Perfil / Vehículo / Entrevista) en lugar del Score CV.
  2. Pipeline de 5 columnas (sin «Evaluación»); lo que estaba en «Evaluación» regresa a «Entrevista» intacto.
  3. Filtros de Entrevista: Realizadas → Aptos / No aptos y «Evaluaciones pendientes».
  4-6. «Agregar entrevista humana o evaluación» (incluida la Entrevista humana con Apto / No apto) nunca mueve la
     tarjeta; «Avanzar a Contratación» solo con la entrevista Apta y todo concluido y revisado.
  7. La liga del médico abre SU evaluación (no la «Capacitación en tienda · Otra» de la v1) y guarda ahí.
  8. El texto del evaluador queda con nombre y fecha, aparte del adjunto, y persiste.
  9. «Ver informe» inline / «Descargar» attachment; una captura vacía no se registra como falla.
  10. Texto + archivo desde la liga llegan a la evaluación correcta; la etapa solo cambia con «Avanzar a Contratación».

Uso (desde red-human-api/):  python scripts/verificar_seza_evaluaciones_v3.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASE = Path(tempfile.mkdtemp()) / "seza_v3.db"
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
PDF = b"%PDF-1.4\n" + b"0" * 900
PNG_VACIO = b""  # captura vacía usada como prueba


def check(cond, nombre):
    print(("✅ " if cond else "❌ ") + nombre)
    if not cond:
        FALLAS.append(nombre)


def main():
    with TestClient(app):  # arranque: crea tablas y administrador
        pass
    salida = subprocess.run([sys.executable, str(RAIZ / "scripts" / "cargar_demo_seza.py"), "--ejecutar"],
                            capture_output=True, text=True, encoding="utf-8", env=os.environ)
    check(salida.returncode == 0, "carga del ambiente SEZA")
    if salida.returncode:
        print(salida.stdout[-2000:], salida.stderr[-2000:])
        return

    with TestClient(app) as c:
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        cuentas = c.get("/cuentas").json()
        h = {"X-Cuenta-Id": str(next((x["id"] for x in cuentas if "SEZA" in x.get("nombre", "")), 1))}

        # ---- 2. pipeline de 5 columnas + normalización de «Evaluación» ----
        fl = c.get("/candidatos-flujo", headers=h).json()
        check(fl["etapas"] == ["Prefiltro", "Revisión de vehículo", "Entrevista", "Contratación", "Onboarding"],
              "pipeline: Prefiltro → Revisión de vehículo → Entrevista → Contratación → Onboarding")
        tarjetas = {t["nombre"]: t for t in c.get("/candidatos", headers=h).json()}
        check(not any(t["etapa"] == "Evaluación" for t in tarjetas.values()), "ninguna tarjeta queda en «Evaluación»")

        from app.database import SessionLocal
        from app.models import EvaluacionCandidato, Postulacion
        from app.seed import normalizar_etapas_operativo

        ricardo = tarjetas["Ricardo Jiménez Mora"]["id"]
        with SessionLocal() as db:  # simula una base anterior: la tarjeta seguía en la columna eliminada
            p = db.query(Postulacion).filter(Postulacion.codigo == ricardo).first()
            p.etapa = "Evaluación"
            antes = [(e.codigo, e.estado, e.dictamen) for e in db.query(EvaluacionCandidato).filter(EvaluacionCandidato.postulacion_id == p.id)]
            db.commit()
            movidas = normalizar_etapas_operativo(db)
            p = db.query(Postulacion).filter(Postulacion.codigo == ricardo).first()
            despues = [(e.codigo, e.estado, e.dictamen) for e in db.query(EvaluacionCandidato).filter(EvaluacionCandidato.postulacion_id == p.id)]
            check(movidas == 1 and p.etapa == "Entrevista" and antes == despues and antes,
                  "lo que estaba en «Evaluación» regresa a «Entrevista» con sus evaluaciones y resultados intactos")
            check(normalizar_etapas_operativo(db) == 0, "la normalización es idempotente")

        # ---- 1 y 3. tarjetas y filtros ----
        tarjetas = {t["nombre"]: t for t in c.get("/candidatos", headers=h).json()}
        hugo, patricia, fernando = (tarjetas[n] for n in ("Hugo Sánchez Ibarra", "Patricia León Trejo", "Fernando Ruiz Olvera"))
        res = {r["clave"]: r["texto"] for r in hugo["operativo"]["resultados"]}
        check(res.get("perfil") == "Perfil cumple" and res.get("vehiculo", "").startswith("Vehículo aprobado") and res.get("entrevista") == "Entrevista apto",
              f"tarjeta: Perfil cumple · Vehículo aprobado · Entrevista apto {res}")
        check(any(r["texto"] == "Entrevista no apto" for r in patricia["operativo"]["resultados"]), "tarjeta: Entrevista no apto")
        check({"realizada", "apto"} <= set(hugo["operativo"]["filtros"]) and {"realizada", "no_apto"} <= set(patricia["operativo"]["filtros"]),
              "filtro Realizadas → Aptos / No aptos")
        check("evaluaciones_pendientes" in fernando["operativo"]["filtros"] and fernando["operativo"]["evaluacionesPendientes"] == 1
              and "evaluaciones_pendientes" not in tarjetas["Ricardo Jiménez Mora"]["operativo"]["filtros"],
              "filtro «Evaluaciones pendientes» (con evaluación sin resultado o sin revisión)")
        sin_agendar = tarjetas["Miguel Ángel Rosas"]["operativo"]["filtros"]
        check(sin_agendar == ["sin_agendar"], "se conservan los estados de agenda (Sin agendar)")
        r = c.post(f"/candidatos/{fernando['id']}/operativo/avanzar-contratacion", headers=h)
        check(r.status_code == 409 and "Cleaver" in r.json()["detail"], "«Avanzar a Contratación» bloqueado con una evaluación pendiente")
        r = c.post(f"/candidatos/{patricia['id']}/operativo/avanzar-contratacion", headers=h)
        check(r.status_code == 409 and "No apto" in r.json()["detail"], "«Avanzar a Contratación» bloqueado con la entrevista No apto")

        # ---- 7. liga médica vs. «Capacitación en tienda · Otra» de la v1 ----
        P = hugo["id"]
        c.post(f"/candidatos/{P}/consentimiento", json={"acepta": True, "medio": "verbal", "evidencia": "prueba"}, headers=h)
        with SessionLocal() as db:  # evaluación de la v1 (sesión con cupo) en la MISMA postulación
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            leg = EvaluacionCandidato(codigo="TMP", cuenta_id=p.cuenta_id, postulacion_id=p.id, tipo="otra", nombre="Capacitación en tienda",
                                      sesion_id=1, estado="pendiente", historial=[], evaluador_token="token-legado-v1")
            db.add(leg)
            db.flush()
            leg.codigo = f"EVA-{7000 + leg.id}"
            db.commit()
        medico = c.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "medico", "nombre": "Examen médico de ingreso", "evaluador_tipo": "externo",
                                                                  "evaluador_nombre": "Dra. Prueba", "evaluador_correo": "dra@demo.invalid"}, headers=h).json()
        lista = {e["id"]: e for e in c.get(f"/evaluaciones/postulaciones/{P}", headers=h).json()}
        legado = next(e for e in lista.values() if e["nombre"] == "Capacitación en tienda")
        check(legado["legado"] and legado["ligaEvaluador"] is None, "la «Capacitación en tienda» de la v1 queda como historial SIN liga")
        check(c.get("/evaluaciones/publica/evaluador/token-legado-v1").json()["historica"] is True
              and c.post("/evaluaciones/publica/evaluador/token-legado-v1/resultado", data={"resumen": "x", "evaluador": "Alguien"}).status_code == 409,
              "su liga vieja se muestra como histórica y no recibe resultados")
        tok_cons = lista[medico["id"]]["ligaConsentimiento"].rsplit("/", 1)[1]
        c.post(f"/evaluaciones/publica/consentimiento/{tok_cons}/aceptar", json={"nombre": "Hugo Sánchez Ibarra", "acepto": True})
        m = next(e for e in c.get(f"/evaluaciones/postulaciones/{P}", headers=h).json() if e["id"] == medico["id"])
        tok_med = m["ligaEvaluador"].rsplit("/", 1)[1]
        pub = c.get(f"/evaluaciones/publica/evaluador/{tok_med}").json()
        check(pub["codigo"] == medico["id"] and pub["tipo"] == "medico" and pub["tipoTexto"] == "Médico" and pub["evaluacion"] == "Examen médico de ingreso"
              and pub["candidato"] == "Hugo Sánchez Ibarra" and pub["habilitada"],
              "la liga del médico abre SU evaluación: candidato, nombre y tipo correctos (no «Capacitación en tienda · Otra»)")

        # ---- 8 y 10. texto + archivo desde la liga → evaluación correcta, con nombre y fecha ----
        r = c.post(f"/evaluaciones/publica/evaluador/{tok_med}/resultado",
                   data={"resumen": "Apto para conducir. Presión arterial normal.", "evaluador": "Dra. Prueba", "apto": "apto"},
                   files={"archivo": ("informe.pdf", PDF, "application/pdf")})
        check(r.status_code == 200 and r.json()["yaRegistrado"], "el médico registra texto + PDF desde su liga")
        lista = {e["id"]: e for e in c.get(f"/evaluaciones/postulaciones/{P}", headers=h).json()}  # «reabrir la ficha»
        m = lista[medico["id"]]
        check(m["resultadoResumen"] == "Apto para conducir. Presión arterial normal." and m["tieneInforme"] and m["resultadoCargadoPor"].startswith("Dra. Prueba")
              and m["resultadoCargadoEn"] and m["resultadoOrigen"] == "evaluador" and m["estado"] == "resultado_recibido",
              "texto y archivo quedan en la evaluación correcta, con nombre y fecha, y persisten al reabrir")
        check(not lista[legado["id"]].get("resultadoResumen") and not lista[legado["id"]]["tieneInforme"], "nada se guardó en la evaluación de la v1")

        # ---- 9. visor: inline vs. descarga ----
        ver = c.get(f"/evaluaciones/{medico['id']}/informe", headers=h)
        baja = c.get(f"/evaluaciones/{medico['id']}/informe?descargar=true", headers=h)
        check(ver.status_code == 200 and ver.headers["content-disposition"].startswith("inline") and baja.headers["content-disposition"].startswith("attachment"),
              "«Ver informe» se sirve inline (visor interno) y «Descargar» como adjunto")

        # captura vacía usada como prueba
        psico = c.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "psicometrica", "nombre": "Cleaver"}, headers=h).json()
        r = c.post(f"/evaluaciones/{psico['id']}/resultado", data={"resumen": "Perfil estable."}, files={"archivo": ("captura.png", PNG_VACIO, "image/png")}, headers=h)
        d = r.json()
        check(r.status_code == 200 and d["avisoArchivo"] and not d["tieneInforme"] and d["estado"] == "resultado_recibido" and d["resultadoResumen"] == "Perfil estable.",
              "una captura vacía no se registra como falla: el texto se guarda y solo se avisa")

        # ---- 5. Entrevista humana adicional: agenda + entrevistador + Apto / No apto ----
        eh = c.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "entrevista_humana", "evaluador_tipo": "externo", "evaluador_nombre": "Gerente Regional",
                                                              "cita_fecha": "2030-03-01", "cita_hora": "10:00", "cita_lugar": "Oficina SEZA"}, headers=h).json()
        check(eh["tipo"] == "entrevista_humana" and eh["nombre"] == "Entrevista humana" and eh["evaluador"]["nombre"] == "Gerente Regional" and eh["cita"]
              and [d["valor"] for d in eh["dictamenesPosibles"]] == ["apto", "no_apto"], "Entrevista humana: agenda, entrevistador y dictamen Apto / No apto")
        tok_eh = eh["ligaEvaluador"].rsplit("/", 1)[1]
        check(c.get(f"/evaluaciones/publica/evaluador/{tok_eh}").json()["pideApto"], "la liga del entrevistador pide Apto / No apto")
        check(c.post(f"/evaluaciones/publica/evaluador/{tok_eh}/resultado", data={"resumen": "Bien", "evaluador": "Gerente Regional"}).status_code == 400,
              "sin Apto / No apto no se registra")
        r = c.post(f"/evaluaciones/publica/evaluador/{tok_eh}/resultado", data={"apto": "apto", "resumen": "Buena actitud y conoce la zona.", "evaluador": "Gerente Regional"})
        e2 = next(e for e in c.get(f"/evaluaciones/postulaciones/{P}", headers=h).json() if e["id"] == eh["id"])
        check(r.status_code == 200 and e2["aptoEvaluador"] == "apto" and e2["resultadoResumen"] == "Buena actitud y conoce la zona.",
              "el entrevistador registra Apto + observaciones")

        # ---- 6 y 10. nada de lo anterior movió la tarjeta; solo «Avanzar a Contratación» ----
        check(c.get(f"/candidatos/{P}", headers=h).json()["etapa"] == "Entrevista", "agregar, recibir y registrar evaluaciones NO cambia la etapa")
        r = c.post(f"/candidatos/{P}/operativo/avanzar-contratacion", headers=h)
        check(r.status_code == 409 and "Marcar como revisada" in r.json()["detail"], "con resultados sin revisar, «Avanzar a Contratación» sigue bloqueado")
        panel = c.get(f"/candidatos/{P}/operativo", headers=h).json()
        check(len(panel["requisitosContratacion"]) == 3 and panel["evaluacionesPendientes"] == 3, "el panel lista lo que falta para avanzar")
        for ev_id, dictamen in ((medico["id"], "apto"), (psico["id"], "favorable"), (eh["id"], "apto")):
            r = c.post(f"/evaluaciones/{ev_id}/revisar", json={"dictamen": dictamen, "conclusion": "Revisado por RH"}, headers=h)
            check(r.status_code == 200 and r.json()["estado"] == "revisada" and r.json()["revisadaPor"], f"«Marcar como revisada» {ev_id} con conclusión")
        check(c.get(f"/candidatos/{P}", headers=h).json()["etapa"] == "Entrevista", "revisar tampoco cambia la etapa")
        tarjeta = c.get(f"/candidatos/{P}", headers=h).json()
        check("evaluaciones_pendientes" not in tarjeta["operativo"]["filtros"], "sin pendientes, sale del filtro «Evaluaciones pendientes»")
        r = c.post(f"/candidatos/{P}/operativo/avanzar-contratacion", headers=h)
        check(r.status_code == 200 and r.json()["etapa"] == "Contratación", "«Avanzar a Contratación» (manual) mueve a Contratación")

        # Entrevista humana No apto también frena
        R = tarjetas["Ricardo Jiménez Mora"]["id"]
        c.post(f"/candidatos/{R}/consentimiento", json={"acepta": True, "medio": "verbal", "evidencia": "prueba"}, headers=h)
        eh2 = c.post(f"/evaluaciones/postulaciones/{R}", json={"tipo": "entrevista_humana"}, headers=h).json()
        c.post(f"/evaluaciones/{eh2['id']}/resultado", data={"apto": "no_apto", "resumen": "No conoce la zona"}, headers=h)
        c.post(f"/evaluaciones/{eh2['id']}/revisar", json={"dictamen": "no_apto", "conclusion": "Coincido"}, headers=h)
        r = c.post(f"/candidatos/{R}/operativo/avanzar-contratacion", headers=h)
        check(r.status_code == 409 and "No apto" in r.json()["detail"], "una entrevista humana No apto bloquea «Avanzar a Contratación»")
        check(c.patch(f"/candidatos/{R}/etapa", json={"etapa": "Contratación", "manual": True}, headers=h).status_code == 409,
              "tampoco se puede brincar con «Mover a otra etapa»")


if __name__ == "__main__":
    main()
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
