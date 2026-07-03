/**
 * Helpers para construir enlaces `wa.me` — mismo formato en toda la app.
 * Colombia: si el teléfono no tiene prefijo 57, lo agrega.
 */

export function normalizarTelefono(telefono?: string): string {
  const clean = (telefono || "").replace(/\D/g, "");
  if (!clean) return "";
  return clean.startsWith("57") ? clean : `57${clean}`;
}

export function buildWaLink({ telefono, mensaje }: {
  telefono?: string;
  mensaje: string;
}): string {
  const tel = normalizarTelefono(telefono);
  const q = encodeURIComponent(mensaje);
  return tel ? `https://wa.me/${tel}?text=${q}` : `https://wa.me/?text=${q}`;
}
