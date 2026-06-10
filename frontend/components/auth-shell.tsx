"use client";

import { usePathname } from "next/navigation";
import { AuthProvider } from "@/components/auth-provider";
import { Sidebar } from "@/components/sidebar";

/**
 * Decide si renderizar sidebar (rutas privadas) o solo el contenido (login).
 */
export function AuthShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = pathname === "/login";

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
