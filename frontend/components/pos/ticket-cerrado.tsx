"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { formatear } from "@/lib/pos/dinero";
import { pedirTirilla, type Ticket, type Tirilla as DatosTirilla } from "@/lib/pos/api";
import { Tirilla } from "@/components/pos/tirilla";

/**
 * Venta cerrada.
 *
 * El auto-avance importa: sin él la cajera tiene que tocar la pantalla entre
 * clientas, y ese toque son dos segundos de los treinta.
 *
 * El estado fiscal se muestra como lo que es — «emitiendo» — y no se espera.
 * La clienta ya se fue con su prenda y su tirilla (ADR-002).
 *
 * LA TIRILLA SALE SOLA, y el auto-avance NO CORRE hasta que salga. Antes esta
 * pantalla decía «🧾 Ticket impreso» sin imprimir nada: la cajera lo leía,
 * daba la venta por terminada y la clienta se iba sin papel. Ahora se pide al
 * servidor y se manda a imprimir; si falla, se dice que falló y queda el botón.
 */
export function TicketCerrado({ ticket, onNueva }: { ticket: Ticket; onNueva: () => void }) {
  const [restan, setRestan] = useState(8);
  const [tirilla, setTirilla] = useState<DatosTirilla | null>(null);
  const [errorImpresion, setErrorImpresion] = useState<string | null>(null);
  const [imprimiendo, setImprimiendo] = useState(true);
  const yaImprimio = useRef(false);

  const imprimir = useCallback(async () => {
    setImprimiendo(true);
    setErrorImpresion(null);
    try {
      const d = await pedirTirilla(ticket.venta_id);
      setTirilla(d);
      // Una pausa para que React pinte la tirilla antes de abrir el diálogo:
      // sin ella el navegador manda una hoja en blanco.
      //
      // CON `setTimeout`, NO CON `requestAnimationFrame`. Lo tuve con rAF y
      // no dispara en una pestaña oculta: si la cajera cambiaba de app justo
      // al cerrar la venta, la tirilla no salía Y la pantalla se quedaba en
      // «Imprimiendo…» para siempre, bloqueando el paso a la venta siguiente.
      // Un `setTimeout` corre igual en segundo plano.
      await new Promise((r) => setTimeout(r, 60));
      window.print();
    } catch (e) {
      setErrorImpresion(
        e instanceof Error ? e.message : "No se pudo preparar la tirilla.",
      );
    } finally {
      setImprimiendo(false);
    }
  }, [ticket.venta_id]);

  useEffect(() => {
    if (yaImprimio.current) return;
    yaImprimio.current = true;
    imprimir();
  }, [imprimir]);

  useEffect(() => {
    // El reloj arranca cuando la impresión terminó. Si se pasa a la venta
    // siguiente mientras el diálogo está abierto, se imprime a medias o nada.
    if (imprimiendo) return;
    if (restan <= 0) {
      onNueva();
      return;
    }
    const t = setTimeout(() => setRestan((r) => r - 1), 1000);
    return () => clearTimeout(t);
  }, [restan, onNueva, imprimiendo]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-8 text-center">
      {/* Fuera de pantalla, no `display:none`: lo oculto no se imprime. */}
      {tirilla && (
        <div className="absolute -left-[9999px] top-0" aria-hidden>
          <Tirilla datos={tirilla} />
        </div>
      )}

      <div aria-hidden className="text-5xl">✅</div>
      <h1 className="mt-4 titular text-2xl tracking-wide">VENTA CERRADA</h1>
      <p className="mt-1 tabular text-sm text-[var(--pos-700)]">{ticket.numero}</p>

      <div className="mt-6 tabular text-[40px] font-semibold tabular-nums">
        {formatear(ticket.total_centavos)}
      </div>

      {ticket.vuelto_centavos > 0 && (
        <div className="mt-4">
          <div className="titular text-[11px] tracking-[0.14em] text-[var(--pos-600)]">
            VUELTO
          </div>
          <div className="tabular text-[34px] font-semibold tabular-nums text-[var(--pos-800)]">
            {formatear(ticket.vuelto_centavos)}
          </div>
        </div>
      )}

      <div className="mt-6 space-y-1 tabular text-[11.5px] text-[var(--pos-600)]">
        <div>
          {imprimiendo
            ? "🧾 Imprimiendo tirilla…"
            : errorImpresion
              ? "⚠️ La tirilla no salió"
              : "🧾 Tirilla impresa"}
        </div>
        <div>
          {ticket.estado_fiscal === "emitido"
            ? "✅ Factura electrónica emitida"
            : "⏳ Factura electrónica: emitiendo…"}
        </div>
        {ticket.duplicada && <div>↺ Esta venta ya estaba registrada</div>}
      </div>

      {errorImpresion && (
        <p className="mt-3 max-w-[380px] border border-[var(--pos-800)] bg-[var(--pos-800)]/10 p-2.5 text-[12px] leading-relaxed text-[var(--pos-900)]">
          {errorImpresion} La venta SÍ quedó registrada — esto es sólo el papel.
        </p>
      )}

      <div className="mt-8 flex gap-3">
        <button
          onClick={imprimir}
          disabled={imprimiendo}
          className="border border-[var(--pos-divider)] px-6 py-3.5 titular text-[13.5px] tracking-[0.12em] text-[var(--pos-700)] disabled:opacity-50"
        >
          {errorImpresion ? "REINTENTAR" : "REIMPRIMIR"}
        </button>
        <button
          onClick={onNueva}
          className="bg-[var(--pos-accent)] px-10 py-3.5 titular text-[13.5px] font-semibold tracking-[0.12em] text-white"
        >
          NUEVA VENTA · Enter
        </button>
      </div>
      {!imprimiendo && (
        <p className="mt-3 tabular text-[10.5px] text-[var(--pos-500)]">
          Vuelve solo en {restan} s
        </p>
      )}
    </div>
  );
}
