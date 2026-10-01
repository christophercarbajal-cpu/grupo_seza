"""Regresión: validación básica de documentos y fotos (2026-10-01) sobre una base DESECHABLE.

Solo se valida el TIPO de archivo (el servicio de visión se simula): «coincide» → se guarda y queda «Recibido»; «no
coincide» → NO se guarda y el mensaje es «El archivo no corresponde a [requisito]. Carga el archivo solicitado.»;
«ilegible» → NO se guarda y se pide una imagen más clara; el servicio falla o tarda → se guarda como «Pendiente de
revisión» y el requisito NO queda completo. Aplica a la liga del expediente, la captura de RH, el adjunto por chat y las
fotos del vehículo. Lo capturado como texto (referencias) no pasa por la validación.

Uso (desde red-human-api/):  python scripts/verificar_validacion_documentos.py
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
BASE = Path(tempfile.mkdtemp()) / "validacion.db"
os.environ["DATABASE_URL"] = f"sqlite:///{BASE.as_posix()}"
os.environ["ADMIN_PASSWORD"] = "Verificar123!"
os.environ["WHATSAPP_PROVIDER"] = ""
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


def check(cond, nombre):
    print(("✅ " if cond else "❌ ") + nombre)
    if not cond:
        FALLAS.append(nombre)


def resultado(valor):
    """Simula al servicio de visión con un resultado fijo (o una excepción)."""
    from app.services import ia

    if isinstance(valor, Exception):
        return mock.patch.object(ia, "clasificar_tipo_archivo", side_effect=valor)
    return mock.patch.object(ia, "clasificar_tipo_archivo", return_value=ia.ClasificacionArchivo(resultado=valor, tipo_detectado="x", observaciones="ok"))


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
    from app.models import Documento, Postulacion
    from app.services import ia, validacion_archivos as va

    # ---- mapeo de requisitos ----
    esperado = {
        "Fotos del vehículo": "automóvil", "Licencia de conducir vigente": "Licencia de conducir", "Tarjeta de circulación": "Tarjeta de circulación",
        "Póliza de seguro vigente": "Póliza de seguro vehicular", "Identificación oficial (INE)": "Credencial INE",
        "Comprobante de domicilio": "comprobante de domicilio", "CURP": "Constancia de CURP",
        "Constancia de Situación Fiscal / RFC": "Constancia de Situación Fiscal o documento de RFC",
        "Número de Seguridad Social": "NSS", "Cuenta bancaria / CLABE": "CLABE",
    }
    check(all(v in va.descripcion(k) for k, v in esperado.items()), "los 10 requisitos se mapean a lo que debe contener el archivo")

    with TestClient(app) as c, mock.patch.object(ia, "ia_activa", return_value=True):
        c.post("/auth/login", json={"correo": "admin@redhuman.mx", "password": "Verificar123!"})
        cuentas = c.get("/cuentas").json()
        h = {"X-Cuenta-Id": str(next((x["id"] for x in cuentas if "SEZA" in x.get("nombre", "")), 1))}
        tarjetas = {t["nombre"]: t for t in c.get("/candidatos", headers=h).json()}

        # ---- documentos del expediente por la liga pública ----
        P = tarjetas["Gabriela Medina Luján"]["id"]
        with SessionLocal() as db:
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            tok, exp_id = p.expediente.token, p.expediente.id

        def doc(tipo):
            with SessionLocal() as db:
                return db.query(Documento).filter(Documento.expediente_id == exp_id, Documento.tipo == tipo).first()

        def subir(tipo, contenido=PDF, nombre="a.pdf"):
            return c.post(f"/expedientes/publica/{tok}/documentos", data={"tipo": tipo}, files={"archivo": (nombre, contenido, "application/pdf" if nombre.endswith("pdf") else "image/jpeg")})

        with resultado("no_coincide"):
            r = subir("Comprobante de domicilio")
        d = doc("Comprobante de domicilio")
        check(r.status_code == 422 and r.json()["detail"] == "El archivo no corresponde a Comprobante de domicilio. Carga el archivo solicitado."
              and not d.archivo and d.estado == "pendiente", "no coincide → mensaje exacto, el archivo NO se guarda y el requisito sigue pendiente")
        with resultado("ilegible"):
            r = subir("CURP", JPG, "curp.jpg")
        check(r.status_code == 422 and "más clara" in r.json()["detail"] and not doc("CURP").archivo, "ilegible → pide una imagen más clara y permite reintentar (no se guarda)")
        with resultado("coincide"):
            r = subir("CURP", JPG, "curp.jpg")
        d = doc("CURP")
        check(r.status_code == 200 and d.archivo and d.estado == "recibido" and (d.validacion or {}).get("resultado") == "coincide",
              "coincide → se guarda y el requisito queda «Recibido»")
        with resultado(TimeoutError("timeout del servicio")):
            r = subir("Comprobante de domicilio")
        d = doc("Comprobante de domicilio")
        panel = c.get(f"/candidatos/{P}/operativo", headers=h).json()
        simple = next(x["estadoSimple"] for x in panel["expediente"]["documentos"] if x["tipo"] == "Comprobante de domicilio")
        check(r.status_code == 200 and d.archivo and d.estado == "revision" and simple == "Pendiente de revisión" and not d.aprobado
              and "Documento: Comprobante de domicilio" in " ".join(panel["faltantesAlta"]),
              "el servicio falla → se guarda como «Pendiente de revisión» y el requisito NO queda completo")

        # ---- captura de RH desde la ficha ----
        with resultado("no_coincide"):
            r = c.post(f"/contratacion/expedientes/{exp_id}/documentos", data={"tipo": "Constancia de Situación Fiscal / RFC"},
                       files={"archivo": ("rfc.pdf", PDF, "application/pdf")}, headers=h)
        check(r.status_code == 422 and r.json()["detail"].startswith("El archivo no corresponde a Constancia de Situación Fiscal / RFC"),
              "la captura de RH pasa por la misma validación")

        # ---- adjunto por chat (Telegram/WhatsApp) ----
        from app.routers import webhooks

        enviados = []

        async def enviar_falso(tel, texto):
            enviados.append(texto)
            return {"enviado": True}

        with SessionLocal() as db, resultado("no_coincide"), \
             mock.patch.object(webhooks, "descargar_media", new=mock.AsyncMock(return_value={"ok": True, "contenido": PDF, "filename": "ine.pdf", "mime": "application/pdf"})), \
             mock.patch.object(webhooks, "enviar_mensaje", side_effect=enviar_falso):
            p = db.query(Postulacion).filter(Postulacion.codigo == P).first()
            res = asyncio.run(webhooks._recibir_documento_whatsapp(db, p, {"media": {"id": "m1", "filename": "ine.pdf"}, "texto": "mi INE", "tipo": "document", "wa_id": "tg-1"}, "2220000000"))
        check(res.get("error") == "El archivo no corresponde a Identificación oficial (INE). Carga el archivo solicitado."
              and enviados and enviados[-1] == res["error"] and not doc("Identificación oficial (INE)").archivo,
              "por chat: el bot responde el mismo mensaje y el archivo no se guarda")

        # ---- texto plano (referencias): no pasa por la validación ----
        with mock.patch.object(ia, "clasificar_tipo_archivo") as clasif:
            r = c.post(f"/expedientes/publica/{tok}/referencias", json={"referencias": [
                {"nombre": "Ref Uno", "telefono": "5511111111", "parentesco": "Familiar"}, {"nombre": "Ref Dos", "telefono": "5522222222", "parentesco": "Amistad"},
                {"nombre": "Ref Tres", "telefono": "5533333333", "parentesco": "Vecino(a)"}]})
            check(r.status_code == 200 and not clasif.called, "las referencias tecleadas NO pasan por la validación de archivos")

        # ---- fotos del vehículo ----
        V = tarjetas["Luis Fernando Ortega"]["id"]
        with SessionLocal() as db:
            pv = db.query(Postulacion).filter(Postulacion.codigo == V).first()
            vtok = pv.revision_vehiculo.token

        def foto(lado):
            return c.post(f"/vehiculo/publica/{vtok}/foto", data={"lado": lado}, files={"archivo": ("f.jpg", JPG, "image/jpeg")})

        with resultado("no_coincide"):
            r = foto("frente")
        pub = c.get(f"/vehiculo/publica/{vtok}").json()
        check(r.status_code == 422 and r.json()["detail"].startswith("El archivo no corresponde a la foto del vehículo (frente)")
              and not next(x for x in pub["lados"] if x["clave"] == "frente")["cargada"], "foto que no es de un automóvil → rechazada y no se guarda")
        with resultado("coincide"):
            for lado in ("frente", "atras", "izquierdo"):
                foto(lado)
        with resultado(RuntimeError("caída del servicio")):
            r = foto("derecho")
        flujo = c.get(f"/candidatos/{V}/vehiculo", headers=h).json()["vehiculo"]
        pend = next(x for x in flujo["fotos"] if x["lado"] == "derecho")
        check(r.status_code == 200 and pend["cargada"] and pend["pendienteRevision"], "el servicio falla → la foto se guarda como «Pendiente de revisión»")
        with SessionLocal() as db:
            from app.services import vehiculo as vsrv
            pv = db.query(Postulacion).filter(Postulacion.codigo == V).first()
            check(not vsrv.completo(pv.revision_vehiculo), "una foto pendiente de revisión NO completa el requisito del vehículo")

        # ---- alcance: solo el tipo (el prompt no evalúa vigencia, nombre ni autenticidad) ----
        import inspect

        fuente = inspect.getsource(ia.clasificar_tipo_archivo)
        check("NO evalúes vigencia" in fuente and "TIPO" in fuente, "el clasificador solo identifica el tipo (sin vigencia, nombre, autenticidad ni estado físico)")


if __name__ == "__main__":
    main()
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
