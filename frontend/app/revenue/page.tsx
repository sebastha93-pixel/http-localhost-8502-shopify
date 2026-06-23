"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiStrip } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { StatusBadge as ConvStatusBadge } from "@/components/status-badge";
import { ExternalLink, Search, X, Sparkles, Filter, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, AlertCircle } from "lucide-react";

interface DetailResp {
  conversation: any;
  lead: any;
  advisor: { name: string; email?: string } | null;
  messages: Array<{ message_id: string; sender_type: string; sender_name: string; message_text: string; sent_at: string }>;
  audit: any | null;
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
  msgs_customer?: number;
  msgs_advisor?: number;
  avg_response_min?: number | null;
  is_vip?: boolean;
}

interface AdvisorRow {
  advisor_id: string;
  name: string;
  email?: string;
  active: boolean;
  asignadas?: number;
  atendidas?: number;
  conversations: number;
  won: number;
  response_rate?: number | null;
  revenue_ganado?: number;
  ticket_promedio?: number | null;
  avg_response_min?: number | null;
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
  waba: "WhatsApp", whatsapp: "WhatsApp", whatsapp_business: "WhatsApp", wa_business: "WhatsApp", wa: "WhatsApp",
  instagram_business: "Instagram", instagram: "Instagram", instagram_dm: "Instagram", ig: "Instagram", dm: "Instagram",
  messenger: "Messenger", facebook: "Messenger", fb: "Messenger",
  tiktok: "TikTok", tt: "TikTok",
  unknown: "—",
};

function channelLabel(channel: string | null | undefined): string {
  if (!channel) return "—";
  return CHANNEL_LABEL[channel.toLowerCase()] || channel;
}

function fmtCop(n: any) {
  if (n == null) return "—";
  return `$${Number(n).toLocaleString("es-CO")}`;
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("es-CO", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return "—"; }
}

function fmtRelative(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  const min = Math.floor((Date.now() - d.getTime()) / 60000);
  if (min < 1) return "ahora";
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function ageInMin(s: string | null | undefined): number {
  if (!s) return 0;
  return Math.floor((Date.now() - new Date(s).getTime()) / 60000);
}

/** Mapa estado de venta o conversación → variante del badge nuevo. */
function SaleStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="text-graphite text-xs">—</span>;
  const map: Record<string, { tone: "normal" | "riesgo" | "critico" | "info"; label: string }> = {
    won:         { tone: "normal",  label: "Ganada" },
    lost:        { tone: "critico", label: "Perdida" },
    open:        { tone: "riesgo",  label: "Abierta" },
    in_progress: { tone: "info",    label: "En curso" },
    in_work:     { tone: "info",    label: "Activa" },
    closed:      { tone: "normal",  label: "Cerrada" },
  };
  const cfg = map[status.toLowerCase()] || { tone: "neutral" as any, label: status };
  return <Badge tone={cfg.tone as any}>{cfg.label}</Badge>;
}

// ============================================================================
// HERO — Fugas activas
// ============================================================================

interface FugaCard {
  conv: Conversation;
  esperandoMin: number;
  motivo: string;
}

function buildFugas(convs: Conversation[]): FugaCard[] {
  const HORA = 60;
  return convs
    .filter(c => {
      if (!c.last_message_at) return false;
      const min = ageInMin(c.last_message_at);
      if (min < 40) return false;
      // "Esperando" = sin respuesta de asesora ó cliente fue el último ó status activo
      const lowAdvisorMsgs = (c.msgs_advisor ?? 0) === 0;
      const isOpen = c.status?.toLowerCase() !== "closed";
      return isOpen && (lowAdvisorMsgs || min > 2 * HORA);
    })
    .sort((a, b) => ageInMin(b.last_message_at) - ageInMin(a.last_message_at))
    .slice(0, 4)
    .map(c => {
      const min = ageInMin(c.last_message_at);
      const motivos: string[] = [];
      if (!c.advisor_id) motivos.push("sin asignar");
      if ((c.msgs_advisor ?? 0) === 0) motivos.push("sin respuesta del equipo");
      else if ((c.avg_response_min ?? 0) > 30) motivos.push("respuesta lenta");
      if (min > 240) motivos.push("más de 4 horas");
      else if (min > 120) motivos.push("más de 2 horas");
      if (motivos.length === 0) motivos.push("conversación de alta intención");
      return { conv: c, esperandoMin: min, motivo: motivos.join(" · ") };
    });
}

function FugasHero({
  convs,
  loading,
  onSelect,
}: {
  convs: Conversation[];
  loading: boolean;
  onSelect: (id: string) => void;
}) {
  const fugas = buildFugas(convs);
  const totalRiesgo = fugas.reduce((acc, f) => acc + (f.conv.lead_value ?? 0), 0);

  return (
    <section
      className="stitch-top rounded-md border border-terracotta/30 bg-card overflow-hidden"
      aria-labelledby="fugas-heading"
    >
      <div className="flex flex-col gap-2 border-b border-border px-5 py-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="fugas-heading" className="font-display text-lg font-medium tracking-tight text-ink-900">
            Fugas activas
          </h2>
          <p className="text-xs text-graphite">
            Conversaciones de alta intención que llevan rato sin atención. Atiéndelas primero.
          </p>
        </div>
        <div className="text-right">
          <p className="text-[0.62rem] font-semibold uppercase tracking-[0.14em] text-graphite">
            Plata en riesgo ahora
          </p>
          <p className="font-display tabular text-xl font-medium leading-none text-terracotta">
            {totalRiesgo > 0 ? fmtCop(totalRiesgo) : <span className="text-graphite">—</span>}
          </p>
        </div>
      </div>

      <div className="p-5">
        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-32 rounded-md border border-border bg-cloud/40 shimmer" />
            ))}
          </div>
        ) : fugas.length === 0 ? (
          <p className="py-6 text-center text-sm text-graphite">
            Sin fugas activas en este momento. El equipo va al día.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {fugas.map(f => (
              <button
                key={f.conv.conversation_id}
                onClick={() => onSelect(f.conv.conversation_id)}
                className="group stitch-rail pl-3 text-left rounded-md border border-border bg-card p-3 transition-colors hover:bg-cloud focus:outline-none focus:ring-2 focus:ring-terracotta/40"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <p className="truncate font-medium text-sm text-ink-900">
                    {f.conv.is_vip && <span className="mr-1 text-ochre" aria-label="VIP">★</span>}
                    {f.conv.customer_name?.trim() || f.conv.customer_phone || `Lead #${f.conv.lead_id}`}
                  </p>
                  <span className="font-display tabular text-sm font-medium text-terracotta whitespace-nowrap">
                    +{f.esperandoMin}m
                  </span>
                </div>
                <p className="mt-0.5 text-[0.7rem] text-graphite">
                  {channelLabel(f.conv.channel)} · {f.conv.advisor_name || "Sin asignar"}
                </p>
                {f.conv.lead_value != null && f.conv.lead_value > 0 && (
                  <p className="mt-1 font-display tabular text-sm text-ink-900">
                    {fmtCop(f.conv.lead_value)}
                  </p>
                )}
                <p className="mt-1.5 line-clamp-2 text-[0.7rem] text-graphite">{f.motivo}</p>
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

// ============================================================================
// PANEL LATERAL de detalle (reemplaza modal)
// ============================================================================

function ConversationDetailPanel({
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

  // ESC para cerrar
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const d = detailQ.data;
  const audit = d?.audit;

  const fmtPhone = (raw: string | null | undefined) => {
    if (!raw) return null;
    const digits = raw.replace(/\D/g, "");
    if (digits.startsWith("57") && digits.length === 12) {
      return `+57 ${digits.slice(2, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`;
    }
    return raw;
  };
  const phoneDisplay = fmtPhone(d?.lead?.customer_phone);
  const displayName = d?.lead?.customer_name?.trim() || phoneDisplay || "Cliente";
  const initial = (d?.lead?.customer_name?.trim() || displayName).charAt(0).toUpperCase();

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end bg-ink-950/40 animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Detalle de conversación con ${displayName}`}
    >
      <div
        className="flex w-full max-w-2xl flex-col bg-card shadow-2xl animate-slide-in-right"
        onClick={(e) => e.stopPropagation()}
      >
        {/* HEADER */}
        <div className="flex items-center gap-3 border-b border-border bg-card px-5 py-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-sm bg-navy-600 font-display text-base font-medium text-white">
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium text-ink-900">
              {displayName}
              {d?.lead?.lead_value != null && d.lead.lead_value > 0 && (
                <span className="ml-2 font-display tabular text-sm text-ochre">
                  · {fmtCop(d.lead.lead_value)}
                </span>
              )}
            </p>
            <p className="truncate text-xs text-graphite">
              {channelLabel(d?.conversation?.channel)}
              {d?.advisor?.name ? ` · ${d.advisor.name}` : " · Sin asignar"}
              {phoneDisplay && ` · ${phoneDisplay}`}
            </p>
          </div>
          {d?.lead?.lead_id && (
            <a
              href={`https://drtjeans.kommo.com/leads/detail/${d.lead.lead_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-sm border border-border px-2.5 py-1 text-xs text-graphite transition-colors hover:bg-cloud hover:text-ink-900"
              title="Abrir lead en Kommo"
            >
              <ExternalLink className="h-3 w-3" /> Kommo
            </a>
          )}
          <button
            onClick={() => auditMut.mutate()}
            disabled={auditMut.isPending}
            className="inline-flex items-center gap-1 rounded-sm bg-navy-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-navy-700 disabled:opacity-50"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {auditMut.isPending ? "Auditando…" : audit ? "Re-auditar" : "Auditar IA"}
          </button>
          <button
            onClick={onClose}
            className="text-graphite hover:text-ink-900 transition-colors"
            aria-label="Cerrar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {detailQ.isLoading ? (
          <div className="p-5"><LoadingState /></div>
        ) : detailQ.isError ? (
          <div className="p-5"><ErrorState error={detailQ.error} /></div>
        ) : (
          <div className="flex-1 overflow-y-auto">
            {/* DIAGNÓSTICO IA */}
            {audit && (
              <section className="border-b border-border bg-cloud/40 px-5 py-4">
                <div className="flex items-center justify-between">
                  <p className="section-label">Diagnóstico IA</p>
                  <Badge tone={audit.result_classification === "venta_lograda" ? "normal" : audit.result_classification === "venta_perdida" ? "critico" : "riesgo"}>
                    {audit.result_classification?.replace("_", " ") || "—"}
                  </Badge>
                </div>
                <div className="mt-3 flex items-baseline gap-3">
                  <p className="font-display tabular text-3xl font-medium leading-none text-ink-900">
                    {audit.overall_score ?? "—"}<span className="text-base text-graphite">/10</span>
                  </p>
                  {audit.main_loss_reason && (
                    <p className="text-sm text-graphite">{audit.main_loss_reason}</p>
                  )}
                </div>
                {audit.ai_summary_internal && (
                  <p className="mt-2 text-sm text-ink-900">{audit.ai_summary_internal}</p>
                )}
                <div className="mt-3 grid grid-cols-4 gap-2 text-xs tabular">
                  {([
                    ["Respuesta", audit.response_time_score],
                    ["Atención",  audit.attention_score],
                    ["Follow-up", audit.follow_up_score],
                    ["Cierre",    audit.closing_score],
                  ] as const).map(([k, v]) => (
                    <div key={k} className="rounded-sm border border-border bg-card px-2 py-1.5">
                      <p className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite">{k}</p>
                      <p className="font-display text-sm font-medium text-ink-900">{v ?? "—"}</p>
                    </div>
                  ))}
                </div>
                {audit.lost_moment && (
                  <div className="mt-3 stitch-rail pl-3 rounded-sm bg-terracotta/[0.06] py-2 pr-3">
                    <p className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite">Momento crítico</p>
                    <p className="mt-0.5 text-sm italic text-ink-900">&ldquo;{audit.lost_moment}&rdquo;</p>
                    {audit.recommended_response && (
                      <>
                        <p className="mt-2 text-[0.62rem] uppercase tracking-[0.1em] text-graphite">Debió responder</p>
                        <p className="mt-0.5 text-sm italic text-sage">&ldquo;{audit.recommended_response}&rdquo;</p>
                      </>
                    )}
                  </div>
                )}
              </section>
            )}

            {/* CHAT */}
            <section className="px-5 py-4">
              <p className="section-label mb-3">Conversación</p>
              <div className="space-y-1">
                {(d?.messages || []).map((m, idx) => {
                  const isCustomer = m.sender_type === "customer";
                  const isSystem = m.sender_type === "system";
                  const prev = idx > 0 ? (d?.messages || [])[idx - 1] : null;
                  const sameAuthor = prev && prev.sender_type === m.sender_type;
                  if (isSystem) {
                    return (
                      <div key={m.message_id} className="my-2 flex justify-center">
                        <div className="rounded-sm bg-steel-300/20 px-3 py-1 text-xs text-graphite">
                          {m.message_text || "—"}
                        </div>
                      </div>
                    );
                  }
                  return (
                    <div key={m.message_id} className={`flex ${isCustomer ? "justify-start" : "justify-end"}`}>
                      <div
                        className={`max-w-[78%] px-3 py-2 text-sm ${
                          isCustomer
                            ? "bg-cloud text-ink-900 rounded-tr-md rounded-tl-md rounded-br-md"
                            : "bg-navy-600 text-white rounded-tl-md rounded-tr-md rounded-bl-md"
                        } ${sameAuthor ? "mt-0.5" : "mt-2"}`}
                      >
                        {!sameAuthor && !isCustomer && (
                          <p className="mb-0.5 text-[0.7rem] font-medium opacity-80">
                            {m.sender_name || "Asesora"}
                          </p>
                        )}
                        <p className="whitespace-pre-wrap break-words">
                          {m.message_text
                            ? m.message_text
                            : isCustomer
                              ? <em className="opacity-60">(sin contenido)</em>
                              : <em className="text-[0.75rem] opacity-70">✓ enviado · texto pendiente App Review</em>}
                        </p>
                        <p className="mt-0.5 text-right text-[0.65rem] opacity-60 tabular">
                          {new Date(m.sent_at).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", hour12: false })}
                        </p>
                      </div>
                    </div>
                  );
                })}
                {!d?.messages?.length && (
                  <p className="py-12 text-center text-sm text-graphite">
                    Sin mensajes capturados todavía en esta conversación.
                  </p>
                )}
              </div>
            </section>
          </div>
        )}

        {/* FOOTER */}
        <div className="border-t border-border bg-cloud/50 px-5 py-3">
          <button
            disabled
            title="Próximamente"
            className="w-full rounded-sm border border-border bg-card px-3 py-2 text-xs font-medium text-graphite"
          >
            Nota interna — enviar coaching
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// TENDENCIAS — embudo + por canal + por hora
// ============================================================================

function FunnelBar({ etiqueta, valor, pct }: { etiqueta: string; valor: number; pct: number }) {
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between">
        <p className="text-xs font-medium text-ink-900">{etiqueta}</p>
        <p className="font-display tabular text-sm font-medium text-ink-900">
          {valor.toLocaleString("es-CO")}
        </p>
      </div>
      <div className="h-2 rounded-full bg-cloud overflow-hidden">
        <div
          className="h-full bg-navy-600 transition-all duration-300"
          style={{ width: `${Math.max(2, pct)}%` }}
        />
      </div>
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

  // Funnel a partir de por_canal agregado
  const totales = (d?.por_canal || []).reduce(
    (acc: any, c: any) => ({
      total: acc.total + (c.total || 0),
      en_proceso: acc.en_proceso + (c.en_proceso || 0),
      won: acc.won + (c.won || 0),
      lost: acc.lost + (c.lost || 0),
    }),
    { total: 0, en_proceso: 0, won: 0, lost: 0 },
  );
  const conversaron = totales.en_proceso + totales.won + totales.lost;
  const conCotizacion = totales.won + totales.lost; // proxy: tuvo cierre o pérdida ⇒ hubo cotización
  const cierre = totales.won;

  const maxHora = Math.max(1, ...(d?.por_hora || []).map((h: any) => h.total));
  const maxDia  = Math.max(1, ...(d?.por_dia_semana || []).map((h: any) => h.total));
  const maxCanal = Math.max(1, ...(d?.por_canal || []).map((c: any) => c.total));

  return (
    <div className="space-y-5">
      {/* EMBUDO */}
      <Card>
        <CardContent className="p-5">
          <p className="section-label mb-4">Embudo de fuga</p>
          <div className="grid gap-4 md:grid-cols-4">
            <FunnelBar etiqueta="Leads"      valor={totales.total} pct={100} />
            <FunnelBar etiqueta="Conversó"   valor={conversaron}    pct={totales.total ? (conversaron / totales.total) * 100 : 0} />
            <FunnelBar etiqueta="Cotización" valor={conCotizacion}  pct={totales.total ? (conCotizacion / totales.total) * 100 : 0} />
            <FunnelBar etiqueta="Cierre"     valor={cierre}         pct={totales.total ? (cierre / totales.total) * 100 : 0} />
          </div>
          <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
            {[
              ["Leads → Conversó",     totales.total ? Math.round((1 - conversaron / totales.total) * 100) : 0],
              ["Conversó → Cotización", conversaron ? Math.round((1 - conCotizacion / conversaron) * 100) : 0],
              ["Cotización → Cierre",   conCotizacion ? Math.round((1 - cierre / conCotizacion) * 100) : 0],
            ].map(([label, pct]) => (
              <div key={label as string} className="rounded-sm border border-terracotta/25 bg-terracotta/[0.04] px-3 py-2">
                <p className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite">{label}</p>
                <p className="font-display tabular text-base font-medium text-terracotta">
                  {pct}% se fuga
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* POR CANAL */}
      <Card>
        <CardContent className="p-5">
          <p className="section-label mb-4">Fuga por canal</p>
          <div className="space-y-3">
            {(d?.por_canal || []).map((c: any) => {
              const fuga = c.total ? Math.round(((c.total - c.won) / c.total) * 100) : 0;
              return (
                <div key={c.canal} className="grid grid-cols-12 items-center gap-3 text-sm">
                  <p className="col-span-3 truncate font-medium text-ink-900">{channelLabel(c.canal)}</p>
                  <div className="col-span-7">
                    <div className="h-2 rounded-full bg-cloud overflow-hidden">
                      <div
                        className="h-full bg-terracotta transition-all"
                        style={{ width: `${(c.total / maxCanal) * 100}%` }}
                      />
                    </div>
                  </div>
                  <p className="col-span-2 text-right font-display tabular text-sm">
                    <span className="text-graphite">{c.total}</span>
                    <span className="ml-2 text-terracotta">{fuga}%</span>
                  </p>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* POR HORA */}
      <Card>
        <CardContent className="p-5">
          <p className="section-label mb-4">Fuga por franja horaria (Bogotá UTC-5)</p>
          <div className="flex h-32 items-end gap-1">
            {(d?.por_hora || []).map((h: any) => {
              const total = h.total;
              const pct = total > 0 ? (total / maxHora) * 100 : 0;
              const fugaPct = total ? ((total - h.won) / total) * 100 : 0;
              const isPico = fugaPct > 70 && total > 3;
              return (
                <div
                  key={h.hora}
                  className="flex flex-1 flex-col items-center"
                  title={`${h.hora}h · ${total} conversaciones · ${h.won} ganadas`}
                >
                  <div
                    className={`w-full rounded-sm ${isPico ? "bg-terracotta" : "bg-steel-400"}`}
                    style={{ height: `${pct}%`, minHeight: total ? "2px" : 0 }}
                  />
                  <p className="mt-1 text-[0.6rem] tabular text-graphite">{h.hora}</p>
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-xs text-graphite">
            Barras en terracotta = picos de fuga (más del 70 % no convierte). Atiende ese rango primero.
          </p>
        </CardContent>
      </Card>

      {/* POR DÍA */}
      <Card>
        <CardContent className="p-5">
          <p className="section-label mb-4">Por día de la semana</p>
          <div className="flex h-32 items-end gap-2">
            {(d?.por_dia_semana || []).map((dia: any) => {
              const pct = dia.total > 0 ? (dia.total / maxDia) * 100 : 0;
              return (
                <div key={dia.dia} className="flex flex-1 flex-col items-center">
                  <div
                    className="w-full rounded-sm bg-navy-600"
                    style={{ height: `${pct}%`, minHeight: dia.total ? "2px" : 0 }}
                  />
                  <p className="mt-1 text-xs">{dia.dia_label}</p>
                  <p className="text-[0.6rem] tabular text-graphite">
                    {dia.total} · {dia.conv_rate != null ? `${dia.conv_rate}%` : "—"}
                  </p>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ============================================================================
// ALERTAS
// ============================================================================

function AlertasTab({ onSelect }: { onSelect: (id: string) => void }) {
  const [umbral, setUmbral] = useState(30);
  const q = useQuery<any>({
    queryKey: ["revenue", "alertas", umbral],
    queryFn: () => api.get(`/api/revenue/alertas?sin_respuesta_min=${umbral}`),
    refetchInterval: 60_000,
  });
  return (
    <Card>
      <CardContent className="p-5">
        <div className="mb-4 flex items-center gap-3">
          <label className="text-xs text-graphite">Umbral sin respuesta</label>
          <select
            value={umbral}
            onChange={(e) => setUmbral(Number(e.target.value))}
            className="rounded-sm border border-border bg-card px-2 py-1 text-sm"
          >
            <option value={15}>15 min</option>
            <option value={30}>30 min</option>
            <option value={60}>1 hora</option>
            <option value={120}>2 horas</option>
            <option value={240}>4 horas</option>
          </select>
          <p className="ml-auto text-[0.62rem] uppercase tracking-[0.1em] text-graphite">
            Refresca cada 60 s
          </p>
        </div>
        {q.isLoading ? <LoadingState /> : q.isError ? <ErrorState error={q.error} /> : (
          <div className="space-y-2">
            {(q.data?.alertas || []).map((a: any) => (
              <button
                key={a.conversation_id}
                onClick={() => onSelect(a.conversation_id)}
                className="stitch-rail pl-3 block w-full rounded-sm border border-border bg-card p-3 text-left transition-colors hover:bg-cloud"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <p className="font-medium text-ink-900">
                    {a.customer_name || a.customer_phone || "—"}
                  </p>
                  <Badge tone="critico">{a.minutos_sin_respuesta}m sin respuesta</Badge>
                </div>
                <p className="mt-1 text-xs text-graphite">
                  {a.advisor_name || "Sin asignar"} · {channelLabel(a.channel)}
                </p>
                <p className="mt-2 text-sm italic text-ink-900">&ldquo;{a.ultimo_mensaje}&rdquo;</p>
              </button>
            ))}
            {!q.data?.alertas?.length && (
              <p className="py-8 text-center text-sm text-graphite">
                Nadie está esperando. El equipo va al día.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================================================
// COACHING IA
// ============================================================================

interface CasoProblema {
  conversation_id?: string;
  lead_id?: number;
  customer_name?: string | null;
  customer_phone?: string | null;
  lead_value?: number | null;
  result_classification?: string;
  kommo_status?: string | null;
  overall_score?: number | null;
  main_loss_reason?: string | null;
  lost_moment?: string | null;
  recommended_response?: string | null;
  economic_impact?: number | null;
  audit_date?: string | null;
  haiku_vs_kommo_mismatch?: boolean;
}

function CoachingTab({
  advisors, onSelect,
}: {
  advisors: AdvisorRow[];
  onSelect: (id: string) => void;
}) {
  const [selectedAdvisor, setSelectedAdvisor] = useState<string>("");
  const [days, setDays] = useState<number>(8);
  const q = useQuery<any>({
    queryKey: ["revenue", "coaching", selectedAdvisor, days],
    queryFn: () => api.get(`/api/revenue/coaching/${selectedAdvisor}?days_back=${days}`),
    enabled: !!selectedAdvisor,
  });
  return (
    <Card>
      <CardContent className="p-5">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label className="text-xs text-graphite">Asesora</label>
          <select
            value={selectedAdvisor}
            onChange={(e) => setSelectedAdvisor(e.target.value)}
            className="rounded-sm border border-border bg-card px-2 py-1 text-sm"
          >
            <option value="">— Selecciona —</option>
            {advisors.filter(a => a.conversations > 0).map(a => (
              <option key={a.advisor_id} value={a.advisor_id}>
                {a.name} ({a.conversations})
              </option>
            ))}
          </select>
          <span className="ml-2 text-[0.62rem] uppercase tracking-[0.14em] text-graphite">Ventana</span>
          <div className="inline-flex overflow-hidden rounded-sm border border-border bg-card">
            {[3, 8, 15, 30].map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  days === d ? "bg-ink-900 text-white" : "text-graphite hover:bg-cloud"
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>

        {!selectedAdvisor && (
          <p className="py-8 text-center text-sm text-graphite">
            Selecciona una asesora para generar coaching IA basado en sus auditorías.
          </p>
        )}
        {selectedAdvisor && q.isLoading && <LoadingState />}
        {selectedAdvisor && q.isError && <ErrorState error={q.error} />}
        {q.data && !q.data.ok && (
          <p className="py-8 text-center text-sm text-graphite">
            {q.data.error === "sin_auditorias" ? "Esta asesora aún no tiene auditorías." : `Error: ${q.data.error}`}
          </p>
        )}
        {q.data?.ok && (
          <div className="space-y-4">
            {/* Aviso: discrepancias Haiku vs Kommo (ground truth) */}
            {(q.data.stats?.n_mismatches_haiku_kommo ?? 0) > 0 && (
              <div className="rounded-sm border border-ochre/30 bg-ochre/[0.06] px-3 py-2 text-xs text-ink-900">
                <span className="font-medium text-ochre">
                  {q.data.stats.n_mismatches_haiku_kommo} discrepancia{q.data.stats.n_mismatches_haiku_kommo === 1 ? "" : "s"}
                </span>{" "}
                entre lo que dijo la IA y el estado real en Kommo. Los conteos de Ganadas / Perdidas usan Kommo como verdad.
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              {[
                ["Auditorías",       q.data.n_auditorias],
                ["Conversión",       `${q.data.stats.conversion_rate}%`],
                ["Ganadas",          q.data.stats.won, "sage"],
                ["Impacto perdido",  q.data.stats.impact_perdido_cop ? fmtCop(q.data.stats.impact_perdido_cop) : "—", "terracotta"],
                ["Overall",          `${q.data.stats.avg_overall ?? "—"}/10`],
              ].map((row, i) => {
                const [label, value, tone] = row as [string, any, string?];
                return (
                  <div key={i} className="rounded-sm border border-border bg-card px-3 py-2">
                    <p className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite">{label}</p>
                    <p className={`mt-1 font-display tabular text-base font-medium ${
                      tone === "sage" ? "text-sage" : tone === "terracotta" ? "text-terracotta" : "text-ink-900"
                    }`}>
                      {value}
                    </p>
                  </div>
                );
              })}
            </div>

            {q.data.coaching?.diagnostico_general && (
              <div className="rounded-sm bg-cloud/60 p-4">
                <p className="section-label mb-1">Diagnóstico</p>
                <p className="text-sm text-ink-900">{q.data.coaching.diagnostico_general}</p>
              </div>
            )}

            {q.data.coaching?.prioridad_urgente && (
              <div className="stitch-rail pl-3 rounded-sm bg-terracotta/[0.06] p-3">
                <p className="section-label mb-1">Prioridad esta semana</p>
                <p className="text-sm font-medium text-ink-900">{q.data.coaching.prioridad_urgente}</p>
              </div>
            )}

            <div className="grid gap-3 md:grid-cols-2">
              {q.data.coaching?.fortalezas?.length > 0 && (
                <div>
                  <p className="section-label mb-2 text-sage">Fortalezas</p>
                  <ul className="space-y-1 text-sm">
                    {q.data.coaching.fortalezas.map((s: string, i: number) => (
                      <li key={i} className="flex gap-2"><span className="text-sage">•</span>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
              {q.data.coaching?.areas_de_mejora?.length > 0 && (
                <div>
                  <p className="section-label mb-2 text-terracotta">Áreas de mejora</p>
                  <ul className="space-y-1 text-sm">
                    {q.data.coaching.areas_de_mejora.map((s: string, i: number) => (
                      <li key={i} className="flex gap-2"><span className="text-terracotta">•</span>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {q.data.coaching?.plan_accion_30_dias?.length > 0 && (
              <div>
                <p className="section-label mb-2">Plan 30 días</p>
                <div className="grid gap-2 md:grid-cols-2">
                  {q.data.coaching.plan_accion_30_dias.map((s: any, i: number) => (
                    <div key={i} className="rounded-sm border border-border bg-card p-3">
                      <p className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite">Semana {s.semana}</p>
                      <p className="mt-0.5 text-sm font-medium text-ink-900">{s.objetivo}</p>
                      <p className="mt-1 text-xs text-graphite">{s.ejercicio}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* CASOS DONDE FALLASTE — feedback accionable con snippets reales */}
            {q.data.casos_problema?.length > 0 && (
              <div>
                <div className="mb-3 flex items-baseline justify-between">
                  <p className="section-label">Casos donde fallaste — feedback accionable</p>
                  <p className="text-[0.65rem] text-graphite">
                    {q.data.casos_problema.length} {q.data.casos_problema.length === 1 ? "caso" : "casos"} · click para ver conversación
                  </p>
                </div>
                <div className="space-y-3">
                  {q.data.casos_problema.map((c: CasoProblema, i: number) => (
                    <CasoProblemaCard key={c.conversation_id || i} c={c} onOpen={onSelect} />
                  ))}
                </div>
              </div>
            )}

            <p className="border-t border-border pt-2 text-[0.62rem] uppercase tracking-[0.1em] text-graphite">
              {q.data.modelo} · costo {q.data.costo_usd ? `$${q.data.costo_usd.toFixed(4)}` : "—"} USD
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CasoProblemaCard({
  c, onOpen,
}: {
  c: CasoProblema;
  onOpen: (id: string) => void;
}) {
  const isLost = c.result_classification === "venta_perdida";
  const isWon  = c.result_classification === "venta_lograda";
  const score = c.overall_score ?? null;
  const scoreColor =
    score === null ? "text-graphite" :
    score >= 7 ? "text-sage" :
    score >= 5 ? "text-ochre" :
                 "text-terracotta";
  const clienteLabel =
    c.customer_name?.trim() || c.customer_phone || (c.lead_id ? `Lead #${c.lead_id}` : "Cliente sin nombre");

  return (
    <article className="rounded-md border border-border bg-card overflow-hidden">
      {/* Header del caso */}
      <header className="flex flex-wrap items-baseline gap-3 border-b border-border bg-cloud/40 px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-ink-900">
            {clienteLabel}
            {c.lead_value != null && c.lead_value > 0 && (
              <span className="ml-2 font-display tabular text-sm text-ochre">
                · {fmtCop(c.lead_value)}
              </span>
            )}
          </p>
          <p className="text-[0.7rem] text-graphite">
            {c.main_loss_reason || "Sin motivo registrado"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {score !== null && (
            <span className={`font-display tabular text-base font-medium ${scoreColor}`}>
              {score}<span className="text-xs text-graphite">/10</span>
            </span>
          )}
          {isLost && <Badge tone="critico">Perdida</Badge>}
          {isWon  && <Badge tone="normal">Ganada</Badge>}
          {!isLost && !isWon && c.result_classification && (
            <Badge tone="riesgo">{c.result_classification.replace("_", " ")}</Badge>
          )}
          {c.haiku_vs_kommo_mismatch && (
            <span title="La IA y Kommo discreparon. Usamos Kommo como verdad." className="text-[0.65rem] text-ochre">⚠ IA discrepó</span>
          )}
        </div>
      </header>

      {/* Body: snippet del momento + recomendación */}
      <div className="space-y-3 px-4 py-3">
        {c.lost_moment && (
          <div className="stitch-rail pl-3 rounded-sm bg-terracotta/[0.05] py-2 pr-3">
            <p className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite">
              Momento crítico — qué se dijo
            </p>
            <p className="mt-0.5 text-sm italic text-ink-900">&ldquo;{c.lost_moment}&rdquo;</p>
          </div>
        )}
        {c.recommended_response && (
          <div className="rounded-sm bg-sage/[0.06] border-l-2 border-l-sage px-3 py-2">
            <p className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite">
              Qué debió responder
            </p>
            <p className="mt-0.5 text-sm italic text-sage">&ldquo;{c.recommended_response}&rdquo;</p>
          </div>
        )}
        {!c.lost_moment && !c.recommended_response && (
          <p className="text-xs italic text-graphite">
            La auditoría no capturó snippet de este caso. Abre la conversación completa para revisar.
          </p>
        )}
      </div>

      {/* Footer: link a conversación */}
      {c.conversation_id && (
        <footer className="border-t border-border bg-card px-4 py-2">
          <button
            onClick={() => onOpen(c.conversation_id!)}
            className="inline-flex items-center gap-1 text-xs font-medium text-navy-600 transition-colors hover:text-navy-700"
          >
            Ver conversación completa →
          </button>
          {c.economic_impact != null && c.economic_impact > 0 && (
            <span className="ml-3 text-[0.7rem] text-graphite tabular">
              Impacto estimado <span className="font-medium text-terracotta">{fmtCop(c.economic_impact)}</span>
            </span>
          )}
        </footer>
      )}
    </article>
  );
}

// ============================================================================
// CALCULAR RANKINGS BUTTON
// ============================================================================

function CalcularRankingsBtn({ daysBack }: { daysBack: number }) {
  const qc = useQueryClient();
  const [last, setLast] = useState<{ ts: string; ok: number; total: number } | null>(null);
  const mut = useMutation({
    mutationFn: () => api.post<{ ok: boolean; persistidos: number; total_advisors: number }>(
      `/api/revenue/rankings/calcular?days_back=${daysBack}`,
    ),
    onSuccess: (data) => {
      setLast({ ts: new Date().toLocaleTimeString("es-CO"), ok: data.persistidos, total: data.total_advisors });
      qc.invalidateQueries({ queryKey: ["revenue", "advisors"] });
    },
  });
  return (
    <div className="mb-4 flex items-center gap-3 border-b border-border pb-3">
      <button
        onClick={() => mut.mutate()}
        disabled={mut.isPending}
        className="rounded-sm border border-border bg-card px-3 py-1.5 text-xs font-medium text-ink-900 transition-colors hover:bg-cloud disabled:opacity-50"
      >
        {mut.isPending ? "Calculando…" : "Persistir snapshot"}
      </button>
      {last && (
        <p className="text-xs text-graphite">
          {last.ts} · {last.ok}/{last.total} asesoras guardadas en histórico
        </p>
      )}
      {mut.isError && <p className="text-xs text-terracotta">Error: {String(mut.error)}</p>}
    </div>
  );
}

// ============================================================================
// PÁGINA
// ============================================================================

export default function RevenuePage() {
  const [daysBack, setDaysBack] = useState(1);
  const [advisorFilter, setAdvisorFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [channelFilter, setChannelFilter] = useState<string>("");
  const [selectedConv, setSelectedConv] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>("conversaciones");
  const [convSearch, setConvSearch] = useState<string>("");
  const [convSearchInput, setConvSearchInput] = useState<string>("");
  const [convPage, setConvPage] = useState<number>(1);
  const [replyFilter, setReplyFilter] = useState<string>("");
  const [onlyUnassigned, setOnlyUnassigned] = useState<boolean>(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // "/" atajo para enfocar buscador
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const statsQ = useQuery<StatsResp>({
    queryKey: ["revenue", "stats"],
    queryFn: () => api.get("/api/revenue/stats"),
    refetchInterval: 2 * 60_000,
  });

  const convsQ = useQuery<{
    conversations: Conversation[];
    total: number;
    page: number;
    page_size: number;
    pages: number;
  }>({
    queryKey: ["revenue", "conversations", daysBack, advisorFilter, statusFilter, channelFilter, convSearch, replyFilter, convPage],
    enabled: activeTab === "conversaciones",
    queryFn: () => {
      const params = new URLSearchParams({
        days_back: String(daysBack),
        page: String(convPage),
        page_size: "50",
      });
      if (advisorFilter) params.set("advisor_id", advisorFilter);
      if (statusFilter) params.set("status", statusFilter);
      if (channelFilter) params.set("channel", channelFilter);
      if (convSearch.trim()) params.set("search", convSearch.trim());
      if (replyFilter) params.set("reply_filter", replyFilter);
      return api.get(`/api/revenue/conversations?${params.toString()}`);
    },
  });

  // Query separada para el hero — siempre pendientes top 4, no depende de filtros visibles
  const fugasQ = useQuery<{ conversations: Conversation[] }>({
    queryKey: ["revenue", "fugas", daysBack],
    queryFn: () => api.get(`/api/revenue/conversations?days_back=${daysBack}&reply_filter=pending&page=1&page_size=25`),
    refetchInterval: 60_000,
  });

  const advisorsQ = useQuery<{ rows: AdvisorRow[]; total: number }>({
    queryKey: ["revenue", "advisors", "ranking", daysBack],
    queryFn: () => api.get(`/api/revenue/advisors/ranking?days_back=${daysBack}`),
    enabled: activeTab === "asesoras" || activeTab === "conversaciones" || activeTab === "coaching",
  });

  const msgsQ = useQuery<{ messages: MessageRow[]; total: number }>({
    queryKey: ["revenue", "messages", "recent"],
    queryFn: () => api.get("/api/revenue/messages/recent?limit=100"),
    enabled: activeTab === "mensajes",
    refetchInterval: 60_000,
  });

  const msgsStatsQ = useQuery<any>({
    queryKey: ["revenue", "messages", "stats", daysBack],
    queryFn: () => api.get(`/api/revenue/messages/stats?days_back=${Math.min(daysBack, 30)}`),
    refetchInterval: 60_000,
  });

  const stats = statsQ.data;

  return (
    <PageShell
      title="Revenue Intelligence"
      subtitle="Auditoría comercial: conversaciones, equipo, conversión"
      isFetching={statsQ.isFetching}
    >
      {/* HERO — Fugas activas */}
      <FugasHero
        convs={fugasQ.data?.conversations || []}
        loading={fugasQ.isLoading}
        onSelect={setSelectedConv}
      />

      {/* KPI STRIP */}
      <KpiStrip
        items={[
          { label: "Asesoras en línea", value: statsQ.isLoading ? "…" : (stats?.advisors ?? 0) },
          { label: "Leads",             value: statsQ.isLoading ? "…" : (stats?.leads ?? 0).toLocaleString("es-CO") },
          { label: "Conversaciones",    value: statsQ.isLoading ? "…" : (stats?.conversations ?? 0).toLocaleString("es-CO") },
          { label: `Mensajes ${daysBack === 1 ? "hoy" : daysBack === 2 ? "48h" : `${daysBack}d`}`,
            value: msgsStatsQ.isLoading ? "…" : (msgsStatsQ.data?.total_mensajes ?? 0).toLocaleString("es-CO") },
          { label: "Mensajes (total)",  value: statsQ.isLoading ? "…" : (stats?.messages ?? 0).toLocaleString("es-CO") },
          { label: "Por auditar",       value: statsQ.isLoading ? "…" : (stats?.pending_audits ?? 0).toLocaleString("es-CO"),
            tone: (stats?.pending_audits ?? 0) > 10 ? "danger" : "default" },
        ]}
      />

      {/* SELECTOR DE PERÍODO */}
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-[0.62rem] uppercase tracking-[0.14em] text-graphite">Periodo</label>
        <div className="inline-flex rounded-sm border border-border bg-card overflow-hidden">
          {[
            [1,   "Hoy"],
            [2,   "48h"],
            [7,   "7d"],
            [30,  "30d"],
            [90,  "90d"],
            [365, "1 año"],
          ].map(([v, l]) => {
            const active = daysBack === (v as number);
            return (
              <button
                key={v as number}
                onClick={() => setDaysBack(v as number)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  active ? "bg-ink-900 text-white" : "text-graphite hover:bg-cloud"
                }`}
              >
                {l}
              </button>
            );
          })}
        </div>
      </div>

      {/* TABS */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="conversaciones">Conversaciones</TabsTrigger>
          <TabsTrigger value="asesoras">Ranking del equipo</TabsTrigger>
          <TabsTrigger value="mensajes">Mensajes recientes</TabsTrigger>
          <TabsTrigger value="tendencias">Tendencias</TabsTrigger>
          <TabsTrigger value="alertas">Alertas</TabsTrigger>
          <TabsTrigger value="coaching">Coaching IA</TabsTrigger>
        </TabsList>

        {/* === Conversaciones === */}
        <TabsContent value="conversaciones">
          <Card>
            <CardContent className="p-5">
              {/* Sub-tabs */}
              <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-border">
                {[
                  { val: "pending",  label: "Esperando respuesta" },
                  { val: "attended", label: "Atendidas" },
                  { val: "",         label: "Todas" },
                ].map(t => (
                  <button
                    key={t.val}
                    onClick={() => { setReplyFilter(t.val); setConvPage(1); }}
                    className={`relative px-3 py-2 text-sm font-medium transition-colors ${
                      replyFilter === t.val
                        ? "tab-active text-ink-900"
                        : "text-graphite hover:text-ink-900"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
                <button
                  onClick={() => { setOnlyUnassigned(!onlyUnassigned); setConvPage(1); }}
                  className={`ml-auto inline-flex items-center gap-1.5 rounded-sm border px-3 py-1.5 text-xs font-medium transition-colors ${
                    onlyUnassigned
                      ? "border-terracotta/40 bg-terracotta/10 text-terracotta"
                      : "border-border text-graphite hover:bg-cloud"
                  }`}
                  title="Mostrar solo conversaciones sin asesora asignada"
                >
                  <AlertCircle className="h-3.5 w-3.5" /> Sin asignar
                </button>
              </div>

              {/* Filtros + buscador */}
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-graphite" />
                  <input
                    ref={searchRef}
                    type="text"
                    value={convSearchInput}
                    onChange={(e) => setConvSearchInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") { setConvSearch(convSearchInput); setConvPage(1); }
                    }}
                    placeholder="Buscar (/) cliente, teléfono o lead"
                    className="w-72 rounded-sm border border-border bg-card pl-8 pr-3 py-1.5 text-sm placeholder:text-graphite/60 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
                  />
                </div>
                {convSearch && (
                  <button
                    onClick={() => { setConvSearchInput(""); setConvSearch(""); setConvPage(1); }}
                    className="text-xs text-graphite underline-offset-2 hover:underline"
                  >
                    Limpiar
                  </button>
                )}
                <select
                  value={statusFilter}
                  onChange={(e) => { setStatusFilter(e.target.value); setConvPage(1); }}
                  className="rounded-sm border border-border bg-card px-2 py-1 text-sm"
                >
                  <option value="">Todos los estados</option>
                  <option value="in_work">Activas</option>
                  <option value="closed">Cerradas</option>
                </select>
                <select
                  value={channelFilter}
                  onChange={(e) => { setChannelFilter(e.target.value); setConvPage(1); }}
                  className="rounded-sm border border-border bg-card px-2 py-1 text-sm"
                >
                  <option value="">Todos los canales</option>
                  <option value="waba">WhatsApp</option>
                  <option value="instagram_business">Instagram</option>
                </select>
                {advisorsQ.data && (
                  <select
                    value={advisorFilter}
                    onChange={(e) => { setAdvisorFilter(e.target.value); setConvPage(1); }}
                    className="rounded-sm border border-border bg-card px-2 py-1 text-sm"
                  >
                    <option value="">Todas las asesoras</option>
                    {advisorsQ.data.rows.map((a) => (
                      <option key={a.advisor_id} value={a.advisor_id}>{a.name}</option>
                    ))}
                  </select>
                )}
                <p className="ml-auto text-xs text-graphite tabular">
                  {convsQ.data
                    ? `${convsQ.data.total} ${convsQ.data.total === 1 ? "resultado" : "resultados"}${convsQ.data.pages > 1 ? ` · pág. ${convsQ.data.page}/${convsQ.data.pages}` : ""}`
                    : ""}
                </p>
              </div>

              {/* Tabla */}
              {convsQ.isLoading ? <LoadingState /> : convsQ.isError ? <ErrorState error={convsQ.error} /> : (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left">
                        {["Cliente", "Canal", "Asesora", "Estado", "Mensajes", "Última actividad", "Score IA"].map(h => (
                          <th key={h} className="py-2 pr-3 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(convsQ.data?.conversations || [])
                        .filter(c => !onlyUnassigned || !c.advisor_id)
                        .sort((a, b) => {
                          if (replyFilter === "pending") {
                            const ta = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
                            const tb = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
                            return ta - tb;
                          }
                          return 0;
                        })
                        .map((c) => {
                          const min = ageInMin(c.last_message_at);
                          const isPending = replyFilter === "pending";
                          const overdue = isPending && min > 40;
                          // Pseudo-score: solo lo mostramos si hay audit; aquí derivamos urgencia visual
                          return (
                            <tr
                              key={c.conversation_id}
                              className="border-b border-border cursor-pointer transition-colors hover:bg-cloud/50"
                              onClick={() => setSelectedConv(c.conversation_id)}
                            >
                              <td className="py-2.5 pr-3">
                                <div className="flex items-center gap-1.5 font-medium text-ink-900">
                                  {c.is_vip && <span className="text-ochre" title="Cliente VIP">★</span>}
                                  <span className="truncate">
                                    {c.customer_name?.trim() || c.customer_phone || (
                                      <span className="italic text-graphite">Lead #{c.lead_id}</span>
                                    )}
                                  </span>
                                </div>
                                {c.customer_name?.trim() && c.customer_phone && (
                                  <p className="text-[0.7rem] text-graphite tabular">{c.customer_phone}</p>
                                )}
                              </td>
                              <td className="py-2.5 pr-3 text-sm text-graphite">
                                {channelLabel(c.channel)}
                              </td>
                              <td className="py-2.5 pr-3 text-sm">
                                {c.advisor_name || (
                                  <span className="font-medium text-terracotta">Sin asignar</span>
                                )}
                              </td>
                              <td className="py-2.5 pr-3">
                                <ConvStatusBadge
                                  status={!c.advisor_id ? "unassigned" : isPending && overdue ? "wait" : (c.msgs_advisor ?? 0) > 0 ? "done" : "wait"}
                                />
                              </td>
                              <td className="py-2.5 pr-3 text-xs tabular whitespace-nowrap">
                                <span className="text-graphite">{c.msgs_customer ?? 0}</span>
                                <span className="mx-1 text-border">/</span>
                                <span className="text-ink-900">{c.msgs_advisor ?? 0}</span>
                              </td>
                              <td className="py-2.5 pr-3 text-sm whitespace-nowrap">
                                <span className={overdue ? "font-medium text-terracotta tabular" : "text-graphite tabular"}>
                                  {fmtRelative(c.last_message_at)}
                                </span>
                              </td>
                              <td className="py-2.5 pr-3 text-sm tabular">
                                {c.avg_response_min != null ? (
                                  <span className={
                                    c.avg_response_min < 5  ? "text-sage" :
                                    c.avg_response_min < 30 ? "text-ochre" :
                                                              "text-terracotta"
                                  }>
                                    {c.avg_response_min}m
                                  </span>
                                ) : (
                                  <span className="text-graphite">—</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                  {!convsQ.data?.conversations?.length && (
                    <p className="py-8 text-center text-sm text-graphite">
                      Sin conversaciones en este rango. Cambia el período o limpia los filtros.
                    </p>
                  )}
                </div>
              )}

              {/* Paginación */}
              {convsQ.data && convsQ.data.pages > 1 && (
                <div className="mt-4 flex items-center justify-center gap-1">
                  <button
                    onClick={() => setConvPage(1)}
                    disabled={convPage === 1}
                    className="rounded-sm border border-border p-1.5 text-graphite disabled:opacity-30 hover:bg-cloud"
                  >
                    <ChevronsLeft className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setConvPage(Math.max(1, convPage - 1))}
                    disabled={convPage === 1}
                    className="rounded-sm border border-border p-1.5 text-graphite disabled:opacity-30 hover:bg-cloud"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <span className="px-3 text-xs tabular text-graphite">
                    Página <strong className="text-ink-900">{convsQ.data.page}</strong> de <strong className="text-ink-900">{convsQ.data.pages}</strong>
                  </span>
                  <button
                    onClick={() => setConvPage(Math.min(convsQ.data!.pages, convPage + 1))}
                    disabled={convPage >= convsQ.data.pages}
                    className="rounded-sm border border-border p-1.5 text-graphite disabled:opacity-30 hover:bg-cloud"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setConvPage(convsQ.data!.pages)}
                    disabled={convPage >= convsQ.data.pages}
                    className="rounded-sm border border-border p-1.5 text-graphite disabled:opacity-30 hover:bg-cloud"
                  >
                    <ChevronsRight className="h-4 w-4" />
                  </button>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* === Ranking del equipo === */}
        <TabsContent value="asesoras">
          <Card>
            <CardContent className="p-5">
              <CalcularRankingsBtn daysBack={daysBack} />
              {advisorsQ.isLoading ? <LoadingState /> : advisorsQ.isError ? <ErrorState error={advisorsQ.error} /> : (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left">
                        {["#", "Asesora", "Asignadas", "Atendidas", "% Resp.", "Ganadas", "Perdidas", "% Conv.", "Ticket prom.", "Tiempo resp.", "Último activo"].map(h => (
                          <th key={h} className="py-2 pr-3 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(advisorsQ.data?.rows || []).map((r, i) => (
                        <tr key={r.advisor_id} className={`border-b border-border ${i === 0 ? "bg-ochre/[0.04]" : ""}`}>
                          <td className={`py-2.5 pr-3 pl-3 font-display tabular text-base text-ink-900 ${i === 0 ? "border-l-2 border-l-selvedge text-ochre font-medium" : ""}`}>
                            {i + 1}
                          </td>
                          <td className="py-2.5 pr-3 text-left align-middle">
                            <p className="font-medium text-ink-900">{r.name}</p>
                            <p className="text-[0.7rem] text-graphite">{r.email}</p>
                          </td>
                          <td className="py-2.5 pr-3 tabular">{r.asignadas ?? r.conversations}</td>
                          <td className="py-2.5 pr-3 tabular">{r.atendidas ?? 0}</td>
                          <td className="py-2.5 pr-3 tabular font-medium">{r.response_rate != null ? `${r.response_rate}%` : "—"}</td>
                          <td className="py-2.5 pr-3 tabular text-sage">{r.won}</td>
                          <td className="py-2.5 pr-3 tabular text-terracotta">{r.lost}</td>
                          <td className="py-2.5 pr-3 tabular font-medium">{r.conversion_rate != null ? `${r.conversion_rate}%` : "—"}</td>
                          <td className="py-2.5 pr-3 tabular whitespace-nowrap">
                            {r.ticket_promedio ? `$${Math.round(r.ticket_promedio / 1000)}K` : "—"}
                          </td>
                          <td className="py-2.5 pr-3 tabular whitespace-nowrap">
                            {r.avg_response_min != null
                              ? r.avg_response_min < 60
                                ? `${r.avg_response_min}m`
                                : `${(r.avg_response_min / 60).toFixed(1)}h`
                              : "—"}
                          </td>
                          <td className="py-2.5 pr-3 tabular whitespace-nowrap text-graphite">
                            {fmtRelative(r.last_activity)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* === Mensajes recientes === */}
        <TabsContent value="mensajes">
          <Card>
            <CardContent className="p-5">
              <p className="mb-3 text-[0.62rem] uppercase tracking-[0.1em] text-graphite">Refresca cada 60 s</p>
              {msgsQ.isLoading ? <LoadingState /> : msgsQ.isError ? <ErrorState error={msgsQ.error} /> : (
                <div className="space-y-1">
                  {(msgsQ.data?.messages || []).map((m) => (
                    <button
                      key={m.message_id}
                      onClick={() => setSelectedConv(m.conversation_id)}
                      className={`block w-full border-l-2 pl-3 py-1.5 pr-2 text-left transition-colors hover:bg-cloud/50 ${
                        m.sender_type === "customer" ? "border-navy-600" :
                        m.sender_type === "advisor"  ? "border-sage"     :
                                                       "border-graphite"
                      }`}
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <p className="text-xs text-graphite">
                          <span className="font-medium text-ink-900">
                            {m.sender_name || m.customer_name || "—"}
                          </span>
                          {m.customer_phone && <span className="ml-2 tabular">{m.customer_phone}</span>}
                        </p>
                        <p className="whitespace-nowrap text-[0.7rem] text-graphite tabular">{fmtDate(m.sent_at)}</p>
                      </div>
                      <p className="mt-0.5 text-sm text-ink-900">
                        {m.message_text || <em className="text-graphite">(sin texto)</em>}
                      </p>
                    </button>
                  ))}
                  {!msgsQ.data?.messages?.length && (
                    <p className="py-8 text-center text-sm text-graphite">Aún no hay mensajes capturados.</p>
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
          <CoachingTab advisors={advisorsQ.data?.rows || []} onSelect={setSelectedConv} />
        </TabsContent>
      </Tabs>

      {selectedConv && (
        <ConversationDetailPanel
          conversationId={selectedConv}
          onClose={() => setSelectedConv(null)}
        />
      )}
    </PageShell>
  );
}
