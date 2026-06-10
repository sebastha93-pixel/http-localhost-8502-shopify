"use client";

const TOKEN_KEY = "maledenim_token";

export interface User {
  id: string;
  email: string;
  nombre: string;
  rol: "admin" | "operador" | "lectura";
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

export const ROL_LABEL: Record<User["rol"], string> = {
  admin: "Administrador",
  operador: "Operador",
  lectura: "Solo lectura",
};

export function puedeEscribir(user?: User | null): boolean {
  return user?.rol === "admin" || user?.rol === "operador";
}

export function esAdmin(user?: User | null): boolean {
  return user?.rol === "admin";
}
