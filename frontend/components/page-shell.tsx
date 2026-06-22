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
          <h1 className="font-display text-[1.85rem] font-medium tracking-tight text-ink-900 dark:text-foreground">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 text-sm text-graphite">
              {subtitle}
              {isFetching && <Loader2 className="inline ml-2 h-3 w-3 animate-spin text-steel-500" />}
            </p>
          )}
        </div>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="rounded-sm border border-border bg-card px-3.5 py-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-ink-900 transition-colors hover:bg-cloud dark:text-foreground dark:hover:bg-ink-800"
          >
            Refrescar
          </button>
        )}
      </div>
      {children}
    </div>
  );
}

export function LoadingState({ label = "Cargando…" }: { label?: string }) {
  return (
    <div className="space-y-4">
      <div className="h-20 rounded-md border border-border bg-card overflow-hidden">
        <div className="h-full w-full shimmer" />
      </div>
      <div className="grid grid-cols-6 gap-px rounded-md border border-border overflow-hidden bg-border">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="bg-card p-5">
            <div className="h-2 w-16 rounded-sm bg-concrete/60 shimmer" />
            <div className="mt-3 h-5 w-10 rounded-sm bg-concrete/60 shimmer" />
          </div>
        ))}
      </div>
      <div className="h-64 rounded-md border border-border bg-card overflow-hidden">
        <div className="h-full w-full shimmer" />
      </div>
      <p className="text-center text-xs text-graphite">{label}</p>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <Card className="border-terracotta/30 bg-terracotta/[0.03]">
      <CardContent className="p-10 text-center">
        <p className="font-display text-lg text-terracotta">No se pudieron cargar los datos.</p>
        <p className="mt-1 text-sm text-graphite">{(error as Error)?.message ?? "Error desconocido"}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-5 rounded-sm bg-navy-600 px-4 py-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-white transition-colors hover:bg-navy-700"
          >
            Reintentar
          </button>
        )}
      </CardContent>
    </Card>
  );
}
