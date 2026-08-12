"use client";

import { useState } from "react";
import { desdePesosTecleados, formatear } from "@/lib/pos/dinero";

/**
 * Cobro. El botón sólo se habilita cuando lo pagado alcanza (INV-V3), y el
 * vuelto se calcula solo.
 *
 * Las sugerencias rápidas existen porque teclear "200000" son seis toques y
 * un billete de $200.000 es el caso más común.
 */
const MEDIOS = [
  { id: "efectivo", nombre: "💵 Efectivo", esEfectivo: true },
  { id: "datafono_florida", nombre: "💳 Datáfono", esEfectivo: false },
];

export function PanelCobro({
  total,
  onCancelar,
  onConfirmar,
}: {
  total: number;
  onCancelar: () => void;
  onConfirmar: (
    pagos: { medio_pago_id: string; monto_centavos: number; es_efectivo: boolean }[],
  ) => void;
}) {
  const [medio, setMedio] = useState(MEDIOS[0]);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);

  const monto = texto ? desdePesosTecleados(texto) : total;
  const alcanza = monto >= total;
  const vuelto = medio.esEfectivo ? Math.max(monto - total, 0) : 0;
  // Un datáfono no da vuelto: cobrar de más ahí es un error de digitación.
  const excedenteInvalido = !medio.esEfectivo && monto > total;

  return (
    <div className="flex h-full flex-col">
      <button
        onClick={onCancelar}
        className="mb-3 self-start tabular text-[11px] text-[var(--pos-600)] hover:text-[var(--pos-text)]"
      >
        ← Volver al ticket · Esc
      </button>

      <div className="mb-4">
        <div className="titular text-[11px] tracking-[0.14em] text-[var(--pos-600)]">
          A COBRAR
        </div>
        <div className="tabular text-[34px] font-semibold tabular-nums tracking-tight">
          {formatear(total)}
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-2">
        {MEDIOS.map((m) => (
          <button
            key={m.id}
            onClick={() => setMedio(m)}
            className={`border py-3 text-[12.5px] ${
              medio.id === m.id
                ? "border-[var(--pos-accent)] bg-[var(--pos-accent)]/10 text-[var(--pos-text)]"
                : "border-[var(--pos-divider)] bg-[var(--pos-100)] text-[var(--pos-700)]"
            }`}
          >
            {m.nombre}
          </button>
        ))}
      </div>

      <label className="titular text-[10.5px] tracking-[0.12em] text-[var(--pos-600)]">
        MONTO RECIBIDO
      </label>
      <input
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        inputMode="numeric"
        placeholder={formatear(total)}
        className="mt-1 border border-[var(--pos-divider)] bg-[var(--pos-100)] px-3 py-2.5 tabular text-lg tabular-nums text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
      />

      <div className="mt-2 flex gap-2">
        {[total, 200000_00, 500000_00].map((v, i) => (
          <button
            key={i}
            onClick={() => setTexto(String(Math.round(v / 100)))}
            className="border border-[var(--pos-divider)] bg-[var(--pos-100)] px-2.5 py-1.5 tabular text-[11px] text-[var(--pos-700)] hover:border-[var(--pos-600)]"
          >
            {i === 0 ? "Exacto" : formatear(v)}
          </button>
        ))}
      </div>

      <div className="mt-auto">
        {vuelto > 0 && (
          <div className="mb-3">
            <div className="titular text-[10.5px] tracking-[0.12em] text-[var(--pos-600)]">
              VUELTO
            </div>
            <div className="tabular text-[26px] font-semibold tabular-nums text-[var(--pos-800)]">
              {formatear(vuelto)}
            </div>
          </div>
        )}
        {excedenteInvalido && (
          <p className="mb-3 border border-[var(--pos-700)] bg-[var(--pos-700)]/10 p-2.5 text-[11.5px] leading-snug text-[var(--pos-800)]">
            Un datáfono no da vuelto. Si se cobró de más, revisa el monto: ese
            excedente aparecería como sobrante en el arqueo sin saber de dónde salió.
          </p>
        )}

        <button
          disabled={!alcanza || excedenteInvalido || enviando}
          onClick={() => {
            setEnviando(true);
            onConfirmar([
              {
                medio_pago_id: medio.id,
                monto_centavos: monto,
                es_efectivo: medio.esEfectivo,
              },
            ]);
          }}
          className="w-full bg-[var(--pos-accent)] py-3.5 titular text-[13.5px] font-semibold tracking-[0.12em] text-white disabled:cursor-not-allowed disabled:bg-[var(--pos-divider)] disabled:text-[var(--pos-500)]"
        >
          {enviando ? "CERRANDO…" : "CONFIRMAR · F12"}
        </button>
        {!alcanza && (
          <p className="mt-2 text-center tabular text-[11px] text-[var(--pos-600)]">
            Faltan {formatear(total - monto)}
          </p>
        )}
      </div>
    </div>
  );
}
