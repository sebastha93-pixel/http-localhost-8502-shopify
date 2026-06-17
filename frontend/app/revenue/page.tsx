"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { formatMoney } from "@/lib/utils";

interface DetailResp {
  conversation: any;
  lead: any;
  advisor: { name: string; email?: string } | null;
  messages: Array<{ message_id: string; sender_type: string; sender_name: string; message_text: string; sent_at: string }>;
  audit: any | null;
}

function fmtCop(n: any) {
  if (n == null) return "—";
  return `COP $${Number(n).toLocaleString("es-CO")}`;
}

interface StatsResp {
  ok: boolean;
  advisors?: number;
  leads?: number;
  conversations?: number;
  messages?: number;
  audits?: number;
  pending_audits?: number;
}

interface Conversation {
  conversation_id: string;
  lead_id: number;
  advisor_id: string | null;
  channel: string;
  started_at: string | null;
  last_message_at: string | null;
  status: string;
  message_count: number;
  audit_status: string;
  advisor_name?: string | null;
  lead_status?: string | null;
  lead_value?: number | null;
  customer_name?: string | null;
  customer_phone?: string | null;
}

interface AdvisorRow {
  advisor_id: string;
  name: string;
  email?: string;
  active: boolean;
  conversations: number;
  won: number;
  lost: number;
  in_progress: number;
  conversion_rate: number | null;
  last_activity: string | null;
  channels: Record<string, number>;
}

interface MessageRow {
  message_id: string;
  conversation_id: string;
  lead_id: number;
  sender_type: string;
  sender_name: string;
  message_text: string;
  sent_at: string;
  topic: string;
  customer_name?: string | null;
  customer_phone?: string | null;
  lead_status?: string | null;
}

const CHANNEL_LABEL: Record<string, string> = {
  waba: "WhatsApp",
  instagram_business: "Instagram",
  unknown: "—",
};

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    const d = new Date(s);
    return d.toLocaleString("es-CO", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return "—"; }
}

function fmtRelative(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  const diff = Date.now() - d.getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return "ahora";
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h`;
  const days = Math.floor(h / 24);
  return `${days}d`;
}

function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="text-graphite text-xs">—</span>;
  const map: Record<string, { tone: "normal" | "riesgo" | "critico"; label: string }> = {
    won:         { tone: "normal",  label: "Ganada" },
    lost:        { tone: "critico", label: "Perdida" },
    in_progress: { tone: "riesgo",  label: "En curso" },
    in_work:     { tone: "riesgo",  label: "Activa" },
    closed:      { tone: "normal",  label: "Cerrada" },
  };
  const cfg = map[status] || { tone: "riesgo" as const, label: status };
  return <Badge tone={cfg.tone}>{cfg.label}</Badge>;
}

function ConversationDetailModal({
  conversationId,
  onClose,
}: {
  conversationId: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const detailQ = useQuery<DetailResp>({
    queryKey: ["revenue", "detail", conversationId],
    queryFn: () => api.get(`/api/revenue/conversations/${conversationId}/detail`),
  });
  const auditMut = useMutation({
    mutationFn: () => api.post(`/api/revenue/audit/run/${conversationId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["revenue", "detail", conversationId] });
      qc.invalidateQueries({ queryKey: ["revenue", "stats"] });
    },
  });

  const d = detailQ.data;
  const audit = d?.audit;

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-stretch justify-end" onClick={onClose}>
      <div className="bg-white w-full max-w-3xl h-full overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b sticky top-0 bg-white flex items-center gap-3">
          <button onClick={onClose} className="text-graphite hover:text-navy text-2xl leading-none">×</button>
          <div className="flex-1">
            <div className="font-semibold">{d?.lead?.customer_name || "Cliente sin nombre"}</div>
            <div className="text-xs text-graphite">{conversationId} · {d?.advisor?.name || "Sin asesora"}</div>
          </div>
          <button
            onClick={() => auditMut.mutate()}
            disabled={auditMut.isPending}
            className="px-3 py-1.5 rounded bg-navy text-white text-sm disabled:opacity-50"
          >
            {auditMut.isPending ? "Auditando..." : audit ? "Re-auditar" : "Auditar con IA"}
          </button>
        </div>

        {detailQ.isLoading ? <div className="p-6"><LoadingState /></div> : detailQ.isError ? <div className="p-6"><ErrorState error={detailQ.error} /></div> : (
          <div className="p-4 space-y-4">
            {audit && (
              <Card>
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="font-semibold">Auditoría IA</div>
                    <Badge tone={audit.result_classification === "venta_lograda" ? "normal" : audit.result_classification === "venta_perdida" ? "critico" : "riesgo"}>
                      {audit.result_classification?.replace("_", " ") || "—"}
                    </Badge>
                  </div>
                  <p className="text-sm">{audit.ai_summary_internal}</p>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
                    <div><span className="text-graphite">Overall:</span> <span className="font-medium">{audit.overall_score ?? "—"}/10</span></div>
                    <div><span className="text-graphite">Respuesta:</span> <span className="font-medium">{audit.response_time_score ?? "—"}/10</span></div>
                    <div><span className="text-graphite">Atención:</span> <span className="font-medium">{audit.attention_score ?? "—"}/10</span></div>
                    <div><span className="text-graphite">Follow-up:</span> <span className="font-medium">{audit.follow_up_score ?? "—"}/10</span></div>
                    <div><span className="text-graphite">Cierre:</span> <span className="font-medium">{audit.closing_score ?? "—"}/10</span></div>
                  </div>
                  {audit.main_loss_reason && (
                    <div className="text-sm"><span className="text-graphite">Motivo principal:</span> <span className="font-medium">{audit.main_loss_reason}</span></div>
                  )}
                  {audit.lost_moment && (
                    <div className="text-sm bg-rose-50 border-l-2 border-rose-400 p-2">
                      <div className="text-xs text-graphite">Momento crítico:</div>
                      <div>"{audit.lost_moment}"</div>
                      {audit.recommended_response && (
                        <div className="mt-2">
                          <div className="text-xs text-graphite">Debió responder:</div>
                          <div className="text-emerald-800">"{audit.recommended_response}"</div>
                        </div>
                      )}
                    </div>
                  )}
                  {audit.economic_impact_estimate > 0 && (
                    <div className="text-sm"><span className="text-graphite">Impacto económico estimado:</span> <span className="font-medium">{fmtCop(audit.economic_impact_estimate)}</span></div>
                  )}
                  {audit.raw_analysis?.recomendaciones?.length > 0 && (
                    <div>
                      <div className="text-xs text-graphite mb-1">Recomendaciones:</div>
                      <ul className="list-disc list-inside text-sm space-y-1">
                        {audit.raw_analysis.recomendaciones.map((r: string, i: number) => <li key={i}>{r}</li>)}
                      </ul>
                    </div>
                  )}
                  <div className="text-xs text-graphite border-t pt-2">
                    {audit.modelo_ia} · costo ${audit.costo_analisis_usd?.toFixed(4)} USD · confianza {((audit.confidence_score ?? 0) * 100).toFixed(0)}%
                  </div>
                </CardContent>
              </Card>
            )}

            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-graphite mb-3">Thread completo ({d?.messages?.length || 0} mensajes)</div>
                <div className="space-y-2 max-h-[60vh] overflow-y-auto">
                  {(d?.messages || []).map((m) => (
                    <div key={m.message_id} className={`flex ${m.sender_type === "customer" ? "justify-start" : "justify-end"}`}>
                      <div className={`max-w-[75%] rounded px-3 py-2 text-sm ${m.sender_type === "customer" ? "bg-cloud" : "bg-navy text-white"}`}>
                        <div className="text-xs opacity-70 mb-0.5">{m.sender_name || m.sender_type}</div>
                        <div>{m.message_text || <em>(sin texto)</em>}</div>
                        <div className="text-xs opacity-60 mt-1">{new Date(m.sent_at).toLocaleString("es-CO")}</div>
                      </div>
                    </div>
                  ))}
                  {!d?.messages?.length && <div className="text-center text-graphite py-8">Sin mensajes</div>}
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}


function CalcularRankingsBtn({ daysBack }: { daysBack: number }) {
  const qc = useQueryClient();
  const [last, setLast] = useState<{ ts: string; ok: number; total: number } | null>(null);
  const mut = useMutation({
    mutationFn: () => api.post<{ ok: boolean; persistidos: number; total_advisors: number }>(`/api/revenue/rankings/calcular?days_back=${daysBack}`),
    onSuccess: (data) => {
      setLast({ ts: new Date().toLocaleTimeString("es-CO"), ok: data.persistidos, total: data.total_advisors });
      qc.invalidateQueries({ queryKey: ["revenue", "advisors"] });
    },
  });
  return (
    <div className="flex items-center gap-3 mb-4 pb-3 border-b">
      <button
        onClick={() => mut.mutate()}
        disabled={mut.isPending}
        className="px-3 py-1.5 rounded bg-navy text-white text-sm disabled:opacity-50"
      >
        {mut.isPending ? "Calculando..." : "Persistir snapshot del periodo"}
      </button>
      {last && (
        <div className="text-xs text-graphite">
          ✓ {last.ts} · {last.ok}/{last.total} asesoras guardadas en histórico
        </div>
      )}
      {mut.isError && <div className="text-xs text-rose-700">Error: {String(mut.error)}</div>}
    </div>
  );
}


function TendenciasTab({ daysBack }: { daysBack: number }) {
  const q = useQuery<any>({
    queryKey: ["revenue", "tendencias", daysBack],
    queryFn: () => api.get(`/api/revenue/tendencias?days_back=${daysBack}`),
  });
  if (q.isLoading) return <LoadingState />;
  if (q.isError) return <ErrorState error={q.error} />;
  const d = q.data;
  const maxHora = Math.max(1, ...(d?.por_hora || []).map((h: any) => h.total));
  const maxDia = Math.max(1, ...(d?.por_dia_semana || []).map((h: any) => h.total));

  return (
    <div className="space-y-4">
      <Card><CardContent className="p-4">
        <div className="text-sm font-semibold mb-3">Por canal</div>
        <table className="min-w-full text-sm">
          <thead className="text-left text-graphite border-b">
            <tr><th className="py-2">Canal</th><th className="text-right">Total</th><th className="text-right">Ganadas</th><th className="text-right">Perdidas</th><th className="text-right">En curso</th><th className="text-right">% Conv.</th></tr>
          </thead>
          <tbody>
            {(d?.por_canal || []).map((c: any) => (
              <tr key={c.canal} className="border-b">
                <td className="py-2">{c.canal}</td>
                <td className="text-right">{c.total}</td>
                <td className="text-right text-emerald-700">{c.won}</td>
                <td className="text-right text-rose-700">{c.lost}</td>
                <td className="text-right">{c.en_proceso}</td>
                <td className="text-right font-medium">{c.conv_rate != null ? `${c.conv_rate}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent></Card>

      <Card><CardContent className="p-4">
        <div className="text-sm font-semibold mb-3">Por hora del día (Bogotá UTC-5)</div>
        <div className="flex items-end gap-1 h-32">
          {(d?.por_hora || []).map((h: any) => {
            const total = h.total;
            const heightPct = total > 0 ? (total / maxHora) * 100 : 0;
            const wonPct = total > 0 ? (h.won / total) * heightPct : 0;
            return (
              <div key={h.hora} className="flex-1 flex flex-col items-center" title={`${h.hora}h: ${total} (${h.won} won, ${h.lost} lost)`}>
                <div className="w-full flex flex-col-reverse" style={{ height: `${heightPct}%` }}>
                  <div className="bg-emerald-500" style={{ height: `${wonPct}%`, minHeight: h.won ? "2px" : 0 }} />
                  <div className="bg-navy/40 flex-1" />
                </div>
                <div className="text-[10px] text-graphite mt-1">{h.hora}</div>
              </div>
            );
          })}
        </div>
        <div className="text-xs text-graphite mt-2">Verde = ganadas, gris = total. Hora donde concentras más conversaciones.</div>
      </CardContent></Card>

      <Card><CardContent className="p-4">
        <div className="text-sm font-semibold mb-3">Por día de la semana</div>
        <div className="flex items-end gap-2 h-32">
          {(d?.por_dia_semana || []).map((dia: any) => {
            const total = dia.total;
            const heightPct = total > 0 ? (total / maxDia) * 100 : 0;
            return (
              <div key={dia.dia} className="flex-1 flex flex-col items-center">
                <div className="w-full bg-navy/40" style={{ height: `${heightPct}%`, minHeight: total ? "2px" : 0 }} />
                <div className="text-xs mt-1">{dia.dia_label}</div>
                <div className="text-[10px] text-graphite">{total} · {dia.conv_rate != null ? `${dia.conv_rate}%` : "—"}</div>
              </div>
            );
          })}
        </div>
      </CardContent></Card>
    </div>
  );
}


function AlertasTab({ onSelect }: { onSelect: (id: string) => void }) {
  const [umbral, setUmbral] = useState(30);
  const q = useQuery<any>({
    queryKey: ["revenue", "alertas", umbral],
    queryFn: () => api.get(`/api/revenue/alertas?sin_respuesta_min=${umbral}`),
    refetchInterval: 60_000,
  });
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-3 mb-3">
          <label className="text-sm text-graphite">Umbral sin respuesta:</label>
          <select value={umbral} onChange={(e) => setUmbral(Number(e.target.value))} className="border rounded px-2 py-1 text-sm">
            <option value={15}>15 min</option>
            <option value={30}>30 min</option>
            <option value={60}>1 hora</option>
            <option value={120}>2 horas</option>
            <option value={240}>4 horas</option>
          </select>
          <div className="ml-auto text-xs text-graphite">Auto-refresh 60s</div>
        </div>
        {q.isLoading ? <LoadingState /> : q.isError ? <ErrorState error={q.error} /> : (
          <div className="space-y-2">
            {(q.data?.alertas || []).map((a: any) => (
              <div key={a.conversation_id} onClick={() => onSelect(a.conversation_id)} className="border-l-4 border-rose-500 bg-rose-50/60 hover:bg-rose-50 cursor-pointer p-3 rounded">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="font-medium">{a.customer_name || a.customer_phone || "—"}</div>
                  <Badge tone="critico">{a.minutos_sin_respuesta}m sin respuesta</Badge>
                </div>
                <div className="text-xs text-graphite mt-1">{a.advisor_name} · {a.channel}</div>
                <div className="text-sm mt-2 italic">"{a.ultimo_mensaje}"</div>
              </div>
            ))}
            {!q.data?.alertas?.length && (
              <div className="text-center text-graphite py-8">Ninguna conversación con cliente esperando.</div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}


function CoachingTab({ advisors }: { advisors: AdvisorRow[] }) {
  const [selectedAdvisor, setSelectedAdvisor] = useState<string>("");
  const q = useQuery<any>({
    queryKey: ["revenue", "coaching", selectedAdvisor],
    queryFn: () => api.get(`/api/revenue/coaching/${selectedAdvisor}?days_back=60`),
    enabled: !!selectedAdvisor,
  });
  return (
    <Card><CardContent className="p-4">
      <div className="flex gap-3 items-center mb-4">
        <label className="text-sm text-graphite">Asesora:</label>
        <select value={selectedAdvisor} onChange={(e) => setSelectedAdvisor(e.target.value)} className="border rounded px-2 py-1 text-sm">
          <option value="">— Selecciona —</option>
          {advisors.filter(a => a.conversations > 0).map(a => (
            <option key={a.advisor_id} value={a.advisor_id}>{a.name} ({a.conversations})</option>
          ))}
        </select>
      </div>
      {!selectedAdvisor && <div className="text-center text-graphite py-8">Selecciona una asesora para generar coaching IA basado en sus auditorías.</div>}
      {selectedAdvisor && q.isLoading && <LoadingState />}
      {selectedAdvisor && q.isError && <ErrorState error={q.error} />}
      {q.data && !q.data.ok && (
        <div className="text-center text-graphite py-8">{q.data.error === "sin_auditorias" ? "Esta asesora aún no tiene auditorías." : `Error: ${q.data.error}`}</div>
      )}
      {q.data?.ok && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
            <div><div className="text-graphite text-xs">Auditorías</div><div className="font-medium">{q.data.n_auditorias}</div></div>
            <div><div className="text-graphite text-xs">% Conversión</div><div className="font-medium">{q.data.stats.conversion_rate}%</div></div>
            <div><div className="text-graphite text-xs">Won / Lost</div><div className="font-medium text-emerald-700">{q.data.stats.won}</div></div>
            <div><div className="text-graphite text-xs">Impacto perdido</div><div className="font-medium text-rose-700">{q.data.stats.impact_perdido_cop ? `COP $${q.data.stats.impact_perdido_cop.toLocaleString("es-CO")}` : "—"}</div></div>
            <div><div className="text-graphite text-xs">Overall avg</div><div className="font-medium">{q.data.stats.avg_overall ?? "—"}/10</div></div>
          </div>

          <div className="bg-cloud/50 p-3 rounded">
            <div className="text-xs text-graphite mb-1">Diagnóstico general</div>
            <div className="text-sm">{q.data.coaching?.diagnostico_general}</div>
          </div>

          {q.data.coaching?.prioridad_urgente && (
            <div className="bg-amber-50 border-l-4 border-amber-500 p-3">
              <div className="text-xs text-graphite mb-1">⚡ Prioridad urgente esta semana</div>
              <div className="text-sm font-medium">{q.data.coaching.prioridad_urgente}</div>
            </div>
          )}

          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <div className="text-sm font-semibold mb-1 text-emerald-700">Fortalezas</div>
              <ul className="text-sm list-disc list-inside space-y-1">
                {(q.data.coaching?.fortalezas || []).map((s: string, i: number) => <li key={i}>{s}</li>)}
              </ul>
            </div>
            <div>
              <div className="text-sm font-semibold mb-1 text-rose-700">Áreas de mejora</div>
              <ul className="text-sm list-disc list-inside space-y-1">
                {(q.data.coaching?.areas_de_mejora || []).map((s: string, i: number) => <li key={i}>{s}</li>)}
              </ul>
            </div>
          </div>

          {q.data.coaching?.plan_accion_30_dias?.length > 0 && (
            <div>
              <div className="text-sm font-semibold mb-2">Plan de acción 30 días</div>
              <div className="grid md:grid-cols-2 gap-2">
                {q.data.coaching.plan_accion_30_dias.map((s: any, i: number) => (
                  <div key={i} className="border rounded p-3">
                    <div className="text-xs text-graphite">Semana {s.semana}</div>
                    <div className="font-medium text-sm">{s.objetivo}</div>
                    <div className="text-xs mt-1">{s.ejercicio}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid md:grid-cols-2 gap-3">
            {q.data.coaching?.frases_modelo?.length > 0 && (
              <div>
                <div className="text-sm font-semibold mb-1 text-emerald-700">Frases modelo (usar más)</div>
                <ul className="text-sm list-disc list-inside space-y-1">
                  {q.data.coaching.frases_modelo.map((s: string, i: number) => <li key={i} className="italic">"{s}"</li>)}
                </ul>
              </div>
            )}
            {q.data.coaching?.frases_a_evitar?.length > 0 && (
              <div>
                <div className="text-sm font-semibold mb-1 text-rose-700">Frases a evitar</div>
                <ul className="text-sm list-disc list-inside space-y-1">
                  {q.data.coaching.frases_a_evitar.map((s: string, i: number) => <li key={i} className="italic">"{s}"</li>)}
                </ul>
              </div>
            )}
          </div>

          <div className="text-xs text-graphite border-t pt-2">{q.data.modelo} · costo ${q.data.costo_usd?.toFixed(4)} USD</div>
        </div>
      )}
    </CardContent></Card>
  );
}


export default function RevenuePage() {
  const [daysBack, setDaysBack] = useState(30);
  const [advisorFilter, setAdvisorFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [channelFilter, setChannelFilter] = useState<string>("");
  const [selectedConv, setSelectedConv] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>("conversaciones");

  // Stats: refresh moderado cada 2 min (era 30s)
  const statsQ = useQuery<StatsResp>({
    queryKey: ["revenue", "stats"],
    queryFn: () => api.get("/api/revenue/stats"),
    refetchInterval: 2 * 60_000,
  });

  // Conversaciones: solo si la tab activa la usa
  const convsQ = useQuery<{ conversations: Conversation[]; total: number }>({
    queryKey: ["revenue", "conversations", daysBack, advisorFilter, statusFilter, channelFilter],
    enabled: activeTab === "conversaciones",
    queryFn: () => {
      const params = new URLSearchParams({ days_back: String(daysBack), limit: "200" });
      if (advisorFilter) params.set("advisor_id", advisorFilter);
      if (statusFilter) params.set("status", statusFilter);
      if (channelFilter) params.set("channel", channelFilter);
      return api.get(`/api/revenue/conversations?${params.toString()}`);
    },
  });

  // Asesoras: si está activa o si conversaciones la necesita para el dropdown
  const advisorsQ = useQuery<{ rows: AdvisorRow[]; total: number }>({
    queryKey: ["revenue", "advisors", "ranking", daysBack],
    queryFn: () => api.get(`/api/revenue/advisors/ranking?days_back=${daysBack}`),
    enabled: activeTab === "asesoras" || activeTab === "conversaciones" || activeTab === "coaching",
  });

  // Mensajes: refresh suave cada 60s (era 15s) y solo si la tab está activa
  const msgsQ = useQuery<{ messages: MessageRow[]; total: number }>({
    queryKey: ["revenue", "messages", "recent"],
    queryFn: () => api.get("/api/revenue/messages/recent?limit=100"),
    enabled: activeTab === "mensajes",
    refetchInterval: 60_000,
  });

  const stats = statsQ.data;

  return (
    <PageShell
      title="Revenue Intelligence"
      subtitle="Auditoría comercial: conversaciones, asesoras y conversión"
    >
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <KpiCard label="Asesoras" value={stats?.advisors ?? "—"} />
        <KpiCard label="Leads" value={stats?.leads?.toLocaleString("es-CO") ?? "—"} />
        <KpiCard label="Conversaciones" value={stats?.conversations?.toLocaleString("es-CO") ?? "—"} />
        <KpiCard label="Mensajes" value={stats?.messages?.toLocaleString("es-CO") ?? "—"} />
        <KpiCard label="Auditorías pend." value={stats?.pending_audits?.toLocaleString("es-CO") ?? "—"} />
      </div>

      <div className="flex flex-wrap gap-3 items-center mb-4">
        <label className="text-sm text-graphite">Periodo:</label>
        <select value={daysBack} onChange={(e) => setDaysBack(Number(e.target.value))} className="border rounded px-2 py-1 text-sm">
          <option value={7}>7 días</option>
          <option value={30}>30 días</option>
          <option value={90}>90 días</option>
          <option value={365}>1 año</option>
        </select>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="conversaciones">Conversaciones</TabsTrigger>
          <TabsTrigger value="asesoras">Ranking asesoras</TabsTrigger>
          <TabsTrigger value="mensajes">Mensajes recientes</TabsTrigger>
          <TabsTrigger value="tendencias">Tendencias</TabsTrigger>
          <TabsTrigger value="alertas">Alertas</TabsTrigger>
          <TabsTrigger value="coaching">Coaching IA</TabsTrigger>
        </TabsList>

        <TabsContent value="conversaciones">
          <Card>
            <CardContent className="p-4">
              <div className="flex flex-wrap gap-3 mb-3 items-center">
                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="border rounded px-2 py-1 text-sm">
                  <option value="">Todos los estados</option>
                  <option value="in_work">Activas</option>
                  <option value="closed">Cerradas</option>
                </select>
                <select value={channelFilter} onChange={(e) => setChannelFilter(e.target.value)} className="border rounded px-2 py-1 text-sm">
                  <option value="">Todos los canales</option>
                  <option value="waba">WhatsApp</option>
                  <option value="instagram_business">Instagram</option>
                </select>
                {advisorsQ.data && (
                  <select value={advisorFilter} onChange={(e) => setAdvisorFilter(e.target.value)} className="border rounded px-2 py-1 text-sm">
                    <option value="">Todas las asesoras</option>
                    {advisorsQ.data.rows.map((a) => (
                      <option key={a.advisor_id} value={a.advisor_id}>{a.name}</option>
                    ))}
                  </select>
                )}
                <div className="ml-auto text-sm text-graphite">
                  {convsQ.data ? `${convsQ.data.total} conversaciones` : ""}
                </div>
              </div>
              {convsQ.isLoading ? <LoadingState /> : convsQ.isError ? <ErrorState error={convsQ.error} /> : (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="text-left text-graphite border-b">
                      <tr>
                        <th className="py-2 pr-3">Cliente</th>
                        <th className="py-2 pr-3">Asesora</th>
                        <th className="py-2 pr-3">Canal</th>
                        <th className="py-2 pr-3">Último mensaje</th>
                        <th className="py-2 pr-3">Estado conv.</th>
                        <th className="py-2 pr-3">Estado venta</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(convsQ.data?.conversations || []).map((c) => (
                        <tr key={c.conversation_id} className="border-b hover:bg-cloud/40 cursor-pointer" onClick={() => setSelectedConv(c.conversation_id)}>
                          <td className="py-2 pr-3">
                            <div className="font-medium">
                              {c.customer_name?.trim() || c.customer_phone || <span className="text-graphite italic">Lead #{c.lead_id}</span>}
                            </div>
                            {c.customer_name?.trim() && c.customer_phone && (
                              <div className="text-xs text-graphite">{c.customer_phone}</div>
                            )}
                          </td>
                          <td className="py-2 pr-3">{c.advisor_name || <span className="text-graphite italic">Sin asignar</span>}</td>
                          <td className="py-2 pr-3">{CHANNEL_LABEL[c.channel] || c.channel}</td>
                          <td className="py-2 pr-3 whitespace-nowrap">{fmtRelative(c.last_message_at)}</td>
                          <td className="py-2 pr-3"><StatusBadge status={c.status} /></td>
                          <td className="py-2 pr-3"><StatusBadge status={c.lead_status || undefined} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!convsQ.data?.conversations?.length && (
                    <div className="text-center text-graphite py-8">Sin conversaciones en el rango.</div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="asesoras">
          <Card>
            <CardContent className="p-4">
              <CalcularRankingsBtn daysBack={daysBack} />
              {advisorsQ.isLoading ? <LoadingState /> : advisorsQ.isError ? <ErrorState error={advisorsQ.error} /> : (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="text-left text-graphite border-b">
                      <tr>
                        <th className="py-2 pr-3">Asesora</th>
                        <th className="py-2 pr-3 text-right">Conv.</th>
                        <th className="py-2 pr-3 text-right">Ganadas</th>
                        <th className="py-2 pr-3 text-right">Perdidas</th>
                        <th className="py-2 pr-3 text-right">En curso</th>
                        <th className="py-2 pr-3 text-right">% Conv.</th>
                        <th className="py-2 pr-3">Último activo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(advisorsQ.data?.rows || []).map((r) => (
                        <tr key={r.advisor_id} className="border-b">
                          <td className="py-2 pr-3">
                            <div className="font-medium">{r.name}</div>
                            <div className="text-xs text-graphite">{r.email}</div>
                          </td>
                          <td className="py-2 pr-3 text-right">{r.conversations}</td>
                          <td className="py-2 pr-3 text-right text-emerald-700">{r.won}</td>
                          <td className="py-2 pr-3 text-right text-rose-700">{r.lost}</td>
                          <td className="py-2 pr-3 text-right">{r.in_progress}</td>
                          <td className="py-2 pr-3 text-right font-medium">
                            {r.conversion_rate != null ? `${r.conversion_rate}%` : "—"}
                          </td>
                          <td className="py-2 pr-3 whitespace-nowrap">{fmtRelative(r.last_activity)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="mensajes">
          <Card>
            <CardContent className="p-4">
              <div className="text-xs text-graphite mb-3">Auto-actualiza cada 60s</div>
              {msgsQ.isLoading ? <LoadingState /> : msgsQ.isError ? <ErrorState error={msgsQ.error} /> : (
                <div className="space-y-2">
                  {(msgsQ.data?.messages || []).map((m) => (
                    <div key={m.message_id} className={`border-l-2 pl-3 py-1 cursor-pointer hover:bg-cloud/40 ${m.sender_type === "customer" ? "border-navy" : m.sender_type === "advisor" ? "border-emerald-600" : "border-graphite"}`} onClick={() => setSelectedConv(m.conversation_id)}>
                      <div className="flex items-baseline justify-between gap-2">
                        <div className="text-xs text-graphite">
                          <span className="font-medium">
                            {m.sender_type === "customer" ? "👤 " : m.sender_type === "advisor" ? "💼 " : ""}
                            {m.sender_name || m.customer_name || "—"}
                          </span>
                          {m.customer_phone && <span className="ml-2">{m.customer_phone}</span>}
                        </div>
                        <div className="text-xs text-graphite whitespace-nowrap">{fmtDate(m.sent_at)}</div>
                      </div>
                      <div className="text-sm">{m.message_text || <em className="text-graphite">(sin texto)</em>}</div>
                    </div>
                  ))}
                  {!msgsQ.data?.messages?.length && (
                    <div className="text-center text-graphite py-8">Aún no hay mensajes capturados.</div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tendencias">
          <TendenciasTab daysBack={daysBack} />
        </TabsContent>

        <TabsContent value="alertas">
          <AlertasTab onSelect={setSelectedConv} />
        </TabsContent>

        <TabsContent value="coaching">
          <CoachingTab advisors={advisorsQ.data?.rows || []} />
        </TabsContent>
      </Tabs>

      {selectedConv && (
        <ConversationDetailModal
          conversationId={selectedConv}
          onClose={() => setSelectedConv(null)}
        />
      )}
    </PageShell>
  );
}
