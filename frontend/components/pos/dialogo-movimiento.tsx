"use client";

/**
 * Registrar plata que entra o sale del cajón sin ser una venta.
 *
 * POR QUÉ ESTO EXISTE: sin ello, sale plata para un domiciliario o para bolsas
 * y no hay dónde anotarlo. El arqueo lo lee como faltante, y la cajera termina
 * justificando y buscando un supervisor por algo rutinario. Un control que
 * salta con lo normal deja de mirarse en una semana.
 *
 * EL MOTIVO ES OBLIGATORIO y sin sugerencias prefabricadas. Una lista de
 * motivos frecuentes se convierte en «lo primero de la lista» a los tres días:
 * escribirlo obliga a pensar medio segundo, y ese medio segundo es lo que
 * después permite revisar el movimiento.
 */
import { useState } from "react";
import { Panel } from "@/components/pos/marco";
import { formatear, desdePesosTecleados } from "@/lib/pos/dinero";

type Tipo = "retiro" | "gasto" | "ingreso";

const TIPOS: { id: Tipo; etiqueta: string; ayuda: string }[] = [
  { id: "retiro", etiqueta: "Sangría", ayuda: "sale a la caja fuerte" },
  { id: "gasto", etiqueta: "Gasto", ayuda: "caja menor" },
  { id: "ingreso", etiqueta: "Ingreso", ayuda: "entra sencillo" },
];

export function DialogoMovimiento({
  onCancelar,
  onRegistrar,
  error,
  guardando,
}: {
  onCancelar: () => void;
  onRegistrar: (tipo: Tipo, montoCentavos: number, motivo: string) => void;
  error: string | null;
  guardando: boolean;
}) {
  const [tipo, setTipo] = useState<Tipo>("retiro");
  const [monto, setMonto] = useState("");
  const [motivo, setMotivo] = useState("");

  const centavos = desdePesosTecleados(monto);
  const listo = centavos > 0 && motivo.trim().length >= 3;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label="Movimiento de caja"
        className="w-full max-w-[420px] bg-[var(--pos-bg)] p-6"
      >
        <h2 className="titular text-[15px] font-semibold tracking-[0.08em]">
          MOVIMIENTO DE CAJA
        </h2>

        <div className="mt-4 grid grid-cols-3 gap-2">
          {TIPOS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTipo(t.id)}
              className={`border px-2 py-2.5 text-[12px] transition-colors ${
                tipo === t.id
                  ? "border-[var(--pos-800)] bg-[var(--pos-800)] text-white"
                  : "border-[var(--pos-divider)] text-[var(--pos-700)]"
              }`}
            >
              <span className="block font-medium">{t.etiqueta}</span>
              <span className="block text-[12px] opacity-70">{t.ayuda}</span>
            </button>
          ))}
        </div>

        <label className="mt-4 block">
          <span className="kicker text-[var(--pos-600)]">Monto</span>
          <input
            inputMode="numeric"
            autoFocus
            autoComplete="off"
            placeholder="0"
            value={monto}
            onChange={(e) => setMonto(e.target.value.replace(/[^\d]/g, ""))}
            className="mt-1.5 h-12 w-full border border-[var(--pos-divider)] bg-white px-3 titular text-[18px] tabular text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
          />
          {centavos > 0 && (
            <span className="mt-1 block tabular text-[12px] text-[var(--pos-600)]">
              {tipo === "ingreso" ? "+" : "−"}
              {formatear(centavos)}
            </span>
          )}
        </label>

        <label className="mt-4 block">
          <span className="kicker text-[var(--pos-600)]">
            Motivo (obligatorio)
          </span>
          <input
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            placeholder={
              tipo === "gasto" ? "bolsas y cinta" : "sangría a la caja fuerte"
            }
            className="mt-1.5 h-11 w-full border border-[var(--pos-divider)] bg-white px-3 text-[13px] text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
          />
        </label>

        {error && (
          <p className="mt-4 border border-[var(--pos-800)] bg-[var(--pos-800)]/10 p-2.5 text-[12px] leading-relaxed text-[var(--pos-900)]">
            {error}
          </p>
        )}

        <p className="mt-4 tabular text-[12px] leading-relaxed text-[var(--pos-600)]">
          {tipo === "ingreso"
            ? "Queda registrado con tu nombre."
            : "Sacar plata queda como CRÍTICO en la auditoría, con tu nombre y este motivo."}
        </p>

        <div className="mt-5 flex gap-3">
          <button
            onClick={onCancelar}
            className="h-12 flex-1 border border-[var(--pos-divider)] titular text-[13px] tracking-[0.08em] text-[var(--pos-700)]"
          >
            CANCELAR
          </button>
          <button
            disabled={!listo || guardando}
            onClick={() => onRegistrar(tipo, centavos, motivo.trim())}
            className="h-12 flex-1 bg-[var(--pos-accent)] titular text-[13px] font-semibold tracking-[0.08em] text-white disabled:bg-[var(--pos-divider)] disabled:text-[var(--pos-muted)]"
          >
            {guardando ? "GUARDANDO…" : "REGISTRAR"}
          </button>
        </div>
      </Panel>
    </div>
  );
}
