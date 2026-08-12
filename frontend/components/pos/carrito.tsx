"use client";

import { formatear } from "@/lib/pos/dinero";
import type { LineaCarrito } from "@/lib/pos/carrito";

/**
 * El carrito ocupa un tercio fijo de la pantalla. No colapsa, no se esconde:
 * el total es el número que la clienta pregunta.
 */
export function Carrito({
  lineas,
  totales,
  aviso,
  onCantidad,
  onQuitar,
  onCobrar,
}: {
  lineas: LineaCarrito[];
  totales: { base: number; iva: number; total: number };
  aviso: string | null;
  onCantidad: (sku: string, cantidad: number) => void;
  onQuitar: (sku: string) => void;
  onCobrar: () => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-dashed border-[#243036] pb-2 font-mono text-[11px] tracking-widest text-[#6F92A6]">
        TICKET EN CURSO
      </div>

      <div className="flex-1 overflow-y-auto">
        {lineas.length === 0 ? (
          <p className="mt-8 text-center font-mono text-xs text-[#33424A]">
            Sin prendas todavía.
          </p>
        ) : (
          lineas.map((l) => (
            <div key={l.sku} className="border-b border-[#243036] py-2.5">
              <div className="text-[12.5px] text-[#F4F3F0]">{l.descripcion}</div>
              <div className="mb-1.5 mt-0.5 font-mono text-[10.5px] text-[#6F92A6]">
                {l.sku}
              </div>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 font-mono text-xs">
                  <Boton onClick={() => onCantidad(l.sku, l.cantidad - 1)} etiqueta={`Quitar una unidad de ${l.sku}`}>−</Boton>
                  <span className="w-5 text-center tabular-nums">{l.cantidad}</span>
                  <Boton onClick={() => onCantidad(l.sku, l.cantidad + 1)} etiqueta={`Agregar una unidad de ${l.sku}`}>+</Boton>
                  <button
                    onClick={() => onQuitar(l.sku)}
                    aria-label={`Eliminar ${l.sku} del ticket`}
                    className="ml-1 px-1 text-[#6F92A6] hover:text-[#C8412B]"
                  >
                    🗑
                  </button>
                </div>
                <span className="font-mono text-[13px] tabular-nums">
                  {formatear(
                    l.precioUnitarioSinIva * l.cantidad +
                      Math.round((l.precioUnitarioSinIva * l.cantidad * l.tasaIva) / 100),
                  )}
                </span>
              </div>
              {l.disponible <= 0 && (
                <div className="mt-1.5 font-mono text-[10px] text-[#B08C2E]">
                  ⚠ El sistema no la tiene en esta tienda. Se vende igual y queda alertado.
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {aviso && (
        <div className="my-2 border border-[#B4543F] bg-[#B4543F]/10 p-2.5 text-[12px] leading-snug text-[#D4785E]">
          {aviso}
        </div>
      )}

      <div className="pt-2">
        <Fila etiqueta="Base" valor={totales.base} />
        <Fila etiqueta="IVA" valor={totales.iva} />
        <div className="mt-2 flex items-baseline justify-between border-t-[1.5px] border-dashed border-[#C8412B]/60 pt-2">
          <span className="font-display text-[11px] tracking-[0.14em] text-[#6F92A6]">
            TOTAL
          </span>
          <b className="font-mono text-[30px] font-semibold tabular-nums tracking-tight">
            {formatear(totales.total)}
          </b>
        </div>
      </div>

      <button
        onClick={onCobrar}
        disabled={!lineas.length}
        className="mt-3 bg-[#C8412B] py-3.5 font-display text-[13.5px] font-semibold tracking-[0.12em] text-white disabled:cursor-not-allowed disabled:bg-[#243036] disabled:text-[#4A5C66]"
      >
        COBRAR · F4
      </button>
    </div>
  );
}

function Fila({ etiqueta, valor }: { etiqueta: string; valor: number }) {
  return (
    <div className="flex justify-between py-0.5 font-mono text-[11.5px] tabular-nums text-[#A6BECC]">
      <span>{etiqueta}</span>
      <span>{formatear(valor)}</span>
    </div>
  );
}

function Boton({ onClick, children, etiqueta }: { onClick: () => void; children: React.ReactNode; etiqueta: string }) {
  return (
    <button
      onClick={onClick}
      aria-label={etiqueta}
      className="inline-flex h-7 w-7 items-center justify-center border border-[#243036] bg-[#1A242A] text-[#A6BECC] hover:border-[#6F92A6]"
    >
      {children}
    </button>
  );
}
