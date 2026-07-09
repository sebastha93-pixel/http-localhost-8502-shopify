"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface PageShellProps {
  title: string;
  subtitle?: string;
  isFetching?: boolean;
  onRefresh?: () => void;
  /** Timestamp (ms) de la última carga de datos — muestra "Actualizado hace Xm". */
  dataUpdatedAt?: number;
  children: React.ReactNode;
}

/** "Actualizado hace 4 min" con tick cada 30s. */
function UpdatedAgo({ at }: { at: number }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);
  if (!at) return null;
  const mins = Math.floor((Date.now() - at) / 60_000);
  const txt = mins < 1 ? "hace un momento" : mins === 1 ? "hace 1 min" : mins < 60 ? `hace ${mins} min` : `hace ${Math.floor(mins / 60)} h`;
  return <span className="text-[0.68rem] text-graphite/80 tabular-nums">Actualizado {txt}</span>;
}

export function PageShell({ title, subtitle, isFetching, onRefresh, dataUpdatedAt, children }: PageShellProps) {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-medium tracking-tight text-ink-900 dark:text-foreground md:text-[1.7rem]">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 text-sm leading-snug text-graphite">
              {subtitle}
              {isFetching && <Loader2 className="inline ml-2 h-3 w-3 animate-spin text-steel-500" />}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3 self-start sm:self-auto">
        {dataUpdatedAt ? <UpdatedAgo at={dataUpdatedAt} /> : null}
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="shrink-0 rounded-sm border border-border bg-card px-3.5 py-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-ink-900 transition-colors hover:bg-cloud dark:text-foreground dark:hover:bg-ink-800 sm:self-auto"
          >
            Refrescar
          </button>
        )}
        </div>
      </div>
      {children}
    </div>
  );
}

/** Skeleton de tabla: header + N filas shimmer. Para cargas dentro de un tab. */
export function TableSkeleton({ rows = 6, label }: { rows?: number; label?: string }) {
  return (
    <Card>
      <CardContent className="p-0">
        <div className="border-b border-border bg-cloud/40 px-4 py-3">
          <div className="h-2.5 w-40 rounded-sm bg-concrete/60 shimmer" />
        </div>
        <div className="divide-y divide-border">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="flex items-center gap-6 px-4 py-3.5">
              <div className="h-3 w-1/3 rounded-sm bg-concrete/50 shimmer" />
              <div className="ml-auto h-3 w-14 rounded-sm bg-concrete/40 shimmer" />
              <div className="h-3 w-20 rounded-sm bg-concrete/50 shimmer" />
              <div className="h-3 w-12 rounded-sm bg-concrete/40 shimmer" />
            </div>
          ))}
        </div>
        {label && <p className="border-t border-border px-4 py-2.5 text-xs text-graphite">{label}</p>}
      </CardContent>
    </Card>
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
