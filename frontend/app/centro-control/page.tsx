"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard, KpiStrip } from "@/components/kpi-card";
import { LoadingState, ErrorState } from "@/components/page-shell";
import { BotonWhatsApp } from "@/components/boton-whatsapp";
import { formatMoney, formatMoneyShort, fmtDateTime, hoyBogota } from "@/lib/utils";
import {
  ArrowRight, Loader2, TrendingUp, AlertTriangle, CheckCircle,
  Phone, Truck, MapPin, DollarSign, Activity, History, ShieldAlert,
  ShoppingBag, Package, MessageSquare, RotateCcw, CreditCard,
} from "lucide-react";

interface QuickAction {
  label: string;
  count: number;
  valor: number;
  href: string;
  severity: "info" | "warning" | "danger" | "success";
}

interface AlertaProduccion {
  tipo: string;
  severidad: string; // alta | media | baja
  fuente: string;    // inventario | ruta | costeo
  mensaje: string;
}

interface AlertasProduccion {
  alertas: AlertaProduccion[];
  total: number;
  altas: number;
  generado_at: string;
}

interface PedidoUrgente {
  orden_tienda: string;
  orden_melonn: string;
  cliente: string;
  ciudad: string;
  zona: string;
  nivel: string;
  dias: number;
  sla: number;
  valor_cod: number;
  sub_estado: string;
  transportadora: string;
}

interface ZonaStat {
  zona: string;
  total: number;
  en_riesgo: number;
  pct_riesgo: number;
  valor_total: number;
}

interface CarrierStat {
  transportadora: string;
  total: number;
  novedades: number;
  pct_novedades: number;
}

interface ActividadHoy {
  pedidos_creados_hoy: number;
  entregados_hoy: number;
  acciones_hoy: number;
  autorizados_hoy: number;
}

interface AccionReciente {
  orden: string;
  tipo: string;
  descripcion: string;
  autor: string;
  creada_en: string;
}

interface Finanzas {
  cod_total: number;
  cod_pendientes: number;
  cod_transito: number;
  cod_novedades: number;
  cod_entregados: number;
  cod_por_liquidar: number;
  n_por_liquidar: number;
  n_con_diferencia: number;
}

interface Overview {
  fetched_at: string;
  fuente: string;
  n_total: number;
  n_critico: number;
  n_riesgo: number;
  n_normal: number;
  n_pend: number;
  n_transito: number;
  n_novedades: number;
  n_entregados: number;
  val_cod: number;
  val_cod_riesgo: number;
  quick_actions: QuickAction[];
  urgentes: PedidoUrgente[];
  por_zona: ZonaStat[];
  por_carrier: CarrierStat[];
  actividad_hoy: ActividadHoy;
  acciones_recientes: AccionReciente[];
  finanzas: Finanzas;
}

// === Tipos de los endpoints adicionales ===========================
interface ComercialOverview {
  ventas_hoy: { total?: number; num_pedidos?: number; ticket_promedio?: number };
  delta: { ayer?: number; pct?: number; up?: boolean };
  serie_12d: number[];
  top_productos: Array<{ sku?: string; nombre?: string; revenue?: number; unidades?: number }>;
}

interface ComercialComp {
  semana: { actual: { total: number; num_pedidos: number }; pct: number; up: boolean };
  mes:    { actual: { total: number; num_pedidos: number }; pct: number; up: boolean };
}

interface InventarioResumen {
  activos: number;
  total_skus: number;
  total_unidades: number;
  sin_stock: number;
  stock_bajo: number;
}

interface RevenueStats {
  ok: boolean;
  advisors?: number;
  leads?: number;
  conversations?: number;
  messages?: number;
  pending_audits?: number;
}

interface MpResumen {
  total: number;
  valor_neto_total: number;
  comision_total: number;
}

// === Página =======================================================
export default function CentroControlPage() {
  const { user } = useAuth();

  // Query principal: overview de operaciones (la que ya existía)
  const opsQ = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: () => api.get<Overview>("/api/dashboard/overview"),
  });

  // Queries paralelas — cada sección carga independiente.
  // Si falla una, las demás siguen renderizando.
  const comercialQ = useQuery({
    queryKey: ["dashboard", "comercial-overview"],
    queryFn: () => api.get<ComercialOverview>("/api/comercial/overview"),
    staleTime: 5 * 60_000,
    retry: 1,
  });
  const comercialCompQ = useQuery({
    queryKey: ["dashboard", "comercial-comp"],
    queryFn: () => api.get<ComercialComp>("/api/comercial/comparativas"),
    staleTime: 10 * 60_000,
    retry: 1,
  });
  const inventarioQ = useQuery({
    queryKey: ["dashboard", "inventario-resumen"],
    queryFn: () => api.get<InventarioResumen>("/api/inventario/resumen"),
    staleTime: 30 * 60_000,
    retry: 1,
  });
  const revenueQ = useQuery({
    queryKey: ["dashboard", "revenue-stats"],
    queryFn: () => api.get<RevenueStats>("/api/revenue/stats"),
    staleTime: 2 * 60_000,
    retry: 1,
  });
  const alertasProdQ = useQuery({
    queryKey: ["dashboard", "alertas-produccion"],
    queryFn: () => api.get<AlertasProduccion>("/api/produccion/alertas"),
    staleTime: 5 * 60_000,
    retry: 1,
  });
  const mpQ = useQuery({
    queryKey: ["dashboard", "mp-30d"],
    queryFn: () => {
      const desde = new Date();
      desde.setDate(desde.getDate() - 30);
      return api.get<MpResumen>(`/api/finanzas/mercadopago?desde=${desde.toISOString().slice(0, 10)}`);
    },
    staleTime: 15 * 60_000,
    retry: 1,
  });

  if (opsQ.isLoading) return <LoadingState label="Cargando Centro de Control…" />;
  if (opsQ.error || !opsQ.data) return <ErrorState error={opsQ.error} onRetry={() => opsQ.refetch()} />;

  const data = opsQ.data;
  const totalCod = data.n_pend + data.n_transito + data.n_novedades + data.n_entregados;

  return (
    <div className="space-y-7">
      {/* Hero */}
      <div className="flex items-end justify-between border-b border-border pb-5">
        <div>
          <h1 className="font-display text-[1.85rem] font-medium tracking-tight text-ink-900">
            Hola, {user?.nombre?.split(" ")[0] || "Sebastián"}
          </h1>
          <p className="mt-1 text-sm text-graphite">
            Centro de Control · {hoyBogota()}
          </p>
        </div>
        <div className="text-right">
          <p className="section-label">Última sincronización</p>
          <p className="mt-1 text-sm font-medium text-ink-900 tabular-nums">
            {fmtDateTime(data.fetched_at)}
            {opsQ.isFetching && <Loader2 className="inline ml-2 h-3 w-3 animate-spin text-steel-500" />}
          </p>
        </div>
      </div>

      {/* Quick actions */}
      {data.quick_actions.length > 0 && (
        <section>
          <p className="section-label mb-3 flex items-center gap-2">
            <AlertTriangle className="h-3 w-3" /> Atención inmediata
          </p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
            {data.quick_actions.map((q) => (
              <QuickActionCard key={q.label} q={q} />
            ))}
          </div>
        </section>
      )}

      {/* ────────── ALERTAS DE PRODUCCIÓN ─────────── */}
      {(alertasProdQ.data?.total ?? 0) > 0 && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <p className="section-label flex items-center gap-2">
              <ShieldAlert className="h-3 w-3 text-terracotta" />
              Alertas de producción ({alertasProdQ.data!.total})
            </p>
            <div className="flex items-center gap-3">
              <BotonWhatsApp
                mensaje={`⚠️ Producción MALE'DENIM · ${alertasProdQ.data!.total} alerta(s):\n\n${alertasProdQ.data!.alertas.map((a) => `${a.severidad === "alta" ? "🔴" : "🟡"} ${a.mensaje}`).join("\n")}\n\nDetalle: https://app.maledenim.com/produccion/costeo`}
                label="Compartir" />
              <Link href="/produccion/costeo" className="text-[0.65rem] text-navy-600 hover:underline">
                Ver costeo real →
              </Link>
            </div>
          </div>
          <Card>
            <CardContent className="p-4 space-y-2">
              {alertasProdQ.data!.alertas.slice(0, 8).map((a, i) => (
                <div key={i}
                  className={`rounded-sm border px-3 py-2 text-xs ${a.severidad === "alta" ? "border-terracotta/40 bg-terracotta/[0.05] text-terracotta" : "border-ochre/40 bg-ochre/[0.05] text-ink-900"}`}>
                  <span className="mr-2 rounded-sm bg-white/60 px-1.5 py-0.5 text-[0.68rem] font-bold uppercase tracking-widest text-graphite">
                    {a.fuente}
                  </span>
                  {a.mensaje}
                </div>
              ))}
              {alertasProdQ.data!.total > 8 && (
                <p className="text-[0.65rem] text-graphite">
                  … y {alertasProdQ.data!.total - 8} más en{" "}
                  <Link href="/produccion/costeo" className="text-navy-600 hover:underline">Costeo real</Link>.
                </p>
              )}
            </CardContent>
          </Card>
        </section>
      )}

      {/* ────────── BLOQUE 1: OPERACIONES (existente) ─────────── */}
      <section>
        <SectionHeading icon={Activity} title="Operación logística" />
        <KpiStrip
          items={[
            { label: "Pedidos activos", value: data.n_total },
            { label: "Críticos",        value: data.n_critico, tone: data.n_critico > 0 ? "danger" : "default" },
            { label: "En riesgo",       value: data.n_riesgo },
            { label: "Portafolio COD",  value: formatMoneyShort(data.val_cod) },
            { label: "COD en riesgo",   value: formatMoneyShort(data.val_cod_riesgo), tone: data.val_cod_riesgo > 0 ? "danger" : "default" },
          ]}
        />
      </section>

      {/* ────────── BLOQUE 2: COMERCIAL (Shopify) — nuevo ─────────── */}
      <section>
        <SectionHeading icon={ShoppingBag} title="Comercial — Shopify" href="/comercial" />
        {comercialQ.isLoading || !comercialQ.data ? (
          <SkeletonStrip />
        ) : (
          <ComercialBlock
            overview={comercialQ.data}
            comp={comercialCompQ.data}
          />
        )}
      </section>

      {/* ────────── BLOQUE 3: REVENUE IA + INVENTARIO ─────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section>
          <SectionHeading icon={MessageSquare} title="Revenue IA" href="/revenue" />
          {revenueQ.isLoading || !revenueQ.data ? (
            <SkeletonStrip cols={4} />
          ) : (
            <KpiStrip
              items={[
                { label: "Asesoras en línea", value: revenueQ.data.advisors ?? 0 },
                { label: "Conversaciones",    value: (revenueQ.data.conversations ?? 0).toLocaleString("es-CO") },
                { label: "Mensajes (total)",  value: (revenueQ.data.messages ?? 0).toLocaleString("es-CO") },
                { label: "Por auditar",       value: revenueQ.data.pending_audits ?? 0, tone: (revenueQ.data.pending_audits ?? 0) > 10 ? "danger" : "default" },
              ]}
            />
          )}
        </section>

        <section>
          <SectionHeading icon={Package} title="Inventario" href="/inventario" />
          {inventarioQ.isLoading || !inventarioQ.data ? (
            <SkeletonStrip cols={4} />
          ) : (
            <KpiStrip
              items={[
                { label: "Productos activos", value: inventarioQ.data.activos },
                { label: "SKUs",              value: inventarioQ.data.total_skus.toLocaleString("es-CO") },
                { label: "Sin stock",         value: inventarioQ.data.sin_stock, tone: inventarioQ.data.sin_stock > 10 ? "danger" : "default" },
                { label: "Stock bajo",        value: inventarioQ.data.stock_bajo, tone: inventarioQ.data.stock_bajo > 0 ? "danger" : "default" },
              ]}
            />
          )}
        </section>
      </div>

      {/* ────────── BLOQUE 4: DEVOLUCIONES / INCIDENCIAS ─────────── */}
      <section>
        <SectionHeading icon={RotateCcw} title="Devoluciones e incidencias" href="/incidencias" />
        <KpiStrip
          items={[
            { label: "Novedades activas",    value: data.n_novedades,                           tone: data.n_novedades > 0 ? "danger" : "default" },
            { label: "Despacho urgente",     value: data.urgentes.length,                       tone: data.urgentes.length > 0 ? "danger" : "default" },
            { label: "Acciones hoy",         value: data.actividad_hoy.acciones_hoy },
            { label: "Despachos autorizados", value: data.actividad_hoy.autorizados_hoy,        tone: "success" },
          ]}
        />
      </section>

      {/* ────────── BLOQUE 5: Actividad de hoy + Distribución (existente) ─────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="lg:col-span-1">
          <SectionHeading icon={TrendingUp} title="Actividad de hoy" />
          <Card>
            <CardContent className="space-y-3 p-5">
              <StatRow icon={Truck}        label="Pedidos nuevos"        value={data.actividad_hoy.pedidos_creados_hoy} />
              <StatRow icon={CheckCircle}  label="Entregados"            value={data.actividad_hoy.entregados_hoy} accent="sage" />
              <StatRow icon={Phone}        label="Acciones registradas"  value={data.actividad_hoy.acciones_hoy} />
              <StatRow icon={ShieldAlert}  label="Despachos autorizados" value={data.actividad_hoy.autorizados_hoy} accent="navy" />
            </CardContent>
          </Card>
        </section>

        <section className="lg:col-span-2">
          <SectionHeading icon={DollarSign} title="Distribución COD por estado" />
          <Card>
            <CardContent className="space-y-3 p-5">
              <DistRow label="Pendientes despacho" value={data.n_pend}       color="bg-ochre"      total={totalCod} />
              <DistRow label="En tránsito"         value={data.n_transito}   color="bg-navy-600"   total={totalCod} />
              <DistRow label="Novedades"           value={data.n_novedades}  color="bg-terracotta" total={totalCod} />
              <DistRow label="Entregados"          value={data.n_entregados} color="bg-sage"       total={totalCod} />
            </CardContent>
          </Card>
        </section>
      </div>

      {/* ────────── BLOQUE 6: Urgentes + Acciones recientes ─────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section>
          <SectionHeading icon={AlertTriangle} title={`Pedidos urgentes (${data.urgentes.length})`} />
          <Card>
            <CardContent className="p-0">
              {data.urgentes.length === 0 ? (
                <p className="p-8 text-center text-sm text-graphite">Sin urgencias. El equipo va al día.</p>
              ) : (
                <div className="divide-y divide-border">
                  {data.urgentes.map((u) => (
                    <UrgenteRow key={u.orden_tienda || u.orden_melonn} u={u} />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        <section>
          <SectionHeading icon={History} title="Acciones recientes del equipo" />
          <Card>
            <CardContent className="p-0">
              {data.acciones_recientes.length === 0 ? (
                <p className="p-8 text-center text-sm text-graphite">Sin acciones registradas todavía.</p>
              ) : (
                <div className="divide-y divide-border">
                  {data.acciones_recientes.map((a, i) => (
                    <div key={i} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium text-ink-900">{a.descripcion || a.tipo}</p>
                        <p className="text-[0.7rem] text-graphite">
                          {a.orden} · <span className="font-medium text-ink-900">{a.autor}</span> · {fmtDateTime(a.creada_en)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      </div>

      {/* ────────── BLOQUE 7: Performance por zona + carrier ─────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section>
          <SectionHeading icon={MapPin} title="Performance por zona" />
          <Card>
            <CardContent className="space-y-2 p-5">
              {data.por_zona.slice(0, 6).map((z) => (
                <ZonaBar key={z.zona} z={z} />
              ))}
            </CardContent>
          </Card>
        </section>

        <section>
          <SectionHeading icon={Truck} title="Performance por transportadora" />
          <Card>
            <CardContent className="space-y-2 p-5">
              {data.por_carrier.length === 0 ? (
                <p className="py-4 text-center text-sm text-graphite">Sin datos suficientes todavía.</p>
              ) : (
                data.por_carrier.slice(0, 6).map((c) => (
                  <CarrierRow key={c.transportadora} c={c} />
                ))
              )}
            </CardContent>
          </Card>
        </section>
      </div>

      {/* ────────── BLOQUE 8: FINANZAS COD + Pagos online ─────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section>
          <SectionHeading icon={DollarSign} title="Finanzas — COD" href="/finanzas" />
          <div className="grid grid-cols-2 gap-4">
            <KpiCard
              label="COD entregado total"
              value={formatMoneyShort(data.finanzas.cod_entregados)}
              meta={`${data.n_entregados} cobrados`}
              variant="success"
            />
            <KpiCard
              label="Por liquidar Melonn"
              value={formatMoneyShort(data.finanzas.cod_por_liquidar)}
              meta={`${data.finanzas.n_por_liquidar} pedidos`}
              variant={data.finanzas.cod_por_liquidar > 0 ? "danger" : "default"}
            />
            <KpiCard
              label="COD en novedades"
              value={formatMoneyShort(data.finanzas.cod_novedades)}
              meta="Recaudo comprometido"
              variant={data.finanzas.cod_novedades > 0 ? "danger" : "default"}
            />
            <KpiCard
              label="Diferencias detectadas"
              value={data.finanzas.n_con_diferencia}
              meta="Monto ≠ esperado"
              variant={data.finanzas.n_con_diferencia > 0 ? "danger" : "default"}
            />
          </div>
        </section>

        <section>
          <SectionHeading icon={CreditCard} title="Pagos online — MercadoPago" href="/mercadopago" />
          {mpQ.isLoading || !mpQ.data ? (
            <SkeletonStrip cols={2} />
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <KpiCard
                label="Transacciones 30d"
                value={mpQ.data.total}
                meta="Pagos aprobados"
              />
              <KpiCard
                label="Valor neto 30d"
                value={formatMoneyShort(mpQ.data.valor_neto_total)}
                meta="Después de comisión"
                variant="success"
              />
              <KpiCard
                label="Valor bruto 30d"
                value={formatMoneyShort(mpQ.data.valor_neto_total + mpQ.data.comision_total)}
                meta="Recaudo total"
              />
              <KpiCard
                label="Comisión MP"
                value={formatMoneyShort(mpQ.data.comision_total)}
                meta="Cobrado por MP"
              />
            </div>
          )}
        </section>
      </div>

      <p className="pt-2 text-center text-[0.65rem] text-graphite tabular-nums">
        {data.n_total} pedidos · fuente: {data.fuente}
      </p>
    </div>
  );
}

// ────────── Sub-componentes ──────────────────────────────────────────

function SectionHeading({
  icon: Icon, title, href,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  href?: string;
}) {
  const inner = (
    <p className="section-label mb-3 flex items-center gap-2">
      <Icon className="h-3 w-3" /> {title}
      {href && <span className="text-graphite/50">↗</span>}
    </p>
  );
  return href ? (
    <Link href={href} className="block hover:opacity-80 transition-opacity">{inner}</Link>
  ) : inner;
}

function SkeletonStrip({ cols = 5 }: { cols?: number }) {
  return (
    <div className={`grid divide-x divide-border rounded-md border border-border bg-card grid-cols-${cols}`}>
      {Array.from({ length: cols }).map((_, i) => (
        <div key={i} className="px-5 py-4">
          <div className="h-2 w-16 rounded-sm bg-cloud shimmer" />
          <div className="mt-3 h-5 w-12 rounded-sm bg-cloud shimmer" />
        </div>
      ))}
    </div>
  );
}

function ComercialBlock({
  overview, comp,
}: {
  overview: ComercialOverview;
  comp?: ComercialComp;
}) {
  const ventasHoy = overview.ventas_hoy?.total ?? 0;
  const numPedidosHoy = overview.ventas_hoy?.num_pedidos ?? 0;
  const pct = overview.delta?.pct ?? 0;
  const up = !!overview.delta?.up;

  return (
    <>
      <KpiStrip
        items={[
          { label: "Ventas hoy",     value: formatMoneyShort(ventasHoy) },
          { label: "Pedidos hoy",    value: numPedidosHoy },
          { label: "Vs ayer",        value: ventasHoy > 0 ? `${up ? "↑" : "↓"} ${Math.abs(pct).toFixed(1)}%` : "—",
            tone: ventasHoy > 0 ? (up ? "success" : "danger") : "default" },
          { label: "Semana actual",  value: comp ? formatMoneyShort(comp.semana.actual.total) : "…" },
          { label: "Mes a la fecha", value: comp ? formatMoneyShort(comp.mes.actual.total)    : "…" },
        ]}
      />

      {/* Spark 12 días + Top productos */}
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <Card>
          <CardContent className="p-4">
            <p className="section-label mb-2">Ventas últimos 12 días</p>
            <div className="h-16"><Sparkline data={overview.serie_12d || []} /></div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="section-label mb-2">Top productos (30 días)</p>
            {overview.top_productos && overview.top_productos.length > 0 ? (
              <ul className="space-y-1.5">
                {overview.top_productos.slice(0, 3).map((p, i) => (
                  <li key={`${p.sku}-${i}`} className="flex items-baseline justify-between text-xs">
                    <span className="text-graphite tabular-nums">{i + 1}.</span>
                    <span className="mx-2 flex-1 truncate text-ink-900">{p.nombre || p.sku || "—"}</span>
                    <span className="font-medium text-ink-900 tabular-nums">{formatMoney(p.revenue ?? 0)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-2 text-xs text-graphite">Sin ventas en el período.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function Sparkline({ data, height = 50 }: { data: number[]; height?: number }) {
  if (!data?.length) return <div className="text-xs text-graphite">Sin datos</div>;
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
    <svg viewBox={`0 0 ${w} ${height}`} className="h-full w-full" preserveAspectRatio="none">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-navy-600" />
      <circle cx={lastX} cy={lastY} r="2" className="fill-navy-600" />
    </svg>
  );
}

function QuickActionCard({ q }: { q: QuickAction }) {
  const colors: Record<string, string> = {
    info:    "border-l-navy-600   bg-navy-600/[0.04]",
    warning: "border-l-ochre       bg-ochre/[0.04]",
    danger:  "border-l-terracotta  bg-terracotta/[0.04]",
    success: "border-l-sage        bg-sage/[0.04]",
  };
  return (
    <Link
      href={q.href}
      className={`group block rounded-md border border-border border-l-4 ${colors[q.severity]} bg-card p-4 transition-colors hover:bg-cloud`}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">{q.label}</p>
          <p className="mt-0.5 font-display tabular-nums text-2xl font-medium text-ink-900">{q.count}</p>
          {q.valor > 0 && (
            <p className="mt-0.5 text-xs text-graphite tabular-nums">{formatMoney(q.valor)}</p>
          )}
        </div>
        <ArrowRight className="h-4 w-4 text-graphite transition-transform group-hover:translate-x-1" />
      </div>
    </Link>
  );
}

function StatRow({
  icon: Icon, label, value, accent,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
  accent?: "sage" | "navy" | "terracotta";
}) {
  const colorMap = { sage: "text-sage", navy: "text-navy-600", terracotta: "text-terracotta" };
  const valueColor = accent ? colorMap[accent] : "text-ink-900";
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 text-graphite" />
        <span className="text-sm text-ink-900">{label}</span>
      </div>
      <span className={`font-display tabular-nums text-lg font-medium ${valueColor}`}>{value}</span>
    </div>
  );
}

function DistRow({ label, value, color, total }: { label: string; value: number; color: string; total: number }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div>
      <div className="mb-1.5 flex justify-between text-sm">
        <span className="font-medium text-ink-900">{label}</span>
        <span className="text-graphite tabular-nums">{value} · {pct}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-cloud">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
    </div>
  );
}

function UrgenteRow({ u }: { u: PedidoUrgente }) {
  const overSla = u.sla > 0 && u.dias > u.sla;
  const nivelLabel: Record<string, string> = {
    CRITICO: "Crítico",
    VENCIDO: "Vencido",
    RIESGO:  "Riesgo",
    NORMAL:  "Normal",
  };
  return (
    <div className="flex items-center gap-3 px-4 py-2.5">
      <Badge tone={u.nivel === "CRITICO" || u.nivel === "VENCIDO" ? "critico" : "riesgo"}>
        {nivelLabel[u.nivel] || u.nivel}
      </Badge>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-medium text-ink-900 tabular-nums">{u.orden_tienda || u.orden_melonn}</span>
          <span className="truncate text-xs text-graphite">{u.cliente}</span>
        </div>
        <p className="text-[0.7rem] text-graphite">
          {u.ciudad} · {u.transportadora} · {u.sub_estado.replace("_", " ")}
        </p>
      </div>
      <div className="text-right">
        <p className={`text-xs font-medium tabular-nums ${overSla ? "text-terracotta" : "text-ink-900"}`}>
          {u.dias}d{u.sla > 0 && ` / ${u.sla}`}
        </p>
        {u.valor_cod > 0 && (
          <p className="text-[0.65rem] text-graphite tabular-nums">{formatMoneyShort(u.valor_cod)}</p>
        )}
      </div>
    </div>
  );
}

function ZonaBar({ z }: { z: ZonaStat }) {
  const color = z.pct_riesgo > 25 ? "bg-terracotta" : z.pct_riesgo > 10 ? "bg-ochre" : "bg-sage";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="font-medium text-ink-900">{z.zona}</span>
        <span className="text-graphite tabular-nums">
          {z.en_riesgo}/{z.total} · {z.pct_riesgo}%
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-cloud">
        <div className={`h-full ${color}`} style={{ width: `${Math.max(z.pct_riesgo, 2)}%` }} />
      </div>
    </div>
  );
}

function CarrierRow({ c }: { c: CarrierStat }) {
  const color = c.pct_novedades > 20 ? "bg-terracotta" : c.pct_novedades > 10 ? "bg-ochre" : "bg-sage";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="max-w-[200px] truncate font-medium text-ink-900">{c.transportadora}</span>
        <span className="text-graphite tabular-nums">
          {c.novedades}/{c.total} · {c.pct_novedades}%
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-cloud">
        <div className={`h-full ${color}`} style={{ width: `${Math.max(c.pct_novedades, 2)}%` }} />
      </div>
    </div>
  );
}
