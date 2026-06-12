/**
 * Clasifica el método de envío (campo transportadora de Melonn) en un
 * tipo legible + color, para destacar urgencia: mismo día / siguiente día.
 */

// Tonos válidos del componente Badge
export type BadgeTone = "critico" | "riesgo" | "normal" | "pendiente" | "info" | "neutral";

export interface TipoEnvio {
  label: string;
  short: string;
  tone: BadgeTone;
  express: boolean;
}

export function tipoEnvio(metodo?: string): TipoEnvio | null {
  if (!metodo) return null;
  const m = metodo.toLowerCase();

  if (/mismo d[íi]a/.test(m)) {
    return { label: "Mismo día hábil", short: "Mismo día", tone: "critico", express: true };
  }
  if (/siguiente d[íi]a|\+\s*1\s*d[íi]a|próximo d[íi]a/.test(m)) {
    return { label: "Siguiente día hábil", short: "Sig. día", tone: "riesgo", express: true };
  }
  if (/externo\s*2h|2h/.test(m)) {
    return { label: "Externo 2h", short: "2h", tone: "critico", express: true };
  }
  if (/dedicado/.test(m)) {
    return { label: "Envío dedicado", short: "Dedicado", tone: "info", express: false };
  }
  if (/recogida/.test(m)) {
    return { label: "Recogida en punto", short: "Recogida", tone: "neutral", express: false };
  }
  if (/b2b/.test(m)) {
    return { label: "Estándar B2B", short: "B2B", tone: "info", express: false };
  }
  if (/est[áa]ndar/.test(m)) {
    return { label: "Estándar", short: "Estándar", tone: "neutral", express: false };
  }
  return { label: metodo, short: metodo.slice(0, 14), tone: "neutral", express: false };
}

/** ¿Es un envío express (mismo día / 2h) que requiere prioridad? */
export function esExpress(metodo?: string): boolean {
  return tipoEnvio(metodo)?.express ?? false;
}
