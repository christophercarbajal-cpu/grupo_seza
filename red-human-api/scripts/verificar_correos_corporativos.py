"""Regresión: todo correo sale con la plantilla HTML corporativa de Red Human (2026-10-01).

* `correo.enviar_correo` (único punto de salida, Resend) envuelve con `plantillas_correo.envolver` cualquier cuerpo
  que no traiga `plantillas_correo.MARCA_LAYOUT`: texto plano y HTML suelto salen dentro del layout; lo que ya trae la
  plantilla no se envuelve dos veces.
* El correo del curso asignado (`capacitacion._html_liga`) y los respaldos de entrevista
  (`notificaciones._html_correo_candidato / _html_correo_entrevistador`) usan la plantilla.

Uso (desde red-human-api/):  python scripts/verificar_correos_corporativos.py
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(tempfile.mkdtemp()) / 'correos.db').as_posix()}"
sys.path.insert(0, str(RAIZ))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import correo as correo_srv  # noqa: E402
from app.services import plantillas_correo  # noqa: E402

FALLAS = []


def check(cond, nombre):
    print(("✅ " if cond else "❌ ") + nombre)
    if not cond:
        FALLAS.append(nombre)


def main():
    enviados = []

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "re_1"}

    async def post_falso(self, url, headers=None, json=None):
        enviados.append(json)
        return Resp()

    with mock.patch.object(settings, "resend_api_key", "re_prueba"), mock.patch.object(httpx.AsyncClient, "post", post_falso):
        r1 = asyncio.run(correo_srv.enviar_correo("a@demo.invalid", "Aviso", "Texto plano sin formato\nSegunda línea"))
        asyncio.run(correo_srv.enviar_correo("a@demo.invalid", "Aviso", "<p>HTML suelto</p>"))
        asunto, html = plantillas_correo.html_aviso("Título", "Párrafo")
        asyncio.run(correo_srv.enviar_correo("a@demo.invalid", asunto, html))
    marca = plantillas_correo.MARCA_LAYOUT
    check(r1["enviado"] and len(enviados) == 3, "los tres correos salen por Resend")
    check(marca in enviados[0]["html"] and "Texto plano sin formato" in enviados[0]["html"] and "<!doctype html>" in enviados[0]["html"],
          "un cuerpo en texto plano sale dentro de la plantilla corporativa")
    check(marca in enviados[1]["html"] and "<p>HTML suelto</p>" in enviados[1]["html"], "un HTML suelto se envuelve en la plantilla corporativa")
    check(enviados[2]["html"].count(marca) == 1, "lo que ya trae la plantilla no se envuelve dos veces")
    check(marca in html, "las plantillas propias (html_aviso…) llevan la marca del layout")

    from app.routers.capacitacion import _html_liga

    curso = mock.Mock(titulo="Inducción", duracion_horas=1)
    check(marca in _html_liga("Ana", curso, "https://x", "candidato"), "el correo del curso asignado usa la plantilla corporativa")

    from app.services import notificaciones

    eh = mock.Mock(fecha=datetime(2030, 1, 15, 15, 0, tzinfo=timezone.utc), entrevistador="Gerente", modalidad="Presencial", comentario="Llega temprano")
    c = mock.Mock(nombre="Ana Pérez", telefono="5511112222", vacante=mock.Mock(titulo="Chofer"))
    with mock.patch.object(notificaciones, "_detalle_modalidad", return_value="Tienda Centro"):
        cand = notificaciones._html_correo_candidato(eh, c)
        entr = notificaciones._html_correo_entrevistador(eh, c)
    check(marca in cand and "Gerente" in cand and marca in entr and "Ana Pérez" in entr,
          "los respaldos de entrevista (candidato / entrevistador) usan la plantilla corporativa")


if __name__ == "__main__":
    main()
    print("\n" + ("❌ FALLAS: " + ", ".join(FALLAS) if FALLAS else "✅ Todo en orden"))
    sys.exit(1 if FALLAS else 0)
