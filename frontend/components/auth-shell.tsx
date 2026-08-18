"use client";

import { usePathname } from "next/navigation";
import { AuthProvider } from "@/components/auth-provider";
import { Sidebar } from "@/components/sidebar";
import { CommandPalette } from "@/components/command-palette";
import { NotificacionesBell } from "@/components/notificaciones-bell";

/**
 * Decide si renderizar sidebar (rutas privadas) o solo el contenido (login).
 */
// Rutas que NO deben mostrar el sidebar de la app.
// - /login → pantalla de acceso
// - /lote/[token] → vista pública del confeccionista (WhatsApp link)
// - /terminacion/[token] → vista pública del proveedor de terminación
// /recuperar y /restablecer son públicas por definición: a ellas llega quien NO
// puede entrar. Si quedaran detrás del guardián, la recuperación de contraseña
// exigiría estar logueado para poder recuperar la contraseña.
const PUBLIC_PATHS = ["/login", "/recuperar", "/restablecer"];
const PUBLIC_PREFIXES = ["/lote/", "/terminacion/"];

export function AuthShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = PUBLIC_PATHS.includes(pathname) ||
                   PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));

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
