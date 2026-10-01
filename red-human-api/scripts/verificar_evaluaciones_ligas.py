"""Regresión de Evaluaciones v2 (2026-09-30): ligas universales, evaluador y captura. Base desechable, sin claves.

    .venv/Scripts/python.exe scripts/verificar_evaluaciones_ligas.py

Regla universal de ligas (toda liga existe desde que se crea la evaluación y se ve aunque el envío falle), captura
manual de RH siempre disponible y liga del evaluador que alimentan la MISMA evaluación, médico (consentimiento primero,
luego la liga del médico), psicométrica con nombre de prueba y proveedor sin catálogo y estados Pendiente → Enviada →
En curso → Resultado recibido → Revisada, socioeconómico con evaluador interno/externo y cita opcional, «Marcar como
revisada» con usuario, fecha y conclusión, y que recibir un resultado NUNCA mueve al candidato de etapa.
"""

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_dir = tempfile.mkdtemp(prefix="rh_eval_ligas_")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_dir) / "eval.db").replace("\\", "/")
for k in ("OPENAI_API_KEY", "WHATSAPP_PROVIDER", "META_WHATSAPP_TOKEN", "ANAM_API_KEY", "RESEND_API_KEY", "TELEGRAM_BOT_TOKEN"):
    os.environ[k] = ""
os.environ["ADMIN_PASSWORD"] = "prueba-eval"
os.environ["SEMBRAR_DEMO"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.deps import cuenta_actual, usuario_actual, usuario_admin, usuario_decisor  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Cuenta, Usuario, UsuarioCuenta, Vacante  # noqa: E402
from app.services.configuracion import obtener  # noqa: E402

OK = 0
PDF_MIN = b"%PDF-1.4\n" + b"%" * 600 + b"\n%%EOF\n"


def check(cond, msg):
    global OK
    if not cond:
        print(f"❌ FALLO: {msg}")
        sys.exit(1)
    OK += 1
    print(f"✅ {msg}")


with TestClient(app) as client:
    db = SessionLocal()
    admin = db.query(Usuario).filter(Usuario.rol == "Administrador").first()
    cuenta = Cuenta(nombre="Evaluaciones v2", nombre_comercial="Empresa EV2", razon_social="Empresa EV2 SA", estado="Activa")
    db.add(cuenta)
    db.flush()
    db.add(UsuarioCuenta(usuario_id=admin.id, cuenta_id=cuenta.id))
    medica = Usuario(correo="dra.salud@empresa.mx", nombre="Dra. Salud Interna", rol="Usuario", hash_pass="x", activo=True, telefono="5590909090")
    db.add(medica)
    db.flush()
    db.add(UsuarioCuenta(usuario_id=medica.id, cuenta_id=cuenta.id))
    for v in db.query(Vacante).all():
        v.cuenta_id = cuenta.id
    obtener(db).modo_prueba = False
    db.commit()
    for dep in (usuario_actual, usuario_decisor, usuario_admin):
        app.dependency_overrides[dep] = lambda: admin
    app.dependency_overrides[cuenta_actual] = lambda: cuenta

    vac = client.get("/vacantes").json()[0]
    P = client.post("/candidatos", json={"nombre": "Laura Pérez", "telefono": "5511223344", "correo": "laura@correo.mx", "vacante": vac["id"],
                                         "consentimiento": True, "fuente": "RH"}).json()["id"]
    client.patch(f"/candidatos/{P}/etapa", json={"etapa": "Evaluación", "manual": True})

    print("\n--- 1. Psicométrica sin catálogo: nombre de prueba + proveedor; estados ---")
    r = client.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "psicometrica", "nombre": "Cleaver", "proveedor": "Psico SA", "modo": "enlace",
                                                             "url": "https://pruebas.example/cleaver"})
    PSI = r.json()
    check(r.status_code == 201 and PSI["nombre"] == "Cleaver" and PSI["proveedor"] == "Psico SA", "psicométrica con «Nombre de prueba» y «Proveedor» sin catálogo")
    check(PSI["estadoTexto"] == "Pendiente" and PSI["ligaEvaluador"] and PSI["url"], "nace con su liga de evaluador y su enlace externo")
    r = client.post(f"/evaluaciones/{PSI['id']}/enlace/enviar")
    check(r.status_code == 200 and r.json()["estadoTexto"] == "Enviada" and r.json()["envios"][0]["enviado"] is False,
          "enviar el enlace al candidato → «Enviada»; el envío fallido se registra sin bloquear")
    r = client.post(f"/evaluaciones/{PSI['id']}/en-curso")
    check(r.json()["estadoTexto"] == "En curso", "«En curso» cuando el candidato empezó")
    tok = PSI["ligaEvaluador"].rsplit("/", 1)[1]
    r = client.post(f"/evaluaciones/publica/evaluador/{tok}/resultado", data={"resumen": "Perfil dominante-estable", "evaluador": "Psico SA"},
                    files={"archivo": ("informe.pdf", PDF_MIN, "application/pdf")})
    check(r.status_code == 200 and r.json()["yaRegistrado"], "el proveedor registra el resultado en su liga")
    vista = next(x for x in client.get(f"/evaluaciones/postulaciones/{P}").json() if x["id"] == PSI["id"])
    check(vista["estadoTexto"] == "Resultado recibido" and vista["resultadoOrigen"] == "evaluador" and vista["tieneInforme"]
          and vista["resultadoCargadoPor"] == "Psico SA (evaluador)", "…y llega a la MISMA evaluación: «Resultado recibido» con su informe")
    check(client.post(f"/evaluaciones/publica/evaluador/{tok}/resultado", data={"resumen": "otro", "evaluador": "Psico SA"}).status_code == 409,
          "la liga no sobreescribe un resultado registrado")
    r = client.post(f"/evaluaciones/{PSI['id']}/revisar", json={"dictamen": "favorable", "conclusion": "Apto para reparto"})
    check(r.json()["estadoTexto"] == "Revisada" and r.json()["revisadaPor"] and r.json()["revisadaEn"] and r.json()["comentarioRevision"] == "Apto para reparto",
          "«Marcar como revisada» guarda usuario, fecha y conclusión")
    check(client.get(f"/candidatos/{P}").json()["etapa"] == "Evaluación", "recibir y revisar un resultado NO mueve al candidato de etapa")

    print("\n--- 2. Médica: consentimiento primero, luego la liga del médico (con captura manual) ---")
    r = client.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "medico", "nombre": "Examen médico", "evaluador_tipo": "externo",
                                                             "evaluador_nombre": "Dr. Ruiz", "evaluador_telefono": "5598765432"})
    MED = r.json()
    # 2026-10-01 (Zeze punto 5): la liga del médico se genera y se comparte al guardar; lo que espera es la CAPTURA
    check(MED["ligaConsentimiento"] and MED["ligaEvaluador"] and MED["ligaEvaluadorHabilitada"] and not MED["capturaHabilitada"]
          and MED["consentimientoEstado"] == "Pendiente",
          "el médico: liga de consentimiento + liga del médico desde el inicio; consentimiento «Pendiente» y captura bloqueada")
    check(client.post(f"/evaluaciones/{MED['id']}/evaluador/enviar").status_code == 200, "la liga del médico se puede mandar sin esperar el consentimiento")
    tok_med = MED["ligaEvaluador"].rsplit("/", 1)[1]
    pub = client.get(f"/evaluaciones/publica/evaluador/{tok_med}").json()
    check(not pub["habilitada"] and pub["consentimiento"] == "Pendiente" and "consentimiento" in pub["motivo"].lower(),
          "la liga del médico muestra «Consentimiento: Pendiente» y explica que falta")
    check(client.post(f"/evaluaciones/publica/evaluador/{tok_med}/resultado", data={"resumen": "x", "evaluador": "Dr. Ruiz"}).status_code == 409,
          "…y no deja registrar antes")
    tok_c = MED["ligaConsentimiento"].rsplit("/", 1)[1]
    client.post(f"/evaluaciones/publica/consentimiento/{tok_c}/aceptar", json={"nombre": "Laura Pérez Gómez", "acepto": True})
    vista = next(x for x in client.get(f"/evaluaciones/postulaciones/{P}").json() if x["id"] == MED["id"])
    check(vista["capturaHabilitada"] and vista["consentimientoEstado"] == "Aceptado" and vista["estado"] == "pendiente",
          "aceptado el consentimiento → se habilita la captura del médico")
    r = client.post(f"/evaluaciones/{MED['id']}/evaluador/enviar")
    check(r.status_code == 200 and r.json()["envios"][0]["destinatario"] == "evaluador" and r.json()["ligaEvaluador"],
          "se manda la liga al médico (el resultado del envío se ve aparte; la liga sigue ahí)")
    check(client.post(f"/evaluaciones/{MED['id']}/resultado", data={"resumen": "Sin dictamen"}).status_code == 400, "el médico exige dictamen (Apto / Apto con restricciones / No apto)")
    r = client.post(f"/evaluaciones/{MED['id']}/resultado", data={"resumen": "Apto sin restricciones", "apto": "apto"})
    check(r.status_code == 200 and r.json()["resultadoOrigen"] == "rh", "captura manual de RH disponible aunque el médico tenga su liga")
    check(client.post(f"/evaluaciones/publica/evaluador/{tok_med}/resultado", data={"resumen": "x", "evaluador": "Dr. Ruiz"}).status_code == 409,
          "las dos vías alimentan la MISMA evaluación (la liga ya no duplica)")

    print("\n--- 3. Socioeconómica: evaluador interno/externo y cita opcional ---")
    r = client.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "socioeconomico"})
    SOC = r.json()
    check(SOC["evaluador"]["nombre"] == "" and SOC["cita"] is None, "sin evaluador ni cita al crearla (opcionales)")
    r = client.patch(f"/evaluaciones/{SOC['id']}/evaluador", json={"evaluador_tipo": "interno", "evaluador_usuario_id": medica.id,
                                                                   "cita_fecha": "2030-03-04", "cita_hora": "11:30", "cita_lugar": "Domicilio del candidato"})
    d = r.json()
    check(d["evaluador"]["tipo"] == "interno" and d["evaluador"]["nombre"] == "Dra. Salud Interna" and d["evaluador"]["telefono"] == "5590909090"
          and d["cita"] and d["citaLugar"] == "Domicilio del candidato", "evaluador interno con sus datos del perfil + cita")
    check(client.patch(f"/evaluaciones/{SOC['id']}/evaluador", json={"evaluador_tipo": "externo"}).status_code == 400, "externo exige nombre")
    r = client.patch(f"/evaluaciones/{SOC['id']}/evaluador", json={"evaluador_tipo": "externo", "evaluador_nombre": "Visitas SA",
                                                                   "evaluador_correo": "visitas@ejemplo.mx"})
    check(r.json()["evaluador"]["tipo"] == "externo" and r.json()["evaluador"]["correo"] == "visitas@ejemplo.mx" and r.json()["cita"] is None,
          "cambio a evaluador externo con sus datos (cita opcional)")
    r = client.post(f"/evaluaciones/{SOC['id']}/evaluador/enviar")
    check(r.status_code == 200 and r.json()["envios"][0]["canal"] == "correo" and r.json()["envios"][0]["enviado"] is False,
          "el correo sin RESEND no sale, pero la liga queda generada y el intento registrado")
    check(client.get(f"/candidatos/{P}").json()["etapa"] == "Evaluación", "nada de esto mueve la etapa")

print(f"\n🎉 Evaluaciones v2 (ligas, evaluador y captura): {OK} verificaciones OK")
