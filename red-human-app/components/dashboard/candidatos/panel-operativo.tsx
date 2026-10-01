"use client";

/* «Entrevista, contratación y alta» (demo Grupo SEZA) — flujo operativo v3 (2026-10-01), después del vehículo:

   1. Entrevista = capacitación en tienda (sobre la entrevista humana): tienda, fecha/hora y capacitador (usuario de la
      Cuenta o externo); sin grupos ni cupos. La cita al candidato y el aviso al capacitador se envían APARTE: si no
      salen, la cita y la liga siguen ahí (Abrir / Copiar / Reenviar). El resultado (Apto / Requiere seguimiento /
      No apto) lo registra el capacitador en su liga o RH a mano; nunca mueve la tarjeta solo.
   2. Ya no hay columna «Evaluación». Después de la entrevista: «Corregir registro», «Agregar entrevista humana o
      evaluación» (pestaña «Evaluaciones»; nunca mueve la tarjeta) y «Avanzar a Contratación» — habilitado solo con la
      entrevista Apta y todas las evaluaciones con resultado y revisadas. Es la ÚNICA acción que cambia la etapa.
   3. Contratación: condiciones (puesto, sueldo, tipo, fecha) + «Generar contrato» o «Generar después de Onboarding»
      → «Enviar a Onboarding».
   4. Onboarding: 6 documentos personales (los del vehículo ya están) + 3 referencias con registro de llamadas →
      «Dar de alta» (crea el colaborador y cierra el proceso).
   Una acción principal por paso; toda decisión queda con el nombre de quien la tomó. */

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, CalendarCheck, CheckCircle2, ClipboardCheck, ClipboardList, FileCheck2, FileSignature, FileText, Phone, Send, ShieldCheck, Upload, UserCheck, Users, XCircle } from "lucide-react";
import { Badge, Button, Card, Eyebrow } from "@/components/ui";
import { Aviso } from "@/components/dashboard/subida";
import { CampoRH, ModalMarco, inputRH } from "@/components/dashboard/modulos-rh";
import { LigaAcciones } from "@/components/dashboard/liga-acciones";
import { ModalAgregarEvaluacion } from "@/components/dashboard/evaluaciones/panel-evaluaciones";
import { cn } from "@/lib/utils";
import {
  avanzarAContratacionOperativa,
  cancelarEntrevistaOperativa,
  capturarReferenciasOperativo,
  confirmarCitaCapacitacion,
  enviarCartaIntencion,
  decidirContratoOperativo,
  enviarAOnboardingOperativo,
  fetchCursos,
  fetchEntrevistadores,
  fetchPanelOperativo,
  guardarCondicionesContratacion,
  marcarReferencia,
  programarEntrevistaOperativa,
  reenviarEntrevistaOperativa,
  registrarAltaOperativa,
  reprogramarEntrevistaOperativa,
  resultadoEntrevistaOperativa,
  revisarDocumentoOperativo,
  solicitarDocumentosReferencias,
  subirDocumento,
  urlCartaIntencion,
  urlContratoPdf,
  urlDocumento,
  validarReferenciaOperativo,
  type DatosEntrevistaOperativa,
  type Entrevistador,
  type PanelOperativo as Panel,
  type Resultado,
} from "@/lib/api";

const TONO_DOC: Record<string, "good" | "warn" | "bad" | "neutral"> = { Revisado: "good", Recibido: "warn", "Requiere corrección": "bad", Pendiente: "neutral" };
const TONO_REFERENCIA: Record<string, "good" | "warn" | "bad" | "neutral"> = {
  Favorable: "good",
  "Con observaciones": "warn",
  Desfavorable: "bad",
};
const RESULTADOS_REFERENCIA_DEFAULT = {
  contactada: ["Favorable", "Con observaciones", "Desfavorable"],
  noContactada: ["No contestó", "Número equivocado", "Buzón o fuera de servicio"],
};

/** «Ahora» en formato de <input type="datetime-local"> (hora local del navegador). */
function ahoraLocal(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

/** ISO → formato de <input type="datetime-local"> en la hora local del navegador. */
function ahoraLocalDe(iso: string): string {
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function fechaCorta(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("es-MX", { dateStyle: "short", timeStyle: "short" });
}

type Llamada = { indice: number; nombre: string; telefono: string; parentesco: string; contactada: boolean; resultado: string; fecha: string; nota: string };
type FormCita = DatosEntrevistaOperativa & { modo: "nueva" | "reprogramar" };

function condDesde(c: Panel["contratacion"]["condiciones"]) {
  return {
    puesto: c.puesto, sueldo: c.sueldo, tipo: c.tipoContratacion, fecha: (c.fechaIngreso || "").slice(0, 10), ubicacion: c.ubicacion,
    jefe: c.jefeDirecto, instrucciones: c.instruccionesIngreso, duracion: c.duracionContrato ? String(c.duracionContrato) : "", unidad: c.duracionUnidad || "meses",
  };
}

const CITA_VACIA: FormCita = {
  modo: "nueva", tienda: "", direccion: "", fecha: "", hora: "09:00", capacitador_tipo: "interno", capacitador_usuario_id: null,
  capacitador_nombre: "", capacitador_telefono: "", capacitador_correo: "", curso_induccion: null, indicaciones: "",
};

export function PanelOperativo({ codigo, puesto, puedeDecidir, onCambio, onVerEvaluaciones }: {
  codigo: string; puesto?: string; puedeDecidir: boolean; onCambio?: () => void; onVerEvaluaciones?: () => void;
}) {
  const [panel, setPanel] = useState<Panel | null>(null);
  const [ocupado, setOcupado] = useState("");
  const [aviso, setAviso] = useState<{ tono: "ok" | "error" | "warn"; texto: string } | null>(null);
  const [rechazo, setRechazo] = useState<{ tipo: string; motivo: string } | null>(null);
  const [contacto, setContacto] = useState<Llamada | null>(null);
  const [cita, setCita] = useState<FormCita | null>(null);
  const [resultado, setResultado] = useState<{ asistio: boolean; resultado: string; comentario: string; fecha: string; entrevistador: string } | null>(null);
  const [capturaRefs, setCapturaRefs] = useState<{ nombre: string; telefono: string; parentesco: string }[] | null>(null);
  const [confirmarAlta, setConfirmarAlta] = useState(false);
  const [agregarEval, setAgregarEval] = useState(false);
  const [usuarios, setUsuarios] = useState<Entrevistador[]>([]);
  const [cursos, setCursos] = useState<{ id: string; titulo: string }[]>([]);
  const [cond, setCond] = useState({ puesto: "", sueldo: "", tipo: "", fecha: "", ubicacion: "", jefe: "", instrucciones: "", duracion: "", unidad: "meses" });

  const cargar = useCallback(async () => {
    const p = await fetchPanelOperativo(codigo);
    if (p) {
      setPanel(p);
      const c = p.contratacion.condiciones;
      setCond(condDesde(c));
    }
  }, [codigo]);
  useEffect(() => {
    cargar();
    fetchEntrevistadores().then((u) => setUsuarios(u ?? []));
    fetchCursos().then((c) => setCursos((c ?? []).map((x) => ({ id: x.id, titulo: x.titulo }))));
  }, [cargar]);

  async function ejecutar(clave: string, accion: () => Promise<Resultado<Panel>>, exito: (p: Panel) => string) {
    setOcupado(clave);
    setAviso(null);
    const r = await accion();
    setOcupado("");
    if (!r.ok) return setAviso({ tono: "error", texto: r.error });
    setPanel(r.data);
    setCond(condDesde(r.data.contratacion.condiciones));
    const sinEnvio = r.data.whatsapp && !r.data.whatsapp.enviado;
    setAviso({ tono: sinEnvio ? "warn" : "ok", texto: exito(r.data) + (sinEnvio ? " El mensaje no salió: copia la liga y compártela." : "") });
    onCambio?.();
  }

  if (!panel) return <p className="text-sm text-ink-3">Cargando…</p>;
  const eh = panel.entrevista;
  const exp = panel.expediente;
  const etapa = panel.etapa;
  const ct = panel.contratacion;
  const conResultado = Boolean(eh && (eh.asistencia === "asistio" || eh.asistencia === "no_asistio"));
  const citaAbierta = Boolean(eh && !conResultado);
  const enEntrevista = etapa === "Entrevista";
  const cerrada = !panel.activa;

  function abrirCita(modo: "nueva" | "reprogramar") {
    if (modo === "reprogramar" && eh) {
      setCita({
        modo, tienda: eh.tienda, direccion: eh.direccion, fecha: eh.fechaLocal, hora: eh.horaLocal || "09:00",
        capacitador_tipo: eh.capacitador.tipo, capacitador_usuario_id: eh.capacitador.usuarioId,
        capacitador_nombre: eh.capacitador.tipo === "externo" ? eh.capacitador.nombre : "",
        capacitador_telefono: eh.capacitador.tipo === "externo" ? eh.capacitador.telefono : "",
        capacitador_correo: eh.capacitador.tipo === "externo" ? eh.capacitador.correo : "",
        curso_induccion: eh.cursoInduccion?.codigo ?? null, indicaciones: eh.indicaciones,
      });
    } else {
      const induccion = cursos.find((c) => c.titulo === "Inducción SEZA");
      setCita({ ...CITA_VACIA, curso_induccion: induccion?.id ?? null, tienda: eh?.tienda ?? "", direccion: eh?.direccion ?? "" });
    }
  }

  function guardarCita() {
    if (!cita) return;
    const { modo, ...datos } = cita;
    const accion = modo === "reprogramar" ? reprogramarEntrevistaOperativa : programarEntrevistaOperativa;
    ejecutar("cita", () => accion(codigo, datos), (p) => {
      setCita(null);
      const c = p.envioCandidato;
      const k = p.envioCapacitador ?? [];
      const partes = [modo === "reprogramar" ? "Capacitación reprogramada." : "Capacitación programada."];
      partes.push(c?.enviado ? "La cita le llegó al candidato." : `La cita al candidato no salió${c?.detalle ? ` (${c.detalle})` : ""}.`);
      partes.push(k.some((x) => x.enviado) ? "El entrevistador recibió su liga." : "Al entrevistador no le llegó el aviso: comparte su liga.");
      if (p.induccionEnviada) partes.push(`Material de inducción «${p.induccionEnviada.titulo}» compartido.`);
      return partes.join(" ");
    });
  }

  function confirmarContacto() {
    if (!contacto) return;
    const { indice, contactada, resultado: res, fecha, nota } = contacto;
    ejecutar(`ref-${indice}`, () => marcarReferencia(codigo, indice, { contactada, resultado: res, fecha, nota: nota.trim() }), (p) => {
      setContacto(null);
      if (p.listoParaAlta) return "Llamada registrada. ¡Documentos y referencias listos: ya puedes dar de alta!";
      return contactada ? `Llamada registrada: ${res}.` : `Llamada registrada: ${res}. La referencia sigue por contactar.`;
    });
  }

  const ultimoEnvio = (destinatario: string) => eh?.envios.find((x) => x.destinatario === destinatario) ?? null;

  return (
    <div className="flex flex-col gap-5">
      {aviso && (
        <Aviso tono={aviso.tono} onCerrar={() => setAviso(null)}>
          {aviso.texto}
        </Aviso>
      )}

      {/* ---------- 1. Entrevista (capacitación en tienda) ---------- */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <Eyebrow>Entrevista · capacitación en tienda</Eyebrow>
            <p className="mt-1 text-[12px] text-ink-3">Tienda, fecha y capacitador. El capacitador registra asistencia y resultado en su liga.</p>
          </div>
          <Badge tone={(eh?.tono as "neutral" | "warn" | "good" | "bad" | "brand") ?? "neutral"} dot>
            {eh?.estado ?? "Por citar"}
          </Badge>
        </div>

        {eh && (
          <div className="mt-3 rounded-xl bg-surface-2 p-3 text-[13px] text-ink-2">
            <p className="font-medium text-ink">
              {eh.fechaTexto} h · {eh.tienda}
            </p>
            {eh.direccion && <p>{eh.direccion}</p>}
            <p>
              Capacitador: <b>{eh.capacitador.nombre}</b> ({eh.capacitador.tipo === "interno" ? "usuario de la Cuenta" : "externo"})
              {eh.capacitador.telefono ? ` · ${eh.capacitador.telefono}` : ""}
              {eh.capacitador.correo ? ` · ${eh.capacitador.correo}` : ""}
            </p>
            {eh.indicaciones && <p className="mt-1 text-ink-3">📝 {eh.indicaciones}</p>}
            {eh.cursoInduccion && <p className="mt-1 text-ink-3">📄 Inducción al confirmar: {eh.cursoInduccion.titulo}</p>}
            {panel.induccion && <p className="mt-1 text-ink-3">{panel.induccion}</p>}
          </div>
        )}

        {eh && citaAbierta && (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <div className="rounded-xl border border-border-soft p-3 text-[12px]">
              <p className="font-semibold text-ink">Cita al candidato</p>
              <p className={cn("mt-0.5", ultimoEnvio("candidato")?.enviado ? "text-good" : "text-warn")}>
                {ultimoEnvio("candidato")?.enviado ? "Enviada" : `No se envió${ultimoEnvio("candidato")?.detalle ? `: ${ultimoEnvio("candidato")?.detalle}` : ""}`}
              </p>
              <p className="mt-0.5 text-ink-3">{eh.confirmada ? `Confirmada ${fechaCorta(eh.confirmadaEn)}` : "Esperando su «Sí»"}</p>
              {puedeDecidir && (
                <Button size="sm" variant="ghost" className="mt-1" disabled={Boolean(ocupado)}
                  onClick={() => ejecutar("reenviar-c", () => reenviarEntrevistaOperativa(codigo, "candidato"), (p) =>
                    p.envios?.[0]?.enviado ? "Cita reenviada al candidato." : "La cita no salió; avísale por otro medio.")}>
                  <Send className="h-3.5 w-3.5" /> Reenviar cita
                </Button>
              )}
            </div>
            <LigaAcciones
              etiqueta="Liga del capacitador"
              liga={eh.ligaCapacitador}
              ultimoEnvio={ultimoEnvio("capacitador")}
              enviando={ocupado === "reenviar-k"}
              onEnviar={puedeDecidir ? () => ejecutar("reenviar-k", () => reenviarEntrevistaOperativa(codigo, "capacitador"), (p) =>
                (p.envios ?? []).some((x) => x.enviado) ? "Liga reenviada al capacitador." : "El aviso no salió; copia la liga y compártela.") : undefined}
            />
          </div>
        )}

        {eh && conResultado && (
          <p className="mt-3 text-[13px] text-ink-2">
            <b>{eh.asistencia === "no_asistio" ? "No asistió" : `Resultado: ${eh.resultadoEtiqueta}`}</b>
            {eh.asistencia === "asistio" && eh.indicaciones ? ` — ${eh.indicaciones}` : ""}
            <span className="block text-[12px] text-ink-3">
              Realizada: {fechaCorta(eh.realizadaEn)} · entrevistador: {eh.capacitador.nombre} · registró {eh.registradoPor || "—"} vía{" "}
              {eh.capturadoPor === "rh" ? "captura de RH" : "liga del entrevistador"} · {fechaCorta(eh.evaluadaEn)}
            </span>
          </p>
        )}
        {panel.entrevistasAnteriores > 0 && <p className="mt-2 text-[12px] text-ink-3">{panel.entrevistasAnteriores} cita(s) anterior(es) en el historial.</p>}

        {puedeDecidir && !cerrada && (
          <div className="mt-4 flex flex-wrap gap-2">
            {(!eh || eh.asistencia === "no_asistio") && ["Revisión de vehículo", "Entrevista"].includes(etapa) && (
              <Button size="sm" onClick={() => abrirCita("nueva")}>
                <CalendarCheck className="h-4 w-4" /> {eh ? "Programar nueva cita" : "Programar capacitación"}
              </Button>
            )}
            {citaAbierta && (
              <>
                <Button size="sm" onClick={() => setResultado({ asistio: true, resultado: "", comentario: "", fecha: ahoraLocal(), entrevistador: eh!.capacitador.nombre })}>
                  <ClipboardCheck className="h-4 w-4" /> Registrar entrevista
                </Button>
                {!eh!.confirmada && (
                  <Button size="sm" variant="outline" disabled={Boolean(ocupado)}
                    onClick={() => ejecutar("confirmar", () => confirmarCitaCapacitacion(codigo), (p) =>
                      p.induccionEnviada ? `Cita confirmada. Se envió el PDF «${p.induccionEnviada.titulo}».` : "Cita confirmada.")}>
                    <CheckCircle2 className="h-4 w-4" /> Confirmar por el candidato
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => abrirCita("reprogramar")}>Reprogramar…</Button>
                <Button size="sm" variant="ghost" disabled={Boolean(ocupado)}
                  onClick={() => ejecutar("cancelar", () => cancelarEntrevistaOperativa(codigo), () => "Capacitación cancelada.")}>
                  Cancelar cita
                </Button>
              </>
            )}
            {eh && conResultado && (
              <Button size="sm" variant="ghost" onClick={() => setResultado({ asistio: eh.asistencia === "asistio", resultado: eh.resultado, comentario: "",
                fecha: eh.realizadaEn ? ahoraLocalDe(eh.realizadaEn) : ahoraLocal(), entrevistador: eh.capacitador.nombre })}>
                Corregir registro…
              </Button>
            )}
            {!eh && ["Revisión de vehículo", "Entrevista"].includes(etapa) && (
              <Button size="sm" variant="ghost" onClick={() => setResultado({ asistio: true, resultado: "", comentario: "", fecha: ahoraLocal(), entrevistador: "" })}>
                <ClipboardCheck className="h-4 w-4" /> Registrar entrevista (sin cita)
              </Button>
            )}
            {enEntrevista && eh?.asistencia === "asistio" && (
              <Button size="sm" variant="outline" disabled={Boolean(ocupado)} onClick={() => setAgregarEval(true)}>
                <ClipboardList className="h-4 w-4" /> Agregar entrevista humana o evaluación
              </Button>
            )}
          </div>
        )}
      </Card>

      {/* ---------- 2. Resultados y avance a Contratación (v3: sin columna «Evaluación») ---------- */}
      {enEntrevista && eh?.asistencia === "asistio" && (
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <Eyebrow>Resultados y evaluaciones</Eyebrow>
            {panel.evaluacionesPendientes > 0 ? (
              <Badge tone="warn" dot>{panel.evaluacionesPendientes} evaluación(es) pendiente(s)</Badge>
            ) : (
              <Badge tone="good" dot>Sin evaluaciones pendientes</Badge>
            )}
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {[
              { t: "Prefiltro", v: panel.evaluacionResumen.prefiltro.etiqueta,
                d: panel.evaluacionResumen.prefiltro.aprobadoPorRH ? `Aprobado por ${panel.evaluacionResumen.prefiltro.aprobadoPorRH.usuario}` : panel.evaluacionResumen.prefiltro.motivos.slice(0, 2).join(" · ") },
              { t: "Revisión de vehículo", v: panel.evaluacionResumen.vehiculo.etiqueta,
                d: [panel.evaluacionResumen.vehiculo.decididoPor && `por ${panel.evaluacionResumen.vehiculo.decididoPor}`, panel.evaluacionResumen.vehiculo.comentario].filter(Boolean).join(" · ") },
              { t: "Entrevista en tienda", v: panel.evaluacionResumen.entrevista.resultadoEtiqueta || panel.evaluacionResumen.entrevista.estado,
                d: [panel.evaluacionResumen.entrevista.entrevistador, panel.evaluacionResumen.entrevista.observaciones].filter(Boolean).join(" · ") },
            ].map((x) => (
              <div key={x.t} className="rounded-xl border border-border-soft p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">{x.t}</p>
                <p className="mt-1 text-sm font-semibold text-ink">{x.v || "—"}</p>
                {x.d && <p className="mt-0.5 text-[12px] text-ink-3">{x.d}</p>}
              </div>
            ))}
          </div>
          <p className="mt-3 text-[13px] text-ink-2">
            Agregar una entrevista humana o una evaluación no mueve al candidato: cada una conserva su estado y resultado
            {onVerEvaluaciones && (
              <> (<button type="button" className="font-semibold text-brand hover:underline" onClick={onVerEvaluaciones}>ver «Evaluaciones»</button>)</>
            )}
            . Solo «Avanzar a Contratación» cambia la etapa.
          </p>
          {panel.requisitosContratacion.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-[12px] text-ink-3">
              {panel.requisitosContratacion.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
          {puedeDecidir && !cerrada && (
            <Button size="sm" className="mt-3" disabled={Boolean(ocupado) || panel.requisitosContratacion.length > 0}
              title={panel.requisitosContratacion.length ? "Se habilita con la entrevista Apta y todas las evaluaciones concluidas y revisadas." : undefined}
              onClick={() => ejecutar("contratacion", () => avanzarAContratacionOperativa(codigo), () => "Avanzó a Contratación.")}>
              <ArrowRight className="h-4 w-4" /> Avanzar a Contratación
            </Button>
          )}
        </Card>
      )}

      {/* ---------- 3. Contratación ---------- */}
      {(etapa === "Contratación" || etapa === "Onboarding") && (
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <Eyebrow>Contratación</Eyebrow>
            <Badge tone={ct.contrato === "generado" ? "good" : ct.contrato === "despues" ? "brand" : "warn"} dot>
              {ct.contrato === "generado" ? "Contrato generado" : ct.contrato === "despues" ? "Contrato: después de Onboarding" : "Contrato sin decidir"}
            </Badge>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <CampoRH label="Puesto">
              <input className={inputRH} value={cond.puesto} disabled={!puedeDecidir || cerrada} onChange={(e) => setCond({ ...cond, puesto: e.target.value })} />
            </CampoRH>
            <CampoRH label="Tipo de contratación" ayuda={cond.tipo ? `Plantilla: ${ct.plantillas[cond.tipo]?.titulo ?? ""}` : undefined}>
              <select className={inputRH} value={cond.tipo} disabled={!puedeDecidir || cerrada} onChange={(e) => setCond({ ...cond, tipo: e.target.value })}>
                <option value="">Elige…</option>
                {ct.tiposContratacion.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </CampoRH>
            <CampoRH label={`${ct.plantillas[cond.tipo]?.pago ?? "Sueldo"} (condiciones económicas)`}>
              <input className={inputRH} value={cond.sueldo} disabled={!puedeDecidir || cerrada} onChange={(e) => setCond({ ...cond, sueldo: e.target.value })} placeholder="$650 MXN diarios, pago semanal" />
            </CampoRH>
            {cond.tipo === "Tiempo determinado" && (
              <CampoRH label="Duración">
                <div className="flex gap-2">
                  <input className={inputRH} inputMode="numeric" value={cond.duracion} disabled={!puedeDecidir || cerrada} onChange={(e) => setCond({ ...cond, duracion: e.target.value.replace(/\D/g, "") })} />
                  <select className={inputRH} value={cond.unidad} disabled={!puedeDecidir || cerrada} onChange={(e) => setCond({ ...cond, unidad: e.target.value })}>
                    {["días", "meses", "años"].map((u) => <option key={u} value={u}>{u}</option>)}
                  </select>
                </div>
              </CampoRH>
            )}
            <CampoRH label={ct.plantillas[cond.tipo]?.pago && ct.plantillas[cond.tipo].pago !== "Sueldo" ? "Fecha de inicio" : "Fecha de ingreso"}>
              <input type="date" className={inputRH} value={cond.fecha} disabled={!puedeDecidir || cerrada} onChange={(e) => setCond({ ...cond, fecha: e.target.value })} />
            </CampoRH>
            <CampoRH label="Ubicación">
              <input className={inputRH} value={cond.ubicacion} disabled={!puedeDecidir || cerrada} onChange={(e) => setCond({ ...cond, ubicacion: e.target.value })} />
            </CampoRH>
            <CampoRH label="Jefe directo / contacto">
              <input className={inputRH} value={cond.jefe} disabled={!puedeDecidir || cerrada} onChange={(e) => setCond({ ...cond, jefe: e.target.value })} />
            </CampoRH>
          </div>
          <CampoRH label="Instrucciones de ingreso">
            <textarea rows={2} value={cond.instrucciones} disabled={!puedeDecidir || cerrada} onChange={(e) => setCond({ ...cond, instrucciones: e.target.value })}
              className="w-full rounded-xl border border-border-soft bg-surface px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20" />
          </CampoRH>
          {puedeDecidir && !cerrada && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" disabled={Boolean(ocupado) || !cond.puesto || !cond.sueldo || !cond.tipo || !cond.fecha}
                onClick={() => ejecutar("condiciones", async () => {
                  const r = await guardarCondicionesContratacion(codigo, {
                    puesto: cond.puesto, sueldo: cond.sueldo, tipoContratacion: cond.tipo, fechaIngreso: cond.fecha, ubicacion: cond.ubicacion,
                    jefeDirecto: cond.jefe, instruccionesIngreso: cond.instrucciones,
                    duracionContrato: cond.tipo === "Tiempo determinado" && cond.duracion ? Number(cond.duracion) : null,
                    duracionUnidad: cond.tipo === "Tiempo determinado" ? cond.unidad : "",
                  });
                  if (!r.ok) return r;
                  const p = await fetchPanelOperativo(codigo);
                  return p ? { ok: true as const, data: p } : { ok: false as const, error: "No se pudo recargar." };
                }, () => "Condiciones guardadas.")}>
                Guardar condiciones
              </Button>
              {ct.contrato !== "generado" && (
                <Button size="sm" disabled={Boolean(ocupado) || !ct.completas}
                  onClick={() => ejecutar("contrato", () => decidirContratoOperativo(codigo, "ahora"), (p) => {
                    if (p.expediente) window.open(urlContratoPdf(p.expediente.id), "_blank");
                    return "Contrato generado (se abrió la vista previa).";
                  })}>
                  <FileSignature className="h-4 w-4" /> Generar contrato
                </Button>
              )}
              {!ct.contrato && etapa === "Contratación" && (
                <Button size="sm" variant="ghost" disabled={Boolean(ocupado)}
                  onClick={() => ejecutar("despues", () => decidirContratoOperativo(codigo, "despues"), () => "El contrato queda pendiente para Onboarding.")}>
                  Generar después de Onboarding
                </Button>
              )}
              {ct.contrato === "generado" && exp && (
                <a href={urlContratoPdf(exp.id)} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-1 rounded-xl px-3 text-sm font-semibold text-brand hover:bg-brand-soft">
                  <FileSignature className="h-4 w-4" /> Ver contrato
                </a>
              )}
              {ct.cartaDisponible && exp && (
                <>
                  <a href={urlCartaIntencion(exp.id)} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-1 rounded-xl px-3 text-sm font-semibold text-brand hover:bg-brand-soft">
                    <FileText className="h-4 w-4" /> Carta de intención
                  </a>
                  <Button size="sm" variant="ghost" disabled={Boolean(ocupado)} onClick={async () => {
                    setOcupado("carta");
                    const r = await enviarCartaIntencion(exp.id, "whatsapp");
                    setOcupado("");
                    setAviso(r.ok ? { tono: r.data.enviado ? "ok" : "warn", texto: r.data.enviado ? "Carta de intención enviada al candidato." : `La carta no salió (${r.data.detalle}); compártela desde su liga.` } : { tono: "error", texto: r.error });
                  }}>
                    <Send className="h-4 w-4" /> Enviar carta
                  </Button>
                </>
              )}
            </div>
          )}
          {ct.contratoPor && <p className="mt-2 text-[12px] text-ink-3">Decidió: {ct.contratoPor} · {fechaCorta(ct.contratoEn)}</p>}
          {etapa === "Contratación" && (
            <div className="mt-4 border-t border-border-faint pt-4">
              {ct.requisitosOnboarding.length > 0 && (
                <ul className="mb-3 list-disc pl-5 text-[12px] text-ink-3">
                  {ct.requisitosOnboarding.map((r) => <li key={r}>{r}</li>)}
                </ul>
              )}
              {puedeDecidir && !cerrada && (
                <Button size="sm" disabled={Boolean(ocupado) || ct.requisitosOnboarding.length > 0}
                  onClick={() => ejecutar("onboarding", () => enviarAOnboardingOperativo(codigo), () => "Pasó a Onboarding: se envió la liga de documentos y referencias.")}>
                  <Send className="h-4 w-4" /> Enviar a Onboarding
                </Button>
              )}
            </div>
          )}
        </Card>
      )}

      {/* ---------- 4. Onboarding: documentos, referencias y alta ---------- */}
      {etapa === "Onboarding" && exp && (
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <Eyebrow>Onboarding · documentos y referencias</Eyebrow>
              <p className="mt-1 text-[12px] text-ink-3">Documentos revisados: {exp.progreso}% · los del vehículo vienen de la revisión del vehículo.</p>
            </div>
          </div>
          <LigaAcciones
            className="mt-3"
            etiqueta="Liga del candidato (documentos + 3 referencias)"
            liga={exp.liga}
            enviando={ocupado === "docs"}
            textoEnviar="Reenviar liga"
            onEnviar={puedeDecidir && !cerrada ? () => ejecutar("docs", () => solicitarDocumentosReferencias(codigo), () => "Se reenvió la liga de documentos y referencias.") : undefined}
          />
          {ct.contrato === "despues" && (
            <p className="mt-3 rounded-xl bg-brand-soft/40 p-3 text-[13px] text-ink-2">
              <FileSignature className="mr-1 inline h-4 w-4 text-brand" /> El contrato quedó para esta etapa: usa «Generar contrato» en Contratación (arriba).
            </p>
          )}

          <div className="scroll-x mt-4 rounded-xl border border-border-soft">
            <table className="w-full text-[13px]">
              <tbody>
                {exp.documentos.map((d) => (
                  <tr key={d.tipo} className="border-b border-border-faint last:border-0">
                    <td className="px-3 py-2 text-ink">
                      {d.archivo ? (
                        <a href={urlDocumento(exp.id, d.tipo)} target="_blank" rel="noreferrer" className="hover:text-brand hover:underline">{d.tipo}</a>
                      ) : (
                        d.tipo
                      )}
                      {d.delVehiculo && <span className="ml-1 text-[11px] text-ink-3">(vehículo)</span>}
                      {d.estadoSimple === "Requiere corrección" && d.notas && <span className="block text-[12px] text-bad">Corregir: {d.notas}</span>}
                      {d.estadoSimple === "Revisado" && d.revisadoPor && <span className="block text-[12px] text-ink-3">Revisado por {d.revisadoPor}</span>}
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={TONO_DOC[d.estadoSimple] ?? "neutral"}>{d.estadoSimple}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      {puedeDecidir && !cerrada && !d.aprobado && (
                        <SubirDoc ocupado={ocupado === `subir-${d.tipo}`} onArchivo={(a) => ejecutar(`subir-${d.tipo}`, async () => {
                          const r = await subirDocumento(exp.id, d.tipo, a);
                          if (!r.ok) return r;
                          const p = await fetchPanelOperativo(codigo);
                          return p ? { ok: true as const, data: p } : { ok: false as const, error: "No se pudo recargar." };
                        }, () => `«${d.tipo}» cargado: queda «Recibido» para revisión.`)} />
                      )}
                      {puedeDecidir && !cerrada && d.archivo && !d.aprobado && (
                        <span className="inline-flex gap-1">
                          <Button size="sm" variant="ghost" disabled={Boolean(ocupado)}
                            onClick={() => ejecutar(`doc-${d.tipo}`, () => revisarDocumentoOperativo(codigo, d.tipo, "aprobado"), () => `«${d.tipo}» revisado.`)}>
                            <CheckCircle2 className="h-4 w-4 text-good" /> Marcar revisado
                          </Button>
                          {d.estadoSimple !== "Requiere corrección" && (
                            <Button size="sm" variant="ghost" disabled={Boolean(ocupado)} onClick={() => setRechazo({ tipo: d.tipo, motivo: "" })}>
                              <XCircle className="h-4 w-4 text-bad" /> Pedir corrección
                            </Button>
                          )}
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
                placeholder={`¿Qué debe corregir en «${rechazo.tipo}»? (se le envía al candidato)`}
                className="h-10 flex-1 rounded-xl border border-border-soft bg-surface px-3 text-sm"
              />
              <Button size="sm" variant="outline" onClick={() => setRechazo(null)}>Cancelar</Button>
              <Button size="sm" disabled={!rechazo.motivo.trim() || Boolean(ocupado)}
                onClick={() => ejecutar("rechazo", () => revisarDocumentoOperativo(codigo, rechazo.tipo, "rechazado", rechazo.motivo), () => { setRechazo(null); return "Documento en «Requiere corrección»: se le avisó al candidato."; })}>
                Pedir corrección
              </Button>
            </div>
          )}

          <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[12px] font-semibold uppercase tracking-wide text-ink-3">Referencias (3) · contactada ≠ validada</p>
            {puedeDecidir && !cerrada && (
              <Button size="sm" variant="ghost" onClick={() => setCapturaRefs(
                [0, 1, 2].map((i) => ({ nombre: exp.referencias[i]?.nombre ?? "", telefono: exp.referencias[i]?.telefono ?? "", parentesco: exp.referencias[i]?.parentesco ?? "" })),
              )}>
                <Users className="h-4 w-4" /> {exp.referencias.length ? "Editar referencias" : "Capturar referencias"}
              </Button>
            )}
          </div>
          {exp.referencias.length === 0 ? (
            <p className="mt-2 text-sm text-ink-3">El candidato aún no captura sus referencias en la liga (o captúralas tú).</p>
          ) : (
            <ul className="mt-2 flex flex-col gap-2">
              {exp.referencias.map((r, i) => {
                const llamadas = r.llamadas ?? [];
                return (
                  <li key={i} className={cn("rounded-xl border px-3 py-2", r.contactada ? "border-good/30 bg-good-soft/30" : "border-border-soft")}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm">
                        <b className="text-ink">{r.nombre}</b> <span className="text-ink-3">· {r.parentesco}</span>
                        <a href={`tel:${r.telefono}`} className="ml-2 inline-flex items-center gap-1 text-brand">
                          <Phone className="h-3.5 w-3.5" /> {r.telefono}
                        </a>
                      </span>
                      <span className="flex items-center gap-2">
                        <Badge tone={r.contactada ? TONO_REFERENCIA[r.resultado ?? ""] ?? "good" : llamadas.length ? "warn" : "neutral"}>
                          {r.contactada ? `Contactada${r.resultado ? ` · ${r.resultado}` : ""}` : llamadas.length ? `Sin contactar · ${r.resultado || "intento"}` : "Por llamar"}
                        </Badge>
                        {r.validada ? (
                          <Badge tone="good" dot>Validada</Badge>
                        ) : (
                          r.contactada && <Badge tone="warn">Sin validar</Badge>
                        )}
                        {puedeDecidir && !cerrada && r.contactada && (
                          <Button size="sm" variant={r.validada ? "ghost" : "outline"} disabled={Boolean(ocupado)}
                            onClick={() => ejecutar(`val-${i}`, () => validarReferenciaOperativo(codigo, i, !r.validada), () => (r.validada ? "Validación retirada." : "Referencia validada."))}>
                            <ShieldCheck className="h-4 w-4" /> {r.validada ? "Quitar validación" : "Validar"}
                          </Button>
                        )}
                        {puedeDecidir && !cerrada && (
                          <Button size="sm" variant={r.contactada ? "ghost" : "outline"} disabled={Boolean(ocupado)}
                            onClick={() => setContacto({ indice: i, nombre: r.nombre, telefono: r.telefono, parentesco: r.parentesco, contactada: true, resultado: "", fecha: ahoraLocal(), nota: "" })}>
                            <Phone className="h-4 w-4" /> {llamadas.length ? "Registrar otra llamada" : "Registrar llamada"}
                          </Button>
                        )}
                      </span>
                    </div>
                    {r.validada && <p className="mt-1 text-[12px] text-good">Validada por {r.validada_por} · {fechaCorta(r.validada_en)}{r.validacion_nota ? ` — ${r.validacion_nota}` : ""}</p>}
                    {llamadas.length > 0 && (
                      <ul className="mt-2 flex flex-col gap-1 border-t border-border-faint pt-2 text-[12px] text-ink-3">
                        {[...llamadas].reverse().map((l, j) => (
                          <li key={j}>
                            <span className="font-medium text-ink-2">{fechaCorta(l.fecha)}</span> · {l.contactada ? "Contactada" : "No contactada"}
                            {l.resultado ? ` · ${l.resultado}` : ""} · {l.usuario}
                            {l.observaciones ? <span className="block pl-3 italic">«{l.observaciones}»</span> : null}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      )}

      {/* ---------- Alta ---------- */}
      {(etapa === "Onboarding" || panel.alta) && (
        <Card className={cn("p-5", panel.alta ? "border-good/40" : "")}>
          <Eyebrow>Alta</Eyebrow>
          {panel.alta ? (
            <p className="mt-2 flex items-center gap-2 text-sm text-good">
              <UserCheck className="h-4 w-4" /> Alta realizada por {panel.alta.por} · {fechaCorta(panel.alta.en)}
              {panel.alta.colaborador ? ` · ${panel.alta.colaborador.codigo}` : ""}. El proceso quedó cerrado.
            </p>
          ) : panel.listoParaAlta ? (
            <>
              <p className="mt-2 flex items-center gap-2 text-sm text-ink"><FileCheck2 className="h-4 w-4 text-good" /> Documentos revisados y 3 referencias validadas.</p>
              {puedeDecidir && (
                <Button className="mt-3" disabled={Boolean(ocupado)}
                  onClick={() => (ct.contrato === "generado"
                    ? ejecutar("alta", () => registrarAltaOperativa(codigo), () => "Alta realizada: se creó el colaborador y se cerró el proceso.")
                    : setConfirmarAlta(true))}>
                  <UserCheck className="h-4 w-4" /> Dar de alta
                </Button>
              )}
            </>
          ) : (
            <>
              <p className="mt-2 text-[13px] text-ink-2">«Dar de alta» se habilita cuando todo esté listo. Falta:</p>
              <ul className="mt-1 list-disc pl-5 text-[13px] text-ink-3">
                {panel.faltantesAlta.map((f) => <li key={f}>{f}</li>)}
              </ul>
            </>
          )}
        </Card>
      )}

      {/* ---------- Modal: programar / reprogramar capacitación ---------- */}
      {cita && (
        <ModalMarco titulo={cita.modo === "reprogramar" ? "Reprogramar capacitación" : "Programar capacitación en tienda"}
          subtitulo="Sin grupos ni cupos: una cita por candidato." onClose={() => !ocupado && setCita(null)} ancho="max-w-xl">
          <div className="grid gap-3 sm:grid-cols-2">
            <CampoRH label="Tienda">
              <input className={inputRH} value={cita.tienda} onChange={(e) => setCita({ ...cita, tienda: e.target.value })} placeholder="Tienda SEZA Angelópolis" />
            </CampoRH>
            <CampoRH label="Dirección (opcional)">
              <input className={inputRH} value={cita.direccion ?? ""} onChange={(e) => setCita({ ...cita, direccion: e.target.value })} />
            </CampoRH>
            <CampoRH label="Fecha">
              <input type="date" className={inputRH} value={cita.fecha} onChange={(e) => setCita({ ...cita, fecha: e.target.value })} />
            </CampoRH>
            <CampoRH label="Hora">
              <input type="time" className={inputRH} value={cita.hora} onChange={(e) => setCita({ ...cita, hora: e.target.value })} />
            </CampoRH>
          </div>
          <CampoRH label="Capacitador">
            <div className="flex gap-2">
              {(["interno", "externo"] as const).map((t) => (
                <button key={t} type="button" onClick={() => setCita({ ...cita, capacitador_tipo: t })}
                  className={cn("h-10 flex-1 rounded-xl border text-sm font-semibold", cita.capacitador_tipo === t ? "border-brand bg-brand-soft text-brand" : "border-border-soft text-ink-2")}>
                  {t === "interno" ? "Usuario de la Cuenta" : "Externo"}
                </button>
              ))}
            </div>
          </CampoRH>
          {cita.capacitador_tipo === "interno" ? (
            <CampoRH label="¿Quién capacita?" ayuda="Su teléfono y correo salen de su perfil (Configuración → Usuarios).">
              <select className={inputRH} value={cita.capacitador_usuario_id ?? ""} onChange={(e) => setCita({ ...cita, capacitador_usuario_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">Elige…</option>
                {usuarios.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
              </select>
            </CampoRH>
          ) : (
            <div className="grid gap-3 sm:grid-cols-3">
              <CampoRH label="Nombre"><input className={inputRH} value={cita.capacitador_nombre ?? ""} onChange={(e) => setCita({ ...cita, capacitador_nombre: e.target.value })} /></CampoRH>
              <CampoRH label="Teléfono"><input className={inputRH} value={cita.capacitador_telefono ?? ""} onChange={(e) => setCita({ ...cita, capacitador_telefono: e.target.value })} /></CampoRH>
              <CampoRH label="Correo"><input className={inputRH} value={cita.capacitador_correo ?? ""} onChange={(e) => setCita({ ...cita, capacitador_correo: e.target.value })} /></CampoRH>
            </div>
          )}
          <CampoRH label="PDF de inducción al confirmar (opcional)">
            <select className={inputRH} value={cita.curso_induccion ?? ""} onChange={(e) => setCita({ ...cita, curso_induccion: e.target.value || null })}>
              <option value="">Sin inducción</option>
              {cursos.map((c) => <option key={c.id} value={c.id}>{c.titulo}</option>)}
            </select>
          </CampoRH>
          <CampoRH label="Indicaciones (opcional)">
            <input className={inputRH} value={cita.indicaciones ?? ""} onChange={(e) => setCita({ ...cita, indicaciones: e.target.value })} placeholder="Llega 15 minutos antes con tu INE y licencia" />
          </CampoRH>
          <p className="mt-2 text-[12px] text-ink-3">La cita y el aviso al capacitador se envían aparte: si alguno no sale, la cita se guarda igual y puedes reenviar o copiar la liga.</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCita(null)} disabled={Boolean(ocupado)}>Cancelar</Button>
            <Button onClick={guardarCita} disabled={Boolean(ocupado) || !cita.tienda.trim() || !cita.fecha || !cita.hora}>
              <CalendarCheck className="h-4 w-4" /> {ocupado === "cita" ? "Guardando…" : "Guardar y enviar cita"}
            </Button>
          </div>
        </ModalMarco>
      )}

      {/* ---------- Modal: resultado manual de RH ---------- */}
      {resultado && (
        <ModalMarco titulo="Registrar entrevista" subtitulo="Captura interna de RH (aunque no esté confirmada): alimenta el mismo registro que la liga del entrevistador. Queda tu nombre, la fecha y la vía."
          onClose={() => !ocupado && setResultado(null)} ancho="max-w-lg">
          <div className="grid gap-3 sm:grid-cols-2">
            <CampoRH label="Fecha y hora realizada">
              <input type="datetime-local" className={inputRH} value={resultado.fecha} max={ahoraLocal()} onChange={(e) => setResultado({ ...resultado, fecha: e.target.value })} />
            </CampoRH>
            <CampoRH label="Entrevistador / capacitador">
              <input className={inputRH} value={resultado.entrevistador} onChange={(e) => setResultado({ ...resultado, entrevistador: e.target.value })} />
            </CampoRH>
          </div>
          <CampoRH label="¿Asistió?">
            <div className="flex gap-2">
              {[true, false].map((v) => (
                <button key={String(v)} type="button" onClick={() => setResultado({ ...resultado, asistio: v, resultado: v ? resultado.resultado : "" })}
                  className={cn("h-11 flex-1 rounded-xl border text-sm font-semibold", resultado.asistio === v ? "border-brand bg-brand-soft text-brand" : "border-border-soft text-ink-2")}>
                  {v ? "Sí asistió" : "No asistió"}
                </button>
              ))}
            </div>
          </CampoRH>
          {resultado.asistio && (
            <CampoRH label="Resultado">
              <div className="grid grid-cols-3 gap-2">
                {panel.resultadosCapacitacion.map((o) => (
                  <button key={o.valor} type="button" onClick={() => setResultado({ ...resultado, resultado: o.valor })}
                    className={cn("h-11 rounded-xl border text-sm font-semibold", resultado.resultado === o.valor ? "border-brand bg-brand-soft text-brand" : "border-border-soft text-ink-2")}>
                    {o.texto}
                  </button>
                ))}
              </div>
            </CampoRH>
          )}
          <CampoRH label={resultado.asistio && resultado.resultado !== "favorable" ? "Observaciones (obligatorias)" : "Observaciones (opcional)"}>
            <textarea rows={3} value={resultado.comentario} onChange={(e) => setResultado({ ...resultado, comentario: e.target.value })}
              className="w-full rounded-xl border border-border-soft bg-surface px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20" />
          </CampoRH>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setResultado(null)} disabled={Boolean(ocupado)}>Cancelar</Button>
            <Button disabled={Boolean(ocupado) || (resultado.asistio && !resultado.resultado) || !resultado.fecha}
              onClick={() => ejecutar("resultado", () => resultadoEntrevistaOperativa(codigo, {
                asistio: resultado.asistio, resultado: resultado.resultado, comentario: resultado.comentario,
                fecha_realizada: resultado.fecha, entrevistador: resultado.entrevistador,
              }), () => { setResultado(null); return "Entrevista registrada. La tarjeta sigue en Entrevista hasta que uses «Avanzar a Contratación»."; })}>
              Guardar registro
            </Button>
          </div>
        </ModalMarco>
      )}

      {/* ---------- Modal: agregar entrevista humana o evaluación (no mueve la tarjeta) ---------- */}
      {agregarEval && (
        <ModalAgregarEvaluacion codigo={codigo} puesto={puesto} conEntrevistaHumana onClose={() => setAgregarEval(false)}
          onAgregada={async (ev) => {
            setAgregarEval(false);
            await cargar();
            setAviso({ tono: "ok", texto: `«${ev.nombre}» agregada (${ev.estadoTexto}). El candidato sigue en Entrevista.` });
            onCambio?.();
          }} />
      )}

      {/* ---------- Modal: el contrato quedó pendiente → se ofrece antes del alta ---------- */}
      {confirmarAlta && (
        <ModalMarco titulo="El contrato está pendiente" subtitulo="Se dejó para después de Onboarding. ¿Lo generas antes de dar de alta?"
          onClose={() => !ocupado && setConfirmarAlta(false)} ancho="max-w-lg">
          <div className="flex flex-col gap-2">
            <Button disabled={Boolean(ocupado) || !ct.completas} onClick={() => ejecutar("alta", async () => {
              const r = await decidirContratoOperativo(codigo, "ahora");
              if (!r.ok) return r;
              if (r.data.expediente) window.open(urlContratoPdf(r.data.expediente.id), "_blank");
              return registrarAltaOperativa(codigo);
            }, () => { setConfirmarAlta(false); return "Contrato generado y alta realizada: se creó el colaborador y se cerró el proceso."; })}>
              <FileSignature className="h-4 w-4" /> Generar contrato y dar de alta
            </Button>
            <Button variant="outline" disabled={Boolean(ocupado)} onClick={() => ejecutar("alta", () => registrarAltaOperativa(codigo),
              () => { setConfirmarAlta(false); return "Alta realizada sin contrato: se creó el colaborador y se cerró el proceso."; })}>
              Dar de alta sin generar el contrato
            </Button>
            <Button variant="ghost" onClick={() => setConfirmarAlta(false)} disabled={Boolean(ocupado)}>Cancelar</Button>
          </div>
        </ModalMarco>
      )}

      {/* ---------- Modal: captura manual de referencias ---------- */}
      {capturaRefs && (
        <ModalMarco titulo="Referencias del candidato" subtitulo="Nombre, relación y teléfono. Alimenta el mismo registro que la liga del candidato."
          onClose={() => !ocupado && setCapturaRefs(null)} ancho="max-w-xl">
          <div className="flex flex-col gap-3">
            {capturaRefs.map((r, i) => (
              <div key={i} className="grid gap-2 sm:grid-cols-3">
                <input className={inputRH} placeholder={`Nombre (referencia ${i + 1})`} value={r.nombre}
                  onChange={(e) => setCapturaRefs(capturaRefs.map((x, j) => (j === i ? { ...x, nombre: e.target.value } : x)))} />
                <select className={inputRH} value={r.parentesco} onChange={(e) => setCapturaRefs(capturaRefs.map((x, j) => (j === i ? { ...x, parentesco: e.target.value } : x)))}>
                  <option value="">Relación…</option>
                  {["Familiar", "Amistad", "Exjefe o excompañero", "Vecino(a)", "Otro"].map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
                <input className={inputRH} placeholder="Teléfono (10 dígitos)" inputMode="tel" value={r.telefono}
                  onChange={(e) => setCapturaRefs(capturaRefs.map((x, j) => (j === i ? { ...x, telefono: e.target.value } : x)))} />
              </div>
            ))}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCapturaRefs(null)} disabled={Boolean(ocupado)}>Cancelar</Button>
            <Button disabled={Boolean(ocupado) || capturaRefs.some((r) => !r.nombre.trim() || !r.parentesco || r.telefono.replace(/\D/g, "").length < 10)}
              onClick={() => ejecutar("refs", () => capturarReferenciasOperativo(codigo, capturaRefs), () => { setCapturaRefs(null); return "Referencias guardadas."; })}>
              Guardar referencias
            </Button>
          </div>
        </ModalMarco>
      )}

      {/* ---------- Modal: llamada a referencia ---------- */}
      {contacto && (
        <ModalMarco
          titulo="Registrar llamada a referencia"
          subtitulo={`${contacto.nombre} · ${contacto.parentesco} · ${contacto.telefono}`}
          onClose={() => !ocupado && setContacto(null)}
          ancho="max-w-lg"
        >
          <div className="flex flex-col gap-4">
            <CampoRH label="Fecha y hora de la llamada">
              <input type="datetime-local" value={contacto.fecha} max={ahoraLocal()} onChange={(e) => setContacto({ ...contacto, fecha: e.target.value })} className={inputRH} />
            </CampoRH>
            <CampoRH label="¿Se logró contactar?">
              <div className="flex gap-2">
                {[true, false].map((v) => (
                  <button key={String(v)} type="button" onClick={() => setContacto({ ...contacto, contactada: v, resultado: "" })}
                    className={cn("h-11 flex-1 rounded-xl border text-sm font-semibold transition",
                      contacto.contactada === v ? "border-brand bg-brand-soft text-brand" : "border-border-soft bg-surface text-ink-2 hover:border-brand/40")}>
                    {v ? "Sí, contactada" : "No se contactó"}
                  </button>
                ))}
              </div>
            </CampoRH>
            <CampoRH label="Resultado">
              <select value={contacto.resultado} onChange={(e) => setContacto({ ...contacto, resultado: e.target.value })} className={inputRH}>
                <option value="">Elige el resultado…</option>
                {(contacto.contactada
                  ? exp?.resultadosReferencia?.contactada ?? RESULTADOS_REFERENCIA_DEFAULT.contactada
                  : exp?.resultadosReferencia?.noContactada ?? RESULTADOS_REFERENCIA_DEFAULT.noContactada
                ).map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </CampoRH>
            <CampoRH label="Observaciones (opcional)" ayuda="Quedan en el historial con tu nombre.">
              <textarea rows={3} value={contacto.nota} onChange={(e) => setContacto({ ...contacto, nota: e.target.value })}
                className="w-full rounded-xl border border-border-soft bg-surface px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20" />
            </CampoRH>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setContacto(null)} disabled={Boolean(ocupado)}>Cancelar</Button>
            <Button onClick={confirmarContacto} disabled={Boolean(ocupado) || !contacto.resultado || !contacto.fecha}>
              <Phone className="h-4 w-4" /> {ocupado ? "Guardando…" : "Guardar llamada"}
            </Button>
          </div>
        </ModalMarco>
      )}
    </div>
  );
}

/** Captura interna: RH sube el documento desde la ficha (queda «Recibido» para revisión, igual que por la liga). */
function SubirDoc({ onArchivo, ocupado }: { onArchivo: (a: File) => void; ocupado: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <input ref={ref} type="file" className="hidden" accept="image/jpeg,image/png,image/webp,application/pdf"
        onChange={(e) => { const a = e.target.files?.[0]; if (a) onArchivo(a); e.target.value = ""; }} />
      <Button size="sm" variant="ghost" disabled={ocupado} onClick={() => ref.current?.click()} title="Subir el archivo desde la ficha">
        <Upload className="h-4 w-4" /> {ocupado ? "Subiendo…" : "Subir"}
      </Button>
    </>
  );
}
