"use client";

/* Difusión manual en Facebook (demo Grupo SEZA, 2026-09-29).

   Por vacante: copy, imagen (1080×1080, color de la empresa) y liga única (`?origen=facebook`), con
   botones para copiar y descargar. NO publica nada: RH pega el texto y sube la imagen a mano. La imagen
   es un <svg> que se dibuja aquí mismo y se convierte a PNG en el navegador al descargar (sin servidor,
   sin sesión en la URL de la imagen). Los datos salen de GET /vacantes/{codigo}/facebook. */

import { useCallback, useEffect, useRef, useState } from "react";
import { Download, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui";
import { Aviso, BotonCopiar } from "@/components/dashboard/subida";
import { fetchPiezaFacebook, type PiezaFacebook } from "@/lib/api";

const LADO = 1080;
const FUENTE = "Arial, Helvetica, sans-serif"; // fuente del sistema: el PNG se ve igual que la vista previa

/** Parte un texto en renglones de a lo más `max` caracteres (sin cortar palabras). */
function renglones(texto: string, max: number, tope: number): string[] {
  const salida: string[] = [];
  let actual = "";
  for (const palabra of texto.split(/\s+/).filter(Boolean)) {
    const prueba = actual ? `${actual} ${palabra}` : palabra;
    if (prueba.length > max && actual) {
      salida.push(actual);
      actual = palabra;
    } else {
      actual = prueba;
    }
  }
  if (actual) salida.push(actual);
  if (salida.length > tope) {
    const recortado = salida.slice(0, tope);
    recortado[tope - 1] = `${recortado[tope - 1].replace(/[.,;:]?$/, "")}…`;
    return recortado;
  }
  return salida;
}

function ImagenFacebook({ datos, svgRef }: { datos: PiezaFacebook["imagen"]; svgRef: React.RefObject<SVGSVGElement | null> }) {
  const color = datos.color || "#ee4444";
  const titulo = renglones(datos.titulo, 20, 3);
  const altoTitulo = titulo.length * 84;
  const yTitulo = 300;
  const yDatos = yTitulo + altoTitulo + 40;
  const destacados = datos.destacados.slice(0, 3).map((d) => renglones(d, 38, 1)[0]);

  return (
    <svg
      ref={svgRef}
      xmlns="http://www.w3.org/2000/svg"
      viewBox={`0 0 ${LADO} ${LADO}`}
      width={LADO}
      height={LADO}
      className="h-auto w-full rounded-xl"
      role="img"
      aria-label={`Imagen para Facebook: ${datos.titulo}`}
    >
      <rect width={LADO} height={LADO} fill={color} />
      {/* textura sutil: dos círculos translúcidos */}
      <circle cx={LADO - 60} cy={120} r={260} fill="#ffffff" opacity={0.08} />
      <circle cx={80} cy={LADO - 200} r={200} fill="#000000" opacity={0.08} />

      <text x={80} y={140} fill="#ffffff" fontFamily={FUENTE} fontSize={40} fontWeight={700} letterSpacing={6}>
        {(datos.empresa || "").toUpperCase()}
      </text>
      <rect x={80} y={165} width={120} height={8} rx={4} fill="#ffffff" />
      <text x={80} y={250} fill="#ffffff" fontFamily={FUENTE} fontSize={46} fontWeight={400} opacity={0.92}>
        ¡Estamos contratando!
      </text>

      {titulo.map((r, i) => (
        <text key={i} x={80} y={yTitulo + 70 + i * 84} fill="#ffffff" fontFamily={FUENTE} fontSize={76} fontWeight={700}>
          {r}
        </text>
      ))}

      {datos.ubicacion && (
        <text x={80} y={yDatos + 50} fill="#ffffff" fontFamily={FUENTE} fontSize={40} opacity={0.95}>
          {`Ubicación: ${datos.ubicacion}`}
        </text>
      )}
      {datos.sueldo && (
        <g>
          <rect x={80} y={yDatos + 80} width={Math.min(920, 60 + datos.sueldo.length * 22)} height={76} rx={38} fill="#ffffff" />
          <text x={110} y={yDatos + 131} fill={color} fontFamily={FUENTE} fontSize={38} fontWeight={700}>
            {datos.sueldo}
          </text>
        </g>
      )}

      {destacados.map((d, i) => {
        const y = yDatos + 230 + i * 62;
        return (
          <g key={i}>
            <circle cx={98} cy={y - 12} r={16} fill="#ffffff" />
            <path d={`M ${90} ${y - 12} l 6 6 l 11 -12`} stroke={color} strokeWidth={4} fill="none" strokeLinecap="round" strokeLinejoin="round" />
            <text x={130} y={y} fill="#ffffff" fontFamily={FUENTE} fontSize={36}>
              {d}
            </text>
          </g>
        );
      })}

      <rect x={0} y={LADO - 130} width={LADO} height={130} fill="#ffffff" />
      <text x={80} y={LADO - 52} fill={color} fontFamily={FUENTE} fontSize={48} fontWeight={700}>
        {datos.llamado}
      </text>
      <text x={LADO - 80} y={LADO - 55} textAnchor="end" fill="#58595b" fontFamily={FUENTE} fontSize={30}>
        Liga en la publicación
      </text>
    </svg>
  );
}

async function descargarPng(svg: SVGSVGElement, nombre: string) {
  const xml = new XMLSerializer().serializeToString(svg);
  const img = new Image();
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
  await img.decode();
  const lienzo = document.createElement("canvas");
  lienzo.width = LADO;
  lienzo.height = LADO;
  lienzo.getContext("2d")?.drawImage(img, 0, 0, LADO, LADO);
  const blob = await new Promise<Blob | null>((ok) => lienzo.toBlob(ok, "image/png"));
  if (!blob) throw new Error("No se pudo generar la imagen.");
  bajar(blob, nombre);
}

function bajar(blob: Blob, nombre: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function PiezaFacebookVacante({ codigo }: { codigo: string }) {
  const [pieza, setPieza] = useState<PiezaFacebook | null>(null);
  const [error, setError] = useState("");
  const [descargando, setDescargando] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const cargar = useCallback(async () => {
    const r = await fetchPiezaFacebook(codigo);
    if (r) setPieza(r);
    else setError("No se pudo cargar la pieza de Facebook de esta vacante.");
  }, [codigo]);
  useEffect(() => {
    cargar();
  }, [cargar]);

  async function descargarImagen() {
    if (!svgRef.current) return;
    setDescargando(true);
    try {
      await descargarPng(svgRef.current, `facebook-${codigo}.png`);
    } catch {
      setError("Tu navegador no pudo generar la imagen. Intenta de nuevo.");
    }
    setDescargando(false);
  }

  if (error && !pieza) return <Aviso tono="error">{error}</Aviso>;
  if (!pieza) return <p className="text-sm text-ink-3">Cargando pieza de Facebook…</p>;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-ink-3">
        Publicación manual: copia el texto, descarga la imagen y pégalos en Facebook. Red Human no publica nada por su cuenta.
      </p>
      {!pieza.publicada && (
        <Aviso tono="warn">La vacante no está publicada: la liga no recibirá postulaciones hasta que la publiques.</Aviso>
      )}
      {error && <Aviso tono="error">{error}</Aviso>}

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-[11px] uppercase tracking-wider text-ink-3">Imagen · 1080×1080</span>
          </div>
          <div className="mt-1.5">
            <ImagenFacebook datos={pieza.imagen} svgRef={svgRef} />
          </div>
          <Button variant="secondary" size="sm" className="mt-2 w-full" onClick={descargarImagen} disabled={descargando}>
            <Download className="h-4 w-4" /> {descargando ? "Generando…" : "Descargar imagen (PNG)"}
          </Button>
        </div>

        <div className="flex flex-col gap-4">
          <div>
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ink-3">Liga única de Facebook</span>
              <BotonCopiar texto={pieza.liga} etiqueta="Copiar liga" />
            </div>
            <a
              href={pieza.liga}
              target="_blank"
              rel="noreferrer"
              className="mt-1.5 flex items-center gap-1.5 break-all rounded-xl bg-surface-2 p-3 text-[13px] text-brand hover:underline"
            >
              {pieza.liga} <ExternalLink className="h-3.5 w-3.5 shrink-0" />
            </a>
            <p className="mt-1 text-[11px] text-ink-3">Quien se postule por esta liga queda registrado con fuente «Facebook».</p>
          </div>

          <div>
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ink-3">Copy ({pieza.copyConLiga.length} car.)</span>
              <div className="flex items-center gap-3">
                <BotonCopiar texto={pieza.copyConLiga} etiqueta="Copiar texto" />
                <button
                  type="button"
                  onClick={() => bajar(new Blob([pieza.copyConLiga], { type: "text/plain;charset=utf-8" }), `facebook-${codigo}.txt`)}
                  className="inline-flex items-center gap-1 text-xs font-medium text-brand transition hover:underline"
                >
                  <Download className="h-3.5 w-3.5" /> Descargar
                </button>
              </div>
            </div>
            <pre className="mt-1.5 max-h-80 overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-surface-2 p-3 font-sans text-[13px] leading-relaxed text-ink-2">
              {pieza.copyConLiga}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
