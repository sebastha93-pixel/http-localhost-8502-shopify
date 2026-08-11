"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiStrip } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney, formatMoneyShort, fmtDateTime } from "@/lib/utils";
import { ConciliacionBancaria } from "@/components/conciliacion-bancaria";
import { CarteraCod } from "@/components/cartera-cod";

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
  // Cartera real cruzada contra Siigo. `cod_entregados` es el BRUTO entregado y
  // solo crece; esto es lo que Melonn efectivamente debe.
  cartera_disponible?: boolean;
  cartera_motivo?: string | null;
  cod_melonn_debe?: number;
  n_cod_melonn_debe?: number;
  cod_ya_cobrado?: number;
  cod_sin_facturar?: number;
  n_cod_sin_facturar?: number;
  cod_cartera_transito?: number;
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

  if (isLoading) return <LoadingState label="Cargando finanzas…" />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <PageShell
      title="Finanzas"
      subtitle={`Resumen financiero · sincronizado ${fmtDateTime(data.fetched_at)}`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      <section>
        <p className="section-label mb-3">Portafolio Contraentrega</p>
        <KpiStrip
          items={[
            { label: "Total COD",   value: formatMoneyShort(data.cod_total) },
            { label: "Pendientes",  value: formatMoneyShort(data.cod_pendientes) },
            { label: "En tránsito", value: formatMoneyShort(data.cod_transito) },
            { label: "Novedades",   value: formatMoneyShort(data.cod_novedades),  tone: data.n_cod_novedades > 0 ? "danger" : "default" },
            { label: "Entregados",  value: formatMoneyShort(data.cod_entregados), tone: "success" },
          ]}
        />
      </section>

      {/* LO QUE MELONN DEBE DE VERDAD.
          "Entregados" de arriba suma todo lo entregado en 90 días y nunca
          descuenta lo consignado: el 2026-08-10 marcaba $168.388.033 cuando la
          deuda real era $36.552.345 — inflado 4,6 veces. Estas cifras salen del
          saldo de cada factura en Siigo, que es donde la contadora registra la
          plata cuando entra. */}
      <section>
        <CarteraCod
          disponible={data.cartera_disponible}
          motivo={data.cartera_motivo}
          melonnDebe={data.cod_melonn_debe}
          nMelonnDebe={data.n_cod_melonn_debe}
          yaCobrado={data.cod_ya_cobrado}
          sinFacturar={data.cod_sin_facturar}
          nSinFacturar={data.n_cod_sin_facturar}
          enTransito={data.cod_cartera_transito}
          brutoEntregado={data.cod_entregados}
        />
      </section>

      <section>
        <p className="section-label mb-3">Detalle COD</p>
        <Card>
          <CardContent className="p-5">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  {["Estado", "Pedidos", "Valor COD", "% del total"].map((h, i) => (
                    <th key={h} className={`py-2 text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite ${i === 0 ? "text-left" : "text-right"}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <DetailRow label="Pendientes despacho" n={data.n_cod_pendientes} v={data.cod_pendientes} total={data.cod_total} />
                <DetailRow label="En tránsito"         n={data.n_cod_transito}   v={data.cod_transito}   total={data.cod_total} />
                <DetailRow label="Con novedades"       n={data.n_cod_novedades}  v={data.cod_novedades}  total={data.cod_total} accent="terracotta" />
                <DetailRow label="Entregados"          n={data.n_cod_entregados} v={data.cod_entregados} total={data.cod_total} accent="sage" />
                <tr className="border-t-2 border-ink-900/15 bg-cloud/50">
                  <td className="py-2 font-medium text-ink-900">Total portafolio</td>
                  <td className="py-2 text-right font-medium text-ink-900 tabular-nums">{data.n_cod_total}</td>
                  <td className="py-2 text-right font-medium text-ink-900 tabular-nums">{formatMoney(data.cod_total)}</td>
                  <td className="py-2 text-right font-medium text-ink-900 tabular-nums">100%</td>
                </tr>
              </tbody>
            </table>
          </CardContent>
        </Card>
      </section>

      <section>
        <p className="section-label mb-3">MercadoPago · últimos 30 días</p>
        <KpiStrip
          items={[
            { label: "Transacciones", value: data.n_mp },
            { label: "Valor bruto",   value: formatMoneyShort(data.mp_total) },
            { label: "Valor neto",    value: formatMoneyShort(data.mp_neto), tone: "success" },
            { label: "Comisiones",    value: formatMoneyShort(data.mp_comisiones) },
          ]}
        />
      </section>

      {/* Conciliación bancaria — vive en el servicio male-denim-reconciliation.
          Va al final porque es el cierre del ciclo del dinero: arriba está lo que
          se vendió y está por cobrar, acá lo que ya entró al banco y cuánto falta
          por plataforma. Se pinta solo si el servicio responde. */}
      <section>
        <ConciliacionBancaria />
      </section>
    </PageShell>
  );
}

function DetailRow({
  label, n, v, total, accent,
}: {
  label: string; n: number; v: number; total: number; accent?: "terracotta" | "sage";
}) {
  const pct = total > 0 ? Math.round((v / total) * 100) : 0;
  const colorCls = accent === "terracotta" ? "text-terracotta" : accent === "sage" ? "text-sage" : "text-ink-900";
  return (
    <tr className="border-b border-border transition-colors hover:bg-cloud/50">
      <td className={`py-2 ${colorCls}`}>{label}</td>
      <td className="py-2 text-right tabular-nums">{n}</td>
      <td className="py-2 text-right tabular-nums">{formatMoney(v)}</td>
      <td className="py-2 text-right tabular-nums text-graphite">{pct}%</td>
    </tr>
  );
}
