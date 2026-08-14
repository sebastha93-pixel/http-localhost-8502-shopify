"use client";

import { useState } from "react";
import { desdePesosTecleados, formatear } from "@/lib/pos/dinero";
import type { MedioPago } from "@/lib/pos/api";

/**
 * Cobro. El botón sólo se habilita cuando lo pagado alcanza (INV-V3), y el
 * vuelto se calcula solo.
 *
 * LOS MEDIOS SALEN DE LA TIENDA, NO DE ESTE ARCHIVO. Estaban quemados aquí en
 * una lista de dos, y uno de ellos apuntaba a `datafono_florida`, un id que no
 * existe en la base: la llave foránea rechazaba TODO cobro con tarjeta. Nunca
 * saltó porque todas las ventas de prueba fueron en efectivo. Ahora vienen del
 * contexto de la caja —que el equipo guarda para trabajar sin red—, así que
 * dar de alta Addi o un QR es un dato, no un despliegue.
 *
 * Las sugerencias rápidas existen porque teclear "200000" son seis toques y un
 * billete de $200.000 es el caso más común. Sólo tienen sentido con efectivo:
 * en un datáfono se cobra el exacto.
 */
export function PanelCobro({
  total,
  medios,
  onCancelar,
  onConfirmar,
}: {
  total: number;
  medios: MedioPago[];
  onCancelar: () => void;
  onConfirmar: (
    pagos: {
      medio_pago_id: string;
      monto_centavos: number;
      es_efectivo: boolean;
      referencia?: string;
    }[],
  ) => void;
}) {
  const [medioId, setMedioId] = useState(medios[0]?.id ?? "");
  const [texto, setTexto] = useState("");
  const [referencia, setReferencia] = useState("");
  const [enviando, setEnviando] = useState(false);

  const medio = medios.find((m) => m.id === medioId) ?? medios[0];
  const monto = texto ? desdePesosTecleados(texto) : total;
  const alcanza = monto >= total;
  const vuelto = medio?.permite_vuelto ? Math.max(monto - total, 0) : 0;
  // Sólo el efectivo da vuelto. Cobrar de más en cualquier otro medio es un
  // error de digitación que aparecería como sobrante sin explicación.
  const excedenteInvalido = !medio?.permite_vuelto && monto > total;
  const faltaReferencia =
    Boolean(medio?.exige_referencia) && referencia.trim().length < 4;

  if (!medio) {
    return (
      <div className="flex h-full flex-col justify-center">
        <p className="text-[13px] leading-relaxed text-[var(--pos-700)]">
          Esta tienda no tiene medios de pago configurados. Sin eso no se puede
          cobrar: pide que los den de alta antes de abrir.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <button
        onClick={onCancelar}
        className="mb-3 self-start tabular text-[12px] text-[var(--pos-600)] hover:text-[var(--pos-text)]"
      >
        ← Volver al ticket · Esc
      </button>

      <div className="mb-4">
        <div className="titular text-[12px] tracking-[0.14em] text-[var(--pos-600)]">
          A COBRAR
        </div>
        <div className="tabular text-[34px] font-semibold tabular-nums tracking-tight">
          {formatear(total)}
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-2">
        {medios.map((m) => (
          <button
            key={m.id}
            onClick={() => {
              setMedioId(m.id);
              setReferencia("");
              // El exacto es lo normal en todo lo que no es efectivo: el
              // datáfono y la app cobran la cifra, no un billete.
              if (!m.permite_vuelto) setTexto("");
            }}
            className={`border px-2 py-3 text-[13px] transition-colors duration-[var(--pos-transicion)] ${
              medio.id === m.id
                ? "border-[var(--pos-accent)] bg-[var(--pos-accent)]/10 text-[var(--pos-text)]"
                : "border-[var(--pos-divider)] bg-[var(--pos-100)] text-[var(--pos-700)]"
            }`}
          >
            {m.nombre}
          </button>
        ))}
      </div>

      {/* LO QUE NO SE PUEDE FACTURAR TODAVÍA, dicho aquí y no al final del día.
          La venta se cobra igual —la caja nunca se bloquea por Siigo— pero
          quien cobra tiene derecho a saber que ese documento va a quedar
          esperando, en vez de descubrirlo cuando la clienta reclame factura. */}
      {!medio.factura_lista && (
        <p className="mb-3 border-l-2 border-[var(--pos-accent)] bg-[var(--pos-accent)]/10 py-2 pl-3 text-[12px] leading-relaxed text-[var(--pos-900)]">
          <b>{medio.nombre}</b> todavía no tiene forma de pago configurada en
          Siigo. La venta se registra y se cobra normal; la factura electrónica
          queda pendiente hasta que se configure.
        </p>
      )}

      {medio.exige_referencia && (
        <label className="mb-3 block">
          <span className="titular text-[12px] tracking-[0.12em] text-[var(--pos-600)]">
            NÚMERO DE APROBACIÓN
          </span>
          <input
            value={referencia}
            onChange={(e) => setReferencia(e.target.value)}
            autoComplete="off"
            placeholder="el que salió en la pantalla o en la app"
            className="mt-1 w-full border border-[var(--pos-divider)] bg-white px-3 py-2.5 tabular text-[15px] text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
          />
          <span className="mt-1 block text-[12px] leading-relaxed text-[var(--pos-600)]">
            Es lo único que después permite cuadrar este cobro contra el informe
            de {medio.nombre} — y lo que la clienta necesita para reclamar.
          </span>
        </label>
      )}

      <label className="titular text-[12px] tracking-[0.12em] text-[var(--pos-600)]">
        {medio.permite_vuelto ? "MONTO RECIBIDO" : "MONTO COBRADO"}
      </label>
      <input
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        inputMode="numeric"
        placeholder={formatear(total)}
        className="mt-1 border border-[var(--pos-divider)] bg-[var(--pos-100)] px-3 py-2.5 tabular text-lg tabular-nums text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
      />

      {medio.permite_vuelto && (
        <div className="mt-2 flex gap-2">
          {[total, 200000_00, 500000_00].map((v, i) => (
            <button
              key={i}
              onClick={() => setTexto(String(Math.round(v / 100)))}
              className="border border-[var(--pos-divider)] bg-[var(--pos-100)] px-2.5 py-1.5 tabular text-[12px] text-[var(--pos-700)] transition-colors duration-[var(--pos-transicion)] hover:border-[var(--pos-600)]"
            >
              {i === 0 ? "Exacto" : formatear(v)}
            </button>
          ))}
        </div>
      )}

      <div className="mt-auto pt-4">
        {vuelto > 0 && (
          <div className="mb-3">
            <div className="titular text-[12px] tracking-[0.12em] text-[var(--pos-600)]">
              VUELTO
            </div>
            <div className="tabular text-[26px] font-semibold tabular-nums text-[var(--pos-800)]">
              {formatear(vuelto)}
            </div>
          </div>
        )}
        {excedenteInvalido && (
          <p className="mb-3 border border-[var(--pos-700)] bg-[var(--pos-700)]/10 p-2.5 text-[12px] leading-snug text-[var(--pos-800)]">
            {medio.nombre} no da vuelto. Si se cobró de más, revisa el monto: ese
            excedente aparecería como sobrante en el arqueo sin saber de dónde salió.
          </p>
        )}

        <button
          disabled={!alcanza || excedenteInvalido || faltaReferencia || enviando}
          onClick={() => {
            setEnviando(true);
            onConfirmar([
              {
                medio_pago_id: medio.id,
                monto_centavos: monto,
                es_efectivo: medio.es_efectivo,
                ...(referencia.trim() ? { referencia: referencia.trim() } : {}),
              },
            ]);
          }}
          className="w-full bg-[var(--pos-accent)] py-3.5 titular text-[13.5px] font-semibold tracking-[0.12em] text-white disabled:cursor-not-allowed disabled:bg-[var(--pos-divider)] disabled:text-[var(--pos-muted)]"
        >
          {enviando ? "CERRANDO…" : "CONFIRMAR · F12"}
        </button>
        {!alcanza && (
          <p className="mt-2 text-center tabular text-[12px] text-[var(--pos-600)]">
            Faltan {formatear(total - monto)}
          </p>
        )}
        {alcanza && faltaReferencia && (
          <p className="mt-2 text-center text-[12px] text-[var(--pos-600)]">
            Falta el número de aprobación de {medio.nombre}.
          </p>
        )}
      </div>
    </div>
  );
}
