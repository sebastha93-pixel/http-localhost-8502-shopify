"use client";

import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { obtenerCaso, cambiarEstado, ESTADOS_LABEL, type EstadoPostventa } from "@/lib/postventa";

// Transiciones ofrecidas en UI (espejo del backend postventa_logic.TRANSICIONES).
const ACCIONES: Record<string, EstadoPostventa[]> = {
  creado: ["pendiente_validacion"],
  pendiente_validacion: ["aprobado", "rechazado", "escalado"],
  aprobado: ["nota_credito_emitida", "cerrado"],
  escalado: ["aprobado", "rechazado"],
  nota_credito_emitida: ["factura_emitida", "cerrado"],
  factura_emitida: ["cerrado"],
};

export default function CasoDetallePage() {
  const params = useParams();
  const caseId = params?.caseId as string;
  const qc = useQueryClient();
  const caso = useQuery({ queryKey: ["postventa-caso", caseId],
                          queryFn: () => obtenerCaso(caseId) });

  const mut = useMutation({
    mutationFn: (estado: string) => cambiarEstado(caseId, estado),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["postventa-caso", caseId] });
      qc.invalidateQueries({ queryKey: ["postventa-casos"] });
    },
  });

  if (caso.isLoading) return <PageShell title="Caso"><LoadingState /></PageShell>;
  if (caso.isError || !caso.data)
    return <PageShell title="Caso"><ErrorState error={caso.error} onRetry={() => caso.refetch()} /></PageShell>;

  const c = caso.data;
  const acciones = ACCIONES[c.status] ?? [];

  return (
    <PageShell title={c.case_number} subtitle={`${c.type} · ${c.reason}`}>
      <Card className="mb-4"><CardContent className="py-4 space-y-1">
        <div className="flex items-center gap-2">
          <Badge>{ESTADOS_LABEL[c.status] ?? c.status}</Badge>
          <span className="text-sm text-muted-foreground">
            Prioridad: {c.priority}
          </span>
        </div>
        <div className="text-sm">Cliente: {c.customer_name || c.customer_email || "—"}</div>
        <div className="text-sm">Teléfono: {c.customer_phone || "—"}</div>
        <div className="text-sm">Pedido Shopify: {c.shopify_order_name || "—"}</div>
      </CardContent></Card>

      <div className="flex gap-2 flex-wrap">
        {acciones.map((a) => (
          <button key={a} disabled={mut.isPending}
                  onClick={() => mut.mutate(a)}
                  className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-medium text-graphite transition-colors hover:bg-cloud disabled:opacity-50">
            {ESTADOS_LABEL[a] ?? a}
          </button>
        ))}
        {acciones.length === 0 && (
          <p className="text-sm text-muted-foreground">Caso en estado final.</p>
        )}
      </div>
      {mut.isError && (
        <p className="text-sm text-destructive mt-2">
          No se pudo cambiar el estado (transición inválida).
        </p>
      )}
    </PageShell>
  );
}
