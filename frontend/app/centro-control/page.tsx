"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { MetricasResponse } from "@/lib/types";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatMoneyShort } from "@/lib/utils";
import { Loader2 } from "lucide-react";

export default function CentroControlPage() {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["metricas"],
    queryFn: () => api.get<MetricasResponse>("/api/metricas"),
  });

  if (isLoading) {
    return (
      <div className="flex h-96 items-center justify-center text-graphite">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Cargando datos de operación...
      </div>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <CardContent className="p-10 text-center">
          <p className="text-crimson font-semibold mb-2">Error al cargar datos</p>
          <p className="text-sm text-graphite">{(error as Error)?.message ?? "Sin datos"}</p>
          <button
            onClick={() => refetch()}
            className="mt-4 rounded-md bg-ink px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black"
          >
            Reintentar
          </button>
        </CardContent>
      </Card>
    );
  }

  const m = data.metricas;
  const totalCod = m.n_pend + m.n_tran_cod + m.n_nov_cod + m.n_ent_cod;

  const alerts: Array<{ title: string; msg: string; tone: "critico" | "riesgo" | "pendiente" }> = [];
  if (m.n_critico > 0)  alerts.push({ title: `${m.n_critico} pedidos en estado crítico`, msg: "Requieren acción inmediata", tone: "critico" });
  if (m.n_riesgo > 0)   alerts.push({ title: `${m.n_riesgo} pedidos en riesgo`, msg: "Monitorear hoy",                tone: "riesgo" });
  if (m.n_pend > 0)     alerts.push({ title: `${m.n_pend} pendientes de despacho`, msg: "Esperan autorización",        tone: "pendiente" });
  if (m.n_nov_cod > 0)  alerts.push({ title: `${m.n_nov_cod} novedades COD`, msg: "Transportadora no pudo entregar",   tone: "riesgo" });

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div className="flex items-end justify-between border-b border-border pb-5">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink">Hola, Sebastián</h1>
          <p className="mt-1 text-sm text-graphite">
            Estado general de MALE'DENIM OS · {new Date().toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" })}
          </p>
        </div>
        <div className="text-right">
          <p className="section-label">Última sincronización</p>
          <p className="text-sm font-semibold text-ink mt-1">
            {data.fetched_at ? new Date(data.fetched_at).toLocaleString("es-CO", {
              hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit",
            }) : "—"}
            {isFetching && <Loader2 className="inline ml-2 h-3 w-3 animate-spin text-steel" />}
          </p>
          <div className="mt-1">
            <Badge tone={data.stale ? "riesgo" : "normal"}>
              {data.stale ? "Desactualizado" : "Sincronizado"}
            </Badge>
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
        <KpiCard label="Pedidos activos" value={m.n_total}                meta="Total en operación"   accent="steel" />
        <KpiCard label="Críticos"        value={m.n_critico}              meta="Acción inmediata"     accent={m.n_critico ? "crimson" : "steel"} danger={m.n_critico > 0} />
        <KpiCard label="En riesgo"       value={m.n_riesgo}               meta="Monitorear hoy"       accent={m.n_riesgo ? "rust" : "steel"} />
        <KpiCard label="Portafolio COD"  value={formatMoneyShort(m.val_cod)}    meta="Total contraentrega" accent="navy" />
        <KpiCard label="COD en riesgo"   value={formatMoneyShort(m.val_riesgo)} meta="Recaudo comprometido" accent={m.val_riesgo ? "rust" : "steel"} />
      </div>

      {/* 2 columnas: Alertas + Distribución */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section>
          <p className="section-label mb-3">Alertas prioritarias</p>
          <Card>
            <CardContent className="p-2">
              {alerts.length === 0 ? (
                <p className="text-center py-8 text-sm text-graphite">
                  ✓ Todo operando con normalidad
                </p>
              ) : (
                alerts.map((a, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-3 px-3 py-2.5 border-b border-border last:border-0"
                  >
                    <Badge tone={a.tone}>{a.tone}</Badge>
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-ink">{a.title}</p>
                      <p className="text-xs text-graphite">{a.msg}</p>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </section>

        <section>
          <p className="section-label mb-3">Distribución COD por estado</p>
          <Card>
            <CardContent className="space-y-3 p-5">
              <DistRow label="Pendientes despacho" value={m.n_pend}    color="bg-khaki" total={totalCod} />
              <DistRow label="En tránsito"         value={m.n_tran_cod} color="bg-navy"  total={totalCod} />
              <DistRow label="Novedades"           value={m.n_nov_cod}  color="bg-rust"  total={totalCod} />
              <DistRow label="Entregados"          value={m.n_ent_cod}  color="bg-teal"  total={totalCod} />
            </CardContent>
          </Card>
        </section>
      </div>

      {/* Footer */}
      <p className="text-[0.65rem] text-graphite text-center">
        {m.n_total} pedidos · fuente: {data.fuente} · backend FastAPI
      </p>
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
