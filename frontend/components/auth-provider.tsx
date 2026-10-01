"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { homePath } from "@/lib/nav";
import { User, getToken, clearToken } from "@/lib/auth";
import { esRutaPublica } from "@/lib/rutas-publicas";
import { Loader2 } from "lucide-react";

interface Ctx {
  user: User | null;
  loading: boolean;
  logout: () => void;
}

const AuthCtx = createContext<Ctx>({ user: null, loading: true, logout: () => {} });

export const useAuth = () => useContext(AuthCtx);


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

  const isPublic = esRutaPublica(pathname);
  const loading = !hydrated || (!!token && meQ.isLoading);

  // Redirige a /login si no hay token y no es ruta pública.
  // GATE: solo después de hidratar para no expulsar usuarios con sesión.
  //
  // SE LEE EL TOKEN VIVO, NO EL DEL ESTADO. `setToken` escribe en localStorage
  // y el estado de aquí sólo se refresca al cambiar de ruta, un render
  // después. En ese render intermedio —el primero de la ruta a la que acabas
  // de entrar— el estado todavía dice `null` y esta compuerta expulsaba al
  // login a quien se acababa de autenticar. El rebote era invisible porque el
  // login, viéndote ya con sesión, te mandaba a tu página de inicio: el
  // destino equivocado coincidía con el de siempre. Con `?volver=` deja de
  // coincidir, y el enlace de una caja del POS terminaba en Centro de Control.
  useEffect(() => {
    if (!hydrated) return;
    const vivo = getToken();
    if (!vivo && !isPublic) {
      // Guardamos dónde estaba para devolverlo ahí después de entrar, en vez
      // de mandarlo siempre al home y que pierda la pantalla. CON la búsqueda:
      // el enlace de cada caja del POS es `/pos/venta?caja=…`, y sin ella la
      // tableta volvía del login sin saber qué caja es.
      const actual = pathname + window.location.search;
      const volver = pathname && pathname !== "/"
        ? `?volver=${encodeURIComponent(actual)}` : "";
      router.replace(`/login${volver}`);
    }
    // Si ya estás autenticado y estás en /login, mándate a la app.
    // No aplicamos esta regla a las otras rutas públicas (/lote/, /terminacion/)
    // porque un admin puede necesitar ver esas vistas estando logueado.
    //
    // RESPETA `?volver=`, igual que el formulario: quien llegó al login desde
    // un enlace concreto —la caja de una tienda— tiene que volver ahí, no a la
    // página de inicio. Sólo rutas internas; un `volver` con http:// o //otro
    // sería un redirect abierto.
    if (vivo && pathname === "/login" && meQ.data) {
      const pedido = new URLSearchParams(window.location.search).get("volver") || "";
      const destino = pedido.startsWith("/") && !pedido.startsWith("//")
        ? pedido : homePath(meQ.data);
      router.replace(destino);
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
