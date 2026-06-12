/**
 * Mapea el estado de Melonn (largo, en inglés) a un texto corto en español
 * para mostrar legible en las tablas.
 */

export function estadoMelonnCorto(estado?: string, code?: number): string {
  if (!estado && !code) return "—";

  // Primero por código (más confiable)
  switch (code) {
    case 1:  return "Pendiente alistar";
    case 2:  return "Listo alistar";
    case 5:  return "Empacado";
    case 6:  return "Entregado";
    case 7:  return "En tránsito";
    case 8:  return "Entregado";
    case 20: return "Entrega no posible";
    case 24: return "Preparado";
    case 26: return "Hold - autorizar";
    case 28: return "Listo empacar";
    case 29: return "En espera";
  }

  // Fallback por texto
  const s = (estado || "").toLowerCase();
  if (s.includes("ready for fulfillment"))     return "Listo alistar";
  if (s.includes("ready for packing"))         return "Listo empacar";
  if (s.includes("prepared"))                  return "Preparado";
  if (s.includes("packed"))                    return "Empacado";
  if (s.includes("shipped") && s.includes("transit")) return "En tránsito";
  if (s.includes("delivered"))                 return "Entregado";
  if (s.includes("delivery not"))              return "Entrega fallida";
  if (s.includes("hold"))                      return "En espera";
  if (s.includes("no stock"))                  return "Sin stock";
  if (s.includes("invalid"))                   return "Inválida";
  if (s.includes("not able to process"))       return "Error proceso";
  if (s.includes("expired promise"))           return "Promesa vencida";

  // Default: primeros 22 chars
  return (estado || "").slice(0, 22);
}
