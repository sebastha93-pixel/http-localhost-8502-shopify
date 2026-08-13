/**
 * La tirilla armada EN EL DISPOSITIVO, para cuando no hay red.
 *
 * Normalmente la tirilla se lee de la base: es el comprobante de lo que quedó
 * REGISTRADO, y si el servidor guardó otra cosa el papel tiene que delatarlo.
 * Sin red no hay nada registrado todavía, así que ese razonamiento no aplica —
 * y la alternativa es que la clienta se vaya sin papel justo cuando más falta
 * hace un comprobante.
 *
 * LO QUE NO PUEDE PASAR: que este papel diga un número distinto al que después
 * guarde el servidor. Por eso el IVA se separa **por línea y con el mismo
 * redondeo** que el backend, y no sobre el total: `separar_iva` corre línea a
 * línea allá, y hacerlo aquí sobre la suma da diferencias de centavos. Una
 * tirilla que no cuadra con el sistema es peor que no imprimir, porque la
 * clienta la trae de vuelta y nadie sabe cuál de los dos números es el bueno.
 *
 * NUNCA se marca como factura. Offline no hay documento emitido —ni puede
 * haberlo, emitirlo requiere Siigo— así que sale como comprobante y lo dice.
 */
import type { ContextoCaja, Tirilla } from "@/lib/pos/api";
import { ivaDe } from "@/lib/pos/dinero";
import type { LineaCarrito } from "@/lib/pos/carrito";

export function armarTirillaLocal(opciones: {
  contexto: ContextoCaja;
  numero: string;
  cajera: string;
  lineas: LineaCarrito[];
  pagos: { nombre: string; monto_centavos: number }[];
  clienteNombre?: string | null;
  clienteDocumento?: string | null;
  cuando?: Date;
}): Tirilla {
  const { contexto: c } = opciones;
  const cuando = opciones.cuando ?? new Date();

  let subtotal = 0;
  let descuento = 0;
  let iva = 0;
  let unidades = 0;

  const lineas = opciones.lineas.map((l) => {
    const bruto = l.precioConIva * l.cantidad;
    const desc = l.descuentoPct ? Math.round((bruto * l.descuentoPct) / 100) : 0;
    const total = bruto - desc;
    subtotal += bruto;
    descuento += desc;
    // Por LÍNEA, igual que el backend. Sobre el total daría otro centavo.
    iva += ivaDe(total, Number(l.tasaIva));
    unidades += l.cantidad;
    return {
      sku: l.sku,
      descripcion: `${l.descripcion} · Talla ${l.talla}`,
      cantidad: l.cantidad,
      precio_unitario_centavos: l.precioConIva,
      descuento_centavos: desc,
      descuento_motivo: l.descuentoMotivo ?? null,
      total_centavos: total,
    };
  });

  const total = subtotal - descuento;
  const pagado = opciones.pagos.reduce((a, p) => a + p.monto_centavos, 0);

  return {
    razon_social: c.razon_social || c.tienda_nombre,
    nit: c.nit,
    direccion: c.direccion,
    telefono: c.telefono,
    tienda_nombre: c.tienda_nombre,
    // Aunque la tienda TENGA resolución, sin documento emitido esto no es una
    // factura. Mandar la resolución aquí haría que el papel la imprimiera.
    resolucion_dian: null,
    mensaje: c.mensaje_tirilla ?? null,
    numero: opciones.numero,
    fecha: formatearFecha(cuando),
    caja_nombre: c.caja_nombre,
    cajera_nombre: opciones.cajera,
    cliente_nombre: opciones.clienteNombre ?? null,
    cliente_documento: opciones.clienteDocumento ?? null,
    lineas,
    pagos: opciones.pagos.map((p) => ({
      nombre: p.nombre, monto_centavos: p.monto_centavos, referencia: null,
    })),
    subtotal_centavos: subtotal,
    descuento_centavos: descuento,
    total_centavos: total,
    base_gravable_centavos: total - iva,
    iva_centavos: iva,
    pagado_centavos: pagado,
    vuelto_centavos: Math.max(0, pagado - total),
    unidades,
    estado_fiscal: "pendiente",
    documento_fiscal: null,
    cufe: null,
    anulada: false,
    qr_contenido: null,
    qr_ruta: null,
    qr_modulos: 0,
    es_documento_fiscal: false,
  };
}

/** `DD/MM/YYYY HH:MM`, el mismo formato que arma el servidor.
 *  Se construye a mano y no con `toLocaleString`, que cambia de forma según
 *  la configuración del equipo — y dos tirillas de la misma tienda con
 *  formatos distintos de fecha se leen como de sistemas distintos. */
function formatearFecha(d: Date): string {
  const dos = (n: number) => String(n).padStart(2, "0");
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)}/${d.getFullYear()} `
       + `${dos(d.getHours())}:${dos(d.getMinutes())}`;
}
