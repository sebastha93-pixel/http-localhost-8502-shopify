/**
 * Cliente HTTP del backend MALE'DENIM OS.
 * Envía JWT Bearer token y redirige a /login si recibe 401.
 */
import { getToken, clearToken } from "@/lib/auth";

const BASE = process.env.NEXT_PUBLIC_API_URL || "";
export const API_BASE = BASE;

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE}${path}`;
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(url, { ...init, headers, cache: "no-store" });

  if (res.status === 401) {
    // Mostrar la razón REAL del backend (Credenciales inválidas, Usuario
    // inactivo, Token expirado…) en vez del genérico "No autenticado".
    let detalle = "";
    try {
      detalle = ((await res.json()) as { detail?: string })?.detail || "";
    } catch { /* sin body */ }
    clearToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, detalle || "No autenticado");
  }

  if (!res.ok) {
    let detail: unknown = undefined;
    let detailMsg = "";
    try {
      detail = await res.json();
      detailMsg = (detail as { detail?: string })?.detail || "";
    } catch {}
    throw new ApiError(res.status, detailMsg || `HTTP ${res.status} on ${path}`, detail);
  }
  return res.json() as Promise<T>;
}

/** Descarga un archivo autenticado (Bearer) y dispara el guardado en el navegador. */
async function download(path: string, fallbackName: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { msg = ((await res.json()) as { detail?: { error?: string } | string })?.detail as string || msg; } catch {}
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  const disp = res.headers.get("Content-Disposition") || "";
  const m = disp.match(/filename="?([^";]+)"?/);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = m?.[1] || fallbackName;
  a.click();
  URL.revokeObjectURL(url);
}

export const api = {
  get:  <T>(path: string) => request<T>(path),
  download,
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) =>
    request<T>(path, { method: "DELETE" }),
};
