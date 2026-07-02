"use client";

import { usePathname } from "next/navigation";
import { AuthProvider } from "@/components/auth-provider";
import { Sidebar } from "@/components/sidebar";

/**
 * Decide si renderizar sidebar (rutas privadas) o solo el contenido (login).
 */
// Rutas que NO deben mostrar el sidebar de la app.
// - /login → pantalla de acceso
// - /lote/[token] → vista pública del confeccionista (WhatsApp link)
// - /terminacion/[token] → vista pública del proveedor de terminación
const PUBLIC_PATHS = ["/login"];
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
          <main className="ml-60 flex-1 px-10 py-8">{children}</main>
        </div>
      )}
    </AuthProvider>
  );
}
