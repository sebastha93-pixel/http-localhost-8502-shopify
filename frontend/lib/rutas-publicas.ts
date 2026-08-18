/**
 * QUÉ RUTAS SE VEN SIN SESIÓN. Una sola lista, un solo lugar.
 *
 * POR QUÉ EXISTE ESTE ARCHIVO (2026-08-18). La lista estaba DUPLICADA: una
 * copia en `auth-shell.tsx` (que decide si se pinta el menú lateral) y otra en
 * `auth-provider.tsx` (que decide si te expulsa al login). Al agregar las
 * pantallas de recuperar contraseña actualicé la primera y no vi la segunda,
 * así que el enlace del correo abría `/restablecer`… y el guardián lo devolvía
 * al login antes de mostrar nada. La pantalla existía, compilaba, se
 * desplegaba, y era inalcanzable.
 *
 * Dos listas para el mismo concepto no es un detalle de estilo: la que se
 * olvida no falla con un error, falla en silencio y con una redirección que
 * parece una decisión deliberada del sistema.
 *
 * AL AGREGAR UNA PANTALLA PÚBLICA, SE AGREGA ACÁ Y EN NINGÚN OTRO LADO.
 */

/** Rutas exactas. */
export const RUTAS_PUBLICAS = [
  "/login",         // pantalla de acceso
  "/recuperar",     // pedir el enlace para restablecer la contraseña
  "/restablecer",   // escribir la contraseña nueva (llega por correo)
] as const;

/** Rutas con parámetro: se comparan por prefijo. */
export const PREFIJOS_PUBLICOS = [
  "/lote/",         // vista del confeccionista, sin login (llega por WhatsApp)
  "/terminacion/",  // vista del proveedor de terminación
] as const;

export function esRutaPublica(pathname: string | null | undefined): boolean {
  const p = pathname || "";
  return (RUTAS_PUBLICAS as readonly string[]).includes(p) ||
         (PREFIJOS_PUBLICOS as readonly string[]).some((x) => p.startsWith(x));
}
