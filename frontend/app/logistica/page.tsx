"use client";

import { usePedidos } from "@/lib/hooks";
import { PedidosTable } from "@/components/pedidos-table";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";

export default function LogisticaPage() {
  const { data, isLoading, error, refetch, isFetching } = usePedidos();

  if (isLoading) return <LoadingState label="Cargando pedidos…" />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <PageShell
      title="Logística"
      subtitle={`${data.total} pedidos activos en operación`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      <PedidosTable pedidos={data.pedidos} selectable />
    </PageShell>
  );
}
