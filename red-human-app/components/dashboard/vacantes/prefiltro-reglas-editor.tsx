"use client";

/* Reglas del prefiltro de ESTA vacante (demo Grupo SEZA, 2026-09-29).

   Las 12 preguntas son las del documento del cliente; lo que cambia por plaza se guarda aquí: jornada,
   ubicación y zona que se mencionan en las preguntas, cobertura de municipios, si la experiencia es
   indispensable, tipos de vehículo y año mínimo (vacío = sin mínimo), si el CV es obligatorio y qué hace
   cada respuesta. Regla del documento: fuera de parámetro o posible excepción = revisión humana; documento
   pendiente no es descarte. Se guarda en `Vacante.prefiltro_reglas` (PATCH /vacantes/{codigo}); quien
   evalúa es el backend (services/prefiltro_reglas.py). */

import { useState } from "react";
import { Save } from "lucide-react";
import { Button } from "@/components/ui";
import { Aviso } from "@/components/dashboard/subida";
import { actualizarVacante } from "@/lib/api";
import { DIAS_OPERACION, TIPOS_VEHICULO, type ConfigPrefiltroReglas, type Vacante } from "@/lib/data";

type Efecto = "ok" | "revision" | "no_cumple";

/** Respuestas configurables y su efecto por defecto (espejo de prefiltro_reglas.REGLAS_BASE + evaluar()). */
const CONFIGURABLES: { id: string; valor: string; respuesta: string; base: Efecto }[] = [
  { id: "municipio", valor: "fuera_cobertura", respuesta: "Fuera de la cobertura", base: "revision" },
  { id: "jornada", valor: "no", respuesta: "No", base: "no_cumple" },
  { id: "zona", valor: "no", respuesta: "No", base: "no_cumple" },
  { id: "vehiculo_propio", valor: "no", respuesta: "No", base: "no_cumple" },
  { id: "tipo_vehiculo", valor: "no_permitido", respuesta: "Tipo no aceptado", base: "revision" },
  { id: "anio_vehiculo", valor: "menor_al_minimo", respuesta: "Menor al año mínimo", base: "revision" },
  { id: "taxi", valor: "si", respuesta: "Sí (rotulado)", base: "revision" },
  { id: "circulacion", valor: "no", respuesta: "No", base: "revision" },
  { id: "licencia", valor: "no tengo licencia vigente", respuesta: "No tengo licencia vigente", base: "revision" },
  { id: "licencia", valor: "no_aceptada", respuesta: "Tipo no aceptado", base: "revision" },
  { id: "poliza", valor: "no", respuesta: "No", base: "revision" },
  { id: "android", valor: "no", respuesta: "No", base: "no_cumple" },
];
const EFECTOS: { valor: Efecto; texto: string }[] = [
  { valor: "ok", texto: "Sigue" },
  { valor: "revision", texto: "Revisión humana" },
  { valor: "no_cumple", texto: "No cumple" },
];

const vacia = (ubicacion: string): ConfigPrefiltroReglas => ({
  activo: true,
  jornada_horas: null,
  ubicacion_texto: ubicacion,
  zona: "",
  cobertura: [],
  experiencia_indispensable: false,
  dias_operacion: "diario",
  licencias_aceptadas: [],
  vehiculo: { tipos_permitidos: [TIPOS_VEHICULO[0]], anio_minimo: null },
  reglas: {},
  fotos_vehiculo: true,
});

export function PrefiltroReglasEditor({ v, editable, onGuardada }: { v: Vacante; editable: boolean; onGuardada: () => void }) {
  const inicial = v.prefiltroReglas && "activo" in v.prefiltroReglas ? (v.prefiltroReglas as ConfigPrefiltroReglas) : null;
  const [cfg, setCfg] = useState<ConfigPrefiltroReglas>({ ...vacia(v.ubicacion ?? ""), ...(inicial ?? {}) });
  const [cobertura, setCobertura] = useState((inicial?.cobertura ?? []).join(", "));
  const [activo, setActivo] = useState(Boolean(inicial?.activo));
  const [cvObligatorio, setCvObligatorio] = useState(v.cvObligatorio !== false);
  const [guardando, setGuardando] = useState(false);
  const [aviso, setAviso] = useState<{ tono: "ok" | "error"; texto: string } | null>(null);
  const textos = Object.fromEntries((v.prefiltroPreguntas ?? []).map((q) => [q.id, q.texto]));
  // tipos de licencia del Estado de la vacante (la última opción es «No tengo licencia vigente»)
  const licencias = ((v.prefiltroPreguntas ?? []).find((q) => q.id === "licencia")?.opciones ?? []).slice(0, -1);
  const aceptadas = cfg.licencias_aceptadas?.length ? cfg.licencias_aceptadas : licencias.filter((l) => !/motociclista/i.test(l));
  function alternarLicencia(l: string) {
    setCfg((c) => ({ ...c, licencias_aceptadas: aceptadas.includes(l) ? aceptadas.filter((x) => x !== l) : [...aceptadas, l] }));
  }

  const efecto = (id: string, valor: string, base: Efecto): Efecto => cfg.reglas[id]?.[valor] ?? base;
  function cambiarEfecto(id: string, valor: string, e: Efecto) {
    setCfg((c) => ({ ...c, reglas: { ...c.reglas, [id]: { ...(c.reglas[id] ?? {}), [valor]: e } } }));
  }
  function alternarTipo(t: string) {
    setCfg((c) => {
      const tipos = c.vehiculo.tipos_permitidos.includes(t) ? c.vehiculo.tipos_permitidos.filter((x) => x !== t) : [...c.vehiculo.tipos_permitidos, t];
      return { ...c, vehiculo: { ...c.vehiculo, tipos_permitidos: tipos } };
    });
  }

  async function guardar() {
    setGuardando(true);
    setAviso(null);
    const listaCobertura = cobertura.split(",").map((m) => m.trim()).filter(Boolean);
    const r = await actualizarVacante(v.id, {
      prefiltro_reglas: activo ? { ...cfg, activo: true, cobertura: listaCobertura } : {},
      cv_obligatorio: cvObligatorio,
    });
    setGuardando(false);
    if (!r.ok) return setAviso({ tono: "error", texto: r.error });
    setAviso({ tono: "ok", texto: "Reglas guardadas. Aplican a las postulaciones que terminen el prefiltro desde ahora." });
    onGuardada();
  }

  const campo = "h-11 w-full rounded-xl border border-border-soft bg-surface px-3 text-sm outline-none focus:border-brand disabled:opacity-60";
  const casilla = "h-4 w-4 accent-[var(--brand)]";

  return (
    <div className="flex flex-col gap-4">
      {aviso && (
        <Aviso tono={aviso.tono} onCerrar={() => setAviso(null)}>
          {aviso.texto}
        </Aviso>
      )}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={activo} disabled={!editable} onChange={(e) => setActivo(e.target.checked)} className={casilla} />
        Usar prefiltro por reglas (preguntas fijas, web y WhatsApp) en lugar del prefiltro conversacional
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={cvObligatorio} disabled={!editable} onChange={(e) => setCvObligatorio(e.target.checked)} className={casilla} />
        El CV es obligatorio al postularse por la web
      </label>

      {activo && (
        <>
          <p className="rounded-xl bg-surface-2 p-3 text-[12px] text-ink-3">
            Regla del documento: fuera de parámetro o posible excepción = revisión humana; documento pendiente no es descarte.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-[12px] font-medium text-ink-2">Jornada (horas)</span>
              <input type="number" min={1} max={24} className={campo} disabled={!editable} value={cfg.jornada_horas ?? ""}
                onChange={(e) => setCfg((c) => ({ ...c, jornada_horas: e.target.value ? Number(e.target.value) : null }))} />
            </label>
            <label className="block">
              <span className="text-[12px] font-medium text-ink-2">Ubicación que menciona la pregunta de jornada</span>
              <input className={campo} disabled={!editable} value={cfg.ubicacion_texto}
                onChange={(e) => setCfg((c) => ({ ...c, ubicacion_texto: e.target.value }))} />
            </label>
            <label className="block">
              <span className="text-[12px] font-medium text-ink-2">Zona de entregas (vacía = no se pregunta)</span>
              <input className={campo} disabled={!editable} value={cfg.zona} placeholder="Ej. Centro y Angelópolis"
                onChange={(e) => setCfg((c) => ({ ...c, zona: e.target.value }))} />
            </label>
            <label className="block">
              <span className="text-[12px] font-medium text-ink-2">Municipios con cobertura (separados por coma; vacío = no descarta)</span>
              <input className={campo} disabled={!editable} value={cobertura} placeholder="Ej. Puebla, San Andrés Cholula"
                onChange={(e) => setCobertura(e.target.value)} />
            </label>
            <label className="block">
              <span className="text-[12px] font-medium text-ink-2">Año mínimo del vehículo (vacío = sin mínimo)</span>
              <input type="number" min={1950} className={campo} disabled={!editable} value={cfg.vehiculo.anio_minimo ?? ""}
                onChange={(e) => setCfg((c) => ({ ...c, vehiculo: { ...c.vehiculo, anio_minimo: e.target.value ? Number(e.target.value) : null } }))} />
            </label>
            <label className="block">
              <span className="text-[12px] font-medium text-ink-2">Días de operación (pregunta de circulación)</span>
              <select className={campo} disabled={!editable} value={cfg.dias_operacion ?? "diario"}
                onChange={(e) => setCfg((c) => ({ ...c, dias_operacion: e.target.value }))}>
                {DIAS_OPERACION.map((d) => (
                  <option key={d.valor} value={d.valor}>
                    {d.texto}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 self-end pb-3 text-sm">
              <input type="checkbox" disabled={!editable} checked={cfg.experiencia_indispensable}
                onChange={(e) => setCfg((c) => ({ ...c, experiencia_indispensable: e.target.checked }))} className={casilla} />
              Experiencia como chofer o repartidor indispensable
            </label>
          </div>
          <div>
            <p className="text-[12px] font-medium text-ink-2">Vehículos aceptados</p>
            <div className="mt-1.5 flex flex-wrap gap-2">
              {TIPOS_VEHICULO.map((t) => (
                <label key={t} className="flex min-h-10 items-center gap-2 rounded-xl border border-border-soft px-3 text-sm">
                  <input type="checkbox" disabled={!editable} checked={cfg.vehiculo.tipos_permitidos.includes(t)} onChange={() => alternarTipo(t)} className={casilla} />
                  {t}
                </label>
              ))}
            </div>
          </div>
          {licencias.length > 0 && (
            <div>
              <p className="text-[12px] font-medium text-ink-2">
                Licencias aceptadas{cfg.estado ? ` (${cfg.estado})` : ""} — otro tipo o sin licencia va a revisión
              </p>
              <div className="mt-1.5 flex flex-wrap gap-2">
                {licencias.map((l) => (
                  <label key={l} className="flex min-h-10 items-center gap-2 rounded-xl border border-border-soft px-3 text-sm">
                    <input type="checkbox" disabled={!editable} checked={aceptadas.includes(l)} onChange={() => alternarLicencia(l)} className={casilla} />
                    {l}
                  </label>
                ))}
              </div>
            </div>
          )}
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" disabled={!editable} checked={cfg.fotos_vehiculo}
              onChange={(e) => setCfg((c) => ({ ...c, fotos_vehiculo: e.target.checked }))} className={casilla} />
            Pedir fotos del vehículo (frente, atrás y costados) antes de citar
          </label>

          <div className="scroll-x rounded-xl border border-border-soft">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-border-faint text-left text-[11px] uppercase tracking-wide text-ink-3">
                  <th className="px-3 py-2">Pregunta</th>
                  <th className="px-3 py-2">Respuesta</th>
                  <th className="px-3 py-2">Efecto</th>
                </tr>
              </thead>
              <tbody>
                {CONFIGURABLES.filter((x) => x.id !== "zona" || cfg.zona.trim()).map((x) => (
                  <tr key={`${x.id}-${x.valor}`} className="border-b border-border-faint last:border-0">
                    <td className="whitespace-normal px-3 py-2 text-ink-2">{textos[x.id] ?? x.id}</td>
                    <td className="px-3 py-2 text-ink-3">{x.respuesta}</td>
                    <td className="px-3 py-2">
                      <select disabled={!editable} value={efecto(x.id, x.valor, x.base)} onChange={(e) => cambiarEfecto(x.id, x.valor, e.target.value as Efecto)}
                        className="h-9 rounded-lg border border-border-soft bg-surface px-2 text-[13px]">
                        {EFECTOS.map((o) => (
                          <option key={o.valor} value={o.valor}>
                            {o.texto}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {editable && (
        <div className="flex justify-end">
          <Button size="sm" onClick={guardar} disabled={guardando}>
            <Save className="h-4 w-4" /> {guardando ? "Guardando…" : "Guardar reglas"}
          </Button>
        </div>
      )}
    </div>
  );
}
