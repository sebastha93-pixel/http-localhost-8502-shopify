"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 2 * 60_000,           // 2 min — datos frescos sin refetch
            gcTime: 30 * 60_000,             // 30 min — basura recolectada
            refetchOnWindowFocus: true,      // volver a la pestaña → refresca
            refetchOnMount: false,           // navegar entre páginas no refetcha
            refetchInterval: 2 * 60_000,     // auto-refresh cada 2 min
            refetchIntervalInBackground: false,  // pausa si la pestaña no está visible
            retry: 1,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
