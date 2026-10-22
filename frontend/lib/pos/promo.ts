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
  /** `segunda_a_precio` (la segunda a $1.000), `porcentaje` (10 % en todo)
   *  o `regalo_por_monto` (la pañoleta desde $149.900). */
  tipo: string;
  precio_centavos: number;
  porcentaje?: number | null;
  /** Para el regalo: desde cuánto en prendas, ya con sus descuentos. */
  minimo_centavos?: number | null;
  referencias: string[];
  /** Las que NO llevan el porcentaje: las rebajadas. */
  excluidas?: string[];
  hasta: string;
}

/** `93634-1T12` → `93634-1`. */
export function referenciaDe(sku: string): string {
  const s = (sku || "").trim().toUpperCase();
  const i = s.lastIndexOf("T");
  return i > 0 ? s.slice(0, i) : s;
}

/** Las líneas con su descuento de promoción ya puesto (`descuentoValor`).
 *
 * DOS A LA VEZ (2026-10-15): la segunda a $1.000 para las del listado y un
 * porcentaje para todo lo demás, en la misma compra. Una prenda está en UNA
 * sola. Lo que ya tiene un descuento a mano no entra a ninguna. */
export function conPromocion(
  lineas: LineaCarrito[],
  promos: Promocion[] | Promocion | null | undefined,
): LineaCarrito[] {
  const ahora = Date.now();
  const vigentes = (Array.isArray(promos) ? promos : promos ? [promos] : [])
    .filter((p) => new Date(p.hasta).getTime() > ahora);
  const segunda = vigentes.find((p) => p.tipo === "segunda_a_precio");
  const pct = vigentes.find((p) => p.tipo === "porcentaje" && p.porcentaje);
  const regalo = vigentes.find((p) => p.tipo === "regalo_por_monto" && p.minimo_centavos);
  const limpias = lineas.map((l) => ({ ...l, descuentoValor: undefined, promocionId: undefined }));
  if (!segunda && !pct && !regalo) return limpias;
  const refsRegalo = new Set((regalo?.referencias ?? []).map((r) => r.toUpperCase()));
  const esRegalo = (l: LineaCarrito) => refsRegalo.has(referenciaDe(l.sku));

  const refs = new Set((segunda?.referencias ?? []).map((r) => r.toUpperCase()));
  const excluidas = new Set((pct?.excluidas ?? []).map((r) => r.toUpperCase()));
  const enSegunda = (l: LineaCarrito) =>
    Boolean(segunda) && !l.descuentoPct && refs.has(referenciaDe(l.sku));

  const unidades: { precio: number; orden: number; sku: string }[] = [];
  limpias.forEach((l, orden) => {
    if (!enSegunda(l)) return;
    for (let k = 0; k < l.cantidad; k++) {
      unidades.push({ precio: l.precioConIva, orden, sku: l.sku });
    }
  });
  unidades.sort((a, b) => b.precio - a.precio || a.orden - b.orden);
  const desc = new Map<string, number>();
  for (let i = 1; i < unidades.length; i += 2) {
    const u = unidades[i];
    const rebaja = Math.max(u.precio - (segunda?.precio_centavos ?? 0), 0);
    if (rebaja) desc.set(u.sku, (desc.get(u.sku) ?? 0) + rebaja);
  }

  const conLasOtras = limpias.map((l) => {
    if (enSegunda(l)) {
      const d = desc.get(l.sku);
      return { ...l, promocionId: segunda!.id, descuentoValor: d || undefined,
               descuentoMotivo: d ? segunda!.nombre : l.descuentoMotivo };
    }
    const ref = referenciaDe(l.sku);
    if (pct && !l.descuentoPct && !refs.has(ref) && !excluidas.has(ref)
        && !(regalo && esRegalo(l))) {
      const d = Math.round((l.precioConIva * l.cantidad * (pct.porcentaje ?? 0)) / 100);
      return { ...l, promocionId: pct.id, descuentoValor: d || undefined,
               descuentoMotivo: pct.nombre };
    }
    return l;
  });

  // El regalo, como en el servidor: UNA unidad en $0 si lo demás —ya con sus
  // descuentos, sin contar lo que se regala— llega al mínimo.
  if (!regalo || !llegaAlRegalo(conLasOtras, regalo)) return conLasOtras;
  const i = conLasOtras.findIndex((l) => esRegalo(l) && !l.descuentoPct);
  if (i < 0) return conLasOtras;
  return conLasOtras.map((l, k) => k !== i ? l : {
    ...l, promocionId: regalo.id, descuentoValor: l.precioConIva,
    descuentoMotivo: regalo.nombre });
}

/** Lo que se paga por las prendas, sin contar lo que se regala. */
function baseDelRegalo(lineas: LineaCarrito[], regalo: Promocion): number {
  const refs = new Set(regalo.referencias.map((r) => r.toUpperCase()));
  return lineas
    .filter((l) => !refs.has(referenciaDe(l.sku)))
    .reduce((s, l) => s + l.precioConIva * l.cantidad - descuentoDeLinea(l), 0);
}

function llegaAlRegalo(lineas: LineaCarrito[], regalo: Promocion): boolean {
  return baseDelRegalo(lineas, regalo) >= (regalo.minimo_centavos ?? Infinity);
}

/** El aviso para la caja: la compra ya llegó y falta escanear el regalo. */
export function regaloPendiente(
  lineas: LineaCarrito[],
  promos: Promocion[] | null | undefined,
): Promocion | null {
  const regalo = (promos ?? []).find((p) => p.tipo === "regalo_por_monto"
    && p.minimo_centavos && new Date(p.hasta).getTime() > Date.now());
  if (!regalo || !llegaAlRegalo(lineas, regalo)) return null;
  const refs = new Set(regalo.referencias.map((r) => r.toUpperCase()));
  return lineas.some((l) => refs.has(referenciaDe(l.sku))) ? null : regalo;
}

/** El descuento total de una línea, sea a mano (%) o de la promoción. */
export function descuentoDeLinea(l: LineaCarrito): number {
  const sub = l.precioConIva * l.cantidad;
  if (l.descuentoPct) return Math.round((sub * l.descuentoPct) / 100);
  return Math.min(l.descuentoValor ?? 0, sub);
}
