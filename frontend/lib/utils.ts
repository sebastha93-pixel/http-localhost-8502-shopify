import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Formato monetario COP — $1.234.567 */
export function formatMoney(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return "$" + Math.round(v).toLocaleString("es-CO");
}

/** Versión compacta: $18.4M, $25.2K */
export function formatMoneyShort(v: number): string {
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000)     return `$${Math.round(v / 1_000)}K`;
  return `$${Math.round(v)}`;
}

// ── Fechas: SIEMPRE en zona horaria Colombia (America/Bogota, UTC-5) ─────────
// El backend devuelve fechas en UTC con sufijo Z (o sin tz, asumido UTC).
// Acá las convertimos a Bogotá para mostrar.

const TZ = "America/Bogota";

function _toDate(iso?: string | null): Date | null {
  if (!iso) return null;
  // Si el string no tiene tz info, asumimos UTC (lo que envía el backend)
  const s = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "10/06/26 10:39" — fecha + hora cortas */
export function fmtDateTime(iso?: string | null): string {
  const d = _toDate(iso);
  if (!d) return "—";
  return d.toLocaleString("es-CO", {
    timeZone: TZ,
    day: "2-digit", month: "2-digit", year: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

/** "10 de junio de 2026" — fecha larga */
export function fmtDateLong(iso?: string | null): string {
  const d = _toDate(iso);
  if (!d) return "—";
  return d.toLocaleDateString("es-CO", {
    timeZone: TZ,
    day: "numeric", month: "long", year: "numeric",
  });
}

/** "10:39 a. m." — solo hora */
export function fmtTime(iso?: string | null): string {
  const d = _toDate(iso);
  if (!d) return "—";
  return d.toLocaleTimeString("es-CO", {
    timeZone: TZ,
    hour: "2-digit", minute: "2-digit",
  });
}

/** "3 jul 2026" — para fechas tipo YYYY-MM-DD (sin hora, sin shift de zona).
 * Usar en fechas de negocio: recogida, entrega, despacho. */
export function fmtFecha(fecha?: string | null): string {
  if (!fecha) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(fecha);
  if (!m) return fecha;
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${parseInt(m[3], 10)} ${MESES[parseInt(m[2], 10) - 1]} ${m[1]}`;
}

/** Hoy en Bogotá como YYYY-MM-DD (para defaults de inputs date — evita que
 * después de las 7 PM el default UTC salte al día siguiente). */
export function hoyBogotaISO(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Bogota" }).format(new Date());
}

/** Fecha de "hoy" en Bogotá, formato largo */
export function hoyBogota(): string {
  return new Date().toLocaleDateString("es-CO", {
    timeZone: TZ,
    day: "numeric", month: "long", year: "numeric",
  });
}

/** Parser de Valor COD del backend (puede venir como string "$123,456") */
export function parseCOD(raw: unknown): number {
  if (raw == null) return 0;
  if (typeof raw === "number") return raw;
  const s = String(raw).replace(/[^\d.-]/g, "");
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : 0;
}
