/**
 * Dinero en el POS — centavos enteros, igual que en el backend.
 *
 * Es el espejo de `backend/modules/retail/domain/shared/dinero.py`. La misma
 * regla, por la misma razón: en este repositorio un cambio salió facturado
 * por 67.960 cuando la prenda valía 169.900, porque el precio se manipuló
 * como decimal. El error no revienta — produce un número plausible.
 *
 * En JavaScript el riesgo es peor que en Python: `0.1 + 0.2` da
 * 0.30000000000000004 y nadie avisa. Con centavos enteros eso no puede pasar
 * hasta los 90 billones de pesos, muy por encima de cualquier venta.
 *
 * REGLA: los centavos NUNCA se dividen ni se multiplican por fracciones
 * directamente. Para eso está `porcentaje()`, que redondea igual que el
 * backend (medio hacia arriba) — si redondearan distinto, el total de la
 * pantalla no coincidiría con el de la factura.
 */

export type Centavos = number;

/** Redondeo MEDIO HACIA ARRIBA, el de la facturación colombiana.
 *  `Math.round` en JS ya redondea .5 hacia arriba para positivos, pero se
 *  escribe explícito porque para negativos no lo hace y el descuento de una
 *  devolución sí los produce. */
function medioArriba(x: number): number {
  return x < 0 ? -Math.round(-x) : Math.round(x);
}

export function porcentaje(base: Centavos, tasa: number): Centavos {
  return medioArriba((base * tasa) / 100);
}

/**
 * El IVA contenido en un precio de vitrina.
 *
 * Espejo de `separar_iva` del backend. El precio ES el número redondo de la
 * etiqueta y el impuesto se LEE de él — no al revés. Guardando la base, la
 * rejilla mostraba $139.900,01 en una prenda de $139.900, porque ninguna base
 * da ese total exacto.
 */
export function ivaDe(precioConIva: Centavos, tasaIva: number): Centavos {
  if (!tasaIva) return 0;
  return precioConIva - Math.round(precioConIva / (1 + tasaIva / 100));
}

/** Reparte conservando hasta el último centavo.
 *  $100 entre 3 no son tres veces $33,33: sobra un centavo, y ese centavo
 *  tiene que ir a alguna parte o la suma de las líneas no da el total. */
export function repartir(monto: Centavos, partes: number): Centavos[] {
  if (partes <= 0) throw new Error("repartir necesita al menos una parte");
  const signo = monto < 0 ? -1 : 1;
  const abs = Math.abs(monto);
  const base = Math.floor(abs / partes);
  const resto = abs - base * partes;
  return Array.from({ length: partes }, (_, i) =>
    signo * (base + (i < resto ? 1 : 0)),
  );
}

/**
 * Para la pantalla. En COP el peso es la unidad: los centavos sólo aparecen
 * cuando existen, para no llenar el POS de ",00".
 */
export function formatear(centavos: Centavos): string {
  const signo = centavos < 0 ? "-" : "";
  const abs = Math.abs(centavos);
  const pesos = Math.floor(abs / 100);
  const cents = abs % 100;
  const entero = pesos.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return cents
    ? `${signo}$${entero},${cents.toString().padStart(2, "0")}`
    : `${signo}$${entero}`;
}

/** Desde lo que teclea la cajera ("180000", "180.000", "180 000"). */
export function desdePesosTecleados(texto: string): Centavos {
  const limpio = (texto || "").replace(/[^\d]/g, "");
  if (!limpio) return 0;
  return parseInt(limpio, 10) * 100;
}

export const cero = 0;
export const esCero = (c: Centavos) => c === 0;
export const esPositivo = (c: Centavos) => c > 0;
