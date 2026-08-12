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

export interface Cliente {
  id: string;
  tipo_documento: string;
  numero_documento: string;
  nombre: string;
  telefono?: string | null;
  correo?: string | null;
  compras: number;
}

export interface Talla {
  variante_id: string;
  sku: string;
  talla: string;
  disponible: number;
}

/** Una referencia con sus tallas — la forma que pide la rejilla del diseño. */
export interface Referencia {
  referencia: string;
  nombre: string;
  color: string;
  categoria: string;
  precio_base_centavos: number;
  precio_con_iva_centavos: number;
  tasa_iva: string;
  tallas: Talla[];
}

export interface Catalogo {
  categorias: string[];
  referencias: Referencia[];
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

interface DetalleError {
  error?: string;
  mensaje?: string;
  accion_sugerida?: string;
}

/**
 * Saca el detalle real del error.
 *
 * FastAPI envuelve todo en `{detail: ...}`, y el cliente del ERP guarda ese
 * SOBRE completo en `ApiError.detail` — no su contenido. Cuando el detalle es
 * un objeto (como aquí, que lleva `error` y `mensaje`) tambien termina como
 * `message`, y la pantalla mostraba «[object Object]» en vez del texto escrito
 * para la cajera. Lo vi en el diálogo del PIN.
 *
 * Se desenvuelve aquí y no en `lib/api.ts` porque ese cliente lo comparten
 * todas las pantallas del ERP y sus errores son strings.
 */
function detalleDe(e: ApiError): DetalleError | undefined {
  const bruto = e.detail as { detail?: unknown } | undefined;
  const interno = bruto && typeof bruto === "object" && "detail" in bruto
    ? bruto.detail
    : bruto;
  return interno && typeof interno === "object"
    ? (interno as DetalleError)
    : undefined;
}

function traducir(e: unknown): never {
  if (e instanceof ApiError) {
    const d = detalleDe(e);
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

export async function listarCatalogo(
  ubicacionId: string,
  q = "",
  categoria = "",
): Promise<Catalogo> {
  const p = new URLSearchParams({ ubicacion_id: ubicacionId });
  if (q) p.set("q", q);
  if (categoria && categoria !== "Todo") p.set("categoria", categoria);
  return api.get<Catalogo>(`/api/retail/catalogo/referencias?${p}`);
}

export async function cerrarVenta(cuerpo: unknown): Promise<Ticket> {
  try {
    return await api.post<Ticket>("/api/retail/ventas/cerrar", cuerpo);
  } catch (e) {
    return traducir(e);
  }
}

export interface Firma {
  autorizado_por: string;
  nombre: string;
  tope_descuento_pct: string;
}

/** Valida el PIN de un supervisor. NO abre una sesión: dice quién firma ESTA
 *  operación, y ese nombre viaja con la venta hasta la auditoría. */
export async function pedirAutorizacion(pin: string, tiendaId: string): Promise<Firma> {
  try {
    return await api.post<Firma>("/api/retail/autorizacion", {
      pin,
      tienda_id: tiendaId,
    });
  } catch (e) {
    return traducir(e);
  }
}

/** Sólo por número de identificación: buscar por nombre en un mostrador
 *  devuelve seis «María González» y la cajera tiene que adivinar. */
export async function buscarClientes(documento: string): Promise<Cliente[]> {
  const p = new URLSearchParams({ documento });
  return api.get<Cliente[]>(`/api/retail/clientes/buscar?${p}`);
}

export async function crearCliente(cuerpo: {
  cliente_id: string;
  tipo_documento: string;
  numero_documento: string;
  nombre: string;
  telefono: string;
  correo: string;
}): Promise<Cliente> {
  try {
    return await api.post<Cliente>("/api/retail/clientes", cuerpo);
  } catch (e) {
    return traducir(e);
  }
}
