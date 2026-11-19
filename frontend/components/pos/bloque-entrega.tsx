"use client";

import type { Entrega } from "@/lib/pos/api";
import { CIUDADES_FRECUENTES, DEPARTAMENTOS, faltaEnLaEntrega } from "@/lib/pos/envio";

/**
 * A quién y a dónde se lleva una venta con envío. Va ARRIBA del cobro: sin
 * entrega completa no hay venta con envío, y descubrirlo después de pasar la
 * tarjeta sería devolver un cobro con la clienta enfrente.
 *
 * Todo obligatorio salvo el complemento (diseño, 2026-11-13). Quien recibe y
 * su celular se proponen desde la clienta de la venta —casi siempre es ella—,
 * pero se pueden cambiar: a veces es un regalo.
 */
export function BloqueEntrega({
  entrega,
  onCambio,
}: {
  entrega: Entrega;
  onCambio: (e: Entrega) => void;
}) {
  const falta = faltaEnLaEntrega(entrega);
  const poner = (campo: keyof Entrega) =>
    (ev: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      onCambio({ ...entrega, [campo]: ev.target.value });

  return (
    <fieldset className="mb-4 border border-[var(--pos-accent)]/40 bg-[var(--pos-accent)]/5 p-3">
      <legend className="kicker px-1">ENTREGA A DOMICILIO · SIN COSTO DE ENVÍO</legend>

      <div className="grid grid-cols-2 gap-2">
        <Campo etiqueta="Quién recibe" className="col-span-2">
          <input value={entrega.destinatario} onChange={poner("destinatario")}
                 autoComplete="off" className={CLASE} aria-label="Quién recibe" />
        </Campo>
        <Campo etiqueta="Celular">
          <input value={entrega.telefono} onChange={poner("telefono")}
                 inputMode="tel" autoComplete="off" className={`${CLASE} tabular`}
                 aria-label="Celular de quien recibe" />
        </Campo>
        <Campo etiqueta="Departamento">
          <select value={entrega.departamento} onChange={poner("departamento")}
                  className={CLASE} aria-label="Departamento">
            <option value="">Elige…</option>
            {DEPARTAMENTOS.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </Campo>
        <Campo etiqueta="Dirección" className="col-span-2">
          <input value={entrega.direccion} onChange={poner("direccion")}
                 placeholder="Calle 10 # 43-21" autoComplete="off" className={CLASE}
                 aria-label="Dirección" />
        </Campo>
        <Campo etiqueta="Complemento">
          <input value={entrega.complemento} onChange={poner("complemento")}
                 placeholder="Opcional: apto, torre" autoComplete="off" className={CLASE}
                 aria-label="Complemento de la dirección" />
        </Campo>
        <Campo etiqueta="Ciudad">
          <input value={entrega.ciudad} onChange={poner("ciudad")}
                 list="pos-ciudades" autoComplete="off" className={CLASE}
                 aria-label="Ciudad" />
          <datalist id="pos-ciudades">
            {CIUDADES_FRECUENTES.map((c) => <option key={c} value={c} />)}
          </datalist>
        </Campo>
      </div>

      {falta.length > 0 && (
        <p className="mt-2 text-[12px] leading-snug text-[var(--pos-700)]">
          Falta {falta.join(", ")}.
        </p>
      )}
    </fieldset>
  );
}

const CLASE = "mt-1 h-11 w-full pos-input px-3 text-[14px] text-[var(--pos-text)]";

function Campo({ etiqueta, className = "", children }: {
  etiqueta: string; className?: string; children: React.ReactNode;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="kicker" style={{ color: "var(--pos-600)" }}>{etiqueta}</span>
      {children}
    </label>
  );
}
