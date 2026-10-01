"use client";

/* «Ver expediente completo» del colaborador (Cambios ZESE, 2026-10-01): TODO su historial previo leído de los registros
   ORIGINALES de su postulación (GET /colaboradores/{codigo}/expediente-completo) — respuestas de filtros, fotos del
   vehículo, referencias, documentos, entrevistas, evaluaciones, onboarding y capacitación con su calificación. Nada se
   copia ni se duplica; los archivos se ven en el visor interno sobre la ficha. */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Award, Car, ClipboardList, FileText, GraduationCap, History, Loader2, MessageSquareText, Phone, UserCheck, Users, X } from "lucide-react";
import { Badge, Button, Eyebrow } from "@/components/ui";
import { AccionesArchivo, VisorArchivo, type ArchivoVisor } from "@/components/dashboard/visor-archivo";
import { fetchExpedienteCompleto, urlArchivo, urlInformeEvaluacion, type ExpedienteCompleto as Datos } from "@/lib/api";

function fecha(iso?: string | null) {
  return iso ? new Date(iso).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" }) : "";
}

function Seccion({ icono: Icono, titulo, vacio, children }: { icono: typeof FileText; titulo: string; vacio?: boolean; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border-soft p-4">
      <p className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-ink-3"><Icono className="h-4 w-4" /> {titulo}</p>
      <div className="mt-2 text-sm text-ink-2">{vacio ? <p className="text-ink-3">Sin registros.</p> : children}</div>
    </section>
  );
}

export function ExpedienteCompleto({ codigo, onClose }: { codigo: string; onClose: () => void }) {
  const [d, setD] = useState<Datos | null | undefined>(undefined);
  const [visor, setVisor] = useState<ArchivoVisor | null>(null);
  useEffect(() => {
    fetchExpedienteCompleto(codigo).then(setD);
  }, [codigo]);
  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-0 backdrop-blur-sm sm:p-6" onClick={onClose} role="dialog" aria-modal="true" aria-label="Expediente completo">
      <div className="flex h-[100dvh] w-full max-w-3xl flex-col overflow-hidden bg-bg shadow-2xl sm:h-[90vh] sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-border-soft px-5 py-4">
          <div className="min-w-0">
            <Eyebrow>Expediente completo</Eyebrow>
            <h2 className="font-display truncate text-lg font-bold">{d?.colaborador.nombre ?? codigo}</h2>
            {d?.postulacion && (
              <p className="text-[12px] text-ink-3">
                {d.postulacion.vacante} · {d.postulacion.codigo} · <Badge tone={d.postulacion.estadoPipeline === "Contratado" ? "good" : "neutral"}>{d.postulacion.estadoPipeline}</Badge>
              </p>
            )}
          </div>
          <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /> Cerrar</Button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {d === undefined && <div className="grid place-items-center py-16 text-ink-3"><Loader2 className="h-6 w-6 animate-spin" /></div>}
          {d === null && <p className="text-sm text-bad">No se pudo cargar el expediente completo.</p>}
          {d && (
            <div className="flex flex-col gap-4">
              {!d.postulacion && <p className="rounded-xl bg-warn-soft/50 px-3 py-2 text-sm text-warn">Este colaborador no tiene una postulación de origen (alta manual o importada).</p>}

              <Seccion icono={ClipboardList} titulo={`Respuestas de filtros${d.filtros.resultado ? ` · ${d.filtros.resultado}` : ""}`} vacio={!d.filtros.respuestas.length}>
                <ul className="flex flex-col gap-1.5">
                  {d.filtros.respuestas.map((r, i) => (
                    <li key={i} className="rounded-xl bg-surface-2 px-3 py-2">
                      <span className="block text-[12px] text-ink-3">{r.pregunta}{r.origen ? ` · ${r.origen}` : ""}</span>
                      <span className="text-ink">{r.respuesta || "—"}</span>
                    </li>
                  ))}
                </ul>
              </Seccion>

              <Seccion icono={Car} titulo={`Vehículo${d.vehiculo ? ` · ${d.vehiculo.estado}` : ""}`} vacio={!d.vehiculo}>
                {d.vehiculo && (
                  <>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {d.vehiculo.fotos.map((f) => (
                        <button key={f.lado} type="button" className="overflow-hidden rounded-xl border border-border-soft" title={`Ver ${f.nombre}`}
                          onClick={() => setVisor({ url: urlArchivo(f.url), nombre: `vehiculo-${f.lado}.jpg`, titulo: `Vehículo · ${f.nombre}` })}>
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={urlArchivo(f.url)} alt={f.nombre} className="aspect-[4/3] w-full object-cover" />
                          <span className="block px-2 py-1 text-[11px] text-ink-3">{f.nombre}</span>
                        </button>
                      ))}
                    </div>
                    {(d.vehiculo.decididoPor || d.vehiculo.comentario) && (
                      <p className="mt-2 text-[12px] text-ink-3">{[d.vehiculo.decididoPor && `Decidió: ${d.vehiculo.decididoPor}`, d.vehiculo.comentario].filter(Boolean).join(" · ")}</p>
                    )}
                  </>
                )}
              </Seccion>

              <Seccion icono={FileText} titulo="Documentos" vacio={!d.documentos.length}>
                <ul className="divide-y divide-border-faint">
                  {d.documentos.map((doc) => (
                    <li key={doc.tipo} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                      <span className="text-ink">{doc.tipo}{doc.interno ? " (RH)" : ""} <Badge tone={doc.estado === "Revisado" ? "good" : doc.estado === "Requiere corrección" ? "bad" : "neutral"}>{doc.estado}</Badge></span>
                      <AccionesArchivo onVer={setVisor} archivo={doc.url ? { url: urlArchivo(doc.url), nombre: doc.nombreArchivo || doc.tipo, titulo: doc.tipo } : null} />
                    </li>
                  ))}
                </ul>
              </Seccion>

              <Seccion icono={Users} titulo="Referencias" vacio={!d.referencias.length}>
                <ul className="flex flex-col gap-1.5">
                  {d.referencias.map((r, i) => (
                    <li key={i} className="flex flex-wrap items-center gap-2">
                      <b className="text-ink">{r.nombre}</b> <span className="text-ink-3">· {r.parentesco}</span>
                      <span className="inline-flex items-center gap-1 text-ink-3"><Phone className="h-3.5 w-3.5" /> {r.telefono}</span>
                      {r.validada ? <Badge tone="good" dot>Validada{r.validada_por ? ` por ${r.validada_por}` : ""}</Badge> : r.contactada ? <Badge tone="warn">Contactada{r.resultado ? ` · ${r.resultado}` : ""}</Badge> : <Badge>Sin contactar</Badge>}
                    </li>
                  ))}
                </ul>
              </Seccion>

              <Seccion icono={MessageSquareText} titulo="Entrevistas" vacio={!d.entrevistas.length}>
                <ul className="flex flex-col gap-2">
                  {d.entrevistas.map((e, i) => (
                    <li key={i} className="rounded-xl border border-border-faint px-3 py-2">
                      <p className="text-ink"><b>{e.tipo}</b>{e.fecha ? ` · ${fecha(e.fecha)}` : ""}{e.lugar ? ` · ${e.lugar}` : ""}</p>
                      <p className="text-[12px] text-ink-3">
                        {e.entrevistador && `Entrevistador: ${e.entrevistador}`}{e.cancelada ? " · Cancelada" : ""}{e.confirmada ? " · Confirmada" : ""}
                        {e.asistencia === "asistio" ? " · Asistió" : e.asistencia === "no_asistio" ? " · No asistió" : ""}{e.resultado ? ` · ${e.resultado}` : ""}
                      </p>
                      {e.observaciones && <p className="mt-1 text-[13px]">{e.observaciones}</p>}
                    </li>
                  ))}
                </ul>
              </Seccion>

              <Seccion icono={ClipboardList} titulo="Evaluaciones" vacio={!d.evaluaciones.length}>
                <ul className="flex flex-col gap-2">
                  {d.evaluaciones.map((ev) => (
                    <li key={ev.id} className="rounded-xl border border-border-faint px-3 py-2">
                      <p className="text-ink"><b>{ev.nombre}</b> · {ev.tipoTexto} <Badge>{ev.estado === "revisada" && ev.dictamenTexto ? `Revisada · ${ev.dictamenTexto}` : ev.estadoTexto}</Badge></p>
                      {ev.dictamenEvaluadorTexto && <p className="text-[12px] text-ink-3">Dictamen del evaluador: {ev.dictamenEvaluadorTexto}</p>}
                      {ev.resultadoResumen && <p className="mt-1 text-[13px]">{ev.resultadoResumen}</p>}
                      {ev.tieneInforme && !ev.informeRestringido && (
                        <AccionesArchivo className="mt-1" onVer={setVisor}
                          archivo={{ url: urlInformeEvaluacion(ev.id), urlDescarga: urlInformeEvaluacion(ev.id, true), nombre: ev.nombreArchivo || `informe-${ev.id}`, titulo: `${ev.nombre} · informe` }} />
                      )}
                    </li>
                  ))}
                </ul>
              </Seccion>

              <Seccion icono={UserCheck} titulo="Onboarding" vacio={!d.onboarding.condiciones && !d.onboarding.tareas.length}>
                {d.onboarding.condiciones && (
                  <p className="text-[13px]">
                    {d.onboarding.condiciones.puesto} · {d.onboarding.condiciones.sueldo} · {d.onboarding.condiciones.tipoContratacion}
                    {d.onboarding.condiciones.fechaIngreso ? ` · ingreso ${new Date(d.onboarding.condiciones.fechaIngreso).toLocaleDateString("es-MX")}` : ""}
                  </p>
                )}
                {d.onboarding.tareas.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-1">
                    {d.onboarding.tareas.map((t, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-2 text-[13px]">
                        <Badge tone={t.estado === "realizada" ? "good" : t.estado === "cancelada" ? "neutral" : "warn"}>{t.estado}</Badge> {t.nombre}
                        {t.realizadaPor && <span className="text-[12px] text-ink-3">· {t.realizadaPor} {fecha(t.realizadaEn)}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {d.onboarding.alta && <p className="mt-2 text-[12px] text-good">Alta autorizada por {d.onboarding.alta.por} · {fecha(d.onboarding.alta.en)}</p>}
              </Seccion>

              <Seccion icono={GraduationCap} titulo="Capacitación" vacio={!d.capacitacion.length}>
                <ul className="flex flex-col gap-1.5">
                  {d.capacitacion.map((k) => (
                    <li key={k.codigo} className="flex flex-wrap items-center gap-2">
                      <Award className="h-4 w-4 text-ink-3" /> <span className="text-ink">{k.curso}</span>
                      {k.estado === "completado" && k.calificacion !== null ? (
                        <Badge tone={k.aprobado ? "good" : "bad"} dot>{k.aprobado ? "Aprobado" : "No aprobado"} · {k.calificacion}%</Badge>
                      ) : (
                        <Badge>{k.estado === "en_curso" ? "En curso" : k.estado === "pendiente" ? "Pendiente" : k.estado}</Badge>
                      )}
                      {k.completadoEn && <span className="text-[12px] text-ink-3">{fecha(k.completadoEn)}</span>}
                    </li>
                  ))}
                </ul>
              </Seccion>

              {d.historial.length > 0 && (
                <details className="rounded-2xl border border-border-soft px-4 py-3">
                  <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-ink-2"><History className="h-4 w-4" /> Historial del proceso ({d.historial.length})</summary>
                  <ul className="mt-2 flex flex-col gap-1 text-[12px] text-ink-2">
                    {d.historial.map((h, i) => <li key={i}>• {h.texto}{h.usuario ? <span className="text-ink-3"> · {h.usuario}</span> : null}{h.fecha ? <span className="text-ink-3"> · {fecha(h.fecha)}</span> : null}</li>)}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>
      </div>
      {visor && <VisorArchivo archivo={visor} onClose={() => setVisor(null)} />}
    </div>,
    document.body,
  );
}
