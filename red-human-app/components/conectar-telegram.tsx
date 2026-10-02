"use client";

import { MessageCircle } from "lucide-react";
import { BOT_TELEGRAM_DEFAULT, ligaTelegramInicio, ligaTelegramWeb } from "@/lib/api";

/** Handoff OPCIONAL (2026-10-01): al terminar la ruta web, Telegram solo para recibir los avances. El enlace nativo
 *  (`tg://resolve`) abre el bot con `/start <token>` y el bot únicamente confirma la postulación. */
export function ConectarTelegram({ token, bot, liga, ligaWeb }: { token?: string; bot?: string; liga?: string; ligaWeb?: string }) {
  const nativa = liga || (token ? ligaTelegramInicio(token, bot || BOT_TELEGRAM_DEFAULT) : "");
  const web = ligaWeb || (token ? ligaTelegramWeb(token, bot || BOT_TELEGRAM_DEFAULT) : "");
  if (!nativa) return null;
  return (
    <div className="flex w-full max-w-md flex-col items-center gap-3 rounded-2xl border border-[#229ED9]/30 bg-[#229ED9]/10 p-5 text-center">
      <span className="grid h-10 w-10 place-items-center rounded-xl bg-[#229ED9]/15 text-[#229ED9]">
        <MessageCircle className="h-5 w-5" />
      </span>
      <p className="text-sm font-semibold text-ink">Recibe por Telegram los avances de tu postulación</p>
      <a href={nativa}
        className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#229ED9] px-5 text-sm font-semibold text-white transition hover:brightness-105">
        Conectar Telegram
      </a>
      <p className="text-[12px] text-ink-3">
        Es opcional. ¿No se abrió Telegram? <a href={web} target="_blank" rel="noreferrer" className="font-semibold text-brand hover:underline">Ábrelo aquí</a>
      </p>
    </div>
  );
}
