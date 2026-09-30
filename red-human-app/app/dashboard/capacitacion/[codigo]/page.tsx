"use client";

/* Ficha del curso (módulo universal, 2026-09-16): resumen compacto; Objetivo visible; Módulos y Evaluación en
   secciones CONTRAÍDAS (sin efecto libro), editables solo si RH quiere; UNA acción principal («Publicar curso» o
   «Asignar»); secundarias en «…». Asignación universal: colaboradores, candidatos o externos, mismo curso. */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Check, ChevronDown, ChevronRight, Copy, Download, ExternalLink, Link2, Loader2, Pencil, RefreshCw, Save, Send, Sparkles, Users, X } from "lucide-react";
import { Badge, Button, Card, Eyebrow } from "@/components/ui";
import { PageHeader } from "@/components/dashboard/parts";
import { Aviso } from "@/components/dashboard/subida";
import { MenuAcciones } from "@/components/dashboard/menu-acciones";
import { usePuedeDecidir } from "@/components/sesion";
import { usePolling } from "@/lib/use-polling";
import { duplicarCurso } from "@/lib/api";
import {
  archivarCurso,
  asignarCurso,
  editarCurso,
  fetchAsignacionesCurso,
  generarLigaDemoCurso,
  fetchCandidatos,
  fetchColaboradores,
  fetchCurso,
  publicarCurso,
  etiquetaEstadoCurso,
  urlPdfCurso,
  type AsignacionCurso,
  type Colaborador,
  type Curso,
  type PreguntaEvaluacion,
} from "@/lib/api";
import type { Candidato } from "@/lib/data";
import { cn } from "@/lib/utils";

const ETIQUETA_TIPO = { colaborador: "Colaborador", candidato: "Candidato", externo: "Externo" } as const;

function Plegable({ titulo, resumen, children, abiertoInicial = false }: { titulo: string; resumen?: string; children: React.ReactNode; abiertoInicial?: boolean }) {
  const [abierto, setAbierto] = useState(abiertoInicial);
  return (
    <section className="rounded-2xl border border-border-soft bg-surface">
      <button type="button" onClick={() => setAbierto((a) => !a)} aria-expanded={abierto} className="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left">
        <span className="min-w-0">
          <span className="text-sm font-semibold text-ink">{titulo}</span>
          {resumen && <span className="block truncate text-xs text-ink-3">{resumen}</span>}
        </span>
        {abierto ? <ChevronDown className="h-4 w-4 shrink-0 text-ink-3" /> : <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" />}
      </button>
      {abierto && <div className="border-t border-border-faint px-5 py-4">{children}</div>}
    </section>
  );
}

export default function FichaCurso() {
  const params = useParams();
  const codigo = String(params?.codigo ?? "");
  const router = useRouter();
  const puedeDecidir = usePuedeDecidir();
  const [curso, setCurso] = useState<Curso | null>(null);
  const [asignaciones, setAsignaciones] = useState<AsignacionCurso[]>([]);
  const [cargando, setCargando] = useState(true);
  const [aviso, setAviso] = useState<{ tono: "ok" | "error" | "warn"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState("");
  const [asignar, setAsignar] = useState(false);
  // 2026-09-23 (Expo): liga pública inmediata para demostrar el curso en el tótem
  const [ligaDemo, setLigaDemo] = useState<{ liga: string; ligaTotem: string; reutilizada: boolean } | null>(null);
  const [editando, setEditando] = useState<null | "objetivo" | "modulos" | "evaluacion">(null);

  const recargar = useCallback(async () => {
    const [c, a] = await Promise.all([fetchCurso(codigo), fetchAsignacionesCurso(codigo)]);
    if (c) setCurso(c);
    if (a) setAsignaciones(a);
    setCargando(false);
  }, [codigo]);
  useEffect(() => {
    recargar();
  }, [recargar]);
  usePolling(recargar, undefined, !asignar && editando === null);

  async function publicar() {
    if (!curso) return;
    setOcupado("publicar");
    const r = await publicarCurso(curso.id);
    setOcupado("");
    if (!r.ok) return setAviso({ tono: "error", texto: r.error });
    setCurso(r.data);
    setAviso({ tono: "ok", texto: "Curso publicado: ya se puede asignar." });
  }

  async function generarLigaDemo(nueva = false) {
    if (!curso) return;
    setOcupado("demo");
    const r = await generarLigaDemoCurso(curso.id, nueva);
    setOcupado("");
    if (!r.ok) return setAviso({ tono: "error", texto: r.error });
    setLigaDemo({ liga: r.data.liga, ligaTotem: r.data.ligaTotem, reutilizada: r.data.reutilizada });
    recargar();
  }

  /** Demo SEZA: copia completa del curso (módulos, evaluación y material) con otro nombre. */
  async function duplicar() {
    if (!curso) return;
    const titulo = window.prompt("Nombre de la copia", `${curso.titulo} (copia)`);
    if (!titulo?.trim()) return;
    const r = await duplicarCurso(curso.id, titulo.trim());
    if (!r.ok) return setAviso({ tono: "error", texto: r.error });
    router.push(`/dashboard/capacitacion/${r.data.id}`);
  }

  async function archivar() {
    if (!curso || !window.confirm(`¿Archivar «${curso.titulo}»?`)) return;
    const r = await archivarCurso(curso.id);
    if (!r.ok) return setAviso({ tono: "error", texto: r.error });
    router.push("/dashboard/capacitacion");
  }

  if (cargando || !curso) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
        {cargando ? <Loader2 className="h-6 w-6 animate-spin text-ink-3" /> : <Aviso tono="error">Curso no encontrado.</Aviso>}
      </div>
    );
  }

  const completadas = asignaciones.filter((a) => a.estado === "completado");

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
      <Link href="/dashboard/capacitacion" className="inline-flex items-center gap-1.5 text-xs text-ink-3 hover:text-ink"><ArrowLeft className="h-3.5 w-3.5" /> Capacitación</Link>
      <PageHeader title={curso.titulo} subtitle={`${curso.categoria || "General"} · ${curso.modalidad === "instructor_ia" ? "Instructor IA" : "Autoguiado"} · ${curso.duracion || `${curso.duracionHoras} h`} · ${curso.modulos} módulos · ${curso.preguntas} preguntas · mínimo ${curso.calificacionMinima}%`}>
        <Badge tone={curso.estado === "Publicado" ? "good" : "neutral"} dot>{etiquetaEstadoCurso(curso.estado)}</Badge>
        {puedeDecidir && curso.estado === "Borrador" && (
          <Button onClick={publicar} disabled={Boolean(ocupado)} title="Crear → Revisar → Finalizar → Asignar">
            <Check className="h-4 w-4" /> {ocupado === "publicar" ? "Finalizando…" : "Finalizar curso"}
          </Button>
        )}
        {puedeDecidir && curso.estado === "Publicado" && (
          <Button onClick={() => setAsignar(true)}>
            <Users className="h-4 w-4" /> Asignar
          </Button>
        )}
        {/* Botón Mágico (Expo 2026-09-23): liga pública al instante, sin persona real ni WhatsApp.
            Sirve aunque el curso siga en Borrador: en la Expo se genera y se enseña en el mismo minuto. */}
        {puedeDecidir && curso.modulos > 0 && (
          <Button
            variant="secondary"
            onClick={() => generarLigaDemo(false)}
            disabled={Boolean(ocupado)}
            title="Crea una liga pública de demostración (no asigna a nadie ni manda WhatsApp)"
          >
            {ocupado === "demo" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            Generar Liga Directa (Modo Expo)
          </Button>
        )}
        {puedeDecidir && (
          <MenuAcciones
            etiqueta="Más acciones del curso"
            acciones={[
              { etiqueta: "Editar objetivo", icono: <Pencil />, onClick: () => setEditando("objetivo") },
              { etiqueta: "Editar módulos", icono: <Pencil />, onClick: () => setEditando("modulos") },
              { etiqueta: "Editar evaluación", icono: <Pencil />, onClick: () => setEditando("evaluacion") },
              { etiqueta: "Descargar PDF del curso", icono: <Download />, onClick: () => window.open(urlPdfCurso(curso.id), "_blank") },
              { etiqueta: "Duplicar curso…", icono: <Copy />, onClick: duplicar },
              { etiqueta: "Archivar curso", icono: <X />, peligrosa: true, onClick: archivar },
            ]}
          />
        )}
      </PageHeader>

      {aviso && <div className="mt-4"><Aviso tono={aviso.tono} onCerrar={() => setAviso(null)}>{aviso.texto}</Aviso></div>}

      <div className="mt-6 flex flex-col gap-3">
        <Card className="p-5">
          <Eyebrow>Objetivo</Eyebrow>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">{curso.objetivo}</p>
          {curso.adjuntos.length > 0 && <p className="mt-2 text-[11px] text-ink-3">Material de referencia: {curso.adjuntos.join(" · ")}</p>}
        </Card>

        <Plegable titulo="Módulos" resumen={(curso.listaModulos ?? []).map((m) => m.titulo).join(" · ")}>
          <ol className="flex flex-col gap-3">
            {(curso.listaModulos ?? []).map((m) => (
              <li key={m.orden}>
                <Plegable titulo={`${m.orden}. ${m.titulo}`}>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-2">{m.contenido}</p>
                </Plegable>
              </li>
            ))}
          </ol>
        </Plegable>

        <Plegable titulo="Evaluación final" resumen={`${curso.preguntas} preguntas (opción múltiple / V-F) · se califica sola · aprobado desde ${curso.calificacionMinima}%`}>
          <ol className="flex flex-col gap-3">
            {(curso.evaluacion ?? []).map((q, i) => (
              <li key={i} className="rounded-xl border border-border-soft p-3">
                <p className="text-sm font-medium">{i + 1}. {q.pregunta}</p>
                <ul className="mt-1.5 flex flex-col gap-1">
                  {q.opciones.map((o, k) => (
                    <li key={k} className={cn("text-xs", k === q.correcta ? "font-semibold text-good" : "text-ink-2")}>{k === q.correcta ? "✓ " : "· "}{o}</li>
                  ))}
                </ul>
                {q.explicacion && <p className="mt-1 text-[11px] text-ink-3">{q.explicacion}</p>}
              </li>
            ))}
          </ol>
        </Plegable>

        <Plegable titulo="Personas asignadas" resumen={`${asignaciones.length} asignadas · ${completadas.length} completadas · ${completadas.filter((a) => a.aprobado).length} aprobadas`}>
          {asignaciones.length === 0 ? (
            <p className="text-sm text-ink-3">Todavía nadie tiene este curso asignado.</p>
          ) : (
            <ul className="divide-y divide-border-faint">
              {asignaciones.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                  <span className="min-w-0 flex-1">
                    <span className="font-medium">{a.persona}</span>
                    <span className="ml-2 text-[11px] text-ink-3">{ETIQUETA_TIPO[a.tipo]}{a.vacante ? ` · ${a.vacante}` : a.organizacion ? ` · ${a.organizacion}` : ""}</span>
                  </span>
                  <span className="text-xs text-ink-3">{a.moduloActual}/{a.totalModulos}</span>
                  {a.calificacion === null ? (
                    <Badge tone={a.estado === "en_curso" ? "brand" : "neutral"} dot>{a.estado === "en_curso" ? "En curso" : "Pendiente"}</Badge>
                  ) : (
                    <Badge tone={a.aprobado ? "good" : "bad"} dot>{a.aprobado ? "Aprobado" : "No aprobado"} · {a.calificacion}%</Badge>
                  )}
                  <button type="button" title="Copiar liga" onClick={() => navigator.clipboard?.writeText(a.liga)} className="text-ink-3 hover:text-brand"><Link2 className="h-3.5 w-3.5" /></button>
                </li>
              ))}
            </ul>
          )}
        </Plegable>
      </div>

      {ligaDemo && (
        <ModalLigaDemo
          datos={ligaDemo}
          curso={curso}
          onOtra={() => generarLigaDemo(true)}
          regenerando={ocupado === "demo"}
          onClose={() => setLigaDemo(null)}
        />
      )}

      {asignar && (
        <AsignarCurso
          curso={curso}
          onClose={() => setAsignar(false)}
          onAsignado={(msg) => {
            setAsignar(false);
            setAviso({ tono: "ok", texto: msg });
            recargar();
          }}
        />
      )}
      {editando && (
        <EditarCurso
          curso={curso}
          que={editando}
          onClose={() => setEditando(null)}
          onGuardado={(c) => {
            setEditando(null);
            setCurso(c);
            setAviso({ tono: "ok", texto: "Curso actualizado." });
          }}
        />
      )}
    </div>
  );
}

/* ---------------- Asignación universal ---------------- */
function AsignarCurso({ curso, onClose, onAsignado }: { curso: Curso; onClose: () => void; onAsignado: (msg: string) => void }) {
  const [tab, setTab] = useState<"colaborador" | "candidato" | "externo">("colaborador");
  const [colaboradores, setColaboradores] = useState<Colaborador[]>([]);
  const [candidatos, setCandidatos] = useState<Candidato[]>([]);
  const [busqueda, setBusqueda] = useState("");
  const [selCol, setSelCol] = useState<string[]>([]);
  const [selPost, setSelPost] = useState<string[]>([]);
  const [externos, setExternos] = useState<{ nombre: string; correo: string; telefono: string; organizacion: string }[]>([{ nombre: "", correo: "", telefono: "", organizacion: "" }]);
  const [ligaAbierta, setLigaAbierta] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  const [ligas, setLigas] = useState<{ persona: string; liga: string }[]>([]);

  useEffect(() => {
    fetchColaboradores(true).then((c) => setColaboradores(c ?? []));
    fetchCandidatos().then((c) => setCandidatos(c ?? []));
  }, []);

  const q = busqueda.trim().toLowerCase();
  const colFiltrados = useMemo(() => colaboradores.filter((c) => !q || c.nombre.toLowerCase().includes(q) || (c.puesto ?? "").toLowerCase().includes(q)), [colaboradores, q]);
  const postFiltradas = useMemo(() => candidatos.filter((c) => !q || c.nombre.toLowerCase().includes(q) || (c.puesto ?? "").toLowerCase().includes(q)), [candidatos, q]);

  const toggle = (lista: string[], set: (v: string[]) => void, id: string) => set(lista.includes(id) ? lista.filter((x) => x !== id) : [...lista, id]);

  async function confirmar() {
    // hotfix 2026-09-22: la liga abierta manda un externo con los 4 campos vacíos (nunca `{}`), para que el
    // backend lo reciba con su forma completa y no dependa de los defaults del validador.
    const ext = ligaAbierta
      ? [{ nombre: "", correo: "", telefono: "", organizacion: "" }]
      : externos.filter((e) => e.nombre.trim() || e.correo.trim() || e.telefono.trim());
    if (!selCol.length && !selPost.length && !ext.length) return setError("Elige al menos una persona o genera una liga abierta.");
    setOcupado(true);
    setError("");
    const r = await asignarCurso(curso.id, { colaboradorIds: selCol, postulacionIds: selPost, externos: ext });
    setOcupado(false);
    if (!r.ok) return setError(r.error);
    const nuevas = r.data.envios.map((e) => ({ persona: String(e.persona || "Liga abierta (externo)"), liga: String(e.liga) }));
    if (nuevas.some((n) => n.persona.startsWith("Liga abierta"))) {
      setLigas(nuevas);
      return;
    }
    onAsignado(`Curso asignado a ${r.data.asignaciones.length} persona(s).${r.data.noEncontrados.length ? ` No encontrados: ${r.data.noEncontrados.join(", ")}.` : ""}`);
  }

  const tabCls = (t: typeof tab) => cn("rounded-full px-3 py-1.5 text-xs font-semibold transition", tab === t ? "bg-brand text-brand-ink" : "text-ink-2 hover:bg-surface-2");
  const inputCls = "h-10 rounded-xl border border-border-soft bg-surface px-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-0 backdrop-blur-sm sm:p-4" onClick={() => !ocupado && onClose()}>
      <Card className="flex h-[100dvh] w-full max-w-2xl flex-col overflow-y-auto rounded-none p-4 sm:h-auto sm:max-h-[90vh] sm:rounded-2xl sm:p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-lg font-bold">Asignar «{curso.titulo}»</h2>
            <p className="mt-1 text-sm text-ink-2">El mismo curso para colaboradores, candidatos o externos. Se manda la liga por WhatsApp/correo.</p>
          </div>
          <button type="button" onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg text-ink-3 hover:bg-surface-2" aria-label="Cerrar"><X className="h-4 w-4" /></button>
        </div>

        {ligas.length > 0 ? (
          <div className="mt-4 flex flex-col gap-3">
            <Aviso tono="ok">Liga generada. Compártela con la persona externa: al abrirla solo se le pide nombre y correo o WhatsApp.</Aviso>
            {ligas.map((l) => (
              <div key={l.liga} className="flex items-center gap-2 rounded-xl border border-border-soft bg-surface-2 px-3 py-2">
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink-2">{l.liga}</span>
                <button type="button" onClick={() => navigator.clipboard?.writeText(l.liga)} className="text-ink-3 hover:text-brand" title="Copiar"><Copy className="h-4 w-4" /></button>
              </div>
            ))}
            <Button className="self-end" size="sm" onClick={() => onAsignado("Liga externa generada.")}>Listo</Button>
          </div>
        ) : (
          <>
            <div className="mt-4 flex flex-wrap items-center gap-1 rounded-full bg-surface-2/60 p-1">
              <button type="button" className={tabCls("colaborador")} onClick={() => setTab("colaborador")}>Colaboradores{selCol.length ? ` (${selCol.length})` : ""}</button>
              <button type="button" className={tabCls("candidato")} onClick={() => setTab("candidato")}>Candidatos{selPost.length ? ` (${selPost.length})` : ""}</button>
              <button type="button" className={tabCls("externo")} onClick={() => setTab("externo")}>Externos</button>
            </div>

            <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
              {tab !== "externo" && (
                <>
                  <input value={busqueda} onChange={(e) => setBusqueda(e.target.value)} placeholder="Buscar por nombre o puesto…" className={cn(inputCls, "mb-2 w-full")} />
                  <ul className="divide-y divide-border-faint">
                    {(tab === "colaborador" ? colFiltrados : postFiltradas).map((p) => {
                      const id = p.id;
                      const marcado = tab === "colaborador" ? selCol.includes(id) : selPost.includes(id);
                      return (
                        <li key={id}>
                          <label className="flex cursor-pointer items-center gap-3 py-2">
                            <input type="checkbox" checked={marcado} onChange={() => (tab === "colaborador" ? toggle(selCol, setSelCol, id) : toggle(selPost, setSelPost, id))} className="h-4 w-4 rounded border-border-soft text-brand" />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-medium">{p.nombre}</span>
                              <span className="block truncate text-[11px] text-ink-3">{p.puesto}{tab === "candidato" ? ` · ${(p as Candidato).etapa}` : ""}</span>
                            </span>
                          </label>
                        </li>
                      );
                    })}
                    {(tab === "colaborador" ? colFiltrados : postFiltradas).length === 0 && <li className="py-4 text-sm text-ink-3">Sin resultados.</li>}
                  </ul>
                </>
              )}
              {tab === "externo" && (
                <div className="flex flex-col gap-3">
                  <label className="flex items-center gap-2 rounded-xl border border-border-soft p-3 text-sm">
                    <input type="checkbox" checked={ligaAbierta} onChange={(e) => setLigaAbierta(e.target.checked)} className="h-4 w-4 rounded border-border-soft text-brand" />
                    <span>Generar una <b>liga abierta</b>: la persona se registra al abrirla (solo nombre y correo o WhatsApp).</span>
                  </label>
                  {!ligaAbierta && (
                    <>
                      {externos.map((e, i) => (
                        <div key={i} className="grid gap-2 sm:grid-cols-4">
                          <input value={e.nombre} onChange={(ev) => setExternos(externos.map((x, k) => (k === i ? { ...x, nombre: ev.target.value } : x)))} placeholder="Nombre" className={inputCls} />
                          <input value={e.correo} onChange={(ev) => setExternos(externos.map((x, k) => (k === i ? { ...x, correo: ev.target.value } : x)))} placeholder="Correo" className={inputCls} />
                          <input value={e.telefono} onChange={(ev) => setExternos(externos.map((x, k) => (k === i ? { ...x, telefono: ev.target.value } : x)))} placeholder="WhatsApp (10 dígitos)" className={inputCls} />
                          <input value={e.organizacion} onChange={(ev) => setExternos(externos.map((x, k) => (k === i ? { ...x, organizacion: ev.target.value } : x)))} placeholder="Proveedor / cliente" className={inputCls} />
                        </div>
                      ))}
                      <button type="button" onClick={() => setExternos([...externos, { nombre: "", correo: "", telefono: "", organizacion: "" }])} className="self-start text-xs font-semibold text-brand hover:underline">+ Otra persona</button>
                    </>
                  )}
                </div>
              )}
            </div>

            {error && <p className="mt-2 text-sm font-semibold text-bad">{error}</p>}
            <div className="mt-4 flex justify-end gap-2 border-t border-border-faint pt-4">
              <Button variant="outline" size="sm" onClick={onClose} disabled={ocupado}>Cancelar</Button>
              <Button size="sm" onClick={confirmar} disabled={ocupado}>
                {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} {ocupado ? "Asignando…" : ligaAbierta && tab === "externo" ? "Generar liga" : "Asignar y enviar liga"}
              </Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

/* ---------------- Edición (solo si RH quiere) ---------------- */
function EditarCurso({ curso, que, onClose, onGuardado }: { curso: Curso; que: "objetivo" | "modulos" | "evaluacion"; onClose: () => void; onGuardado: (c: Curso) => void }) {
  const [objetivo, setObjetivo] = useState(curso.objetivo);
  const [minimo, setMinimo] = useState(String(curso.calificacionMinima));
  const [modulos, setModulos] = useState(() => (curso.listaModulos ?? []).map((m) => ({ titulo: m.titulo, contenido: m.contenido })));
  const [preguntas, setPreguntas] = useState<PreguntaEvaluacion[]>(() => (curso.evaluacion ?? []).map((q) => ({ ...q, opciones: [...q.opciones] })));
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const inputCls = "w-full rounded-xl border border-border-soft bg-surface px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20";

  async function guardar() {
    setGuardando(true);
    setError("");
    const r = await editarCurso(
      curso.id,
      que === "objetivo"
        ? { objetivo, calificacionMinima: parseInt(minimo, 10) || curso.calificacionMinima }
        : que === "modulos"
          ? { modulos }
          : { evaluacion: preguntas },
    );
    setGuardando(false);
    if (!r.ok) return setError(r.error);
    onGuardado(r.data);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-0 backdrop-blur-sm sm:p-4" onClick={() => !guardando && onClose()}>
      <Card className="flex h-[100dvh] w-full max-w-2xl flex-col overflow-y-auto rounded-none p-4 sm:h-auto sm:max-h-[90vh] sm:rounded-2xl sm:p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <h2 className="font-display text-lg font-bold">{que === "objetivo" ? "Objetivo y mínimo aprobatorio" : que === "modulos" ? "Módulos" : "Evaluación final"}</h2>
          <button type="button" onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg text-ink-3 hover:bg-surface-2" aria-label="Cerrar"><X className="h-4 w-4" /></button>
        </div>
        <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
          {que === "objetivo" && (
            <div className="flex flex-col gap-3">
              <textarea value={objetivo} onChange={(e) => setObjetivo(e.target.value)} rows={4} className={inputCls} />
              <label className="flex items-center gap-2 text-sm text-ink-2">
                Aprobado desde
                <input type="number" min={1} max={100} value={minimo} onChange={(e) => setMinimo(e.target.value)} className="h-9 w-20 rounded-xl border border-border-soft bg-surface px-2 text-sm outline-none focus:border-brand" /> %
              </label>
            </div>
          )}
          {que === "modulos" && (
            <div className="flex flex-col gap-4">
              {modulos.map((m, i) => (
                <div key={i} className="flex flex-col gap-2 rounded-xl border border-border-soft p-3">
                  <div className="flex items-center gap-2">
                    <input value={m.titulo} onChange={(e) => setModulos(modulos.map((x, k) => (k === i ? { ...x, titulo: e.target.value } : x)))} className={inputCls} placeholder={`Módulo ${i + 1}`} />
                    <button type="button" onClick={() => setModulos(modulos.filter((_, k) => k !== i))} className="text-ink-3 hover:text-bad" aria-label="Quitar módulo"><X className="h-4 w-4" /></button>
                  </div>
                  <textarea value={m.contenido} onChange={(e) => setModulos(modulos.map((x, k) => (k === i ? { ...x, contenido: e.target.value } : x)))} rows={5} className={inputCls} />
                </div>
              ))}
              <button type="button" onClick={() => setModulos([...modulos, { titulo: "", contenido: "" }])} className="self-start text-xs font-semibold text-brand hover:underline">+ Agregar módulo</button>
            </div>
          )}
          {que === "evaluacion" && (
            <div className="flex flex-col gap-4">
              {preguntas.map((q, i) => (
                <div key={i} className="flex flex-col gap-2 rounded-xl border border-border-soft p-3">
                  <div className="flex items-center gap-2">
                    <input value={q.pregunta} onChange={(e) => setPreguntas(preguntas.map((x, k) => (k === i ? { ...x, pregunta: e.target.value } : x)))} className={inputCls} placeholder={`Pregunta ${i + 1}`} />
                    <select
                      value={q.tipo}
                      onChange={(e) => {
                        const tipo = e.target.value as "opcion" | "vf";
                        setPreguntas(preguntas.map((x, k) => (k === i ? { ...x, tipo, opciones: tipo === "vf" ? ["Verdadero", "Falso"] : x.opciones.length >= 3 ? x.opciones : ["", "", ""], correcta: 0 } : x)));
                      }}
                      className="h-10 rounded-xl border border-border-soft bg-surface px-2 text-sm outline-none"
                    >
                      <option value="opcion">Opción múltiple</option>
                      <option value="vf">Verdadero / Falso</option>
                    </select>
                    <button type="button" onClick={() => setPreguntas(preguntas.filter((_, k) => k !== i))} className="text-ink-3 hover:text-bad" aria-label="Quitar pregunta"><X className="h-4 w-4" /></button>
                  </div>
                  {q.opciones.map((o, k) => (
                    <label key={k} className="flex items-center gap-2">
                      <input type="radio" name={`correcta-${i}`} checked={q.correcta === k} onChange={() => setPreguntas(preguntas.map((x, j) => (j === i ? { ...x, correcta: k } : x)))} title="Respuesta correcta" />
                      <input value={o} disabled={q.tipo === "vf"} onChange={(e) => setPreguntas(preguntas.map((x, j) => (j === i ? { ...x, opciones: x.opciones.map((y, m) => (m === k ? e.target.value : y)) } : x)))} className={inputCls} placeholder={`Opción ${k + 1}`} />
                    </label>
                  ))}
                  {q.tipo === "opcion" && q.opciones.length < 4 && (
                    <button type="button" onClick={() => setPreguntas(preguntas.map((x, j) => (j === i ? { ...x, opciones: [...x.opciones, ""] } : x)))} className="self-start text-xs text-brand hover:underline">+ Opción</button>
                  )}
                  <input value={q.explicacion} onChange={(e) => setPreguntas(preguntas.map((x, k) => (k === i ? { ...x, explicacion: e.target.value } : x)))} className={inputCls} placeholder="Explicación (opcional)" />
                </div>
              ))}
              <button type="button" onClick={() => setPreguntas([...preguntas, { pregunta: "", tipo: "opcion", opciones: ["", "", ""], correcta: 0, explicacion: "" }])} className="self-start text-xs font-semibold text-brand hover:underline">+ Agregar pregunta</button>
            </div>
          )}
        </div>
        {error && <p className="mt-2 text-sm font-semibold text-bad">{error}</p>}
        <div className="mt-4 flex justify-end gap-2 border-t border-border-faint pt-4">
          <Button variant="outline" size="sm" onClick={onClose} disabled={guardando}>Cancelar</Button>
          <Button size="sm" onClick={guardar} disabled={guardando}>{guardando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Guardar</Button>
        </div>
      </Card>
    </div>
  );
}


/* ============================================================
   Liga directa de demostración (Expo 2026-09-23)
   ============================================================ */

function ModalLigaDemo({ datos, curso, onOtra, regenerando, onClose }: {
  datos: { liga: string; ligaTotem: string; reutilizada: boolean };
  curso: Curso;
  onOtra: () => void;
  regenerando: boolean;
  onClose: () => void;
}) {
  const [copiada, setCopiada] = useState<"" | "totem" | "normal">("");

  async function copiar(url: string, cual: "totem" | "normal") {
    try {
      await navigator.clipboard.writeText(url);
      setCopiada(cual);
      setTimeout(() => setCopiada(""), 2500);
    } catch {
      window.prompt("Copia la liga:", url);
    }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-0 backdrop-blur-sm sm:p-4" onClick={onClose}>
      <Card className="flex h-[100dvh] w-full max-w-xl flex-col overflow-y-auto rounded-none p-5 sm:h-auto sm:rounded-2xl sm:p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-lg font-bold">Liga directa · Modo Expo</h2>
            <p className="mt-1 text-sm text-ink-2">
              «{curso.titulo}» listo para demostrarse. No se asignó a ninguna persona y no salió ningún WhatsApp ni correo.
            </p>
          </div>
          <button onClick={onClose} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-ink-3 transition hover:bg-surface-2" aria-label="Cerrar">
            <X className="h-4 w-4" />
          </button>
        </div>

        {datos.reutilizada && (
          <p className="mt-3 rounded-xl bg-surface-2 px-3.5 py-2.5 text-[12px] text-ink-2">
            Se reutilizó la liga de demostración que ya existía para este curso (conserva el avance). Si quieres una
            limpia, usa «Generar otra liga».
          </p>
        )}

        {/* La liga del tótem es la principal: abre la interfaz vertical a pantalla completa */}
        <div className="mt-4 rounded-2xl border border-brand/30 bg-brand-soft/30 p-4">
          <Eyebrow>Para el tótem (1080×1920)</Eyebrow>
          <p className="mt-2 break-all rounded-xl bg-surface px-3 py-2.5 font-mono text-[12px] text-ink">{datos.ligaTotem}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => copiar(datos.ligaTotem, "totem")}>
              {copiada === "totem" ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} {copiada === "totem" ? "Copiada" : "Copiar Liga"}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => window.open(datos.ligaTotem, "_blank", "noopener")}>
              <ExternalLink className="h-4 w-4" /> Abrir en Tótem
            </Button>
          </div>
          <p className="mt-2 text-[11px] text-ink-3">
            El parámetro <code className="font-mono">?totem=1</code> fuerza la pantalla completa vertical: video a tamaño
            real sin barras negras y botones táctiles grandes.
          </p>
        </div>

        <div className="mt-3 rounded-2xl border border-border-soft p-4">
          <Eyebrow>Para cualquier pantalla (celular o laptop)</Eyebrow>
          <p className="mt-2 break-all rounded-xl bg-surface-2 px-3 py-2.5 font-mono text-[12px] text-ink-2">{datos.liga}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => copiar(datos.liga, "normal")}>
              {copiada === "normal" ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} {copiada === "normal" ? "Copiada" : "Copiar liga normal"}
            </Button>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
          <Button size="sm" variant="ghost" onClick={onOtra} disabled={regenerando}>
            {regenerando ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Generar otra liga
          </Button>
          <Button size="sm" onClick={onClose}>Listo</Button>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-ink-3">
          La demostración aparece en el tablero de Capacitación como «{curso.titulo}» para <b>Demo Expo</b>, así se
          distingue del avance real de los colaboradores.
        </p>
      </Card>
    </div>
  );
}
