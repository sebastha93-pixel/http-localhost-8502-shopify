/**
 * Cascarón del POS. Deliberadamente distinto al del ERP.
 *
 * Sin sidebar del ERP, sin campanita, sin paleta de comandos: el POS trae su
 * propio rail de navegación. Cada elemento ajeno es una forma de salirse de la
 * tarea, y una cajera con una clienta enfrente no tiene por qué poder llegar a
 * Producción.
 *
 * El sistema visual es el del handoff v2 ("Apple-grade"): tema CLARO, fuente
 * del SISTEMA, tarjetas blancas redondas con sombra suave, botones píldora.
 * Va aislado bajo `.pos-raiz` porque el ERP tiene su propia paleta y dos
 * sistemas sueltos en el mismo `:root` se pisan.
 *
 * ── YA NO SE DESCARGA NINGUNA FUENTE (v2, 2026-08-25) ──────────────────────
 * Aquí vivían Barlow y Barlow Condensed, de la v1. La v2 pide el stack del
 * sistema (ver `--pos-fuente` en `pos.css`), así que las dos se van: mantener
 * cargadas dos familias que ya no pinta nadie le cuesta a la caja dos
 * descargas en el arranque, que es justo el momento en que la cajera está
 * esperando para abrir el turno.
 */
import type { Metadata } from "next";
import "./pos.css";
import { RegistrarSW } from "@/components/pos/registrar-sw";

export const metadata: Metadata = {
  title: "POS · MALE'DENIM",
  // La caja se opera a pantalla completa, sin barra del navegador.
  appleWebApp: { capable: true, statusBarStyle: "default" },
  manifest: "/pos.webmanifest",
};

export default function PosLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="pos-raiz min-h-screen antialiased">
      {/* Lo que permite que la caja ABRA sin internet. Todo lo demás del
          offline sólo funciona si la pestaña ya estaba viva. */}
      <RegistrarSW />
      {children}
    </div>
  );
}
