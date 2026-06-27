"use client";

const TOKEN_KEY = "maledenim_token";

// Roles del sistema:
//   admin  = acceso total (owner)
//   lector = solo lectura en todos los módulos
//   user   = permisos granulares por módulo (definidos en `permisos`)
// Legacy (retro-compat con usuarios viejos):
//   operador → equivale a "user" con permisos amplios
//   lectura  → equivale a "lector"
export type Rol = "admin" | "lector" | "user" | "operador" | "lectura";

export interface User {
  id: string;
  email: string;
  nombre: string;
  cargo?: string;
  rol: Rol;
  permisos?: Record<string, string[] | Record<string, boolean>>;
  activo?: boolean;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
}

export const ROL_LABEL: Record<Rol, string> = {
  admin:    "Administrador",
  lector:   "Solo lectura",
  user:     "Usuario",
  operador: "Usuario",       // legacy
  lectura:  "Solo lectura",  // legacy
};

export const MODULOS = [
  "centro_control", "logistica", "contraentrega", "envios", "b2b",
  "devoluciones", "incidencias", "historico", "finanzas", "comercial",
  "inventario", "revenue", "inteligencia", "configuracion", "usuarios",
  "auditoria",
] as const;

export const MODULO_LABEL: Record<string, string> = {
  centro_control: "Centro de control",
  logistica: "Logística",
  contraentrega: "Contraentrega",
  envios: "Envíos",
  b2b: "B2B",
  devoluciones: "Devoluciones",
  incidencias: "Incidencias",
  historico: "Histórico",
  finanzas: "Finanzas",
  comercial: "Comercial",
  inventario: "Inventario",
  revenue: "Revenue IA",
  inteligencia: "Inteligencia",
  configuracion: "Configuración",
  usuarios: "Usuarios",
  auditoria: "Auditoría",
};

export const ACCIONES = ["ver", "modificar", "borrar"] as const;
export type Accion = (typeof ACCIONES)[number];

export const ACCION_LABEL: Record<Accion, string> = {
  ver:       "Ver",
  modificar: "Modificar",
  borrar:    "Borrar",
};

export function esAdmin(user?: User | null): boolean {
  return user?.rol === "admin";
}

export function esLector(user?: User | null): boolean {
  return user?.rol === "lector" || user?.rol === "lectura";
}

/** Devuelve true si el usuario puede ejecutar `accion` en `modulo`. */
export function tienePermiso(user: User | null | undefined, modulo: string, accion: Accion): boolean {
  if (!user) return false;
  if (user.activo === false) return false;
  if (user.rol === "admin") return true;
  if (user.rol === "lector" || user.rol === "lectura") return accion === "ver";
  if (user.rol === "user") {
    const acciones = user.permisos?.[modulo];
    if (Array.isArray(acciones)) return acciones.includes(accion);
    if (acciones && typeof acciones === "object") return !!(acciones as Record<string, boolean>)[accion];
    return false;
  }
  // Legacy: operador puede ver+modificar pero no borrar
  if (user.rol === "operador") return accion === "ver" || accion === "modificar";
  return false;
}

/** Helper de retro-compat: ¿el usuario puede modificar cualquier cosa? */
export function puedeEscribir(user?: User | null): boolean {
  if (!user) return false;
  if (user.rol === "admin" || user.rol === "operador") return true;
  if (user.rol === "user") {
    // Cualquier módulo con accion 'modificar' habilita el flag de escritura
    const perms = user.permisos || {};
    for (const acciones of Object.values(perms)) {
      if (Array.isArray(acciones) && acciones.includes("modificar")) return true;
      if (acciones && typeof acciones === "object" && (acciones as Record<string, boolean>).modificar) return true;
    }
  }
  return false;
}
