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
