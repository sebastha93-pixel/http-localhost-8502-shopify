"use client";

import { formatear } from "@/lib/pos/dinero";
import type { LineaCarrito } from "@/lib/pos/carrito";
import type { Cliente } from "@/lib/pos/api";

/**
 * Carrito — 360px fijos, con la estructura del handoff:
 * cabecera + clienta + líneas + totales + botón sólido de cobro.
 *
 * El botón primario es el ÚNICO objeto sólido de la pantalla. Todo lo demás
 * son bordes finos. Si aparece un segundo relleno de acento, el sistema se
 * rompió.
 */
export function CarritoPanel({
  lineas,
  totales,
  aviso,
  onCantidad,
  onDescuento,
  onCobrar,
  cliente,
  onAsignarCliente,
  onQuitarCliente,
}: {
  lineas: LineaCarrito[];
  totales: { base: number; iva: number; descuento: number; total: number };
  aviso: string | null;
  onCantidad: (sku: string, cantidad: number) => void;
  onDescuento: (sku: string) => void;
  onCobrar: () => void;
  cliente: Cliente | null;
  onAsignarCliente: () => void;
  onQuitarCliente: () => void;
}) {
  const articulos = lineas.reduce((n, l) => n + l.cantidad, 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between">
        <h2 className="titular text-[16px]">Venta actual</h2>
        <span
          className="kicker rounded-[var(--pos-r-sm)] px-2 py-1"
          style={{ background: "var(--pos-200)", color: "var(--pos-700)" }}
        >
          {articulos} art.
        </span>
      </div>

      {cliente ? (
        <div
          className="mt-3 flex items-center justify-between rounded-[var(--pos-r-md)] border px-3 py-2"
          style={{ borderColor: "var(--pos-divider)" }}
        >
          <div className="min-w-0">
            <p className="truncate text-[13px]">{cliente.nombre}</p>
            <p className="text-[12px]" style={{ color: "var(--pos-600)" }}>
              {cliente.tipo_documento} {cliente.numero_documento}
              {cliente.telefono && ` · ${cliente.telefono}`}
            </p>
          </div>
          <button
            onClick={onQuitarCliente}
            className="shrink-0 text-[12px] underline"
            style={{ color: "var(--pos-600)" }}
          >
            quitar
          </button>
        </div>
      ) : (
        <button
          onClick={onAsignarCliente}
          className="mt-3 h-11 w-full rounded-[var(--pos-r-md)] border border-dashed text-[13px] transition-colors hover:bg-[var(--pos-100)]"
          style={{ borderColor: "var(--pos-400)", color: "var(--pos-700)" }}
          title="Necesaria para la factura electrónica"
        >
          + Asignar clienta
        </button>
      )}

      <div className="my-3 min-h-0 flex-1 overflow-y-auto">
        {lineas.length === 0 ? (
          <p
            className="mt-10 px-4 text-center text-[13px] leading-relaxed"
            style={{ color: "var(--pos-muted)" }}
          >
            Toca una talla para agregar artículos a la venta.
          </p>
        ) : (
          lineas.map((l) => (
            <div
              key={l.sku}
              className="border-b py-2.5"
              style={{ borderColor: "var(--pos-divider)" }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-[13px]">{l.descripcion}</p>
                  <p className="text-[12px]" style={{ color: "var(--pos-600)" }}>
                    Talla {l.talla} · {formatear(conIvaUnidad(l))}
                  </p>
                </div>
                <span className="tabular shrink-0 text-[13px]">
                  {formatear(totalLinea(l))}
                </span>
              </div>

              <div className="mt-2 flex items-center gap-1.5">
                <Paso onClick={() => onCantidad(l.sku, l.cantidad - 1)} etiqueta={`Quitar una unidad de ${l.sku}`}>−</Paso>
                <span className="tabular w-6 text-center text-[13px]">{l.cantidad}</span>
                <Paso onClick={() => onCantidad(l.sku, l.cantidad + 1)} etiqueta={`Agregar una unidad de ${l.sku}`}>+</Paso>
                <button
                  onClick={() => onDescuento(l.sku)}
                  aria-label={`Aplicar descuento a ${l.sku}`}
                  className="ml-1 h-11 min-w-11 rounded-[var(--pos-r-sm)] border px-2 text-[13px] transition-colors duration-[var(--pos-transicion)] hover:bg-[var(--pos-100)]"
                  style={{ borderColor: "var(--pos-divider)", color: "var(--pos-700)" }}
                >
                  %
                </button>
              </div>

              {l.descuentoPct ? (
                <p className="mt-1.5 text-[12px]" style={{ color: "var(--pos-700)" }}>
                  −{l.descuentoPct}% · {l.descuentoMotivo}
                  {l.autorizadoPor && ` · firmó ${l.autorizadoPor}`}
                </p>
              ) : null}

              {l.disponible <= 0 && (
                <p className="mt-1.5 text-[12px]" style={{ color: "var(--pos-700)" }}>
                  ⚠ El sistema no la tiene en esta tienda. Se vende igual y queda alertado.
                </p>
              )}
            </div>
          ))
        )}
      </div>

      {aviso && (
        <div
          className="mb-3 rounded-[var(--pos-r-sm)] border p-2.5 text-[12px] leading-snug"
          style={{ borderColor: "var(--pos-700)", color: "var(--pos-900)", background: "var(--pos-100)" }}
        >
          {aviso}
        </div>
      )}

      <div style={{ borderTop: "1px solid var(--pos-divider)" }} className="pt-3">
        {/* Subtotal = suma de las ETIQUETAS, antes de descuento. El IVA va
            debajo como línea informativa, no como algo que se suma: ya está
            dentro. Mostrar aquí la base sin IVA se lee como si el impuesto se
            estuviera agregando, que es justo lo contrario. */}
        <Fila etiqueta="Subtotal" valor={totales.total + totales.descuento} />
        {totales.descuento > 0 && (
          <Fila etiqueta="Descuento" valor={-totales.descuento} />
        )}
        <Fila etiqueta="IVA incluido (19%)" valor={totales.iva} tenue />

        <div className="mt-2 flex items-baseline justify-between">
          <span className="titular text-[16px]">Total</span>
          <b className="titular tabular text-[26px]" style={{ fontWeight: 700 }}>
            {formatear(totales.total)}
          </b>
        </div>
      </div>

      <button
        onClick={onCobrar}
        disabled={!lineas.length}
        className="blueprint mt-3 h-14 w-full text-[14px] font-semibold tracking-[0.1em] transition-opacity"
        style={{
          background: lineas.length ? "var(--pos-accent)" : "var(--pos-300)",
          color: lineas.length ? "#fff" : "var(--pos-600)",
          borderColor: "transparent",
        }}
      >
        <i className="corner tl" aria-hidden /><i className="corner tr" aria-hidden />
        <i className="corner bl" aria-hidden /><i className="corner br" aria-hidden />
        COBRAR {formatear(totales.total)}
      </button>
    </div>
  );
}

/** Ya es el precio de la etiqueta: no hay nada que sumar. */
const conIvaUnidad = (l: LineaCarrito) => l.precioConIva;

function totalLinea(l: LineaCarrito) {
  const sub = l.precioConIva * l.cantidad;
  const desc = l.descuentoPct ? Math.round((sub * l.descuentoPct) / 100) : 0;
  return sub - desc;
}

function Fila({ etiqueta, valor, tenue }: { etiqueta: string; valor: number; tenue?: boolean }) {
  return (
    <div
      className="tabular flex justify-between py-0.5 text-[13px]"
      style={{ color: tenue ? "var(--pos-muted)" : "var(--pos-700)" }}
    >
      <span>{etiqueta}</span>
      <span>{formatear(valor)}</span>
    </div>
  );
}

function Paso({ onClick, children, etiqueta }: { onClick: () => void; children: React.ReactNode; etiqueta: string }) {
  return (
    <button
      onClick={onClick}
      aria-label={etiqueta}
      className="h-11 w-11 rounded-[var(--pos-r-sm)] border text-[15px] transition-colors duration-[var(--pos-transicion)] hover:bg-[var(--pos-100)]"
      style={{ borderColor: "var(--pos-divider)", color: "var(--pos-800)" }}
    >
      {children}
    </button>
  );
}
