"use client";

import { useState } from "react";
import { formatear, porcentaje } from "@/lib/pos/dinero";

/**
 * Descuento sobre una línea.
 *
 * Los porcentajes por encima del tope se muestran CON CANDADO, no se ocultan.
 * Esconderlos haría creer a la cajera que no existen, y terminaría llamando a
 * la supervisora para preguntar en vez de para firmar.
 *
 * El motivo es obligatorio porque un descuento sin explicación es un
 * descuadre sin explicación cuando gerencia revise por qué bajó el margen.
 */
//
// LOS BOTONES LLEGAN HASTA DONDE LLEGAN LOS TOPES. Eran cinco, hasta el 30 %,
// de cuando ninguna cajera pasaba de ahí. Al subir el tope de las tiendas al
// 60 % el diálogo decía «Tu tope: 60 %» y no había cómo marcar más de 30
// (Arrayanes, 2026-10-09). Diez botones en dos filas, y un campo para el
// porcentaje que no esté entre ellos.
const RAPIDOS = [5, 10, 15, 20, 25, 30, 35, 40, 50, 60];

export function DialogoDescuento({
  sku,
  base,
  tope,
  onCancelar,
  onAplicar,
}: {
  sku: string;
  base: number;
  tope: number;
  onCancelar: () => void;
  onAplicar: (pct: number, motivo: string) => void;
}) {
  const [pct, setPct] = useState<number>(RAPIDOS[0]);
  const [otro, setOtro] = useState("");
  const [motivo, setMotivo] = useState("");

  const monto = porcentaje(base, pct);
  const sobreTope = pct > tope;
  const motivoValido = motivo.trim().length >= 4;

  return (
    <Marco titulo="APLICAR DESCUENTO" onCancelar={onCancelar}>
      <p className="tabular text-[12px] text-[var(--pos-600)]">
        {sku} · {formatear(base)}
      </p>

      <div className="mt-4 grid grid-cols-5 gap-2">
        {RAPIDOS.map((p) => (
          <button
            key={p}
            onClick={() => { setPct(p); setOtro(""); }}
            className={`border py-2.5 tabular text-[13px] ${
              pct === p && !otro
                ? "border-[var(--pos-accent)] bg-[var(--pos-accent)]/15 text-[var(--pos-text)]"
                : "border-[var(--pos-divider)] bg-[var(--pos-100)] text-[var(--pos-700)]"
            }`}
          >
            {p}%
            <span className="mt-0.5 block text-[9px]">
              {p > tope ? "🔒" : "✓"}
            </span>
          </button>
        ))}
      </div>

      {/* ENTERO, de 1 a 100. Siigo sólo acepta el descuento como porcentaje
          entero: un 12,5 % saldría en la factura como el precio ya rebajado,
          sin mostrar el descuento. */}
      <label className="mt-3 flex items-center gap-2 tabular text-[12px] text-[var(--pos-600)]">
        <span>Otro porcentaje</span>
        <input
          value={otro}
          onChange={(e) => {
            const limpio = e.target.value.replace(/\D/g, "").slice(0, 3);
            const n = Math.min(Number(limpio || 0), 100);
            setOtro(limpio ? String(n) : "");
            if (n > 0) setPct(n);
          }}
          inputMode="numeric"
          placeholder="—"
          aria-label="Otro porcentaje de descuento"
          className="w-16 border border-[var(--pos-divider)] bg-[var(--pos-100)] px-2 py-1.5 text-center text-[13px] text-[var(--pos-text)]"
        />
        <span>%</span>
      </label>

      <label className="mt-4 block kicker">
        MOTIVO (OBLIGATORIO)
      </label>
      <input
        value={motivo}
        onChange={(e) => setMotivo(e.target.value)}
        placeholder="Prenda con defecto menor"
        className="mt-1 w-full border border-[var(--pos-divider)] bg-[var(--pos-100)] px-3 py-2.5 text-[13px] text-[var(--pos-text)]"
      />

      <div className="mt-4 flex items-baseline justify-between tabular text-[12px]">
        <span className="text-[var(--pos-600)]">Tu tope: {tope}%</span>
        <span className="text-[var(--pos-text)]">
          −{formatear(monto)} → {formatear(base - monto)}
        </span>
      </div>

      {/* El tope dejó de ser «pide permiso» y pasó a ser un NO. Se avisa AQUÍ,
          con el botón ya deshabilitado, y no después de aplicarlo: enterarse
          de que no se puede cuando ya se lo dijiste a la clienta es peor que
          no haberlo ofrecido. */}
      {sobreTope && (
        <p className="mt-3 border border-[var(--pos-700)] bg-[var(--pos-700)]/10 p-2.5 text-[12px] leading-snug text-[var(--pos-800)]">
          Supera tu tope ({tope}%). Para aplicarlo tiene que entrar alguien con
          un tope mayor, con su correo y contraseña.
        </p>
      )}

      <button
        disabled={!motivoValido || sobreTope}
        onClick={() => onAplicar(pct, motivo.trim())}
        className="mt-4 w-full pos-btn pos-btn-primario py-3 text-[13px]"
      >
        APLICAR
      </button>
      {!motivoValido && !sobreTope && (
        <p className="mt-2 text-center tabular text-[12px] text-[var(--pos-600)]">
          Escribe el motivo (mínimo 4 letras).
        </p>
      )}
    </Marco>
  );
}
function Marco({
  titulo,
  onCancelar,
  children,
}: {
  titulo: string;
  onCancelar: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center pos-backdrop p-6">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={titulo}
        className="pos-dialogo w-full max-w-md p-6"
      >
        <div className="mb-4 flex items-start justify-between">
          <h2 className="titular text-[15px] text-[var(--pos-text)]">
            {titulo}
          </h2>
          <button
            onClick={onCancelar}
            aria-label="Cerrar"
            className="text-[var(--pos-600)] hover:text-[var(--pos-text)]"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
