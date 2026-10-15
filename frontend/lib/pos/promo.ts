/**
 * La promoción «la segunda prenda a $1.000», en la caja.
 *
 * Es la MISMA regla que `backend/modules/retail/domain/venta/promocion.py`:
 * de las prendas del listado se ordenan de mayor a menor precio y, por cada
 * par, la más barata queda en el precio de la promoción. Se cuenta por unidad.
 *
 * La caja la calcula para mostrarla y cobrar el total correcto; al cerrar, el
 * servidor la vuelve a calcular y es la suya la que vale. Por eso NO entra a
 * una línea que ya tiene un descuento a mano: serían dos descuentos encima.
 */
import type { LineaCarrito } from "./carrito";

export interface Promocion {
  id: string;
  nombre: string;
  tipo: string;
  precio_centavos: number;
  referencias: string[];
  hasta: string;
}

/** `93634-1T12` → `93634-1`. */
export function referenciaDe(sku: string): string {
  const s = (sku || "").trim().toUpperCase();
  const i = s.lastIndexOf("T");
  return i > 0 ? s.slice(0, i) : s;
}

/** Las líneas con su descuento de promoción ya puesto (`descuentoValor`). */
export function conPromocion(
  lineas: LineaCarrito[], promo: Promocion | null | undefined,
): LineaCarrito[] {
  if (!promo || new Date(promo.hasta).getTime() <= Date.now()) {
    return lineas.map((l) => ({ ...l, descuentoValor: undefined, promocionId: undefined }));
  }
  const refs = new Set(promo.referencias.map((r) => r.toUpperCase()));
  const entra = (l: LineaCarrito) =>
    !l.descuentoPct && refs.has(referenciaDe(l.sku));

  const unidades: { precio: number; orden: number; sku: string }[] = [];
  lineas.forEach((l, orden) => {
    if (!entra(l)) return;
    for (let k = 0; k < l.cantidad; k++) {
      unidades.push({ precio: l.precioConIva, orden, sku: l.sku });
    }
  });
  unidades.sort((a, b) => b.precio - a.precio || a.orden - b.orden);
  const desc = new Map<string, number>();
  for (let i = 1; i < unidades.length; i += 2) {
    const u = unidades[i];
    const rebaja = Math.max(u.precio - promo.precio_centavos, 0);
    if (rebaja) desc.set(u.sku, (desc.get(u.sku) ?? 0) + rebaja);
  }
  return lineas.map((l) => entra(l)
    ? { ...l, promocionId: promo.id, descuentoValor: desc.get(l.sku) || undefined,
        descuentoMotivo: desc.get(l.sku) ? promo.nombre : l.descuentoMotivo }
    : { ...l, descuentoValor: undefined, promocionId: undefined });
}

/** El descuento total de una línea, sea a mano (%) o de la promoción. */
export function descuentoDeLinea(l: LineaCarrito): number {
  const sub = l.precioConIva * l.cantidad;
  if (l.descuentoPct) return Math.round((sub * l.descuentoPct) / 100);
  return Math.min(l.descuentoValor ?? 0, sub);
}
