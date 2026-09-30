"use client";

/* Sesiones de «Capacitación en tienda» (demo Grupo SEZA, 2026-09-29).

   Sesiones compartidas con cupo: RH las crea (tienda, fecha, cupo, supervisor, curso de inducción) y cita a los
   candidatos desde su ficha. El supervisor registra asistencia y resultado (Apto / Requiere seguimiento / No
   apto) desde su liga, sin entrar al sistema. Aquí RH ve la ocupación, los citados y copia esa liga. */

import { useCallback, useEffect, useState } from "react";
import { CalendarPlus, ExternalLink, Users } from "lucide-react";
import { Badge, Button, Card } from "@/components/ui";
import { PageHeader } from "@/components/dashboard/parts";
import { AvisoLinea, CampoRH, Cargando, ModalMarco, inputRH, type AvisoRH } from "@/components/dashboard/modulos-rh";
import { BotonCopiar } from "@/components/dashboard/subida";
import { usePuedeDecidir } from "@/components/sesion";
import { usePolling } from "@/lib/use-polling";
import { cn } from "@/lib/utils";
import {
  crearSesionCapacitacion,
  estadoSesionCapacitacion,
  fetchCursos,
  fetchSesionCapacitacion,
  fetchSesionesCapacitacion,
  fetchVacantes,
  type CamposSesion,
  type Curso,
  type SesionCapacitacion,
} from "@/lib/api";
import type { Vacante } from "@/lib/data";

const TONO_RESULTADO: Record<string, "good" | "warn" | "bad"> = { favorable: "good", con_observaciones: "warn", desfavorable: "bad" };

export default function Sesiones() {
  const puedeDecidir = usePuedeDecidir();
  const [sesiones, setSesiones] = useState<SesionCapacitacion[] | null>(null);
  const [pasadas, setPasadas] = useState(false);
  const [nueva, setNueva] = useState(false);
  const [detalle, setDetalle] = useState<SesionCapacitacion | null>(null);
  const [aviso, setAviso] = useState<AvisoRH>(null);

  const cargar = useCallback(async () => {
    const s = await fetchSesionesCapacitacion(pasadas);
    setSesiones(s ?? []);
  }, [pasadas]);
  useEffect(() => {
    cargar();
  }, [cargar]);
  usePolling(cargar, 30000);

  async function abrir(codigo: string) {
    const s = await fetchSesionCapacitacion(codigo);
    if (s) setDetalle(s);
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      <PageHeader title="Sesiones de capacitación" subtitle="Capacitación en tienda con cupo · el supervisor registra asistencia y resultado desde su liga">
        {puedeDecidir && (
          <Button onClick={() => setNueva(true)}>
            <CalendarPlus className="h-4 w-4" /> Nueva sesión
          </Button>
        )}
      </PageHeader>
      {aviso && <AvisoLinea aviso={aviso} onCerrar={() => setAviso(null)} />}

      <label className="mt-4 flex items-center gap-2 text-sm text-ink-2">
        <input type="checkbox" checked={pasadas} onChange={(e) => setPasadas(e.target.checked)} className="h-4 w-4 accent-[var(--brand)]" />
        Mostrar sesiones realizadas y canceladas
      </label>

      {sesiones === null ? (
        <Cargando />
      ) : sesiones.length === 0 ? (
        <Card className="mt-4 p-8 text-center text-sm text-ink-3">No hay sesiones programadas. Crea la primera con «Nueva sesión».</Card>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sesiones.map((s) => {
            const lleno = s.disponibles === 0;
            return (
              <button key={s.codigo} type="button" onClick={() => abrir(s.codigo)} className="text-left">
                <Card className="h-full p-4 transition hover:border-brand/50">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-mono text-[11px] text-ink-3">{s.codigo}</p>
                      <p className="font-semibold text-ink">{s.tienda}</p>
                      <p className="text-[13px] text-ink-2">{s.inicioTexto} h</p>
                    </div>
                    <Badge tone={s.estado === "programada" ? (lleno ? "warn" : "good") : "neutral"} dot>
                      {s.estado === "programada" ? (lleno ? "Llena" : "Programada") : s.estado === "cerrada" ? "Realizada" : "Cancelada"}
                    </Badge>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2">
                    <div className={cn("h-full rounded-full", lleno ? "bg-warn" : "bg-brand")} style={{ width: `${Math.min(100, (s.ocupados / Math.max(1, s.cupo)) * 100)}%` }} />
                  </div>
                  <p className="mt-1.5 flex items-center gap-1.5 text-[12px] text-ink-3">
                    <Users className="h-3.5 w-3.5" /> {s.ocupados} de {s.cupo} lugares
                    {s.vacanteTitulo ? ` · ${s.vacanteTitulo}` : ""}
                  </p>
                  {s.supervisorNombre && <p className="text-[12px] text-ink-3">Supervisor: {s.supervisorNombre}</p>}
                </Card>
              </button>
            );
          })}
        </div>
      )}

      {nueva && (
        <NuevaSesion
          onClose={() => setNueva(false)}
          onCreada={(s) => {
            setNueva(false);
            setAviso({ tono: "ok", texto: `Sesión ${s.codigo} creada. Copia la liga del supervisor desde su detalle.` });
            cargar();
          }}
        />
      )}
      {detalle && (
        <DetalleSesion
          s={detalle}
          puedeDecidir={puedeDecidir}
          onClose={() => setDetalle(null)}
          onCambio={(s) => {
            setDetalle(s);
            cargar();
          }}
        />
      )}
    </div>
  );
}

function NuevaSesion({ onClose, onCreada }: { onClose: () => void; onCreada: (s: SesionCapacitacion) => void }) {
  const [f, setF] = useState<CamposSesion>({ tienda: "", direccion: "", inicio: "", cupo: 10, duracion_min: 180, supervisor_nombre: "", supervisor_telefono: "", indicaciones: "", vacante: "", curso_induccion: "" });
  const [vacantes, setVacantes] = useState<Vacante[]>([]);
  const [cursos, setCursos] = useState<Curso[]>([]);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);
  useEffect(() => {
    fetchVacantes({ estado: "Publicada" }).then((v) => setVacantes(v ?? []));
    fetchCursos().then((c) => setCursos(c ?? []));
  }, []);
  const set = (k: keyof CamposSesion, v: string | number) => setF((x) => ({ ...x, [k]: v }));

  async function guardar() {
    setGuardando(true);
    setError("");
    const r = await crearSesionCapacitacion({ ...f, vacante: f.vacante || null, curso_induccion: f.curso_induccion || null });
    setGuardando(false);
    if (!r.ok) return setError(r.error);
    onCreada(r.data);
  }

  return (
    <ModalMarco titulo="Nueva sesión de capacitación" subtitulo="Capacitación en tienda · sesión compartida con cupo" onClose={onClose}>
      <div className="grid gap-3 sm:grid-cols-2">
        <CampoRH label="Tienda o lugar">
          <input className={inputRH} value={f.tienda} onChange={(e) => set("tienda", e.target.value)} placeholder="Tienda SEZA Angelópolis" />
        </CampoRH>
        <CampoRH label="Fecha y hora">
          <input type="datetime-local" className={inputRH} value={f.inicio} onChange={(e) => set("inicio", e.target.value)} />
        </CampoRH>
        <CampoRH label="Dirección">
          <input className={inputRH} value={f.direccion} onChange={(e) => set("direccion", e.target.value)} />
        </CampoRH>
        <CampoRH label="Cupo">
          <input type="number" min={1} max={200} className={inputRH} value={f.cupo} onChange={(e) => set("cupo", Number(e.target.value))} />
        </CampoRH>
        <CampoRH label="Supervisor (nombre)">
          <input className={inputRH} value={f.supervisor_nombre} onChange={(e) => set("supervisor_nombre", e.target.value)} />
        </CampoRH>
        <CampoRH label="Supervisor (WhatsApp)">
          <input className={inputRH} value={f.supervisor_telefono} onChange={(e) => set("supervisor_telefono", e.target.value)} inputMode="tel" />
        </CampoRH>
        <CampoRH label="Vacante / plaza (opcional)">
          <select className={inputRH} value={f.vacante ?? ""} onChange={(e) => set("vacante", e.target.value)}>
            <option value="">Todas</option>
            {vacantes.map((v) => (
              <option key={v.id} value={v.id}>
                {v.titulo} · {v.ubicacion}
              </option>
            ))}
          </select>
        </CampoRH>
        <CampoRH label="Curso de inducción (PDF al confirmar la cita)">
          <select className={inputRH} value={f.curso_induccion ?? ""} onChange={(e) => set("curso_induccion", e.target.value)}>
            <option value="">Ninguno</option>
            {cursos.map((c) => (
              <option key={c.id} value={c.id}>
                {c.titulo}
              </option>
            ))}
          </select>
        </CampoRH>
        <div className="sm:col-span-2">
          <CampoRH label="Indicaciones para el candidato (opcional)">
            <input className={inputRH} value={f.indicaciones} onChange={(e) => set("indicaciones", e.target.value)} placeholder="Llega 15 minutos antes con INE y licencia" />
          </CampoRH>
        </div>
      </div>
      {error && <p className="mt-3 text-sm text-bad">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancelar</Button>
        <Button onClick={guardar} disabled={guardando || !f.tienda.trim() || !f.inicio}>
          {guardando ? "Guardando…" : "Crear sesión"}
        </Button>
      </div>
    </ModalMarco>
  );
}

function DetalleSesion({ s, puedeDecidir, onClose, onCambio }: { s: SesionCapacitacion; puedeDecidir: boolean; onClose: () => void; onCambio: (s: SesionCapacitacion) => void }) {
  const [ocupado, setOcupado] = useState(false);
  async function cambiarEstado(estado: "cerrada" | "cancelada" | "programada") {
    setOcupado(true);
    const r = await estadoSesionCapacitacion(s.codigo, estado);
    setOcupado(false);
    if (r.ok) onCambio(r.data);
  }
  return (
    <ModalMarco titulo={`${s.tienda} · ${s.inicioTexto} h`} subtitulo={`${s.codigo} · ${s.ocupados} de ${s.cupo} lugares${s.cursoInduccionTitulo ? ` · Inducción: ${s.cursoInduccionTitulo}` : ""}`} onClose={onClose}>
      <div className="flex flex-wrap items-center gap-2 rounded-xl bg-surface-2 px-3 py-2">
        <span className="text-[12px] font-medium text-ink-2">Liga del supervisor:</span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3">{s.ligaSupervisor}</span>
        <BotonCopiar texto={s.ligaSupervisor} etiqueta="Copiar" />
        <a href={s.ligaSupervisor} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">
          Abrir <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
      <div className="scroll-x mt-4 rounded-xl border border-border-soft">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-border-faint text-left text-[11px] uppercase tracking-wide text-ink-3">
              <th className="px-3 py-2">Candidato</th>
              <th className="px-3 py-2">Cita</th>
              <th className="px-3 py-2">Resultado</th>
            </tr>
          </thead>
          <tbody>
            {(s.citados ?? []).length === 0 && (
              <tr>
                <td colSpan={3} className="px-3 py-4 text-center text-ink-3">Aún no hay citados. Cita candidatos desde su ficha (pestaña «Capacitación y alta»).</td>
              </tr>
            )}
            {(s.citados ?? []).map((c) => (
              <tr key={c.evaluacion} className="border-b border-border-faint last:border-0">
                <td className="px-3 py-2">
                  <span className="font-medium text-ink">{c.nombre}</span> <span className="font-mono text-[11px] text-ink-3">{c.postulacion}</span>
                  <span className="block text-[12px] text-ink-3">{c.vacante}</span>
                </td>
                <td className="px-3 py-2 text-ink-2">{c.confirmada ? "Confirmada" : "Por confirmar"}</td>
                <td className="px-3 py-2">
                  {c.resultado ? (
                    <Badge tone={TONO_RESULTADO[c.resultado]} dot>{c.resultadoEtiqueta}</Badge>
                  ) : c.asistencia === "no_asistio" ? (
                    <Badge tone="bad">No asistió</Badge>
                  ) : (
                    <span className="text-ink-3">Pendiente</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {puedeDecidir && s.estado === "programada" && (
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" disabled={ocupado} onClick={() => cambiarEstado("cancelada")}>Cancelar sesión</Button>
          <Button variant="outline" size="sm" disabled={ocupado} onClick={() => cambiarEstado("cerrada")}>Marcar como realizada</Button>
        </div>
      )}
    </ModalMarco>
  );
}
