/**
 * Cliente del API del POS.
 *
 * Envuelve el cliente del ERP para heredar el JWT y la sesión deslizante, y
 * le agrega lo único que el POS necesita distinto: distinguir «falta
 * autorización» de «hay un error». No son lo mismo en pantalla — uno abre el
 * diálogo del PIN, el otro pinta un error rojo.
 */
import { api, ApiError } from "@/lib/api";

export interface Variante {
  variante_id: string;
  sku: string;
  referencia: string;
  talla: string;
  color: string;
  nombre: string;
  precio_base_centavos: number;
  precio_con_iva_centavos: number;
  disponible: number;
  es_escaneo: boolean;
}

export interface LineaEnvio {
  sku: string;
  cantidad: number;
  precio_unitario_centavos: number;
  tasa_iva: string;
  descripcion: string;
  descuento_porcentaje?: string;
  descuento_motivo?: string;
  autorizado_por?: string;
}

export interface Ticket {
  venta_id: string;
  numero: string;
  total_centavos: number;
  pagado_centavos: number;
  vuelto_centavos: number;
  iva_centavos: number;
  descuento_centavos: number;
  estado_fiscal: string;
  duplicada: boolean;
}

/** El error que NO es un error: la operación es posible, falta una firma. */
export class RequiereAutorizacion extends Error {
  constructor(public mensaje: string) {
    super(mensaje);
    this.name = "RequiereAutorizacion";
  }
}

function traducir(e: unknown): never {
  if (e instanceof ApiError) {
    const d = e.detail as { error?: string; mensaje?: string } | undefined;
    if (e.status === 403 && d?.error === "requiere_autorizacion") {
      throw new RequiereAutorizacion(d.mensaje || "Necesita autorización.");
    }
    // El mensaje del backend está escrito para la CAJERA. Se muestra tal cual.
    if (d?.mensaje) throw new Error(d.mensaje);
  }
  throw e;
}

export async function buscar(q: string, ubicacionId: string): Promise<Variante[]> {
  const p = new URLSearchParams({ q, ubicacion_id: ubicacionId });
  return api.get<Variante[]>(`/api/retail/catalogo/buscar?${p}`);
}

export async function cerrarVenta(cuerpo: unknown): Promise<Ticket> {
  try {
    return await api.post<Ticket>("/api/retail/ventas/cerrar", cuerpo);
  } catch (e) {
    return traducir(e);
  }
}
