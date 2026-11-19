/**
 * Venta con envío a domicilio: lo que la pantalla necesita y no es pantalla.
 *
 * La vendedora vende lo que hay en la TIENDA EN LÍNEA (la bodega de Melonn),
 * no lo de su estante. Ver docs/superpowers/specs/2026-11-13-pedido-con-envio-design.md
 */
import type { Entrega, ProductoEnLinea, Referencia } from "./api";

/** La tasa con la que la web cobra todo lo que vende, EN PORCENTAJE y con
 *  el mismo formato que trae el catálogo de la tienda (`"19.00"`). Estuvo como
 *  `"0.19"` y la caja mostraba «IVA incluido $303» en una prenda de $159.900
 *  (visto en la demo del 2026-11-19). El servidor calcula con la suya; esto es
 *  lo que ve la vendedora. */
const IVA_WEB = "19.00";

/**
 * Lo de la tienda en línea, con la forma que pinta la rejilla.
 *
 * UNA TARJETA POR PRODUCTO Y PRECIO. Casi siempre todas las tallas de un
 * producto valen lo mismo; cuando no, cada precio va en su tarjeta, porque la
 * tarjeta tiene UN precio y cobrar una talla con el precio de otra lo rechaza
 * el servidor («el precio cambió»).
 */
export function comoReferencias(productos: ProductoEnLinea[]): Referencia[] {
  const salida: Referencia[] = [];
  for (const p of productos) {
    const porPrecio = new Map<number, ProductoEnLinea["variantes"]>();
    for (const v of p.variantes) {
      if (!v.activo || !v.sku) continue;
      const grupo = porPrecio.get(v.precio_centavos) ?? [];
      grupo.push(v);
      porPrecio.set(v.precio_centavos, grupo);
    }
    for (const [precio, variantes] of porPrecio) {
      // La referencia es el SKU sin la talla (`92633-1T10` → `92633-1`).
      const ref = variantes[0].sku.replace(/T[^T]*$/i, "") || variantes[0].sku;
      salida.push({
        referencia: porPrecio.size > 1 ? `${ref} · ${precio / 100}` : ref,
        nombre: p.nombre || variantes[0].nombre,
        color: "",
        categoria: "",
        precio_con_iva_centavos: precio,
        tasa_iva: IVA_WEB,
        precio_lista_centavos: Math.max(...variantes.map((v) => v.precio_lista_centavos)),
        tallas: variantes.map((v) => ({
          variante_id: v.sku, sku: v.sku, talla: v.talla, disponible: v.disponible,
        })),
      });
    }
  }
  return salida;
}

export const ENTREGA_VACIA: Entrega = {
  destinatario: "", telefono: "", direccion: "", complemento: "",
  ciudad: "", departamento: "",
};

/** Lo que falta para poder despachar, en palabras de la vendedora. Vacío =
 *  completa. El servidor exige lo mismo; esto evita llegar al rechazo con la
 *  clienta enfrente. */
export function faltaEnLaEntrega(e: Entrega): string[] {
  const falta: string[] = [];
  if (e.destinatario.trim().length < 3) falta.push("quién recibe");
  if (e.telefono.replace(/\D/g, "").length < 10) falta.push("un celular de 10 dígitos");
  if (e.direccion.trim().length < 5) falta.push("la dirección");
  if (e.ciudad.trim().length < 3) falta.push("la ciudad");
  if (!e.departamento.trim()) falta.push("el departamento");
  return falta;
}

/** Los departamentos de Colombia, como los escribe Melonn. */
export const DEPARTAMENTOS = [
  "Amazonas", "Antioquia", "Arauca", "Atlántico", "Bogotá D.C.", "Bolívar",
  "Boyacá", "Caldas", "Caquetá", "Casanare", "Cauca", "Cesar", "Chocó",
  "Córdoba", "Cundinamarca", "Guainía", "Guaviare", "Huila", "La Guajira",
  "Magdalena", "Meta", "Nariño", "Norte de Santander", "Putumayo", "Quindío",
  "Risaralda", "San Andrés y Providencia", "Santander", "Sucre", "Tolima",
  "Valle del Cauca", "Vaupés", "Vichada",
];

/** Las ciudades de donde más se pide: sugerencias, no una lista cerrada. */
export const CIUDADES_FRECUENTES = [
  "Medellín", "Envigado", "Sabaneta", "Itagüí", "Bello", "La Estrella",
  "Rionegro", "Bogotá", "Cali", "Barranquilla", "Bucaramanga", "Pereira",
  "Manizales", "Cartagena",
];
