"use client";

/**
 * Export a Excel vía CSV (UTF-8 con BOM + separador ';').
 * El BOM hace que Excel respete tildes/ñ; el ';' es el separador de listas
 * en la configuración regional es-CO, así Excel abre el archivo en columnas
 * directamente con doble click, sin asistente de importación.
 */
export function exportarExcel(
  nombreArchivo: string,
  headers: string[],
  filas: Array<Array<string | number | null | undefined>>,
) {
  const esc = (v: string | number | null | undefined): string => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lineas = [headers.map(esc).join(";"), ...filas.map((f) => f.map(esc).join(";"))];
  const blob = new Blob(["﻿" + lineas.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombreArchivo.endsWith(".csv") ? nombreArchivo : `${nombreArchivo}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
