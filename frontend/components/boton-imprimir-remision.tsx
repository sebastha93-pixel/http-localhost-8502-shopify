"use client";

/**
 * Botón "Imprimir" de una remisión — la salida MANUAL cuando el agente falla.
 *
 * Baja el PDF con el token y abre el diálogo de impresión del navegador, así
 * la hoja sale por cualquier impresora que tenga el PC (la RICOH con su driver
 * de Windows, otra láser, o Guardar como PDF). Es a propósito el camino de las
 * PERSONAS y va por PDF: el navegador y el driver saben rasterizar. El agente
 * usa otro endpoint (/pwg) porque la RICOH por red no interpreta PDF.
 *
 * Imprime desde un iframe oculto para no sacar al usuario de la página. Si el
 * navegador no deja disparar print() ahí (pasa en algunos Safari), abre el PDF
 * en una pestaña para que quede a un Cmd/Ctrl+P — nunca deja al usuario sin
 * salida.
 */
import { useCallback, useState } from "react";
import { API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { Printer, Loader2 } from "lucide-react";

/** Segundos que se deja vivo el iframe: si se limpia antes, Chrome cierra el
 *  diálogo de impresión a medias. */
const VIDA_IFRAME_MS = 120_000;

export function useImprimirRemision() {
  const [imprimiendo, setImprimiendo] = useState<string | null>(null);
  const [error, setError] = useState("");

  const imprimir = useCallback(async (remisionId: string) => {
    setError("");
    setImprimiendo(remisionId);
    let url = "";
    try {
      const r = await fetch(
        `${API_BASE}/api/produccion/remisiones/${remisionId}/pdf`,
        { headers: { Authorization: `Bearer ${getToken()}` }, cache: "no-store" },
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      url = URL.createObjectURL(await r.blob());

      const marco = document.createElement("iframe");
      marco.style.position = "fixed";
      marco.style.width = "0";
      marco.style.height = "0";
      marco.style.border = "0";
      marco.style.right = "0";
      marco.style.bottom = "0";
      marco.src = url;
      marco.onload = () => {
        try {
          marco.contentWindow?.focus();
          marco.contentWindow?.print();
        } catch {
          window.open(url, "_blank", "noopener,noreferrer");
        }
      };
      document.body.appendChild(marco);
      window.setTimeout(() => {
        marco.remove();
        URL.revokeObjectURL(url);
      }, VIDA_IFRAME_MS);
    } catch (e) {
      if (url) {
        // Se pudo bajar el PDF pero no imprimirlo: al menos que lo vea.
        window.open(url, "_blank", "noopener,noreferrer");
      } else {
        setError(e instanceof Error ? e.message : "no se pudo generar el PDF");
      }
    } finally {
      setImprimiendo(null);
    }
  }, []);

  return { imprimir, imprimiendo, error };
}

export function BotonImprimirRemision({
  remisionId, etiqueta = "Imprimir", compacto = false, titulo,
}: {
  remisionId: string;
  etiqueta?: string;
  compacto?: boolean;
  titulo?: string;
}) {
  const { imprimir, imprimiendo, error } = useImprimirRemision();
  const cargando = imprimiendo === remisionId;

  const clases = compacto
    ? "inline-flex items-center gap-1 rounded-sm border border-border bg-white px-2 py-1 text-[0.62rem] font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud disabled:opacity-40"
    : "inline-flex items-center gap-1.5 rounded-sm border border-border bg-white px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud disabled:opacity-40";

  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <button
        type="button"
        onClick={() => imprimir(remisionId)}
        disabled={cargando}
        className={clases}
        title={titulo || "Bajar el PDF y abrir el diálogo de impresión"}
      >
        {cargando
          ? <Loader2 className={compacto ? "h-3 w-3 animate-spin" : "h-3.5 w-3.5 animate-spin"} />
          : <Printer className={compacto ? "h-3 w-3" : "h-3.5 w-3.5"} />}
        {etiqueta}
      </button>
      {error && (
        <span className="text-[0.6rem] text-rust">{error}</span>
      )}
    </span>
  );
}
