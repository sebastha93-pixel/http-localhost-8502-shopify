"use client";

import { useState } from "react";
import { Printer, FileSpreadsheet, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Sacar el inventario: imprimir (PDF) o trabajarlo (Excel).
 *
 * POR QUÉ (2026-08-05, pedido de Sebastián): los datos estaban en pantalla y no
 * había forma de sacarlos. Un inventario sirve para caminar la bodega y contar, y
 * eso se hace con una hoja en la mano.
 *
 * El PDF trae una columna "Conteo físico" EN BLANCO: al lado de lo que el sistema
 * cree, un espacio para escribir lo que de verdad hay. Sin esa columna el papel
 * solo sirve para mirar.
 *
 * Se abre en una pestaña nueva en vez de descargar, porque el visor del navegador
 * ya tiene el botón de imprimir — que es lo que se pidió. Descargar obligaría a
 * abrir el archivo aparte.
 */

interface Props {
  /** telas | insumos | ambos — qué incluir en el PDF. */
  tipo?: "telas" | "insumos" | "ambos";
}

export function BotonInformeInventario({ tipo = "ambos" }: Props) {
  const [cargando, setCargando] = useState<"pdf" | "xlsx" | null>(null);
  const [error, setError] = useState("");

  async function abrirPdf() {
    setCargando("pdf"); setError("");
    try {
      // blobUrl pasa por el api con el token; una URL directa no llevaría sesión.
      const url = await api.blobUrl(
        `/api/produccion/inventario/informe.pdf?tipo=${tipo}`);
      const w = window.open(url, "_blank");
      if (!w) setError("El navegador bloqueó la pestaña. Permite las ventanas emergentes.");
      // No se revoca de inmediato: la pestaña nueva todavía está leyendo el blob.
      setTimeout(() => URL.revokeObjectURL(url), 120_000);
    } catch (e) {
      setError(`No se pudo generar el PDF: ${(e as Error).message}`);
    } finally {
      setCargando(null);
    }
  }

  async function bajarExcel() {
    setCargando("xlsx"); setError("");
    try {
      const hoy = new Date().toISOString().slice(0, 10);
      await api.download("/api/produccion/inventario/informe.xlsx",
                         `inventario_${hoy}.xlsx`);
    } catch (e) {
      setError(`No se pudo generar el Excel: ${(e as Error).message}`);
    } finally {
      setCargando(null);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-2">
        <button
          onClick={abrirPdf}
          disabled={cargando !== null}
          title="Abre el inventario en PDF, listo para imprimir, con columna para el conteo físico"
          className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-3 py-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-ink-900 transition-colors hover:bg-cloud disabled:opacity-50 dark:text-foreground dark:hover:bg-ink-800"
        >
          {cargando === "pdf"
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <Printer className="h-3.5 w-3.5" />}
          Imprimir
        </button>
        <button
          onClick={bajarExcel}
          disabled={cargando !== null}
          title="Descarga el inventario en Excel: una hoja de telas y una de insumos"
          className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-3 py-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-graphite transition-colors hover:bg-cloud disabled:opacity-50 dark:hover:bg-ink-800"
        >
          {cargando === "xlsx"
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <FileSpreadsheet className="h-3.5 w-3.5" />}
          Excel
        </button>
      </div>
      {error && <p className="max-w-xs text-right text-[0.68rem] text-terracotta">{error}</p>}
    </div>
  );
}
