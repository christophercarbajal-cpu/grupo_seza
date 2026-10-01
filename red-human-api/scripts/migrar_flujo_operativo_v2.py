"""Migra el Kanban OPERATIVO de 8 columnas (v1) al de 6 (v2, 2026-09-30) en las Cuentas con flujo operativo.

    Nuevo → Prefiltro · Cita para capacitación / Capacitación realizada → Entrevista
    Documentos y referencias / Listo para alta → Onboarding · Alta realizada → Onboarding + CERRADA (contratado)

Además, la capacitación de la v1 (evaluación «Capacitación en tienda» en una sesión con cupo) se copia a una
`EntrevistaHumana` de la postulación (tienda, dirección, fecha, supervisor = capacitador, confirmación, asistencia y
resultado), que es donde la lee la v2. Nunca borra nada: la evaluación y la sesión viejas quedan como historial.

Seguridad: sin `--ejecutar` es SIMULACRO (muestra lo que haría y deshace). Idempotente: una postulación ya migrada
no se vuelve a tocar.

Uso (desde red-human-api/):
    python scripts/migrar_flujo_operativo_v2.py              # simulacro
    python scripts/migrar_flujo_operativo_v2.py --ejecutar   # aplica
"""

import argparse
import secrets
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from app.database import SessionLocal, engine  # noqa: E402
from app.migraciones import sincronizar  # noqa: E402
from app.models import (  # noqa: E402
    ETAPAS_OPERATIVO_LEGADO,
    NOMBRE_CAPACITACION_TIENDA,
    Cuenta,
    EntrevistaHumana,
    EvaluacionCandidato,
    Postulacion,
    SesionCapacitacion,
    registrar,
)

ACTOR = "script:migrar_flujo_operativo_v2"


def _copiar_capacitacion(db, p: Postulacion) -> bool:
    """Capacitación v1 (evaluación + sesión) → EntrevistaHumana v2. False si no había nada que copiar."""
    if any(not eh.cancelada for eh in p.entrevistas_humanas):
        return False
    ev = (db.query(EvaluacionCandidato)
          .filter(EvaluacionCandidato.postulacion_id == p.id, EvaluacionCandidato.tipo == "otra",
                  EvaluacionCandidato.nombre == NOMBRE_CAPACITACION_TIENDA, EvaluacionCandidato.sesion_id.isnot(None))
          .order_by(EvaluacionCandidato.id.desc()).first())
    s = db.get(SesionCapacitacion, ev.sesion_id) if ev else None
    if not s:
        return False
    asistio = ev.asistencia == "asistio"
    eh = EntrevistaHumana(
        candidato_id=p.candidato_id, token=secrets.token_urlsafe(24), tipo="externo", entrevistador=s.supervisor_nombre or "Supervisor",
        whatsapp_externo=s.supervisor_telefono or "", fecha=s.inicio, modalidad="Presencial", tienda=s.tienda, ubicacion=s.direccion or "",
        comentario=(ev.comentario_revision or ev.motivo_fallida or s.indicaciones or "")[:2000], confirmada_en=ev.cita_confirmada_en,
        asistencia=ev.asistencia or "", realizada=asistio, resultado=(ev.dictamen if asistio else "") or "",
        resultado_capturado_por="entrevistador" if ev.asistencia else "", evaluada_en=ev.revisada_en,
        curso_induccion_id=s.curso_induccion_id, envios=[],
    )
    p.entrevistas_humanas.append(eh)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ejecutar", action="store_true", help="aplica los cambios (sin esto es simulacro)")
    args = ap.parse_args()
    sincronizar(engine)  # columnas nuevas de la v2 (EntrevistaHumana.tienda, Expediente.contrato_operativo…)

    db = SessionLocal()
    try:
        cuentas = db.query(Cuenta).filter(Cuenta.flujo_candidatos == "operativo").all()
        print(("EJECUTANDO" if args.ejecutar else "SIMULACRO") + f" — {len(cuentas)} Cuenta(s) con flujo operativo")
        movidas, cerradas, copiadas = Counter(), 0, 0
        for cuenta in cuentas:
            ps = db.query(Postulacion).filter(Postulacion.cuenta_id == cuenta.id, Postulacion.etapa.in_(list(ETAPAS_OPERATIVO_LEGADO))).all()
            for p in ps:
                anterior, nueva = p.etapa, ETAPAS_OPERATIVO_LEGADO[p.etapa]
                if anterior in ("Cita para capacitación", "Capacitación realizada") and _copiar_capacitacion(db, p):
                    copiadas += 1
                p.etapa = nueva
                p.historial = [*(p.historial or []), {"evento": "migracion_v2", "texto": f"{anterior} → {nueva} (Kanban operativo v2)",
                                                      "usuario": ACTOR, "fecha": __import__("datetime").datetime.now().isoformat()}]
                if anterior == "Alta realizada" and p.activa:
                    p.cerrar("contratado")
                    cerradas += 1
                movidas[f"{anterior} → {nueva}"] += 1
            print(f"  {cuenta.nombre}: {len(ps)} postulación(es)")
        for k, n in sorted(movidas.items()):
            print(f"    {k}: {n}")
        print(f"  Capacitaciones copiadas a Entrevista: {copiadas} · Altas cerradas como contratado: {cerradas}")
        registrar(db, ACTOR, "flujo_operativo_v2_migrado", "sistema", "kanban-operativo",
                  {"movidas": dict(movidas), "cerradas": cerradas, "capacitaciones": copiadas, "simulacro": not args.ejecutar})
        if args.ejecutar:
            db.commit()
            print("✅ Migración aplicada.")
        else:
            db.rollback()
            print("✅ Simulacro correcto. Corre con --ejecutar para aplicar.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
