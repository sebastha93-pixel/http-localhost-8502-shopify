"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { esAdmin } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiStrip } from "@/components/kpi-card";
import { Shield } from "lucide-react";

interface Diagnostico {
  ok: boolean;
  ventana_dias: number;
  desde: string;
  hasta: string;
  audits: {
    total: number;
    haiku_dice: Record<string, number>;
    kommo_dice: Record<string, number>;
    mismatches_count: Record<string, number>;
    mismatches_ejemplos: Record<string, any[]>;
  };
  conversations: {
    total: number;
    con_lead_id: number;
    sin_lead_id_huerfanas: number;
    sin_advisor_asignada: number;
    ejemplos_huerfanas: any[];
    edad_distribucion: Record<string, number>;
  };
  leads_periodo: {
    total: number;
    distribucion_status: Record<string, number>;
    valor_total_ganadas_cop: number;
    valor_total_perdidas_cop: number;
  };
}

function fmtCop(n: number | null | undefined) {
  if (n == null) return "—";
  return `COP $${Number(n).toLocaleString("es-CO")}`;
}

export default function DiagnosticoRevenuePage() {
  const { user } = useAuth();
  const [days, setDays] = useState<number>(8);

  const q = useQuery<Diagnostico>({
    queryKey: ["diagnostico-revenue", days],
    queryFn: () => api.get(`/api/revenue/diagnostico/data-quality?days_back=${days}`),
    enabled: esAdmin(user),
    staleTime: 60_000,
  });

  if (!esAdmin(user)) {
    return (
      <PageShell title="Diagnóstico Revenue">
        <Card className="border-terracotta/25 bg-terracotta/[0.03]">
          <CardContent className="p-10 text-center">
            <Shield className="mx-auto mb-3 h-10 w-10 text-terracotta" />
            <p className="font-display text-base font-medium text-ink-900">Acceso restringido</p>
            <p className="mt-1 text-sm text-graphite">Solo administradores pueden ver este reporte.</p>
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  if (q.isLoading) return <LoadingState label="Calculando diagnóstico…" />;
  if (q.isError || !q.data?.ok) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const d = q.data;
  const totalMismatch = Object.values(d.audits.mismatches_count).reduce((a, b) => a + b, 0);
  const haikuLost = d.audits.haiku_dice["venta_perdida"] || 0;
  const kommoLost = d.audits.kommo_dice["venta_perdida"] || 0;
  const haikuWon  = d.audits.haiku_dice["venta_lograda"] || 0;
  const kommoWon  = d.audits.kommo_dice["venta_lograda"] || 0;

  return (
    <PageShell
      title="Diagnóstico Revenue"
      subtitle={`Calidad de los datos · ventana de ${d.ventana_dias} días`}
      isFetching={q.isFetching}
      onRefresh={() => q.refetch()}
    >
      {/* Selector de ventana */}
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-[0.62rem] uppercase tracking-[0.14em] text-graphite">Ventana</label>
        <div className="inline-flex overflow-hidden rounded-sm border border-border bg-card">
          {[3, 8, 15, 30, 60].map((dd) => (
            <button
              key={dd}
              onClick={() => setDays(dd)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                days === dd ? "bg-ink-900 text-white" : "text-graphite hover:bg-cloud"
              }`}
            >
              {dd}d
            </button>
          ))}
        </div>
      </div>

      {/* Resumen ejecutivo */}
      <KpiStrip
        items={[
          { label: "Audits",        value: d.audits.total },
          { label: "Conversaciones", value: d.conversations.total },
          { label: "Huérfanas",     value: d.conversations.sin_lead_id_huerfanas, tone: d.conversations.sin_lead_id_huerfanas > 0 ? "danger" : "default" },
          { label: "Mismatches IA", value: totalMismatch,                          tone: totalMismatch > 0 ? "danger" : "success" },
          { label: "Ganadas COP",   value: fmtCop(d.leads_periodo.valor_total_ganadas_cop),  tone: "success" },
          { label: "Perdidas COP",  value: fmtCop(d.leads_periodo.valor_total_perdidas_cop), tone: "danger" },
        ]}
      />

      {/* AUDITS: Haiku vs Kommo */}
      <section>
        <p className="section-label mb-3">Audits — clasificación según fuente</p>
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardContent className="p-5">
              <p className="text-xs font-medium text-graphite mb-2">Según Haiku (lo que dijo la IA)</p>
              <table className="w-full text-sm">
                <tbody>
                  <tr><td className="py-1">Venta lograda</td><td className="py-1 text-right tabular text-sage">{haikuWon}</td></tr>
                  <tr><td className="py-1">Venta perdida</td><td className="py-1 text-right tabular text-terracotta">{haikuLost}</td></tr>
                  <tr><td className="py-1">Inconclusa</td><td className="py-1 text-right tabular">{d.audits.haiku_dice["inconclusa"] || 0}</td></tr>
                </tbody>
              </table>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-5">
              <p className="text-xs font-medium text-graphite mb-2">Según Kommo (verdad operativa)</p>
              <table className="w-full text-sm">
                <tbody>
                  <tr><td className="py-1">Ganada (won)</td><td className="py-1 text-right tabular text-sage">{kommoWon}</td></tr>
                  <tr><td className="py-1">Perdida (lost)</td><td className="py-1 text-right tabular text-terracotta">{kommoLost}</td></tr>
                  <tr><td className="py-1">En proceso</td><td className="py-1 text-right tabular">{d.audits.kommo_dice["en_proceso"] || 0}</td></tr>
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* MISMATCHES con ejemplos */}
      <section>
        <p className="section-label mb-3">Discrepancias Haiku vs Kommo · ejemplos para inspección</p>
        <div className="space-y-3">
          {Object.entries(d.audits.mismatches_ejemplos).map(([k, ejemplos]) => (
            <Card key={k}>
              <CardContent className="p-4">
                <div className="mb-2 flex items-baseline justify-between">
                  <p className="font-medium text-ink-900">{labelMismatch(k)}</p>
                  <Badge tone={d.audits.mismatches_count[k] > 0 ? "critico" : "normal"}>
                    {d.audits.mismatches_count[k]} casos
                  </Badge>
                </div>
                {ejemplos.length === 0 ? (
                  <p className="text-xs text-graphite italic">Sin casos en este período.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {ejemplos.map((e: any, i: number) => (
                      <li key={i} className="rounded-sm border border-border bg-cloud/30 px-3 py-2 text-xs">
                        <span className="font-medium text-ink-900">{e.cliente || `Lead #${e.lead_id}`}</span>
                        {e.lead_value > 0 && <span className="ml-2 text-ochre tabular">{fmtCop(e.lead_value)}</span>}
                        <span className="ml-3 text-graphite">
                          Haiku: <span className="text-ink-900">{e.haiku}</span>{" · "}
                          Kommo: <span className="text-ink-900">{e.kommo_status || "—"}</span>
                        </span>
                        {e.conversation_id && (
                          <a
                            href={`/revenue?conv=${e.conversation_id}`}
                            className="ml-3 text-navy-600 hover:underline"
                          >
                            ver →
                          </a>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* CONVERSATIONS */}
      <section>
        <p className="section-label mb-3">Conversaciones del período</p>
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardContent className="p-5">
              <p className="text-xs font-medium text-graphite mb-2">Calidad</p>
              <table className="w-full text-sm">
                <tbody>
                  <tr><td className="py-1">Total</td><td className="py-1 text-right tabular font-medium">{d.conversations.total}</td></tr>
                  <tr><td className="py-1">Con lead asociado</td><td className="py-1 text-right tabular text-sage">{d.conversations.con_lead_id}</td></tr>
                  <tr><td className="py-1">Huérfanas (sin lead)</td><td className="py-1 text-right tabular text-terracotta">{d.conversations.sin_lead_id_huerfanas}</td></tr>
                  <tr><td className="py-1">Sin asesora asignada</td><td className="py-1 text-right tabular text-ochre">{d.conversations.sin_advisor_asignada}</td></tr>
                </tbody>
              </table>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-5">
              <p className="text-xs font-medium text-graphite mb-2">Edad del último mensaje</p>
              <table className="w-full text-sm">
                <tbody>
                  {Object.entries(d.conversations.edad_distribucion).map(([k, v]) => (
                    <tr key={k}>
                      <td className="py-1">{k}</td>
                      <td className="py-1 text-right tabular">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>

        {d.conversations.ejemplos_huerfanas.length > 0 && (
          <Card className="mt-3">
            <CardContent className="p-5">
              <p className="text-xs font-medium text-graphite mb-2">Conversaciones huérfanas (primeras 10)</p>
              <ul className="space-y-1 text-xs">
                {d.conversations.ejemplos_huerfanas.map((c: any, i: number) => (
                  <li key={i} className="flex justify-between gap-3">
                    <span className="font-mono text-ink-900 truncate">{c.conversation_id}</span>
                    <span className="text-graphite">{c.last_message_at?.slice(0, 16).replace("T", " ")}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </section>

      {/* LEADS POR STATUS */}
      <section>
        <p className="section-label mb-3">Leads del período por status (Kommo)</p>
        <Card>
          <CardContent className="p-5">
            <table className="w-full text-sm">
              <thead className="border-b border-border">
                <tr>
                  <th className="text-left py-2 text-[0.62rem] uppercase tracking-[0.12em] text-graphite">Status</th>
                  <th className="text-right py-2 text-[0.62rem] uppercase tracking-[0.12em] text-graphite">Cantidad</th>
                  <th className="text-right py-2 text-[0.62rem] uppercase tracking-[0.12em] text-graphite">%</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(d.leads_periodo.distribucion_status)
                  .sort((a, b) => b[1] - a[1])
                  .map(([status, count]) => {
                    const pct = d.leads_periodo.total > 0
                      ? Math.round((count / d.leads_periodo.total) * 100)
                      : 0;
                    return (
                      <tr key={status} className="border-b border-border">
                        <td className="py-2 text-ink-900">{status}</td>
                        <td className="py-2 text-right tabular font-medium">{count}</td>
                        <td className="py-2 text-right tabular text-graphite">{pct}%</td>
                      </tr>
                    );
                  })}
                <tr className="bg-cloud/40">
                  <td className="py-2 font-medium text-ink-900">Total</td>
                  <td className="py-2 text-right tabular font-medium">{d.leads_periodo.total}</td>
                  <td className="py-2 text-right tabular font-medium">100%</td>
                </tr>
              </tbody>
            </table>
          </CardContent>
        </Card>
      </section>

      <p className="text-center text-[0.65rem] text-graphite/70">
        Desde {d.desde.slice(0, 16).replace("T", " ")} · Hasta {d.hasta.slice(0, 16).replace("T", " ")}
      </p>
    </PageShell>
  );
}

function labelMismatch(k: string): string {
  switch (k) {
    case "haiku_perdida_kommo_ganada": return "Haiku dijo perdida — Kommo dice ganada (falsos negativos)";
    case "haiku_ganada_kommo_perdida": return "Haiku dijo ganada — Kommo dice perdida (falsos positivos)";
    case "haiku_terminal_kommo_abierto": return "Haiku cerró el caso — Kommo sigue en proceso";
    case "sin_lead_id_en_audit": return "Audits sin lead_id (huérfanos)";
    default: return k;
  }
}
