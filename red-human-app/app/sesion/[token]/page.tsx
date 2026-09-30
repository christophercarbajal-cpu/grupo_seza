"use client";

/* Liga del SUPERVISOR para una sesión de «Capacitación en tienda» (demo Grupo SEZA, 2026-09-29).

   Sin sesión (el token es la credencial). El supervisor escribe su nombre una vez y, por cada citado, marca
   si asistió y el resultado: Apto / Requiere seguimiento / No apto (este último y «Requiere seguimiento» piden
   comentario). Solo ve nombre y vacante de cada persona — nada de teléfonos ni documentos. Lo registrado ya no
   se puede cambiar desde aquí (RH lo ve con su nombre en la ficha del candidato). */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, Loader2, UserX } from "lucide-react";
import { Logo, Card, Badge } from "@/components/ui";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";
import { fetchSesionSupervisor, registrarAsistenciaSupervisor, type CitadoSesion, type SesionSupervisor } from "@/lib/api";

const TONO: Record<string, "good" | "warn" | "bad"> = { favorable: "good", con_observaciones: "warn", desfavorable: "bad" };

export default function SesionSupervisorPagina() {
  const params = useParams();
  const token = String(params?.token ?? "");
  const [info, setInfo] = useState<SesionSupervisor | null>(null);
  const [fase, setFase] = useState<"cargando" | "no_disponible" | "lista">("cargando");
  const [supervisor, setSupervisor] = useState("");
  const [error, setError] = useState("");

  const cargar = useCallback(() => {
    fetchSesionSupervisor(token).then((i) => {
      if (!i) return setFase("no_disponible");
      setInfo(i);
      setSupervisor((s) => s || i.supervisor);
      setFase("lista");
    });
  }, [token]);
  useEffect(() => {
    cargar();
  }, [cargar]);

  async function registrar(c: CitadoSesion, asistio: boolean, resultado: string, comentario: string) {
    setError("");
    const r = await registrarAsistenciaSupervisor(token, { evaluacion: c.evaluacion, asistio, resultado, comentario, supervisor });
    if (!r.ok) return setError(r.error);
    setInfo(r.data);
  }

  const pendientes = info?.citados.filter((c) => !c.asistencia).length ?? 0;

  return (
    <main className="sala-publica min-h-svh bg-bg">
      <header className="border-b border-border-soft">
        <div className="mx-auto flex max-w-2xl items-center justify-between px-5 py-4">
          <Logo />
          <ThemeToggle />
        </div>
      </header>
      <div className="mx-auto max-w-2xl px-4 py-8 sm:px-5">
        {fase === "cargando" && (
          <div className="grid place-items-center py-24 text-ink-3">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        )}
        {fase === "no_disponible" && (
          <Card className="p-8 text-center">
            <h1 className="font-display text-xl font-bold">Liga no disponible</h1>
            <p className="mt-2 text-sm text-ink-2">Esta liga no es válida o la sesión fue cancelada.</p>
          </Card>
        )}
        {fase === "lista" && info && (
          <>
            <div className="text-center">
              <Badge tone="brand" dot>{info.nombre}</Badge>
              <h1 className="font-display mt-3 text-2xl font-bold">{info.tienda}</h1>
              <p className="mt-1 text-sm text-ink-2">
                {info.inicioTexto} h{info.empresa ? ` · ${info.empresa}` : ""}
              </p>
              <p className="mt-1 text-[13px] text-ink-3">
                {info.citados.length} citado(s) · {pendientes ? `${pendientes} por registrar` : "todo registrado"}
              </p>
            </div>

            <Card className="mt-6 p-4">
              <label className="block">
                <span className="text-sm font-medium text-ink-2">Tu nombre (queda registrado en cada resultado)</span>
                <input
                  value={supervisor}
                  onChange={(e) => setSupervisor(e.target.value)}
                  className="mt-1.5 h-12 w-full rounded-xl border border-border-soft bg-surface px-4 text-sm outline-none focus:border-brand"
                />
              </label>
            </Card>

            {error && <div className="mt-4 rounded-xl border border-bad/25 bg-bad-soft px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

            <div className="mt-4 flex flex-col gap-3">
              {info.citados.length === 0 && <Card className="p-6 text-center text-sm text-ink-3">Todavía no hay personas citadas a esta sesión.</Card>}
              {info.citados.map((c) => (
                <Citado key={c.evaluacion} c={c} resultados={info.resultados} deshabilitado={!supervisor.trim()} onRegistrar={registrar} />
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  );
}

function Citado({
  c,
  resultados,
  deshabilitado,
  onRegistrar,
}: {
  c: CitadoSesion;
  resultados: SesionSupervisor["resultados"];
  deshabilitado: boolean;
  onRegistrar: (c: CitadoSesion, asistio: boolean, resultado: string, comentario: string) => Promise<void>;
}) {
  const [resultado, setResultado] = useState("");
  const [comentario, setComentario] = useState("");
  const [enviando, setEnviando] = useState(false);
  const pideComentario = resultado === "con_observaciones" || resultado === "desfavorable";

  async function enviar(asistio: boolean) {
    setEnviando(true);
    await onRegistrar(c, asistio, resultado, comentario.trim());
    setEnviando(false);
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-ink">{c.nombre}</p>
          <p className="text-[12px] text-ink-3">
            {c.vacante} · {c.confirmada ? "confirmó asistencia" : "sin confirmar"}
          </p>
        </div>
        {c.asistencia === "asistio" && (
          <Badge tone={TONO[c.resultado] ?? "neutral"} dot>
            <CheckCircle2 className="h-3 w-3" /> {c.resultadoEtiqueta}
          </Badge>
        )}
        {c.asistencia === "no_asistio" && (
          <Badge tone="bad" dot>
            <UserX className="h-3 w-3" /> No asistió
          </Badge>
        )}
      </div>
      {c.asistencia && c.comentario && <p className="mt-2 text-[13px] text-ink-2">{c.comentario}</p>}

      {!c.asistencia && (
        <div className="mt-3 flex flex-col gap-3">
          <div className="grid grid-cols-3 gap-2">
            {resultados.map((r) => (
              <button
                key={r.valor}
                type="button"
                onClick={() => setResultado(r.valor)}
                className={cn(
                  "min-h-12 rounded-xl border px-2 text-sm font-medium transition totem:min-h-16 totem:text-xl",
                  resultado === r.valor
                    ? r.valor === "favorable"
                      ? "border-good bg-good-soft text-good"
                      : r.valor === "con_observaciones"
                        ? "border-warn bg-warn-soft text-warn"
                        : "border-bad bg-bad-soft text-bad"
                    : "border-border-soft bg-surface hover:border-brand",
                )}
              >
                {r.texto}
              </button>
            ))}
          </div>
          {resultado && (
            <textarea
              value={comentario}
              onChange={(e) => setComentario(e.target.value)}
              rows={2}
              placeholder={pideComentario ? "Comentario (obligatorio): ¿qué hay que reforzar o por qué no es apto?" : "Comentario (opcional)"}
              className="w-full rounded-xl border border-border-soft bg-surface px-3.5 py-2.5 text-sm outline-none focus:border-brand"
            />
          )}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={deshabilitado || enviando}
              onClick={() => enviar(false)}
              className="min-h-11 flex-1 rounded-xl border border-border-soft px-3 text-sm font-medium text-ink-2 transition hover:border-bad disabled:opacity-50"
            >
              No asistió
            </button>
            <button
              type="button"
              disabled={deshabilitado || enviando || !resultado || (pideComentario && !comentario.trim())}
              onClick={() => enviar(true)}
              className="min-h-11 flex-[2] rounded-xl bg-brand px-3 text-sm font-semibold text-brand-ink transition hover:brightness-110 disabled:opacity-50"
            >
              {enviando ? "Guardando…" : "Asistió · guardar resultado"}
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
