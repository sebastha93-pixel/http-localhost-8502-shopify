/**
 * Construye el link directo de rastreo de cada transportadora con la guía.
 * Al tocar la guía en la UI, abre directo el seguimiento en el sitio del carrier.
 */

interface CarrierDef {
  match: RegExp;
  url: (guia: string) => string;
  label: string;
}

const CARRIERS: CarrierDef[] = [
  {
    match: /coordinadora/i,
    label: "Coordinadora",
    // URL real confirmada: .../detalle-de-rastreo-de-guia/?guia=X
    url: (g) => `https://coordinadora.com/rastreo/rastreo-de-guia/detalle-de-rastreo-de-guia/?guia=${encodeURIComponent(g)}`,
  },
  {
    match: /servientrega/i,
    label: "Servientrega",
    // URL real confirmada
    url: (g) => `https://www.servientrega.com/wps/portal/rastreo-envio?guia=${encodeURIComponent(g)}`,
  },
  {
    match: /env[íi]a/i,
    label: "Envía",
    // Envía no acepta guía por query param → abre su home de rastreo
    // (el operador pega la guía, ya va copiada al portapapeles)
    url: () => `https://envia.co`,
  },
  {
    match: /interrap/i,
    label: "Interrapidísimo",
    url: (g) => `https://www.interrapidisimo.com/sigue-tu-envio/?guia=${encodeURIComponent(g)}`,
  },
  {
    match: /\btcc\b/i,
    label: "TCC",
    url: (g) => `https://tcc.com.co/rastreo-de-envios/?guia=${encodeURIComponent(g)}`,
  },
  {
    match: /domina/i,
    label: "Domina",
    url: (g) => `https://domina.com.co/rastreo-de-envios?guia=${encodeURIComponent(g)}`,
  },
];

/**
 * Devuelve la URL de rastreo directo para una guía + transportadora.
 * Si no reconoce la transportadora, retorna null (se usa fallback Melonn).
 */
// Links directos ACTIVOS con URLs reales confirmadas (Coordinadora,
// Servientrega, etc.). Envía abre su home (no acepta guía por query).
const LINKS_DIRECTOS_ACTIVOS = true;

export function trackingUrl(carrier?: string, guia?: string): string | null {
  if (!LINKS_DIRECTOS_ACTIVOS) return null;
  if (!carrier || !guia) return null;
  const c = CARRIERS.find((x) => x.match.test(carrier));
  return c ? c.url(guia) : null;
}

/** Nombre normalizado del carrier (para mostrar consistente). */
export function carrierLabel(carrier?: string): string {
  if (!carrier) return "—";
  const c = CARRIERS.find((x) => x.match.test(carrier));
  return c ? c.label : carrier;
}

/** ¿Es envío con mensajería local (sin rastreo de transportadora)? */
export function esMensajeriaLocal(carrier?: string): boolean {
  return /mensajer[íi]a local|local/i.test(carrier || "");
}
