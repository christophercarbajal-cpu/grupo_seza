"use client";

/* Regla universal de ligas (2026-09-30): toda liga externa (consentimiento, médico, proveedor, capacitador,
   vehículo, expediente…) se muestra en su tarjeta con «Generar liga / Abrir / Copiar liga / Enviar o reenviar». Si ya
   existe se REUTILIZA; existe aunque el envío automático falle (no depende de WhatsApp ni de Telegram): el resultado
   del envío se muestra aparte y nunca la oculta.
   2026-10-01 (Zeze punto 4): cada canal (mensaje y correo, independientes) muestra su estado — Pendiente / Enviado /
   Entregado / Fallido — con Copiar liga y Reenviar siempre disponibles (`envios`, ver `EstadosEnvio`). */

import { ExternalLink, Link2, Send } from "lucide-react";
import { Button } from "@/components/ui";
import { BotonCopiar } from "@/components/dashboard/subida";
import { cn } from "@/lib/utils";

export interface EnvioLiga {
  enviado: boolean;
  detalle?: string;
  canal?: string;
  fecha?: string;
  /** pendiente | enviado | entregado | fallido (filas nuevas); las viejas se deducen de `enviado`. */
  estado?: string;
  estadoTexto?: string;
}

const TEXTO_ESTADO: Record<string, string> = { pendiente: "Pendiente", enviado: "Enviado", entregado: "Entregado", fallido: "Fallido" };
const TONO_ESTADO: Record<string, string> = {
  pendiente: "bg-surface text-ink-3", enviado: "bg-brand-soft text-brand", entregado: "bg-good-soft text-good", fallido: "bg-bad-soft text-bad",
};
const NOMBRE_CANAL: Record<string, string> = { mensaje: "Mensaje", correo: "Correo", whatsapp: "Mensaje" };

function estadoDe(e: EnvioLiga) {
  return e.estado || (e.enviado ? "enviado" : "fallido");
}

/** El último estado por canal (los envíos llegan del más reciente al más viejo). */
export function EstadosEnvio({ envios, className }: { envios: EnvioLiga[]; className?: string }) {
  const vistos = new Set<string>();
  const ultimos = envios.filter((e) => {
    const k = e.canal || "—";
    if (vistos.has(k)) return false;
    vistos.add(k);
    return true;
  });
  if (!ultimos.length) return <p className={cn("text-[11px] text-ink-3", className)}>Sin envíos todavía · <span className={cn("rounded px-1.5 py-0.5 font-semibold", TONO_ESTADO.pendiente)}>Pendiente</span></p>;
  return (
    <ul className={cn("flex flex-col gap-0.5 text-[11px]", className)}>
      {ultimos.map((e, i) => {
        const est = estadoDe(e);
        return (
          <li key={i} className="flex flex-wrap items-center gap-1.5">
            <span className="text-ink-3">{NOMBRE_CANAL[e.canal ?? ""] ?? (e.canal && e.canal !== "—" ? e.canal : "Envío")}:</span>
            <span className={cn("rounded px-1.5 py-0.5 font-semibold", TONO_ESTADO[est] ?? TONO_ESTADO.pendiente)}>{e.estadoTexto || TEXTO_ESTADO[est] || est}</span>
            {e.fecha && <span className="text-ink-3">{new Date(e.fecha).toLocaleString("es-MX", { dateStyle: "short", timeStyle: "short" })}</span>}
            {est !== "enviado" && est !== "entregado" && e.detalle && <span className="text-ink-3">— {e.detalle}</span>}
          </li>
        );
      })}
    </ul>
  );
}

export function LigaAcciones({
  etiqueta,
  liga,
  onEnviar,
  enviando = false,
  ultimoEnvio,
  textoEnviar,
  className,
  onGenerar,
  generando = false,
  envios,
}: {
  etiqueta?: string;
  liga: string;
  /** Sin `onEnviar` solo se muestran Abrir y Copiar. */
  onEnviar?: () => void;
  /** Sin liga todavía: «Generar liga» (la crea sin enviarla). */
  onGenerar?: () => void;
  generando?: boolean;
  enviando?: boolean;
  ultimoEnvio?: EnvioLiga | null;
  textoEnviar?: string;
  className?: string;
  /** Envíos por canal (más reciente primero): muestra Pendiente / Enviado / Entregado / Fallido por canal. */
  envios?: EnvioLiga[];
}) {
  if (!liga) {
    if (!onGenerar) return null;
    return (
      <div className={cn("flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-2 px-3 py-2", className)}>
        <span className="text-[12px] text-ink-3">{etiqueta ? `${etiqueta}: ` : ""}aún no hay liga.</span>
        <Button size="sm" variant="outline" disabled={generando} onClick={onGenerar}>
          <Link2 className="h-3.5 w-3.5" /> {generando ? "Generando…" : "Generar liga"}
        </Button>
      </div>
    );
  }
  return (
    <div className={cn("rounded-xl bg-surface-2 px-3 py-2", className)}>
      {etiqueta && <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">{etiqueta}</p>}
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3" title={liga}>{liga}</span>
        <a href={liga} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-[12px] font-semibold text-brand hover:bg-brand-soft">
          <ExternalLink className="h-3.5 w-3.5" /> Abrir
        </a>
        <BotonCopiar texto={liga} etiqueta="Copiar liga" />
        {onEnviar && (
          <Button size="sm" variant="outline" disabled={enviando} onClick={onEnviar}>
            <Send className="h-3.5 w-3.5" /> {enviando ? "Enviando…" : textoEnviar ?? (ultimoEnvio || envios?.length ? "Reenviar" : "Enviar")}
          </Button>
        )}
      </div>
      {envios ? (
        <EstadosEnvio envios={envios} className="mt-1" />
      ) : ultimoEnvio && (
        <p className={cn("mt-1 text-[11px]", ultimoEnvio.enviado ? "text-good" : "text-warn")}>
          {ultimoEnvio.enviado
            ? `Enviada${ultimoEnvio.canal ? ` por ${ultimoEnvio.canal}` : ""}${ultimoEnvio.fecha ? ` · ${new Date(ultimoEnvio.fecha).toLocaleString("es-MX")}` : ""}`
            : `No se envió${ultimoEnvio.detalle ? `: ${ultimoEnvio.detalle}` : ""} — copia la liga y compártela.`}
        </p>
      )}
    </div>
  );
}
