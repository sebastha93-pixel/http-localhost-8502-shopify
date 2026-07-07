import { api } from "@/lib/api";

export type EstadoPostventa =
  | "creado" | "pendiente_validacion" | "aprobado" | "rechazado"
  | "nota_credito_emitida" | "factura_emitida" | "cerrado" | "escalado";

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
  nota_credito_emitida: "Nota crédito emitida",
  factura_emitida: "Factura emitida",
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
