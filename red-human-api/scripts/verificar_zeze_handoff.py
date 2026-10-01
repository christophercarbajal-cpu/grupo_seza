"""Regresión del handoff web → Telegram y de los 8 «Cambios para desarrollo - Zeze» (2026-10-01), base DESECHABLE.

Parte 1 — Handoff: /candidatos/postular devuelve `telegram_onboarding_token` (único por postulación, se reutiliza al
reaplicar); `/start <token>` amarra el chat a ESA postulación y lanza su evaluación (sin pedir el número); el token no
sirve en otro chat; `/start` vacío = menú general; sin teléfono se pide el contacto y al compartirlo arranca sola.
Parte 2 — 1 visor (inline / attachment) · 2 textos «Entrevista / Entrevistador» · 3 y 8 «Pasar a Contratación» con
requisitos · 4 correo independiente, plantilla aprobada de Meta sin texto previo y estados (Pendiente / Enviado /
Entregado / Fallido, acuses de Meta) · 5 liga médica al guardar con consentimiento Pendiente/Aceptado · 6 dictamen del
evaluador (médico / socioeconómico) aparte de RH y «Corregir resultado» → «Pendiente de revisión» sin mover la columna
· 7 resumen de la ficha.

Uso (desde red-human-api/):  python scripts/verificar_zeze_handoff.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
BASE = Path(tempfile.mkdtemp()) / "zeze.db"
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
JPG = b"\xff\xd8\xff\xe0" + b"0" * 2000
SLUG = "chofer-de-reparto-con-unidad-propia-"
R_OK = {"municipio": "Puebla", "jornada": "Sí", "experiencia": "No", "vehiculo_propio": "Sí", "tipo_vehiculo": "Sedán de cuatro puertas",
        "anio_vehiculo": "2019", "taxi": "No", "circulacion": "Sí", "licencia": "Sí", "poliza": "Sí", "android": "Sí"}


def check(cond, nombre):
    print(("✅ " if cond else "❌ ") + nombre)
    if not cond:
        FALLAS.append(nombre)


def update_start(chat_id: int, texto: str, uid: int) -> dict:
    return {"update_id": uid, "message": {"message_id": uid, "chat": {"id": chat_id, "type": "private"},
                                          "from": {"id": chat_id, "is_bot": False, "first_name": "Prueba"}, "text": texto}}


def main():
    with TestClient(app):
        pass
    salida = subprocess.run([sys.executable, str(RAIZ / "scripts" / "cargar_demo_seza.py"), "--ejecutar"],
                            capture_output=True, text=True, encoding="utf-8", env=os.environ)
    check(salida.returncode == 0, "carga del ambiente SEZA")
    if salida.returncode:
        print(salida.stdout[-2000:], salida.stderr[-2000:])
        return

    from app.database import SessionLocal
    from app.models import ChatTelegram, EvaluacionCandidato, Mensaje, Postulacion
    from app.routers import webhooks
    from app.services import telegram

    with TestClient(app) as c:
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        cuentas = c.get("/cuentas").json()
        h = {"X-Cuenta-Id": str(next((x["id"] for x in cuentas if "SEZA" in x.get("nombre", "")), 1))}

        # ================= PARTE 1: handoff web → Telegram =================
        def postular(nombre, tel, correo=""):
            return c.post("/candidatos/postular", data={"vacante": SLUG + "puebla", "nombre": nombre, "telefono": tel, "correo": correo,
                                                        "consentimiento": "true", "respuestas_reglas": json.dumps(R_OK)}).json()

        d = postular("Hand Off", "2225550001", "handoff@demo.invalid")
        tok = d.get("telegram_onboarding_token") or ""
        check(len(tok) >= 20 and telegram.RE_TOKEN_INICIO.match(tok) and d.get("telegramBot") == "GrupoSeza_bot"
              and d.get("telegramLiga") == f"tg://resolve?domain=GrupoSeza_bot&start={tok}",
              "postular devuelve telegram_onboarding_token (válido para /start) y el deep link tg://resolve")
        P = d["postulacion"]
        d2 = postular("Hand Off", "2225550001", "handoff@demo.invalid")
        check(d2["postulacion"] == P and d2["telegram_onboarding_token"] == tok, "reaplicar a la misma vacante reutiliza la postulación y su token")
        otro = postular("Otra Persona", "2225550002")
        check(otro["telegram_onboarding_token"] != tok, "cada postulación tiene su propio token")

        parse = telegram.parsear_update(update_start(111, f"/start {tok}", 1))
        vacio = telegram.parsear_update(update_start(111, "/start", 2))
        check(parse["start_token"] == tok and parse["texto"] == "Hola" and vacio["start_token"] == "" and vacio["texto"] == "Hola",
              "el bot distingue /start <token> de /start vacío")

        enviados = []

        async def chat_falso(chat_id, texto, teclado=None):
            enviados.append((str(chat_id), texto))
            return {"enviado": True}

        with mock.patch.object(telegram, "_enviar_a_chat", side_effect=chat_falso), \
             mock.patch.object(telegram, "pedir_contacto", new=mock.AsyncMock(return_value={"enviado": True})) as pedir:
            r = asyncio.run(webhooks.procesar_update_telegram(update_start(111, f"/start {tok}", 10)))
            check(r.get("accion") == "handoff_evaluacion" and r.get("postulacion") == P and not pedir.called,
                  "/start <token> lanza la evaluación de ESA postulación sin pedir el número")
            with SessionLocal() as db:
                p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
                chat = db.get(ChatTelegram, "111")
                ultimo = db.query(Mensaje).filter(Mensaje.postulacion_id == p.id, Mensaje.rol == "assistant").order_by(Mensaje.id.desc()).first()
                check(p.telegram_chat_id == "111" and p.telegram_vinculado_en and chat and chat.telefono == "2225550001"
                      and p.candidato.postulacion_conversacion_id == p.id, "el chat queda amarrado a la postulación y al teléfono de la ficha")
                check(ultimo is not None and "*1/" in ultimo.texto and "Gracias" not in ultimo.texto,
                      "tras el saludo arranca la primera pregunta del agente (no el cierre)")
            r = asyncio.run(webhooks.procesar_update_telegram(update_start(222, f"/start {tok}", 11)))
            check(r.get("accion") == "token_en_otro_chat" and any("otra cuenta de Telegram" in t for ch, t in enviados if ch == "222"),
                  "el mismo token en otro chat se rechaza")
            r = asyncio.run(webhooks.procesar_update_telegram(update_start(111, "/start", 12)))
            check(r.get("accion") != "handoff_evaluacion", "/start vacío no lanza el handoff (va al menú general)")
            r = asyncio.run(webhooks.procesar_update_telegram(update_start(333, "/start tokeninexistente123", 13)))
            check(r.get("accion") == "token_invalido" and any("ya no está vigente" in t for ch, t in enviados if ch == "333"),
                  "token desconocido → aviso y menú general (pide el número si el chat es nuevo)")
            # sin teléfono: pide el contacto y al compartirlo arranca sola
            sin_tel = postular("Sin Telefono", "", "sintel@demo.invalid")
            tok3 = sin_tel["telegram_onboarding_token"]
            r = asyncio.run(webhooks.procesar_update_telegram(update_start(444, f"/start {tok3}", 14)))
            check(r.get("accion") == "handoff_sin_telefono" and pedir.called, "sin teléfono en la ficha: el bot pide compartir el número")
            contacto = {"update_id": 15, "message": {"message_id": 15, "chat": {"id": 444, "type": "private"}, "from": {"id": 444, "is_bot": False, "first_name": "S"},
                                                     "contact": {"phone_number": "+52 222 555 0003", "user_id": 444}}}
            with mock.patch.object(telegram, "confirmar_contacto", new=mock.AsyncMock(return_value={})):
                r = asyncio.run(webhooks.procesar_update_telegram(contacto))
            with SessionLocal() as db:
                p3 = db.query(Postulacion).filter(Postulacion.codigo == sin_tel["postulacion"]).first()
                check(r.get("accion") == "handoff_evaluacion" and p3.candidato.telefono == "2225550003",
                      "al compartir su número se guarda en la ficha y la evaluación arranca sola")

        # ================= PARTE 2 =================
        tarjetas = {t["nombre"]: t for t in c.get("/candidatos", headers=h).json()}
        hugo = tarjetas["Hugo Sánchez Ibarra"]["id"]
        c.post(f"/candidatos/{hugo}/consentimiento", json={"acepta": True, "medio": "verbal", "evidencia": "prueba"}, headers=h)

        # 1. visor: inline / attachment
        panel = c.get(f"/candidatos/{hugo}/operativo", headers=h).json()
        exp_id = panel["expediente"]["id"]
        doc = "Póliza de seguro vigente"
        url = f"/contratacion/expedientes/{exp_id}/documentos/{doc}/archivo"
        ver, baja = c.get(url, headers=h), c.get(url + "?descargar=true", headers=h)
        check(ver.status_code == 200 and ver.headers["content-disposition"].startswith("inline") and baja.headers["content-disposition"].startswith("attachment"),
              "1 · documento del expediente: «Ver» inline (visor) y «Descargar» como adjunto")
        foto = c.get(f"/candidatos/{hugo}/vehiculo/foto/frente", headers=h)
        foto_d = c.get(f"/candidatos/{hugo}/vehiculo/foto/frente?descargar=true", headers=h)
        check(foto.status_code == 200 and foto.headers["content-disposition"].startswith("inline") and foto_d.headers["content-disposition"].startswith("attachment"),
              "1 · foto del vehículo: inline / descarga")

        # 2. textos «Entrevista / Entrevistador»
        from app.services import flujo_operativo as flujo

        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == hugo).first()
            eh = flujo.entrevista_actual(p)
            cita, aviso = flujo.texto_cita(p, eh, db), flujo.texto_capacitador(p, eh, db)
            check("entrevista" in cita and "capacitaci" not in cita.lower() and "entrevista" in aviso and "capacitaci" not in aviso.lower(),
                  "2 · la cita y el aviso dicen «entrevista» (no «capacitación en tienda»)")
        pub = c.get(f"/entrevista-humana/publica/{panel['entrevista']['ligaCapacitador'].rsplit('/', 1)[1]}").json()
        check(pub.get("tipo") == "capacitacion", "2 · la liga del entrevistador sigue funcionando (mismo contrato de API)")

        # 4. notificaciones: correo independiente + estados + acuses de Meta + plantilla aprobada
        miguel = tarjetas["Miguel Ángel Rosas"]["id"]
        with SessionLocal() as db:
            pm = db.query(Postulacion).filter(Postulacion.codigo == miguel).first()
            pm.candidato.correo = "miguel@demo.invalid"
            db.commit()
        cita_d = {"tienda": "Tienda prueba", "direccion": "Av. 1", "fecha": "2030-01-15", "hora": "09:00", "capacitador_tipo": "externo",
                  "capacitador_nombre": "Gerente", "capacitador_telefono": "5511112222"}
        r = c.post(f"/candidatos/{miguel}/operativo/entrevista", json=cita_d, headers=h).json()
        filas = [x for x in r["entrevista"]["envios"] if x["destinatario"] == "candidato" and x["canal"] in ("mensaje", "correo")]
        canales = {x["canal"]: x for x in filas}
        check({"mensaje", "correo"} <= set(canales) and all(x["estado"] in ("pendiente", "enviado", "entregado", "fallido") and x["estadoTexto"] for x in filas),
              "4 · la cita sale por mensaje Y por correo, cada uno con su estado visible")
        check(canales["correo"]["estado"] == "fallido" and "RESEND" in canales["correo"]["detalle"].upper() and canales["mensaje"]["estado"] in ("pendiente", "fallido"),
              "4 · el correo se intenta aunque el mensaje no salga (sin teléfono → mensaje «Pendiente»; sin Resend → correo «Fallido» con el motivo)")
        with SessionLocal() as db:  # un envío aceptado por Meta (wamid) → el acuse lo vuelve «Entregado»
            pm = db.query(Postulacion).filter(Postulacion.codigo == miguel).first()
            eh = flujo.entrevista_actual(pm)
            eh.envios = [*eh.envios, {"destinatario": "candidato", "canal": "mensaje", "enviado": True, "estado": "enviado", "wa_id": "wamid.PRUEBA1",
                                      "detalle": "", "fecha": "2030-01-01T00:00:00+00:00"}]
            db.commit()
        acuse = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {"statuses": [
            {"id": "wamid.PRUEBA1", "status": "delivered"}]}}]}]}
        check(c.post("/webhooks/whatsapp", json=acuse).status_code == 200, "4 · el webhook acepta los acuses de entrega de Meta")
        env = c.get(f"/candidatos/{miguel}/operativo", headers=h).json()["entrevista"]["envios"]
        check(next(x for x in env if x.get("wa_id") == "wamid.PRUEBA1")["estado"] == "entregado", "4 · acuse «delivered» → «Entregado»")
        c.post("/webhooks/whatsapp", json={**acuse, "entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.PRUEBA1", "status": "sent"}]}}]}]})
        env = c.get(f"/candidatos/{miguel}/operativo", headers=h).json()["entrevista"]["envios"]
        check(next(x for x in env if x.get("wa_id") == "wamid.PRUEBA1")["estado"] == "entregado", "4 · un «sent» tardío no baja el estado")
        r = c.post(f"/candidatos/{miguel}/operativo/entrevista/reenviar", json={"destinatario": "candidato"}, headers=h).json()
        check({x["canal"] for x in r["envios"]} == {"mensaje", "correo"}, "4 · «Reenviar» manda de nuevo por ambos canales")

        from app.config import settings
        from app.services import whatsapp

        cuerpos = []

        async def meta_falso(cuerpo):
            cuerpos.append(cuerpo)
            return {"enviado": True, "proveedor": "meta", "detalle": 200, "wa_id": "wamid.X"}

        with mock.patch.object(settings, "whatsapp_provider", "meta"), mock.patch.object(settings, "telegram_bot_token", ""), \
             mock.patch.object(settings, "meta_plantilla_aviso", "aviso_general"), mock.patch.object(whatsapp, "_meta_post", side_effect=meta_falso):
            res = asyncio.run(whatsapp.enviar_notificacion("2225550009", "Hola, te citamos"))
            res2 = asyncio.run(whatsapp.enviar_notificacion("2225550009", "Hola", "cita_entrevista", ["Ana", "15/01 09:00", "Tienda", "Gerente"]))
        check(res["enviado"] and len(cuerpos) == 2 and cuerpos[0]["type"] == "template" and cuerpos[0]["template"]["name"] == "aviso_general"
              and cuerpos[1]["template"]["name"] == "cita_entrevista" and len(cuerpos[1]["template"]["components"][0]["parameters"]) == 4,
              "4 · con Meta el aviso va DIRECTO por plantilla aprobada (sin exigir que la persona escriba primero)")

        # 5. liga médica al guardar + consentimiento Pendiente / Aceptado
        med = c.post(f"/evaluaciones/postulaciones/{hugo}", json={"tipo": "medico", "nombre": "Examen médico", "evaluador_tipo": "externo",
                                                                   "evaluador_nombre": "Dra. Uno", "evaluador_correo": "dra@demo.invalid"}, headers=h).json()
        check(med["ligaEvaluador"] and med["ligaEvaluadorHabilitada"] and med["consentimientoEstado"] == "Pendiente" and med["capturaHabilitada"] is False,
              "5 · la liga del médico existe al guardar; consentimiento «Pendiente» y captura bloqueada")
        tok_med = med["ligaEvaluador"].rsplit("/", 1)[1]
        pubm = c.get(f"/evaluaciones/publica/evaluador/{tok_med}").json()
        check(pubm["consentimiento"] == "Pendiente" and not pubm["habilitada"]
              and c.post(f"/evaluaciones/publica/evaluador/{tok_med}/resultado", data={"resumen": "x", "evaluador": "Dra. Uno", "apto": "apto"}).status_code == 409,
              "5 · la liga abre y muestra «Pendiente»; la captura de datos médicos está bloqueada")
        check(c.post(f"/evaluaciones/{med['id']}/evaluador/enviar", headers=h).status_code == 200, "5 · la liga del médico se envía sin esperar el consentimiento")
        tok_c = med["ligaConsentimiento"].rsplit("/", 1)[1]
        c.post(f"/evaluaciones/publica/consentimiento/{tok_c}/aceptar", json={"nombre": "Hugo Sánchez Ibarra", "acepto": True})
        check(c.get(f"/evaluaciones/publica/evaluador/{tok_med}").json()["consentimiento"] == "Aceptado", "5 · aceptado el consentimiento → «Aceptado»")

        # 6. dictamen del evaluador aparte de RH + «Corregir resultado»
        check([d["valor"] for d in pubm["dictamenesEvaluador"]] == ["apto", "apto_con_restricciones", "no_apto"], "6 · el médico dictamina Apto / Apto con restricciones / No apto")
        check(c.post(f"/evaluaciones/publica/evaluador/{tok_med}/resultado", data={"resumen": "x", "evaluador": "Dra. Uno"}).status_code == 400,
              "6 · sin dictamen no se registra")
        c.post(f"/evaluaciones/publica/evaluador/{tok_med}/resultado", data={"resumen": "Hipertensión leve", "evaluador": "Dra. Uno", "apto": "apto_con_restricciones"})
        soc = c.post(f"/evaluaciones/postulaciones/{hugo}", json={"tipo": "socioeconomico"}, headers=h).json()
        check([d["valor"] for d in soc["dictamenesEvaluador"]] == ["favorable", "favorable_observaciones", "no_favorable"],
              "6 · el socioeconómico dictamina Favorable / Favorable con observaciones / No favorable")
        r = c.post(f"/evaluaciones/{soc['id']}/resultado", data={"resumen": "Vivienda propia", "apto": "favorable_observaciones"}, headers=h).json()
        check(r["dictamenEvaluadorTexto"] == "Favorable con observaciones" and r["estado"] == "resultado_recibido", "6 · el dictamen del evaluador se guarda aparte")
        r = c.post(f"/evaluaciones/{soc['id']}/revisar", json={"dictamen": "favorable", "conclusion": "OK"}, headers=h).json()
        check(r["estado"] == "revisada" and r["dictamen"] == "favorable" and r["dictamenEvaluador"] == "favorable_observaciones",
              "6 · la revisión de RH tiene su propio dictamen (separado del evaluador)")
        etapa_antes = c.get(f"/candidatos/{hugo}", headers=h).json()["etapa"]
        r = c.post(f"/evaluaciones/{soc['id']}/resultado", data={"resumen": "Vivienda rentada", "apto": "no_favorable", "corregir": "true",
                                                                 "motivo": "Dato equivocado"}, headers=h).json()
        check(r["estado"] == "resultado_recibido" and r["estadoTexto"] == "Pendiente de revisión" and len(r["correcciones"]) == 1
              and r["correcciones"][0]["antes"]["dictamenEvaluador"] == "favorable_observaciones" and r["correcciones"][0]["motivo"] == "Dato equivocado"
              and not r["dictamen"], "6 · RH «Corregir resultado»: historial (antes/después) y regresa a «Pendiente de revisión»")
        m = next(x for x in c.get(f"/evaluaciones/postulaciones/{hugo}", headers=h).json() if x["id"] == med["id"])
        r = c.post(f"/evaluaciones/publica/evaluador/{tok_med}/resultado", data={"resumen": "Sin hallazgos", "evaluador": "Dra. Uno", "apto": "apto",
                                                                              "corregir": "true", "motivo": "Resultado de laboratorio"})
        m2 = next(x for x in c.get(f"/evaluaciones/postulaciones/{hugo}", headers=h).json() if x["id"] == med["id"])
        check(r.status_code == 200 and m2["dictamenEvaluador"] == "apto" and len(m2["correcciones"]) == 1 and m2["estadoTexto"] == "Pendiente de revisión"
              and m["dictamenEvaluador"] == "apto_con_restricciones", "6 · el evaluador corrige desde su liga (con historial)")
        check(c.get(f"/candidatos/{hugo}", headers=h).json()["etapa"] == etapa_antes, "6 · las correcciones no mueven al candidato de columna")

        # 7 y 8. resumen + «Pasar a Contratación»
        panel = c.get(f"/candidatos/{hugo}/operativo", headers=h).json()
        rs = panel["resumen"]
        nombres = [v["nombre"] for v in rs["validaciones"]]
        check(rs["etapa"] == "Entrevista" and rs["resultadoIntegral"]["texto"] in ("En proceso", "Apto", "No apto")
              and {"Prefiltro", "Vehículo", "Entrevista", "Examen médico"} <= set(nombres) and rs["pendientes"] == panel["requisitosContratacion"],
              "7 · resumen: etapa, resultado integral, validaciones y requisitos pendientes")
        r = c.post(f"/candidatos/{hugo}/operativo/avanzar-contratacion", headers=h)
        check(r.status_code == 409 and "Marcar como revisada" in r.json()["detail"], "8 · «Pasar a Contratación» indica exactamente qué falta")
        for ev_id, dic in ((med["id"], "apto"), (soc["id"], "favorable")):
            c.post(f"/evaluaciones/{ev_id}/revisar", json={"dictamen": dic, "conclusion": "Revisado"}, headers=h)
        r = c.post(f"/candidatos/{hugo}/operativo/avanzar-contratacion", headers=h)
        check(r.status_code == 200 and r.json()["etapa"] == "Contratación" and r.json()["resumen"]["pendientes"],
              "8 · con todo revisado pasa a Contratación (y el resumen ya pide las condiciones)")


def flujo_por_chat():
    """Arquitectura de dos pasos (2026-10-01): (1) el portal EXIGE el prefiltro web; (2) tras /start <token> el bot saluda
    («Hola X. Vi que estás interesado en la vacante Y.») y hace las preguntas SECUNDARIAS del agente —nunca las del
    prefiltro web—, una por una, guardando cada respuesta; el «Gracias» solo sale al contestar la última."""
    from app.config import settings
    from app.database import SessionLocal
    from app.models import Mensaje, Postulacion, Vacante
    from app.routers import webhooks
    from app.services import flujo_operativo, prefiltro_reglas, telegram

    def asistente(db, p):
        return [m.texto for m in db.query(Mensaje).filter(Mensaje.postulacion_id == p.id, Mensaje.rol == "assistant").order_by(Mensaje.id)]

    uid = [1000]

    def mandar(chat_id, t):
        uid[0] += 1
        upd = {"update_id": uid[0], "message": {"message_id": uid[0], "chat": {"id": chat_id, "type": "private"},
                                                "from": {"id": chat_id, "is_bot": False, "first_name": "P"}, "text": t}}
        return asyncio.run(webhooks.procesar_update_telegram(upd))

    with TestClient(app) as c, mock.patch.object(settings, "telegram_bot_token", "123:prueba"), \
         mock.patch.object(telegram, "_enviar_a_chat", new=mock.AsyncMock(return_value={"enviado": True})), \
         mock.patch.object(telegram, "pedir_contacto", new=mock.AsyncMock(return_value={"enviado": True})):
        # ---- Paso 1: el portal exige el prefiltro (también con Telegram activo) ----
        r = c.post("/candidatos/postular", data={"vacante": SLUG + "puebla", "nombre": "Sin Prefiltro", "telefono": "2226660009", "consentimiento": "true"})
        check(r.status_code == 400 and "prefiltro" in r.json()["detail"].lower(), "paso 1: sin contestar el prefiltro web no se guarda la postulación (ni hay token)")
        d = c.post("/candidatos/postular", data={"vacante": SLUG + "puebla", "nombre": "Chat Reglas", "telefono": "2226660001", "consentimiento": "true",
                                                 "respuestas_reglas": json.dumps(R_OK)}).json()
        P, tok = d["postulacion"], d["telegram_onboarding_token"]
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            antes = len(asistente(db, p))
            titulo = p.vacante.titulo
            web = [q["texto"] for q in prefiltro_reglas.preguntas(p.vacante.prefiltro_reglas)]
            check(tok and p.prefiltro_completo and p.etapa == "Revisión de vehículo", "paso 1: con el prefiltro web guardado se genera el token del handoff")

        # ---- Paso 2: saludo + preguntas del agente ----
        mandar(5001, f"/start {tok}")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            nuevos = asistente(db, p)[antes:]
            preguntas = flujo_operativo.preguntas_agente(p.vacante)
            check(len(nuevos) == 2 and nuevos[0] == f"Hola Chat. Vi que estás interesado en la vacante {titulo}.",
                  "paso 2: saludo personalizado con el nombre del candidato y el título de la vacante")
            check(f"*1/{len(preguntas)}* {preguntas[0]}" in nuevos[1] and not any(w in nuevos[1] for w in web) and "Gracias" not in "".join(nuevos),
                  "inmediatamente la primera pregunta del agente (no repite el prefiltro web, no manda el cierre)")
        for i, respuesta in enumerate(["Nissan Versa 2020", "ABC-123-D", "El lunes"]):
            mandar(5001, respuesta)
            with SessionLocal() as db:
                p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
                ultimo = asistente(db, p)[-1]
                if i < len(preguntas) - 1:
                    check(f"*{i + 2}/{len(preguntas)}* {preguntas[i + 1]}" in ultimo and "Gracias" not in ultimo,
                          f"respuesta {i + 1} guardada → pregunta {i + 2} (sin cierre)")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            agente = (p.analisis or {}).get("preguntas_agente") or {}
            check([x["respuesta"] for x in agente.get("respuestas", [])] == ["Nissan Versa 2020", "ABC-123-D", "El lunes"] and agente.get("completado_en"),
                  "cada respuesta queda en el expediente de la postulación")
            ultimo = asistente(db, p)[-1]
            check("Gracias por tus respuestas" in ultimo and "/vehiculo/" in ultimo, "el «Gracias» solo al contestar la última (con el siguiente paso: liga del vehículo)")
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        res = c.get(f"/candidatos/{P}/operativo", headers={"X-Cuenta-Id": str(p.cuenta_id)}).json()["resumen"]
        check(len(res["respuestasAgente"]) == 3 and any(v["nombre"].startswith("Preguntas del agente") and v["estado"] == "Completadas" for v in res["validaciones"]),
              "RH ve las respuestas del agente en el Resumen de la ficha")
        mandar(5001, f"/start {tok}")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            msgs = asistente(db, p)
            check(msgs[-2].startswith("Hola Chat. Vi que") and "*1/" not in msgs[-1], "volver a abrir la liga: saluda y recuerda en qué va (no repite las preguntas)")

        # ---- vacante sin reglas: el agente no repite las preguntas web ----
        with SessionLocal() as db:
            v = db.query(Vacante).filter(Vacante.slug == SLUG + "cdmx").first()
            v.prefiltro_reglas = {**(v.prefiltro_reglas or {}), "activo": False}
            v.preguntas_filtro = [{"pregunta": "¿Tienes licencia vigente?"}]
            v.preguntas_filtro_whatsapp = [{"pregunta": "¿Tienes licencia vigente?"}, {"pregunta": "¿En qué colonia vives?"}]
            db.commit()
        d = c.post("/candidatos/postular", data={"vacante": SLUG + "cdmx", "nombre": "Chat Libre", "telefono": "2226660002", "consentimiento": "true",
                                                 "respuestas": json.dumps([{"pregunta": "¿Tienes licencia vigente?", "respuesta": "Sí"}])}).json()
        P2 = d["postulacion"]
        mandar(5002, f"/start {d['telegram_onboarding_token']}")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P2).first()
            msgs = asistente(db, p)
            check("*1/1* ¿En qué colonia vives?" in msgs[-1] and "licencia" not in msgs[-1].lower(),
                  "vacante sin reglas: el agente solo hace sus preguntas que NO estaban en la web")
        mandar(5002, "Narvarte")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P2).first()
            check(p.prefiltro_completo and p.estado == "revision" and "Gracias por tus respuestas" in asistente(db, p)[-1],
                  "al terminar: «Requiere revisión» (RH decide) y el «Gracias»")
            v = db.query(Vacante).filter(Vacante.slug == SLUG + "cdmx").first()
            v.prefiltro_reglas = {**(v.prefiltro_reglas or {}), "activo": True}
            db.commit()

if __name__ == "__main__":
    main()
    if not FALLAS:
        flujo_por_chat()
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
