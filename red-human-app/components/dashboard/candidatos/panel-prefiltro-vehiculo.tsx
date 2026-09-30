"use client";

/* «Prefiltro / Revisión de vehículo» (demo Grupo SEZA, 2026-09-29).

   Resultado del prefiltro por reglas (Cumple perfil / Requiere revisión / No cumple) con cada motivo y la
   siguiente acción, y la revisión de las fotos del vehículo: RH aprueba, pide corrección de ciertos lados
   (con comentario; se reenvía la misma liga) o marca excepción (con motivo). Hasta que el vehículo esté
   aprobado o en excepción no se puede citar al candidato. Todas las decisiones son de RH (HITL). */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, Camera, Check, CheckCircle2, Clock, Send, ShieldCheck, XCircle } from "lucide-react";
import { Badge, Button, Card, Eyebrow } from "@/components/ui";
import { Aviso, BotonCopiar } from "@/components/dashboard/subida";
import { cn } from "@/lib/utils";
import {
  aprobarPrefiltroReglas,
  decidirVehiculo,
  enviarLigaVehiculo,
  fetchFlujoVehiculo,
  urlArchivo,
  type FlujoVehiculo,
  type Resultado,
} from "@/lib/api";

const TONO_RESULTADO = { cumple: "good", revision: "warn", no_cumple: "bad", pendiente: "neutral" } as const;
const TONO_VEHICULO = { sin_liga: "neutral", pendiente: "neutral", por_revisar: "warn", correccion: "warn", aprobado: "good", excepcion: "human" } as const;

type Modal = null | "aprobar_prefiltro" | "correccion" | "excepcion";

export function PanelPrefiltroVehiculo({ codigo, puedeDecidir, onCambio }: { codigo: string; puedeDecidir: boolean; onCambio?: () => void }) {
  const [flujo, setFlujo] = useState<FlujoVehiculo | null>(null);
  const [aviso, setAviso] = useState<{ tono: "ok" | "error" | "warn"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState("");
  const [modal, setModal] = useState<Modal>(null);
  const [texto, setTexto] = useState("");
  const [lados, setLados] = useState<string[]>([]);

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
    setModal(null);
    setTexto("");
    setLados([]);
    const whatsapp = r.data.envio?.whatsapp;
    setAviso(
      whatsapp && !whatsapp.enviado
        ? { tono: "warn", texto: `${exito} El WhatsApp no salió (sin teléfono o fuera de la ventana de 24 h): copia la liga y compártela.` }
        : { tono: "ok", texto: exito },
    );
    onCambio?.();
  }

  if (!flujo) return <p className="text-sm text-ink-3">Cargando prefiltro…</p>;
  const pf = flujo.prefiltro;
  const vh = flujo.vehiculo;
  if (!pf) return <p className="text-sm text-ink-3">La vacante de esta postulación no usa prefiltro por reglas.</p>;

  const puedeAprobarPrefiltro = puedeDecidir && pf.completo && (pf.resultado === "revision" || pf.resultado === "no_cumple");
  const fotosCompletas = vh?.fotos.every((f) => f.cargada) ?? false;

  return (
    <div className="flex flex-col gap-5">
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
              <Badge tone={TONO_RESULTADO[pf.resultado]} dot>
                {pf.etiqueta}
              </Badge>
              {pf.canal && <span className="text-[12px] text-ink-3">vía {pf.canal === "web" ? "formulario web" : "WhatsApp"}</span>}
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
            {puedeDecidir && pf.resultado === "cumple" && vh.estado !== "aprobado" && vh.estado !== "excepcion" && (
              <Button
                size="sm"
                variant="outline"
                disabled={Boolean(ocupado)}
                onClick={() => ejecutar("liga", () => enviarLigaVehiculo(codigo), "Liga de fotos enviada.")}
              >
                <Send className="h-4 w-4" /> {vh.estado === "sin_liga" ? "Enviar liga de fotos" : "Reenviar liga"}
              </Button>
            )}
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

          {vh.liga && (
            <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-surface-2 px-3 py-2">
              <span className="min-w-0 flex-1 truncate text-[12px] text-ink-3">{vh.liga}</span>
              <BotonCopiar texto={vh.liga} etiqueta="Copiar liga" />
            </div>
          )}

          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {vh.fotos.map((f) => (
              <figure key={f.lado} className={cn("overflow-hidden rounded-xl border", vh.ladosCorregir?.includes(f.lado) && vh.estado === "correccion" ? "border-warn" : "border-border-soft")}>
                <div className="aspect-[4/3] bg-surface-2">
                  {f.cargada ? (
                    <a href={urlArchivo(f.url)} target="_blank" rel="noreferrer" title="Abrir en tamaño completo">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={urlArchivo(f.url)} alt={`Vehículo: ${f.nombre}`} className="h-full w-full object-cover" />
                    </a>
                  ) : (
                    <div className="grid h-full place-items-center text-ink-3">
                      <Camera className="h-7 w-7" />
                    </div>
                  )}
                </div>
                <figcaption className="px-2.5 py-1.5 text-[12px]">
                  <span className="font-medium text-ink">{f.nombre}</span>
                  <span className="block text-ink-3">{f.cargada ? "Recibida" : "Pendiente"}</span>
                </figcaption>
              </figure>
            ))}
          </div>

          {puedeDecidir && vh.estado !== "sin_liga" && (
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={Boolean(ocupado) || !fotosCompletas || vh.estado === "aprobado"}
                onClick={() => ejecutar("aprobar", () => decidirVehiculo(codigo, "aprobar"), "Vehículo aprobado: ya se puede citar al candidato.")}
              >
                <Check className="h-4 w-4" /> Aprobar vehículo
              </Button>
              <Button size="sm" variant="outline" disabled={Boolean(ocupado) || !vh.fotos.some((f) => f.cargada)} onClick={() => setModal("correccion")}>
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
              {modal === "aprobar_prefiltro" ? "Aprobar prefiltro" : modal === "correccion" ? "Pedir corrección de fotos" : "Marcar excepción"}
            </h3>
            <p className="mt-1 text-[13px] text-ink-3">
              {modal === "aprobar_prefiltro"
                ? "El prefiltro quedará como «Cumple perfil» y se enviará la liga de fotos del vehículo."
                : modal === "correccion"
                  ? "Se le reenvía la misma liga con tu comentario; solo podrá volver a subir los lados marcados."
                  : "El vehículo queda aprobado por excepción y se podrá citar al candidato."}
            </p>
            {modal === "correccion" && vh && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                {vh.fotos.map((f) => (
                  <label key={f.lado} className="flex min-h-11 items-center gap-2 rounded-xl border border-border-soft px-3 text-sm">
                    <input
                      type="checkbox"
                      checked={lados.includes(f.lado)}
                      onChange={(e) => setLados((l) => (e.target.checked ? [...l, f.lado] : l.filter((x) => x !== f.lado)))}
                      className="h-4 w-4 accent-[var(--brand)]"
                    />
                    {f.nombre}
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
                    ? ejecutar("prefiltro", () => aprobarPrefiltroReglas(codigo, texto.trim()), "Prefiltro aprobado; se envió la liga de fotos.")
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
