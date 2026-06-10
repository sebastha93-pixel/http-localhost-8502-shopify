"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney, formatMoneyShort, fmtDateTime } from "@/lib/utils";
import { Search } from "lucide-react";

interface PagoMP {
  mp_id: string;
  valor_bruto: number;
  comision: number;
  valor_neto: number;
  email: string;
  nombre_pagador: string;
  fecha_aprobado: string;
  estado: string;
  descripcion: string;
  external_reference: string;
}

interface PagosResponse {
  pagos: PagoMP[];
  total: number;
  valor_bruto_total: number;
  valor_neto_total: number;
  comision_total: number;
  desde: string;
  hasta: string;
}

export default function MercadoPagoPage() {
  const [dias, setDias] = useState(30);
  const [q, setQ] = useState("");

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["mp", "pagos", dias],
    queryFn: () => {
      const desde = new Date();
      desde.setDate(desde.getDate() - dias);
      const fechaDesde = desde.toISOString().slice(0, 10);
      return api.get<PagosResponse>(`/api/finanzas/mercadopago?desde=${fechaDesde}`);
    },
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    const term = q.trim().toLowerCase();
    if (!term) return data.pagos;
    return data.pagos.filter((p) =>
      p.nombre_pagador?.toLowerCase().includes(term) ||
      p.email?.toLowerCase().includes(term) ||
      p.descripcion?.toLowerCase().includes(term) ||
      p.external_reference?.toLowerCase().includes(term) ||
      p.mp_id?.includes(term),
    );
  }, [data, q]);

  if (isLoading) return <LoadingState label="Consultando MercadoPago..." />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <PageShell
      title="MercadoPago"
      subtitle={`Pagos aprobados · ${data.total} transacciones · ${data.desde} a ${data.hasta}`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      {/* KPIs */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard label="Transacciones" value={data.total}                                meta="Aprobadas"           accent="navy" />
        <KpiCard label="Valor bruto"   value={formatMoneyShort(data.valor_bruto_total)}  meta="Recaudo total"       accent="steel" />
        <KpiCard label="Valor neto"    value={formatMoneyShort(data.valor_neto_total)}   meta="Después de comisión" accent="teal" />
        <KpiCard label="Comisión MP"   value={formatMoneyShort(data.comision_total)}     meta={`${data.valor_bruto_total > 0 ? ((data.comision_total / data.valor_bruto_total) * 100).toFixed(2) : 0}% del bruto`} accent="khaki" />
      </div>

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[280px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar por pagador, email, descripción, MP ID..."
            className="w-full rounded-md border border-border bg-white pl-9 pr-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-graphite">
          <span className="font-semibold uppercase tracking-wider text-[0.6rem]">Periodo</span>
          <select
            value={dias}
            onChange={(e) => setDias(Number(e.target.value))}
            className="rounded-md border border-border bg-white px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
          >
            <option value={7}>Últimos 7 días</option>
            <option value={30}>Últimos 30 días</option>
            <option value={60}>Últimos 60 días</option>
            <option value={90}>Últimos 90 días</option>
          </select>
        </label>
      </div>

      <p className="text-xs text-graphite">
        Mostrando {filtered.length} de {data.total} pagos
      </p>

      {/* Tabla */}
      <Card>
        <CardContent className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-concrete/50 border-b border-border">
                <tr>
                  <Th>Fecha</Th>
                  <Th>Pagador</Th>
                  <Th>Email</Th>
                  <Th>Descripción</Th>
                  <Th>Ref.</Th>
                  <Th align="right">Bruto</Th>
                  <Th align="right">Comisión</Th>
                  <Th align="right">Neto</Th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-graphite">
                      Sin pagos en este periodo
                    </td>
                  </tr>
                ) : (
                  filtered.slice(0, 500).map((p) => (
                    <tr key={p.mp_id} className="border-b border-border hover:bg-concrete/30">
                      <Td className="text-xs tabular-nums">{p.fecha_aprobado}</Td>
                      <Td><span className="font-semibold text-ink">{p.nombre_pagador || "—"}</span></Td>
                      <Td className="text-xs text-graphite">{p.email || "—"}</Td>
                      <td className="px-3 py-2 text-left text-xs max-w-[200px] truncate" title={p.descripcion}>{p.descripcion || "—"}</td>
                      <Td className="text-[0.7rem] text-graphite tabular-nums">{p.external_reference || "—"}</Td>
                      <Td align="right" className="tabular-nums font-semibold">{formatMoney(p.valor_bruto)}</Td>
                      <Td align="right" className="tabular-nums text-rust">{formatMoney(p.comision)}</Td>
                      <Td align="right" className="tabular-nums text-teal font-semibold">{formatMoney(p.valor_neto)}</Td>
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
  return <th className={`px-3 py-2.5 text-[0.6rem] font-bold uppercase tracking-[0.15em] text-graphite ${cls}`}>{children}</th>;
}

function Td({
  children, align = "left", className = "",
}: { children: React.ReactNode; align?: "left" | "right"; className?: string }) {
  const cls = align === "right" ? "text-right" : "text-left";
  return <td className={`px-3 py-2 ${cls} ${className}`}>{children}</td>;
}
