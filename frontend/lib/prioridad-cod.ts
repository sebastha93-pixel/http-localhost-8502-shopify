/**
 * Lógica de prioridad COD basada en el tier del cliente.
 * Decisión principal del operador: ¿este pedido se autoriza directo,
 * se llama antes, o se exige prepago?
 *
 * Reglas (factor principal = confianza del cliente):
 *   vip / recurrente      → AUTORIZAR YA   (verde)
 *   nuevo                 → OK             (azul, autoriza normal)
 *   primer_pedido / sin clasificar → VERIFICAR (amarillo)
 *   riesgo                → LLAMAR ANTES   (rojo)
 */

export type PrioridadCod = "autorizar_ya" | "ok" | "verificar" | "llamar_antes";

export interface PrioridadInfo {
  nivel: PrioridadCod;
  label: string;
  short: string;
  tone: "normal" | "info" | "pendiente" | "critico" | "neutral";
  motivo: string;
  orden: number;  // Mayor = más confiable; usar para sort descendente
}

const NIVELES: Record<PrioridadCod, Omit<PrioridadInfo, "motivo" | "nivel">> = {
  autorizar_ya: {
    label: "Autorizar ya",
    short: "Autorizar",
    tone: "normal",
    orden: 4,
  },
  ok:           { label: "OK",           short: "OK",        tone: "info",      orden: 3 },
  verificar:    { label: "Verificar",    short: "Verificar", tone: "pendiente", orden: 2 },
  llamar_antes: { label: "Llamar antes", short: "Llamar",    tone: "critico",   orden: 1 },
};

export function calcularPrioridad(tier?: string): PrioridadInfo {
  switch (tier) {
    case "vip":
      return { nivel: "autorizar_ya", motivo: "VIP — 5+ entregas exitosas, sin cancelaciones", ...NIVELES.autorizar_ya };
    case "recurrente":
      return { nivel: "autorizar_ya", motivo: "Recurrente — historial confiable", ...NIVELES.autorizar_ya };
    case "nuevo":
      return { nivel: "ok", motivo: "Ya entregó 1 pedido — autorizar normal", ...NIVELES.ok };
    case "primer_pedido":
      return { nivel: "verificar", motivo: "Primer pedido — verificar teléfono y dirección antes", ...NIVELES.verificar };
    case "riesgo":
      return { nivel: "llamar_antes", motivo: "Cancelaciones ≥ entregas — llamar a confirmar antes de despachar", ...NIVELES.llamar_antes };
    case "desconocido":
    default:
      return { nivel: "verificar", motivo: "Sin clasificación — verificar datos antes de autorizar", ...NIVELES.verificar };
  }
}
