/**
 * Estado del correo de la orden de corte — presentación compartida.
 *
 * Vive aquí y no dentro de una página porque lo usan dos: el detalle de la
 * orden y la lista de cortes. El estado lo calcula el backend a partir del
 * `last_event` de Resend (ver backend/services/produccion.py).
 */

export type EstadoCorreo =
  | "enviado"
  | "entregado"
  | "rebotado"
  | "spam"
  | "demorado"
  | "fallido"
  | "suprimido"
  | "error_envio";

export interface CorreoEnvio {
  id: string;
  destinatarios: string[];
  motivo: "autorizacion" | "reenvio_indicaciones" | "reenvio_manual";
  estado: EstadoCorreo;
  error: string | null;
  enviado_por: string | null;
  created_at: string;
}

/** Icono, texto y color de cada estado. Paleta del proyecto, no Tailwind genérico. */
export const ESTADO_CORREO: Record<
  EstadoCorreo,
  { icono: string; texto: string; tono: string }
> = {
  enviado:     { icono: "🕐", texto: "Enviado, esperando confirmación", tono: "text-graphite" },
  entregado:   { icono: "✅", texto: "Entregado",                        tono: "text-teal" },
  rebotado:    { icono: "⚠️", texto: "Rebotó — la dirección no existe",  tono: "text-ochre" },
  spam:        { icono: "⚠️", texto: "Marcado como spam",                tono: "text-ochre" },
  demorado:    { icono: "🕐", texto: "Demorado, reintentando",           tono: "text-graphite" },
  fallido:     { icono: "❌", texto: "No se entregó",                    tono: "text-crimson" },
  suprimido:   { icono: "❌", texto: "Bloqueado por Resend",             tono: "text-crimson" },
  error_envio: { icono: "❌", texto: "No se pudo enviar",                tono: "text-crimson" },
};

/** Estado desconocido (backend nuevo, frontend viejo) sin reventar la pantalla. */
export function presentacionCorreo(estado: string | null | undefined) {
  return (
    ESTADO_CORREO[estado as EstadoCorreo] ?? {
      icono: "•",
      texto: estado || "Sin registro de envío",
      tono: "text-graphite",
    }
  );
}

/** Un envío que hay que atender: no salió, o salió y no llegó. */
export function necesitaAtencion(estado: string | null | undefined): boolean {
  return ["rebotado", "spam", "fallido", "suprimido", "error_envio"].includes(
    estado ?? "",
  );
}
