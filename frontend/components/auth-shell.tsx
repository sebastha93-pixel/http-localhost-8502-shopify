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

export function AuthShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = esRutaPublica(pathname);

  return (
    <AuthProvider>
      {isPublic ? (
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
