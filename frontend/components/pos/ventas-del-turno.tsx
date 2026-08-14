"use client";

/**
 * Las ventas de este turno, para reimprimir o anular.
 *
 * POR QUÉ HACE FALTA: hasta ahora la tirilla sólo se podía reimprimir mientras
 * la pantalla del ticket siguiera abierta — ocho segundos. La clienta que
 * vuelve media hora después con el papel borrado, o el domiciliario que pide
 * copia, no tenían por dónde.
 *
 * LA ANULADA NO DESAPARECE de la lista. Una venta que se esfuma es
 * indistinguible de una que nunca existió, y es justo la que hay que poder
 * revisar: queda tachada, con su motivo a la vista.
 */
import { useState } from "react";
import { Panel } from "@/components/pos/marco";
import { formatear } from "@/lib/pos/dinero";
import type { VentaDelTurno } from "@/lib/pos/api";

export function VentasDelTurno({
  ventas,
  onReimprimir,
  onAnular,
  puedeAnular,
}: {
  ventas: VentaDelTurno[];
  onReimprimir: (ventaId: string) => void;
  onAnular: (venta: VentaDelTurno) => void;
  puedeAnular: boolean;
}) {
  return (
    <Panel className="flex flex-col gap-2 p-6">
      <div className="flex items-baseline justify-between">
        <h2 className="titular text-[17px] font-semibold">Ventas del turno</h2>
        <span className="tabular text-[12px] text-[var(--pos-600)]">
          {ventas.filter((v) => v.estado === "cerrada").length} vigentes
        </span>
      </div>

      {ventas.length === 0 && (
        <p className="text-[13px] text-[var(--pos-600)]">
          Todavía no hay ventas en este turno.
        </p>
      )}

      {ventas.map((v) => {
        const anulada = v.estado === "anulada";
        return (
          <div
            key={v.venta_id}
            className="flex items-center gap-3 border-b border-[var(--pos-divider)]/60 py-2 last:border-0"
          >
            <div className="min-w-0 flex-1">
              <p className="flex items-baseline gap-2 text-[13px]">
                <span
                  className={`tabular font-medium ${
                    anulada ? "text-[var(--pos-muted)] line-through" : ""
                  }`}
                >
                  {v.numero}
                </span>
                <span className="tabular text-[12px] text-[var(--pos-600)]">
                  {v.hora} · {v.unidades} u
                </span>
                {v.cliente_nombre && (
                  <span className="truncate text-[12px] text-[var(--pos-600)]">
                    {v.cliente_nombre}
                  </span>
                )}
              </p>
              {anulada && v.motivo_anulacion && (
                <p className="text-[12px] text-[var(--pos-accent)]">
                  Anulada · {v.motivo_anulacion}
                </p>
              )}
            </div>

            <span
              className={`tabular whitespace-nowrap text-[13px] font-semibold ${
                anulada ? "text-[var(--pos-muted)] line-through" : ""
              }`}
            >
              {formatear(v.total_centavos)}
            </span>

            <div className="flex shrink-0 gap-1.5">
              {/* Reimprimir SIEMPRE, incluso una anulada: alguien va a pedir el
                  papel de la que se deshizo, y negarlo obliga a buscarlo en la
                  base. Sale marcada como anulada. */}
              <button
                onClick={() => onReimprimir(v.venta_id)}
                title="Reimprimir la tirilla"
                className="border border-[var(--pos-divider)] px-2 py-1 text-[12px] text-[var(--pos-700)] hover:bg-[var(--pos-100)]"
              >
                Tirilla
              </button>
              {!anulada && puedeAnular && (
                <button
                  onClick={() => onAnular(v)}
                  className="border border-[var(--pos-accent)]/40 px-2 py-1 text-[12px] text-[var(--pos-accent)] hover:bg-[var(--pos-accent)]/10"
                >
                  Anular
                </button>
              )}
            </div>
          </div>
        );
      })}
    </Panel>
  );
}

/** Anular exige motivo escrito. Es lo único que después permite distinguir un
 *  error de digitación de una venta que alguien hizo desaparecer. */
export function DialogoAnular({
  venta,
  onCancelar,
  onConfirmar,
  error,
  anulando,
}: {
  venta: VentaDelTurno;
  onCancelar: () => void;
  onConfirmar: (motivo: string) => void;
  error: string | null;
  anulando: boolean;
}) {
  const [motivo, setMotivo] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label="Anular venta"
        className="w-full max-w-[440px] bg-[var(--pos-bg)] p-6"
      >
        <h2 className="titular text-[15px] font-semibold tracking-[0.08em]">
          ANULAR {venta.numero}
        </h2>
        <p className="mt-2 tabular text-[13px] text-[var(--pos-700)]">
          {formatear(venta.total_centavos)} · {venta.unidades} prenda
          {venta.unidades === 1 ? "" : "s"}
        </p>

        <p className="mt-3 border-l-2 border-[var(--pos-accent)] bg-[var(--pos-accent)]/10 py-2 pl-3 text-[12px] leading-relaxed text-[var(--pos-900)]">
          La prenda vuelve al inventario y la plata sale del arqueo.
          {venta.estado_fiscal === "emitido" && (
            <>
              {" "}
              <strong>
                La factura ya salió: esto no la revierte ante la DIAN, hace
                falta una nota crédito.
              </strong>
            </>
          )}
        </p>

        <label className="mt-4 block">
          <span className="kicker text-[var(--pos-600)]">
            Motivo (obligatorio)
          </span>
          <input
            autoFocus
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            placeholder="se cobró dos veces por error"
            className="mt-1.5 h-11 w-full border border-[var(--pos-divider)] bg-white px-3 text-[13px] text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
          />
        </label>

        {error && (
          <p className="mt-4 border border-[var(--pos-800)] bg-[var(--pos-800)]/10 p-2.5 text-[12px] leading-relaxed text-[var(--pos-900)]">
            {error}
          </p>
        )}

        <p className="mt-4 tabular text-[12px] leading-relaxed text-[var(--pos-600)]">
          Queda como CRÍTICO en la auditoría, con tu nombre y este motivo.
        </p>

        <div className="mt-5 flex gap-3">
          <button
            onClick={onCancelar}
            className="h-12 flex-1 border border-[var(--pos-divider)] titular text-[13px] tracking-[0.08em] text-[var(--pos-700)]"
          >
            NO ANULAR
          </button>
          <button
            disabled={motivo.trim().length < 5 || anulando}
            onClick={() => onConfirmar(motivo.trim())}
            className="h-12 flex-1 bg-[var(--pos-accent)] titular text-[13px] font-semibold tracking-[0.08em] text-white disabled:bg-[var(--pos-divider)] disabled:text-[var(--pos-muted)]"
          >
            {anulando ? "ANULANDO…" : "ANULAR"}
          </button>
        </div>
      </Panel>
    </div>
  );
}
