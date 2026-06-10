"use client";

/**
 * Identidad del usuario actual (hasta tener auth real con JWT).
 *
 * Guarda el nombre en localStorage para auditoría de acciones.
 * Cada acción/nota lleva este nombre como `autor`.
 */

const KEY = "maledenim_user";

export function getUser(): string {
  if (typeof window === "undefined") return "Sistema";
  const v = localStorage.getItem(KEY);
  return v?.trim() || "";
}

export function setUser(name: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(KEY, name.trim());
}

/**
 * Devuelve el nombre del usuario, pidiéndolo si no existe.
 * Pensado para llamar antes de cada acción de escritura.
 */
export function ensureUser(): string {
  let name = getUser();
  if (!name) {
    name = (prompt("Tu nombre (queda registrado en cada acción que realices):") || "").trim();
    if (!name) name = "Equipo";
    setUser(name);
  }
  return name;
}
