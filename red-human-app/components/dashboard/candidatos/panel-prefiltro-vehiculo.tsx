"use client";

/* «Prefiltro / Revisión de vehículo» (demo Grupo SEZA; v2 2026-09-30).

   Estado del prefiltro (Sin iniciar / En curso / Completado) y, APARTE, su resultado (Cumple perfil / Requiere
   revisión / No cumple) con cada motivo y la siguiente acción. Revisión del vehículo: 4 fotos + licencia, tarjeta
   de circulación y póliza (quedan en el expediente). RH aprueba (revisa también los documentos), pide corrección
   de ciertas fotos o documentos (con comentario; se reenvía la misma liga) o marca excepción (con motivo). Hasta
   que el vehículo esté aprobado o en excepción no se puede citar al candidato. Las decisiones son de RH (HITL). */

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, Camera, Check, CheckCircle2, Clock, Download, Eye, FileText, ShieldCheck, Upload, XCircle } from "lucide-react";
import { Badge, Button, Card, Eyebrow } from "@/components/ui";
import { Aviso } from "@/components/dashboard/subida";
import { LigaAcciones } from "@/components/dashboard/liga-acciones";
import { VisorArchivo, conDescarga, type ArchivoVisor } from "@/components/dashboard/visor-archivo";
import { cn } from "@/lib/utils";
import {
  aprobarPrefiltroReglas,
  decidirVehiculo,
  enviarLigaVehiculo,
  fetchFlujoVehiculo,
  generarLigaVehiculo,
  subirDocumentoVehiculoRH,
  subirFotoVehiculoRH,
  urlArchivo,
  urlDocumento,
  type FlujoVehiculo,
  type Resultado,
} from "@/lib/api";

const TONO_RESULTADO = { cumple: "good", revision: "warn", no_cumple: "bad", pendiente: "neutral" } as const;
const TONO_VEHICULO = { sin_liga: "neutral", pendiente: "neutral", por_revisar: "warn", correccion: "warn", aprobado: "good", excepcion: "human" } as const;
const TONO_DOC: Record<string, "good" | "warn" | "bad" | "neutral"> = { Revisado: "good", Recibido: "warn", "Requiere corrección": "bad", Pendiente: "neutral" };
const TONO_ESTADO_PREFILTRO: Record<string, "neutral" | "warn" | "brand"> = { "Sin iniciar": "neutral", "En curso": "warn", Completado: "brand" };

type Modal = null | "aprobar_prefiltro" | "correccion" | "excepcion";

export function PanelPrefiltroVehiculo({ codigo, puedeDecidir, onCambio }: { codigo: string; puedeDecidir: boolean; onCambio?: () => void }) {
  const [flujo, setFlujo] = useState<FlujoVehiculo | null>(null);
  const [aviso, setAviso] = useState<{ tono: "ok" | "error" | "warn"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState("");
  const [modal, setModal] = useState<Modal>(null);
  const [texto, setTexto] = useState("");
  const [lados, setLados] = useState<string[]>([]);
  const [visor, setVisor] = useState<ArchivoVisor | null>(null);  // fotos y documentos se ven SOBRE la ficha
  const [enviosLiga, setEnviosLiga] = useState<NonNullable<FlujoVehiculo["envio"]>["envios"]>(undefined);  // estado por canal

  const cargar = useCallback(async () => {
    const r = await fetchFlujoVehiculo(codigo);
    if (r) setFlujo(r);
  }, [codigo]);
  useEffect(() => {
    cargar();
  }, [cargar]);

  async function ejecutar(clave: string, accion: () => Promise<Resultado<FlujoVehiculo>>, exito: string) {
    setOcupado(clave);
    setAviso(null);
    const r = await accion();
    setOcupado("");
    if (!r.ok) return setAviso({ tono: "error", texto: r.error });
    setFlujo(r.data);
    if (r.data.envio?.envios) setEnviosLiga(r.data.envio.envios);
    setModal(null);
    setTexto("");
    setLados([]);
    const whatsapp = r.data.envio?.whatsapp;
    setAviso(
      whatsapp && !whatsapp.enviado
        ? { tono: "warn", texto: `${exito} El mensaje no salió: copia la liga y compártela.` }
        : { tono: "ok", texto: exito },
    );
    onCambio?.();
  }

  if (!flujo) return <p className="text-sm text-ink-3">Cargando prefiltro…</p>;
  const pf = flujo.prefiltro;
  const vh = flujo.vehiculo;
  if (!pf) return <p className="text-sm text-ink-3">La vacante de esta postulación no usa prefiltro por reglas.</p>;

  const puedeAprobarPrefiltro = puedeDecidir && pf.completo && (pf.resultado === "revision" || pf.resultado === "no_cumple");
  const completo = vh?.completo ?? false;
  const hayAlgo = Boolean(vh && (vh.fotos.some((f) => f.cargada) || vh.documentos.some((d) => d.cargado)));

  return (
    <div className="flex flex-col gap-5">
      {visor && <VisorArchivo archivo={visor} onClose={() => setVisor(null)} />}
      {aviso && (
        <Aviso tono={aviso.tono} onCerrar={() => setAviso(null)}>
          {aviso.texto}
        </Aviso>
      )}

      {/* ---------- Siguiente acción (lo primero que ve RH) ---------- */}
      <Card className="flex items-start gap-3 border-brand/30 bg-brand-soft/30 p-4">
        <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-brand">Siguiente acción</p>
          <p className="text-sm font-medium text-ink">{pf.siguienteAccion}</p>
        </div>
      </Card>

      {/* ---------- Resultado del prefiltro ---------- */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <Eyebrow>Prefiltro</Eyebrow>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {pf.estadoPrefiltro && (
                <Badge tone={TONO_ESTADO_PREFILTRO[pf.estadoPrefiltro] ?? "neutral"}>{pf.estadoPrefiltro}</Badge>
              )}
              {pf.completo && (
                <Badge tone={TONO_RESULTADO[pf.resultado]} dot>
                  Resultado: {pf.etiqueta}
                </Badge>
              )}
              {pf.canal && <span className="text-[12px] text-ink-3">vía {pf.canal === "web" ? "formulario web" : "chat"}</span>}
              {!pf.completo && pf.total ? <span className="text-[12px] text-ink-3">{pf.respondidas}/{pf.total} respuestas</span> : null}
            </div>
          </div>
          {puedeAprobarPrefiltro && (
            <Button size="sm" variant="outline" onClick={() => setModal("aprobar_prefiltro")}>
              <ShieldCheck className="h-4 w-4" /> Aprobar prefiltro…
            </Button>
          )}
        </div>

        {pf.completo && pf.motivos.length === 0 && pf.resultado === "cumple" && (
          <p className="mt-3 flex items-center gap-1.5 text-sm text-good">
            <CheckCircle2 className="h-4 w-4" /> Cumple todas las reglas de la vacante.
          </p>
        )}
        {pf.motivos.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1.5">
            {pf.motivos.map((m, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                {m.efecto === "no_cumple" ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-bad" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />}
                <span>
                  <span className="text-ink">{m.motivo}</span>
                  <span className="block text-[12px] text-ink-3">
                    {m.efecto === "no_cumple" ? "Descarta" : "Requiere revisión"} · {m.pregunta}
                    {m.respuesta ? ` → «${m.respuesta}»` : ""}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
        {pf.aprobadoPorRH && (
          <p className="mt-3 rounded-xl bg-surface-2 p-3 text-[13px] text-ink-2">
            Aprobado por <b>{pf.aprobadoPorRH.usuario}</b> el {new Date(pf.aprobadoPorRH.fecha).toLocaleString("es-MX")} — {pf.aprobadoPorRH.motivo}
          </p>
        )}

        {Boolean(pf.respuestas?.length) && (
          <details className="mt-4 rounded-xl border border-border-soft">
            <summary className="cursor-pointer px-3.5 py-2.5 text-sm font-medium text-ink-2">Ver respuestas ({pf.respuestas!.length})</summary>
            <div className="scroll-x border-t border-border-faint">
              <table className="w-full text-[13px]">
                <tbody>
                  {pf.respuestas!.map((r) => (
                    <tr key={r.id} className="border-b border-border-faint last:border-0">
                      <td className="whitespace-normal px-3.5 py-2 text-ink-3">{r.pregunta}</td>
                      <td className="px-3.5 py-2 font-medium text-ink">{r.respuesta || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </Card>

      {/* ---------- Revisión de vehículo ---------- */}
      {vh && (
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <Eyebrow>Revisión de vehículo</Eyebrow>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge tone={TONO_VEHICULO[vh.estado]} dot>
                  {vh.etiqueta}
                </Badge>
                {vh.decididoPor && (
                  <span className="text-[12px] text-ink-3">
                    por {vh.decididoPor}
                    {vh.decididoEn ? ` · ${new Date(vh.decididoEn).toLocaleString("es-MX")}` : ""}
                  </span>
                )}
              </div>
            </div>
          </div>

          {!vh.puedeCitar && (
            <p className="mt-3 flex items-start gap-2 rounded-xl bg-warn-soft/50 p-3 text-[13px] text-ink-2">
              <Clock className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
              {vh.motivoBloqueo}
            </p>
          )}
          {vh.comentario && (vh.estado === "correccion" || vh.estado === "excepcion") && (
            <p className="mt-3 text-[13px] text-ink-2">
              <b>{vh.estado === "correccion" ? "Corrección pedida:" : "Motivo de la excepción:"}</b> {vh.comentario}
            </p>
          )}

          <LigaAcciones
            className="mt-3"
            etiqueta="Liga del candidato (fotos y documentos)"
            liga={vh.liga}
            generando={ocupado === "generar"}
            onGenerar={puedeDecidir ? () => ejecutar("generar", () => generarLigaVehiculo(codigo), "Liga generada: ábrela, cópiala o envíala.") : undefined}
            enviando={ocupado === "liga"}
            ultimoEnvio={vh.ligaEnviadaEn ? { enviado: true, fecha: vh.ligaEnviadaEn } : null}
            envios={enviosLiga}
            onEnviar={puedeDecidir && vh.estado !== "aprobado" && vh.estado !== "excepcion"
              ? () => ejecutar("liga", () => enviarLigaVehiculo(codigo), "Liga del vehículo enviada.") : undefined}
          />

          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {vh.fotos.map((f) => (
              <figure key={f.lado} className={cn("overflow-hidden rounded-xl border", vh.ladosCorregir?.includes(f.lado) && vh.estado === "correccion" ? "border-warn" : "border-border-soft")}>
                <div className="aspect-[4/3] bg-surface-2">
                  {f.cargada ? (
                    <button type="button" className="block h-full w-full" title="Ver en tamaño completo"
                      onClick={() => setVisor({ url: urlArchivo(f.url), urlDescarga: conDescarga(urlArchivo(f.url)), nombre: `vehiculo-${f.lado}.jpg`, titulo: `Vehículo · ${f.nombre}` })}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={urlArchivo(f.url)} alt={`Vehículo: ${f.nombre}`} className="h-full w-full object-cover" />
                    </button>
                  ) : (
                    <div className="grid h-full place-items-center text-ink-3">
                      <Camera className="h-7 w-7" />
                    </div>
                  )}
                </div>
                <figcaption className="flex items-center justify-between gap-1 px-2.5 py-1.5 text-[12px]">
                  <span>
                    <span className="font-medium text-ink">{f.nombre}</span>
                    <span className="block text-ink-3">{f.cargada ? "Recibida" : "Pendiente"}</span>
                  </span>
                  {puedeDecidir && (
                    <SubirArchivo soloImagen reemplazar={f.cargada} ocupado={ocupado === `foto-${f.lado}`} titulo={`Subir foto: ${f.nombre}`}
                      onArchivo={(a) => ejecutar(`foto-${f.lado}`, () => subirFotoVehiculoRH(codigo, f.lado, a), `Foto «${f.nombre}» cargada.`)} />
                  )}
                </figcaption>
              </figure>
            ))}
          </div>

          <p className="mt-4 text-[12px] font-semibold uppercase tracking-wide text-ink-3">Documentos del vehículo</p>
          <ul className="mt-2 flex flex-col gap-1.5">
            {vh.documentos.map((d) => (
              <li key={d.clave} className={cn("flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2 text-[13px]",
                vh.estado === "correccion" && vh.ladosCorregir?.includes(d.clave) ? "border-warn" : "border-border-soft")}>
                <span className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-ink-3" />
                  <span className="text-ink">{d.tipo}</span>
                  {d.estadoSimple === "Requiere corrección" && d.notas && <span className="text-[12px] text-bad">· {d.notas}</span>}
                </span>
                <span className="flex items-center gap-1.5">
                  <Badge tone={TONO_DOC[d.estadoSimple] ?? "neutral"}>{d.estadoSimple}</Badge>
                  {d.cargado && vh.expedienteId && (
                    <>
                      <button type="button" className="inline-flex h-7 items-center gap-1 rounded-lg px-1.5 text-[11px] font-semibold text-brand hover:bg-brand-soft"
                        onClick={() => setVisor({ url: urlDocumento(vh.expedienteId!, d.tipo), nombre: d.tipo, titulo: `Vehículo · ${d.tipo}` })}>
                        <Eye className="h-3.5 w-3.5" /> Ver
                      </button>
                      <a href={conDescarga(urlDocumento(vh.expedienteId, d.tipo))} download className="inline-flex h-7 items-center gap-1 rounded-lg px-1.5 text-[11px] font-semibold text-brand hover:bg-brand-soft">
                        <Download className="h-3.5 w-3.5" /> Descargar
                      </a>
                    </>
                  )}
                  {puedeDecidir && (
                    <SubirArchivo reemplazar={d.cargado} ocupado={ocupado === `doc-${d.clave}`} titulo={`Subir ${d.tipo}`}
                      onArchivo={(a) => ejecutar(`doc-${d.clave}`, () => subirDocumentoVehiculoRH(codigo, d.clave, a), `«${d.tipo}» cargado.`)} />
                  )}
                </span>
              </li>
            ))}
          </ul>

          {puedeDecidir && vh.estado !== "sin_liga" && (
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={Boolean(ocupado) || !completo || vh.estado === "aprobado"}
                title={completo ? "Aprueba las fotos y marca como revisados la licencia, la tarjeta y la póliza" : "Faltan fotos o documentos"}
                onClick={() => ejecutar("aprobar", () => decidirVehiculo(codigo, "aprobar"), "Vehículo aprobado (fotos y documentos revisados): ya se puede citar al candidato.")}
              >
                <Check className="h-4 w-4" /> Aprobar vehículo
              </Button>
              <Button size="sm" variant="outline" disabled={Boolean(ocupado) || !hayAlgo} onClick={() => setModal("correccion")}>
                Pedir corrección…
              </Button>
              <Button size="sm" variant="ghost" disabled={Boolean(ocupado) || vh.estado === "excepcion"} onClick={() => setModal("excepcion")}>
                Marcar excepción…
              </Button>
            </div>
          )}

          {vh.historial.length > 0 && (
            <details className="mt-4">
              <summary className="cursor-pointer text-[13px] font-medium text-ink-3">Historial ({vh.historial.length})</summary>
              <ul className="mt-2 flex flex-col gap-1">
                {vh.historial.map((h, i) => (
                  <li key={i} className="text-[12px] text-ink-2">
                    <span className="text-ink-3">{new Date(h.fecha).toLocaleString("es-MX")}</span> · {h.texto} <span className="text-ink-3">({h.usuario})</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </Card>
      )}

      {/* ---------- Diálogos con motivo (toda decisión queda con nombre en bitácora) ---------- */}
      {modal && (
        <div className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 sm:place-items-center sm:p-4" onClick={() => setModal(null)}>
          <div className="w-full rounded-t-2xl bg-surface p-5 shadow-xl sm:max-w-md sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-display text-lg font-bold">
              {modal === "aprobar_prefiltro" ? "Aprobar prefiltro" : modal === "correccion" ? "Pedir corrección" : "Marcar excepción"}
            </h3>
            <p className="mt-1 text-[13px] text-ink-3">
              {modal === "aprobar_prefiltro"
                ? "El prefiltro quedará como «Cumple perfil» y se enviará la liga del vehículo (fotos y documentos)."
                : modal === "correccion"
                  ? "Se le reenvía la misma liga con tu comentario; solo podrá volver a subir lo que marques."
                  : "El vehículo queda aprobado por excepción y se podrá citar al candidato."}
            </p>
            {modal === "correccion" && vh && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                {[...vh.fotos.map((f) => ({ clave: f.lado, nombre: `Foto: ${f.nombre}` })), ...vh.documentos.map((d) => ({ clave: d.clave, nombre: d.tipo }))].map((o) => (
                  <label key={o.clave} className="flex min-h-11 items-center gap-2 rounded-xl border border-border-soft px-3 text-sm">
                    <input
                      type="checkbox"
                      checked={lados.includes(o.clave)}
                      onChange={(e) => setLados((l) => (e.target.checked ? [...l, o.clave] : l.filter((x) => x !== o.clave)))}
                      className="h-4 w-4 accent-[var(--brand)]"
                    />
                    {o.nombre}
                  </label>
                ))}
              </div>
            )}
            <textarea
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              rows={3}
              placeholder={modal === "correccion" ? "¿Qué debe corregir? Ej. la foto de atrás salió borrosa" : "Motivo (obligatorio)"}
              className="mt-3 w-full rounded-xl border border-border-soft bg-surface px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setModal(null)}>
                Cancelar
              </Button>
              <Button
                size="sm"
                disabled={!texto.trim() || Boolean(ocupado) || (modal === "correccion" && lados.length === 0)}
                onClick={() =>
                  modal === "aprobar_prefiltro"
                    ? ejecutar("prefiltro", () => aprobarPrefiltroReglas(codigo, texto.trim()), "Prefiltro aprobado; se envió la liga del vehículo.")
                    : modal === "correccion"
                      ? ejecutar("correccion", () => decidirVehiculo(codigo, "correccion", texto.trim(), lados), "Corrección solicitada; se reenvió la liga.")
                      : ejecutar("excepcion", () => decidirVehiculo(codigo, "excepcion", texto.trim()), "Vehículo aprobado por excepción.")
                }
              >
                Confirmar
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Captura interna: RH sube el archivo desde la ficha (alimenta la misma revisión que la liga del candidato). */
function SubirArchivo({ onArchivo, ocupado, titulo, soloImagen = false, reemplazar = false }: { onArchivo: (a: File) => void; ocupado: boolean; titulo: string; soloImagen?: boolean; reemplazar?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <input ref={ref} type="file" className="hidden" accept={soloImagen ? "image/jpeg,image/png,image/webp" : "image/jpeg,image/png,image/webp,application/pdf"}
        onChange={(e) => { const a = e.target.files?.[0]; if (a) onArchivo(a); e.target.value = ""; }} />
      <button type="button" title={titulo} disabled={ocupado} onClick={() => ref.current?.click()}
        className="inline-flex h-7 items-center gap-1 rounded-lg px-1.5 text-[11px] font-semibold text-brand hover:bg-brand-soft disabled:opacity-50">
        <Upload className="h-3.5 w-3.5" /> {ocupado ? "…" : reemplazar ? "Reemplazar" : "Subir"}
      </button>
    </>
  );
}
