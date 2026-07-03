/**
 * Medidas de CIERRES por talla — regla MALE'DENIM.
 * Se usa al separar los insumos de confección para saber qué largo
 * de cierre corresponde a cada talla según el tipo de tiro.
 */

export const TALLAS_CIERRES = ["4", "6", "8", "10", "12", "14", "16"] as const;

export const MEDIDAS_CIERRES: Record<string, Record<string, number>> = {
  "Tiro Alto": {
    "4": 12, "6": 13, "8": 14, "10": 15, "12": 16, "14": 17, "16": 17,
  },
  "Tiro Medio": {
    "4": 11, "6": 12, "8": 13, "10": 14, "12": 15, "14": 16, "16": 16,
  },
  "Cierre Cruzado": {
    "4": 8, "6": 9, "8": 10, "10": 11, "12": 12, "14": 13, "16": 13,
  },
};
