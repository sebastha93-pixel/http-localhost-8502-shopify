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

/** Parser de Valor COD del backend (puede venir como string "$123,456") */
export function parseCOD(raw: unknown): number {
  if (raw == null) return 0;
  if (typeof raw === "number") return raw;
  const s = String(raw).replace(/[^\d.-]/g, "");
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : 0;
}
