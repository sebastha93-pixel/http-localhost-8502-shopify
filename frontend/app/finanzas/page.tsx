"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney, formatMoneyShort, fmtDateTime } from "@/lib/utils";

interface ResumenFinanzas {
  cod_total: number;
  cod_pendientes: number;
  cod_transito: number;
  cod_novedades: number;
  cod_entregados: number;
  n_cod_total: number;
  n_cod_pendientes: number;
  n_cod_transito: number;
  n_cod_novedades: number;
  n_cod_entregados: number;
  mp_total: number;
  mp_neto: number;
  mp_comisiones: number;
  n_mp: number;
  fuente: string;
  fetched_at: string;
}

export default function FinanzasPage() {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["finanzas", "resumen"],
    queryFn: () => api.get<ResumenFinanzas>("/api/finanzas/resumen"),
  });

  if (isLoading) return <LoadingState label="Cargando finanzas..." />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <PageShell
      title="Finanzas"
      subtitle={`Resumen financiero · sincronizado ${fmtDateTime(data.fetched_at)}`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      {/* Bloque COD */}
      <section>
        <p className="section-label mb-3">Portafolio Contraentrega</p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <KpiCard label="Total COD"     value={formatMoneyShort(data.cod_total)}      meta={`${data.n_cod_total} pedidos`}    accent="navy" />
          <KpiCard label="Pendientes"    value={formatMoneyShort(data.cod_pendientes)} meta={`${data.n_cod_pendientes} despacho`} accent="khaki" />
          <KpiCard label="En tránsito"   value={formatMoneyShort(data.cod_transito)}   meta={`${data.n_cod_transito} pedidos`}    accent="steel" />
          <KpiCard label="Novedades"     value={formatMoneyShort(data.cod_novedades)}  meta={`${data.n_cod_novedades} comprometidos`} accent={data.n_cod_novedades ? "rust" : "steel"} danger={data.n_cod_novedades > 0} />
          <KpiCard label="Entregados"    value={formatMoneyShort(data.cod_entregados)} meta={`${data.n_cod_entregados} cobrados`} accent="teal" />
        </div>
      </section>

      {/* Detalle COD */}
      <section>
        <p className="section-label mb-3">Detalle COD</p>
        <Card>
          <CardContent className="p-5">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-2 text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Estado</th>
                  <th className="text-right py-2 text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Pedidos</th>
                  <th className="text-right py-2 text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Valor COD</th>
                  <th className="text-right py-2 text-[0.6rem] font-bold uppercase tracking-wider text-graphite">% del total</th>
                </tr>
              </thead>
              <tbody>
                <DetailRow label="Pendientes despacho" n={data.n_cod_pendientes} v={data.cod_pendientes} total={data.cod_total} />
                <DetailRow label="En tránsito"         n={data.n_cod_transito}   v={data.cod_transito}   total={data.cod_total} />
                <DetailRow label="Con novedades"       n={data.n_cod_novedades}  v={data.cod_novedades}  total={data.cod_total} accent="rust" />
                <DetailRow label="Entregados"          n={data.n_cod_entregados} v={data.cod_entregados} total={data.cod_total} accent="teal" />
                <tr className="border-t-2 border-ink font-bold">
                  <td className="py-2 text-ink">Total portafolio</td>
                  <td className="text-right tabular-nums text-ink">{data.n_cod_total}</td>
                  <td className="text-right tabular-nums text-ink">{formatMoney(data.cod_total)}</td>
                  <td className="text-right tabular-nums text-ink">100%</td>
                </tr>
              </tbody>
            </table>
          </CardContent>
        </Card>
      </section>

      {/* MercadoPago */}
      <section>
        <p className="section-label mb-3">MercadoPago · últimos 30 días</p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <KpiCard label="Transacciones"    value={data.n_mp}                              meta="Pagos aprobados"      accent="navy" />
          <KpiCard label="Valor bruto"      value={formatMoneyShort(data.mp_total)}        meta="Recaudo total"        accent="steel" />
          <KpiCard label="Valor neto"       value={formatMoneyShort(data.mp_neto)}         meta="Después de comisión"  accent="teal" />
          <KpiCard label="Comisiones"       value={formatMoneyShort(data.mp_comisiones)}   meta="Cobrado por MP"       accent="khaki" />
        </div>
      </section>
    </PageShell>
  );
}

function DetailRow({
  label, n, v, total, accent,
}: {
  label: string; n: number; v: number; total: number; accent?: "rust" | "teal";
}) {
  const pct = total > 0 ? Math.round((v / total) * 100) : 0;
  const colorCls = accent === "rust" ? "text-rust" : accent === "teal" ? "text-teal" : "text-ink";
  return (
    <tr className="border-b border-border hover:bg-concrete/30">
      <td className={`py-2 ${colorCls}`}>{label}</td>
      <td className="text-right tabular-nums">{n}</td>
      <td className="text-right tabular-nums">{formatMoney(v)}</td>
      <td className="text-right tabular-nums text-graphite">{pct}%</td>
    </tr>
  );
}
