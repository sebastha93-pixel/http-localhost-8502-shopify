/**
 * Leer un conteo pegado desde Excel (o un CSV) — sin librerías de Excel.
 *
 * Lo práctico en tienda: en el Excel del conteo se seleccionan las columnas
 * y se pegan aquí. Excel pega con tabuladores; un CSV trae `;` o `,`.
 *
 * Por fila: el CÓDIGO es la primera celda y la CANTIDAD la última celda que
 * sea un número entero. Así sirve igual «código | cantidad» que
 * «código | nombre | talla | cantidad». Lo que no tenga cantidad (los
 * encabezados) se salta y se cuenta, para que nadie crea que entró.
 */
import type { LineaConteo } from "./api";

export interface LecturaConteo {
  lineas: LineaConteo[];
  saltadas: number;
}

function cantidadDe(celda: string): number | null {
  const t = celda.trim().replace(/\s/g, "");
  // «3», «3,00», «3.00»: unidades enteras, a veces con decimales en cero.
  const m = t.match(/^(\d{1,6})(?:[.,]0+)?$/);
  return m ? Number(m[1]) : null;
}

export function leerConteo(texto: string): LecturaConteo {
  const lineas: LineaConteo[] = [];
  let saltadas = 0;
  for (const fila of texto.replace(/\r/g, "").split("\n")) {
    if (!fila.trim()) continue;
    const sep = fila.includes("\t") ? "\t" : fila.includes(";") ? ";" : ",";
    const celdas = fila.split(sep).map((c) => c.trim().replace(/^"|"$/g, ""));
    const codigo = celdas[0] ?? "";
    let cantidad: number | null = null;
    for (let i = celdas.length - 1; i >= 1; i--) {
      cantidad = cantidadDe(celdas[i]);
      if (cantidad !== null) break;
    }
    if (!codigo || cantidad === null) {
      saltadas++;
      continue;
    }
    lineas.push({ codigo, cantidad });
  }
  return { lineas, saltadas };
}
