"use client";

import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { DateRangePicker, type Periodo } from "@/components/date-range-picker";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiStrip } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { formatMoneyShort, formatMoney } from "@/lib/utils";

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

interface DesgloseResp {
  periodo: string;
  desde: string;
  hasta: string;
  bruto: number;
  neto: number;
  descuentos: number;
  num_pedidos: number;
  ticket_promedio: number;
  unidades?: number;
  upt?: number;
  por_canal:  Array<{ label: string;  ventas: number; num_pedidos: number; unidades: number; upt: number; pct: number }>;
  por_asesor: Array<{ nombre: string; ventas: number; num_pedidos: number; unidades: number; upt: number; pct: number }>;
}

interface FitTallaResp {
  neto: number;
  unidades: number;
  canales: string[];
  por_fit:   Array<{ fit: string;   ventas: number; unidades: number; num_pedidos: number; participacion: number; ticket_promedio: number }>;
  por_talla: Array<{ talla: string; ventas: number; unidades: number; num_pedidos: number; participacion: number; ticket_promedio: number }>;
}

type PeriodoDesglose = "hoy" | "ayer" | "7d" | "30d" | "mes" | "ytd" | "custom";

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
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-navy-600" />
      <circle cx={lastX} cy={lastY} r="2" className="fill-navy-600" />
    </svg>
  );
}

function DeltaBadge({ pct, up }: { pct: number; up: boolean }) {
  const tone = up ? "normal" : pct < -10 ? "critico" : "riesgo";
  return <Badge tone={tone}>{up ? "↑" : "↓"} {Math.abs(pct).toFixed(1)}%</Badge>;
}

function SectionHeading({ title, hint }: { title: string; hint?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h3 className="font-display text-base font-medium text-ink-900">{title}</h3>
      {hint && <span className="text-[0.7rem] text-graphite">{hint}</span>}
    </div>
  );
}

export default function ComercialPage() {
  const [periodoDesglose, setPeriodoDesglose] = useState<PeriodoDesglose>("hoy");
  const hoyISO = new Date().toISOString().slice(0, 10);
  const hace30 = new Date(Date.now() - 29 * 86400_000).toISOString().slice(0, 10);
  const [rangoDesde, setRangoDesde] = useState<string>(hace30);
  const [rangoHasta, setRangoHasta] = useState<string>(hoyISO);
  const [tabActivo, setTabActivo] = useState<"ventas" | "comp" | "clientes" | "fittalla">("ventas");
  const [periodoFT, setPeriodoFT] = useState<PeriodoDesglose>("hoy");
  const [rangoDesdeFT, setRangoDesdeFT] = useState<string>(hace30);
  const [rangoHastaFT, setRangoHastaFT] = useState<string>(hoyISO);
  const [canalFT, setCanalFT] = useState<string>("");

  // ── Filtros persistentes en la URL (?tab=&p=&d=&h=&fp=&fd=&fh=&canal=) ──
  // Se leen al montar y se escriben con replaceState: la vista es compartible
  // y al volver al módulo no se pierde lo que estabas mirando.
  const urlInit = useRef(false);
  useEffect(() => {
    if (urlInit.current) return;
    urlInit.current = true;
    const q = new URLSearchParams(window.location.search);
    const tab = q.get("tab");
    if (tab && ["ventas", "comp", "clientes", "fittalla"].includes(tab)) setTabActivo(tab as typeof tabActivo);
    const per = q.get("p");
    if (per && ["hoy", "ayer", "7d", "30d", "mes", "ytd", "custom"].includes(per)) setPeriodoDesglose(per as PeriodoDesglose);
    if (q.get("d")) setRangoDesde(q.get("d")!);
    if (q.get("h")) setRangoHasta(q.get("h")!);
    const fper = q.get("fp");
    if (fper && ["hoy", "ayer", "7d", "30d", "mes", "ytd", "custom"].includes(fper)) setPeriodoFT(fper as PeriodoDesglose);
    if (q.get("fd")) setRangoDesdeFT(q.get("fd")!);
    if (q.get("fh")) setRangoHastaFT(q.get("fh")!);
    if (q.get("canal")) setCanalFT(q.get("canal")!);
  }, []);
  useEffect(() => {
    if (!urlInit.current) return;
    const q = new URLSearchParams(window.location.search);
    const setOrDel = (k: string, v: string, def: string) => (v && v !== def ? q.set(k, v) : q.delete(k));
    setOrDel("tab", tabActivo, "ventas");
    setOrDel("p", periodoDesglose, "hoy");
    setOrDel("d", periodoDesglose === "custom" ? rangoDesde : "", "");
    setOrDel("h", periodoDesglose === "custom" ? rangoHasta : "", "");
    setOrDel("fp", periodoFT, "hoy");
    setOrDel("fd", periodoFT === "custom" ? rangoDesdeFT : "", "");
    setOrDel("fh", periodoFT === "custom" ? rangoHastaFT : "", "");
    setOrDel("canal", canalFT, "");
    const qs = q.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [tabActivo, periodoDesglose, rangoDesde, rangoHasta, periodoFT, rangoDesdeFT, rangoHastaFT, canalFT]);

  const overview = useQuery<OverviewResp>({
    queryKey: ["comercial-overview"],
    queryFn: () => api.get<OverviewResp>("/api/comercial/overview"),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    enabled: tabActivo === "ventas",
  });

  const comp = useQuery<CompResp>({
    queryKey: ["comercial-comp"],
    queryFn: () => api.get<CompResp>("/api/comercial/comparativas"),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    enabled: tabActivo === "comp",
  });

  const cli = useQuery<ClientesResp>({
    queryKey: ["comercial-clientes"],
    queryFn: () => api.get<ClientesResp>("/api/comercial/clientes?dias=90"),
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    enabled: tabActivo === "clientes",
  });

  const desg = useQuery<DesgloseResp>({
    queryKey: ["comercial-desglose", periodoDesglose, periodoDesglose === "custom" ? `${rangoDesde}_${rangoHasta}` : ""],
    queryFn: () => {
      const url =
        periodoDesglose === "custom"
          ? `/api/comercial/desglose?periodo=custom&desde=${rangoDesde}&hasta=${rangoHasta}`
          : `/api/comercial/desglose?periodo=${periodoDesglose}`;
      return api.get<DesgloseResp>(url);
    },
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    enabled: tabActivo === "ventas" && (periodoDesglose !== "custom" || !!(rangoDesde && rangoHasta)),
  });

  const ft = useQuery<FitTallaResp>({
    queryKey: ["comercial-fittalla", periodoFT, periodoFT === "custom" ? `${rangoDesdeFT}_${rangoHastaFT}` : "", canalFT],
    queryFn: () => api.get<FitTallaResp>(
      periodoFT === "custom"
        ? `/api/comercial/fit-talla?periodo=custom&desde=${rangoDesdeFT}&hasta=${rangoHastaFT}${canalFT ? `&canal=${encodeURIComponent(canalFT)}` : ""}`
        : `/api/comercial/fit-talla?periodo=${periodoFT}${canalFT ? `&canal=${encodeURIComponent(canalFT)}` : ""}`),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    enabled: tabActivo === "fittalla",
  });

  if (overview.isLoading) return <LoadingState label="Cargando métricas comerciales…" />;
  if (overview.error || !overview.data) return <ErrorState error={overview.error} onRetry={() => overview.refetch()} />;

  const data = overview.data;
  const d = data.delta || {};
  const up = !!d.up;
  const pct = d.pct || 0;
  const serie = data.serie_12d || [];

  return (
    <PageShell
      title="Comercial"
      subtitle="Ventas y clientes · Shopify"
      isFetching={overview.isFetching}
      dataUpdatedAt={Math.max(overview.dataUpdatedAt || 0, desg.dataUpdatedAt || 0)}
      onRefresh={() => { overview.refetch(); comp.refetch(); desg.refetch(); cli.refetch(); }}
    >
      {data.errores?.length > 0 && (
        <div className="rounded-md border border-terracotta/30 bg-terracotta/[0.04] px-3 py-2 text-xs text-terracotta">
          Algunos bloques no cargaron: {data.errores.join(" · ")}
        </div>
      )}

      <Tabs value={tabActivo} onValueChange={(v) => setTabActivo(v as typeof tabActivo)}>
        <TabsList>
          <TabsTrigger value="ventas">Ventas</TabsTrigger>
          <TabsTrigger value="comp">Comparativas</TabsTrigger>
          <TabsTrigger value="clientes">Clientes</TabsTrigger>
          <TabsTrigger value="fittalla">Fit y Talla</TabsTrigger>
        </TabsList>

        {/* ─── TAB VENTAS ─── */}
        <TabsContent value="ventas" className="space-y-4">
          {/* Selector de período (estilo Shopify) */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[0.7rem] uppercase tracking-[0.14em] text-graphite">Periodo</span>
            <DateRangePicker
              value={{ periodo: periodoDesglose as Periodo, desde: rangoDesde, hasta: rangoHasta }}
              onChange={(v) => {
                setPeriodoDesglose(v.periodo as PeriodoDesglose);
                if (v.desde) setRangoDesde(v.desde);
                if (v.hasta) setRangoHasta(v.hasta);
              }}
            />
          </div>

          {desg.isLoading || !desg.data ? (
            <Card><CardContent className="p-8 text-center text-sm text-graphite">Cargando ventas…</CardContent></Card>
          ) : (
            <>
              {/* KPIs principales (5) → KpiStrip */}
              <KpiStrip
                items={[
                  { label: "Ventas brutas",   value: formatMoney(desg.data.bruto) },
                  { label: "Descuentos",      value: formatMoney(desg.data.descuentos) },
                  { label: "Ventas netas",    value: formatMoney(desg.data.neto) },
                  { label: "Pedidos",         value: desg.data.num_pedidos },
                  { label: "Ticket promedio", value: formatMoney(desg.data.ticket_promedio) },
                ]}
              />

              <p className="text-[0.7rem] text-graphite">
                {desg.data.desde} → {desg.data.hasta} · Neto = Bruto − Descuentos · Sin IVA
              </p>

              {/* Delta vs ayer */}
              {periodoDesglose === "hoy" && overview.data?.delta && (
                <Card>
                  <CardContent className="flex items-center justify-between p-5">
                    <div>
                      <p className="section-label mb-1">Vs ayer</p>
                      <p className={`font-display text-xl font-medium ${up ? "text-sage" : "text-terracotta"}`}>
                        {up ? "↑" : "↓"} {Math.abs(pct).toFixed(1)}%
                      </p>
                    </div>
                    <p className="text-xs text-graphite">
                      Ayer <span className="font-medium text-ink-900 tabular-nums">{formatMoney(d.ayer || 0)}</span>
                    </p>
                  </CardContent>
                </Card>
              )}

              {/* Sparkline 12 días */}
              <Card>
                <CardContent className="space-y-3 p-5">
                  <SectionHeading
                    title="Ventas últimos 12 días"
                    hint={<>Total <span className="font-medium text-ink-900 tabular-nums">{formatMoney(serie.reduce((a, b) => a + b, 0))}</span></>}
                  />
                  <div className="h-20"><Sparkline data={serie} height={60} /></div>
                </CardContent>
              </Card>

              {/* Por canal */}
              <Card>
                <CardContent className="space-y-3 p-5">
                  <SectionHeading title="Ventas por canal" hint="% sobre neto" />
                  {desg.data.por_canal.length === 0 ? (
                    <p className="py-4 text-center text-sm text-graphite">Sin ventas en este período.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="border-b border-border">
                          <tr>
                            {["Canal", "Pedidos", "Unidades", "UPT", "Ventas", "%"].map((h, i) => (
                              <th key={h} className={`py-2 text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite ${i === 0 ? "text-left" : "text-right"}`}>
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {desg.data.por_canal.map((c) => (
                            <tr key={c.label} className="transition-colors hover:bg-cloud/50">
                              <td className="py-2.5 font-medium text-ink-900">{c.label}</td>
                              <td className="py-2.5 text-right text-ink-900 tabular-nums">{c.num_pedidos}</td>
                              <td className="py-2.5 text-right text-ink-900 tabular-nums">{(c.unidades ?? 0).toLocaleString("es-CO")}</td>
                              <td className="py-2.5 text-right text-graphite tabular-nums">{(c.upt ?? 0).toFixed(1)}</td>
                              <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{formatMoney(c.ventas)}</td>
                              <td className="py-2.5 text-right text-graphite tabular-nums">{c.pct.toFixed(1)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Por asesor */}
              <Card>
                <CardContent className="space-y-3 p-5">
                  <SectionHeading title="Ventas por asesor" hint="Solo órdenes creadas por staff" />
                  {desg.data.por_asesor.length === 0 ? (
                    <p className="py-4 text-center text-sm text-graphite">Sin ventas registradas por asesor en este período.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="border-b border-border">
                          <tr>
                            {["Asesor", "Pedidos", "Unidades", "UPT", "Ventas netas", "Ticket promedio", "% participación"].map((h, i) => (
                              <th key={h} className={`py-2 text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite ${i === 0 ? "text-left" : "text-right"}`}>
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {desg.data.por_asesor.map((a) => {
                            const ticket = a.num_pedidos > 0 ? a.ventas / a.num_pedidos : 0;
                            return (
                              <tr key={a.nombre} className="transition-colors hover:bg-cloud/50">
                                <td className="py-2.5 font-medium text-ink-900">{a.nombre}</td>
                                <td className="py-2.5 text-right text-ink-900 tabular-nums">{a.num_pedidos}</td>
                                <td className="py-2.5 text-right text-ink-900 tabular-nums">{(a.unidades ?? 0).toLocaleString("es-CO")}</td>
                                <td className="py-2.5 text-right text-graphite tabular-nums">{(a.upt ?? 0).toFixed(1)}</td>
                                <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{formatMoney(a.ventas)}</td>
                                <td className="py-2.5 text-right text-graphite tabular-nums">{formatMoney(ticket)}</td>
                                <td className="py-2.5 text-right text-graphite tabular-nums">{a.pct.toFixed(1)}%</td>
                              </tr>
                            );
                          })}
                        </tbody>
                        <tfoot className="border-t-2 border-ink-900/15 bg-cloud/60">
                          {(() => {
                            const totalPedidos = desg.data.por_asesor.reduce((s, a) => s + a.num_pedidos, 0);
                            const totalVentas  = desg.data.por_asesor.reduce((s, a) => s + a.ventas, 0);
                            const totalUnid    = desg.data.por_asesor.reduce((s, a) => s + (a.unidades ?? 0), 0);
                            const ticketProm   = totalPedidos > 0 ? totalVentas / totalPedidos : 0;
                            const uptTotal     = totalPedidos > 0 ? totalUnid / totalPedidos : 0;
                            const totalPct     = desg.data.por_asesor.reduce((s, a) => s + a.pct, 0);
                            return (
                              <tr>
                                <td className="py-2.5 font-medium text-ink-900">Total</td>
                                <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{totalPedidos}</td>
                                <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{totalUnid.toLocaleString("es-CO")}</td>
                                <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{uptTotal.toFixed(1)}</td>
                                <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{formatMoney(totalVentas)}</td>
                                <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{formatMoney(ticketProm)}</td>
                                <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{totalPct.toFixed(1)}%</td>
                              </tr>
                            );
                          })()}
                        </tfoot>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Top productos */}
              {overview.data?.top_productos && overview.data.top_productos.length > 0 && (
                <Card>
                  <CardContent className="p-5">
                    <SectionHeading title="Top productos (últimos 30 días)" />
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="border-b border-border">
                          <tr>
                            {["#", "Producto", "SKU", "Unidades", "Revenue", "% total"].map((h, i) => (
                              <th key={h} className={`py-2 text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite ${i <= 2 ? "text-left" : "text-right"}`}>
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {overview.data.top_productos.map((p, i) => (
                            <tr key={`${p.sku}-${i}`} className="transition-colors hover:bg-cloud/50">
                              <td className="py-2.5 text-graphite tabular-nums">{i + 1}</td>
                              <td className="py-2.5 font-medium text-ink-900">{p.nombre || "—"}</td>
                              <td className="py-2.5 text-xs text-graphite tabular-nums">{p.sku || "—"}</td>
                              <td className="py-2.5 text-right text-ink-900 tabular-nums">{p.unidades || 0}</td>
                              <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{formatMoney(p.revenue || 0)}</td>
                              <td className="py-2.5 text-right text-graphite tabular-nums">{(p.pct_del_total || 0).toFixed(1)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}
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
                    <div className="mb-3 flex items-center justify-between">
                      <div>
                        <h3 className="font-display text-base font-medium text-ink-900">{titulo}</h3>
                        <p className="mt-0.5 text-xs text-graphite/70">{sub}</p>
                      </div>
                      <DeltaBadge pct={c.pct} up={c.up} />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="border-r border-border pr-4">
                        <p className="section-label mb-1">Actual</p>
                        <p className="font-display tabular-nums text-2xl font-medium text-ink-900">{formatMoneyShort(c.actual.total)}</p>
                        <p className="text-xs text-graphite">{c.actual.num_pedidos} pedidos</p>
                      </div>
                      <div>
                        <p className="section-label mb-1">Anterior</p>
                        <p className="font-display tabular-nums text-2xl font-medium text-graphite">{formatMoneyShort(c.anterior.total)}</p>
                        <p className="text-xs text-graphite">{c.anterior.num_pedidos} pedidos</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </>
          )}
        </TabsContent>

        {/* ─── TAB CLIENTES ─── */}
        <TabsContent value="clientes" className="space-y-4">
          {cli.isLoading || !cli.data ? (
            <Card><CardContent className="p-8 text-center text-sm text-graphite">Cargando análisis de clientes…</CardContent></Card>
          ) : (
            <>
              <KpiStrip
                items={[
                  { label: "Clientes únicos", value: cli.data.total_clientes_unicos },
                  { label: "LTV promedio",    value: formatMoneyShort(cli.data.ltv_promedio) },
                  { label: "% Recurrentes",   value: `${cli.data.pct_recurrentes.toFixed(1)}%` },
                  { label: "Recompra 60d",    value: `${cli.data.tasa_recompra_60d.toFixed(1)}%` },
                ]}
              />

              <Card>
                <CardContent className="p-5">
                  <SectionHeading title="Top 10 clientes por revenue" />
                  {cli.data.top_clientes.length === 0 ? (
                    <p className="py-6 text-center text-sm text-graphite">Sin datos de clientes en este período.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="border-b border-border">
                          <tr>
                            {["#", "Cliente", "Email", "Pedidos", "Revenue"].map((h, i) => (
                              <th key={h} className={`py-2 text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite ${i <= 2 ? "text-left" : "text-right"}`}>
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {cli.data.top_clientes.map((c, i) => (
                            <tr key={`${c.email}-${i}`} className="transition-colors hover:bg-cloud/50">
                              <td className="py-2.5 text-graphite tabular-nums">{i + 1}</td>
                              <td className="py-2.5 font-medium text-ink-900">{c.nombre || "—"}</td>
                              <td className="py-2.5 text-xs text-graphite">{c.email || "—"}</td>
                              <td className="py-2.5 text-right text-ink-900 tabular-nums">{c.ordenes}</td>
                              <td className="py-2.5 text-right font-medium text-ink-900 tabular-nums">{formatMoneyShort(c.revenue)}</td>
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

        {/* ─── TAB FIT Y TALLA (RF-05) ─── */}
        <TabsContent value="fittalla" className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[0.7rem] uppercase tracking-[0.14em] text-graphite">Periodo</span>
            <DateRangePicker
              value={{ periodo: periodoFT as Periodo, desde: rangoDesdeFT, hasta: rangoHastaFT }}
              onChange={(v) => {
                setPeriodoFT(v.periodo as PeriodoDesglose);
                if (v.desde) setRangoDesdeFT(v.desde);
                if (v.hasta) setRangoHastaFT(v.hasta);
              }}
            />
            <select value={canalFT} onChange={(e) => setCanalFT(e.target.value)}
              className="rounded-sm border border-border bg-card px-3 py-1.5 text-xs">
              <option value="">Todos los canales</option>
              {(ft.data?.canales || []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          {ft.isLoading ? (
            <LoadingState label="Cargando ventas por fit y talla…" />
          ) : ft.error || !ft.data ? (
            <ErrorState error={ft.error} onRetry={() => ft.refetch()} />
          ) : (
            <div className="grid grid-cols-1 gap-4">
              <FitTallaTabla titulo="Ventas por Fit" col="Fit"
                filas={ft.data.por_fit.map((r) => ({ nombre: r.fit, ...r }))} />
              <FitTallaTabla titulo="Ventas por Talla" col="Talla"
                filas={ft.data.por_talla.map((r) => ({ nombre: r.talla, ...r }))} />
            </div>
          )}
        </TabsContent>
      </Tabs>

      <p className="mt-2 text-[0.65rem] text-graphite/70">
        Próximamente: códigos de descuento más usados · cohorts de retención.
      </p>
    </PageShell>
  );
}

function FitTallaTabla({ titulo, col, filas }: {
  titulo: string; col: string;
  filas: Array<{ nombre: string; ventas: number; unidades: number; num_pedidos: number; participacion: number; ticket_promedio: number }>;
}) {
  const totalUnd = filas.reduce((a, r) => a + r.unidades, 0);
  const totalVta = filas.reduce((a, r) => a + r.ventas, 0);
  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <SectionHeading title={titulo} hint="Ventas netas sin IVA · ordenado por venta" />
        {filas.length === 0 ? (
          <p className="py-4 text-center text-sm text-graphite">Sin ventas en este período.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-3 py-2 text-left text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">{col}</th>
                  <th className="whitespace-nowrap px-3 py-2 text-right text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">Und.</th>
                  <th className="whitespace-nowrap px-3 py-2 text-right text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">Ventas netas</th>
                  <th className="whitespace-nowrap px-3 py-2 text-right text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">Ticket prom.</th>
                  <th className="whitespace-nowrap px-3 py-2 text-right text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">% part.</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filas.map((r) => (
                  <tr key={r.nombre} className="transition-colors hover:bg-cloud/50">
                    <td className="max-w-[260px] truncate px-3 py-2.5 font-medium text-ink-900" title={r.nombre}>{r.nombre}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-ink-900">{r.unidades.toLocaleString("es-CO")}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right font-medium tabular-nums text-ink-900">{formatMoney(r.ventas)}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-graphite">{formatMoney(r.ticket_promedio)}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-graphite">
                      <span className="inline-flex min-w-[3rem] items-center justify-end gap-1.5">
                        <span className="hidden h-1.5 w-8 overflow-hidden rounded-full bg-cloud sm:inline-block">
                          <span className="block h-full rounded-full bg-ink-900/40" style={{ width: `${Math.min(100, r.participacion)}%` }} />
                        </span>
                        {r.participacion.toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border font-semibold text-ink-900">
                  <td className="px-3 py-2.5 text-left">Total</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{totalUnd.toLocaleString("es-CO")}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{formatMoney(totalVta)}</td>
                  <td className="px-3 py-2.5"></td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">100%</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}