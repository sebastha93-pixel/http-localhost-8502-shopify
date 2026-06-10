"use client";

import { useMemo } from "react";
import { usePedidos } from "@/lib/hooks";
import { PedidosTable } from "@/components/pedidos-table";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
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

  if (isLoading) return <LoadingState label="Cargando incidencias..." />;
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
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard label="Total"           value={groups.todas.length}          meta="Pedidos con novedad"        accent={groups.todas.length ? "rust" : "steel"} danger={groups.todas.length > 0} />
        <KpiCard label="Cliente"         value={groups.cliente.length}        meta="Requiere contactar"         accent="khaki" />
        <KpiCard label="Transportadora"  value={groups.transportadora.length} meta="Problema operador"          accent="navy" />
        <KpiCard label="Seguimiento"     value={groups.seguimiento.length}    meta="Verificar estado"           accent="steel" />
      </div>

      <Tabs defaultValue="todas">
        <TabsList>
          <TabsTrigger value="todas">Todas ({groups.todas.length})</TabsTrigger>
          <TabsTrigger value="cliente">Cliente ({groups.cliente.length})</TabsTrigger>
          <TabsTrigger value="transportadora">Transportadora ({groups.transportadora.length})</TabsTrigger>
          <TabsTrigger value="seguimiento">Seguimiento ({groups.seguimiento.length})</TabsTrigger>
          {groups.otros.length > 0 && <TabsTrigger value="otros">Otros ({groups.otros.length})</TabsTrigger>}
        </TabsList>

        <TabsContent value="todas">
          <PedidosTable pedidos={groups.todas} emptyMessage="✓ Sin incidencias activas" columns={cols} selectable />
        </TabsContent>
        <TabsContent value="cliente">
          <PedidosTable
            pedidos={groups.cliente}
            showTipoFilter={false}
            emptyMessage="✓ Sin incidencias de cliente"
            columns={cols}
            selectable
          />
        </TabsContent>
        <TabsContent value="transportadora">
          <PedidosTable
            pedidos={groups.transportadora}
            showTipoFilter={false}
            emptyMessage="✓ Sin incidencias de transportadora"
            columns={cols}
            selectable
          />
        </TabsContent>
        <TabsContent value="seguimiento">
          <PedidosTable
            pedidos={groups.seguimiento}
            showTipoFilter={false}
            emptyMessage="✓ Sin incidencias de seguimiento"
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
