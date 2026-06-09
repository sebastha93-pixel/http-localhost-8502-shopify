"use client";

import { useMemo } from "react";
import { usePedidos } from "@/lib/hooks";
import { PedidosTable } from "@/components/pedidos-table";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Pedido } from "@/lib/types";

export default function EnviosPage() {
  const { data, isLoading, error, refetch, isFetching } = usePedidos();

  const groups = useMemo(() => {
    const pres = (data?.pedidos ?? []).filter((p) => p.tipo_recaudo === "Prepago");
    const sub  = (p: Pedido) => p.sub_estado_logistico;
    return {
      todos:      pres,
      transito:   pres.filter((p) => sub(p) === "en_transito" || sub(p) === "pendiente_despacho"),
      novedades:  pres.filter((p) => sub(p) === "novedad"),
      entregados: pres.filter((p) => sub(p) === "entregado"),
    };
  }, [data]);

  if (isLoading) return <LoadingState label="Cargando envíos prepago..." />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <PageShell
      title="Envíos"
      subtitle={`${groups.todos.length} envíos prepago · pagados, en flujo logístico`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard label="Total prepago" value={groups.todos.length}      meta="Ya cobrados"           accent="navy" />
        <KpiCard label="En tránsito"   value={groups.transito.length}   meta="Camino al cliente"     accent="steel" />
        <KpiCard label="Novedades"     value={groups.novedades.length}  meta="No entregados"         accent={groups.novedades.length ? "rust" : "steel"} danger={groups.novedades.length > 0} />
        <KpiCard label="Entregados"    value={groups.entregados.length} meta="Completados"           accent="teal" />
      </div>

      <Tabs defaultValue="transito">
        <TabsList>
          <TabsTrigger value="transito">Tránsito ({groups.transito.length})</TabsTrigger>
          <TabsTrigger value="novedades">Novedades ({groups.novedades.length})</TabsTrigger>
          <TabsTrigger value="entregados">Entregados ({groups.entregados.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="transito">
          <PedidosTable
            pedidos={groups.transito}
            showTipoFilter={false}
            emptyMessage="No hay envíos en tránsito"
            columns={["nivel", "orden", "cliente", "ciudad", "zona", "dias", "estado", "link"]}
          />
        </TabsContent>
        <TabsContent value="novedades">
          <PedidosTable
            pedidos={groups.novedades}
            showTipoFilter={false}
            emptyMessage="✓ Sin novedades en prepago"
            columns={["nivel", "orden", "cliente", "ciudad", "dias", "novedad", "link"]}
          />
        </TabsContent>
        <TabsContent value="entregados">
          <PedidosTable
            pedidos={groups.entregados}
            showTipoFilter={false}
            showNivelFilter={false}
            emptyMessage="Sin entregas registradas"
            columns={["orden", "cliente", "ciudad", "dias", "estado", "link"]}
          />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
