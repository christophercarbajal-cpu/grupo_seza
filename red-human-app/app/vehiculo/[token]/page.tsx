"use client";

/* Liga pública para que el candidato suba lo de su vehículo (demo Grupo SEZA; v2 2026-09-30).
   Sin sesión: el token es el secreto. Cuatro fotos — frente, atrás y ambos costados — (en el celular el botón abre
   la cámara trasera) y tres documentos en foto o PDF: licencia vigente, tarjeta de circulación y póliza de seguro.
   Si RH pide corrección, solo se habilita lo que hay que volver a subir y se muestra su comentario. La decisión
   (aprobar / corregir / excepción) es de RH. */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Camera, CheckCircle2, Clock, FileText, Loader2, RefreshCw, Upload } from "lucide-react";
import { Logo, Card, Badge } from "@/components/ui";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";
import { fetchVehiculoPublico, subirDocumentoVehiculo, subirFotoVehiculo, urlFotoVehiculoPublica, type VehiculoPublico } from "@/lib/api";

type Fase = "cargando" | "no_disponible" | "lista";

const GUIA: Record<string, string> = {
  frente: "De frente, que se vea completo con placas.",
  atras: "Por detrás, completo y con placas.",
  izquierdo: "Costado del conductor, de extremo a extremo.",
  derecho: "Costado del copiloto, de extremo a extremo.",
};

export default function FotosVehiculo() {
  const params = useParams();
  const token = String(params?.token ?? "");
  const [fase, setFase] = useState<Fase>("cargando");
  const [info, setInfo] = useState<VehiculoPublico | null>(null);
  const [subiendo, setSubiendo] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [errores, setErrores] = useState<Record<string, string>>({});  // por foto/documento (validación básica)
  const [version, setVersion] = useState(0); // refresca las miniaturas tras subir

  const cargar = useCallback(() => {
    fetchVehiculoPublico(token).then((i) => {
      if (!i) return setFase("no_disponible");
      setInfo(i);
      setFase("lista");
    });
  }, [token]);
  useEffect(() => {
    cargar();
  }, [cargar]);

  async function subir(lado: string, archivo?: File) {
    if (!archivo) return;
    setSubiendo(lado);
    setError("");
    setErrores((e) => ({ ...e, [lado]: "" }));
    const r = await subirFotoVehiculo(token, lado, archivo);
    setSubiendo(null);
    if (!r.ok) return setErrores((e) => ({ ...e, [lado]: r.error }));
    setInfo(r.data);
    setVersion((v) => v + 1);
  }

  async function subirDoc(clave: string, archivo?: File) {
    if (!archivo) return;
    setSubiendo(clave);
    setError("");
    setErrores((e) => ({ ...e, [clave]: "" }));
    const r = await subirDocumentoVehiculo(token, clave, archivo);
    setSubiendo(null);
    if (!r.ok) return setErrores((e) => ({ ...e, [clave]: r.error }));
    setInfo(r.data);
  }

  const pendientes = (info?.lados.filter((l) => l.pendiente).length ?? 0) + (info?.documentos?.filter((d) => d.pendiente).length ?? 0);

  return (
    <main className="sala-publica min-h-svh bg-bg">
      <header className="border-b border-border-soft">
        <div className="mx-auto flex max-w-2xl items-center justify-between px-5 py-4">
          <Logo />
          <ThemeToggle />
        </div>
      </header>

      <div className="mx-auto max-w-2xl px-4 py-8 sm:px-5 sm:py-10">
        {fase === "cargando" && (
          <div className="grid place-items-center py-24 text-ink-3">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        )}

        {fase === "no_disponible" && (
          <Card className="p-8 text-center">
            <h1 className="font-display text-xl font-bold">Liga no disponible</h1>
            <p className="mt-2 text-sm text-ink-2">Esta liga no es válida o tu postulación ya se cerró. Si crees que es un error, escríbenos por el chat.</p>
          </Card>
        )}

        {fase === "lista" && info && (
          <>
            <div className="text-center">
              <Badge tone="brand" dot>
                Fotos del vehículo
              </Badge>
              <h1 className="font-display mt-3 text-2xl font-bold sm:text-3xl">{info.nombre ? `Hola, ${info.nombre}` : "Fotos de tu vehículo"}</h1>
              <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-2">
                {info.vacante && `Para tu postulación a ${info.vacante}${info.empresa ? ` en ${info.empresa}` : ""}. `}
                Sube 4 fotos del vehículo completo (de día y sin filtros) y tu licencia, tarjeta de circulación y póliza de seguro.
              </p>
            </div>

            {info.estado === "correccion" && info.comentario && (
              <Card className="mt-6 border-warn/40 bg-warn-soft/40 p-4">
                <p className="text-sm font-semibold text-ink">Necesitamos que vuelvas a subir {pendientes === 1 ? "un archivo" : `${pendientes} archivos`}</p>
                <p className="mt-1 text-[13px] text-ink-2">{info.comentario}</p>
              </Card>
            )}

            {!info.abierta && (
              <Card className="mt-6 p-6 text-center">
                {info.estado === "por_revisar" ? <Clock className="mx-auto h-8 w-8 text-warn" /> : <CheckCircle2 className="mx-auto h-8 w-8 text-good" />}
                <p className="mt-2 text-sm text-ink-2">
                  {info.estado === "por_revisar"
                    ? "¡Listo! Recibimos tus fotos y documentos. El equipo de RH los revisará y te avisará por el chat."
                    : "Tu vehículo ya fue revisado. Te contactaremos por el chat para el siguiente paso."}
                </p>
              </Card>
            )}

            {error && <div className="mt-4 rounded-xl border border-bad/25 bg-bad-soft px-3.5 py-2.5 text-[13px] text-bad">{error}</div>}

            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              {info.lados.map((l) => (
                <LadoFoto
                  key={l.clave}
                  nombre={l.nombre}
                  guia={GUIA[l.clave] ?? ""}
                  cargada={l.cargada}
                  habilitado={info.abierta && (info.estado === "pendiente" || l.pendiente)}
                  subiendo={subiendo === l.clave}
                  error={errores[l.clave] ?? ""}
                  miniatura={l.cargada ? urlFotoVehiculoPublica(token, l.clave, String(version)) : ""}
                  onArchivo={(f) => void subir(l.clave, f)}
                />
              ))}
            </div>
            {Boolean(info.documentos?.length) && (
              <>
                <h2 className="font-display mt-8 text-lg font-bold">Documentos</h2>
                <div className="mt-3 flex flex-col gap-3">
                  {info.documentos.map((d) => (
                    <DocumentoVehiculo
                      key={d.clave}
                      nombre={d.nombre}
                      estado={d.estado}
                      motivo={d.motivo}
                      cargado={d.cargado}
                      habilitado={info.abierta && (info.estado === "pendiente" ? !d.cargado || d.pendiente : d.pendiente)}
                      subiendo={subiendo === d.clave}
                      error={errores[d.clave] ?? ""}
                      onArchivo={(f) => void subirDoc(d.clave, f)}
                    />
                  ))}
                </div>
              </>
            )}
            {info.abierta && (
              <p className="mt-4 text-center text-[12px] text-ink-3">
                {pendientes ? `Faltan ${pendientes}.` : ""} Fotos: JPG, PNG o WEBP · documentos: foto o PDF · máx. 10 MB. En iPhone usa «Más compatible» en Ajustes › Cámara › Formatos.
              </p>
            )}
          </>
        )}
      </div>
    </main>
  );
}

function LadoFoto({
  nombre,
  guia,
  cargada,
  habilitado,
  subiendo,
  miniatura,
  onArchivo,
  error = "",
}: {
  nombre: string;
  guia: string;
  cargada: boolean;
  habilitado: boolean;
  subiendo: boolean;
  error?: string;
  miniatura: string;
  onArchivo: (f?: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <Card className={cn("overflow-hidden", habilitado && !cargada && "border-brand/40")}>
      <div className="relative aspect-[4/3] bg-surface-2">
        {miniatura ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={miniatura} alt={`Foto: ${nombre}`} className="h-full w-full object-cover" />
        ) : (
          <div className="grid h-full place-items-center text-ink-3">
            <Camera className="h-10 w-10" />
          </div>
        )}
        {cargada && !habilitado && (
          <span className="absolute right-2 top-2">
            <Badge tone="good" dot>Recibida</Badge>
          </span>
        )}
      </div>
      <div className="flex flex-col gap-2 p-3.5">
        <div>
          <p className="text-sm font-semibold text-ink">{nombre}</p>
          <p className="text-[12px] text-ink-3">{guia}</p>
        </div>
        {habilitado && (
          <>
            <input
              ref={input}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              className="hidden"
              onChange={(e) => {
                onArchivo(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => input.current?.click()}
              disabled={subiendo}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-brand px-4 text-sm font-semibold text-brand-ink transition hover:brightness-110 disabled:opacity-60 totem:min-h-16 totem:text-xl"
            >
              {subiendo ? <Loader2 className="h-4 w-4 animate-spin" /> : cargada || error ? <RefreshCw className="h-4 w-4" /> : <Camera className="h-4 w-4" />}
              {subiendo ? "Revisando archivo..." : error ? "Tomar otra foto" : cargada ? "Volver a tomar" : "Tomar foto"}
            </button>
          </>
        )}
        {error && <p role="alert" className="rounded-xl border border-bad/25 bg-bad-soft px-3 py-2 text-[12px] text-bad">{error}</p>}
      </div>
    </Card>
  );
}

function DocumentoVehiculo({
  nombre,
  estado,
  motivo,
  cargado,
  habilitado,
  subiendo,
  onArchivo,
  error = "",
}: {
  nombre: string;
  estado: string;
  motivo: string;
  cargado: boolean;
  habilitado: boolean;
  subiendo: boolean;
  error?: string;
  onArchivo: (f?: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const tono = estado === "Revisado" ? "good" : estado === "Requiere corrección" ? "bad" : cargado ? "warn" : "neutral";
  return (
    <Card className={cn("flex flex-col gap-2 p-3.5", habilitado && !cargado && "border-brand/40")}>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-semibold text-ink">
          <FileText className="h-4 w-4 text-ink-3" /> {nombre}
        </span>
        <Badge tone={tono} dot>{estado}</Badge>
      </div>
      {motivo && <p className="text-[12px] text-bad">Qué corregir: {motivo}</p>}
      {habilitado && (
        <>
          <input
            ref={input}
            type="file"
            accept="image/jpeg,image/png,image/webp,application/pdf"
            className="hidden"
            onChange={(e) => {
              onArchivo(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => input.current?.click()}
            disabled={subiendo}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-brand px-4 text-sm font-semibold text-brand-ink transition hover:brightness-110 disabled:opacity-60 totem:min-h-16 totem:text-xl"
          >
            {subiendo ? <Loader2 className="h-4 w-4 animate-spin" /> : cargado || error ? <RefreshCw className="h-4 w-4" /> : <Upload className="h-4 w-4" />}
            {subiendo ? "Revisando archivo..." : error ? "Reemplazar archivo" : cargado ? "Volver a subir" : "Subir foto o PDF"}
          </button>
        </>
      )}
      {error && <p role="alert" className="rounded-xl border border-bad/25 bg-bad-soft px-3 py-2 text-[12px] text-bad">{error}</p>}
    </Card>
  );
}
