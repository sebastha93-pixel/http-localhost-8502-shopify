"use client";

import { useEffect, useState } from "react";
import { formatear } from "@/lib/pos/dinero";
import type { Ticket } from "@/lib/pos/api";

/**
 * Venta cerrada.
 *
 * El auto-avance importa: sin él la cajera tiene que tocar la pantalla entre
 * clientas, y ese toque son dos segundos de los treinta.
 *
 * El estado fiscal se muestra como lo que es — «emitiendo» — y no se espera.
 * La clienta ya se fue con su prenda y su ticket (ADR-002).
 */
export function TicketCerrado({ ticket, onNueva }: { ticket: Ticket; onNueva: () => void }) {
  const [restan, setRestan] = useState(8);

  useEffect(() => {
    if (restan <= 0) {
      onNueva();
      return;
    }
    const t = setTimeout(() => setRestan((r) => r - 1), 1000);
    return () => clearTimeout(t);
  }, [restan, onNueva]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-8 text-center">
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
        <div>🧾 Ticket impreso</div>
        <div>
          {ticket.estado_fiscal === "emitido"
            ? "✅ Factura electrónica emitida"
            : "⏳ Factura electrónica: emitiendo…"}
        </div>
        {ticket.duplicada && <div>↺ Esta venta ya estaba registrada</div>}
      </div>

      <button
        onClick={onNueva}
        className="mt-8 bg-[var(--pos-accent)] px-10 py-3.5 titular text-[13.5px] font-semibold tracking-[0.12em] text-white"
      >
        NUEVA VENTA · Enter
      </button>
      <p className="mt-3 tabular text-[10.5px] text-[var(--pos-500)]">
        Vuelve solo en {restan} s
      </p>
    </div>
  );
}
