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
export interface Pedido {
  orden_melonn: string;
  orden_tienda: string;
  estado_melonn: string;
  estado_melonn_code: number;
  sub_estado_logistico: string;
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
  sla_critico?: number;
  zona?: string;
  motivo_riesgo?: string;
  categoria_incidencia?: string;
  requiere_contacto?: boolean;
  es_novedad_visible?: boolean;
  valor_num?: number;
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
