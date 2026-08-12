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
        className="mb-3 self-start font-mono text-[11px] text-[#6F92A6] hover:text-[#F4F3F0]"
      >
        ← Volver al ticket · Esc
      </button>

      <div className="mb-4">
        <div className="font-display text-[11px] tracking-[0.14em] text-[#6F92A6]">
          A COBRAR
        </div>
        <div className="font-mono text-[34px] font-semibold tabular-nums tracking-tight">
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
                ? "border-[#C8412B] bg-[#C8412B]/10 text-[#F4F3F0]"
                : "border-[#243036] bg-[#1A242A] text-[#A6BECC]"
            }`}
          >
            {m.nombre}
          </button>
        ))}
      </div>

      <label className="font-display text-[10.5px] tracking-[0.12em] text-[#6F92A6]">
        MONTO RECIBIDO
      </label>
      <input
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        inputMode="numeric"
        placeholder={formatear(total)}
        className="mt-1 border border-[#243036] bg-[#1A242A] px-3 py-2.5 font-mono text-lg tabular-nums text-[#F4F3F0] outline-none focus:border-[#C8412B]"
      />

      <div className="mt-2 flex gap-2">
        {[total, 200000_00, 500000_00].map((v, i) => (
          <button
            key={i}
            onClick={() => setTexto(String(Math.round(v / 100)))}
            className="border border-[#243036] bg-[#1A242A] px-2.5 py-1.5 font-mono text-[11px] text-[#A6BECC] hover:border-[#6F92A6]"
          >
            {i === 0 ? "Exacto" : formatear(v)}
          </button>
        ))}
      </div>

      <div className="mt-auto">
        {vuelto > 0 && (
          <div className="mb-3">
            <div className="font-display text-[10.5px] tracking-[0.12em] text-[#6F92A6]">
              VUELTO
            </div>
            <div className="font-mono text-[26px] font-semibold tabular-nums text-[#6E9169]">
              {formatear(vuelto)}
            </div>
          </div>
        )}
        {excedenteInvalido && (
          <p className="mb-3 border border-[#B08C2E] bg-[#B08C2E]/10 p-2.5 text-[11.5px] leading-snug text-[#C6A047]">
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
          className="w-full bg-[#C8412B] py-3.5 font-display text-[13.5px] font-semibold tracking-[0.12em] text-white disabled:cursor-not-allowed disabled:bg-[#243036] disabled:text-[#4A5C66]"
        >
          {enviando ? "CERRANDO…" : "CONFIRMAR · F12"}
        </button>
        {!alcanza && (
          <p className="mt-2 text-center font-mono text-[11px] text-[#6F92A6]">
            Faltan {formatear(total - monto)}
          </p>
        )}
      </div>
    </div>
  );
}
