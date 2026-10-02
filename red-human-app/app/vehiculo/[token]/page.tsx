"use client";

/* Liga pública para que el candidato suba lo de su vehículo (demo Grupo SEZA; v2 2026-09-30; rutas paralelas 2026-10-01).
   Sin sesión: el token es el secreto. Cuatro fotos — frente, atrás y ambos costados — y tres documentos en foto o PDF:
   licencia vigente, tarjeta de circulación y póliza de seguro. Es parte de la ruta 100 % web: al terminar se ofrece
   (opcional) «Conectar Telegram» solo para recibir avisos.
   Corrección de RH: la página abre directo en los archivos POR CORREGIR — cada uno con el motivo y la instrucción de RH y
   el botón «Reemplazar foto» (cámara o galería). Lo ya recibido se conserva intacto (no se puede tocar). Al reemplazar:
   «Recibimos tu nueva foto. Está pendiente de revisión.» La decisión (aprobar / corregir / excepción) es de RH. */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { AlertTriangle, Camera, CheckCircle2, Clock, FileText, Image as ImageIcon, Loader2, Lock, RefreshCw, Upload } from "lucide-react";
import { Logo, Card, Badge } from "@/components/ui";
import { ThemeToggle } from "@/components/theme-toggle";
import { ConectarTelegram } from "@/components/conectar-telegram";
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
  const [errores, setErrores] = useState<Record<string, string>>({});  // por foto/documento (validación básica)
  const [exitos, setExitos] = useState<Record<string, string>>({});  // «Recibimos tu nueva foto…» por archivo
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

  async function enviar(clave: string, archivo: File | undefined, esFoto: boolean) {
    if (!archivo) return;
    setSubiendo(clave);
    setErrores((e) => ({ ...e, [clave]: "" }));
    setExitos((e) => ({ ...e, [clave]: "" }));
    const r = esFoto ? await subirFotoVehiculo(token, clave, archivo) : await subirDocumentoVehiculo(token, clave, archivo);
    setSubiendo(null);
    if (!r.ok) return setErrores((e) => ({ ...e, [clave]: r.error }));
    setInfo(r.data);
    if (r.data.mensaje) setExitos((e) => ({ ...e, [r.data.claveMensaje || clave]: r.data.mensaje! }));
    if (esFoto) setVersion((v) => v + 1);
  }

  const enCorreccion = info?.estado === "correccion";
  const correccion = info?.correccion ?? [];
  const porCorregir = new Set(correccion.filter((c) => c.pendiente).map((c) => c.clave));
  const reemplazados = correccion.filter((c) => !c.pendiente);
  const pedidos = new Set(correccion.map((c) => c.clave));  // lo pedido en la corrección (pendiente o ya reemplazado)
  const modoCorreccion = enCorreccion && pedidos.size > 0;  // correcciones viejas sin detalle: vista normal
  const pendientes = (info?.lados.filter((l) => l.pendiente).length ?? 0) + (info?.documentos?.filter((d) => d.pendiente).length ?? 0);
  const motivo = (clave: string) => correccion.find((c) => c.clave === clave);
  // En corrección: arriba SOLO lo que hay que reemplazar; lo demás va abajo, intacto y bloqueado
  const lados = info?.lados ?? [];
  const documentos = info?.documentos ?? [];
  const ladosArriba = modoCorreccion ? lados.filter((l) => pedidos.has(l.clave)) : lados;
  const docsArriba = modoCorreccion ? documentos.filter((d) => pedidos.has(d.clave)) : documentos;
  const recibidos = modoCorreccion ? [...lados.filter((l) => !pedidos.has(l.clave)), ...documentos.filter((d) => !pedidos.has(d.clave))] : [];

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
            <p className="mt-2 text-sm text-ink-2">Esta liga no es válida o tu postulación ya se cerró. Si crees que es un error, contacta al equipo de RH.</p>
          </Card>
        )}

        {fase === "lista" && info && (
          <>
            <div className="text-center">
              <Badge tone={enCorreccion ? "warn" : "brand"} dot>
                {enCorreccion ? "Archivos por corregir" : "Fotos y documentos del vehículo"}
              </Badge>
              <h1 className="font-display mt-3 text-2xl font-bold sm:text-3xl">{info.nombre ? `Hola, ${info.nombre}` : "Fotos de tu vehículo"}</h1>
              <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-2">
                {info.vacante && `Para tu postulación a ${info.vacante}${info.empresa ? ` en ${info.empresa}` : ""}. `}
                {enCorreccion
                  ? porCorregir.size
                    ? `Reemplaza ${porCorregir.size === 1 ? "el archivo marcado" : `los ${porCorregir.size} archivos marcados`}. Lo demás ya está recibido y se conserva.`
                    : "Ya reemplazaste todo lo que te pedimos."
                  : "Sube 4 fotos del vehículo completo (de día y sin filtros) y tu licencia, tarjeta de circulación y póliza de seguro."}
              </p>
            </div>

            {!info.abierta && (
              <Card className="mt-6 p-6 text-center">
                {info.estado === "por_revisar" ? <Clock className="mx-auto h-8 w-8 text-warn" /> : <CheckCircle2 className="mx-auto h-8 w-8 text-good" />}
                <p className="mt-2 text-sm text-ink-2">
                  {info.estado === "por_revisar"
                    ? "¡Listo! Recibimos tus fotos y documentos. Están pendientes de revisión; te avisaremos el siguiente paso."
                    : "Tu vehículo ya fue revisado. Te avisaremos el siguiente paso."}
                </p>
                {reemplazados.length > 0 && info.estado === "por_revisar" && (
                  <p className="mt-2 text-[13px] text-good">
                    {reemplazados.length === 1 ? (reemplazados[0].esFoto ? "Recibimos tu nueva foto. Está pendiente de revisión." : "Recibimos tu nuevo documento. Está pendiente de revisión.")
                      : "Recibimos tus nuevos archivos. Están pendientes de revisión."}
                  </p>
                )}
              </Card>
            )}

            {/* Fin de la ruta web: Telegram es OPCIONAL y solo para avisos */}
            {!info.abierta && info.telegram?.liga && !info.telegram.conectado && (
              <div className="mt-5 flex justify-center">
                <ConectarTelegram liga={info.telegram.liga} ligaWeb={info.telegram.ligaWeb} />
              </div>
            )}
            {info.telegram?.conectado && !info.abierta && (
              <p className="mt-4 text-center text-[13px] text-ink-3">Telegram conectado: por ahí te avisaremos los siguientes pasos.</p>
            )}

            {info.abierta && (
              <>
                <div className={cn("mt-6 grid gap-3", !modoCorreccion && "sm:grid-cols-2")}>
                  {ladosArriba.map((l) => (
                    <LadoFoto
                      key={l.clave}
                      nombre={l.nombre}
                      guia={GUIA[l.clave] ?? ""}
                      cargada={l.cargada}
                      habilitado={info.estado === "pendiente" || l.pendiente}
                      correccion={motivo(l.clave)}
                      subiendo={subiendo === l.clave}
                      error={errores[l.clave] ?? ""}
                      exito={exitos[l.clave] ?? ""}
                      miniatura={l.cargada ? urlFotoVehiculoPublica(token, l.clave, String(version)) : ""}
                      onArchivo={(f) => void enviar(l.clave, f, true)}
                    />
                  ))}
                </div>
                {docsArriba.length > 0 && (
                  <>
                    {!modoCorreccion && <h2 className="font-display mt-8 text-lg font-bold">Documentos</h2>}
                    <div className="mt-3 flex flex-col gap-3">
                      {docsArriba.map((d) => (
                        <DocumentoVehiculo
                          key={d.clave}
                          nombre={d.nombre}
                          estado={d.estado}
                          correccion={motivo(d.clave)}
                          motivo={d.motivo}
                          cargado={d.cargado}
                          habilitado={info.estado === "pendiente" ? !d.cargado || d.pendiente : d.pendiente}
                          subiendo={subiendo === d.clave}
                          error={errores[d.clave] ?? ""}
                          exito={exitos[d.clave] ?? ""}
                          onArchivo={(f) => void enviar(d.clave, f, false)}
                        />
                      ))}
                    </div>
                  </>
                )}

                {recibidos.length > 0 && (
                  <Card className="mt-6 p-4">
                    <p className="flex items-center gap-2 text-sm font-semibold text-ink">
                      <Lock className="h-4 w-4 text-ink-3" /> Ya recibidos (se conservan)
                    </p>
                    <ul className="mt-2 flex flex-wrap gap-2">
                      {recibidos.map((x) => (
                        <li key={x.clave}>
                          <Badge tone="good" dot>{x.nombre}</Badge>
                        </li>
                      ))}
                    </ul>
                  </Card>
                )}

                <p className="mt-4 text-center text-[12px] text-ink-3">
                  {pendientes ? `Faltan ${pendientes}.` : ""} Fotos: JPG, PNG o WEBP · documentos: foto o PDF · máx. 10 MB. En iPhone usa «Más compatible» en Ajustes › Cámara › Formatos.
                </p>
              </>
            )}
          </>
        )}
      </div>
    </main>
  );
}

type Correccion = NonNullable<VehiculoPublico["correccion"]>[number];

/** Motivo + instrucción de RH junto al archivo rechazado. */
function NotaCorreccion({ c }: { c?: Correccion }) {
  if (!c?.pendiente) return null;
  return (
    <div className="rounded-xl border border-warn/40 bg-warn-soft/40 px-3 py-2 text-[13px]">
      <p className="flex items-start gap-1.5 font-semibold text-ink">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" /> {c.motivo ? `Motivo: ${c.motivo}` : "RH pidió reemplazarlo"}
      </p>
      {c.instruccion && <p className="mt-1 text-ink-2">{c.instruccion}</p>}
    </div>
  );
}

function Mensajes({ error, exito }: { error: string; exito: string }) {
  return (
    <>
      {error && <p role="alert" className="rounded-xl border border-bad/25 bg-bad-soft px-3 py-2 text-[12px] text-bad">{error}</p>}
      {exito && (
        <p role="status" className="flex items-center gap-1.5 rounded-xl border border-good/25 bg-good-soft px-3 py-2 text-[12px] text-good">
          <CheckCircle2 className="h-4 w-4 shrink-0" /> {exito}
        </p>
      )}
    </>
  );
}

const BOTON = "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 text-sm font-semibold transition disabled:opacity-60 totem:min-h-16 totem:text-xl";

function LadoFoto({
  nombre,
  guia,
  cargada,
  habilitado,
  correccion,
  subiendo,
  miniatura,
  onArchivo,
  error = "",
  exito = "",
}: {
  nombre: string;
  guia: string;
  cargada: boolean;
  habilitado: boolean;
  correccion?: Correccion;
  subiendo: boolean;
  error?: string;
  exito?: string;
  miniatura: string;
  onArchivo: (f?: File) => void;
}) {
  const camara = useRef<HTMLInputElement>(null);
  const galeria = useRef<HTMLInputElement>(null);
  const reemplazar = Boolean(correccion?.pendiente) || cargada || Boolean(error);
  const elegir = (e: React.ChangeEvent<HTMLInputElement>) => {
    onArchivo(e.target.files?.[0]);
    e.target.value = "";
  };
  return (
    <Card className={cn("overflow-hidden", correccion?.pendiente ? "border-warn/60" : habilitado && !cargada && "border-brand/40")}>
      <div className="relative aspect-[4/3] bg-surface-2">
        {miniatura ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={miniatura} alt={`Foto: ${nombre}`} className={cn("h-full w-full object-cover", correccion?.pendiente && "opacity-60")} />
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
        {correccion?.pendiente && (
          <span className="absolute right-2 top-2">
            <Badge tone="warn" dot>Por reemplazar</Badge>
          </span>
        )}
      </div>
      <div className="flex flex-col gap-2 p-3.5">
        <div>
          <p className="text-sm font-semibold text-ink">{nombre}</p>
          {!correccion?.pendiente && <p className="text-[12px] text-ink-3">{guia}</p>}
        </div>
        <NotaCorreccion c={correccion} />
        {habilitado && (
          <>
            {/* cámara trasera directa o galería: el candidato elige */}
            <input ref={camara} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="hidden" onChange={elegir} />
            <input ref={galeria} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={elegir} />
            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={() => camara.current?.click()} disabled={subiendo}
                className={cn(BOTON, "bg-brand text-brand-ink hover:brightness-110")}>
                {subiendo ? <Loader2 className="h-4 w-4 animate-spin" /> : reemplazar ? <RefreshCw className="h-4 w-4" /> : <Camera className="h-4 w-4" />}
                {subiendo ? "Revisando archivo..." : reemplazar ? "Reemplazar foto" : "Tomar foto"}
              </button>
              <button type="button" onClick={() => galeria.current?.click()} disabled={subiendo}
                className={cn(BOTON, "border border-border-soft bg-surface text-ink hover:border-brand")}>
                <ImageIcon className="h-4 w-4" /> Elegir de galería
              </button>
            </div>
          </>
        )}
        <Mensajes error={error} exito={exito} />
      </div>
    </Card>
  );
}

function DocumentoVehiculo({
  nombre,
  estado,
  motivo,
  correccion,
  cargado,
  habilitado,
  subiendo,
  onArchivo,
  error = "",
  exito = "",
}: {
  nombre: string;
  estado: string;
  motivo: string;
  correccion?: Correccion;
  cargado: boolean;
  habilitado: boolean;
  subiendo: boolean;
  error?: string;
  exito?: string;
  onArchivo: (f?: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const tono = estado === "Revisado" ? "good" : estado === "Requiere corrección" ? "bad" : cargado ? "warn" : "neutral";
  const reemplazar = Boolean(correccion?.pendiente) || cargado || Boolean(error);
  return (
    <Card className={cn("flex flex-col gap-2 p-3.5", correccion?.pendiente ? "border-warn/60" : habilitado && !cargado && "border-brand/40")}>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-semibold text-ink">
          <FileText className="h-4 w-4 text-ink-3" /> {nombre}
        </span>
        <Badge tone={correccion?.pendiente ? "warn" : tono} dot>{correccion?.pendiente ? "Por reemplazar" : estado}</Badge>
      </div>
      {correccion ? <NotaCorreccion c={correccion} /> : motivo && <p className="text-[12px] text-bad">Qué corregir: {motivo}</p>}
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
          <button type="button" onClick={() => input.current?.click()} disabled={subiendo}
            className={cn(BOTON, "bg-brand text-brand-ink hover:brightness-110")}>
            {subiendo ? <Loader2 className="h-4 w-4 animate-spin" /> : reemplazar ? <RefreshCw className="h-4 w-4" /> : <Upload className="h-4 w-4" />}
            {subiendo ? "Revisando archivo..." : reemplazar ? "Reemplazar documento" : "Subir foto o PDF"}
          </button>
        </>
      )}
      <Mensajes error={error} exito={exito} />
    </Card>
  );
}
