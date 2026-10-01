"""Regresión de Evaluaciones y verificaciones (2026-09-28). Base desechable, SIN proveedores externos ni claves.

    .venv/Scripts/python.exe scripts/verificar_evaluaciones.py

Catálogo de Pruebas psicométricas, «Agregar evaluación o verificación» sin mover el pipeline, consentimientos
(general y expreso por escrito para el estudio médico), seguimiento Pendiente → En proceso → Resultado recibido →
Revisada / Fallida-Cancelada con motivo, modo Integrada simulado, dictámenes generales y médicos, permisos sobre el
informe médico y la sugerencia por vacante con aviso antes de Onboarding.
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

_dir = tempfile.mkdtemp(prefix="rh_eval_")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_dir) / "eval.db").replace("\\", "/")
for k in ("OPENAI_API_KEY", "WHATSAPP_PROVIDER", "META_WHATSAPP_TOKEN", "ANAM_API_KEY", "RESEND_API_KEY"):
    os.environ[k] = ""
os.environ["ADMIN_PASSWORD"] = "prueba-eval"
os.environ["SEMBRAR_DEMO"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.deps import cuenta_actual, usuario_actual, usuario_decisor, usuario_admin  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Bitacora, Cuenta, EvaluacionCandidato, Usuario, UsuarioCuenta, Vacante  # noqa: E402
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


def como(usuario):
    for dep in (usuario_actual, usuario_decisor):
        app.dependency_overrides[dep] = lambda: usuario


with TestClient(app) as client:
    db = SessionLocal()
    admin = db.query(Usuario).filter(Usuario.rol == "Administrador").first()
    cuenta = Cuenta(nombre="Evaluaciones", nombre_comercial="Empresa EV", razon_social="Empresa EV SA", estado="Activa")
    otra = Cuenta(nombre="Otra", nombre_comercial="Otra", estado="Activa")
    db.add_all([cuenta, otra])
    db.flush()
    db.add(UsuarioCuenta(usuario_id=admin.id, cuenta_id=cuenta.id))
    rh = Usuario(correo="rh.sin.permiso@empresa.mx", nombre="RH Sin Permiso", rol="Usuario", hash_pass="x", activo=True)
    db.add(rh)
    db.flush()
    db.add(UsuarioCuenta(usuario_id=rh.id, cuenta_id=cuenta.id))
    for v in db.query(Vacante).all():
        v.cuenta_id = cuenta.id
    obtener(db).modo_prueba = False
    db.commit()
    como(admin)
    app.dependency_overrides[usuario_admin] = lambda: admin
    app.dependency_overrides[cuenta_actual] = lambda: cuenta

    print("\n--- 1. Catálogo: Pruebas psicométricas ---")
    r = client.post("/evaluaciones/pruebas", json={"clave": "PSI-CLEAVER", "nombre": "Cleaver", "descripcion": "Estilo de comportamiento",
                                                     "puestos": ["Chofer repartidor", " "], "modo": "integrada", "proveedor": "Psicometrix", "id_proveedor": "clv-01"})
    check(r.status_code == 201 and r.json()["modo"] == "integrada" and r.json()["puestos"] == ["Chofer repartidor"] and r.json()["activa"],
          "alta con identificador, nombre, descripción, puestos, modo, proveedor, id en proveedor y estado")
    CLEAVER = r.json()["id"]
    check(client.post("/evaluaciones/pruebas", json={"clave": "psi-cleaver", "nombre": "Otra"}).status_code == 409, "el identificador interno no se repite")
    check(client.post("/evaluaciones/pruebas", json={"clave": "X", "nombre": "X", "modo": "enlace"}).status_code == 400, "«Enlace externo» exige la liga")
    check(client.post("/evaluaciones/pruebas", json={"clave": "Y", "nombre": "Y", "modo": "integrada"}).status_code == 400, "«Integrada» exige proveedor")
    check(client.post("/evaluaciones/pruebas", json={"clave": "Z", "nombre": "Z", "modo": "telepatia"}).status_code == 400, "modo inválido → 400")
    r = client.post("/evaluaciones/pruebas", json={"clave": "PSI-TERMAN", "nombre": "Terman", "modo": "enlace", "url": "https://pruebas.example/terman"})
    TERMAN = r.json()["id"]
    r = client.post("/evaluaciones/pruebas", json={"clave": "PSI-VIEJA", "nombre": "Vieja", "modo": "manual"})
    VIEJA = r.json()["id"]
    lista = client.get("/evaluaciones/pruebas", params={"puesto": "chofer REPARTIDOR"}).json()
    check(lista[0]["nombre"] == "Cleaver" and lista[0]["sugerida"], "con puesto, las sugeridas para ese puesto van primero")
    r = client.delete(f"/evaluaciones/pruebas/{VIEJA}")
    check(r.json()["activa"] is False and all(x["id"] != VIEJA for x in client.get("/evaluaciones/pruebas").json()), "«Eliminar» = Inactiva (sale del listado)")
    check(any(x["id"] == VIEJA for x in client.get("/evaluaciones/pruebas", params={"incluir_inactivas": True}).json()), "…pero sigue existiendo")
    check(client.patch(f"/evaluaciones/pruebas/{TERMAN}", json={"descripcion": "Inteligencia general"}).json()["descripcion"] == "Inteligencia general", "se edita")
    app.dependency_overrides[cuenta_actual] = lambda: otra
    check(client.patch(f"/evaluaciones/pruebas/{TERMAN}", json={"nombre": "x"}).status_code == 404, "otra Cuenta no la ve (404)")
    app.dependency_overrides[cuenta_actual] = lambda: cuenta

    print("\n--- 2. Agregar evaluación o verificación (sin mover el pipeline) ---")
    vac = client.get("/vacantes").json()[0]
    r = client.post("/candidatos", json={"nombre": "Carla Méndez", "telefono": "5512121212", "correo": "carla@correo.mx", "vacante": vac["id"], "consentimiento": True, "fuente": "RH"})
    P = r.json()["id"]
    client.patch(f"/candidatos/{P}/etapa", json={"etapa": "Evaluación", "manual": True})
    check(client.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "horoscopo"}).status_code == 400, "tipo inválido → 400")
    check(client.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "psicometrica"}).status_code == 400, "psicométrica exige una prueba del catálogo")
    check(client.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "psicometrica", "prueba_id": VIEJA}).status_code == 409, "…y activa")
    r = client.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "psicometrica", "prueba_id": CLEAVER})
    PSI = r.json()
    check(r.status_code == 201 and PSI["nombre"] == "Cleaver" and PSI["modo"] == "integrada" and PSI["proveedor"] == "Psicometrix",
          "la psicométrica toma nombre, modo y proveedor del catálogo")
    check(PSI["estado"] == "pendiente" and PSI["pasoIntegrada"] == "asignada", "con consentimiento de privacidad nace Pendiente (Integrada: Asignada)")
    tipos = {}
    for tipo in ("tecnica", "referencias", "socioeconomico", "otra"):
        tipos[tipo] = client.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": tipo}).json()
    check([tipos[t]["tipoTexto"] for t in tipos] == ["Técnica o caso práctico", "Referencias", "Socioeconómico", "Otra"], "los seis tipos del menú")
    check(client.get(f"/candidatos/{P}").json()["etapa"] == "Evaluación", "agregar evaluaciones NO mueve la columna del pipeline")

    print("\n--- 3. Consentimiento general antes de enviar ---")
    r = client.post("/candidatos", json={"nombre": "Sin Consentimiento", "telefono": "5534343434", "vacante": vac["id"], "consentimiento": False, "fuente": "RH"})
    P2 = r.json()["id"]
    r = client.post(f"/evaluaciones/postulaciones/{P2}", json={"tipo": "referencias"})
    SIN = r.json()
    check(SIN["estado"] == "en_espera_consentimiento" and SIN["estadoTexto"] == "En espera de consentimiento", "sin consentimiento: «En espera de consentimiento»")
    r = client.post(f"/evaluaciones/{SIN['id']}/enviar")
    check(r.status_code == 409 and "consentimiento" in r.json()["detail"].lower(), "…y el envío queda bloqueado")
    client.post(f"/candidatos/{P2}/consentimiento", json={"acepta": True, "medio": "escrito"})
    check(client.get(f"/evaluaciones/postulaciones/{P2}").json()[0]["estado"] == "pendiente", "al registrar el consentimiento pasa a Pendiente")

    print("\n--- 4. Estudio médico: consentimiento expreso por escrito (electrónico) ---")
    r = client.post(f"/evaluaciones/postulaciones/{P}", json={"tipo": "medico", "nombre": "Examen médico de ingreso"})
    MED = r.json()
    check(MED["estado"] == "en_espera_consentimiento" and MED["requiereConsentimientoExpreso"] and MED["ligaConsentimiento"],
          "el médico nace «En espera de consentimiento» aunque haya consentimiento general, con liga de aceptación")
    check(client.post(f"/evaluaciones/{MED['id']}/enviar").status_code == 409, "sin consentimiento expreso no se envía")
    check(client.post(f"/evaluaciones/{MED['id']}/resultado", data={"resumen": "x"}).status_code == 409, "…ni se carga resultado")
    token = MED["ligaConsentimiento"].rsplit("/", 1)[-1]
    r = client.post(f"/evaluaciones/{MED['id']}/consentimiento/enviar")
    check(r.status_code == 200 and {x["canal"] for x in r.json()["resultados"]} == {"whatsapp", "correo"}, "RH manda la liga por WhatsApp y correo (resultado visible)")
    pub = client.get(f"/evaluaciones/publica/consentimiento/{token}").json()
    check("Carla Méndez" in pub["texto"] and "datos personales sensibles" in pub["texto"] and not pub["aceptado"], "la persona lee el texto con su nombre")
    check(client.post(f"/evaluaciones/publica/consentimiento/{token}/aceptar", json={"nombre": "Carla Méndez"}).status_code == 400, "sin marcar «Acepto» no cuenta")
    check(client.post(f"/evaluaciones/publica/consentimiento/{token}/aceptar", json={"nombre": "CM", "acepto": True}).status_code == 400, "exige el nombre completo como firma")
    r = client.post(f"/evaluaciones/publica/consentimiento/{token}/aceptar", json={"nombre": "Carla Méndez Ruiz", "acepto": True}, headers={"user-agent": "PruebaNavegador/1.0"})
    check(r.status_code == 200 and r.json()["estado"] == "pendiente", "aceptado → Pendiente")
    db.expire_all()
    ev = db.query(EvaluacionCandidato).filter(EvaluacionCandidato.codigo == MED["id"]).one()
    check(ev.consentimiento_texto.startswith("Yo, Carla Méndez") and ev.consentimiento_aceptado_en is not None, "se guarda el texto EXACTO aceptado y la fecha")
    evid = ev.consentimiento_evidencia
    check(evid["nombre_escrito"] == "Carla Méndez Ruiz" and evid["navegador"] == "PruebaNavegador/1.0" and len(evid["huella_sha256"]) == 64 and evid["medio"] == "electronico",
          "evidencia: nombre escrito, navegador, IP y huella SHA-256")
    check(db.query(Bitacora).filter(Bitacora.accion == "consentimiento_medico_otorgado").count() == 1, "queda en la bitácora hash-encadenada")
    check(client.post(f"/evaluaciones/publica/consentimiento/{token}/aceptar", json={"nombre": "Carla Méndez", "acepto": True}).status_code == 409, "no se acepta dos veces")

    print("\n--- 5. Modo Integrada simulado ---")
    r = client.post(f"/evaluaciones/{PSI['id']}/enviar")
    check(r.json()["pasoIntegrada"] == "enviada" and r.json()["estado"] == "en_proceso", "Asignada → Enviada (En proceso)")
    pasos = []
    for _ in range(3):
        r = client.post(f"/evaluaciones/{PSI['id']}/integracion/avanzar")
        pasos.append((r.json()["pasoIntegrada"], r.json()["estado"]))
    check(pasos == [("iniciada", "en_proceso"), ("completada", "en_proceso"), ("resultado_recibido", "resultado_recibido")],
          f"Enviada → Iniciada → Completada → Resultado recibido ({pasos})")
    check(client.post(f"/evaluaciones/{PSI['id']}/integracion/avanzar").status_code == 409, "no avanza más allá del resultado")
    check(client.post(f"/evaluaciones/{tipos['tecnica']['id']}/integracion/avanzar").status_code == 409, "solo el modo Integrada avanza por pasos")

    print("\n--- 6. Resultado manual y revisión general ---")
    check(client.post(f"/evaluaciones/{PSI['id']}/revisar", json={"dictamen": "apto"}).status_code == 400, "un dictamen médico no sirve para una prueba general")
    r = client.post(f"/evaluaciones/{PSI['id']}/revisar", json={"dictamen": "favorable", "comentario": "Perfil adecuado"})
    check(r.json()["estado"] == "revisada" and r.json()["dictamenTexto"] == "Favorable" and r.json()["revisadaPor"] == admin.nombre, "Revisada: Favorable, con quién")
    check(client.post(f"/evaluaciones/{PSI['id']}/revisar", json={"dictamen": "favorable"}).status_code == 409, "no se revisa dos veces")
    TEC = tipos["tecnica"]["id"]
    check(client.post(f"/evaluaciones/{TEC}/revisar", json={"dictamen": "favorable"}).status_code == 409, "no se revisa sin resultado")
    client.post(f"/evaluaciones/{TEC}/enviar")
    check(client.post(f"/evaluaciones/{TEC}/resultado", data={"resumen": ""}).status_code == 400, "resultado vacío → 400")
    r = client.post(f"/evaluaciones/{TEC}/resultado", data={"resumen": "Resolvió 4 de 5 casos"}, files={"archivo": ("caso.pdf", PDF_MIN, "application/pdf")})
    check(r.json()["estado"] == "resultado_recibido" and r.json()["tieneInforme"] and r.json()["resultadoCargadoPor"] == admin.nombre and r.json()["resultadoCargadoEn"],
          "informe adjunto manualmente: quién lo cargó y cuándo")
    r = client.post(f"/evaluaciones/{TEC}/revisar", json={"dictamen": "con_observaciones"})
    check(r.json()["dictamenTexto"] == "Con observaciones", "Revisada: Con observaciones")
    check(client.get(f"/evaluaciones/{TEC}/informe").status_code == 200, "el informe general se descarga")

    print("\n--- 7. Estudio médico: permisos sobre el informe ---")
    client.post(f"/evaluaciones/{MED['id']}/enviar")
    como(rh)
    check(client.post(f"/evaluaciones/{MED['id']}/resultado", data={"resumen": "x"}).status_code == 403, "sin permiso no se carga el informe médico")
    como(admin)
    r = client.post(f"/evaluaciones/{MED['id']}/resultado", data={"resumen": "Hipertensión controlada", "apto": "apto_con_restricciones"}, files={"archivo": ("medico.pdf", PDF_MIN, "application/pdf")})
    check(r.status_code == 200 and r.json()["resultadoResumen"] == "Hipertensión controlada", "con permiso (Administrador) se carga y se ve completo")
    check(client.post(f"/evaluaciones/{MED['id']}/revisar", json={"dictamen": "favorable"}).status_code == 400, "el médico solo acepta Apto / Apto con restricciones / No apto")
    como(rh)
    check(client.post(f"/evaluaciones/{MED['id']}/revisar", json={"dictamen": "apto"}).status_code == 403, "sin permiso no se transcribe el dictamen médico")
    como(admin)
    client.post(f"/evaluaciones/{MED['id']}/revisar", json={"dictamen": "apto_con_restricciones", "comentario": "Evitar cargas mayores a 25 kg"})
    como(rh)
    vista = next(x for x in client.get(f"/evaluaciones/postulaciones/{P}").json() if x["id"] == MED["id"])
    check(vista["informeRestringido"] and "resultadoResumen" not in vista and "comentarioRevision" not in vista and "nombreArchivo" not in vista,
          "sin permiso NO viaja el informe (ni resumen, ni comentario, ni archivo)")
    check(vista["estadoTexto"] == "Revisada" and vista["dictamenTexto"] == "Apto con restricciones", "…pero sí el estado y el dictamen")
    check(client.get(f"/evaluaciones/{MED['id']}/informe").status_code == 403, "descargar el informe médico sin permiso → 403")
    tec_vista = next(x for x in client.get(f"/evaluaciones/postulaciones/{P}").json() if x["id"] == TEC)
    check(not tec_vista["informeRestringido"] and tec_vista["resultadoResumen"], "la restricción es solo para lo médico")
    como(admin)
    r = client.patch(f"/auth/usuarios/{rh.id}", json={"acceso_informes_medicos": True})
    check(r.status_code == 200 and r.json()["puedeVerInformeMedico"], "un Administrador otorga el permiso de informes médicos")
    db.expire_all()
    rh = db.get(Usuario, rh.id)
    como(rh)
    check(client.get(f"/evaluaciones/{MED['id']}/informe").status_code == 200, "con el permiso ya lo descarga (y queda en bitácora)")
    como(admin)

    print("\n--- 8. Fallida / Cancelada ---")
    REF = tipos["referencias"]["id"]
    check(client.post(f"/evaluaciones/{REF}/cancelar", json={}).status_code == 400, "Fallida/Cancelada exige motivo")
    r = client.post(f"/evaluaciones/{REF}/cancelar", json={"motivo": "Las referencias no respondieron"})
    check(r.json()["estado"] == "fallida" and r.json()["motivoFallida"] and r.json()["estadoTexto"] == "Fallida/Cancelada", "Fallida/Cancelada con motivo")
    check(client.post(f"/evaluaciones/{REF}/enviar").status_code == 409, "una fallida ya no se mueve")
    check(len(r.json()["historial"]) >= 2, "cada cambio queda en el historial de la evaluación")
    check(client.get(f"/candidatos/{P}").json()["etapa"] == "Evaluación", "nada de lo anterior movió el pipeline")

    print("\n--- 9. Vacante: sugerencias y «Avisar antes de Onboarding» ---")
    r = client.patch(f"/vacantes/{vac['id']}", json={
        "evaluaciones_sugeridas": [{"tipo": "psicometrica", "prueba_id": CLEAVER}, {"tipo": "medico"}, {"tipo": "referencias"}, {"tipo": "tarot"}, {"tipo": "medico"}],
        "avisar_evaluaciones_antes_onboarding": True,
    })
    v2 = r.json()
    check(r.status_code == 200 and [s["tipo"] for s in v2["evaluacionesSugeridas"]] == ["psicometrica", "medico", "referencias"] and v2["evaluacionesSugeridas"][0]["nombre"] == "Cleaver",
          "sugerencias limpias (sin tipos inválidos ni duplicados) con el nombre del catálogo")
    check(v2["avisarEvaluacionesAntesOnboarding"] is True, "casilla «Avisar antes de Onboarding»")
    r = client.post("/candidatos", json={"nombre": "Diego Onboarding", "telefono": "5556565656", "correo": "diego@correo.mx", "vacante": vac["id"], "consentimiento": True, "fuente": "RH"})
    P3 = r.json()["id"]
    EXP3 = client.patch(f"/candidatos/{P3}/etapa", json={"etapa": "Contratación", "manual": True}).json()["expedienteId"]
    client.post(f"/evaluaciones/postulaciones/{P3}", json={"tipo": "psicometrica", "prueba_id": CLEAVER})
    avisos = client.get(f"/onboarding/expedientes/{EXP3}/resumen").json()["avisosEvaluaciones"]
    check(any("Médico" in a for a in avisos) and any("Referencias" in a for a in avisos) and any("Cleaver" in a and "sin revisar" in a for a in avisos),
          f"el resumen de «Enviar a Onboarding» avisa lo sugerido que falta y lo no revisado ({len(avisos)} avisos)")
    client.patch(f"/vacantes/{vac['id']}", json={"avisar_evaluaciones_antes_onboarding": False})
    check(client.get(f"/onboarding/expedientes/{EXP3}/resumen").json()["avisosEvaluaciones"] == [], "sin la casilla no hay aviso (nunca bloquea)")

    db.close()

print(f"\n🎉 Evaluaciones y verificaciones: {OK} verificaciones OK")
