/**
 * Tipos TypeScript que mapean los modelos Pydantic del backend.
 * Mantener en sync con backend/api/*.py.
 */

// ── Health ──────────────────────────────────────────────────────────────────
export interface HealthResponse {
  status: string;
  env: string;
  version: string;
  timestamp: string;
}

export interface ConfigCheck {
  melonn: boolean;
  shopify: boolean;
  mercadopago: boolean;
  supabase: boolean;
}

// ── Melonn ──────────────────────────────────────────────────────────────────
/**
 * Proyección del estado del carrier. Fuente única: _sub_estado_logistico()
 * en src/melonn_client.py — con "otro" de catch-all, así que el conjunto es
 * cerrado y ningún otro valor puede llegar por la API.
 *
 * OJO: no existe "resuelto" ni "devuelto". Resolver un caso es una decisión
 * interna, no un hecho del carrier: ese concepto vive en el `tipo` de las
 * acciones de auditoría ("resuelto", "devolucion"), no aquí.
 */
export type SubEstadoLogistico =
  | "novedad"
  | "entregado"
  | "en_transito"
  | "pendiente_despacho"
  | "otro";

export interface ItemPedido {
  sku: string;
  titulo: string;
  variante: string;
  cantidad: number;
  precio: number;
  imagen: string;
}

export interface Pedido {
  orden_melonn: string;
  orden_tienda: string;
  estado_melonn: string;
  estado_melonn_code: number;
  sub_estado_logistico: SubEstadoLogistico;
  canal_venta: string;
  es_b2b: boolean;
  nombre_comprador: string;
  telefono_comprador: string;
  ciudad_destino: string;
  region_destino: string;
  transportadora: string;
  link_guia: string;
  fecha_creacion: string;
  valor_cod_raw: string;
  tipo_recaudo: string;
  es_contraentrega: boolean;
  incidencia?: string;
  fecha_despacho?: string;
  fecha_promesa?: string;
  // Campos enriquecidos por backend/services/metricas.clasificar:
  nivel?: NivelRiesgo;
  score?: number;
  dias_real?: number;
  /** true = los días NO salen de una fecha de despacho, se estimaron
   *  desde la creación del pedido. La tabla los muestra con "≈". */
  dias_estimados?: boolean;
  sla_critico?: number;
  zona?: string;
  motivo_riesgo?: string;
  categoria_incidencia?: string;
  requiere_contacto?: boolean;
  es_novedad_visible?: boolean;
  novedad_manual?: boolean;
  motivo_novedad_manual?: string;
  carrier_real?: string;
  guia_real?: string;
  valor_num?: number;
  // Producto (enriquecido desde Shopify)
  sku?: string;
  producto?: string;
  variante?: string;
  cantidad?: number;
  precio_unitario?: number;
  imagen_producto?: string;
  items?: ItemPedido[];
  [key: string]: unknown;
}

export interface PedidoListResponse {
  pedidos: Pedido[];
  total: number;
  fuente: string;
  stale: boolean;
  fetched_at: string;
}

export interface CacheInfo {
  total: number | null;
  age_seconds: number | null;
  fetched_at: string | null;
  stale: boolean | null;
  fuente: string | null;
  backend: string | null;
}

export interface MelonnStatus {
  credenciales_ok: boolean;
  cache: CacheInfo | null;
}

// ── Niveles de riesgo (derivados) ───────────────────────────────────────────
export type NivelRiesgo = "CRITICO" | "RIESGO" | "NORMAL" | "VENCIDO" | "RESUELTO";

// ── Métricas globales ───────────────────────────────────────────────────────
export interface MetricasGlobales {
  n_total: number;
  n_pend: number;
  n_tran_cod: number;
  n_nov_cod: number;
  n_ent_cod: number;
  n_nov_pre: number;
  n_tran_pre: number;
  n_ent_pre: number;
  n_critico: number;
  n_riesgo: number;
  n_normal: number;
  val_cod: number;
  val_riesgo: number;
  val_ent: number;
  val_nov_cod: number;
}

export interface MetricasResponse {
  metricas: MetricasGlobales;
  fuente: string;
  stale: boolean;
  fetched_at: string;
}
