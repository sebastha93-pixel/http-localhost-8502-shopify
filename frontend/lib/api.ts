/**
 * Cliente HTTP del backend MALE'DENIM OS.
 * Envía JWT Bearer token y redirige a /login si recibe 401.
 */
import { getToken, setToken, clearToken } from "@/lib/auth";

const BASE = process.env.NEXT_PUBLIC_API_URL || "";
export const API_BASE = BASE;

/**
 * Sesión deslizante. El backend devuelve un token fresco en esta cabecera
 * cuando al actual le queda poca vida; guardarlo mantiene la sesión viva
 * mientras la persona use la app, en vez de echarla al login a media tarea.
 * (El backend tiene que exponerla en expose_headers del CORS.)
 */
const CABECERA_TOKEN = "X-Token-Renovado";

function guardarTokenRenovado(res: Response) {
  const nuevo = res.headers.get(CABECERA_TOKEN);
  if (nuevo) setToken(nuevo);
}

/** Manda al login PERO recordando dónde estabas, para volver ahí al entrar. */
function irAlLogin() {
  if (typeof window === "undefined") return;
  const actual = window.location.pathname + window.location.search;
  if (window.location.pathname.startsWith("/login")) return;
  const volver = actual && actual !== "/" ? `?volver=${encodeURIComponent(actual)}` : "";
  window.location.href = `/login${volver}`;
}

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
  guardarTokenRenovado(res);

  if (res.status === 401) {
    // Mostrar la razón REAL del backend (Credenciales inválidas, Usuario
    // inactivo, Token expirado…) en vez del genérico "No autenticado".
    let detalle = "";
    try {
      detalle = ((await res.json()) as { detail?: string })?.detail || "";
    } catch { /* sin body */ }
    clearToken();
    irAlLogin();
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
  // 204 No Content (ej. DELETE) o cuerpo vacío: no intentar parsear JSON —
  // en Safari res.json() sobre vacío lanza "did not match the expected pattern".
  if (res.status === 204) return undefined as T;
  const texto = await res.text();
  if (!texto) return undefined as T;
  return JSON.parse(texto) as T;
}

/** Descarga un archivo autenticado (Bearer) y dispara el guardado en el navegador. */
async function download(path: string, fallbackName: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    cache: "no-store",
  });
  guardarTokenRenovado(res);
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

/** Descarga un recurso binario autenticado (Bearer) y devuelve un object
 *  URL para usarlo en <img>/<embed>. Recuerda revokeObjectURL al reemplazar. */
async function blobUrl(path: string): Promise<string> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    cache: "no-store",
  });
  guardarTokenRenovado(res);
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status} on ${path}`);
  return URL.createObjectURL(await res.blob());
}

export const api = {
  get:  <T>(path: string) => request<T>(path),
  download,
  blobUrl,
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) =>
    request<T>(path, { method: "DELETE" }),
};
