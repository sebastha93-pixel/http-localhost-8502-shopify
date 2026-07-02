"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { User, getToken, clearToken } from "@/lib/auth";
import { Loader2 } from "lucide-react";

interface Ctx {
  user: User | null;
  loading: boolean;
  logout: () => void;
}

const AuthCtx = createContext<Ctx>({ user: null, loading: true, logout: () => {} });

export const useAuth = () => useContext(AuthCtx);

// Rutas públicas — no requieren token.
// /lote/[token] es la vista del confeccionista sin login.
// /terminacion/[token] es la vista del proveedor de terminación.
const PUBLIC_PATHS = ["/login"];
const PUBLIC_PREFIXES = ["/lote/", "/terminacion/"];

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const [token, setLocalToken] = useState<string | null>(null);
  // hydrated=true cuando ya leímos localStorage; antes NO decidimos nada.
  // Evita una race: el useEffect de redirect veía token=null en el primer
  // render y mandaba al /login a usuarios que SÍ tenían sesión, antes de
  // que llegáramos a leer el token. Resultado: F5/bookmark/link-directo
  // en cualquier ruta privada terminaba en /centro-control.
  const [hydrated, setHydrated] = useState(false);

  // Hidratamos el token client-side para evitar mismatch SSR
  useEffect(() => {
    setLocalToken(getToken());
    setHydrated(true);
  }, [pathname]);

  const meQ = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.get<User>("/api/auth/me"),
    enabled: !!token,
    retry: false,
    staleTime: 5 * 60_000,
  });

  const isPublic = PUBLIC_PATHS.includes(pathname) ||
                   PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));
  const loading = !hydrated || (!!token && meQ.isLoading);

  // Redirige a /login si no hay token y no es ruta pública.
  // GATE: solo después de hidratar para no expulsar usuarios con sesión.
  useEffect(() => {
    if (!hydrated) return;
    if (!token && !isPublic) {
      router.replace("/login");
    }
    // Si ya estás autenticado y estás en /login, mándate a la app.
    // No aplicamos esta regla a las otras rutas públicas (/lote/, /terminacion/)
    // porque un admin puede necesitar ver esas vistas estando logueado.
    if (token && pathname === "/login" && meQ.data) {
      router.replace("/centro-control");
    }
  }, [hydrated, token, pathname, isPublic, router, meQ.data]);

  const logout = () => {
    clearToken();
    qc.clear();
    setLocalToken(null);
    router.replace("/login");
  };

  // Mientras carga el /me, splash
  if (loading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-cream">
        <Loader2 className="h-6 w-6 animate-spin text-graphite" />
      </div>
    );
  }

  // Ruta privada sin token → redirigirá; no renderizamos nada para evitar flash
  if (!isPublic && !token) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-cream">
        <Loader2 className="h-6 w-6 animate-spin text-graphite" />
      </div>
    );
  }

  return (
    <AuthCtx.Provider value={{ user: meQ.data ?? null, loading, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}
