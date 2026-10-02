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
                check(ultimo is not None and ultimo.texto.startswith("Gracias, Hand. Tu postulación a ") and ultimo.texto.endswith("quedó registrada. Por aquí te avisaremos los siguientes pasos.")
                      and "*1/" not in ultimo.texto and "/vehiculo/" not in ultimo.texto,
                      "postulación web completa: al conectar Telegram el bot SOLO confirma (rutas paralelas 2026-10-01)")
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
    """Cambios ZESE (2026-10-01): entrada dual, identidad «Red Human», ligas directas con acción, cita idéntica al
    reenviar, «Sí» → Confirmada sin reiniciar el reclutamiento, expediente completo del colaborador y la evaluación de
    capacitación (nunca «Terminado» sin preguntas respondidas)."""
    from app.config import settings
    from app.database import SessionLocal
    from app.models import AsignacionCurso, Colaborador, Curso, Mensaje, Postulacion
    from app.routers import webhooks
    from app.services import flujo_operativo, prefiltro_reglas, telegram
    from app.serial import nombre_empresa_candidato

    def asistente(db, p):
        return [m.texto for m in db.query(Mensaje).filter(Mensaje.postulacion_id == p.id, Mensaje.rol == "assistant").order_by(Mensaje.id)]

    uid = [1000]

    def mandar(chat_id, t):
        uid[0] += 1
        upd = {"update_id": uid[0], "message": {"message_id": uid[0], "chat": {"id": chat_id, "type": "private"},
                                                "from": {"id": chat_id, "is_bot": False, "first_name": "P"}, "text": t}}
        return asyncio.run(webhooks.procesar_update_telegram(upd))

    llamadas = []

    async def llamar_falso(metodo, json=None, data=None, files=None):
        llamadas.append((metodo, json or {}))
        return {"ok": True, "result": {"message_id": len(llamadas)}}

    with TestClient(app) as c, mock.patch.object(settings, "telegram_bot_token", "123:prueba"), \
         mock.patch.object(telegram, "llamar", side_effect=llamar_falso):
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        cuentas = c.get("/cuentas").json()
        h = {"X-Cuenta-Id": str(next((x["id"] for x in cuentas if "SEZA" in x.get("nombre", "")), 1))}

        # ---- 2. presentación: «Red Human», corta y sin vista previa de ligas ----
        asyncio.run(telegram._enviar_a_chat("9", "Sube tus fotos: https://app/vehiculo/x"))
        cuerpo = llamadas[-1][1]
        check(cuerpo.get("link_preview_options") == {"is_disabled": True} and "disable_web_page_preview" not in cuerpo,
              "2 · los mensajes con ligas operativas salen sin vista previa publicitaria")
        asyncio.run(telegram.pedir_contacto("9", "Ana López"))
        check("Soy Red Human" in llamadas[-1][1]["text"] and len(llamadas[-1][1]["text"]) < 120, "2 · la presentación es corta y el agente se llama «Red Human»")

        # ---- 1. entrada dual: filtro web completo → Telegram solo seguimiento ----
        d = c.post("/candidatos/postular", data={"vacante": SLUG + "puebla", "nombre": "Dual Web", "telefono": "2227770001", "consentimiento": "true",
                                                 "respuestas_reglas": json.dumps(R_OK)}).json()
        P, tok = d["postulacion"], d["telegram_onboarding_token"]
        mandar(6001, f"/start {tok}")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            msgs = asistente(db, p)
            titulo = p.vacante.titulo
            web = [q["texto"] for q in prefiltro_reglas.preguntas(p.vacante.prefiltro_reglas)]
            empresa = nombre_empresa_candidato(p.vacante)
            check(msgs[-1] == f"Gracias, Dual. Tu postulación a {titulo} en {empresa} quedó registrada. Por aquí te avisaremos los siguientes pasos."
                  and not any(w in msgs[-1] for w in web) and not (p.analisis or {}).get("preguntas_agente"),
                  "1 · llegó por la web con el filtro completo: Telegram solo confirma (no repite preguntas ni pide archivos)")

        # ---- 1. entrada directa a Telegram: el filtro se completa en el chat sin repetir lo contestado ----
        d2 = c.post("/candidatos/postular", data={"vacante": SLUG + "puebla", "nombre": "Dual Chat", "telefono": "2227770002", "consentimiento": "true",
                                                  "respuestas_reglas": json.dumps(R_OK)}).json()
        with SessionLocal() as db:  # simula que entró por el chat y ya contestó 3 preguntas
            p2 = db.query(Postulacion).filter(Postulacion.codigo == d2["postulacion"]).first()
            p2.prefiltro_completo, p2.estado, p2.etapa = False, "pendiente", "Prefiltro"
            p2.analisis = {"prefiltro_reglas": {"respuestas": {"municipio": "Puebla", "jornada": "si", "experiencia": "no"}, "textos": {}, "pendiente": None}}
            db.commit()
        mandar(6002, f"/start {d2['telegram_onboarding_token']}")
        with SessionLocal() as db:
            p2 = db.query(Postulacion).filter(Postulacion.codigo == d2["postulacion"]).first()
            ultimo = asistente(db, p2)[-1]
            lista = prefiltro_reglas.preguntas(p2.vacante.prefiltro_reglas)
            siguiente = next(q for q in lista if q["id"] == "vehiculo_propio")
            check(siguiente["texto"] in ultimo and lista[0]["texto"] not in ultimo and len(ultimo) < 200,
                  "1 · filtro a medias: el chat sigue en la primera pregunta sin contestar (nunca repite las contestadas)")

        # ---- 1. ligas directas con acción ----
        check(telegram.separar_inicio(f"cita_{tok}") == ("cita", tok) and telegram.separar_inicio(tok) == ("", tok)
              and telegram.liga_inicio(tok, "docs") == f"tg://resolve?domain=GrupoSeza_bot&start=docs_{tok}",
              "1 · ligas directas: /start <accion>_<token> (cita, docs, vehiculo)")
        mandar(6001, f"/start vehiculo_{tok}")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            msgs = asistente(db, p)
            check("/vehiculo/" in msgs[-1] and "Vi que estás interesado" in msgs[-2], "1 · la liga de vehículo abre directo su proceso, sin pedir datos ni vacante")

        # ---- 3. cita: reenviar la MISMA cita y «Sí» → Confirmada ----
        tarjetas = {t["nombre"]: t for t in c.get("/candidatos", headers=h).json()}
        mig = tarjetas["Miguel Ángel Rosas"]["id"]
        with SessionLocal() as db:
            pm = db.query(Postulacion).filter(Postulacion.codigo == mig).first()
            pm.candidato.telefono = "2227770003"
            db.commit()
        cita = {"tienda": "Tienda Centro", "direccion": "Av. Juárez 10", "fecha": "2030-02-03", "hora": "10:30", "capacitador_tipo": "externo",
                "capacitador_nombre": "Laura Gerente", "capacitador_telefono": "5511110000"}
        c.post(f"/candidatos/{mig}/operativo/entrevista", json=cita, headers=h)
        with SessionLocal() as db:
            pm = db.query(Postulacion).filter(Postulacion.codigo == mig).first()
            original = [m for m in asistente(db, pm) if "Te citamos" in m][-1]
        c.post(f"/candidatos/{mig}/operativo/entrevista/reenviar", json={"destinatario": "candidato"}, headers=h)
        with SessionLocal() as db:
            pm = db.query(Postulacion).filter(Postulacion.codigo == mig).first()
            reenvio = [m for m in asistente(db, pm) if "Te citamos" in m][-1]
            check(reenvio == original and all(x in reenvio for x in (pm.vacante.titulo, "Laura Gerente", "Tienda Centro", "Av. Juárez 10", "03/02/2030", "10:30")),
                  "3 · «Reenviar cita» manda EXACTAMENTE la misma cita (vacante, empresa, entrevistador, fecha, hora y lugar)")
            telegram.guardar_chat(db, "6003", "2227770003", "Miguel")
            pm.candidato.postulacion_conversacion_id = None  # sin puntero: el «Sí» igual debe llegar a la cita
            db.commit()
        with mock.patch("app.routers.webhooks.ventana_modo_prueba_min", return_value=1), \
             mock.patch("app.routers.webhooks.modo_prueba_activo", return_value=True):
            with SessionLocal() as db:  # la última actividad fue hace horas (antes: la ventana corta reiniciaba el reclutamiento)
                from datetime import datetime, timedelta, timezone
                pm = db.query(Postulacion).filter(Postulacion.codigo == mig).first()
                pm.ultima_actividad_en = datetime.now(timezone.utc) - timedelta(hours=6)
                for m in pm.mensajes:
                    m.creado_en = datetime.now(timezone.utc) - timedelta(hours=6)
                db.commit()
            mandar(6003, "Sí")
        with SessionLocal() as db:
            pm = db.query(Postulacion).filter(Postulacion.codigo == mig).first()
            eh = flujo_operativo.entrevista_actual(pm)
            ultimo = asistente(db, pm)[-1]
            check(pm.activa and eh.confirmada_en and eh.confirmada_por == "candidato" and ultimo == "Gracias, Miguel. Tu asistencia quedó confirmada.",
                  "3 · «Sí» al aviso de cita → Confirmada en la base y respuesta exacta")
            todos = " ".join(m.texto for m in db.query(Mensaje).filter(Mensaje.candidato_id == pm.candidato_id).order_by(Mensaje.id.desc()).limit(3))
            check("vacantes" not in todos.lower() and pm.etapa == "Entrevista", "3 · confirmar no reinicia el reclutamiento ni ofrece otras vacantes")
        panel = c.get(f"/candidatos/{mig}/operativo", headers=h).json()
        check(panel["entrevista"]["confirmada"] and panel["entrevista"]["confirmadaPor"] == "candidato" and panel["ligasTelegram"]["cita"].endswith(f"cita_{panel['ligasTelegram']['proceso'].rsplit('=', 1)[1]}"),
              "3 · el dashboard muestra la cita «Confirmada por el candidato» y la liga directa a la cita")

        # ---- 4. expediente completo del colaborador ----
        P = tarjetas["Hugo Sánchez Ibarra"]["id"]  # candidato demo con historial completo (filtro, fotos, documentos, entrevista)
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            from app.models import Usuario
            admin = db.query(Usuario).filter(Usuario.correo == "admin@redhuman.mx").first()
            with mock.patch("app.services.flujo_operativo.faltantes_para_alta", return_value=[]):
                p.etapa = "Onboarding"
                _, col = flujo_operativo.registrar_alta(db, p, admin, prueba=True)
            db.commit()
            col_cod, pid = col.codigo, p.id
            check(col.postulacion_origen_id == pid and p.motivo_cierre == "contratado" and not p.activa,
                  "4 · el alta liga al colaborador con su postulación original y la deja «Contratado»")
        tarjeta = next(t for t in c.get("/candidatos?mostrar_cerradas=true", headers=h).json() if t["id"] == P)
        check(tarjeta["motivoCierre"] == "contratado", "4 · en el pipeline la postulación queda como «Contratado»")
        ex = c.get(f"/colaboradores/{col_cod}/expediente-completo", headers=h).json()
        check(ex["postulacion"]["estadoPipeline"] == "Contratado" and len(ex["filtros"]["respuestas"]) >= 10 and ex["vehiculo"] is not None
              and len(ex["vehiculo"]["fotos"]) == 4 and any(d["tipo"].startswith("Póliza") and d["url"] for d in ex["documentos"])
              and any(e["tipo"] == "Entrevista" and e["resultado"] == "Apto" for e in ex["entrevistas"]) and ex["historial"],
              "4 · «Ver expediente completo»: filtros, fotos del auto, documentos, entrevistas e historial desde el registro original")
        foto = c.get(ex["vehiculo"]["fotos"][0]["url"], headers=h)
        check(foto.status_code == 200, "4 · las fotos del auto se abren con la ruta original (sin duplicar archivos)")
        with SessionLocal() as db:
            check(db.query(Colaborador).filter(Colaborador.postulacion_origen_id == pid).count() == 1, "4 · no se duplica nada: un solo colaborador ligado")

        # ---- 5. capacitación: sin preguntas nunca «Terminado»; contador correcto ----
        with SessionLocal() as db:
            curso = db.query(Curso).filter(Curso.titulo == "Inducción SEZA").first()
            sin_eval = Curso(codigo="TMP", cuenta_id=curso.cuenta_id, titulo="Curso sin evaluación", estado="Publicado", evaluacion=[])
            db.add(sin_eval)
            db.flush()
            sin_eval.codigo = f"CUR-{100 + sin_eval.id}"
            from app.models import ModuloCurso
            db.add(ModuloCurso(curso_id=sin_eval.id, orden=1, titulo="Único", contenido="Contenido"))
            raro = Curso(codigo="TMP2", cuenta_id=curso.cuenta_id, titulo="Curso con evaluación en otro formato", estado="Publicado",
                         evaluacion={"preguntas": [{"texto": "¿2+2?", "opciones": ["3", "4"], "correcta": 1}, {"pregunta": "Sin opciones", "opciones": []}]})
            db.add(raro)
            db.flush()
            raro.codigo = f"CUR-{100 + raro.id}"
            db.add(ModuloCurso(curso_id=raro.id, orden=1, titulo="Único", contenido="Contenido"))
            import secrets as _s
            a1 = AsignacionCurso(codigo="ASG-T1", curso_id=sin_eval.id, tipo="externo", externo_nombre="Prueba", token=_s.token_urlsafe(16))
            a2 = AsignacionCurso(codigo="ASG-T2", curso_id=raro.id, tipo="externo", externo_nombre="Prueba", token=_s.token_urlsafe(16))
            db.add_all([a1, a2])
            db.commit()
            t1, t2 = a1.token, a2.token
        c.post(f"/capacitacion/publica/{t1}/avanzar", json={"modulo": 1})
        pub = c.get(f"/capacitacion/publica/{t1}").json()
        r = c.post(f"/capacitacion/publica/{t1}/responder", json={"indice": 0, "respuesta": 0})
        check(pub["evaluacionDisponible"] is False and pub["estado"] != "completado" and pub["resultado"] is None and r.status_code == 409,
              "5 · curso sin preguntas: no se marca «terminado» ni hay resultado (la sala lo dice; antes «Cargando…»/«Terminado»)")
        c.post(f"/capacitacion/publica/{t2}/avanzar", json={"modulo": 1})
        pub = c.get(f"/capacitacion/publica/{t2}").json()
        check(pub["totalPreguntas"] == 1 and pub["pregunta"]["pregunta"] == "¿2+2?" and pub["estado"] != "completado",
              "5 · la evaluación guardada en otro formato se lee bien: «Pregunta 1 de 1» (no «1/0»)")
        r = c.post(f"/capacitacion/publica/{t2}/responder", json={"indice": 0, "respuesta": 1}).json()
        check(r["estado"] == "completado" and r["resultado"]["calificacion"] == 100 and r["resultado"]["aprobado"],
              "5 · solo al responder y guardar el resultado queda «completado» con su calificación")
        tablero = c.get("/capacitacion/asignaciones", headers=h).json()
        asg = next((x for x in tablero if x.get("id") == "ASG-T2"), None)
        sin = next((x for x in tablero if x.get("id") == "ASG-T1"), None)
        check(asg is not None and asg.get("calificacion") == 100 and asg.get("aprobado") is True and sin is not None and sin.get("calificacion") is None,
              "5 · la calificación y el resultado se ven en el tablero de Capacitación (y el curso sin preguntas no tiene calificación)")
        ex = c.get(f"/colaboradores/{col_cod}/expediente-completo", headers=h).json()
        check(isinstance(ex["capacitacion"], list), "5 · el expediente del colaborador trae su capacitación con calificación")

if __name__ == "__main__":
    main()
    if not FALLAS:
        flujo_por_chat()
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
