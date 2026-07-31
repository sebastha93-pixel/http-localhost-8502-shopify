"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { KpiStrip } from "@/components/kpi-card";
import { StatusBadge } from "@/components/status-badge";
import { fmtDateTime, formatMoney } from "@/lib/utils";
import {
  listarCasos, dashboardPostventa, impactoVentas, ESTADOS_LABEL, ESTADO_KIND,
  type EstadoPostventa,
} from "@/lib/postventa";

const TIPO_LABEL: Record<string, string> = {
  cambio_talla: "Cambio de talla", cambio_ref: "Cambio de referencia",
  reembolso: "Reembolso", bono: "Bono", garantia: "Garantía",
};

export default function PostventaPage() {
  const [filtro, setFiltro] = useState<string>("");
  const casos = useQuery({
    queryKey: ["postventa-casos", filtro],
    queryFn: () => listarCasos(filtro || undefined),
  });
  const dash = useQuery({ queryKey: ["postventa-dash"], queryFn: dashboardPostventa });
  const impacto = useQuery({ queryKey: ["postventa-impacto"], queryFn: impactoVentas });

  return (
    <PageShell title="Postventa" subtitle="Cambios, devoluciones y garantías">
      <div className="flex items-start justify-between gap-4 mb-4">
        {dash.data ? (
          <div className="flex-1">
            <KpiStrip items={[
              { label: "Abiertos", value: dash.data.abiertos },
              { label: "Cerrados", value: dash.data.cerrados, tone: "success" },
              { label: "Total", value: dash.data.total },
              ...(impacto.data ? [
                { label: "Devuelto", value: formatMoney(impacto.data.devuelto),
                  tone: "danger" as const },
                { label: "Refacturado", value: formatMoney(impacto.data.refacturado),
                  tone: "success" as const },
                { label: "Impacto neto", value: formatMoney(impacto.data.neto),
                  tone: "danger" as const },
              ] : []),
            ]} />
          </div>
        ) : <div className="flex-1" />}
        <Link href="/postventa/nuevo"
          className="shrink-0 rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white
                     transition-colors hover:bg-navy-700">
          Nuevo caso
        </Link>
      </div>

      {dash.data && dash.data.top_motivos.length > 0 && (
        <p className="mb-4 text-xs text-graphite">
          <span className="section-label mr-2">Motivo más frecuente</span>
          {dash.data.top_motivos[0].motivo.replace(/_/g, " ")}
          {" · "}
          <span className="font-display tabular-nums">{dash.data.top_motivos[0].total}</span> casos
        </p>
      )}

      {/* Solo los estados que TIENEN casos. Trece chips vacíos hacen ver el
          flujo como un trámite largo, y ninguno de ellos lleva a nada. El
          activo se conserva aunque quede en cero para poder volver. */}
      <div className="flex gap-1.5 mb-4 flex-wrap">
        <FiltroChip label="Todos" activo={filtro === ""} onClick={() => setFiltro("")} />
        {(Object.keys(ESTADOS_LABEL) as EstadoPostventa[])
          .filter((e) => (dash.data?.por_estado[e] ?? 0) > 0 || filtro === e)
          .map((e) => (
            <FiltroChip key={e} label={ESTADOS_LABEL[e]} activo={filtro === e}
                        onClick={() => setFiltro(e)}
                        contador={dash.data?.por_estado[e]} />
          ))}
      </div>

      {casos.isLoading && <LoadingState />}
      {casos.isError && <ErrorState error={casos.error} onRetry={() => casos.refetch()} />}
      {casos.data && (
        <div className="space-y-2">
          {casos.data.length === 0 && (
            <Card><CardContent className="py-10 text-center">
              <p className="text-sm text-ink-900">No hay casos para este filtro.</p>
              <p className="mt-1 text-xs text-graphite">
                Los cambios y devoluciones que registres aparecerán aquí.
              </p>
            </CardContent></Card>
          )}
          {casos.data.map((c) => (
            <Link key={c.id} href={`/postventa/${c.id}`} className="block">
              <Card className="transition-colors hover:border-navy-600/40 hover:bg-cloud/40">
                <CardContent className="flex items-center justify-between gap-4 py-3">
                  <div className="min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="font-display tabular-nums text-sm text-ink-900">
                        {c.case_number}
                      </span>
                      <span className="text-xs text-graphite truncate">
                        {TIPO_LABEL[c.type] ?? c.type}
                      </span>
                    </div>
                    <p className="mt-0.5 text-sm text-graphite truncate">
                      {c.customer_name || c.customer_email || "Sin cliente"}
                      {c.shopify_order_name && (
                        <span className="font-display tabular-nums"> · {c.shopify_order_name}</span>
                      )}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <StatusBadge status={ESTADO_KIND[c.status] ?? "wait"}
                                 label={ESTADOS_LABEL[c.status] ?? c.status} />
                    <p className="mt-1 text-[0.68rem] text-graphite tabular-nums">
                      {fmtDateTime(c.created_at)}
                    </p>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </PageShell>
  );
}

function FiltroChip({ label, activo, onClick, contador }:
  { label: string; activo: boolean; onClick: () => void; contador?: number }) {
  return (
    <button onClick={onClick}
      className={`rounded-sm border px-2.5 py-1 text-xs transition-colors ${
        activo
          ? "border-navy-600 bg-navy-600 text-white"
          : "border-border bg-card text-graphite hover:bg-cloud"}`}>
      {label}
      {contador !== undefined && contador > 0 && (
        <span className={`ml-1.5 font-display tabular-nums ${
          activo ? "text-white/80" : "text-ink-900"}`}>{contador}</span>
      )}
    </button>
  );
}
