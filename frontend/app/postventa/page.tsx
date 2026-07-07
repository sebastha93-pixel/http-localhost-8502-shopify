"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtDateTime } from "@/lib/utils";
import {
  listarCasos, dashboardPostventa, ESTADOS_LABEL, type EstadoPostventa,
} from "@/lib/postventa";

export default function PostventaPage() {
  const [filtro, setFiltro] = useState<string>("");
  const casos = useQuery({
    queryKey: ["postventa-casos", filtro],
    queryFn: () => listarCasos(filtro || undefined),
  });
  const dash = useQuery({ queryKey: ["postventa-dash"], queryFn: dashboardPostventa });

  return (
    <PageShell title="Postventa" subtitle="Cambios, devoluciones y garantías">
      {dash.data && (
        <div className="grid grid-cols-3 gap-3 mb-4">
          <KpiBox label="Abiertos" value={dash.data.abiertos} />
          <KpiBox label="Cerrados" value={dash.data.cerrados} />
          <KpiBox label="Total" value={dash.data.total} />
        </div>
      )}

      <div className="flex gap-2 mb-4 flex-wrap">
        <FiltroChip label="Todos" activo={filtro === ""} onClick={() => setFiltro("")} />
        {(Object.keys(ESTADOS_LABEL) as EstadoPostventa[]).map((e) => (
          <FiltroChip key={e} label={ESTADOS_LABEL[e]} activo={filtro === e}
                      onClick={() => setFiltro(e)} />
        ))}
      </div>

      {casos.isLoading && <LoadingState />}
      {casos.isError && <ErrorState error={casos.error} onRetry={() => casos.refetch()} />}
      {casos.data && (
        <div className="space-y-2">
          {casos.data.length === 0 && (
            <p className="text-sm text-muted-foreground">No hay casos para este filtro.</p>
          )}
          {casos.data.map((c) => (
            <Link key={c.id} href={`/postventa/${c.id}`}>
              <Card className="hover:bg-accent/40 transition-colors">
                <CardContent className="flex items-center justify-between py-3">
                  <div>
                    <div className="font-medium">{c.case_number}
                      <span className="text-muted-foreground font-normal"> · {c.type}</span>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {c.customer_name || c.customer_email || "Sin cliente"}
                      {c.shopify_order_name ? ` · ${c.shopify_order_name}` : ""}
                    </div>
                  </div>
                  <div className="text-right">
                    <Badge>{ESTADOS_LABEL[c.status] ?? c.status}</Badge>
                    <div className="text-xs text-muted-foreground mt-1">
                      {fmtDateTime(c.created_at)}
                    </div>
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

function KpiBox({ label, value }: { label: string; value: number }) {
  return (
    <Card><CardContent className="py-3">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </CardContent></Card>
  );
}

function FiltroChip({ label, activo, onClick }:
  { label: string; activo: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`px-3 py-1 rounded-full text-sm border ${
        activo ? "bg-primary text-primary-foreground" : "bg-background"}`}>
      {label}
    </button>
  );
}
