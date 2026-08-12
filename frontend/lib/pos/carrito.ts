/** Una línea del carrito, mientras vive en el dispositivo.
 *
 * El precio se CONGELA al agregar la prenda: si el catálogo cambia a mitad de
 * la venta, no puede cambiar lo que la cajera ya le dijo a la clienta. Es la
 * misma regla que INV-F5 en el backend.
 */
export interface LineaCarrito {
  sku: string;
  descripcion: string;
  /** El diseno la muestra aparte: «Talla 24 · $189.900». */
  talla: string;
  cantidad: number;
  /** El precio de la ETIQUETA, con IVA incluido.
   *
   *  Antes se guardaba la base sin IVA y la pantalla se lo volvía a sumar.
   *  Ese viaje no siempre regresa: $139.900 salía como $139.900,01. Ahora el
   *  precio ES el de vitrina y el impuesto se lee de él. */
  precioConIva: number;
  tasaIva: number;
  /** Lo que había al agregarla. Se muestra, no se impone: la prenda física
   *  que la clienta tiene en la mano existe aunque el dato diga que no. */
  disponible: number;
  /** Descuento aplicado, si lo hay. `autorizadoPor` sólo existe cuando superó
   *  el tope de quien lo aplicó — y ese nombre llega hasta la auditoría. */
  descuentoPct?: number;
  descuentoMotivo?: string;
  autorizadoPor?: string | null;
}
