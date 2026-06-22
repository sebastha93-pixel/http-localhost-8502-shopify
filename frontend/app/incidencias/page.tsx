"use client";

import { useMemo } from "react";
import { usePedidos } from "@/lib/hooks";
import { PedidosTable } from "@/components/pedidos-table";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiStrip } from "@/components/kpi-card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Pedido } from "@/lib/types";

export default function IncidenciasPage() {
  const { data, isLoading, error, refetch, isFetching } = usePedidos();

  const groups = useMemo(() => {
    const novedades = (data?.pedidos ?? []).filter((p) => p.es_novedad_visible);
    const cat = (p: Pedido) => (p.categoria_incidencia || "OTRO").toUpperCase();
    return {
      todas:           novedades,
      cliente:         novedades.filter((p) => cat(p) === "CLIENTE"),
      transportadora:  novedades.filter((p) => cat(p) === "TRANSPORTADORA"),
      seguimiento:     novedades.filter((p) => cat(p) === "SEGUIMIENTO"),
      otros:           novedades.filter((p) => !["CLIENTE", "TRANSPORTADORA", "SEGUIMIENTO"].includes(cat(p))),
    };
  }, [data]);

  if (isLoading) return <LoadingState label="Cargando incidencias…" />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  const cols: Array<"nivel" | "orden" | "cliente" | "telefono" | "ciudad" | "dias" | "valor" | "novedad" | "tipo" | "link"> = [
    "nivel", "orden", "cliente", "telefono", "ciudad", "dias", "valor", "novedad", "tipo", "link",
  ];

  return (
    <PageShell
      title="Incidencias"
      subtitle={`${groups.todas.length} novedades activas · requieren gestión`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      <KpiStrip
        items={[
          { label: "Total",          value: groups.todas.length, tone: groups.todas.length > 0 ? "danger" : "default" },
          { label: "Cliente",        value: groups.cliente.length },
          { label: "Transportadora", value: groups.transportadora.length },
          { label: "Seguimiento",    value: groups.seguimiento.length },
        ]}
      />

      <Tabs defaultValue="todas">
        <TabsList>
          <TabsTrigger value="todas">Todas ({groups.todas.length})</TabsTrigger>
          <TabsTrigger value="cliente">Cliente ({groups.cliente.length})</TabsTrigger>
          <TabsTrigger value="transportadora">Transportadora ({groups.transportadora.length})</TabsTrigger>
          <TabsTrigger value="seguimiento">Seguimiento ({groups.seguimiento.length})</TabsTrigger>
          {groups.otros.length > 0 && <TabsTrigger value="otros">Otros ({groups.otros.length})</TabsTrigger>}
        </TabsList>

        <TabsContent value="todas">
          <PedidosTable pedidos={groups.todas} emptyMessage="Sin incidencias activas. Equipo al día." columns={cols} selectable />
        </TabsContent>
        <TabsContent value="cliente">
          <PedidosTable
            pedidos={groups.cliente}
            showTipoFilter={false}
            emptyMessage="Sin incidencias de cliente."
            columns={cols}
            selectable
          />
        </TabsContent>
        <TabsContent value="transportadora">
          <PedidosTable
            pedidos={groups.transportadora}
            showTipoFilter={false}
            emptyMessage="Sin incidencias de transportadora."
            columns={cols}
            selectable
          />
        </TabsContent>
        <TabsContent value="seguimiento">
          <PedidosTable
            pedidos={groups.seguimiento}
            showTipoFilter={false}
            emptyMessage="Sin incidencias de seguimiento."
            columns={cols}
            selectable
          />
        </TabsContent>
        {groups.otros.length > 0 && (
          <TabsContent value="otros">
            <PedidosTable pedidos={groups.otros} showTipoFilter={false} columns={cols} selectable />
          </TabsContent>
        )}
      </Tabs>
    </PageShell>
  );
}
