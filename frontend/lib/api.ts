/**
 * Cliente HTTP del backend MALE'DENIM OS.
 *
 * En desarrollo:
 *   Next.js redirige /api/* al backend FastAPI (port 8000) via rewrites.
 *
 * En producción:
 *   NEXT_PUBLIC_API_URL apunta al servicio de Railway del backend.
 *   Las llamadas relativas /api/* son enviadas al backend.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || "";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown = undefined;
    try { detail = await res.json(); } catch {}
    throw new ApiError(res.status, `HTTP ${res.status} on ${path}`, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get:  <T>(path: string)              => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
};
