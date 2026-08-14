"use client";

import { useState } from "react";
import { desdePesosTecleados, formatear } from "@/lib/pos/dinero";
import type { MedioPago } from "@/lib/pos/api";

/**
 * Cobro, con pago mixto.
 *
 * EL BACKEND SIEMPRE ACEPTÓ VARIOS PAGOS —`Venta` tiene `saldo()`, `vuelto()` e
 * INV-V3— y esta pantalla mandaba siempre uno solo. Con Addi eso deja de ser un
 * detalle: el cupo aprobado casi nunca cubre la compra entera, así que la
 * clienta completa con un billete o con la tarjeta. Sin pago mixto, la cajera
 * tendría que partir la venta en dos tiquetes — y entonces el inventario, la
 * numeración y la factura cuentan dos ventas donde hubo una.
 *
 * UNA VENTA NORMAL SIGUE SIENDO UN TOQUE. El monto viene relleno con lo que
 * falta, así que en el caso de siempre —un medio, la cifra exacta— el botón ya
 * dice CONFIRMAR y no hay ningún paso nuevo. Sólo cuando se teclea MENOS de lo
 * que falta el botón se convierte en AGREGAR y aparece el siguiente cobro. El
 * caso raro no le cuesta nada al caso común.
 *
 * SE PUEDE QUITAR UN PAGO YA AGREGADO. Equivocarse de medio o de cifra a mitad
 * del cobro es normal; sin un deshacer, la salida sería cancelar la venta
 * entera y volver a armar el carrito delante de la clienta.
 *
 * LOS MEDIOS SALEN DE LA TIENDA, no de este archivo. Estaban quemados aquí, y
 * uno apuntaba a `datafono_florida`, un id que no existe: la llave foránea
 * rechazaba TODO cobro con tarjeta y nunca saltó porque las pruebas fueron en
 * efectivo.
 */
interface PagoLocal {
  medio: MedioPago;
  monto: number;
  referencia?: string;
}

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
  const [pagos, setPagos] = useState<PagoLocal[]>([]);
  const [medioId, setMedioId] = useState(medios[0]?.id ?? "");
  const [texto, setTexto] = useState("");
  const [referencia, setReferencia] = useState("");
  const [enviando, setEnviando] = useState(false);

  const medio = medios.find((m) => m.id === medioId) ?? medios[0];
  const yaPagado = pagos.reduce((s, p) => s + p.monto, 0);
  const restante = Math.max(total - yaPagado, 0);

  // El monto se rellena con LO QUE FALTA. Es lo que hace que una venta de un
  // solo pago no note que esta pantalla sabe hacer pagos mixtos.
  const monto = texto ? desdePesosTecleados(texto) : restante;
  const cubre = monto >= restante;
  const faltaTrasEste = Math.max(restante - monto, 0);

  // El vuelto sale del efectivo, y sólo de ahí (INV-V3). Se comprueba también
  // aquí para que la cajera lo vea ANTES de que el servidor lo rechace.
  const efectivoTotal =
    pagos.filter((p) => p.medio.permite_vuelto).reduce((s, p) => s + p.monto, 0) +
    (medio?.permite_vuelto ? monto : 0);
  const excedente = Math.max(yaPagado + monto - total, 0);
  const vuelto = Math.min(excedente, efectivoTotal);
  const excedenteInvalido = excedente > efectivoTotal;

  const faltaReferencia =
    Boolean(medio?.exige_referencia) && referencia.trim().length < 4;
  const montoInvalido = monto <= 0;

  function limpiar() {
    setTexto("");
    setReferencia("");
  }

  function agregar() {
    if (!medio) return;
    setPagos((p) => [
      ...p,
      { medio, monto, ...(referencia.trim() ? { referencia: referencia.trim() } : {}) },
    ]);
    limpiar();
  }

  function confirmar() {
    if (!medio) return;
    setEnviando(true);
    const todos: PagoLocal[] = [
      ...pagos,
      { medio, monto, ...(referencia.trim() ? { referencia: referencia.trim() } : {}) },
    ];
    onConfirmar(
      todos.map((p) => ({
        medio_pago_id: p.medio.id,
        monto_centavos: p.monto,
        es_efectivo: p.medio.es_efectivo,
        ...(p.referencia ? { referencia: p.referencia } : {}),
      })),
    );
  }

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
          {pagos.length ? "FALTA POR COBRAR" : "A COBRAR"}
        </div>
        <div className="tabular text-[34px] font-semibold tabular-nums tracking-tight">
          {formatear(pagos.length ? restante : total)}
        </div>
        {pagos.length > 0 && (
          <div className="tabular text-[12px] text-[var(--pos-600)]">
            de {formatear(total)}
          </div>
        )}
      </div>

      {/* LO YA COBRADO. Va arriba y con su referencia porque es lo que la
          cajera repasa antes de confirmar, y porque un pago equivocado tiene
          que poder quitarse sin cancelar la venta entera. */}
      {pagos.length > 0 && (
        <div className="mb-4 border-t border-[var(--pos-divider)]">
          {pagos.map((p, i) => (
            <div
              key={i}
              className="flex items-center gap-2 border-b border-[var(--pos-divider)]/60 py-1.5"
            >
              <div className="min-w-0 flex-1">
                <div className="text-[13px]">{p.medio.nombre}</div>
                {p.referencia && (
                  <div className="tabular text-[12px] text-[var(--pos-600)]">
                    {p.referencia}
                  </div>
                )}
              </div>
              <span className="tabular text-[13px] font-semibold">
                {formatear(p.monto)}
              </span>
              <button
                onClick={() => setPagos((l) => l.filter((_, j) => j !== i))}
                aria-label={`Quitar el pago de ${p.medio.nombre}`}
                title="Quitar este pago"
                className="h-11 w-11 shrink-0 border border-[var(--pos-divider)] text-[14px] text-[var(--pos-700)] transition-colors duration-[var(--pos-transicion)] hover:bg-[var(--pos-100)]"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-2">
        {medios.map((m) => (
          <button
            key={m.id}
            onClick={() => {
              setMedioId(m.id);
              limpiar();
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
        placeholder={formatear(restante)}
        aria-label={`Monto con ${medio.nombre}`}
        className="mt-1 border border-[var(--pos-divider)] bg-[var(--pos-100)] px-3 py-2.5 tabular text-lg tabular-nums text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
      />

      <div className="mt-2 flex flex-wrap gap-2">
        {/* «Lo que falta» primero: en un pago mixto es el que se pulsa para
            cerrar, y en uno normal es el exacto de siempre. */}
        <Rapido etiqueta="Lo que falta" onClick={() => setTexto(String(Math.round(restante / 100)))} />
        {medio.permite_vuelto &&
          [200000_00, 500000_00]
            .filter((v) => v > restante)
            .map((v) => (
              <Rapido key={v} etiqueta={formatear(v)}
                      onClick={() => setTexto(String(Math.round(v / 100)))} />
            ))}
        {/* La MITAD sólo aparece cuando aún no se ha cobrado nada: es el
            atajo del caso mixto típico —el cupo cubre una parte— y después de
            partir el pago ya no significa nada. */}
        {pagos.length === 0 && (
          <Rapido etiqueta="Mitad"
                  onClick={() => setTexto(String(Math.round(total / 2 / 100)))} />
        )}
      </div>

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
            Se están cobrando {formatear(yaPagado + monto)} por una venta de{" "}
            {formatear(total)}, y ese excedente no se puede devolver: no entró
            en efectivo. Revisa los montos — así aparecería como sobrante en el
            arqueo sin saber de qué venta salió.
          </p>
        )}

        <button
          disabled={montoInvalido || excedenteInvalido || faltaReferencia || enviando}
          onClick={cubre ? confirmar : agregar}
          className="w-full bg-[var(--pos-accent)] py-3.5 titular text-[13.5px] font-semibold tracking-[0.12em] text-white disabled:cursor-not-allowed disabled:bg-[var(--pos-divider)] disabled:text-[var(--pos-muted)]"
        >
          {enviando
            ? "CERRANDO…"
            : cubre
              ? "CONFIRMAR · F12"
              : `AGREGAR ${formatear(monto)}`}
        </button>

        {!cubre && !montoInvalido && (
          <p className="mt-2 text-center tabular text-[12px] text-[var(--pos-600)]">
            Quedarían {formatear(faltaTrasEste)} por cobrar con otro medio.
          </p>
        )}
        {faltaReferencia && !montoInvalido && (
          <p className="mt-2 text-center text-[12px] text-[var(--pos-600)]">
            Falta el número de aprobación de {medio.nombre}.
          </p>
        )}
      </div>
    </div>
  );
}

function Rapido({ etiqueta, onClick }: { etiqueta: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="border border-[var(--pos-divider)] bg-[var(--pos-100)] px-2.5 py-1.5 tabular text-[12px] text-[var(--pos-700)] transition-colors duration-[var(--pos-transicion)] hover:border-[var(--pos-600)]"
    >
      {etiqueta}
    </button>
  );
}
