"use client";

/* Sala pública del curso (módulo universal, 2026-09-16). Una sola pantalla:
   1) externos con liga abierta: registro (solo nombre y correo o WhatsApp);
   2) módulos uno por uno con «Siguiente módulo»;
   3) evaluación integrada, UNA pregunta por pantalla, calificada al instante;
   4) resultado: Aprobado / No aprobado + %. */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowRight, Award, BookOpen, CheckCircle2, Download, Loader2, XCircle } from "lucide-react";
import { Badge, Button, Card, Logo } from "@/components/ui";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";
import { avanzarModulo, fetchAsignacionPublica, registrarExternoCurso, responderEvaluacion, urlPdfCursoPublico, type AsignacionPublica } from "@/lib/api";
import { InstructorAvatar } from "@/components/capacitacion/instructor-avatar";
import { useTotem } from "@/lib/use-totem";

type Vista = "cargando" | "no_disponible" | "registro" | "portada" | "modulo" | "evaluacion" | "resultado";

export default function SalaCurso() {
  const params = useParams();
  const token = String(params?.token ?? "");
  // 2026-09-21: Modo Tótem (LCD 55" vertical): columna única, avatar a tamaño real, botones táctiles y letra grande.
  const totem = useTotem();
  const btnTotem = "totem:min-h-16 totem:rounded-2xl totem:text-xl";
  const [a, setA] = useState<AsignacionPublica | null>(null);
  const [vista, setVista] = useState<Vista>("cargando");
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  // registro externo
  const [nombre, setNombre] = useState("");
  const [correo, setCorreo] = useState("");
  const [telefono, setTelefono] = useState("");
  // evaluación
  const [eleccion, setEleccion] = useState<number | null>(null);
  const [retro, setRetro] = useState<{ correcta: boolean; explicacion: string } | null>(null);

  const colocar = useCallback((d: AsignacionPublica) => {
    setA(d);
    if (d.requiereRegistro) return setVista("registro");
    if (d.estado === "completado" && d.resultado) return setVista("resultado");
    if (d.modulosCompletados >= d.totalModulos) return setVista(d.pregunta ? "evaluacion" : "resultado");
    setVista(d.modulosCompletados === 0 && d.estado === "pendiente" ? "portada" : "modulo");
  }, []);

  useEffect(() => {
    fetchAsignacionPublica(token).then((d) => (d ? colocar(d) : setVista("no_disponible")));
  }, [token, colocar]);

  async function registrar() {
    setOcupado(true);
    setError("");
    const r = await registrarExternoCurso(token, { nombre, correo, telefono });
    setOcupado(false);
    if (!r.ok) return setError(r.error);
    colocar(r.data);
  }

  async function siguienteModulo() {
    if (!a) return;
    setOcupado(true);
    setError("");
    const r = await avanzarModulo(token, a.modulosCompletados + 1);
    setOcupado(false);
    if (!r.ok) return setError(r.error);
    setA(r.data);
    setVista(r.data.modulosCompletados >= r.data.totalModulos ? "evaluacion" : "modulo");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function responder() {
    if (!a?.pregunta || eleccion === null) return;
    setOcupado(true);
    setError("");
    const r = await responderEvaluacion(token, a.pregunta.indice, eleccion);
    setOcupado(false);
    if (!r.ok) return setError(r.error);
    setRetro({ correcta: Boolean(r.data.correcta), explicacion: r.data.explicacion });
    setA(r.data);
  }

  function continuar() {
    setRetro(null);
    setEleccion(null);
    if (a?.estado === "completado") setVista("resultado");
  }

  const modulo = a && vista === "modulo" ? a.modulos[a.modulosCompletados] : null;

  return (
    <main className={cn("sala-publica min-h-svh bg-bg", totem && "totem")}>
      <header className="border-b border-border-soft">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-5 py-4 totem:max-w-none totem:px-10 totem:py-6">
          <Logo size={totem ? "lg" : "md"} />
          <ThemeToggle />
        </div>
      </header>

      <div className={cn("mx-auto px-5 py-8 sm:py-10 totem:max-w-none totem:px-10", vista === "modulo" ? "max-w-5xl" : "max-w-3xl")}>
        {vista === "cargando" && <div className="grid place-items-center py-24 text-ink-3"><Loader2 className="h-6 w-6 animate-spin" /></div>}

        {vista === "no_disponible" && (
          <Card className="p-8 text-center">
            <h1 className="font-display text-xl font-bold">Liga no disponible</h1>
            <p className="mt-2 text-sm text-ink-2">Este curso no existe o ya no está activo. Pide una liga nueva a quien te lo asignó.</p>
          </Card>
        )}

        {a && vista !== "cargando" && vista !== "no_disponible" && (
          <div className="mb-6 text-center">
            <Badge tone="brand" dot>{a.empresa} · Capacitación</Badge>
            <h1 className="font-display mt-3 text-2xl font-bold sm:text-3xl totem:text-4xl">{a.curso}</h1>
            {a.totalModulos > 0 && vista !== "registro" && (
              <div className="mx-auto mt-4 flex max-w-md items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                  <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${Math.round(((a.modulosCompletados + (vista === "resultado" ? 1 : 0)) / (a.totalModulos + 1)) * 100)}%` }} />
                </div>
                <span className="font-mono text-[11px] text-ink-3">
                  {vista === "evaluacion" ? `Evaluación ${a.preguntasRespondidas + 1}/${a.totalPreguntas}` : vista === "resultado" ? "Terminado" : `Módulo ${Math.min(a.modulosCompletados + 1, a.totalModulos)}/${a.totalModulos}`}
                </span>
              </div>
            )}
          </div>
        )}

        {a && vista === "registro" && (
          <Card className="p-6">
            <h2 className="font-display text-lg font-bold">Antes de empezar</h2>
            <p className="mt-1 text-sm text-ink-2">Solo necesitamos tu nombre y un correo o celular para enviarte tu resultado.</p>
            <div className="mt-4 flex flex-col gap-3">
              <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Nombre completo" className="h-11 rounded-xl border border-border-soft bg-surface px-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 totem:min-h-16 totem:text-xl" />
              <div className="grid gap-3 sm:grid-cols-2">
                <input value={correo} onChange={(e) => setCorreo(e.target.value)} placeholder="Correo" type="email" className="h-11 rounded-xl border border-border-soft bg-surface px-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 totem:min-h-16 totem:text-xl" />
                <input value={telefono} onChange={(e) => setTelefono(e.target.value)} placeholder="Celular (10 dígitos)" className="h-11 rounded-xl border border-border-soft bg-surface px-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 totem:min-h-16 totem:text-xl" />
              </div>
              {error && <p className="text-sm font-semibold text-bad">{error}</p>}
              <Button className={cn("w-full", btnTotem)} onClick={registrar} disabled={ocupado || !nombre.trim() || !(correo.trim() || telefono.trim())}>
                {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />} Empezar el curso
              </Button>
            </div>
          </Card>
        )}

        {a && vista === "portada" && (
          <Card className="p-6">
            <p className="text-sm text-ink-2">Hola{a.persona ? ` ${a.persona.split(" ")[0]}` : ""} 👋</p>
            <h2 className="font-display mt-1 text-lg font-bold">Objetivo del curso</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-2">{a.objetivo}</p>
            <ul className="mt-4 flex flex-col gap-1.5 text-sm text-ink-2">
              {a.modulos.map((m) => (
                <li key={m.orden} className="flex items-center gap-2"><BookOpen className="h-4 w-4 text-ink-3" /> {m.orden}. {m.titulo}</li>
              ))}
              <li className="flex items-center gap-2"><Award className="h-4 w-4 text-ink-3" /> Evaluación final ({a.totalPreguntas} preguntas)</li>
            </ul>
            <p className="mt-3 text-xs text-ink-3">
              {a.modalidad === "instructor_ia" ? "Tu instructor con avatar te explica cada módulo y responde tus dudas; al final contestas una evaluación breve." : "Lee cada módulo a tu ritmo; al final contestas una evaluación breve."} Duración aproximada: {a.duracion || `${a.duracionHoras} h`}. Puedes cerrar y volver: tu avance se guarda.
            </p>
            <Button className={cn("mt-5 w-full", btnTotem)} onClick={() => setVista("modulo")}>
              <ArrowRight className="h-4 w-4 totem:h-6 totem:w-6" /> Comenzar
            </Button>
          </Card>
        )}

        {a && vista === "modulo" && modulo && a.modalidad === "instructor_ia" && (
          /* 2026-09-19 (Bloque 4): Instructor IA — el avatar explica primero; el guion queda plegado como apoyo.
             Flujo: Instructor explica → la persona pregunta → Continuar → siguiente módulo → evaluación. */
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="font-mono text-[11px] uppercase tracking-wide text-ink-3">Módulo {modulo.orden} de {a.totalModulos}</p>
                <h2 className="font-display mt-0.5 text-xl font-bold">{modulo.titulo}</h2>
              </div>
              <a href={urlPdfCursoPublico(token)} target="_blank" rel="noreferrer" title="Material de apoyo (PDF)" className="btn-touch inline-flex h-9 shrink-0 items-center gap-1.5 rounded-xl border border-border-soft bg-surface px-3 text-xs font-semibold text-ink-2 transition hover:border-brand/40 hover:text-brand active:scale-95 totem:min-h-16 totem:px-6 totem:text-lg">
                <Download className="h-4 w-4 totem:h-6 totem:w-6" /> Material de apoyo
              </a>
            </div>
            <InstructorAvatar token={token} modulo={modulo.orden} titulo={modulo.titulo} autoIniciar totem={totem} />
            <details className="rounded-2xl border border-border-soft bg-surface">
              <summary className="cursor-pointer px-5 py-3 text-sm font-semibold text-ink-2 totem:text-lg">Ver el guion del módulo (texto)</summary>
              <div className="whitespace-pre-wrap border-t border-border-faint px-5 py-4 text-sm leading-relaxed text-ink-2 totem:text-lg">{modulo.contenido}</div>
            </details>
            {error && <p className="text-sm font-semibold text-bad">{error}</p>}
            <Button className={cn("w-full", btnTotem)} onClick={siguienteModulo} disabled={ocupado}>
              {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4 totem:h-6 totem:w-6" />}
              {a.modulosCompletados + 1 >= a.totalModulos ? "Continuar a la evaluación" : "Continuar al siguiente módulo"}
            </Button>
          </div>
        )}

        {a && vista === "modulo" && modulo && a.modalidad !== "instructor_ia" && (
          /* Autoguiado: contenido breve y visual; el instructor queda disponible por texto al lado.
             Dos columnas SOLO en escritorio apaisado; en retrato (tótem 1080×1920 incluido) siempre columna única. */
          <div className="grid gap-5 lg:landscape:grid-cols-[1fr_340px]">
            <Card className="p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-mono text-[11px] uppercase tracking-wide text-ink-3">Módulo {modulo.orden} de {a.totalModulos}</p>
                  <h2 className="font-display mt-1 text-xl font-bold">{modulo.titulo}</h2>
                </div>
                <a href={urlPdfCursoPublico(token)} target="_blank" rel="noreferrer" title="Material de apoyo (PDF)" className="btn-touch inline-flex h-9 shrink-0 items-center gap-1.5 rounded-xl border border-border-soft bg-surface px-3 text-xs font-semibold text-ink-2 transition hover:border-brand/40 hover:text-brand active:scale-95 totem:min-h-16 totem:px-6 totem:text-lg">
                  <Download className="h-4 w-4 totem:h-6 totem:w-6" /> PDF
                </a>
              </div>
              <div className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-ink-2 totem:text-xl">{modulo.contenido}</div>
              {error && <p className="mt-3 text-sm font-semibold text-bad">{error}</p>}
              <Button className={cn("mt-6 w-full", btnTotem)} onClick={siguienteModulo} disabled={ocupado}>
                {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4 totem:h-6 totem:w-6" />}
                {a.modulosCompletados + 1 >= a.totalModulos ? "Terminar módulos e ir a la evaluación" : "Siguiente módulo"}
              </Button>
            </Card>
            <div className="lg:landscape:sticky lg:landscape:top-6 lg:landscape:self-start">
              <InstructorAvatar token={token} modulo={modulo.orden} titulo={modulo.titulo} totem={totem} />
            </div>
          </div>
        )}

        {a && vista === "evaluacion" && a.pregunta && (
          <Card className="p-6">
            <p className="font-mono text-[11px] uppercase tracking-wide text-ink-3">Evaluación · pregunta {a.pregunta.indice + 1} de {a.totalPreguntas}</p>
            <h2 className="font-display mt-1 text-lg font-bold totem:text-2xl">{a.pregunta.pregunta}</h2>
            <div className="mt-4 flex flex-col gap-2 totem:gap-3">
              {a.pregunta.opciones.map((o, k) => (
                <button
                  key={k}
                  type="button"
                  disabled={retro !== null}
                  onClick={() => setEleccion(k)}
                  className={cn(
                    "rounded-xl border px-4 py-3 text-left text-sm transition active:scale-[0.99] totem:min-h-16 totem:rounded-2xl totem:px-6 totem:text-xl",
                    eleccion === k ? "border-brand bg-brand-soft text-ink ring-2 ring-brand/30" : "border-border-soft bg-surface hover:border-brand/40",
                    retro !== null && eleccion === k && (retro.correcta ? "border-good bg-good-soft" : "border-bad bg-bad-soft"),
                  )}
                >
                  {o}
                </button>
              ))}
            </div>
            {retro && (
              <div className={cn("mt-4 flex items-start gap-2 rounded-xl p-3 text-sm totem:text-lg", retro.correcta ? "bg-good-soft text-good" : "bg-bad-soft text-bad")}>
                {retro.correcta ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
                <span>{retro.correcta ? "¡Correcto!" : "Incorrecto."} {retro.explicacion && <span className="text-ink-2">{retro.explicacion}</span>}</span>
              </div>
            )}
            {error && <p className="mt-3 text-sm font-semibold text-bad">{error}</p>}
            {retro === null ? (
              <Button className={cn("mt-5 w-full", btnTotem)} onClick={responder} disabled={ocupado || eleccion === null}>
                {ocupado ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4 totem:h-6 totem:w-6" />} Responder
              </Button>
            ) : (
              <Button className={cn("mt-5 w-full", btnTotem)} onClick={continuar}>
                <ArrowRight className="h-4 w-4 totem:h-6 totem:w-6" /> {a.estado === "completado" ? "Ver mi resultado" : "Siguiente pregunta"}
              </Button>
            )}
          </Card>
        )}

        {a && vista === "evaluacion" && !a.pregunta && a.estado !== "completado" && (
          <Card className="p-6 text-center text-sm text-ink-2">Cargando la evaluación…</Card>
        )}

        {a && vista === "resultado" && a.resultado && (
          <Card className="p-8 text-center">
            <span className={cn("mx-auto grid h-16 w-16 place-items-center rounded-full", a.resultado.aprobado ? "bg-good-soft text-good" : "bg-bad-soft text-bad")}>
              {a.resultado.aprobado ? <Award className="h-8 w-8" /> : <XCircle className="h-8 w-8" />}
            </span>
            <h2 className="font-display mt-4 text-2xl font-bold">{a.resultado.aprobado ? "¡Aprobado!" : "No aprobado"}</h2>
            <p className="mt-1 text-sm text-ink-2">
              {a.resultado.calificacion}% · {a.resultado.aciertos} de {a.resultado.total} correctas · mínimo {a.resultado.minimo}%
            </p>
            <ul className="mx-auto mt-5 max-w-md divide-y divide-border-faint text-left">
              {a.resultado.detalle.map((d, i) => (
                <li key={i} className="flex items-start gap-2 py-2 text-xs">
                  {d.correcta ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-good" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-bad" />}
                  <span className="text-ink-2">{d.pregunta}{!d.correcta && d.explicacion ? <span className="block text-ink-3">{d.explicacion}</span> : null}</span>
                </li>
              ))}
            </ul>
            <p className="mt-5 text-xs text-ink-3">Tu resultado quedó registrado{a.persona ? ` a nombre de ${a.persona}` : ""}. Ya puedes cerrar esta ventana.</p>
            <Button href={urlPdfCursoPublico(token)} variant="outline" size="sm" className={cn("mt-4", btnTotem, "totem:px-8")}>
              <Download className="h-4 w-4 totem:h-6 totem:w-6" /> Descargar el material y mi resultado (PDF)
            </Button>
          </Card>
        )}
      </div>
    </main>
  );
}
