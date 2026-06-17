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


export default function RevenuePage() {
  const [daysBack, setDaysBack] = useState(30);
  const [advisorFilter, setAdvisorFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [channelFilter, setChannelFilter] = useState<string>("");
  const [selectedConv, setSelectedConv] = useState<string | null>(null);

  const statsQ = useQuery<StatsResp>({
    queryKey: ["revenue", "stats"],
    queryFn: () => api.get("/api/revenue/stats"),
    refetchInterval: 30000,
  });

  const convsQ = useQuery<{ conversations: Conversation[]; total: number }>({
    queryKey: ["revenue", "conversations", daysBack, advisorFilter, statusFilter, channelFilter],
    queryFn: () => {
      const params = new URLSearchParams({ days_back: String(daysBack), limit: "200" });
      if (advisorFilter) params.set("advisor_id", advisorFilter);
      if (statusFilter) params.set("status", statusFilter);
      if (channelFilter) params.set("channel", channelFilter);
      return api.get(`/api/revenue/conversations?${params.toString()}`);
    },
  });

  const advisorsQ = useQuery<{ rows: AdvisorRow[]; total: number }>({
    queryKey: ["revenue", "advisors", "ranking", daysBack],
    queryFn: () => api.get(`/api/revenue/advisors/ranking?days_back=${daysBack}`),
  });

  const msgsQ = useQuery<{ messages: MessageRow[]; total: number }>({
    queryKey: ["revenue", "messages", "recent"],
    queryFn: () => api.get("/api/revenue/messages/recent?limit=100"),
    refetchInterval: 15000,
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

      <Tabs defaultValue="conversaciones">
        <TabsList>
          <TabsTrigger value="conversaciones">Conversaciones</TabsTrigger>
          <TabsTrigger value="asesoras">Ranking asesoras</TabsTrigger>
          <TabsTrigger value="mensajes">Mensajes recientes</TabsTrigger>
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
                            <div className="font-medium">{c.customer_name || "—"}</div>
                            <div className="text-xs text-graphite">{c.customer_phone || ""}</div>
                          </td>
                          <td className="py-2 pr-3">{c.advisor_name || <span className="text-graphite">—</span>}</td>
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
                      {(advisorsQ.data?.rows || []).filter(r => r.conversations > 0 || r.active).map((r) => (
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
              <div className="text-xs text-graphite mb-3">Auto-actualiza cada 15s</div>
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
