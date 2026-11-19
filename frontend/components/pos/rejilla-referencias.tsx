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
  enLinea = false,
  vacio = "Sin referencias para ese filtro.",
}: {
  referencias: Referencia[];
  onElegir: (r: Referencia, t: Talla) => void;
  /** Lo que se muestra viene de la TIENDA EN LÍNEA (venta con envío). Ahí la
   *  talla en cero NO se vende: no hay una prenda en la mano que desmienta
   *  al sistema, y Melonn no puede despachar lo que no tiene. */
  enLinea?: boolean;
  vacio?: string;
}) {
  if (!referencias.length) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-[13px]" style={{ color: "var(--pos-muted)" }}>
          {vacio}
        </p>
      </div>
    );
  }

  return (
    <div
      className="pos-rejilla grid min-w-0 flex-1 auto-rows-min content-start gap-[10px] overflow-y-auto pr-1"
    >
      {/* `blueprint` = la tarjeta del sistema: blanca, r18 y con sombra. El
          borde de 1px se va con la v1 — sobre el gris del fondo, borde y
          sombra juntos ensucian el canto. */}
      {referencias.map((r) => (
        <article key={r.referencia} className="blueprint p-4">
          <h3 className="titular text-[15px]">{r.nombre}</h3>

          <div className="mt-2 flex items-baseline justify-between gap-2">
            <span className="whitespace-nowrap font-mono text-[12px]" style={{ color: "var(--pos-600)" }}>
              {r.referencia}
            </span>
            {/* El tachado de la web va ENCIMA del precio, no al lado: en la
                tarjeta angosta del iPad, al lado partía la referencia. */}
            <span className="flex flex-col items-end tabular text-[13px] font-semibold leading-tight">
              {enLinea && (r.precio_lista_centavos ?? 0) > r.precio_con_iva_centavos && (
                <s className="text-[11px] font-normal" style={{ color: "var(--pos-muted)" }}>
                  {formatear(r.precio_lista_centavos ?? 0)}
                </s>
              )}
              {formatear(r.precio_con_iva_centavos)}
            </span>
          </div>

          {/**
            * Las tallas en REJILLA PROPIA, no en una fila que se estira.
            *
            * Eran una fila `flex-1`: a 1280px daban 40px de ancho y a 1024 —el
            * iPad apaisado de una caja, que es el equipo real— bajaban a 19px.
            * Cinco chips de 44 no caben en una tarjeta de 150px y no hay
            * pseudo-elemento que lo arregle: agrandar la zona sensible más allá
            * del hueco haría que pulsar la 10 registrara la 12, que es peor que
            * el problema.
            *
            * `auto-fill minmax(44px,1fr)` los deja envolver a la siguiente
            * línea manteniendo el ancho mínimo y el mismo ancho entre ellos. La
            * tarjeta crece un renglón; el catálogo conserva sus columnas.
            */}
          <div
            className="mt-3 grid gap-1.5"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(44px, 1fr))" }}
          >
            {r.tallas.map((t) => {
              const agotada = t.disponible <= 0;
              if (enLinea) {
                return (
                  <button
                    key={t.sku}
                    onClick={() => onElegir(r, t)}
                    disabled={agotada}
                    aria-label={`Talla ${t.talla}${agotada
                      ? ", agotada en la tienda en línea"
                      : `, ${t.disponible} disponibles para envío`}`}
                    className="flex h-11 w-full flex-col items-center justify-center rounded-[var(--pos-r-sm)] border border-[var(--pos-divider)] text-[14px] leading-none transition-colors duration-[var(--pos-transicion)] hover:border-[var(--pos-accent)] hover:bg-[var(--pos-100)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-[var(--pos-divider)] disabled:hover:bg-transparent"
                  >
                    <span>{t.talla}</span>
                    <span className="mt-0.5 text-[10px] tabular" style={{ color: "var(--pos-600)" }}>
                      {agotada ? "agotada" : `${t.disponible} disp.`}
                    </span>
                  </button>
                );
              }
              return (
                // LA TALLA EN CERO SE PUEDE VENDER. El inventario del sistema
                // es el de Siigo, y Siigo no siempre va al día: la prenda que
                // la cajera tiene en la mano existe aunque el sistema diga
                // cero. Bloquearla era perder la venta por un dato atrasado.
                // Se ve distinta —punteada y apagada— para que se note, el
                // carrito lo avisa, y contabilidad recibe la lista cada día.
                <button
                  key={t.sku}
                  onClick={() => onElegir(r, t)}
                  title={agotada
                    ? "El sistema la tiene en cero. Se puede vender: queda avisado a contabilidad."
                    : `${t.disponible} en stock`}
                  aria-label={`Talla ${t.talla}${agotada ? ", en cero según el sistema" : `, ${t.disponible} en stock`}`}
                  style={agotada
                    ? { borderStyle: "dashed", color: "var(--pos-muted)" }
                    : undefined}
                  // 44×44 de verdad, no una zona sensible que lo aparente. Es
                  // el control más pulsado del producto —uno por línea de cada
                  // venta, de pie y con una prenda en la otra mano— y ahí un
                  // fallo de puntería es una talla equivocada en la bolsa.
                  className="h-11 w-full rounded-[var(--pos-r-sm)] border border-[var(--pos-divider)] text-[14px] transition-colors duration-[var(--pos-transicion)] hover:border-[var(--pos-accent)] hover:bg-[var(--pos-100)]"
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
