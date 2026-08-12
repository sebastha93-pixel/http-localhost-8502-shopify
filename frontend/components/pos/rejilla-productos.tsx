"use client";

import { formatear } from "@/lib/pos/dinero";
import type { Variante } from "@/lib/pos/api";

/**
 * Rejilla con foto, no lista.
 *
 * En moda la cajera reconoce la prenda por la imagen antes que por el nombre.
 * Y la talla es una tarjeta propia, no un segundo paso: buscar `92611` muestra
 * todas sus tallas y se toca la correcta.
 */
export function RejillaProductos({
  resultados,
  consulta,
  onElegir,
}: {
  resultados: Variante[];
  consulta: string;
  onElegir: (v: Variante) => void;
}) {
  if (!consulta.trim()) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="max-w-xs text-center font-mono text-xs leading-relaxed text-[#33424A]">
          Escanea una prenda o escribe una referencia.
        </p>
      </div>
    );
  }

  if (!resultados.length) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="font-mono text-xs text-[#6F92A6]">
          Nada con «{consulta}» en esta tienda.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-3 grid flex-1 auto-rows-min grid-cols-3 gap-2.5 overflow-y-auto pr-1">
      {resultados.map((v) => (
        <button
          key={v.variante_id}
          onClick={() => onElegir(v)}
          className="group border border-[#243036] bg-[#1A242A] p-2 text-left transition-colors hover:border-[#C8412B] focus:border-[#C8412B] focus:outline-none"
        >
          <div
            aria-hidden
            className="mb-2 h-16 border border-[#243036]"
            style={{
              background:
                "repeating-linear-gradient(45deg,#1F2A31 0 6px,#243036 6px 12px)",
            }}
          />
          <div className="font-mono text-[10.5px] text-[#A6BECC]">{v.sku}</div>
          <div className="mt-0.5 truncate text-[11.5px] text-[#F4F3F0]">
            {v.nombre} {v.color && `· ${v.color}`}
          </div>
          <div className="mt-1 font-mono text-[12.5px] font-semibold tabular-nums">
            {formatear(v.precio_con_iva_centavos)}
          </div>
          <Disponibilidad n={v.disponible} />
        </button>
      ))}
    </div>
  );
}

/** Agotado se muestra pero NO se esconde: la prenda física puede estar en la
 *  mano de la clienta aunque el dato diga que no (INV-I2). */
function Disponibilidad({ n }: { n: number }) {
  if (n <= 0)
    return <div className="mt-1 text-[10.5px] text-[#6F92A6]">○ agotado aquí</div>;
  if (n <= 1)
    return <div className="mt-1 text-[10.5px] text-[#B08C2E]">● {n} · último</div>;
  return <div className="mt-1 text-[10.5px] text-[#6E9169]">● {n} disponibles</div>;
}
