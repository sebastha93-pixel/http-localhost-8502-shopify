"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoneyShort } from "@/lib/utils";

interface OverviewResp {
  ventas_hoy: { fecha?: string; total?: number; num_pedidos?: number; ticket_promedio?: number };
  delta: { hoy?: number; ayer?: number; pct?: number; up?: boolean };
  serie_12d: number[];
  top_productos: Array<{ sku?: string; nombre?: string; revenue?: number; unidades?: number; pct_del_total?: number }>;
  errores: string[];
}

const FECHA_FMT = new Intl.DateTimeFormat("es-CO", { weekday: "short", day: "numeric", month: "short" });

function Sparkline({ data, height = 60 }: { data: number[]; height?: number }) {
  if (!data?.length) return <div className="text-graphite text-xs">Sin datos</div>;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const w = 100;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1 || 1)) * w;
    const y = height - ((v - min) / range) * height;
    return `${x},${y}`;
  }).join(" ");
  const lastX = ((data.length - 1) / (data.length - 1 || 1)) * w;
  const lastY = height - ((data[data.length - 1] - min) / range) * height;
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="w-full h-full" preserveAspectRatio="none">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-navy" />
      <circle cx={lastX} cy={lastY} r="2" className="fill-navy" />
    </svg>
  );
}

export default function ComercialPage() {
  const { data, isLoading, error, refetch, isFetching } = useQuery<OverviewResp>({
    queryKey: ["comercial-overview"],
    queryFn: () => api.get<OverviewResp>("/api/comercial/overview"),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  if (isLoading) return <LoadingState label="Cargando métricas comerciales..." />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  const v = data.ventas_hoy || {};
  const d = data.delta || {};
  const totalHoy = v.total || 0;
  const ayer = d.ayer || 0;
  const pct = d.pct || 0;
  const up = d.up;

  // Genera labels de los últimos N días
  const serie = data.serie_12d || [];
  const labels = serie.map((_, i) => {
    const dt = new Date();
    dt.setDate(dt.getDate() - (serie.length - 1 - i));
    return FECHA_FMT.format(dt);
  });
  const maxSerie = Math.max(...serie, 1);

  return (
    <PageShell
      title="Comercial"
      subtitle="Ventas de Shopify · datos en vivo (caché 3 min)"
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      {data.errores?.length > 0 && (
        <div className="rounded-md border border-rust/30 bg-rust/5 px-3 py-2 text-xs text-rust">
          Algunos bloques no cargaron: {data.errores.join(" · ")}
        </div>
      )}

      {/* KPIs principales */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard
          label="Ventas hoy"
          value={formatMoneyShort(totalHoy)}
          meta={`${v.num_pedidos || 0} pedidos`}
          accent="navy"
        />
        <KpiCard
          label={up ? "↑ vs ayer" : "↓ vs ayer"}
          value={`${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`}
          meta={`Ayer: ${formatMoneyShort(ayer)}`}
          accent={up ? "teal" : "rust"}
          danger={!up && Math.abs(pct) > 20}
        />
        <KpiCard
          label="Ticket promedio"
          value={formatMoneyShort(v.ticket_promedio || 0)}
          meta="Hoy"
          accent="steel"
        />
        <KpiCard
          label="Pedidos hoy"
          value={String(v.num_pedidos || 0)}
          meta={v.fecha || ""}
          accent="khaki"
        />
      </div>

      {/* Sparkline + tabla diaria */}
      <Card>
        <CardContent className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold uppercase tracking-wider text-graphite">
              Ventas últimos 12 días
            </h3>
            <span className="text-xs text-graphite">
              Total período: <span className="font-semibold text-ink">{formatMoneyShort(serie.reduce((a, b) => a + b, 0))}</span>
            </span>
          </div>
          <div className="h-20">
            <Sparkline data={serie} height={60} />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-graphite uppercase tracking-wider">
                <tr>{labels.map((l) => <th key={l} className="px-1 py-1 text-center font-medium">{l}</th>)}</tr>
              </thead>
              <tbody>
                <tr>
                  {serie.map((val, i) => (
                    <td
                      key={i}
                      className={`px-1 py-1 text-center tabular-nums ${val === maxSerie ? "font-bold text-navy" : "text-ink"}`}
                    >
                      {formatMoneyShort(val)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Top productos */}
      <Card>
        <CardContent className="p-5">
          <h3 className="text-sm font-bold uppercase tracking-wider text-graphite mb-3">
            Top productos (últimos 30 días)
          </h3>
          {data.top_productos?.length === 0 ? (
            <p className="text-sm text-graphite text-center py-6">Sin ventas en el período.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border text-xs uppercase tracking-wider text-graphite">
                  <tr>
                    <th className="text-left py-2 font-medium">#</th>
                    <th className="text-left py-2 font-medium">Producto</th>
                    <th className="text-left py-2 font-medium">SKU</th>
                    <th className="text-right py-2 font-medium">Unidades</th>
                    <th className="text-right py-2 font-medium">Revenue</th>
                    <th className="text-right py-2 font-medium">% del total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.top_productos?.map((p, i) => (
                    <tr key={`${p.sku}-${i}`} className="hover:bg-concrete/30">
                      <td className="py-2.5 text-graphite tabular-nums">{i + 1}</td>
                      <td className="py-2.5 text-ink font-medium">{p.nombre || "—"}</td>
                      <td className="py-2.5 text-graphite text-xs tabular-nums">{p.sku || "—"}</td>
                      <td className="py-2.5 text-right text-ink tabular-nums">{p.unidades || 0}</td>
                      <td className="py-2.5 text-right text-ink font-semibold tabular-nums">{formatMoneyShort(p.revenue || 0)}</td>
                      <td className="py-2.5 text-right text-graphite tabular-nums">{(p.pct_del_total || 0).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-[0.65rem] text-graphite/70 mt-2">
        Próximamente: clientes recurrentes / LTV · análisis por canal · códigos de descuento.
        El módulo Comercial está en v1 — estos quedan para v2.
      </p>
    </PageShell>
  );
}
