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

/** Tallaje de PRENDAS SUPERIORES (bodys, camisetas): sin espigas, cada
 *  talla se corta por su cuenta. */
export const TALLAS_SUPERIOR: string[] = ["S", "M", "L", "XL"];

const ORDEN_LETRAS: Record<string, number> = { XS: 0, S: 1, M: 2, L: 3, XL: 4, XXL: 5 };

/** Ordena tallas mezclando numéricas (4,6,8…) y de letra (S,M,L,XL). */
export function ordenarTallas(tallas: string[]): string[] {
  const peso = (t: string) => {
    const u = t.trim().toUpperCase();
    if (u in ORDEN_LETRAS) return 100 + ORDEN_LETRAS[u];
    const n = parseInt(u, 10);
    return Number.isFinite(n) ? n : 999;
  };
  return [...tallas].sort((a, b) => peso(a) - peso(b));
}
