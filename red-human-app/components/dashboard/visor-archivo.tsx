"use client";

/* Visor interno de archivos de la ficha (2026-10-01, cambios Zeze punto 1): fotografías y PDF (documentos del
   expediente, del vehículo, CV, contrato e informes de evaluaciones) se abren SOBRE la ficha, en un portal, con
   «Cerrar» y «Descargar» por separado. Nada navega ni recarga: al cerrar se conservan el candidato, la pestaña, los
   filtros y la posición del tablero. El archivo se baja como blob (con la sesión): si su tipo no tiene vista previa
   (Word, Excel…) se descarga directo y el visor se cierra solo, sin cerrar la ficha. Un archivo vacío o ilegible se
   informa sin marcarse como falla. Ver · Descargar · Subir/Reemplazar son acciones separadas (`AccionesArchivo`). */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Download, Eye, Loader2, Upload, X } from "lucide-react";
import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";

export interface ArchivoVisor {
  /** URL inline (la del visor). */
  url: string;
  /** URL de descarga (attachment). Por defecto `url` + `descargar=true`. */
  urlDescarga?: string;
  /** Nombre del archivo (para la descarga). */
  nombre?: string;
  titulo: string;
  subtitulo?: string;
}

export function conDescarga(url: string) {
  return `${url}${url.includes("?") ? "&" : "?"}descargar=true`;
}

const PREVIEW = (tipo: string) => tipo.startsWith("image/") || tipo === "application/pdf";

function descargarBlob(blobUrl: string, nombre: string) {
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = nombre || "archivo";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function VisorArchivo({ archivo, onClose }: { archivo: ArchivoVisor; onClose: () => void }) {
  const [estado, setEstado] = useState<{ fase: "cargando" | "listo" | "vacio" | "error"; blob?: string; tipo?: string; detalle?: string }>({ fase: "cargando" });
  const cerrar = useRef(onClose);
  cerrar.current = onClose;
  const urlDescarga = archivo.urlDescarga ?? conDescarga(archivo.url);

  useEffect(() => {
    let vivo = true;
    let blobUrl = "";
    (async () => {
      try {
        const r = await fetch(archivo.url, { credentials: "include" });
        if (!r.ok) {
          let detalle = `No se pudo abrir el archivo (HTTP ${r.status}).`;
          try {
            detalle = (await r.json()).detail || detalle;
          } catch {
            /* sin cuerpo JSON */
          }
          if (vivo) setEstado({ fase: "error", detalle });
          return;
        }
        const blob = await r.blob();
        if (!vivo) return;
        if (!blob.size) return setEstado({ fase: "vacio" });
        blobUrl = URL.createObjectURL(blob);
        const tipo = (blob.type || r.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
        if (!PREVIEW(tipo)) {
          // sin vista previa: se descarga directo y el visor se cierra (la ficha sigue abierta)
          descargarBlob(blobUrl, archivo.nombre || "archivo");
          cerrar.current();
          return;
        }
        setEstado({ fase: "listo", blob: blobUrl, tipo });
      } catch {
        if (vivo) setEstado({ fase: "error", detalle: "No se pudo abrir el archivo. Revisa tu conexión o usa «Descargar»." });
      }
    })();
    return () => {
      vivo = false;
      if (blobUrl) setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
    };
  }, [archivo.url, archivo.nombre]);

  useEffect(() => {
    const tecla = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        ev.stopPropagation();
        cerrar.current();
      }
    };
    window.addEventListener("keydown", tecla, true);
    return () => window.removeEventListener("keydown", tecla, true);
  }, []);

  if (typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-0 backdrop-blur-sm sm:p-6"
      role="dialog" aria-modal="true" aria-label={archivo.titulo}
      onClick={(x) => { x.stopPropagation(); onClose(); }}>
      <div className="flex h-[100dvh] w-full max-w-4xl flex-col overflow-hidden bg-bg shadow-2xl sm:h-[90vh] sm:rounded-2xl" onClick={(x) => x.stopPropagation()}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-soft px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">{archivo.titulo}</p>
            {(archivo.subtitulo || archivo.nombre) && <p className="truncate text-[11px] text-ink-3">{archivo.subtitulo || archivo.nombre}</p>}
          </div>
          <div className="flex items-center gap-2">
            <a href={urlDescarga} download={archivo.nombre || undefined}
              className="inline-flex h-9 items-center gap-1 rounded-xl border border-border-soft px-3 text-sm font-semibold text-brand hover:bg-brand-soft">
              <Download className="h-4 w-4" /> Descargar
            </a>
            <Button size="sm" onClick={onClose}><X className="h-4 w-4" /> Cerrar</Button>
          </div>
        </div>
        <div className="relative flex-1 overflow-auto bg-surface-2">
          {estado.fase === "cargando" && <div className="grid h-full place-items-center text-ink-3"><Loader2 className="h-6 w-6 animate-spin" /></div>}
          {estado.fase === "vacio" && (
            <div className="grid h-full place-items-center p-6 text-center text-sm text-ink-3">El archivo está vacío: no hay nada que mostrar.</div>
          )}
          {estado.fase === "error" && <div className="grid h-full place-items-center p-6 text-center text-sm text-ink-3">{estado.detalle}</div>}
          {estado.fase === "listo" && estado.tipo?.startsWith("image/") && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={estado.blob} alt={archivo.titulo} className="mx-auto max-h-full max-w-full object-contain p-2"
              onError={() => setEstado({ fase: "vacio" })} />
          )}
          {estado.fase === "listo" && estado.tipo === "application/pdf" && (
            <iframe src={estado.blob} title={archivo.titulo} className="h-full w-full border-0 bg-white" />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Ver · Descargar · Subir/Reemplazar como acciones separadas (Subir solo si se pasa `onSubir`). */
export function AccionesArchivo({
  archivo, onVer, onSubir, subiendo = false, accept = "image/jpeg,image/png,image/webp,application/pdf", className, textoSubir,
}: {
  archivo: ArchivoVisor | null;
  onVer: (a: ArchivoVisor) => void;
  onSubir?: (f: File) => void;
  subiendo?: boolean;
  accept?: string;
  className?: string;
  textoSubir?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1", className)}>
      {archivo && (
        <>
          <Button size="sm" variant="ghost" onClick={() => onVer(archivo)} title="Ver dentro de la ficha"><Eye className="h-4 w-4" /> Ver</Button>
          <a href={archivo.urlDescarga ?? conDescarga(archivo.url)} download={archivo.nombre || undefined} title="Descargar"
            className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-[12px] font-semibold text-brand hover:bg-brand-soft">
            <Download className="h-3.5 w-3.5" /> Descargar
          </a>
        </>
      )}
      {onSubir && (
        <>
          <input ref={ref} type="file" className="hidden" accept={accept}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) onSubir(f); e.target.value = ""; }} />
          <Button size="sm" variant="ghost" disabled={subiendo} onClick={() => ref.current?.click()}>
            <Upload className="h-4 w-4" /> {subiendo ? "Revisando archivo..." : textoSubir ?? (archivo ? "Reemplazar" : "Subir")}
          </Button>
        </>
      )}
    </span>
  );
}
