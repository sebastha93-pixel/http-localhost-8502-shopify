"use client";

/**
 * Compensaciones — tiempo por reponer.
 *
 * "Validar" confronta lo programado con lo que dicen las marcaciones reales.
 * Programar no compensa: si no marcó, no repuso.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard } from "@/components/kpi-card";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { Empleado, fechaCorta, hoyISO, minutosAHoras } from "@/lib/personal";

interface Plan {
  id: string;
  empleado_id: string;
  minutos_a_compensar: number;
  minutos_compensados: number;
  minutos_pendientes: number;
  fecha_limite: string;
  estado: string;
}

const TONO: Record<string, "normal" | "riesgo" | "critico" | "neutral" | "info"> = {
  activo: "riesgo", completado: "normal", vencido: "critico",
  cancelado: "neutral", convertido_a_nomina: "info",
};

const TABS = [
  { k: "activo", label: "Activos" },
  { k: "vencido", label: "Vencidos" },
  { k: "completado", label: "Completados" },
  { k: "", label: "Todos" },
];

export default function CompensacionesPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState("activo");
  const [err, setErr] = useState("");

  const q = useQuery<{ planes: Plan[] }>({
    queryKey: ["personal", "compensaciones", tab],
    queryFn: () => {
      const p = new URLSearchParams();
      if (tab) p.set("estado", tab);
      return api.get(`/api/personal/compensaciones?${p}`);
    },
  });

  const empQ = useQuery<{ empleados: Empleado[] }>({
    queryKey: ["personal", "empleados", "nombres"],
    queryFn: () => api.get("/api/personal/empleados?limit=500"),
    staleTime: 10 * 60_000,
  });
  const nombre = (id: string) =>
    empQ.data?.empleados.find((e) => e.id === id)?.nombre_completo ?? "—";

  const validar = useMutation({
    mutationFn: (planId: string) =>
      api.post(`/api/personal/compensaciones/${planId}/validar`, {}),
    onSuccess: () => {
      setErr("");
      qc.invalidateQueries({ queryKey: ["personal", "compensaciones"] });
      qc.invalidateQueries({ queryKey: ["personal", "dashboard"] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  if (q.isLoading) return <LoadingState label="Cargando compensaciones…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const planes = q.data?.planes ?? [];
  const pendiente = planes.reduce((s, p) => s + (p.minutos_pendientes || 0), 0);
  const vencidos = planes.filter((p) => p.estado === "vencido").length;

  return (
    <PageShell
      title="Compensaciones"
      subtitle={`${planes.length} plan${planes.length === 1 ? "" : "es"}`}
      isFetching={q.isFetching}
      onRefresh={() => q.refetch()}
    >
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <KpiCard label="Tiempo por reponer" value={minutosAHoras(pendiente)} accent="khaki" />
        <KpiCard label="Planes vencidos" value={vencidos}
                 variant={vencidos > 0 ? "danger" : "success"}
                 meta={vencidos > 0 ? "requieren decisión de TH" : undefined} />
        <KpiCard label="Planes activos" value={planes.filter((p) => p.estado === "activo").length} />
      </div>

      <div className="mt-4 flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button key={t.k} onClick={() => setTab(t.k)}
            className={`rounded-sm border px-3 py-1.5 text-xs font-medium transition-colors ${
              tab === t.k
                ? "border-navy-600 bg-navy-600 text-white"
                : "border-border bg-card text-graphite hover:bg-cloud"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {err && (
        <p role="alert" className="mt-3 rounded-sm border border-terracotta/25 bg-terracotta/10 px-3 py-2 text-sm text-terracotta">
          {err}
        </p>
      )}

      <Card className="mt-4">
        <CardContent className="p-0">
          {planes.length === 0 ? (
            <div className="flex items-center gap-2 px-5 py-8 text-sm text-graphite">
              <CheckCircle2 className="h-4 w-4 text-sage" />
              No hay planes de compensación en esta bandeja.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border">
                  <tr className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                    <th className="px-5 py-2.5 text-left">Empleado</th>
                    <th className="px-3 py-2.5 text-left">Estado</th>
                    <th className="px-3 py-2.5 text-right">A reponer</th>
                    <th className="px-3 py-2.5 text-right">Repuesto</th>
                    <th className="px-3 py-2.5 text-right">Pendiente</th>
                    <th className="px-3 py-2.5 text-left">Plazo</th>
                    <th className="px-5 py-2.5 text-right"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {planes.map((p) => {
                    const vencido = p.fecha_limite.slice(0, 10) < hoyISO()
                                    && p.estado === "activo";
                    return (
                      <tr key={p.id} className="hover:bg-cloud/50">
                        <td className="px-5 py-2.5 text-ink-900">{nombre(p.empleado_id)}</td>
                        <td className="px-3 py-2.5">
                          <Badge tone={TONO[p.estado] ?? "neutral"}>{p.estado}</Badge>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-graphite">
                          {minutosAHoras(p.minutos_a_compensar)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-sage">
                          {minutosAHoras(p.minutos_compensados)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-ink-900">
                          {minutosAHoras(p.minutos_pendientes)}
                        </td>
                        <td className={`px-3 py-2.5 ${vencido ? "text-terracotta" : "text-graphite"}`}>
                          {fechaCorta(p.fecha_limite)}
                          {vencido && " · vencido"}
                        </td>
                        <td className="px-5 py-2.5 text-right">
                          <button
                            onClick={() => validar.mutate(p.id)}
                            disabled={validar.isPending}
                            title="Confronta lo programado con las marcaciones reales"
                            className="inline-flex items-center gap-1 text-xs font-medium text-navy-600 hover:underline disabled:opacity-40"
                          >
                            <RefreshCw className={`h-3 w-3 ${
                              validar.isPending ? "animate-spin" : ""}`} />
                            Validar
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
