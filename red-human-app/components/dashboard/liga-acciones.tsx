"use client";

/* Regla universal de ligas (2026-09-30): toda liga que el sistema genera (consentimiento, médico, proveedor,
   capacitador, vehículo, expediente…) se muestra en su tarjeta con «Abrir / Copiar / Enviar o reenviar». La liga
   existe aunque el envío automático falle: el resultado del envío se muestra aparte y nunca la oculta. */

import { ExternalLink, Send } from "lucide-react";
import { Button } from "@/components/ui";
import { BotonCopiar } from "@/components/dashboard/subida";
import { cn } from "@/lib/utils";

export interface EnvioLiga {
  enviado: boolean;
  detalle?: string;
  canal?: string;
  fecha?: string;
}

export function LigaAcciones({
  etiqueta,
  liga,
  onEnviar,
  enviando = false,
  ultimoEnvio,
  textoEnviar,
  className,
}: {
  etiqueta?: string;
  liga: string;
  /** Sin `onEnviar` solo se muestran Abrir y Copiar. */
  onEnviar?: () => void;
  enviando?: boolean;
  ultimoEnvio?: EnvioLiga | null;
  textoEnviar?: string;
  className?: string;
}) {
  if (!liga) return null;
  return (
    <div className={cn("rounded-xl bg-surface-2 px-3 py-2", className)}>
      {etiqueta && <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">{etiqueta}</p>}
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3" title={liga}>{liga}</span>
        <a href={liga} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-[12px] font-semibold text-brand hover:bg-brand-soft">
          <ExternalLink className="h-3.5 w-3.5" /> Abrir
        </a>
        <BotonCopiar texto={liga} etiqueta="Copiar" />
        {onEnviar && (
          <Button size="sm" variant="outline" disabled={enviando} onClick={onEnviar}>
            <Send className="h-3.5 w-3.5" /> {enviando ? "Enviando…" : textoEnviar ?? (ultimoEnvio ? "Reenviar" : "Enviar")}
          </Button>
        )}
      </div>
      {ultimoEnvio && (
        <p className={cn("mt-1 text-[11px]", ultimoEnvio.enviado ? "text-good" : "text-warn")}>
          {ultimoEnvio.enviado
            ? `Enviada${ultimoEnvio.canal ? ` por ${ultimoEnvio.canal}` : ""}${ultimoEnvio.fecha ? ` · ${new Date(ultimoEnvio.fecha).toLocaleString("es-MX")}` : ""}`
            : `No se envió${ultimoEnvio.detalle ? `: ${ultimoEnvio.detalle}` : ""} — copia la liga y compártela.`}
        </p>
      )}
    </div>
  );
}
