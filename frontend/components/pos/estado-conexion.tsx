"use client";

/**
 * Si hay red, y cuántas ventas están esperando.
 *
 * SÓLO APARECE CUANDO HAY ALGO QUE DECIR. Un indicador verde permanente se
 * vuelve parte del fondo en dos días y deja de leerse; cuando por fin importe,
 * nadie lo va a mirar. Con todo en orden, esto no se ve.
 *
 * NO USA `navigator.onLine` COMO VERDAD. Dice si hay una interfaz de red
 * levantada, no si el servidor contesta: el wifi de un centro comercial con el
 * portal caído da `true` y no llega nada. Lo que se muestra es el resultado de
 * los intentos reales.
 */
import { useEffect, useState } from "react";
import { alCambiar, sincronizar, type EstadoCola } from "@/lib/pos/sincronizacion";

export function EstadoConexion() {
  const [cola, setCola] = useState<EstadoCola | null>(null);

  useEffect(() => alCambiar(setCola), []);

  if (!cola || (cola.enCola === 0 && cola.rechazadas === 0)) return null;

  const hayRechazadas = cola.rechazadas > 0;

  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-center gap-2 border px-3 py-1.5 text-[12px] ${
        hayRechazadas
          ? "border-[var(--pos-accent)] bg-[var(--pos-accent)]/10 text-[var(--pos-900)]"
          : "border-[var(--pos-800)]/30 bg-[var(--pos-800)]/10 text-[var(--pos-900)]"
      }`}
    >
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${
          hayRechazadas
            ? "bg-[var(--pos-accent)]"
            : cola.sincronizando
              ? "animate-pulse bg-[var(--pos-800)]"
              : "bg-[var(--pos-800)]"
        }`}
      />
      {cola.enCola > 0 && (
        <span>
          {/* Se dice que están GUARDADAS, no que fallaron: fallar suena a que
              hay que rehacerlas, y no hay que rehacer nada. */}
          {cola.enCola} venta{cola.enCola === 1 ? "" : "s"} guardada
          {cola.enCola === 1 ? "" : "s"}, sin enviar
        </span>
      )}
      {hayRechazadas && (
        <span>
          · {cola.rechazadas} rechazada{cola.rechazadas === 1 ? "" : "s"}
        </span>
      )}
      <button
        onClick={() => void sincronizar()}
        disabled={cola.sincronizando}
        className="ml-1 underline underline-offset-2 disabled:opacity-50"
      >
        {cola.sincronizando ? "enviando…" : "reintentar"}
      </button>
    </div>
  );
}
