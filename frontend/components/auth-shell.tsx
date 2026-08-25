"use client";

import { usePathname } from "next/navigation";
import { AuthProvider } from "@/components/auth-provider";
import { Sidebar } from "@/components/sidebar";
import { CommandPalette } from "@/components/command-palette";
import { NotificacionesBell } from "@/components/notificaciones-bell";
import { esRutaPublica } from "@/lib/rutas-publicas";

/**
 * Decide si renderizar sidebar (rutas privadas) o solo el contenido (login).
 */
// La lista vive en lib/rutas-publicas.ts — ver por qué está allá y no acá.

// El POS entra por el login del ERP (correo + contrasena) como todo lo
// demas, pero NO comparte su navegacion: trae su propio rail. Cada enlace
// ajeno es una forma de salirse de la venta, y una cajera con una clienta
// enfrente no tiene por que poder llegar a Produccion.
const SIN_CHROME_ERP = ["/pos"];

export function AuthShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  // ⚠️ DOS COSAS DISTINTAS QUE AQUÍ SE SUMAN, y conviene no fundirlas:
  //
  //   · `esRutaPublica` = la ruta va SIN sesión (login, enlaces firmados).
  //   · `SIN_CHROME_ERP` = la ruta SÍ exige sesión, pero no quiere la
  //     navegación del ERP. Es el caso del POS.
  //
  // Se ven iguales porque las dos esconden el sidebar, pero meter `/pos` en
  // la lista de rutas públicas le quitaría la autenticación a la caja sin que
  // nadie lo note hasta que alguien entre sin contraseña.
  const sinChromeERP = esRutaPublica(pathname) ||
                       SIN_CHROME_ERP.some((p) => pathname.startsWith(p));

  return (
    <AuthProvider>
      {sinChromeERP ? (
        children
      ) : (
        <div className="flex min-h-screen">
          <Sidebar />
          <CommandPalette />
          {/* Campanita fija arriba a la derecha. Va acá y no en PageShell para
              que esté en TODAS las páginas privadas, incluidas las que no usan
              PageShell. */}
          <NotificacionesBell />
          <main className="ml-60 flex-1 px-10 py-8">{children}</main>
        </div>
      )}
    </AuthProvider>
  );
}
