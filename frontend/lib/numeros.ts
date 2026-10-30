/**
 * Lectura de números escritos a mano — UN solo criterio para todas las
 * pantallas de producción (2026-10-30).
 *
 * POR QUÉ: `parseFloat` lee "12.300" como 12,3 (pesos mil veces menos) y
 * "48,7" como 48 (corta en la coma, que es el decimal en Colombia y lo que
 * escribe el teclado del celular en español). Así se guardaban precosteos,
 * costos por metro, metros de rollo y consumos de corte equivocados.
 */

/** Pesos colombianos (sin centavos). "12.300" → 12300 · "1.250.000" → 1250000 ·
 *  "45,000" → 45000 · "1400,50" o "1400.5" → 1400 (los centavos se descartan). */
export function pesos(s?: string | number | null): number {
  if (typeof s === "number") return Number.isFinite(s) ? Math.round(s) : 0;
  let t = (s ?? "").trim();
  if (!t) return 0;
  // 1-2 dígitos tras el último separador = centavos → fuera. 3 = miles.
  t = t.replace(/[.,]\d{1,2}$/, "");
  return parseInt(t.replace(/\D/g, ""), 10) || 0;
}

/** Cantidad de un insumo. "1.500" o "1,500" son MIL QUINIENTOS (botones,
 *  cierres: así se escribe en Colombia), no 1,5. Con decimales de verdad
 *  ("12,5" m de elástico, "1.500,5") se lee como decimal(). */
export function cantidadInsumo(s?: string | number | null): number {
  if (typeof s === "number") return Number.isFinite(s) ? s : 0;
  const t = (s ?? "").trim().replace(/\s/g, "");
  if (/^\d{1,3}([.,]\d{3})+$/.test(t)) return parseInt(t.replace(/\D/g, ""), 10) || 0;
  return decimal(t);
}

/** Cantidades con decimales (metros, metros por prenda, %). "48,7" → 48.7 ·
 *  "1.245,6" → 1245.6 · "1,245.6" → 1245.6 · "0.8" → 0.8. Un punto solo se
 *  sigue leyendo como decimal (como antes). Vacío o ilegible → 0. */
export function decimal(s?: string | number | null): number {
  if (typeof s === "number") return Number.isFinite(s) ? s : 0;
  let t = (s ?? "").trim().replace(/\s/g, "");
  if (!t) return 0;
  const coma = t.lastIndexOf(",");
  const punto = t.lastIndexOf(".");
  if (coma >= 0 && punto >= 0) {
    // El separador que va de último es el decimal; el otro es de miles.
    t = coma > punto ? t.replace(/\./g, "").replace(",", ".") : t.replace(/,/g, "");
  } else if (coma >= 0) {
    t = t.replace(/,/g, ".");
  }
  const n = parseFloat(t);
  return Number.isFinite(n) ? n : 0;
}
