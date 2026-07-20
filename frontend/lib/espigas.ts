/**
 * ESPIGAS de corte — regla MALE'DENIM (vigente 2026-07).
 * El trazo se corta por espigas (trazos combinados de tallas), en este orden:
 *   · Talla 4 sola
 *   · Tallas 6 y 16 juntas
 *   · Tallas 8 y 10 juntas
 *   · Tallas 12 y 14 juntas
 * Cada capa de una espiga produce 1 prenda de CADA talla de la espiga,
 * por eso al llenar una talla en la curva su compañera se llena igual.
 */

export const ESPIGAS: string[][] = [["4"], ["6", "16"], ["8", "10"], ["12", "14"]];

/** Pareja de cada talla dentro de su espiga (la talla 4 va sola). */
export const PAREJA_TALLA: Record<string, string> = {
  "6": "16", "16": "6",
  "8": "10", "10": "8",
  "12": "14", "14": "12",
};

/** Etiqueta legible de una espiga. */
export function labelEspiga(espiga: string[]): string {
  return espiga.length === 1 ? `T${espiga[0]}` : `T${espiga.join(" + T")}`;
}

/** Capas que necesita una espiga según unidades por talla (max de la pareja). */
export function capasDeEspiga(espiga: string[], unidades: Record<string, number>): number {
  return Math.max(0, ...espiga.map((t) => unidades[t] || 0));
}

/** Sobrante fijo por espiga al extender el trazo (2 cm). */
export const SOBRANTE_ESPIGA_M = 0.02;
