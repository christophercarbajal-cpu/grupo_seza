"""Regresión: rutas paralelas Web / Chat y correcciones claras de fotos y documentos (2026-10-01), base DESECHABLE.

CAMBIO 1 — Cada vacante tiene «Copiar liga web» / «Copiar liga Telegram» (WhatsApp solo si el canal está habilitado). La
ruta WEB se hace completa en la web (datos + prefiltro → fotos y documentos en la liga del vehículo) y al final ofrece
«Conectar Telegram» solo para avisos: el bot únicamente confirma. La ruta CHAT (`/start vac_<VAC-####>`) abre una
postulación nueva amarrada a ESA vacante y empresa, hace el prefiltro y recibe fotos y documentos en el chat; nunca
repite preguntas ni pide lo ya entregado, y no mezcla procesos anteriores de la persona.
CAMBIO 2 — «Pedir corrección» exige un motivo por archivo; el mensaje dice qué, por qué y cómo; el botón es específico
(«Corregir foto del frente») o «Corregir archivos»; chat → se corrige en el chat; web → la liga abre los pendientes;
lo ya recibido se conserva; al reemplazar: «Recibimos tu nueva foto. Está pendiente de revisión.»

Uso (desde red-human-api/):  python scripts/verificar_rutas_paralelas.py
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
BASE = Path(tempfile.mkdtemp()) / "rutas.db"
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
SLUG = "chofer-de-reparto-con-unidad-propia-puebla"
R_OK = {"municipio": "Puebla, Puebla", "jornada": "Sí", "experiencia": "No", "vehiculo_propio": "Sí", "tipo_vehiculo": "Sedán de cuatro puertas",
        "anio_vehiculo": "2019", "taxi": "No", "circulacion": "Sí", "licencia": "Automovilista", "poliza": "Sí", "android": "Sí", "zona": "Sí", "cobertura": "Sí"}
FOTOS = ["frente", "atras", "izquierdo", "derecho"]
DOCS = ["licencia", "tarjeta", "poliza"]


def check(cond, nombre):
    print(("✅ " if cond else "❌ ") + nombre)
    if not cond:
        FALLAS.append(nombre)


_uid = [1000]


def update(chat_id, texto="", foto=False, documento=False, callback=""):
    _uid[0] += 1
    uid = _uid[0]
    remitente = {"id": chat_id, "is_bot": False, "first_name": "Chat"}
    if callback:
        return {"update_id": uid, "callback_query": {"id": f"cb{uid}", "from": remitente, "data": callback,
                                                       "message": {"chat": {"id": chat_id, "type": "private"}, "reply_markup": {}}}}
    m = {"message_id": uid, "chat": {"id": chat_id, "type": "private"}, "from": remitente}
    if foto:
        m["photo"] = [{"file_id": f"f{uid}", "file_size": 100}]
    if documento:
        m["document"] = {"file_id": f"d{uid}", "mime_type": "application/pdf", "file_name": "doc.pdf"}
    if texto:
        m["caption" if (foto or documento) else "text"] = texto
    return {"update_id": uid, "message": m}


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
    from app.models import ChatTelegram, Mensaje, Postulacion, Vacante
    from app.routers import webhooks
    from app.serial import nombre_empresa_candidato
    from app.services import ia, prefiltro_reglas, telegram
    from app.services import vehiculo as vsrv
    from app.services import whatsapp

    def asistente(db, p):
        return [m.texto for m in db.query(Mensaje).filter(Mensaje.postulacion_id == p.id, Mensaje.rol == "assistant").order_by(Mensaje.id).all()]

    def mandar(upd):
        return asyncio.run(webhooks.procesar_update_telegram(upd))

    descarga_jpg = mock.AsyncMock(return_value={"ok": True, "contenido": JPG, "filename": "foto.jpg", "mime": "image/jpeg"})
    descarga_pdf = mock.AsyncMock(return_value={"ok": True, "contenido": PDF, "filename": "doc.pdf", "mime": "application/pdf"})

    with TestClient(app) as c, mock.patch.object(ia, "ia_activa", return_value=False):
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        cuentas = c.get("/cuentas").json()
        h = {"X-Cuenta-Id": str(next((x["id"] for x in cuentas if "SEZA" in x.get("nombre", "")), 1))}
        with SessionLocal() as db:
            vac = db.query(Vacante).filter(Vacante.slug == SLUG).first()
            VAC, titulo, empresa = vac.codigo, vac.titulo, nombre_empresa_candidato(vac)

        # ================= CAMBIO 1.1: ligas de entrada =================
        det = c.get(f"/vacantes/{VAC}", headers=h).json()
        ligas = det.get("ligasEntrada") or {}
        check(ligas.get("web", "").endswith(f"/aplicar/{SLUG}") and ligas.get("telegram") == f"https://t.me/GrupoSeza_bot?start=vac_{VAC}"
              and ligas.get("whatsapp") == "" and ligas.get("whatsappHabilitado") is False,
              "1.1 · la vacante trae liga web y liga Telegram; WhatsApp no se ofrece si el canal no está habilitado")
        from app.config import settings
        from app.services import canales
        with mock.patch.object(settings, "whatsapp_provider", "meta"), mock.patch.object(settings, "whatsapp_numero_publico", "5512345678"):
            with SessionLocal() as db:
                wa = canales.ligas_entrada(db.query(Vacante).filter(Vacante.codigo == VAC).first())
        check(wa["whatsappHabilitado"] and wa["whatsapp"].startswith("https://wa.me/525512345678?text=") and VAC in wa["whatsapp"],
              "1.1 · con WhatsApp habilitado aparece «Copiar liga WhatsApp» (wa.me con el código de la vacante)")
        check(telegram.separar_inicio(f"vac_{VAC}") == ("vac", VAC), "1.1 · /start vac_<VAC-####> identifica la vacante")

        # ================= CAMBIO 1.2: ruta 100 % web =================
        d = c.post("/candidatos/postular", data={"vacante": SLUG, "nombre": "Wendy Web", "telefono": "2228880001", "consentimiento": "true",
                                                 "respuestas_reglas": json.dumps(R_OK)}).json()
        sig = d.get("siguientePaso") or {}
        check(sig.get("tipo") == "vehiculo" and "/vehiculo/" in sig.get("liga", "") and sig.get("boton") == "Subir fotos y documentos",
              "1.2/1.6 · al enviar el prefiltro, el siguiente paso REAL es en la web: «Subir fotos y documentos»")
        vtok = sig["liga"].rsplit("/", 1)[-1]
        PW = d["postulacion"]
        for lado in FOTOS:
            c.post(f"/vehiculo/publica/{vtok}/foto", data={"lado": lado}, files={"archivo": ("f.jpg", JPG, "image/jpeg")})
        for clave in DOCS:
            c.post(f"/vehiculo/publica/{vtok}/documento", data={"clave": clave}, files={"archivo": ("d.pdf", PDF, "application/pdf")})
        pub = c.get(f"/vehiculo/publica/{vtok}").json()
        check(pub["estado"] == "por_revisar" and pub["telegram"]["liga"].startswith("tg://resolve?domain=GrupoSeza_bot&start=")
              and not pub["telegram"]["conectado"], "1.2/1.5 · fotos y documentos completos en la web → fin de ruta con «Conectar Telegram» (opcional)")

        # ================= CAMBIO 1.5: conectar Telegram = solo confirmación =================
        tok = d["telegram_onboarding_token"]
        mandar(update(7001, f"/start {tok}"))
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == PW).first()
            msgs = asistente(db, p)
            esperado = f"Gracias, Wendy. Tu postulación a {titulo} en {empresa} quedó registrada. Por aquí te avisaremos los siguientes pasos."
            check(msgs[-1] == esperado and p.telegram_chat_id == "7001", "1.5 · al conectar Telegram el bot SOLO confirma con el texto exacto")
            check(not any("/vehiculo/" in m for m in msgs[-1:]) and "Vi que estás interesado" not in " ".join(msgs[-2:]),
                  "1.5 · no hay salto Web → Telegram → Web: el bot no pide nada ni manda ligas")

        # ================= CAMBIO 1.3/1.4: ruta 100 % chat =================
        with SessionLocal() as db:  # la misma persona de la web ya tenía su chat; un chat nuevo de otra persona entra por la liga
            db.add(ChatTelegram(chat_id="7002", telefono="2228880002", nombre="Carlos Chat"))
            db.commit()
        r = mandar(update(7002, f"/start vac_{VAC}"))
        PC = r.get("postulacion")
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == PC).first()
            check(r.get("accion") == "aviso_privacidad_enviado" and p and p.vacante_id == vac.id and p.cuenta_id == vac.cuenta_id
                  and p.origen == "whatsapp" and not p.consentimiento and "Aviso de Privacidad" in asistente(db, p)[-1],
                  "1.3/1.4 · la liga Telegram abre una postulación NUEVA a esa vacante y empresa, empezando por el aviso de privacidad")
        mandar(update(7002, "Sí"))
        for _ in range(20):  # contesta el prefiltro pregunta por pregunta, siempre la que el bot tiene pendiente
            with SessionLocal() as db:
                p = db.query(Postulacion).filter(Postulacion.codigo == PC).first()
                pendiente = ((p.analisis or {}).get("prefiltro_reglas") or {}).get("pendiente")
                if p.prefiltro_completo or not pendiente:
                    break
            mandar(update(7002, R_OK.get(pendiente, "Sí")))
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == PC).first()
            msgs = asistente(db, p)
            preguntas = [q["texto"] for q in prefiltro_reglas.preguntas(p.vacante.prefiltro_reglas)]
            repetidas = [q for q in preguntas if sum(q in m for m in msgs) > 1]
            check(p.prefiltro_completo and p.estado == "cumple" and not repetidas, "1.3 · el prefiltro se hace completo en el chat, sin repetir preguntas")
            check("Envíame por aquí la foto del frente de tu vehículo" in msgs[-1] and "/vehiculo/" not in msgs[-1],
                  "1.3 · las fotos se piden en el chat (una por mensaje), sin mandarlo a la web")
        # re-abrir la liga de la vacante: misma postulación, sin repetir nada
        r = mandar(update(7002, f"/start vac_{VAC}"))
        check(r.get("postulacion") == PC and r.get("accion") == "postulacion_retomada", "1.4 · volver a abrir la liga retoma la MISMA postulación (no duplica)")
        with mock.patch.object(webhooks, "descargar_media", new=descarga_jpg):
            r = mandar(update(7002, foto=True))
            check(r.get("archivo") == "frente" and "foto de la parte de atrás" in r.get("respuesta", ""),
                  "1.3 · la foto que llega por el chat se guarda y el bot pide la siguiente")
            r = mandar(update(7002, "esta es la de atrás", foto=True))
            check(r.get("archivo") == "atras", "1.3 · el pie de foto indica qué archivo es")
            r = mandar(update(7002, "la de atrás otra vez", foto=True))
            check("Esa ya la tengo" in r.get("respuesta", ""), "1.4 · nunca pide ni toma de nuevo un archivo ya entregado")
            mandar(update(7002, foto=True))
            mandar(update(7002, foto=True))
        with mock.patch.object(webhooks, "descargar_media", new=descarga_pdf):
            for _ in DOCS:
                r = mandar(update(7002, documento=True))
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == PC).first()
            check(p.revision_vehiculo.estado == "por_revisar" and all(l in p.revision_vehiculo.fotos for l in FOTOS)
                  and all(vsrv._doc_cargado(vsrv.documento(p, x)) for x in DOCS) and "Recibí las 4 fotos" in asistente(db, p)[-1],
                  "1.3 · fotos y documentos recibidos en el chat → la revisión queda «Fotos por revisar» en el mismo tablero")
        # la persona de la web abre en Telegram la liga de la MISMA vacante → retoma su postulación (no duplica ni repite)
        with SessionLocal() as db:
            db.add(ChatTelegram(chat_id="7003", telefono="2228880001", nombre="Wendy Web"))
            otra_vac = db.query(Vacante).filter(Vacante.cuenta_id == vac.cuenta_id, Vacante.estado == "Publicada", Vacante.id != vac.id).first()
            db.commit()
            OTRA = otra_vac.codigo
        r = mandar(update(7003, f"/start vac_{VAC}"))
        check(r.get("postulacion") == PW and r.get("accion") == "postulacion_retomada", "1.4 · misma persona y misma vacante: se retoma su postulación web")
        # …y la de OTRA vacante → postulación nueva y aparte (sin heredar consentimiento, respuestas ni archivos)
        r = mandar(update(7003, f"/start vac_{OTRA}"))
        with SessionLocal() as db:
            nueva = db.query(Postulacion).filter(Postulacion.codigo == r.get("postulacion")).first()
            web = db.query(Postulacion).filter(Postulacion.codigo == PW).first()
            check(nueva and nueva.id != web.id and nueva.vacante.codigo == OTRA and not nueva.consentimiento and not nueva.prefiltro_completo
                  and not (nueva.analisis or {}).get("prefiltro_reglas") and nueva.revision_vehiculo is None and web.vacante_id == vac.id,
                  "1.4 · otra vacante: postulación nueva y aislada (no mezcla respuestas, consentimiento ni archivos anteriores)")

        # ================= CAMBIO 2: correcciones claras =================
        # motivo obligatorio por archivo
        r = c.post(f"/candidatos/{PW}/vehiculo/decision", json={"accion": "correccion", "motivos": {"frente": "no se distingue", "poliza": " "}}, headers=h)
        check(r.status_code == 400 and "Póliza" in r.json()["detail"], "2.1 · cada archivo rechazado exige su motivo")
        enviados = []

        async def boton_falso(tel, texto, boton, url="", callback=""):
            enviados.append({"texto": texto, "boton": boton, "url": url, "callback": callback})
            return {"enviado": True}

        with mock.patch.object(whatsapp, "enviar_con_boton", side_effect=boton_falso):
            r = c.post(f"/candidatos/{PW}/vehiculo/decision", json={"accion": "correccion", "motivos": {"frente": "No se distingue."}}, headers=h)
            env = enviados[-1] if enviados else {}
            esperado = ("Hola, Wendy. Necesitamos que reemplaces la foto del frente de tu vehículo porque no se distingue. Tómala de frente, con buena luz, "
                        "mostrando el vehículo completo y las placas. Las demás fotos y documentos están recibidos; solo necesitamos que reemplaces esta foto.")
            check(r.status_code == 200 and env.get("texto") == esperado, "2.2 · mensaje claro: qué, por qué y cómo (texto exacto del ejemplo)")
            check(env.get("boton") == "Corregir foto del frente" and env.get("url", "").endswith(f"/vehiculo/{vtok}?corregir=1"),
                  "2.3/2.4 · un archivo → botón «Corregir foto del frente»; candidato web → la liga abre los pendientes")
            pub = c.get(f"/vehiculo/publica/{vtok}").json()
            frente = next(x for x in pub["lados"] if x["clave"] == "frente")
            atras = next(x for x in pub["lados"] if x["clave"] == "atras")
            check(pub["correccion"] and pub["correccion"][0]["motivo"] == "No se distingue." and "placas" in pub["correccion"][0]["instruccion"]
                  and frente["pendiente"] and not atras["pendiente"], "2.5 · la web muestra motivo e instrucción junto al archivo; lo demás no se pide")
            r = c.post(f"/vehiculo/publica/{vtok}/foto", data={"lado": "atras"}, files={"archivo": ("f.jpg", JPG, "image/jpeg")})
            check(r.status_code == 409, "2.5 · los archivos ya recibidos se conservan intactos (no se pueden reemplazar)")
            r = c.post(f"/vehiculo/publica/{vtok}/foto", data={"lado": "frente"}, files={"archivo": ("f.jpg", JPG, "image/jpeg")}).json()
            check(r["mensaje"] == "Recibimos tu nueva foto. Está pendiente de revisión." and r["estado"] == "por_revisar",
                  "2.6 · al reemplazar: «Recibimos tu nueva foto. Está pendiente de revisión.» y el estado se actualiza")

            # varios archivos, candidato de chat
            r = c.post(f"/candidatos/{PC}/vehiculo/decision", json={"accion": "correccion", "motivos": {"atras": "salió borrosa", "licencia": "está vencida"}}, headers=h)
            env = enviados[-1]
            check(env["boton"] == "Corregir archivos" and env["callback"] == "CORR-todos" and not env["url"]
                  and "• La foto de la parte de atrás de tu vehículo: salió borrosa." in env["texto"] and "• Tu licencia de conducir vigente: está vencida." in env["texto"]
                  and "por aquí" in env["texto"], "2.3/2.4 · varios → «Corregir archivos» con cada motivo; candidato de chat → corrige en el chat")
        r = mandar(update(7002, callback="CORR-todos"))
        check(r.get("accion") == "correccion_chat" and r.get("archivo") == "atras" and "salió borrosa" in r.get("respuesta", ""),
              "2.4 · el botón en el chat pide el archivo ahí mismo, con su motivo")
        with mock.patch.object(webhooks, "descargar_media", new=descarga_jpg):
            r = mandar(update(7002, foto=True))
        check(r.get("respuesta", "").startswith("Recibimos tu nueva foto. Está pendiente de revisión.") and "licencia" in r.get("respuesta", ""),
              "2.6 · en el chat: «Recibimos tu nueva foto…» y pide lo que falta")
        with mock.patch.object(webhooks, "descargar_media", new=descarga_pdf):
            r = mandar(update(7002, "mi licencia", documento=True))
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == PC).first()
            check(r.get("respuesta", "").startswith("Recibimos tu nuevo documento. Está pendiente de revisión.") and p.revision_vehiculo.estado == "por_revisar",
                  "2.6 · documento reemplazado por chat → pendiente de revisión y la revisión vuelve a «Fotos por revisar»")
        panel = c.get(f"/candidatos/{PC}/vehiculo", headers=h).json()["vehiculo"]
        check(panel["canal"] == "chat", "2 · la ficha de RH sabe por qué canal corrige el candidato")


if __name__ == "__main__":
    main()
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
