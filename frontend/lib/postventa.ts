import { api } from "@/lib/api";

export type EstadoPostventa =
  | "creado" | "pendiente_validacion" | "aprobado" | "rechazado"
  | "esperando_envio_cliente" | "en_transito_bodega" | "recibido_bodega"
  | "nota_credito_emitida" | "factura_emitida" | "cambio_enviado"
  | "cerrado" | "escalado";

export interface CasoPostventa {
  id: string;
  case_number: string;
  status: EstadoPostventa;
  type: string;
  reason: string;
  priority: string;
  customer_name?: string | null;
  customer_email?: string | null;
  customer_phone?: string | null;
  shopify_order_name?: string | null;
  /** Factura exacta en Siigo. Es la única vía para las compras en tienda,
   *  que no tienen nº de pedido con el cual encontrarla. */
  siigo_invoice_id?: string | null;
  tienda?: string | null;
  /** Los pasos que ESTE caso recorre. Un cambio en tienda son 4, no 10. */
  ciclo?: EstadoPostventa[];
  created_at: string;
}

export interface DashboardPostventa {
  por_estado: Record<string, number>;
  abiertos: number;
  cerrados: number;
  total: number;
  top_motivos: { motivo: string; total: number }[];
}

export const ESTADOS_LABEL: Record<EstadoPostventa, string> = {
  creado: "Creado",
  pendiente_validacion: "Pendiente validación",
  aprobado: "Aprobado",
  rechazado: "Rechazado",
  esperando_envio_cliente: "Esperando envío",
  en_transito_bodega: "En tránsito",
  recibido_bodega: "Recibido en bodega",
  nota_credito_emitida: "Nota crédito emitida",
  factura_emitida: "Factura emitida",
  cambio_enviado: "Cambio despachado",
  cerrado: "Cerrado",
  escalado: "Escalado",
};

// Catálogos para el formulario de nuevo caso (espejo del backend).
export const TIPOS: { value: string; label: string }[] = [
  { value: "cambio_talla", label: "Cambio de talla" },
  { value: "cambio_ref", label: "Cambio por otra referencia" },
  { value: "reembolso", label: "Reembolso (devolución de dinero)" },
  { value: "bono", label: "Bono / gift card" },
  { value: "garantia", label: "Garantía" },
];

export const MOTIVOS: { value: string; label: string }[] = [
  { value: "talla_pequena", label: "Talla pequeña" },
  { value: "talla_grande", label: "Talla grande" },
  { value: "no_le_gusto_como_quedo", label: "No le gustó cómo le quedó" },
  { value: "color_diferente", label: "Color diferente al esperado" },
  { value: "producto_defectuoso", label: "Producto defectuoso" },
  { value: "producto_equivocado", label: "Producto equivocado" },
  { value: "pedido_incompleto", label: "Pedido incompleto" },
  { value: "demora_entrega", label: "Demora en la entrega" },
  { value: "arrepentimiento", label: "Se arrepintió de la compra" },
  { value: "calidad_percibida", label: "Calidad percibida" },
  { value: "error_asesoria", label: "Error de asesoría" },
  { value: "error_logistico", label: "Error logístico" },
  { value: "cambio_por_otro", label: "Cambio por otro producto" },
  { value: "garantia", label: "Garantía" },
  { value: "otro", label: "Otro" },
];

export const PRIORIDADES: { value: string; label: string }[] = [
  { value: "baja", label: "Baja" },
  { value: "media", label: "Media" },
  { value: "alta", label: "Alta" },
];

export const listarCasos = (status?: string) =>
  api.get<CasoPostventa[]>(`/api/postventa/casos${status ? `?status=${status}` : ""}`);

export const obtenerCaso = (id: string) =>
  api.get<CasoPostventa>(`/api/postventa/casos/${id}`);

export const crearCaso = (body: Record<string, unknown>) =>
  api.post<CasoPostventa>(`/api/postventa/casos`, body);

export const cambiarEstado = (id: string, nuevo_estado: string, motivo = "") =>
  api.patch<CasoPostventa>(`/api/postventa/casos/${id}/estado`, { nuevo_estado, motivo });

export const agregarItem = (id: string, body: Record<string, unknown>) =>
  api.post(`/api/postventa/casos/${id}/items`, body);

export const dashboardPostventa = () =>
  api.get<DashboardPostventa>(`/api/postventa/dashboard`);

// ── Motor fiscal (nota crédito) ──────────────────────────────────────
export interface PreviewFiscal {
  factura_original: { id: string; name: string };
  totales: { subtotal: number; iva: number; total: number };
  modo: string;
  emitido: boolean;
}

export const previewFiscal = (id: string) =>
  api.post<PreviewFiscal>(`/api/postventa/casos/${id}/fiscal/preview`);

export const emitirFiscal = (id: string) =>
  api.post<{ siigo_document_number: string }>(`/api/postventa/casos/${id}/fiscal/emitir`);

// Factura del reemplazo
export interface PreviewFactura {
  resumen: { total: number; anticipo: number; excedente: number };
  modo: string;
  emitido: boolean;
}
/** Con qué medio(s) se cobró el excedente. Sin esto no se puede cruzar la caja
 *  del día: la factura sale por FV-1 y no entra al consecutivo del punto. */
export interface PagoExcedente { id: number; value: number; }
export const previewFactura = (id: string, pagos_excedente: PagoExcedente[] = [],
                               descuento_pesos = 0) =>
  api.post<PreviewFactura>(`/api/postventa/casos/${id}/fiscal/factura/preview`,
                           { pagos_excedente, descuento_pesos });
export const emitirFactura = (id: string) =>
  api.post<{ siigo_document_number: string }>(`/api/postventa/casos/${id}/fiscal/factura/emitir`);

// Ítems de la factura original (para elegir cuál se devuelve)
export interface ItemFactura { code: string; description: string; price: number; variant: string; }
export interface ItemsFactura { factura: { id: string; name: string }; items: ItemFactura[]; }
export const itemsFacturaCaso = (id: string) =>
  api.get<ItemsFactura>(`/api/postventa/casos/${id}/fiscal/items-factura`);

// ── Historial e ítems del caso ───────────────────────────────────────
export interface EventoTimeline {
  id: string; event_type: string; description: string;
  created_by: string; created_at: string;
}
export interface ItemCaso {
  id: string; original_sku: string | null; original_variant: string | null;
  original_price: number | null; requested_sku: string | null;
  price_difference: number | null; item_status: string;
}
export const timelineCaso = (id: string) =>
  api.get<EventoTimeline[]>(`/api/postventa/casos/${id}/timeline`);
export const itemsCaso = (id: string) =>
  api.get<ItemCaso[]>(`/api/postventa/casos/${id}/items`);

// ── Semántica visual de los estados (paleta Selvedge del OS) ─────────
import type { StatusKind } from "@/components/status-badge";

/** Mapea el estado del caso al lenguaje de estados del OS:
 *  terracotta = esperando algo, sage = resuelto, ochre = riesgo/atención. */
export const ESTADO_KIND: Record<EstadoPostventa, StatusKind> = {
  creado:                  "wait",
  pendiente_validacion:    "wait",
  aprobado:                "wait",
  esperando_envio_cliente: "wait",
  en_transito_bodega:      "wait",
  recibido_bodega:         "wait",
  cambio_enviado:          "done",
  nota_credito_emitida: "wait",
  factura_emitida:      "wait",
  cerrado:              "done",
  rechazado:            "unassigned",
  escalado:             "risk",
};

/** Orden del ciclo de vida, para el riel de progreso. */
export const CICLO: EstadoPostventa[] = [
  "creado", "pendiente_validacion", "aprobado",
  "esperando_envio_cliente", "en_transito_bodega", "recibido_bodega",
  "nota_credito_emitida", "factura_emitida", "cambio_enviado", "cerrado",
];

// ── Logística inversa ────────────────────────────────────────────────
export interface Logistica {
  guia_retorno?: string | null; transportadora_retorno?: string | null;
  fecha_envio_cliente?: string | null; fecha_recibido_bodega?: string | null;
  estado_retorno?: string; guia_despacho?: string | null;
  transportadora_despacho?: string | null; fecha_despacho?: string | null;
}
export const obtenerLogistica = (id: string) =>
  api.get<Logistica>(`/api/postventa/casos/${id}/logistica`);
export const registrarGuiaRetorno = (id: string, guia: string, transportadora = "") =>
  api.post(`/api/postventa/casos/${id}/logistica/guia-retorno`, { guia, transportadora });
export const confirmarRecepcion = (id: string, notas = "") =>
  api.post(`/api/postventa/casos/${id}/logistica/recibir`, { notas });
export const registrarDespacho = (id: string, guia: string, transportadora = "") =>
  api.post(`/api/postventa/casos/${id}/logistica/despachar`, { guia, transportadora });

export interface ImpactoVentas {
  devuelto: number; refacturado: number; neto: number; casos: number;
}
export const impactoVentas = () =>
  api.get<ImpactoVentas>(`/api/postventa/impacto-ventas`);

// ── Puntos de venta (cambio presencial) ──────────────────────────────
export interface PuntoVenta {
  clave: string; nombre: string; tienda: string;
  prefijo_factura: string; bodega_id: number | null;
  formas_pago: { id: number; nombre: string }[];
  lista: boolean; falta: string[];
}
export const listarTiendas = () =>
  api.get<PuntoVenta[]>(`/api/postventa/tiendas`);

// ── Buscar compras por cédula ────────────────────────────────────────
export interface PrendaCompra { sku: string; descripcion: string; precio: number; }
export interface Compra {
  factura_id: string; factura: string; fecha: string; total: number;
  canal: string | null; donde: string; pedido: string | null;
  acreditable: boolean; motivo_no_acreditable: string | null;
  /** Días desde la factura. Pasado el plazo ya no se puede cambiar. */
  dias?: number | null;
  prendas: PrendaCompra[];
}
/** Siigo guarda el nombre/email/teléfono en el CLIENTE, no en la factura. */
export interface ClienteSiigo {
  nombre: string; email: string; telefono: string;
  identification?: string; branch_office?: number;
}
export interface ComprasCliente {
  cedula: string; total: number; acreditables: number; compras: Compra[];
  cliente?: ClienteSiigo;
  _error?: string;
}
export const comprasPorCedula = (cedula: string) =>
  api.get<ComprasCliente>(`/api/postventa/clientes/compras?cedula=${encodeURIComponent(cedula)}`);

/* ── Qué se lleva la clienta ─────────────────────────────────────────── */
/** Una referencia que ESE punto puede entregar hoy. `stock` es el de esa
 *  bodega, no el total de la marca. */
export interface OpcionReemplazo {
  code: string; referencia: string; talla: string;
  nombre: string; stock: number; bodega: string;
  /** Precio de la TIENDA, sin IVA. El de Shopify puede estar en promoción. */
  precio_base?: number | null;
}
export interface OpcionesReemplazo {
  bodega: string; tienda: string; opciones: OpcionReemplazo[];
  /** De cuándo es el dato. La caja del POS pudo vender esa talla hace rato. */
  frescura?: string; viejo?: boolean;
}
export const sincronizarInventario = () =>
  api.post<{ filas?: number; _error?: string; detalle?: string }>(
    "/api/postventa/inventario/sincronizar");
export const opcionesReemplazo = (id: string, q = "") =>
  api.get<OpcionesReemplazo>(
    `/api/postventa/casos/${id}/reemplazo/opciones?q=${encodeURIComponent(q)}`);

export const elegirReemplazo = (id: string, requested_sku: string,
                                requested_variant = "") =>
  api.post(`/api/postventa/casos/${id}/reemplazo`,
           { requested_sku, requested_variant });

/** La clienta no se lleva nada hoy: el crédito queda a su nombre en Siigo. */
export const dejarSaldoAFavor = (id: string, monto: number) =>
  api.post(`/api/postventa/casos/${id}/saldo-a-favor`, { monto });

/* ── Cierre de caja ──────────────────────────────────────────────────── */
/** Lo que la cajera SUMA a su arqueo: el excedente se cobró en su caja pero
 *  la factura salió por FV-5 desde Siigo Nube, y el POS no lo ve. */
export interface MedioCobrado { id: number; nombre: string; total: number; }
export interface CasoCobrado {
  caso: string; factura: string; cobrado: number; medios: MedioCobrado[];
}
export interface CierrePunto {
  tienda: string; nombre: string; fecha: string;
  total_cobrado: number; por_medio: MedioCobrado[]; casos: CasoCobrado[];
  notas_credito: { cantidad: number; total: number };
}
export const cierreCaja = (fecha = "") =>
  api.get<{ fecha: string; puntos: CierrePunto[] }>(
    `/api/postventa/caja/cierre${fecha ? `?fecha=${fecha}` : ""}`);
