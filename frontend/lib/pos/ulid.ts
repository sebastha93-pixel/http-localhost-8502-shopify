/**
 * ULID generado en el DISPOSITIVO.
 *
 * No es un detalle: es la llave de idempotencia de toda la venta (ADR-005).
 * El dispositivo crea el id ANTES de hablar con el servidor, así que puede
 * reintentar el cierre cuarenta veces sin miedo — el servidor acepta el
 * primero y responde lo mismo a los demás.
 *
 * Que el id lo ponga el cliente es lo que permite vender sin internet: una
 * venta hecha en modo avión ya tiene su identidad definitiva cuando por fin
 * sincroniza.
 *
 * Formato: 26 caracteres en base32 de Crockford (sin I, L, O, U para que
 * nadie confunda un 1 con una l al leerlo en un ticket).
 * 10 de tiempo (ms desde epoch) + 16 de azar.
 */

const ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

function tiempo(ms: number): string {
  let salida = "";
  let resto = ms;
  for (let i = 0; i < 10; i++) {
    salida = ALFABETO[resto % 32] + salida;
    resto = Math.floor(resto / 32);
  }
  return salida;
}

function azar(): string {
  const bytes = new Uint8Array(16);
  // crypto.getRandomValues, no Math.random: dos cajas de la misma tienda
  // generando ids a la vez no pueden colisionar.
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => ALFABETO[b % 32]).join("");
}

export function nuevoUlid(ahora: number = Date.now()): string {
  return tiempo(ahora) + azar();
}

const PATRON = /^[0-9A-HJKMNP-TV-Z]{26}$/;

export function esUlid(valor: string): boolean {
  return PATRON.test(valor);
}
