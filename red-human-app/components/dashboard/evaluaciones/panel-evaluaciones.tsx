"use client";

/* Evaluaciones y verificaciones del candidato (2026-09-28; v2 2026-09-30). Se agregan desde la ficha («Agregar
   entrevista humana o evaluación») y NUNCA mueven la columna del pipeline: recibir o revisar un resultado no cambia
   la etapa (RH decide). Regla universal de ligas: cada liga (consentimiento, evaluador/médico/proveedor, enlace del
   candidato) existe desde que se crea la evaluación y se muestra con Abrir / Copiar / Enviar o reenviar; el envío va
   aparte y nunca la condiciona. La liga del evaluador y la captura manual de RH (siempre disponible) alimentan la
   MISMA evaluación. Médico: primero el consentimiento expreso; al aceptarlo se habilita la liga del médico. El informe
   médico completo solo lo ve quien tiene permiso. Estados: Pendiente → Enviada → En curso → Resultado recibido → Revisada.
   2026-10-01 (SEZA): «Entrevista humana» como opción (cita + entrevistador + Apto / No apto y observaciones); el texto
   del evaluador se muestra aparte del archivo adjunto («Resultado / comentarios del evaluador» con nombre y fecha);
   «Ver informe» abre un visor interno (Cerrar / Descargar) sin salir de la ficha; la «Capacitación en tienda» de la
   v1 queda como historial sin liga (antes su liga se confundía con la del médico). */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Ban, CalendarClock, CheckCircle2, ClipboardCheck, Download, Eye, FileText, FileUp, History, Loader2, Lock, MessageSquareText, PlayCircle, RefreshCw, Send, SkipForward, Stethoscope, UserCog, X, XCircle } from "lucide-react";
import { Badge, Button, Card, Eyebrow } from "@/components/ui";
import { MenuAcciones } from "@/components/dashboard/menu-acciones";
import { CampoRH, ModalMarco, inputRH } from "@/components/dashboard/modulos-rh";
import { LigaAcciones } from "@/components/dashboard/liga-acciones";
import {
  TIPOS_EVALUACION, agregarEvaluacionCandidato, asignarEvaluadorEvaluacion, avanzarEvaluacionIntegrada, cancelarEvaluacion,
  cargarResultadoEvaluacion, enviarEnlaceEvaluacion, enviarEvaluacion, enviarLigaConsentimientoMedico, enviarLigaEvaluador,
  fetchEntrevistadores, fetchEvaluacionesCandidato, fetchPruebasPsicometricas, lineasResultados, marcarEvaluacionEnCurso,
  revisarEvaluacion, sincronizarEvaluacion, urlInformeEvaluacion,
  type DatosEvaluador, type Entrevistador, type EvaluacionCandidato, type ModoPrueba, type PruebaPsicometrica, type TipoEvaluacion,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const PASOS: Record<string, string> = { asignada: "Asignada", enviada: "Enviada", iniciada: "Iniciada", completada: "Completada", resultado_recibido: "Resultado recibido" };
const ABIERTOS = ["pendiente", "en_proceso"];

function tonoEstado(e: EvaluacionCandidato): "good" | "warn" | "bad" | "neutral" | "brand" {
  if (e.estado === "revisada") return e.dictamen === "desfavorable" || e.dictamen === "no_apto" ? "bad" : e.dictamen === "con_observaciones" || e.dictamen === "apto_con_restricciones" ? "warn" : "good";
  if (e.estado === "fallida") return "neutral";
  if (e.estado === "en_espera_consentimiento") return "warn";
  if (e.estado === "resultado_recibido") return "brand";
  return "neutral";
}

function ultimoEnvio(e: EvaluacionCandidato, liga: string | null | undefined) {
  if (!liga) return null;
  const x = e.envios.find((v) => v.liga === liga);
  return x ? { enviado: x.enviado, detalle: x.detalle, canal: x.canal, fecha: x.fecha } : null;
}

function fechaTexto(iso?: string | null) {
  return iso ? new Date(iso).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" }) : "";
}

/** Quién llena la liga del evaluador, según el tipo (para que cada liga diga a quién corresponde). */
function rolEvaluador(e: EvaluacionCandidato) {
  if (e.tipo === "entrevista_humana") return "entrevistador";
  if (e.tipo === "medico") return "médico";
  if (e.tipo === "psicometrica") return "proveedor / evaluador";
  return "evaluador";
}

export function PanelEvaluaciones({ codigo, puesto, live, version, operativo = false }: { codigo: string; puesto?: string; live: boolean; version?: number; operativo?: boolean }) {
  const [lista, setLista] = useState<EvaluacionCandidato[] | null>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState("");
  const [resultado, setResultado] = useState<EvaluacionCandidato | null>(null);
  const [revisar, setRevisar] = useState<EvaluacionCandidato | null>(null);
  const [cancelar, setCancelar] = useState<EvaluacionCandidato | null>(null);
  const [evaluador, setEvaluador] = useState<EvaluacionCandidato | null>(null);
  const [agregar, setAgregar] = useState(false);
  const [visor, setVisor] = useState<EvaluacionCandidato | null>(null);

  const cargar = useCallback(async () => setLista((await fetchEvaluacionesCandidato(codigo)) ?? []), [codigo]);
  useEffect(() => {
    void cargar();
  }, [cargar, version]);

  async function accion(id: string, fn: () => Promise<{ ok: true; data: unknown } | { ok: false; error: string }>, ok = "") {
    setOcupado(id);
    setError("");
    setAviso("");
    const r = await fn();
    setOcupado("");
    if (!r.ok) return setError(r.error);
    if (ok) setAviso(ok);
    void cargar();
  }

  function enviarLiga(e: EvaluacionCandidato, clave: string, fn: () => Promise<{ ok: true; data: { envios: EvaluacionCandidato["envios"] } } | { ok: false; error: string }>) {
    void accion(`${e.id}-${clave}`, async () => {
      const r = await fn();
      if (r.ok) {
        const salio = r.data.envios.some((x) => x.enviado);
        setAviso(salio ? "Liga enviada." : "La liga no se pudo enviar automáticamente: cópiala y compártela (sigue disponible).");
      }
      return r;
    });
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Eyebrow>{operativo ? "Evaluaciones" : "Evaluaciones y verificaciones"}</Eyebrow>
          <p className="mt-1 text-[12px] text-ink-3">
            {operativo ? "Entrevista humana, psicométricas, técnicas, referencias, médico y socioeconómico." : "Psicométricas, técnicas, referencias, médico y socioeconómico."}
            {" "}Solicitar, recibir o revisar un resultado no mueve al candidato de etapa.
          </p>
        </div>
        {live && (
          <Button size="sm" variant="outline" onClick={() => setAgregar(true)}>
            <ClipboardCheck className="h-4 w-4" /> {operativo ? "Agregar entrevista humana o evaluación" : "Agregar evaluación"}
          </Button>
        )}
      </div>
      {error && <p className="mt-3 text-sm font-semibold text-bad">{error}</p>}
      {aviso && <p className="mt-3 text-sm text-good">{aviso}</p>}
      <div className="mt-3">
        {lista === null ? (
          <Loader2 className="h-5 w-5 animate-spin text-ink-3" />
        ) : lista.length === 0 ? (
          <p className="text-sm text-ink-3">Sin evaluaciones asignadas.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {lista.map((e) => {
              if (e.legado) return <EvaluacionHistorica key={e.id} e={e} />;
              const abierta = ABIERTOS.includes(e.estado);
              const capturaRestringida = e.tipo === "medico" && e.informeRestringido;
              return (
                <li key={e.id} className="rounded-xl border border-border-soft bg-surface px-3.5 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="flex items-center gap-1.5 truncate text-sm font-semibold">
                        {e.tipo === "medico" && <Stethoscope className="h-3.5 w-3.5 text-ink-3" />}
                        {e.tipo === "entrevista_humana" && <CalendarClock className="h-3.5 w-3.5 text-ink-3" />} {e.nombre}
                        <span className="font-normal text-ink-3">· {e.tipoTexto}{e.proveedor ? ` · ${e.proveedor}` : ""}</span>
                      </p>
                      <p className="truncate text-[11px] text-ink-3">
                        {e.evaluador?.nombre
                          ? `${e.tipo === "entrevista_humana" ? "Entrevistador" : "Evaluador"}: ${e.evaluador.nombre} (${e.evaluador.tipo === "interno" ? "interno" : "externo"})`
                          : e.tipo === "entrevista_humana" ? "Sin entrevistador asignado" : "Sin evaluador asignado"}
                        {e.cita ? ` · Cita ${fechaTexto(e.cita)}${e.citaLugar ? ` · ${e.citaLugar}` : ""}` : ""}
                      </p>
                      <p className="truncate text-[11px] text-ink-3">
                        {e.pasoIntegrada && e.modo === "integrada" ? `Integrada: ${PASOS[e.pasoIntegrada] ?? e.pasoIntegrada} · ` : ""}
                        {e.estado === "fallida" && e.motivoFallida ? `Motivo: ${e.motivoFallida}` : ""}
                      </p>
                    </div>
                    <Badge tone={tonoEstado(e)}>{e.estado === "revisada" && e.dictamenTexto ? `Revisada · ${e.dictamenTexto}` : e.estadoTexto}</Badge>
                  </div>

                  {/* ---- Ligas (regla universal): consentimiento primero, luego evaluador; enlace del candidato ---- */}
                  {e.estado !== "fallida" && (
                    <div className="mt-3 flex flex-col gap-2">
                      {e.requiereConsentimientoExpreso && !e.consentimientoAceptadoEn && e.ligaConsentimiento && (
                        <LigaAcciones
                          etiqueta={`1 · Consentimiento expreso del candidato · ${e.nombre} (${e.id})`}
                          liga={e.ligaConsentimiento}
                          enviando={ocupado === `${e.id}-cons`}
                          ultimoEnvio={null}
                          onEnviar={live ? () => void accion(`${e.id}-cons`, async () => {
                            const r = await enviarLigaConsentimientoMedico(e.id);
                            if (r.ok) setAviso(lineasResultados(r.data.resultados).map((l) => l.texto).join(" · ") || "Liga generada.");
                            return r;
                          }) : undefined}
                        />
                      )}
                      {e.requiereConsentimientoExpreso && e.consentimientoAceptadoEn && (
                        <p className="text-[12px] text-good">Consentimiento expreso aceptado · {fechaTexto(e.consentimientoAceptadoEn)}</p>
                      )}
                      {e.ligaEvaluador && e.estado !== "revisada" && (
                        e.ligaEvaluadorHabilitada ? (
                          <LigaAcciones
                            etiqueta={`${e.requiereConsentimientoExpreso ? "2 · " : ""}Liga del ${rolEvaluador(e)} · ${e.nombre} (${e.id})`}
                            liga={e.ligaEvaluador}
                            enviando={ocupado === `${e.id}-eval`}
                            ultimoEnvio={ultimoEnvio(e, e.ligaEvaluador)}
                            onEnviar={live && e.evaluador?.nombre ? () => enviarLiga(e, "eval", () => enviarLigaEvaluador(e.id)) : undefined}
                          />
                        ) : (
                          <p className="rounded-xl bg-surface-2 px-3 py-2 text-[12px] text-ink-3">
                            <Lock className="mr-1 inline h-3 w-3" />
                            {e.requiereConsentimientoExpreso
                              ? `La liga del médico (${e.nombre}) se habilita cuando el candidato acepte el consentimiento.`
                              : `La liga del ${rolEvaluador(e)} se habilita con el consentimiento de privacidad.`}
                          </p>
                        )
                      )}
                      {e.url && abierta && (
                        <LigaAcciones
                          etiqueta="Enlace del candidato (proveedor)"
                          liga={e.url}
                          enviando={ocupado === `${e.id}-enl`}
                          ultimoEnvio={ultimoEnvio(e, e.url)}
                          onEnviar={live ? () => enviarLiga(e, "enl", () => enviarEnlaceEvaluacion(e.id)) : undefined}
                        />
                      )}
                    </div>
                  )}

                  {e.claveProveedor && (
                    <p className="mt-2 text-[12px] text-ink-2">
                      Psicométricas.mx · clave <span className="font-mono">{e.claveProveedor}</span>
                      {!e.urlCandidato && <span className="text-ink-3"> (Psicométricas.mx le manda su liga por correo)</span>}
                    </p>
                  )}
                  {e.estado === "en_espera_consentimiento" && !e.requiereConsentimientoExpreso && (
                    <p className="mt-2 text-[12px] text-warn">Falta el consentimiento de privacidad del candidato. Regístralo en la ficha.</p>
                  )}

                  {/* ---- Acciones: una principal visible + el resto en «…» ---- */}
                  {live && (
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {abierta && !capturaRestringida && (
                        <Button size="sm" onClick={() => setResultado(e)}><FileUp className="h-4 w-4" /> Registrar resultado</Button>
                      )}
                      {e.estado === "resultado_recibido" && (
                        <Button size="sm" onClick={() => setRevisar(e)}><CheckCircle2 className="h-4 w-4" /> Marcar como revisada</Button>
                      )}
                      {e.estado === "pendiente" && (
                        <Button size="sm" variant="outline" disabled={Boolean(ocupado)} onClick={() => accion(e.id, () => enviarEvaluacion(e.id), `«${e.nombre}» enviada.`)}>
                          {ocupado === e.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Marcar enviada
                        </Button>
                      )}
                      {e.estado === "en_proceso" && e.estadoTexto === "Enviada" && !e.conectadaProveedor && (
                        <Button size="sm" variant="outline" disabled={Boolean(ocupado)} onClick={() => accion(e.id, () => marcarEvaluacionEnCurso(e.id), "En curso.")}>
                          <PlayCircle className="h-4 w-4" /> Marcar en curso
                        </Button>
                      )}
                      {e.estado === "en_proceso" && e.conectadaProveedor && (
                        <Button size="sm" variant="outline" disabled={Boolean(ocupado)}
                          onClick={() => accion(e.id, async () => {
                            const r = await sincronizarEvaluacion(e.id);
                            if (r.ok) setAviso(r.data.sincronizacion === "resultado_recibido" ? "Resultado recibido de Psicométricas.mx." : "El candidato aún no termina sus pruebas.");
                            return r;
                          })}>
                          <RefreshCw className="h-4 w-4" /> Consultar resultado
                        </Button>
                      )}
                      <MenuAcciones
                        acciones={[
                          ...(abierta || e.estado === "en_espera_consentimiento"
                            ? [{
                                etiqueta: e.tipo === "entrevista_humana"
                                  ? (e.evaluador?.nombre ? "Cambiar entrevistador / agenda…" : "Agendar / asignar entrevistador…")
                                  : (e.evaluador?.nombre ? "Cambiar evaluador / cita…" : "Asignar evaluador / cita…"),
                                icono: <UserCog className="h-4 w-4" />, onClick: () => setEvaluador(e),
                              }]
                            : []),
                          ...(e.estado === "en_proceso" && e.modo === "integrada" && e.siguientePaso && !e.conectadaProveedor
                            ? [{ etiqueta: `Simular paso: ${PASOS[e.siguientePaso]}`, icono: <SkipForward className="h-4 w-4" />, onClick: () => accion(e.id, () => avanzarEvaluacionIntegrada(e.id)) }]
                            : []),
                          ...(e.estado !== "revisada" && e.estado !== "fallida"
                            ? [{ etiqueta: "Marcar fallida / cancelar…", icono: <Ban className="h-4 w-4" />, peligrosa: true, onClick: () => setCancelar(e) }]
                            : []),
                        ]}
                      />
                    </div>
                  )}

                  {e.informeRestringido ? (
                    <p className="mt-2 flex items-center gap-1.5 text-[11px] text-ink-3"><Lock className="h-3 w-3" /> Informe médico restringido: solo ves el estado y el dictamen.</p>
                  ) : (
                    (e.resultadoCargadoPor || e.resultadoResumen || e.tieneInforme || e.estado === "revisada") && (
                      <div className="mt-3 flex flex-col gap-2">
                        {/* 1) Lo que escribió el evaluador (o RH por él): texto con nombre y fecha */}
                        {(e.resultadoCargadoPor || e.resultadoResumen) && (
                          <div className="rounded-xl border border-border-soft bg-surface-2/50 px-3 py-2">
                            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                              <MessageSquareText className="h-3.5 w-3.5" /> Resultado / comentarios del {e.tipo === "entrevista_humana" ? "entrevistador" : "evaluador"}
                            </p>
                            {e.aptoEvaluadorTexto && (
                              <p className="mt-1"><Badge tone={e.aptoEvaluador === "apto" ? "good" : "bad"} dot>{e.aptoEvaluadorTexto}</Badge></p>
                            )}
                            {e.resultadoResumen
                              ? <p className="mt-1 whitespace-pre-line text-[13px] leading-relaxed text-ink">{e.resultadoResumen}</p>
                              : <p className="mt-1 text-[12px] text-ink-3">Sin comentarios escritos{e.tieneInforme ? " (ver el informe adjunto)" : ""}.</p>}
                            {e.resultadoCargadoPor && (
                              <p className="mt-1 text-[11px] text-ink-3">
                                {e.resultadoCargadoPor} · {fechaTexto(e.resultadoCargadoEn)} · {e.resultadoOrigen === "evaluador" ? "liga del evaluador" : e.resultadoOrigen === "rh" ? "captura de RH" : "proveedor"}
                              </p>
                            )}
                          </div>
                        )}
                        {/* 2) El archivo adjunto, aparte: visor interno + descarga separada */}
                        {e.tieneInforme && (
                          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border-soft px-3 py-2">
                            <FileText className="h-4 w-4 shrink-0 text-ink-3" />
                            <span className="min-w-0 flex-1 truncate text-[12px] text-ink-2" title={e.nombreArchivo}>Informe adjunto{e.nombreArchivo ? ` · ${e.nombreArchivo}` : ""}</span>
                            <Button size="sm" variant="outline" onClick={() => setVisor(e)}><Eye className="h-4 w-4" /> Ver informe</Button>
                            <a href={urlInformeEvaluacion(e.id, true)} download={e.nombreArchivo || undefined}
                              className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-[12px] font-semibold text-brand hover:bg-brand-soft">
                              <Download className="h-3.5 w-3.5" /> Descargar
                            </a>
                          </div>
                        )}
                        {/* 3) Revisión de RH: estado aparte de «Resultado recibido» */}
                        {e.estado === "revisada" && (
                          <p className="text-[12px] text-ink-3">
                            Revisada por {e.revisadaPor} · {fechaTexto(e.revisadaEn)}{e.comentarioRevision ? ` — Conclusión: ${e.comentarioRevision}` : ""}
                          </p>
                        )}
                      </div>
                    )
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {agregar && <ModalAgregarEvaluacion codigo={codigo} puesto={puesto} conEntrevistaHumana={operativo} onClose={() => setAgregar(false)} onAgregada={() => { setAgregar(false); void cargar(); }} />}
      {resultado && <ModalResultado e={resultado} onClose={() => setResultado(null)}
        onListo={(avisoArchivo) => { setResultado(null); setError(""); setAviso(avisoArchivo || "Resultado registrado: queda «Resultado recibido» hasta que lo marques como revisada."); void cargar(); }} />}
      {visor && <VisorInforme e={visor} onClose={() => setVisor(null)} />}
      {revisar && <ModalRevisar e={revisar} onClose={() => setRevisar(null)} onListo={() => { setRevisar(null); void cargar(); }} />}
      {cancelar && <ModalCancelar e={cancelar} onClose={() => setCancelar(null)} onListo={() => { setCancelar(null); void cargar(); }} />}
      {evaluador && <ModalEvaluador e={evaluador} onClose={() => setEvaluador(null)} onListo={() => { setEvaluador(null); void cargar(); }} />}
    </Card>
  );
}

/* ---------- Evaluador + cita (compartido entre «Agregar» y «Asignar evaluador») ---------- */

type FormEvaluador = Required<Pick<DatosEvaluador, "evaluador_tipo">> & {
  usuario: number | null; nombre: string; telefono: string; correo: string; fecha: string; hora: string; lugar: string;
};
const EVALUADOR_VACIO: FormEvaluador = { evaluador_tipo: "", usuario: null, nombre: "", telefono: "", correo: "", fecha: "", hora: "09:00", lugar: "" };

function aDatosEvaluador(f: FormEvaluador): DatosEvaluador {
  return {
    evaluador_tipo: f.evaluador_tipo, evaluador_usuario_id: f.usuario, evaluador_nombre: f.nombre, evaluador_telefono: f.telefono,
    evaluador_correo: f.correo, cita_fecha: f.fecha, cita_hora: f.hora, cita_lugar: f.lugar,
  };
}

function CamposEvaluador({ f, set, conCita = true, rol = "Evaluador" }: { f: FormEvaluador; set: (f: FormEvaluador) => void; conCita?: boolean; rol?: string }) {
  const [usuarios, setUsuarios] = useState<Entrevistador[]>([]);
  useEffect(() => {
    fetchEntrevistadores().then((u) => setUsuarios(u ?? []));
  }, []);
  return (
    <div className="flex flex-col gap-3">
      <CampoRH label={`${rol} (opcional)`}>
        <div className="grid grid-cols-3 gap-2">
          {([["", "Sin asignar"], ["interno", "Usuario de la Cuenta"], ["externo", "Externo"]] as const).map(([v, t]) => (
            <button key={v} type="button" onClick={() => set({ ...f, evaluador_tipo: v })}
              className={cn("h-10 rounded-xl border text-sm font-semibold", f.evaluador_tipo === v ? "border-brand bg-brand-soft text-brand" : "border-border-soft text-ink-2")}>
              {t}
            </button>
          ))}
        </div>
      </CampoRH>
      {f.evaluador_tipo === "interno" && (
        <CampoRH label="Usuario" ayuda="Teléfono y correo salen de su perfil.">
          <select className={inputRH} value={f.usuario ?? ""} onChange={(e) => set({ ...f, usuario: e.target.value ? Number(e.target.value) : null })}>
            <option value="">Elige…</option>
            {usuarios.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
          </select>
        </CampoRH>
      )}
      {f.evaluador_tipo === "externo" && (
        <div className="grid gap-3 sm:grid-cols-3">
          <CampoRH label="Nombre"><input className={inputRH} value={f.nombre} onChange={(e) => set({ ...f, nombre: e.target.value })} /></CampoRH>
          <CampoRH label="Teléfono"><input className={inputRH} value={f.telefono} onChange={(e) => set({ ...f, telefono: e.target.value })} /></CampoRH>
          <CampoRH label="Correo"><input className={inputRH} value={f.correo} onChange={(e) => set({ ...f, correo: e.target.value })} /></CampoRH>
        </div>
      )}
      {conCita && (
        <div className="grid gap-3 sm:grid-cols-3">
          <CampoRH label={rol === "Entrevistador" ? "Fecha de la entrevista" : "Cita (opcional)"}><input type="date" className={inputRH} value={f.fecha} onChange={(e) => set({ ...f, fecha: e.target.value })} /></CampoRH>
          <CampoRH label="Hora"><input type="time" className={inputRH} value={f.hora} onChange={(e) => set({ ...f, hora: e.target.value })} /></CampoRH>
          <CampoRH label="Lugar"><input className={inputRH} value={f.lugar} onChange={(e) => set({ ...f, lugar: e.target.value })} placeholder="Domicilio, clínica…" /></CampoRH>
        </div>
      )}
    </div>
  );
}

function ModalEvaluador({ e, onClose, onListo }: { e: EvaluacionCandidato; onClose: () => void; onListo: () => void }) {
  const cita = e.cita ? new Date(e.cita) : null;
  const [f, setF] = useState<FormEvaluador>({
    evaluador_tipo: e.evaluador.tipo, usuario: e.evaluador.usuarioId, nombre: e.evaluador.tipo === "externo" ? e.evaluador.nombre : "",
    telefono: e.evaluador.tipo === "externo" ? e.evaluador.telefono : "", correo: e.evaluador.tipo === "externo" ? e.evaluador.correo : "",
    fecha: cita ? cita.toLocaleDateString("sv-SE") : "", hora: cita ? cita.toTimeString().slice(0, 5) : "09:00", lugar: e.citaLugar,
  });
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  return (
    <ModalMarco titulo={`${e.tipo === "entrevista_humana" ? "Entrevistador y agenda" : "Evaluador"} · ${e.nombre}`} subtitulo="La liga no cambia; puedes reenviarla después." onClose={onClose}>
      <CamposEvaluador f={f} set={setF} rol={e.tipo === "entrevista_humana" ? "Entrevistador" : "Evaluador"} />
      {error && <p className="mt-3 text-sm font-semibold text-bad">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onClose} disabled={ocupado}>Cancelar</Button>
        <Button size="sm" disabled={ocupado} onClick={async () => {
          setOcupado(true);
          const r = await asignarEvaluadorEvaluacion(e.id, aDatosEvaluador(f));
          setOcupado(false);
          if (!r.ok) return setError(r.error);
          onListo();
        }}>
          {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserCog className="h-4 w-4" />} Guardar
        </Button>
      </div>
    </ModalMarco>
  );
}

/** «Agregar entrevista humana o evaluación». `onEntrevistaHumana` (flujo de RH) abre el modal propio de la Entrevista
 *  Humana; `conEntrevistaHumana` (flujo operativo, 2026-10-01) la ofrece como evaluación adicional: se agenda, se asigna
 *  entrevistador (con su liga) y se registra Apto / No apto + observaciones. Ninguna opción mueve la columna. */
export function ModalAgregarEvaluacion({
  codigo, puesto, onClose, onAgregada, onEntrevistaHumana, conEntrevistaHumana = false,
}: { codigo: string; puesto?: string; onClose: () => void; onAgregada: (e: EvaluacionCandidato) => void; onEntrevistaHumana?: () => void; conEntrevistaHumana?: boolean }) {
  const [tipo, setTipo] = useState<TipoEvaluacion | "">("");
  const [pruebas, setPruebas] = useState<PruebaPsicometrica[] | null>(null);
  const [pruebaId, setPruebaId] = useState<number | null>(null);
  const [nombre, setNombre] = useState("");
  const [modo, setModo] = useState<ModoPrueba>("manual");
  const [url, setUrl] = useState("");
  const [proveedor, setProveedor] = useState("");
  const [ev, setEv] = useState<FormEvaluador>(EVALUADOR_VACIO);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (tipo === "psicometrica" && pruebas === null) fetchPruebasPsicometricas(false, puesto ?? "").then((p) => setPruebas(p ?? []));
  }, [tipo, pruebas, puesto]);

  async function guardar() {
    if (!tipo) return setError("Elige el tipo.");
    if (tipo === "psicometrica" && !pruebaId && !nombre.trim()) return setError("Escribe el nombre de la prueba o elígela del catálogo.");
    setOcupado(true);
    const r = await agregarEvaluacionCandidato(codigo, {
      tipo, nombre, prueba_id: tipo === "psicometrica" ? pruebaId : null, modo, url, proveedor, ...aDatosEvaluador(ev),
    });
    setOcupado(false);
    if (!r.ok) return setError(r.error);
    onAgregada(r.data);
  }

  return (
    <ModalMarco titulo={onEntrevistaHumana || conEntrevistaHumana ? "Agregar entrevista humana o evaluación" : "Agregar evaluación"}
      subtitulo="La columna del pipeline no cambia. Las ligas se generan al guardar; enviarlas es aparte." onClose={onClose}>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {onEntrevistaHumana && (
          <button type="button" onClick={onEntrevistaHumana}
            className="flex items-center gap-1.5 rounded-xl border border-border-soft px-3 py-2.5 text-left text-sm font-medium text-ink-2 transition hover:border-brand/50">
            <CalendarClock className="h-4 w-4" /> Entrevista humana
          </button>
        )}
        {TIPOS_EVALUACION.filter((t) => t.valor !== "entrevista_humana" || (conEntrevistaHumana && !onEntrevistaHumana)).map((t) => (
          <button key={t.valor} type="button" onClick={() => { setTipo(t.valor); setError(""); }}
            className={cn("rounded-xl border px-3 py-2.5 text-left text-sm font-medium transition",
              tipo === t.valor ? "border-brand bg-brand-soft text-brand" : "border-border-soft text-ink-2 hover:border-brand/50")}>
            {t.valor === "entrevista_humana" && <CalendarClock className="mr-1.5 inline h-4 w-4" />}{t.texto}
          </button>
        ))}
      </div>
      {tipo === "psicometrica" && pruebas && pruebas.length > 0 && (
        <div className="mt-4">
          <CampoRH label="Del catálogo (opcional)">
            <select value={pruebaId ?? ""} onChange={(e) => setPruebaId(e.target.value ? Number(e.target.value) : null)} className={inputRH}>
              <option value="">Captura libre (nombre y proveedor abajo)</option>
              {pruebas.map((p) => <option key={p.id} value={p.id}>{p.nombre} · {p.modoTexto}{p.sugerida ? " · sugerida para el puesto" : ""}</option>)}
            </select>
          </CampoRH>
        </div>
      )}
      {tipo && tipo !== "entrevista_humana" && !(tipo === "psicometrica" && pruebaId) && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <CampoRH label={tipo === "psicometrica" ? "Nombre de prueba" : "Nombre (opcional)"}>
            <input value={nombre} onChange={(e) => setNombre(e.target.value)} className={inputRH} placeholder={tipo === "psicometrica" ? "Cleaver, Terman…" : TIPOS_EVALUACION.find((t) => t.valor === tipo)?.texto} />
          </CampoRH>
          <CampoRH label="Proveedor (opcional)"><input value={proveedor} onChange={(e) => setProveedor(e.target.value)} className={inputRH} /></CampoRH>
          <CampoRH label="Modo">
            <select value={modo} onChange={(e) => setModo(e.target.value as ModoPrueba)} className={inputRH}>
              <option value="manual">Carga manual / liga del evaluador</option>
              <option value="enlace">Enlace externo para el candidato</option>
              <option value="integrada">Integrada</option>
            </select>
          </CampoRH>
          {modo === "enlace" && <CampoRH label="Enlace del candidato"><input value={url} onChange={(e) => setUrl(e.target.value)} className={inputRH} placeholder="https://…" /></CampoRH>}
        </div>
      )}
      {tipo && (
        <div className="mt-4 border-t border-border-faint pt-4">
          {tipo === "entrevista_humana" && (
            <p className="mb-3 text-[12px] text-ink-3">Agenda la entrevista y asigna al entrevistador: con su liga registra Apto / No apto y observaciones (o captúralo tú desde la ficha).</p>
          )}
          <CamposEvaluador f={ev} set={setEv} conCita={tipo !== "psicometrica"} rol={tipo === "entrevista_humana" ? "Entrevistador" : "Evaluador"} />
        </div>
      )}
      {tipo === "medico" && (
        <p className="mt-3 rounded-xl border border-warn/30 bg-warn-soft px-3 py-2 text-[12px] text-warn">
          Primero se manda la liga de consentimiento EXPRESO y POR ESCRITO; al aceptarla se habilita la liga del médico.
        </p>
      )}
      {error && <p className="mt-3 text-sm font-semibold text-bad">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onClose} disabled={ocupado}>Cancelar</Button>
        <Button size="sm" onClick={guardar} disabled={ocupado || !tipo}>
          {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />} Agregar
        </Button>
      </div>
    </ModalMarco>
  );
}

function ModalResultado({ e, onClose, onListo }: { e: EvaluacionCandidato; onClose: () => void; onListo: (avisoArchivo: string) => void }) {
  const esEntrevista = e.tipo === "entrevista_humana";
  const [apto, setApto] = useState(e.aptoEvaluador ?? "");
  const [resumen, setResumen] = useState(e.resultadoResumen ?? "");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  return (
    <ModalMarco titulo={`Registrar resultado · ${e.nombre}`} subtitulo="Captura interna de RH: alimenta la misma evaluación que la liga del evaluador. Queda quién y cuándo. No cambia la etapa." onClose={onClose}>
      {esEntrevista && (
        <div className="mb-3">
          <CampoRH label="Resultado de la entrevista">
            <div className="grid grid-cols-2 gap-2">
              {([["apto", "Apto"], ["no_apto", "No apto"]] as const).map(([v, t]) => (
                <button key={v} type="button" onClick={() => setApto(v)}
                  className={cn("h-11 rounded-xl border text-sm font-semibold", apto === v ? (v === "apto" ? "border-good bg-good-soft text-good" : "border-bad bg-bad-soft text-bad") : "border-border-soft text-ink-2")}>
                  {t}
                </button>
              ))}
            </div>
          </CampoRH>
        </div>
      )}
      <CampoRH label={esEntrevista ? "Observaciones" : "Resultado / comentarios del evaluador"}>
        <textarea value={resumen} onChange={(x) => setResumen(x.target.value)} rows={4} className="rounded-xl border border-border-soft bg-surface px-3 py-2 text-sm outline-none focus:border-brand" />
      </CampoRH>
      <input ref={ref} type="file" accept="application/pdf,image/*" className="hidden" onChange={(x) => setArchivo(x.target.files?.[0] ?? null)} />
      <Button variant="outline" size="sm" className="mt-3" onClick={() => ref.current?.click()}><FileUp className="h-4 w-4" /> {archivo ? archivo.name : "Adjuntar informe (PDF o imagen)"}</Button>
      {error && <p className="mt-3 text-sm font-semibold text-bad">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onClose} disabled={ocupado}>Cancelar</Button>
        <Button size="sm" disabled={ocupado || (esEntrevista ? !apto : !resumen.trim() && !archivo)} onClick={async () => {
          setOcupado(true);
          const r = await cargarResultadoEvaluacion(e.id, resumen.trim(), archivo, esEntrevista ? apto : "");
          setOcupado(false);
          if (!r.ok) return setError(r.error);
          onListo(r.data.avisoArchivo ?? "");
        }}>
          {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />} Guardar resultado
        </Button>
      </div>
    </ModalMarco>
  );
}

function ModalRevisar({ e, onClose, onListo }: { e: EvaluacionCandidato; onClose: () => void; onListo: () => void }) {
  const [dictamen, setDictamen] = useState<string>(e.aptoEvaluador ?? "");
  const [conclusion, setConclusion] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  return (
    <ModalMarco titulo={`Marcar como revisada · ${e.nombre}`}
      subtitulo="Queda tu nombre, la fecha y la conclusión. El candidato NO cambia de etapa: tú decides cuándo avanza." onClose={onClose}>
      <div className="grid gap-2 sm:grid-cols-3">
        {e.dictamenesPosibles.map((d) => (
          <button key={d.valor} type="button" onClick={() => setDictamen(d.valor)}
            className={cn("rounded-xl border px-3 py-2.5 text-sm font-medium transition", dictamen === d.valor ? "border-brand bg-brand-soft text-brand" : "border-border-soft text-ink-2 hover:border-brand/50")}>
            {d.texto}
          </button>
        ))}
      </div>
      <div className="mt-3">
        <CampoRH label="Conclusión">
          <textarea value={conclusion} onChange={(x) => setConclusion(x.target.value)} rows={3} className="rounded-xl border border-border-soft bg-surface px-3 py-2 text-sm outline-none focus:border-brand" />
        </CampoRH>
      </div>
      {error && <p className="mt-3 text-sm font-semibold text-bad">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onClose} disabled={ocupado}>Cancelar</Button>
        <Button size="sm" disabled={ocupado || !dictamen || !conclusion.trim()} onClick={async () => {
          setOcupado(true);
          const r = await revisarEvaluacion(e.id, dictamen, conclusion.trim());
          setOcupado(false);
          if (!r.ok) return setError(r.error);
          onListo();
        }}>
          {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Marcar como revisada
        </Button>
      </div>
    </ModalMarco>
  );
}

function ModalCancelar({ e, onClose, onListo }: { e: EvaluacionCandidato; onClose: () => void; onListo: () => void }) {
  const [motivo, setMotivo] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  return (
    <ModalMarco titulo="Fallida / Cancelada" subtitulo={`«${e.nombre}» queda cerrada. El motivo es obligatorio.`} onClose={onClose}>
      <CampoRH label="Motivo"><input value={motivo} onChange={(x) => setMotivo(x.target.value)} className={inputRH} autoFocus /></CampoRH>
      {error && <p className="mt-3 text-sm font-semibold text-bad">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onClose} disabled={ocupado}>Volver</Button>
        <Button size="sm" disabled={ocupado || !motivo.trim()} onClick={async () => {
          setOcupado(true);
          const r = await cancelarEvaluacion(e.id, motivo.trim());
          setOcupado(false);
          if (!r.ok) return setError(r.error);
          onListo();
        }}>
          {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />} Marcar fallida / cancelada
        </Button>
      </div>
    </ModalMarco>
  );
}

/** «Capacitación en tienda» de la versión anterior: solo historial (sin liga ni acciones; ya vive en la Entrevista). */
function EvaluacionHistorica({ e }: { e: EvaluacionCandidato }) {
  return (
    <li className="rounded-xl border border-dashed border-border-soft bg-surface-2/40 px-3.5 py-2.5">
      <p className="flex items-center gap-1.5 text-[12px] text-ink-3">
        <History className="h-3.5 w-3.5" /> Historial · {e.nombre} ({e.id}) — versión anterior; su resultado ya está en la Entrevista. Sin liga.
      </p>
    </li>
  );
}

/** Visor interno del informe (PDF o imagen) con «Cerrar» y «Descargar» por separado. Se pinta en un portal sobre la
 *  ficha: al cerrarlo la ficha, la pestaña activa, los filtros y la posición del tablero siguen intactos (nada navega
 *  ni se recarga). Un archivo que no se puede mostrar (p. ej. una captura vacía de prueba) se informa sin marcar
 *  falla. */
export function VisorInforme({ e, onClose }: { e: EvaluacionCandidato; onClose: () => void }) {
  const url = urlInformeEvaluacion(e.id);
  const nombre = (e.nombreArchivo || "").toLowerCase();
  const mime = e.mimeInforme || "";
  const esImagen = mime.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/.test(nombre);
  const [sinVista, setSinVista] = useState(false);
  useEffect(() => {
    const tecla = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        ev.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", tecla, true);
    return () => window.removeEventListener("keydown", tecla, true);
  }, [onClose]);
  if (typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-0 backdrop-blur-sm sm:p-6"
      role="dialog" aria-modal="true" aria-label={`Informe · ${e.nombre}`}
      onClick={(x) => { x.stopPropagation(); onClose(); }}>
      <div className="flex h-[100dvh] w-full max-w-4xl flex-col overflow-hidden bg-bg shadow-2xl sm:h-[90vh] sm:rounded-2xl" onClick={(x) => x.stopPropagation()}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-soft px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">{e.nombre} · {e.tipoTexto}</p>
            <p className="truncate text-[11px] text-ink-3">{e.nombreArchivo || "Informe"}{e.resultadoCargadoPor ? ` · ${e.resultadoCargadoPor}` : ""}</p>
          </div>
          <div className="flex items-center gap-2">
            <a href={urlInformeEvaluacion(e.id, true)} download={e.nombreArchivo || undefined}
              className="inline-flex h-9 items-center gap-1 rounded-xl border border-border-soft px-3 text-sm font-semibold text-brand hover:bg-brand-soft">
              <Download className="h-4 w-4" /> Descargar
            </a>
            <Button size="sm" onClick={onClose}><X className="h-4 w-4" /> Cerrar</Button>
          </div>
        </div>
        <div className="relative flex-1 overflow-auto bg-surface-2">
          {sinVista ? (
            <div className="grid h-full place-items-center p-6 text-center text-sm text-ink-3">
              Este archivo no tiene una vista previa disponible (puede ser una captura vacía). Usa «Descargar» para revisarlo.
            </div>
          ) : esImagen ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={e.nombreArchivo || "Informe"} className="mx-auto max-h-full max-w-full object-contain p-2" onError={() => setSinVista(true)} />
          ) : (
            <iframe src={url} title={`Informe · ${e.nombre}`} className="h-full w-full border-0 bg-white" />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
