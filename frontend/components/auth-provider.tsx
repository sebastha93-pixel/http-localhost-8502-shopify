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

const PUBLIC_PATHS = ["/login"];

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const [token, setLocalToken] = useState<string | null>(null);

  // Hidratamos el token client-side para evitar mismatch SSR
  useEffect(() => {
    setLocalToken(getToken());
  }, [pathname]);

  const meQ = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.get<User>("/api/auth/me"),
    enabled: !!token,
    retry: false,
    staleTime: 5 * 60_000,
  });

  const isPublic = PUBLIC_PATHS.includes(pathname);
  const loading = !!token && meQ.isLoading;

  // Redirige a /login si no hay token y no es ruta pública
  useEffect(() => {
    if (!token && !isPublic) {
      router.replace("/login");
    }
    if (token && isPublic && meQ.data) {
      router.replace("/centro-control");
    }
  }, [token, isPublic, router, meQ.data]);

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
