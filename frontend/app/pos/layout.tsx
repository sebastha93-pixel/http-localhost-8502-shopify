/**
 * Cascarón del POS. Deliberadamente distinto al del ERP.
 *
 * Sin sidebar, sin campanita, sin paleta de comandos. Cada elemento de
 * navegación es una forma de salirse de la tarea, y una cajera con una
 * clienta enfrente no tiene por qué poder llegar a Producción.
 *
 * Tema oscuro fijo: el POS vive diez horas frente a una vitrina iluminada.
 * No hereda el tema del ERP porque no es una preferencia — es la condición
 * de trabajo del equipo.
 */
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "POS · MALE'DENIM",
  // La caja se opera a pantalla completa, sin barra del navegador.
  appleWebApp: { capable: true, statusBarStyle: "black-translucent" },
};

export default function PosLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="pos-raiz min-h-screen bg-[#0E1417] text-[#F4F3F0] antialiased">
      {children}
    </div>
  );
}
