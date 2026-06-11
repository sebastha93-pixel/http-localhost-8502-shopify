"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard } from "@/components/kpi-card";
import { LoadingState, ErrorState } from "@/components/page-shell";
import { formatMoney, formatMoneyShort, fmtDateTime, hoyBogota } from "@/lib/utils";
import {
  ArrowRight, Loader2, TrendingUp, AlertTriangle, CheckCircle,
  Phone, Truck, MapPin, DollarSign, Activity, History, ShieldAlert,
} from "lucide-react";

interface QuickAction {
  label: string;
  count: number;
  valor: number;
  href: string;
  severity: "info" | "warning" | "danger" | "success";
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

export default function CentroControlPage() {
  const { user } = useAuth();
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: () => api.get<Overview>("/api/dashboard/overview"),
  });

  if (isLoading) return <LoadingState label="Cargando Centro de Control..." />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  const totalCod = data.n_pend + data.n_transito + data.n_novedades + data.n_entregados;

  return (
    <div className="space-y-7">
      {/* Hero */}
      <div className="flex items-end justify-between border-b border-border pb-5">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink">
            Hola, {user?.nombre?.split(" ")[0] || "Sebastián"}
          </h1>
          <p className="mt-1 text-sm text-graphite">
            Centro de Control · {hoyBogota()}
          </p>
        </div>
        <div className="text-right">
          <p className="section-label">Última sincronización</p>
          <p className="text-sm font-semibold text-ink mt-1">
            {fmtDateTime(data.fetched_at)}
            {isFetching && <Loader2 className="inline ml-2 h-3 w-3 animate-spin text-steel" />}
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

      {/* KPIs operativos */}
      <section>
        <p className="section-label mb-3 flex items-center gap-2">
          <Activity className="h-3 w-3" /> Operación logística
        </p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
          <KpiCard label="Pedidos activos" value={data.n_total}          meta="Total en operación"     accent="steel" />
          <KpiCard label="Críticos"        value={data.n_critico}        meta="Acción inmediata"       accent={data.n_critico ? "crimson" : "steel"} danger={data.n_critico > 0} />
          <KpiCard label="En riesgo"       value={data.n_riesgo}         meta="Monitorear hoy"         accent={data.n_riesgo ? "rust" : "steel"} />
          <KpiCard label="Portafolio COD"  value={formatMoneyShort(data.val_cod)}      meta="Total contraentrega"    accent="navy" />
          <KpiCard label="COD en riesgo"   value={formatMoneyShort(data.val_cod_riesgo)} meta="Recaudo comprometido"  accent={data.val_cod_riesgo ? "rust" : "steel"} />
        </div>
      </section>

      {/* Actividad de hoy + Distribución */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Actividad hoy */}
        <section className="lg:col-span-1">
          <p className="section-label mb-3 flex items-center gap-2">
            <TrendingUp className="h-3 w-3" /> Actividad de hoy
          </p>
          <Card>
            <CardContent className="p-4 space-y-3">
              <StatRow icon={Truck}    label="Pedidos nuevos"      value={data.actividad_hoy.pedidos_creados_hoy} />
              <StatRow icon={CheckCircle} label="Entregados"       value={data.actividad_hoy.entregados_hoy} accent="teal" />
              <StatRow icon={Phone}    label="Acciones registradas" value={data.actividad_hoy.acciones_hoy} />
              <StatRow icon={ShieldAlert} label="Despachos autorizados" value={data.actividad_hoy.autorizados_hoy} accent="navy" />
            </CardContent>
          </Card>
        </section>

        {/* Distribución por estado COD */}
        <section className="lg:col-span-2">
          <p className="section-label mb-3">Distribución COD por estado</p>
          <Card>
            <CardContent className="space-y-3 p-5">
              <DistRow label="Pendientes despacho" value={data.n_pend}      color="bg-khaki" total={totalCod} />
              <DistRow label="En tránsito"         value={data.n_transito}  color="bg-navy"  total={totalCod} />
              <DistRow label="Novedades"           value={data.n_novedades} color="bg-rust"  total={totalCod} />
              <DistRow label="Entregados"          value={data.n_entregados} color="bg-teal" total={totalCod} />
            </CardContent>
          </Card>
        </section>
      </div>

      {/* Top urgentes + Acciones recientes */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section>
          <p className="section-label mb-3 flex items-center gap-2">
            <AlertTriangle className="h-3 w-3" /> Pedidos urgentes ({data.urgentes.length})
          </p>
          <Card>
            <CardContent className="p-0">
              {data.urgentes.length === 0 ? (
                <p className="p-8 text-center text-sm text-graphite">✓ Sin urgencias</p>
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
          <p className="section-label mb-3 flex items-center gap-2">
            <History className="h-3 w-3" /> Acciones recientes del equipo
          </p>
          <Card>
            <CardContent className="p-0">
              {data.acciones_recientes.length === 0 ? (
                <p className="p-8 text-center text-sm text-graphite">Sin acciones registradas</p>
              ) : (
                <div className="divide-y divide-border">
                  {data.acciones_recientes.map((a, i) => (
                    <div key={i} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-ink truncate">{a.descripcion || a.tipo}</p>
                        <p className="text-[0.7rem] text-graphite">
                          {a.orden} · <span className="font-semibold">{a.autor}</span> · {fmtDateTime(a.creada_en)}
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

      {/* Performance por zona + por carrier */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section>
          <p className="section-label mb-3 flex items-center gap-2">
            <MapPin className="h-3 w-3" /> Performance por zona
          </p>
          <Card>
            <CardContent className="space-y-2 p-4">
              {data.por_zona.slice(0, 6).map((z) => (
                <ZonaBar key={z.zona} z={z} />
              ))}
            </CardContent>
          </Card>
        </section>

        <section>
          <p className="section-label mb-3 flex items-center gap-2">
            <Truck className="h-3 w-3" /> Performance por transportadora
          </p>
          <Card>
            <CardContent className="space-y-2 p-4">
              {data.por_carrier.length === 0 ? (
                <p className="text-sm text-graphite py-4 text-center">Sin datos suficientes</p>
              ) : (
                data.por_carrier.slice(0, 6).map((c) => (
                  <CarrierRow key={c.transportadora} c={c} />
                ))
              )}
            </CardContent>
          </Card>
        </section>
      </div>

      {/* Finanzas */}
      <section>
        <p className="section-label mb-3 flex items-center gap-2">
          <DollarSign className="h-3 w-3" /> Finanzas
        </p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <KpiCard label="COD entregado total"  value={formatMoneyShort(data.finanzas.cod_entregados)}  meta={`${data.n_entregados} cobrados`}  accent="teal" />
          <KpiCard label="Por liquidar Melonn"   value={formatMoneyShort(data.finanzas.cod_por_liquidar)} meta={`${data.finanzas.n_por_liquidar} pedidos`} accent={data.finanzas.cod_por_liquidar ? "rust" : "steel"} danger={data.finanzas.n_por_liquidar > 0} />
          <KpiCard label="COD en novedades"     value={formatMoneyShort(data.finanzas.cod_novedades)}   meta="Recaudo comprometido"   accent={data.finanzas.cod_novedades ? "crimson" : "steel"} />
          <KpiCard label="Diferencias detectadas" value={data.finanzas.n_con_diferencia}                 meta="Monto ≠ esperado"       accent={data.finanzas.n_con_diferencia ? "crimson" : "steel"} danger={data.finanzas.n_con_diferencia > 0} />
        </div>
      </section>

      <p className="text-[0.65rem] text-graphite text-center pt-2">
        {data.n_total} pedidos · fuente: {data.fuente}
      </p>
    </div>
  );
}

// ── Sub-componentes ──────────────────────────────────────────────────

function QuickActionCard({ q }: { q: QuickAction }) {
  const colors: Record<string, string> = {
    info:    "bg-navy/10 border-navy/30 text-navy",
    warning: "bg-khaki/15 border-khaki/40 text-khaki",
    danger:  "bg-crimson/10 border-crimson/30 text-crimson",
    success: "bg-teal/10 border-teal/30 text-teal",
  };
  return (
    <Link
      href={q.href}
      className={`block rounded-md border-l-4 ${colors[q.severity]} bg-white p-4 hover:shadow-md transition-shadow group`}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">{q.label}</p>
          <p className="text-2xl font-bold text-ink mt-0.5 tabular-nums">{q.count}</p>
          {q.valor > 0 && (
            <p className="text-xs text-graphite mt-0.5">{formatMoney(q.valor)}</p>
          )}
        </div>
        <ArrowRight className="h-4 w-4 text-graphite group-hover:translate-x-1 transition-transform" />
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
  accent?: "teal" | "navy" | "rust";
}) {
  const colorMap = { teal: "text-teal", navy: "text-navy", rust: "text-rust" };
  const valueColor = accent ? colorMap[accent] : "text-ink";
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 text-graphite" />
        <span className="text-sm text-ink">{label}</span>
      </div>
      <span className={`text-lg font-bold tabular-nums ${valueColor}`}>{value}</span>
    </div>
  );
}

function DistRow({ label, value, color, total }: { label: string; value: number; color: string; total: number }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div>
      <div className="flex justify-between text-sm mb-1.5">
        <span className="font-medium text-ink">{label}</span>
        <span className="text-graphite tabular-nums">{value} · {pct}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-concrete overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
    </div>
  );
}

function UrgenteRow({ u }: { u: PedidoUrgente }) {
  const overSla = u.sla > 0 && u.dias > u.sla;
  return (
    <div className="flex items-center gap-3 px-4 py-2.5">
      <Badge tone={u.nivel === "CRITICO" || u.nivel === "VENCIDO" ? "critico" : "riesgo"}>
        {u.nivel}
      </Badge>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-ink truncate">{u.orden_tienda || u.orden_melonn}</span>
          <span className="text-xs text-graphite truncate">{u.cliente}</span>
        </div>
        <p className="text-[0.7rem] text-graphite">
          {u.ciudad} · {u.transportadora} · {u.sub_estado.replace("_", " ")}
        </p>
      </div>
      <div className="text-right">
        <p className={`text-xs tabular-nums font-semibold ${overSla ? "text-crimson" : "text-ink"}`}>
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
  const color = z.pct_riesgo > 25 ? "bg-crimson" : z.pct_riesgo > 10 ? "bg-rust" : "bg-teal";
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="font-semibold text-ink">{z.zona}</span>
        <span className="text-graphite tabular-nums">
          {z.en_riesgo}/{z.total} · {z.pct_riesgo}%
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-concrete overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${Math.max(z.pct_riesgo, 2)}%` }} />
      </div>
    </div>
  );
}

function CarrierRow({ c }: { c: CarrierStat }) {
  const color = c.pct_novedades > 20 ? "bg-crimson" : c.pct_novedades > 10 ? "bg-rust" : "bg-teal";
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="font-semibold text-ink truncate max-w-[200px]">{c.transportadora}</span>
        <span className="text-graphite tabular-nums">
          {c.novedades}/{c.total} · {c.pct_novedades}%
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-concrete overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${Math.max(c.pct_novedades, 2)}%` }} />
      </div>
    </div>
  );
}
