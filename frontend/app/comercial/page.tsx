"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { formatMoneyShort } from "@/lib/utils";

type Periodo = "7d" | "30d" | "90d" | "ytd";

interface OverviewResp {
  ventas_hoy: { fecha?: string; total?: number; num_pedidos?: number; ticket_promedio?: number };
  delta: { hoy?: number; ayer?: number; pct?: number; up?: boolean };
  serie_12d: number[];
  top_productos: Array<{ sku?: string; nombre?: string; revenue?: number; unidades?: number; pct_del_total?: number }>;
  errores: string[];
}

interface CompResp {
  semana: { actual: { total: number; num_pedidos: number }; anterior: { total: number; num_pedidos: number }; pct: number; up: boolean };
  mes:    { actual: { total: number; num_pedidos: number }; anterior: { total: number; num_pedidos: number }; pct: number; up: boolean };
  yoy:    { actual: { total: number; num_pedidos: number }; anterior: { total: number; num_pedidos: number }; pct: number; up: boolean };
}

interface ClientesResp {
  total_clientes_unicos: number;
  total_ordenes: number;
  revenue_total: number;
  pct_recurrentes: number;
  pct_nuevos: number;
  ltv_promedio: number;
  tasa_recompra_60d: number;
  top_clientes: Array<{ nombre: string; email: string; revenue: number; ordenes: number }>;
}

interface VentasPeriodoResp {
  periodo: string;
  desde: string;
  hasta: string;
  resumen: { total: number; num_pedidos: number; ticket_promedio: number };
  serie: Array<{ fecha: string; total: number }>;
}

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

function DeltaBadge({ pct, up }: { pct: number; up: boolean }) {
  const tone = up ? "normal" : pct < -10 ? "critico" : "riesgo";
  return <Badge tone={tone}>{up ? "↑" : "↓"} {Math.abs(pct).toFixed(1)}%</Badge>;
}

export default function ComercialPage() {
  const [periodo, setPeriodo] = useState<Periodo>("30d");
  // Tabs lazy: solo dispara la query del tab activo. Los demás esperan
  // a que el usuario los abra. Reduce 4 queries paralelas a 1 en carga
  // inicial (los datos pesados de Shopify ya no bloquean ver "Hoy").
  const [tabActivo, setTabActivo] = useState<"hoy" | "comp" | "periodo" | "clientes">("hoy");

  const overview = useQuery<OverviewResp>({
    queryKey: ["comercial-overview"],
    queryFn: () => api.get<OverviewResp>("/api/comercial/overview"),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    enabled: tabActivo === "hoy",
  });

  const comp = useQuery<CompResp>({
    queryKey: ["comercial-comp"],
    queryFn: () => api.get<CompResp>("/api/comercial/comparativas"),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    enabled: tabActivo === "comp",
  });

  const ventasP = useQuery<VentasPeriodoResp>({
    queryKey: ["comercial-vp", periodo],
    queryFn: () => api.get<VentasPeriodoResp>(`/api/comercial/ventas-periodo?periodo=${periodo}`),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    enabled: tabActivo === "periodo",
  });

  const cli = useQuery<ClientesResp>({
    queryKey: ["comercial-clientes"],
    queryFn: () => api.get<ClientesResp>("/api/comercial/clientes?dias=90"),
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    enabled: tabActivo === "clientes",
  });

  if (overview.isLoading) return <LoadingState label="Cargando métricas comerciales..." />;
  if (overview.error || !overview.data) return <ErrorState error={overview.error} onRetry={() => overview.refetch()} />;

  const data = overview.data;
  const v = data.ventas_hoy || {};
  const d = data.delta || {};
  const up = !!d.up;
  const pct = d.pct || 0;
  const serie = data.serie_12d || [];

  return (
    <PageShell
      title="Comercial"
      subtitle="Ventas y clientes · Shopify"
      isFetching={overview.isFetching}
      onRefresh={() => { overview.refetch(); comp.refetch(); ventasP.refetch(); cli.refetch(); }}
    >
      {data.errores?.length > 0 && (
        <div className="rounded-md border border-rust/30 bg-rust/5 px-3 py-2 text-xs text-rust">
          Algunos bloques no cargaron: {data.errores.join(" · ")}
        </div>
      )}

      {/* Tabs: Hoy | Comparativas | Período | Clientes */}
      <Tabs value={tabActivo} onValueChange={(v) => setTabActivo(v as typeof tabActivo)}>
        <TabsList>
          <TabsTrigger value="hoy">Hoy</TabsTrigger>
          <TabsTrigger value="comp">Comparativas</TabsTrigger>
          <TabsTrigger value="periodo">Por período</TabsTrigger>
          <TabsTrigger value="clientes">Clientes</TabsTrigger>
        </TabsList>

        {/* ─── TAB HOY ─── */}
        <TabsContent value="hoy" className="space-y-4">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <KpiCard label="Ventas hoy" value={formatMoneyShort(v.total || 0)} meta={`${v.num_pedidos || 0} pedidos`} accent="navy" />
            <KpiCard label={up ? "↑ vs ayer" : "↓ vs ayer"} value={`${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`} meta={`Ayer: ${formatMoneyShort(d.ayer || 0)}`} accent={up ? "teal" : "rust"} danger={!up && Math.abs(pct) > 20} />
            <KpiCard label="Ticket promedio" value={formatMoneyShort(v.ticket_promedio || 0)} meta="Hoy" accent="steel" />
            <KpiCard label="Pedidos hoy" value={String(v.num_pedidos || 0)} meta={v.fecha || ""} accent="khaki" />
          </div>

          <Card>
            <CardContent className="p-5 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold uppercase tracking-wider text-graphite">Ventas últimos 12 días</h3>
                <span className="text-xs text-graphite">Total: <span className="font-semibold text-ink">{formatMoneyShort(serie.reduce((a, b) => a + b, 0))}</span></span>
              </div>
              <div className="h-20"><Sparkline data={serie} height={60} /></div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <h3 className="text-sm font-bold uppercase tracking-wider text-graphite mb-3">Top productos (últimos 30 días)</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-border text-xs uppercase tracking-wider text-graphite">
                    <tr>
                      <th className="text-left py-2 font-medium">#</th>
                      <th className="text-left py-2 font-medium">Producto</th>
                      <th className="text-left py-2 font-medium">SKU</th>
                      <th className="text-right py-2 font-medium">Unidades</th>
                      <th className="text-right py-2 font-medium">Revenue</th>
                      <th className="text-right py-2 font-medium">% total</th>
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
            </CardContent>
          </Card>
        </TabsContent>

        {/* ─── TAB COMPARATIVAS ─── */}
        <TabsContent value="comp" className="space-y-4">
          {comp.isLoading || !comp.data ? (
            <Card><CardContent className="p-8 text-center text-sm text-graphite">Cargando comparativas…</CardContent></Card>
          ) : (
            <>
              {[
                { titulo: "Semana actual vs semana pasada", c: comp.data.semana, sub: "Acumulado de lunes a hoy" },
                { titulo: "Mes a la fecha vs mes anterior", c: comp.data.mes, sub: "Hasta el mismo día del mes anterior" },
                { titulo: "Este mes vs mismo mes año pasado (YoY)", c: comp.data.yoy, sub: "Crecimiento interanual" },
              ].map(({ titulo, c, sub }) => (
                <Card key={titulo}>
                  <CardContent className="p-5">
                    <div className="flex items-center justify-between mb-3">
                      <div>
                        <h3 className="text-sm font-bold uppercase tracking-wider text-graphite">{titulo}</h3>
                        <p className="text-xs text-graphite/70 mt-0.5">{sub}</p>
                      </div>
                      <DeltaBadge pct={c.pct} up={c.up} />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="border-r border-border pr-4">
                        <p className="text-[0.65rem] uppercase tracking-wider text-graphite mb-1">Actual</p>
                        <p className="text-2xl font-bold text-ink tabular-nums">{formatMoneyShort(c.actual.total)}</p>
                        <p className="text-xs text-graphite">{c.actual.num_pedidos} pedidos</p>
                      </div>
                      <div>
                        <p className="text-[0.65rem] uppercase tracking-wider text-graphite mb-1">Anterior</p>
                        <p className="text-2xl font-bold text-graphite tabular-nums">{formatMoneyShort(c.anterior.total)}</p>
                        <p className="text-xs text-graphite">{c.anterior.num_pedidos} pedidos</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </>
          )}
        </TabsContent>

        {/* ─── TAB POR PERÍODO ─── */}
        <TabsContent value="periodo" className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-graphite uppercase tracking-wider">Período:</span>
            {(["7d", "30d", "90d", "ytd"] as Periodo[]).map((p) => (
              <button
                key={p}
                onClick={() => setPeriodo(p)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold uppercase tracking-wider transition-colors ${
                  periodo === p ? "bg-navy text-white" : "bg-concrete text-graphite hover:bg-concrete/70"
                }`}
              >
                {p === "ytd" ? "YTD" : p}
              </button>
            ))}
          </div>

          {ventasP.isLoading || !ventasP.data ? (
            <Card><CardContent className="p-8 text-center text-sm text-graphite">Cargando…</CardContent></Card>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                <KpiCard label="Revenue total" value={formatMoneyShort(ventasP.data.resumen.total)} meta={`${ventasP.data.desde} → ${ventasP.data.hasta}`} accent="navy" />
                <KpiCard label="Pedidos" value={String(ventasP.data.resumen.num_pedidos)} meta="En el período" accent="steel" />
                <KpiCard label="Ticket promedio" value={formatMoneyShort(ventasP.data.resumen.ticket_promedio)} meta="Por pedido" accent="khaki" />
              </div>

              <Card>
                <CardContent className="p-5 space-y-3">
                  <h3 className="text-sm font-bold uppercase tracking-wider text-graphite">Serie diaria</h3>
                  <div className="h-20">
                    <Sparkline data={ventasP.data.serie.map((s) => s.total)} height={60} />
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>

        {/* ─── TAB CLIENTES ─── */}
        <TabsContent value="clientes" className="space-y-4">
          {cli.isLoading || !cli.data ? (
            <Card><CardContent className="p-8 text-center text-sm text-graphite">Cargando análisis de clientes…</CardContent></Card>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <KpiCard label="Clientes únicos" value={String(cli.data.total_clientes_unicos)} meta={`Últimos ${90} días`} accent="navy" />
                <KpiCard label="LTV promedio" value={formatMoneyShort(cli.data.ltv_promedio)} meta="Revenue / cliente" accent="steel" />
                <KpiCard label="% Recurrentes" value={`${cli.data.pct_recurrentes.toFixed(1)}%`} meta={`Nuevos: ${cli.data.pct_nuevos.toFixed(1)}%`} accent="teal" />
                <KpiCard label="Recompra 60d" value={`${cli.data.tasa_recompra_60d.toFixed(1)}%`} meta="Volvieron a comprar" accent="khaki" />
              </div>

              <Card>
                <CardContent className="p-5">
                  <h3 className="text-sm font-bold uppercase tracking-wider text-graphite mb-3">Top 10 clientes por revenue</h3>
                  {cli.data.top_clientes.length === 0 ? (
                    <p className="text-sm text-graphite text-center py-6">Sin datos.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="border-b border-border text-xs uppercase tracking-wider text-graphite">
                          <tr>
                            <th className="text-left py-2 font-medium">#</th>
                            <th className="text-left py-2 font-medium">Cliente</th>
                            <th className="text-left py-2 font-medium">Email</th>
                            <th className="text-right py-2 font-medium">Pedidos</th>
                            <th className="text-right py-2 font-medium">Revenue</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {cli.data.top_clientes.map((c, i) => (
                            <tr key={`${c.email}-${i}`} className="hover:bg-concrete/30">
                              <td className="py-2.5 text-graphite tabular-nums">{i + 1}</td>
                              <td className="py-2.5 text-ink font-medium">{c.nombre || "—"}</td>
                              <td className="py-2.5 text-graphite text-xs">{c.email || "—"}</td>
                              <td className="py-2.5 text-right text-ink tabular-nums">{c.ordenes}</td>
                              <td className="py-2.5 text-right text-ink font-semibold tabular-nums">{formatMoneyShort(c.revenue)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>

      </Tabs>

      <p className="text-[0.65rem] text-graphite/70 mt-2">
        Próximamente v3: canal de venta (D2C / B2B / POS) · códigos de descuento · cohorts de retención.
      </p>
    </PageShell>
  );
}
