"use client";

/* «Capacitación y alta» (demo Grupo SEZA, 2026-09-29) — la parte del flujo operativo después del vehículo:

   1. Cita a capacitación: sesión compartida con cupo (evaluación unificada «Otra» · «Capacitación en tienda»).
      Confirmar la cita simula el envío del PDF de «Inducción SEZA» por WhatsApp.
   2. Resultado: lo registra el supervisor en su liga — Apto / Requiere seguimiento / No apto (internamente
      Favorable / Con observaciones / Desfavorable).
   3. Documentos y 3 referencias: liga pública del expediente; RH aprueba documentos y marca referencias
      contactadas. Con todo listo la tarjeta pasa sola a «Listo para alta».
   4. Registrar alta → «Alta realizada» (crea el colaborador).
   Una acción principal por paso; toda decisión queda con el nombre de quien la tomó. */

import { useCallback, useEffect, useState } from "react";
import { CalendarCheck, CheckCircle2, ClipboardList, FileCheck2, Phone, Send, UserCheck, XCircle } from "lucide-react";
import { Badge, Button, Card, Eyebrow } from "@/components/ui";
import { Aviso, BotonCopiar } from "@/components/dashboard/subida";
import { cn } from "@/lib/utils";
import {
  citarCapacitacion,
  confirmarCitaCapacitacion,
  fetchPanelOperativo,
  fetchSesionesCapacitacion,
  marcarReferencia,
  registrarAltaOperativa,
  revisarDocumentoOperativo,
  solicitarDocumentosReferencias,
  urlDocumento,
  type PanelOperativo as Panel,
  type Resultado,
  type SesionCapacitacion,
} from "@/lib/api";

const TONO_RESULTADO: Record<string, "good" | "warn" | "bad"> = { favorable: "good", con_observaciones: "warn", desfavorable: "bad" };
const TONO_DOC: Record<string, "good" | "warn" | "bad" | "neutral"> = { Aprobado: "good", "Por revisar": "warn", Rechazado: "bad", Pendiente: "neutral" };

export function PanelOperativo({ codigo, puedeDecidir, onCambio }: { codigo: string; puedeDecidir: boolean; onCambio?: () => void }) {
  const [panel, setPanel] = useState<Panel | null>(null);
  const [sesiones, setSesiones] = useState<SesionCapacitacion[]>([]);
  const [sesionElegida, setSesionElegida] = useState("");
  const [ocupado, setOcupado] = useState("");
  const [aviso, setAviso] = useState<{ tono: "ok" | "error" | "warn"; texto: string } | null>(null);
  const [rechazo, setRechazo] = useState<{ tipo: string; motivo: string } | null>(null);

  const cargar = useCallback(async () => {
    const [p, s] = await Promise.all([fetchPanelOperativo(codigo), fetchSesionesCapacitacion()]);
    if (p) setPanel(p);
    setSesiones(s ?? []);
  }, [codigo]);
  useEffect(() => {
    cargar();
  }, [cargar]);

  async function ejecutar(clave: string, accion: () => Promise<Resultado<Panel>>, exito: (p: Panel) => string) {
    setOcupado(clave);
    setAviso(null);
    const r = await accion();
    setOcupado("");
    if (!r.ok) return setAviso({ tono: "error", texto: r.error });
    setPanel(r.data);
    const sinWhatsapp = r.data.whatsapp && !r.data.whatsapp.enviado;
    setAviso({ tono: sinWhatsapp ? "warn" : "ok", texto: exito(r.data) + (sinWhatsapp ? " El WhatsApp no salió (sin teléfono o fuera de la ventana de 24 h)." : "") });
    fetchSesionesCapacitacion().then((s) => setSesiones(s ?? []));
    onCambio?.();
  }

  if (!panel) return <p className="text-sm text-ink-3">Cargando…</p>;
  const cap = panel.capacitacion;
  const exp = panel.expediente;
  const etapa = panel.etapa;
  const citaAbierta = Boolean(cap.sesion && cap.estado && !["revisada", "fallida"].includes(cap.estado));
  const puedeCitar = ["Cita para capacitación", "Revisión de vehículo"].includes(etapa) && !citaAbierta;
  const sesionesDisponibles = sesiones.filter((s) => s.disponibles > 0 && s.estado === "programada");

  return (
    <div className="flex flex-col gap-5">
      {aviso && (
        <Aviso tono={aviso.tono} onCerrar={() => setAviso(null)}>
          {aviso.texto}
        </Aviso>
      )}

      {/* ---------- 1-2. Capacitación en tienda ---------- */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <Eyebrow>Capacitación en tienda</Eyebrow>
            <p className="mt-1 text-[12px] text-ink-3">Evaluación unificada «Otra» · sesión compartida con cupo</p>
          </div>
          {cap.resultado ? (
            <Badge tone={TONO_RESULTADO[cap.resultado] ?? "neutral"} dot>
              {cap.resultadoEtiqueta}
            </Badge>
          ) : cap.asistencia === "no_asistio" ? (
            <Badge tone="bad" dot>No asistió</Badge>
          ) : citaAbierta ? (
            <Badge tone={cap.confirmada ? "good" : "warn"} dot>{cap.confirmada ? "Cita confirmada" : "Cita por confirmar"}</Badge>
          ) : (
            <Badge tone="neutral">Sin cita</Badge>
          )}
        </div>

        {cap.sesion && (
          <div className="mt-3 rounded-xl bg-surface-2 p-3 text-[13px] text-ink-2">
            <p className="font-medium text-ink">
              {cap.sesion.codigo} · {cap.sesion.inicioTexto} h · {cap.sesion.tienda}
            </p>
            <p>
              {cap.sesion.direccion}
              {cap.sesion.supervisorNombre ? ` · Supervisor: ${cap.sesion.supervisorNombre}` : ""}
            </p>
            {cap.induccion && <p className="mt-1 text-ink-3">📄 {cap.induccion}</p>}
          </div>
        )}
        {cap.resultado && (
          <p className="mt-3 text-[13px] text-ink-2">
            <b>Resultado:</b> {cap.resultadoEtiqueta} <span className="text-ink-3">(dictamen interno: {cap.dictamenInterno})</span>
            {cap.comentario ? ` — ${cap.comentario}` : ""}
            <span className="block text-[12px] text-ink-3">Registró: {cap.registradoPor}</span>
          </p>
        )}
        {cap.asistencia === "no_asistio" && <p className="mt-3 text-[13px] text-ink-2">{cap.comentario}. Puedes citarlo a otra sesión.</p>}

        {puedeDecidir && (puedeCitar || cap.asistencia === "no_asistio") && (
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <select
              value={sesionElegida}
              onChange={(e) => setSesionElegida(e.target.value)}
              className="h-11 flex-1 rounded-xl border border-border-soft bg-surface px-3 text-sm"
            >
              <option value="">Elige una sesión con cupo…</option>
              {sesionesDisponibles.map((s) => (
                <option key={s.codigo} value={s.codigo}>
                  {s.inicioTexto} · {s.tienda} · {s.disponibles} de {s.cupo} lugares
                </option>
              ))}
            </select>
            <Button
              size="sm"
              className="h-11"
              disabled={!sesionElegida || Boolean(ocupado)}
              onClick={() => ejecutar("citar", () => citarCapacitacion(codigo, sesionElegida), () => "Cita enviada por WhatsApp; el candidato confirma respondiendo «Sí».")}
            >
              <CalendarCheck className="h-4 w-4" /> Citar a capacitación
            </Button>
          </div>
        )}
        {puedeDecidir && puedeCitar && sesionesDisponibles.length === 0 && (
          <p className="mt-2 text-[12px] text-ink-3">No hay sesiones con cupo. Crea una en «Sesiones de capacitación».</p>
        )}
        {puedeDecidir && citaAbierta && !cap.confirmada && (
          <Button
            size="sm"
            variant="outline"
            className="mt-4"
            disabled={Boolean(ocupado)}
            onClick={() =>
              ejecutar("confirmar", () => confirmarCitaCapacitacion(codigo), (p) =>
                p.induccion ? `Cita confirmada. Se simuló el envío del PDF «${p.induccion.titulo}» por WhatsApp.` : "Cita confirmada.",
              )
            }
          >
            <CheckCircle2 className="h-4 w-4" /> Confirmar cita (el candidato confirmó por otro medio)
          </Button>
        )}
        {citaAbierta && (
          <p className="mt-3 text-[12px] text-ink-3">La asistencia y el resultado los registra el supervisor en su liga de la sesión.</p>
        )}
      </Card>

      {/* ---------- 3. Documentos y referencias ---------- */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <Eyebrow>Documentos y referencias</Eyebrow>
            {exp && <p className="mt-1 text-[12px] text-ink-3">Documentos aprobados: {exp.progreso}%</p>}
          </div>
          {puedeDecidir && !exp && etapa === "Capacitación realizada" && cap.resultado !== "desfavorable" && (
            <Button
              size="sm"
              disabled={Boolean(ocupado)}
              onClick={() => ejecutar("docs", () => solicitarDocumentosReferencias(codigo), () => "Se envió la liga para documentos y 3 referencias.")}
            >
              <Send className="h-4 w-4" /> Pedir documentos y referencias
            </Button>
          )}
        </div>
        {!exp && etapa === "Capacitación realizada" && cap.resultado === "desfavorable" && (
          <p className="mt-3 text-[13px] text-ink-2">La capacitación quedó como «No apto»: decide si lo descartas o lo citas a otra sesión.</p>
        )}
        {!exp && etapa !== "Capacitación realizada" && <p className="mt-3 text-sm text-ink-3">Se piden después de la capacitación.</p>}

        {exp && (
          <>
            <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-surface-2 px-3 py-2">
              <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3">{exp.liga}</span>
              <BotonCopiar texto={exp.liga} etiqueta="Copiar liga" />
            </div>

            <div className="scroll-x mt-4 rounded-xl border border-border-soft">
              <table className="w-full text-[13px]">
                <tbody>
                  {exp.documentos.map((d) => (
                    <tr key={d.tipo} className="border-b border-border-faint last:border-0">
                      <td className="px-3 py-2 text-ink">
                        {d.archivo ? (
                          <a href={urlDocumento(exp.id, d.tipo)} target="_blank" rel="noreferrer" className="hover:text-brand hover:underline">
                            {d.tipo}
                          </a>
                        ) : (
                          d.tipo
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <Badge tone={TONO_DOC[d.estadoSimple] ?? "neutral"}>{d.estadoSimple}</Badge>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right">
                        {puedeDecidir && d.archivo && !d.aprobado && (
                          <span className="inline-flex gap-1">
                            <Button size="sm" variant="ghost" disabled={Boolean(ocupado)}
                              onClick={() => ejecutar(`doc-${d.tipo}`, () => revisarDocumentoOperativo(codigo, d.tipo, "aprobado"), () => `«${d.tipo}» aprobado.`)}>
                              <CheckCircle2 className="h-4 w-4 text-good" /> Aprobar
                            </Button>
                            <Button size="sm" variant="ghost" disabled={Boolean(ocupado)} onClick={() => setRechazo({ tipo: d.tipo, motivo: "" })}>
                              <XCircle className="h-4 w-4 text-bad" /> Rechazar
                            </Button>
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rechazo && (
              <div className="mt-3 flex flex-col gap-2 rounded-xl border border-bad/30 p-3 sm:flex-row">
                <input
                  value={rechazo.motivo}
                  onChange={(e) => setRechazo({ ...rechazo, motivo: e.target.value })}
                  placeholder={`¿Por qué se rechaza «${rechazo.tipo}»?`}
                  className="h-10 flex-1 rounded-xl border border-border-soft bg-surface px-3 text-sm"
                />
                <Button size="sm" variant="outline" onClick={() => setRechazo(null)}>Cancelar</Button>
                <Button size="sm" disabled={!rechazo.motivo.trim() || Boolean(ocupado)}
                  onClick={() => ejecutar("rechazo", () => revisarDocumentoOperativo(codigo, rechazo.tipo, "rechazado", rechazo.motivo), () => { setRechazo(null); return "Documento rechazado; el candidato puede volver a subirlo."; })}>
                  Rechazar
                </Button>
              </div>
            )}

            <p className="mt-5 text-[12px] font-semibold uppercase tracking-wide text-ink-3">Referencias (3)</p>
            {exp.referencias.length === 0 ? (
              <p className="mt-2 text-sm text-ink-3">El candidato aún no captura sus referencias en la liga.</p>
            ) : (
              <ul className="mt-2 flex flex-col gap-2">
                {exp.referencias.map((r, i) => (
                  <li key={i} className={cn("flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2", r.contactada ? "border-good/30 bg-good-soft/30" : "border-border-soft")}>
                    <span className="text-sm">
                      <b className="text-ink">{r.nombre}</b> <span className="text-ink-3">· {r.parentesco}</span>
                      <a href={`tel:${r.telefono}`} className="ml-2 inline-flex items-center gap-1 text-brand">
                        <Phone className="h-3.5 w-3.5" /> {r.telefono}
                      </a>
                      {r.contactada && (
                        <span className="block text-[12px] text-ink-3">
                          Contactada por {r.contactada_por}
                          {r.nota ? ` — ${r.nota}` : ""}
                        </span>
                      )}
                    </span>
                    {puedeDecidir && (
                      <Button size="sm" variant={r.contactada ? "ghost" : "outline"} disabled={Boolean(ocupado)}
                        onClick={() => {
                          const nota = r.contactada ? "" : (window.prompt(`Nota del contacto con ${r.nombre} (opcional)`) ?? "");
                          ejecutar(`ref-${i}`, () => marcarReferencia(codigo, i, !r.contactada, nota), (p) =>
                            p.etapa === "Listo para alta" ? "Referencia contactada. ¡Expediente completo: pasó a «Listo para alta»!" : r.contactada ? "Referencia marcada como no contactada." : "Referencia marcada como contactada.");
                        }}>
                        {r.contactada ? "Deshacer" : "Marcar contactada"}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Card>

      {/* ---------- 4. Alta ---------- */}
      {exp && (
        <Card className={cn("p-5", panel.alta ? "border-good/40" : "")}>
          <Eyebrow>Alta</Eyebrow>
          {panel.alta ? (
            <p className="mt-2 flex items-center gap-2 text-sm text-good">
              <UserCheck className="h-4 w-4" /> Alta realizada por {panel.alta.por}
              {panel.alta.colaborador ? ` · colaborador ${panel.alta.colaborador.codigo}` : ""}
            </p>
          ) : panel.listoParaAlta ? (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <p className="flex items-center gap-2 text-sm text-ink"><FileCheck2 className="h-4 w-4 text-good" /> Documentos aprobados y 3 referencias contactadas.</p>
              {puedeDecidir && (
                <Button size="sm" disabled={Boolean(ocupado)} onClick={() => ejecutar("alta", () => registrarAltaOperativa(codigo), () => "Alta registrada: ya es colaborador.")}>
                  <UserCheck className="h-4 w-4" /> Registrar alta
                </Button>
              )}
            </div>
          ) : (
            <div className="mt-2">
              <p className="flex items-center gap-2 text-sm text-ink-2"><ClipboardList className="h-4 w-4 text-ink-3" /> Falta para «Listo para alta»:</p>
              <ul className="mt-1 list-disc pl-6 text-[13px] text-ink-3">
                {panel.faltantesAlta.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
