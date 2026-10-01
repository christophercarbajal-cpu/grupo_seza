"use client";

import { useCallback, useRef, useState } from "react";
import { AlertTriangle, Check, Copy, Info, Loader2, UploadCloud, X } from "lucide-react";
import { cn } from "@/lib/utils";

/* Formatos que la API acepta (app/services/archivos.py) */
export const FORMATOS_OK = ".pdf,.png,.jpg,.jpeg,.webp";
export const FORMATOS_TEXTO = "PDF, PNG, JPG o WEBP · máx. 10 MB";

export function pesoLegible(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/* ---------------- Zona de arrastre ---------------- */
export function Dropzone({
  onArchivos,
  multiple = false,
  cargando = false,
  textoCargando = "Procesando con IA…",
  titulo = "Arrastra el archivo o haz clic para elegirlo",
  ayuda = FORMATOS_TEXTO,
  compacto = false,
}: {
  onArchivos: (archivos: File[]) => void;
  multiple?: boolean;
  cargando?: boolean;
  /** Texto mientras carga (validación básica de documentos: «Revisando archivo...»). */
  textoCargando?: string;
  titulo?: string;
  ayuda?: string;
  compacto?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [sobre, setSobre] = useState(false);

  const soltar = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setSobre(false);
      if (cargando) return;
      const archivos = Array.from(e.dataTransfer.files ?? []);
      if (archivos.length) onArchivos(multiple ? archivos : archivos.slice(0, 1));
    },
    [cargando, multiple, onArchivos],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setSobre(true);
      }}
      onDragLeave={() => setSobre(false)}
      onDrop={soltar}
      onClick={() => !cargando && input.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") input.current?.click();
      }}
      aria-label={titulo}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed text-center transition",
        compacto ? "px-4 py-4" : "px-6 py-8",
        cargando && "pointer-events-none opacity-70",
        sobre ? "border-brand bg-brand-soft/50" : "border-border-soft hover:border-brand hover:bg-surface-2",
      )}
    >
      <input
        ref={input}
        type="file"
        accept={FORMATOS_OK}
        multiple={multiple}
        className="hidden"
        // el click programático burbujea al contenedor y volvería a abrir el selector
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => {
          const archivos = Array.from(e.target.files ?? []);
          if (archivos.length) onArchivos(archivos);
          e.target.value = ""; // permite volver a subir el mismo archivo
        }}
      />
      {cargando ? (
        <Loader2 className={cn("animate-spin text-brand", compacto ? "h-5 w-5" : "h-8 w-8")} />
      ) : (
        <UploadCloud className={cn("text-ink-3", compacto ? "h-5 w-5" : "h-8 w-8")} />
      )}
      <div>
        <p className={cn("font-semibold", compacto ? "text-[13px]" : "text-sm")}>
          {cargando ? textoCargando : titulo}
        </p>
        <p className="text-xs text-ink-3">{ayuda}</p>
      </div>
    </div>
  );
}

/* ---------------- Aviso en línea ---------------- */
export type TonoAviso = "ok" | "error" | "info" | "warn";

const avisoConfig: Record<TonoAviso, { clase: string; icono: React.ComponentType<{ className?: string }> }> = {
  ok: { clase: "border-good/25 bg-good-soft text-good", icono: Check },
  error: { clase: "border-bad/25 bg-bad-soft text-bad", icono: AlertTriangle },
  warn: { clase: "border-warn/25 bg-warn-soft text-warn", icono: AlertTriangle },
  info: { clase: "border-brand/25 bg-brand-soft/60 text-brand", icono: Info },
};

export function Aviso({
  tono = "info",
  children,
  onCerrar,
}: {
  tono?: TonoAviso;
  children: React.ReactNode;
  onCerrar?: () => void;
}) {
  const c = avisoConfig[tono];
  return (
    <div className={cn("flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-[13px]", c.clase)}>
      <c.icono className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="flex-1 leading-relaxed">{children}</div>
      {onCerrar && (
        <button onClick={onCerrar} className="shrink-0 opacity-60 hover:opacity-100" aria-label="Cerrar aviso">
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

/* ---------------- Botón copiar ---------------- */
export function BotonCopiar({ texto, etiqueta = "Copiar" }: { texto: string; etiqueta?: string }) {
  const [copiado, setCopiado] = useState(false);

  async function copiar() {
    try {
      await navigator.clipboard.writeText(texto);
    } catch {
      return; // el navegador bloqueó el portapapeles (contexto no seguro)
    }
    setCopiado(true);
    setTimeout(() => setCopiado(false), 1800);
  }

  return (
    <button
      onClick={copiar}
      disabled={!texto}
      className="inline-flex items-center gap-1 text-xs font-medium text-brand transition hover:underline disabled:opacity-40"
    >
      {copiado ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copiado ? "Copiado" : etiqueta}
    </button>
  );
}
