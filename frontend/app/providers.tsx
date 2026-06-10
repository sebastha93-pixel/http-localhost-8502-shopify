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
            gcTime: 30 * 60_000,             // 30 min — basura recolectada
            refetchOnWindowFocus: false,
            refetchOnMount: false,           // navegar entre páginas no refetcha
            refetchInterval: 15 * 60_000,    // auto-refresh cada 15 min
            refetchIntervalInBackground: true,
            retry: 1,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
