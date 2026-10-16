/**
 * El número de identificación como lo dicta quien compra.
 *
 * Una cédula llega con puntos o sin ellos. Un NIT llega además con su dígito
 * de verificación después de un guion: `900.123.456-7`. Quitarle «todo lo que
 * no sea dígito» lo convertía en `9001234567` —otro número, de diez cifras—:
 * la búsqueda no encontraba a la empresa y el alta la creaba con un NIT falso.
 */

// Con guion sólo se escribe un NIT, y lo de después del guion es su dígito.
const DIGITO_DE_VERIFICACION = /-\s*\d\s*$/;

/** Para buscar: los dígitos SIN el de verificación, que la base no guarda. */
export function documentoParaBuscar(texto: string): string {
  return texto.replace(DIGITO_DE_VERIFICACION, "").replace(/\D/g, "");
}

/** Para crear: un NIT con guion queda `901495189-5` —el servidor usa el guion
 *  para separar el dígito y guardarla como empresa—. Lo demás va tal cual: un
 *  pasaporte lleva letras, y los puntos y espacios los quita el servidor. */
export function documentoParaCrear(texto: string): string {
  const m = texto.match(/^([\d.\s]+)-\s*(\d)\s*$/);
  if (!m) return texto.trim();
  return `${m[1].replace(/\D/g, "")}-${m[2]}`;
}

/** Escrito como NIT con su dígito: `901495189-5`. */
export function pareceNitConDigito(texto: string): boolean {
  return /^\d{6,12}-\d$/.test(documentoParaCrear(texto));
}
