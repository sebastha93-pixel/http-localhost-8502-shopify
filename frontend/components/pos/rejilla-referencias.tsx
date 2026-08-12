"use client";

import { formatear } from "@/lib/pos/dinero";
import type { Referencia, Talla } from "@/lib/pos/api";

/**
 * Rejilla del catálogo — una tarjeta por REFERENCIA con sus tallas dentro.
 *
 * Viene del handoff, y es mejor que lo que yo había dibujado (una tarjeta por
 * talla, con foto). En denim la foto de cinco tallas es la misma foto: separarlas
 * sólo multiplica tarjetas y scroll. Así la cajera toca la talla donde ya está
 * mirando.
 *
 * DOS COSAS QUE EL PROTOTIPO NO PODÍA SABER:
 *
 * Las tallas NO son cinco fijas. El diseño dibuja 24–32; los SKU reales de
 * MALE parsean a 4, 6, 8, 10, 12. Los chips se generan de los datos.
 *
 * La talla agotada se muestra deshabilitada, no se oculta — tal como pide el
 * handoff. Esconderla haría creer que esa talla no existe, cuando lo que pasa
 * es que hoy no hay.
 */
export function RejillaReferencias({
  referencias,
  onElegir,
}: {
  referencias: Referencia[];
  onElegir: (r: Referencia, t: Talla) => void;
}) {
  if (!referencias.length) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-[13px]" style={{ color: "var(--pos-500)" }}>
          Sin referencias para ese filtro.
        </p>
      </div>
    );
  }

  return (
    <div
      className="pos-rejilla grid min-w-0 flex-1 auto-rows-min content-start gap-[10px] overflow-y-auto pr-1"
    >
      {referencias.map((r) => (
        <article
          key={r.referencia}
          className="rounded-[var(--pos-r-md)] border p-[13.6px]"
          style={{ borderColor: "color-mix(in srgb, var(--pos-text) 10%, transparent)" }}
        >
          <h3 className="titular text-[15px]">{r.nombre}</h3>

          <div className="mt-2 flex items-baseline justify-between">
            <span className="font-mono text-[11px]" style={{ color: "var(--pos-600)" }}>
              {r.referencia}
            </span>
            <span className="tabular text-[13px] font-semibold">
              {formatear(r.precio_con_iva_centavos)}
            </span>
          </div>

          <div className="mt-3 flex gap-1.5">
            {r.tallas.map((t) => {
              const agotada = t.disponible <= 0;
              return (
                <button
                  key={t.sku}
                  disabled={agotada}
                  onClick={() => onElegir(r, t)}
                  title={agotada ? "Agotada" : `${t.disponible} en stock`}
                  aria-label={`Talla ${t.talla}${agotada ? ", agotada" : `, ${t.disponible} en stock`}`}
                  className="h-10 flex-1 rounded-[var(--pos-r-sm)] border text-[13px] transition-colors enabled:hover:border-[var(--pos-accent)] enabled:hover:bg-[var(--pos-100)]"
                  style={{
                    borderColor: "color-mix(in srgb, var(--pos-text) 12%, transparent)",
                  }}
                >
                  {t.talla}
                </button>
              );
            })}
          </div>
        </article>
      ))}
    </div>
  );
}
