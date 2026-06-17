"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60_000,           // 5 min — datos frescos sin refetch
            gcTime: 30 * 60_000,             // 30 min cache en memoria
            refetchOnWindowFocus: false,     // cambiar de tab del browser NO refetcha
            refetchOnMount: false,           // navegar entre páginas usa caché
            refetchOnReconnect: true,        // reconexión de red sí refetcha
            refetchInterval: false,          // sin polling global; solo donde se declare explícito
            refetchIntervalInBackground: false,
            retry: 1,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
