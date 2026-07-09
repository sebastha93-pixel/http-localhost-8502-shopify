"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiStrip } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatMoney, formatMoneyShort } from "@/lib/utils";
import { Search, AlertTriangle, CheckCircle, ExternalLink } from "lucide-react";

interface AddiStatus {
  ok: boolean;
  error?: string;
  base_url?: string;
  token_path?: string;
}

interface TxnAddi {
  addi_id: string;
  valor_bruto: number;
  estado: string;
  fecha: string;
  email_cliente: string;
  nombre_cliente: string;
  external_ref: string;
}

interface TxnAddiResponse {
  transacciones: TxnAddi[];
  total: number;
  valor_total: number;
  desde: string;
  hasta: string;
}

export default function AddiPage() {
  const statusQ = useQuery({
    queryKey: ["addi", "status"],
    queryFn: () => api.get<AddiStatus>("/api/finanzas/addi/status"),
    retry: false,
  });

  if (statusQ.isLoading) return <LoadingState label="Verificando conexión Addi…" />;

  if (!statusQ.data?.ok) {
    return (
      <PageShell title="Addi" subtitle="Configuración pendiente">
        <Card>
          <CardContent className="p-8">
            <div className="mb-4 flex items-start gap-3">
              <AlertTriangle className="h-6 w-6 text-terracotta flex-none mt-0.5" />
              <div>
                <p className="font-medium text-ink-900">No se pudo conectar con Addi.</p>
                <p className="mt-1 text-sm text-graphite">{statusQ.data?.error || "Error desconocido."}</p>
              </div>
            </div>

            <div className="mt-4 space-y-3 rounded-md bg-cloud/60 p-4 text-sm">
              <p className="font-medium text-ink-900">Para activar la integración:</p>
              <ol className="ml-1 list-decimal list-inside space-y-1.5 text-graphite">
                <li>En Railway → backend → Variables, agrega:
                  <pre className="mt-1 ml-4 rounded-sm bg-card p-2 text-xs font-mono">
{`ADDI_CLIENT_ID=tu_client_id
ADDI_CLIENT_SECRET=tu_client_secret`}
                  </pre>
                </li>
                <li>Si el endpoint difiere del default, también:
                  <pre className="mt-1 ml-4 rounded-sm bg-card p-2 text-xs font-mono">
{`ADDI_BASE_URL=https://api.addi.com
ADDI_TOKEN_PATH=/v1/oauth/token
ADDI_TRANSACTIONS_PATH=/v1/transactions`}
                  </pre>
                </li>
                <li>Espera que Railway redeploye y refresca esta página.</li>
              </ol>

              {statusQ.data?.base_url && (
                <div className="border-t border-border pt-2 text-[0.65rem] text-graphite">
                  <span className="font-medium">Endpoints probados:</span><br/>
                  base_url: <code className="font-mono">{statusQ.data.base_url}</code><br/>
                  token_path: <code className="font-mono">{statusQ.data.token_path}</code>
                </div>
              )}
            </div>

            <button
              onClick={() => statusQ.refetch()}
              className="mt-4 rounded-sm bg-navy-600 px-4 py-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-white transition-colors hover:bg-navy-700"
            >
              Reintentar
            </button>
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  return <AddiTransacciones />;
}

function AddiTransacciones() {
  const [dias, setDias] = useState(30);
  const [q, setQ] = useState("");

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["addi", "transacciones", dias],
    queryFn: () => {
      const desde = new Date();
      desde.setDate(desde.getDate() - dias);
      return api.get<TxnAddiResponse>(`/api/finanzas/addi?desde=${desde.toISOString().slice(0, 10)}`);
    },
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    const term = q.trim().toLowerCase();
    if (!term) return data.transacciones;
    return data.transacciones.filter((t) =>
      t.nombre_cliente?.toLowerCase().includes(term) ||
      t.email_cliente?.toLowerCase().includes(term) ||
      t.addi_id?.includes(term) ||
      t.external_ref?.toLowerCase().includes(term),
    );
  }, [data, q]);

  if (isLoading) return <LoadingState label="Consultando Addi…" />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <PageShell
      title="Addi"
      subtitle={`Transacciones · ${data.total} · ${data.desde} a ${data.hasta}`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      <div className="flex items-center gap-2">
        <CheckCircle className="h-4 w-4 text-sage" />
        <span className="text-xs font-medium text-sage">Conectado con Addi API</span>
      </div>

      <KpiStrip
        items={[
          { label: "Transacciones",   value: data.total },
          { label: "Valor total",     value: formatMoneyShort(data.valor_total) },
          { label: "Ticket promedio", value: formatMoneyShort(data.total > 0 ? data.valor_total / data.total : 0), tone: "success" },
        ]}
      />

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[280px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar (/) cliente, email, Addi ID o referencia"
            className="w-full rounded-sm border border-border bg-card pl-9 pr-3 py-2 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-graphite">
          <span className="text-[0.7rem] font-semibold uppercase tracking-[0.12em]">Periodo</span>
          <select
            value={dias}
            onChange={(e) => setDias(Number(e.target.value))}
            className="rounded-sm border border-border bg-card px-3 py-2 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
          >
            <option value={7}>Últimos 7 días</option>
            <option value={30}>Últimos 30 días</option>
            <option value={60}>Últimos 60 días</option>
            <option value={90}>Últimos 90 días</option>
          </select>
        </label>
      </div>

      <p className="text-xs text-graphite tabular-nums">{filtered.length} de {data.total} transacciones</p>

      {/* Tabla */}
      <Card>
        <CardContent className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-cloud/60 border-b border-border">
                <tr>
                  <Th>Fecha</Th>
                  <Th>Cliente</Th>
                  <Th>Email</Th>
                  <Th>Estado</Th>
                  <Th>Ref. pedido</Th>
                  <Th align="right">Valor</Th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={6} className="text-center py-12 text-graphite">Sin transacciones en este periodo.</td></tr>
                ) : (
                  filtered.slice(0, 500).map((t) => (
                    <tr key={t.addi_id} className="border-b border-border transition-colors hover:bg-cloud/50">
                      <td className="px-3 py-2 text-xs tabular-nums">{t.fecha}</td>
                      <td className="px-3 py-2 font-medium text-ink-900">{t.nombre_cliente || "—"}</td>
                      <td className="px-3 py-2 text-xs text-graphite">{t.email_cliente || "—"}</td>
                      <td className="px-3 py-2"><Badge tone={t.estado.toLowerCase().includes("approv") ? "normal" : "neutral"}>{t.estado || "—"}</Badge></td>
                      <td className="px-3 py-2 text-[0.7rem] text-graphite tabular-nums">{t.external_ref || "—"}</td>
                      <td className="px-3 py-2 text-right tabular-nums font-medium">{formatMoney(t.valor_bruto)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </PageShell>
  );
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  const cls = align === "right" ? "text-right" : "text-left";
  return <th className={`px-3 py-2.5 text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite ${cls}`}>{children}</th>;
}
