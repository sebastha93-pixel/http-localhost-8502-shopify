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
      <p className="font-mono text-[11px] text-[#6F92A6]">
        {sku} · {formatear(base)}
      </p>

      <div className="mt-4 grid grid-cols-5 gap-2">
        {RAPIDOS.map((p) => (
          <button
            key={p}
            onClick={() => setPct(p)}
            className={`border py-2.5 font-mono text-[13px] ${
              pct === p
                ? "border-[#C8412B] bg-[#C8412B]/15 text-[#F4F3F0]"
                : "border-[#243036] bg-[#1A242A] text-[#A6BECC]"
            }`}
          >
            {p}%
            <span className="mt-0.5 block text-[9px]">
              {p > tope ? "🔒" : "✓"}
            </span>
          </button>
        ))}
      </div>

      <label className="mt-4 block font-display text-[10.5px] tracking-[0.12em] text-[#6F92A6]">
        MOTIVO (OBLIGATORIO)
      </label>
      <input
        value={motivo}
        onChange={(e) => setMotivo(e.target.value)}
        placeholder="Prenda con defecto menor"
        className="mt-1 w-full border border-[#243036] bg-[#1A242A] px-3 py-2.5 text-[13px] text-[#F4F3F0] outline-none focus:border-[#C8412B]"
      />

      <div className="mt-4 flex items-baseline justify-between font-mono text-[12px]">
        <span className="text-[#6F92A6]">Tu tope: {tope}%</span>
        <span className="text-[#F4F3F0]">
          −{formatear(monto)} → {formatear(base - monto)}
        </span>
      </div>

      {sobreTope && (
        <p className="mt-3 border border-[#B08C2E] bg-[#B08C2E]/10 p-2.5 text-[11.5px] leading-snug text-[#C6A047]">
          🔒 Supera tu tope. Al aplicarlo se pedirá el PIN de un supervisor, y
          su nombre queda registrado.
        </p>
      )}

      <button
        disabled={!motivoValido}
        onClick={() => onAplicar(pct, motivo.trim())}
        className="mt-4 w-full bg-[#C8412B] py-3 font-display text-[13px] font-semibold tracking-[0.12em] text-white disabled:bg-[#243036] disabled:text-[#4A5C66]"
      >
        {sobreTope ? "APLICAR CON AUTORIZACIÓN" : "APLICAR"}
      </button>
      {!motivoValido && (
        <p className="mt-2 text-center font-mono text-[10.5px] text-[#6F92A6]">
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
      <p className="text-[13px] leading-relaxed text-[#A6BECC]">{motivo}</p>

      <div className="my-6 flex justify-center gap-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <span
            key={i}
            className={`h-3 w-3 rounded-full ${
              i < pin.length ? "bg-[#C8412B]" : "bg-[#243036]"
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
            className="h-14 border border-[#243036] bg-[#1A242A] font-mono text-lg text-[#F4F3F0] active:bg-[#243036]"
          >
            {t}
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-4 border border-[#B4543F] bg-[#B4543F]/10 p-2.5 text-center text-[12px] text-[#D4785E]">
          {error}
        </p>
      )}

      <p className="mt-5 text-center font-mono text-[10.5px] leading-relaxed text-[#6F92A6]">
        Esta autorización queda registrada con el nombre de quien la aprueba.
      </p>

      <button
        disabled={pin.length < 4}
        onClick={() => onFirmar(pin)}
        className="mt-4 w-full bg-[#C8412B] py-3 font-display text-[13px] font-semibold tracking-[0.12em] text-white disabled:bg-[#243036] disabled:text-[#4A5C66]"
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
        className="w-full max-w-md border border-[#243036] bg-[#131B1F] p-6 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between">
          <h2 className="font-display text-[15px] tracking-[0.1em] text-[#F4F3F0]">
            {titulo}
          </h2>
          <button
            onClick={onCancelar}
            aria-label="Cerrar"
            className="text-[#6F92A6] hover:text-[#F4F3F0]"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
