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
const RAPIDOS = [5, 10, 15, 20, 30];

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
  const [motivo, setMotivo] = useState("");

  const monto = porcentaje(base, pct);
  const sobreTope = pct > tope;
  const motivoValido = motivo.trim().length >= 4;

  return (
    <Marco titulo="APLICAR DESCUENTO" onCancelar={onCancelar}>
      <p className="tabular text-[11px] text-[var(--pos-600)]">
        {sku} · {formatear(base)}
      </p>

      <div className="mt-4 grid grid-cols-5 gap-2">
        {RAPIDOS.map((p) => (
          <button
            key={p}
            onClick={() => setPct(p)}
            className={`border py-2.5 tabular text-[13px] ${
              pct === p
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

      <label className="mt-4 block titular text-[10.5px] tracking-[0.12em] text-[var(--pos-600)]">
        MOTIVO (OBLIGATORIO)
      </label>
      <input
        value={motivo}
        onChange={(e) => setMotivo(e.target.value)}
        placeholder="Prenda con defecto menor"
        className="mt-1 w-full border border-[var(--pos-divider)] bg-[var(--pos-100)] px-3 py-2.5 text-[13px] text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
      />

      <div className="mt-4 flex items-baseline justify-between tabular text-[12px]">
        <span className="text-[var(--pos-600)]">Tu tope: {tope}%</span>
        <span className="text-[var(--pos-text)]">
          −{formatear(monto)} → {formatear(base - monto)}
        </span>
      </div>

      {sobreTope && (
        <p className="mt-3 border border-[var(--pos-700)] bg-[var(--pos-700)]/10 p-2.5 text-[11.5px] leading-snug text-[var(--pos-800)]">
          🔒 Supera tu tope. Al aplicarlo se pedirá el PIN de un supervisor, y
          su nombre queda registrado.
        </p>
      )}

      <button
        disabled={!motivoValido}
        onClick={() => onAplicar(pct, motivo.trim())}
        className="mt-4 w-full bg-[var(--pos-accent)] py-3 titular text-[13px] font-semibold tracking-[0.12em] text-white disabled:bg-[var(--pos-divider)] disabled:text-[var(--pos-500)]"
      >
        {sobreTope ? "APLICAR CON AUTORIZACIÓN" : "APLICAR"}
      </button>
      {!motivoValido && (
        <p className="mt-2 text-center tabular text-[10.5px] text-[var(--pos-600)]">
          Escribe el motivo (mínimo 4 letras).
        </p>
      )}
    </Marco>
  );
}

/**
 * PIN del supervisor.
 *
 * El texto dice explícitamente que el nombre queda registrado. No es un
 * aviso legal: es la mitad del control. Quien firma tiene que saberlo.
 */
export function DialogoPin({
  motivo,
  onCancelar,
  onFirmar,
  error,
}: {
  motivo: string;
  onCancelar: () => void;
  onFirmar: (pin: string) => void;
  error?: string | null;
}) {
  const [pin, setPin] = useState("");

  return (
    <Marco titulo="🔒 AUTORIZACIÓN REQUERIDA" onCancelar={onCancelar}>
      <p className="text-[13px] leading-relaxed text-[var(--pos-700)]">{motivo}</p>

      <div className="my-6 flex justify-center gap-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <span
            key={i}
            className={`h-3 w-3 rounded-full ${
              i < pin.length ? "bg-[var(--pos-accent)]" : "bg-[var(--pos-divider)]"
            }`}
          />
        ))}
      </div>

      <div className="mx-auto grid max-w-[220px] grid-cols-3 gap-2">
        {["1", "2", "3", "4", "5", "6", "7", "8", "9", "✕", "0", "⌫"].map((t) => (
          <button
            key={t}
            onClick={() => {
              if (t === "⌫") setPin((p) => p.slice(0, -1));
              else if (t === "✕") setPin("");
              else if (pin.length < 6) setPin((p) => p + t);
            }}
            className="h-14 border border-[var(--pos-divider)] bg-[var(--pos-100)] tabular text-lg text-[var(--pos-text)] active:bg-[var(--pos-divider)]"
          >
            {t}
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-4 border border-[var(--pos-800)] bg-[var(--pos-800)]/10 p-2.5 text-center text-[12px] text-[var(--pos-900)]">
          {error}
        </p>
      )}

      <p className="mt-5 text-center tabular text-[10.5px] leading-relaxed text-[var(--pos-600)]">
        Esta autorización queda registrada con el nombre de quien la aprueba.
      </p>

      <button
        disabled={pin.length < 4}
        onClick={() => onFirmar(pin)}
        className="mt-4 w-full bg-[var(--pos-accent)] py-3 titular text-[13px] font-semibold tracking-[0.12em] text-white disabled:bg-[var(--pos-divider)] disabled:text-[var(--pos-500)]"
      >
        AUTORIZAR
      </button>
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={titulo}
        className="w-full max-w-md border border-[var(--pos-divider)] bg-[var(--pos-surface)] p-6 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between">
          <h2 className="titular text-[15px] tracking-[0.1em] text-[var(--pos-text)]">
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
