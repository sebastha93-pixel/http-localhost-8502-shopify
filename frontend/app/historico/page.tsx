"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatMoneyShort } from "@/lib/utils";
import { Search, X, PhoneCall, MessageCircle, FileText, CheckCircle, Truck, AlertCircle } from "lucide-react";

interface PedidoArchivo {
  orden: string;
  orden_melonn?: string;
  nombre_comprador?: string;
  telefono_comprador?: string;
  email_comprador?: string;
  ciudad_destino?: string;
  direccion?: string;
  zona?: string;
  tipo_recaudo?: string;
  valor_num?: number;
  producto?: string;
  transportadora?: string;
  carrier_real?: string;
  guia_real?: string;
  estado_final?: string;
  tuvo_novedad?: boolean;
  motivo_novedad?: string;
  fecha_creacion?: string;
  fecha_entrega?: string;
  dias_total?: number;
  archivado_en?: string;
}

interface ListResp { total: number; pedidos: PedidoArchivo[]; }
interface StatsResp { total: number; con_novedad: number; desde?: string; hasta?: string; }
interface Accion { id: number; tipo: string; nota: string; usuario: string; created_at: string; }
interface Nota { id: number; contenido: string; usuario: string; created_at: string; }

const ICONOS_ACCION: Record<string, React.ComponentType<{ className?: string }>> = {
  llamada: PhoneCall,
  whatsapp: MessageCircle,
  despacho_autorizado: CheckCircle,
  gestion_transportadora: Truck,
  novedad_marcada: AlertCircle,
  nota: FileText,
};

function PedidoDetalleHistorico({ p, onClose }: { p: PedidoArchivo; onClose: () => void }) {
  const acciones = useQuery<Accion[]>({
    queryKey: ["historico-acciones", p.orden],
    queryFn: () => api.get<Accion[]>(`/api/pedidos/${p.orden}/acciones`),
    staleTime: 60_000,
  });
  const notas = useQuery<Nota[]>({
    queryKey: ["historico-notas", p.orden],
    queryFn: () => api.get<Nota[]>(`/api/pedidos/${p.orden}/notas`),
    staleTime: 60_000,
  });

  // Mezclar acciones + notas por fecha, descendente
  const timeline = [
    ...(acciones.data || []).map((a) => ({ kind: "accion" as const, ...a })),
    ...(notas.data || []).map((n) => ({ kind: "nota" as const, ...n })),
  ].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));

  return (
    <div className="rounded-lg border border-border bg-white overflow-hidden">
      {/* Header */}
      <div className="bg-ink text-white px-5 py-3 flex items-center justify-between">
        <div>
          <p className="text-[0.65rem] uppercase tracking-wider text-white/60">Orden</p>
          <p className="text-base font-bold tabular-nums">#{p.orden} {p.orden_melonn ? <span className="text-white/50 font-normal">· Melonn {p.orden_melonn}</span> : null}</p>
        </div>
        <button onClick={onClose} className="text-white/60 hover:text-white">
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Body 2 columnas */}
      <div className="grid grid-cols-1 md:grid-cols-2 divide-x divide-border">
        {/* Izquierda: datos */}
        <div className="p-5 space-y-3">
          <Section label="Cliente">
            <p className="font-semibold text-ink">{p.nombre_comprador || "—"}</p>
            <p className="text-xs text-graphite tabular-nums">{p.telefono_comprador || "—"}</p>
            <p className="text-xs text-graphite">{p.email_comprador || "—"}</p>
          </Section>
          <Section label="Destino">
            <p className="text-sm text-ink">{p.ciudad_destino || "—"} {p.zona ? <span className="text-graphite">· {p.zona}</span> : null}</p>
            <p className="text-xs text-graphite">{p.direccion || "—"}</p>
          </Section>
          <Section label="Envío">
            <p className="text-sm text-ink">{p.transportadora || "—"}</p>
            {p.carrier_real && (
              <p className="text-xs text-graphite">{p.carrier_real} {p.guia_real ? <span className="tabular-nums">· {p.guia_real}</span> : null}</p>
            )}
          </Section>
          <div className="grid grid-cols-3 gap-3">
            <Section label="Tipo">
              <p className="text-sm font-medium text-ink">{p.tipo_recaudo || "—"}</p>
            </Section>
            <Section label="Valor">
              <p className="text-sm font-semibold text-navy">{p.valor_num ? formatMoneyShort(p.valor_num) : "—"}</p>
            </Section>
            <Section label="Días total">
              <p className="text-sm font-medium text-ink tabular-nums">{p.dias_total ?? "—"}d</p>
            </Section>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Section label="Creado">
              <p className="text-xs text-ink">{p.fecha_creacion || "—"}</p>
            </Section>
            <Section label="Entregado">
              <p className="text-xs text-ink">{p.fecha_entrega || p.archivado_en?.slice(0, 10) || "—"}</p>
            </Section>
          </div>
          {p.producto && (
            <Section label="Producto">
              <p className="text-xs text-ink">{p.producto}</p>
            </Section>
          )}
          {p.tuvo_novedad && (
            <div className="rounded-md bg-rust/5 border border-rust/20 px-3 py-2">
              <p className="text-[0.6rem] uppercase tracking-wider text-graphite mb-1">Tuvo novedad</p>
              <p className="text-sm font-semibold text-rust">{p.motivo_novedad || "Sí (sin motivo registrado)"}</p>
            </div>
          )}
        </div>

        {/* Derecha: timeline */}
        <div className="p-5">
          <p className="text-[0.6rem] uppercase tracking-wider text-graphite mb-3">Timeline de acciones</p>
          {(acciones.isLoading || notas.isLoading) && (
            <p className="text-xs text-graphite">Cargando timeline...</p>
          )}
          {!acciones.isLoading && !notas.isLoading && timeline.length === 0 && (
            <p className="text-xs text-graphite">Sin acciones ni notas registradas para este pedido.</p>
          )}
          <ol className="space-y-2.5">
            {timeline.map((t, i) => {
              if (t.kind === "accion") {
                const Icon = ICONOS_ACCION[t.tipo] || CheckCircle;
                return (
                  <li key={`a-${t.id}-${i}`} className="flex gap-2 text-xs">
                    <Icon className="h-3.5 w-3.5 mt-0.5 text-navy flex-none" />
                    <div className="flex-1">
                      <p className="text-ink"><span className="font-semibold">{t.tipo}</span>{t.nota ? <> · {t.nota}</> : null}</p>
                      <p className="text-graphite">{t.usuario} · {t.created_at?.slice(0, 16).replace("T", " ")}</p>
                    </div>
                  </li>
                );
              }
              return (
                <li key={`n-${t.id}-${i}`} className="flex gap-2 text-xs">
                  <FileText className="h-3.5 w-3.5 mt-0.5 text-graphite flex-none" />
                  <div className="flex-1">
                    <p className="text-ink">{t.contenido}</p>
                    <p className="text-graphite">{t.usuario} · {t.created_at?.slice(0, 16).replace("T", " ")}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[0.6rem] uppercase tracking-wider text-graphite mb-0.5">{label}</p>
      {children}
    </div>
  );
}

export default function HistoricoPage() {
  const [q, setQ] = useState("");
  const [seleccionado, setSeleccionado] = useState<PedidoArchivo | null>(null);

  const lista = useQuery<ListResp>({
    queryKey: ["historico", q],
    queryFn: () => api.get<ListResp>(`/api/historico/pedidos?q=${encodeURIComponent(q)}&limit=500`),
    staleTime: 30_000,
  });
  const stats = useQuery<StatsResp>({
    queryKey: ["historico-stats"],
    queryFn: () => api.get<StatsResp>("/api/historico/stats"),
    staleTime: 5 * 60_000,
  });

  if (lista.isLoading) return <LoadingState label="Cargando histórico..." />;
  if (lista.error) return <ErrorState error={lista.error} onRetry={() => lista.refetch()} />;

  const items = lista.data?.pedidos || [];
  const s = stats.data;

  return (
    <PageShell
      title="Histórico"
      subtitle="Pedidos entregados · últimos 3 meses · solo lectura"
      isFetching={lista.isFetching}
      onRefresh={() => { lista.refetch(); stats.refetch(); }}
    >
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard label="Total archivados" value={String(s?.total ?? items.length)} meta="Últimos 90 días" accent="navy" />
        <KpiCard label="Con novedad" value={String(s?.con_novedad ?? 0)} meta="Tuvieron incidencia" accent={s?.con_novedad ? "rust" : "steel"} />
        <KpiCard label="Desde" value={s?.desde || "—"} meta="Pedido más antiguo" accent="steel" />
        <KpiCard label="Hasta" value={s?.hasta || "—"} meta="Pedido más reciente" accent="steel" />
      </div>

      {/* Búsqueda */}
      <div className="relative flex-1 min-w-[240px]">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Buscar por nombre, teléfono, ciudad u orden..."
          className="w-full rounded-md border border-border bg-white pl-9 pr-3 py-2 text-sm text-ink placeholder:text-graphite/60 focus:outline-none focus:ring-2 focus:ring-steel"
        />
      </div>

      <p className="text-xs text-graphite">{items.length} pedidos archivados</p>

      {/* Detalle */}
      {seleccionado && (
        <PedidoDetalleHistorico p={seleccionado} onClose={() => setSeleccionado(null)} />
      )}

      {/* Tabla */}
      <Card>
        <CardContent className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-concrete/50 border-b border-border">
                <tr className="text-left text-[0.65rem] font-bold uppercase tracking-wider text-graphite">
                  <th className="px-3 py-2.5">Orden</th>
                  <th className="px-3 py-2.5">Cliente</th>
                  <th className="px-3 py-2.5">Ciudad</th>
                  <th className="px-3 py-2.5">Transportadora</th>
                  <th className="px-3 py-2.5 text-right">Valor</th>
                  <th className="px-3 py-2.5">Tipo</th>
                  <th className="px-3 py-2.5">Entregado</th>
                  <th className="px-3 py-2.5 text-right">Días</th>
                  <th className="px-3 py-2.5">Novedad</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.length === 0 ? (
                  <tr><td colSpan={9} className="px-3 py-8 text-center text-sm text-graphite">Sin resultados.</td></tr>
                ) : items.map((p) => (
                  <tr
                    key={p.orden}
                    onClick={() => setSeleccionado(p)}
                    className="hover:bg-concrete/30 cursor-pointer"
                  >
                    <td className="px-3 py-2.5 font-semibold text-ink tabular-nums">#{p.orden}</td>
                    <td className="px-3 py-2.5">
                      <p className="text-ink">{p.nombre_comprador || "—"}</p>
                      <p className="text-xs text-graphite tabular-nums">{p.telefono_comprador || ""}</p>
                    </td>
                    <td className="px-3 py-2.5 text-xs text-graphite">{p.ciudad_destino || "—"}</td>
                    <td className="px-3 py-2.5 text-xs text-graphite">{p.carrier_real || p.transportadora || "—"}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{p.valor_num ? formatMoneyShort(p.valor_num) : "—"}</td>
                    <td className="px-3 py-2.5 text-xs">{p.tipo_recaudo || "—"}</td>
                    <td className="px-3 py-2.5 text-xs text-graphite">{p.fecha_entrega || p.archivado_en?.slice(0, 10) || "—"}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{p.dias_total ?? "—"}</td>
                    <td className="px-3 py-2.5">
                      {p.tuvo_novedad ? <Badge tone="riesgo">Sí</Badge> : <Badge tone="normal">No</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </PageShell>
  );
}
