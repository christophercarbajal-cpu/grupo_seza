"use client";

/* Liga pública del EVALUADOR (2026-09-30): médico, socioeconómico, proveedor de psicométricas… Registra el resultado
   (resumen y/o informe) de la MISMA evaluación que RH puede capturar a mano desde la ficha. Sin sesión: el token es la
   credencial. Médico: solo funciona cuando el candidato ya aceptó el consentimiento expreso. La revisión y el
   dictamen siguen siendo de RH.
   2026-10-01: cada liga muestra el candidato, el nombre y el tipo EXACTOS de su evaluación (código EVA-####);
   «Entrevista humana» pide Apto / No apto + observaciones; un adjunto vacío no tumba la captura (solo se avisa); la
   «Capacitación en tienda» de la versión anterior se muestra como histórica.
   Zeze (2026-10-01): la liga abre desde que se guarda la evaluación y muestra «Consentimiento: Pendiente / Aceptado»
   (pendiente = captura bloqueada); el evaluador dictamina según el tipo (médico / socioeconómico / entrevista humana) y
   puede «Corregir resultado» desde aquí mismo (queda historial y RH vuelve a revisar). */

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, ClipboardCheck, FileUp, History, Loader2, Lock } from "lucide-react";
import { Badge, Button, Card, Logo } from "@/components/ui";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";
import { fetchEvaluacionEvaluador, registrarResultadoEvaluador, type EvaluacionEvaluadorPublica } from "@/lib/api";

export default function LigaEvaluador() {
  const params = useParams();
  const token = String(params?.token ?? "");
  const [info, setInfo] = useState<EvaluacionEvaluadorPublica | null>(null);
  const [fase, setFase] = useState<"cargando" | "no_disponible" | "lista">("cargando");
  const [resumen, setResumen] = useState("");
  const [nombre, setNombre] = useState("");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [apto, setApto] = useState("");
  const [corrigiendo, setCorrigiendo] = useState(false);
  const [motivo, setMotivo] = useState("");
  const [avisoArchivo, setAvisoArchivo] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchEvaluacionEvaluador(token).then((i) => {
      if (!i) return setFase("no_disponible");
      setInfo(i);
      setNombre(i.evaluador);
      setFase("lista");
    });
  }, [token]);

  async function enviar() {
    setEnviando(true);
    setError("");
    const r = await registrarResultadoEvaluador(token, { resumen, evaluador: nombre, archivo, apto, corregir: corrigiendo, motivo });
    setEnviando(false);
    if (!r.ok) return setError(r.error);
    setAvisoArchivo(r.data.avisoArchivo ?? "");
    setCorrigiendo(false);
    setArchivo(null);
    setMotivo("");
    setInfo(r.data);
  }

  return (
    <main className="sala-publica min-h-svh bg-bg">
      <header className="border-b border-border-soft">
        <div className="mx-auto flex max-w-2xl items-center justify-between px-5 py-4">
          <Logo />
          <ThemeToggle />
        </div>
      </header>
      <div className="mx-auto max-w-2xl px-4 py-8 sm:px-5 sm:py-10">
        {fase === "cargando" && <div className="grid place-items-center py-24 text-ink-3"><Loader2 className="h-6 w-6 animate-spin" /></div>}
        {fase === "no_disponible" && (
          <Card className="p-8 text-center">
            <h1 className="font-display text-xl font-bold">Liga no disponible</h1>
            <p className="mt-2 text-sm text-ink-2">La liga no es válida. Si crees que es un error, contacta al equipo de RH.</p>
          </Card>
        )}
        {fase === "lista" && info && (
          <>
            <div className="text-center">
              <Badge tone="brand" dot>{info.empresa || "Red Human"} · {info.tipoTexto}</Badge>
              <h1 className="font-display mt-3 text-2xl font-bold sm:text-3xl">{info.evaluacion}</h1>
              <p className="mx-auto mt-2 max-w-md text-sm text-ink-2">
                Candidato: <b>{info.candidato}</b>{info.puesto ? ` · ${info.puesto}` : ""}
              </p>
              {info.codigo && <p className="mt-1 font-mono text-[11px] text-ink-3">{info.codigo} · {info.tipoTexto}</p>}
              {info.consentimiento && !info.historica && !info.cancelada && (
                <p className="mt-2"><Badge tone={info.consentimiento === "Aceptado" ? "good" : "warn"} dot>Consentimiento: {info.consentimiento}</Badge></p>
              )}
              {info.cita && (
                <p className="mt-1 text-sm text-ink-3">
                  Cita: {new Date(info.cita).toLocaleString("es-MX", { dateStyle: "long", timeStyle: "short" })}{info.citaLugar ? ` · ${info.citaLugar}` : ""}
                </p>
              )}
            </div>

            {info.historica ? (
              <Card className="mt-6 p-6 text-center">
                <History className="mx-auto h-8 w-8 text-ink-3" />
                <p className="mt-2 text-sm text-ink-2">Esta liga es de una versión anterior y ya no recibe resultados. Pide a RH la liga vigente de tu evaluación.</p>
              </Card>
            ) : info.cancelada ? (
              <Card className="mt-6 p-6 text-center text-sm text-ink-2">Esta evaluación fue cancelada.</Card>
            ) : info.yaRegistrado && !corrigiendo ? (
              <Card className="mt-6 p-6 text-center">
                <CheckCircle2 className="mx-auto h-8 w-8 text-good" />
                <p className="mt-2 text-sm text-ink-2">El resultado ya quedó registrado. ¡Gracias! RH lo revisa en el expediente.</p>
                {info.resultado && (
                  <div className="mx-auto mt-3 max-w-md rounded-xl bg-surface-2 p-3 text-left text-[13px] text-ink-2">
                    {info.resultado.dictamenEvaluador && (
                      <p><b>Dictamen:</b> {info.dictamenesEvaluador?.find((d) => d.valor === info.resultado!.dictamenEvaluador)?.texto ?? info.resultado.dictamenEvaluador}</p>
                    )}
                    {info.resultado.resumen && <p className="mt-1 whitespace-pre-line">{info.resultado.resumen}</p>}
                    {info.resultado.nombreArchivo && <p className="mt-1 text-ink-3">Informe: {info.resultado.nombreArchivo}</p>}
                    <p className="mt-1 text-[11px] text-ink-3">
                      {info.resultado.cargadoPor}{info.resultado.cargadoEn ? ` · ${new Date(info.resultado.cargadoEn).toLocaleString("es-MX")}` : ""}
                      {info.resultado.correcciones ? ` · ${info.resultado.correcciones} corrección(es)` : ""}
                    </p>
                  </div>
                )}
                {avisoArchivo && <p className="mt-2 text-[13px] text-warn">{avisoArchivo}</p>}
                {info.resultado && (
                  <Button variant="outline" className="mt-4" onClick={() => {
                    setResumen(info.resultado!.resumen);
                    setApto(info.resultado!.dictamenEvaluador);
                    setCorrigiendo(true);
                  }}>
                    Corregir resultado
                  </Button>
                )}
              </Card>
            ) : !info.habilitada && !corrigiendo ? (
              <Card className="mt-6 p-6 text-center">
                <Lock className="mx-auto h-8 w-8 text-warn" />
                <p className="mt-2 text-sm text-ink-2">Todavía no puedes registrar el resultado: {info.motivo || "falta un paso previo"}</p>
              </Card>
            ) : (
              <Card className="mt-6 flex flex-col gap-4 p-5">
                {corrigiendo && <p className="rounded-xl bg-warn-soft/50 px-3 py-2 text-[13px] text-warn">Corrección: queda en el historial y RH vuelve a revisar el resultado.</p>}
                {info.pideApto && (
                  <div>
                    <p className="text-sm font-semibold text-ink">{info.tipo === "entrevista_humana" ? "Resultado de la entrevista" : "Dictamen"}</p>
                    <div className={cn("mt-2 grid gap-2", (info.dictamenesEvaluador?.length ?? 2) === 2 ? "grid-cols-2" : "grid-cols-1 sm:grid-cols-3")}>
                      {(info.dictamenesEvaluador ?? [{ valor: "apto", texto: "Apto" }, { valor: "no_apto", texto: "No apto" }]).map((o) => (
                        <button key={o.valor} type="button" onClick={() => setApto(o.valor)}
                          className={cn("min-h-12 rounded-xl border px-2 text-sm font-semibold transition totem:min-h-16 totem:text-xl",
                            apto === o.valor ? "border-brand bg-brand-soft text-brand" : "border-border-soft text-ink-2")}>
                          {o.texto}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-semibold text-ink">{info.pideApto ? "Observaciones" : "Resultado / comentarios"}</span>
                  <textarea rows={5} value={resumen} onChange={(e) => setResumen(e.target.value)}
                    className="rounded-xl border border-border-soft bg-surface px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20" />
                </label>
                <input ref={ref} type="file" accept="application/pdf,image/*" className="hidden" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} />
                <Button variant="outline" onClick={() => ref.current?.click()}>
                  <FileUp className="h-4 w-4" /> {archivo ? archivo.name : "Adjuntar informe (PDF o imagen)"}
                </Button>
                {corrigiendo && (
                  <label className="flex flex-col gap-1.5">
                    <span className="text-sm font-semibold text-ink">Motivo de la corrección</span>
                    <input value={motivo} onChange={(e) => setMotivo(e.target.value)}
                      className="h-11 rounded-xl border border-border-soft bg-surface px-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20" />
                  </label>
                )}
                <label className="flex flex-col gap-1.5">
                  <span className="text-sm font-semibold text-ink">Tu nombre</span>
                  <input value={nombre} onChange={(e) => setNombre(e.target.value)}
                    className="h-11 rounded-xl border border-border-soft bg-surface px-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20" />
                </label>
                {error && <p className="rounded-xl border border-bad/25 bg-bad-soft px-3.5 py-2.5 text-[13px] text-bad">{error}</p>}
                <Button onClick={enviar} disabled={enviando || nombre.trim().length < 3 || (info.pideApto ? !apto : !resumen.trim() && !archivo)}>
                  {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />} {corrigiendo ? "Guardar corrección" : "Registrar resultado"}
                </Button>
                {corrigiendo && <Button variant="ghost" onClick={() => setCorrigiendo(false)} disabled={enviando}>Cancelar corrección</Button>}
              </Card>
            )}
          </>
        )}
      </div>
    </main>
  );
}
