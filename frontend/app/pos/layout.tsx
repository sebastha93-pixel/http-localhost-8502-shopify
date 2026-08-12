/**
 * Cascarón del POS. Deliberadamente distinto al del ERP.
 *
 * Sin sidebar del ERP, sin campanita, sin paleta de comandos: el POS trae su
 * propio rail de navegación. Cada elemento ajeno es una forma de salirse de la
 * tarea, y una cajera con una clienta enfrente no tiene por qué poder llegar a
 * Producción.
 *
 * El sistema visual es el del handoff ("Industry" retemado): tema CLARO,
 * Barlow + Barlow Condensed, estética de plano — esquinas rectas, bordes
 * finos, marcas de registro. Va aislado bajo `.pos-raiz` porque el ERP tiene
 * su propia paleta y dos sistemas sueltos en el mismo `:root` se pisan.
 */
import type { Metadata } from "next";
import { Barlow, Barlow_Condensed } from "next/font/google";
import "./pos.css";

const barlow = Barlow({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-barlow",
  display: "swap",
});

const barlowCondensed = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-barlow-condensed",
  display: "swap",
});

export const metadata: Metadata = {
  title: "POS · MALE'DENIM",
  // La caja se opera a pantalla completa, sin barra del navegador.
  appleWebApp: { capable: true, statusBarStyle: "default" },
};

export default function PosLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className={`pos-raiz min-h-screen antialiased ${barlow.variable} ${barlowCondensed.variable}`}
    >
      {children}
    </div>
  );
}
