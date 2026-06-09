"use client";

import { Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface PageShellProps {
  title: string;
  subtitle?: string;
  isFetching?: boolean;
  onRefresh?: () => void;
  children: React.ReactNode;
}

export function PageShell({ title, subtitle, isFetching, onRefresh, children }: PageShellProps) {
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between border-b border-border pb-5">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink">{title}</h1>
          {subtitle && (
            <p className="mt-1 text-sm text-graphite">
              {subtitle}
              {isFetching && <Loader2 className="inline ml-2 h-3 w-3 animate-spin text-steel" />}
            </p>
          )}
        </div>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="rounded-md border border-border bg-white px-4 py-2 text-xs font-semibold uppercase tracking-wider text-ink hover:bg-concrete"
          >
            Refrescar
          </button>
        )}
      </div>
      {children}
    </div>
  );
}

export function LoadingState({ label = "Cargando datos..." }: { label?: string }) {
  return (
    <div className="flex h-96 items-center justify-center text-graphite">
      <Loader2 className="mr-2 h-5 w-5 animate-spin" />
      {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <Card>
      <CardContent className="p-10 text-center">
        <p className="text-crimson font-semibold mb-2">Error al cargar datos</p>
        <p className="text-sm text-graphite">{(error as Error)?.message ?? "Error desconocido"}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-4 rounded-md bg-ink px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black"
          >
            Reintentar
          </button>
        )}
      </CardContent>
    </Card>
  );
}
