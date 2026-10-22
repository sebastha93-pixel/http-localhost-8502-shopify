/**
 * Lo que la pistola escribe, corregido.
 *
 * La pistola manda TECLAS, no letras. Configurada como teclado de EE. UU. en
 * un Windows en español, la tecla del guion sale como apóstrofo: el código
 * `26621-1T4` llega como `26621'1T4` y no encuentra nada (Arrayanes,
 * 2026-10-21). Entre dos números un apóstrofo no tiene sentido en este
 * catálogo, así que se vuelve guion; lo demás se deja como se escribió.
 */
export function corregirEscaneo(texto: string): string {
  return texto.replace(/(\d)['´’](?=\d)/g, "$1-");
}
