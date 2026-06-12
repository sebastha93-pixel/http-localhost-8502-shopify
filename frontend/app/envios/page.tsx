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
    const code = (p: Pedido) => p.estado_melonn_code;
    return {
      todos:      pres,
      // En proceso: alistamiento → preparado, ANTES de la transportadora
      proceso:    pres.filter((p) => [1, 2, 5, 24, 26, 28, 29].includes(code(p)) && !p.es_novedad_visible),
      // En tránsito: ya con la transportadora (en ruta al cliente)
      transito:   pres.filter((p) => code(p) === 7 && !p.es_novedad_visible),
      novedades:  pres.filter((p) => p.es_novedad_visible),
      entregados: pres.filter((p) => [6, 8].includes(code(p))),
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
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <KpiCard label="Total prepago" value={groups.todos.length}      meta="Ya cobrados"           accent="navy" />
        <KpiCard label="En proceso"    value={groups.proceso.length}    meta="Alistamiento → listo"  accent="steel" />
        <KpiCard label="En tránsito"   value={groups.transito.length}   meta="Camino al cliente"     accent="navy" />
        <KpiCard label="Novedades"     value={groups.novedades.length}  meta="No entregados"         accent={groups.novedades.length ? "rust" : "steel"} danger={groups.novedades.length > 0} />
        <KpiCard label="Entregados"    value={groups.entregados.length} meta="Completados"           accent="teal" />
      </div>

      <Tabs defaultValue="transito">
        <TabsList>
          <TabsTrigger value="proceso">En proceso ({groups.proceso.length})</TabsTrigger>
          <TabsTrigger value="transito">Tránsito ({groups.transito.length})</TabsTrigger>
          <TabsTrigger value="novedades">Novedades ({groups.novedades.length})</TabsTrigger>
          <TabsTrigger value="entregados">Entregados ({groups.entregados.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="proceso">
          <PedidosTable
            pedidos={groups.proceso}
            showTipoFilter={false}
            emptyMessage="No hay envíos en proceso"
            columns={["nivel", "orden", "cliente", "telefono", "producto", "ciudad", "dias", "estado"]}
            selectable
          />
        </TabsContent>
        <TabsContent value="transito">
          <PedidosTable
            pedidos={groups.transito}
            showTipoFilter={false}
            emptyMessage="No hay envíos en tránsito"
            columns={["nivel", "orden", "cliente", "telefono", "ciudad", "zona", "dias", "estado", "link"]}
            selectable
          />
        </TabsContent>
        <TabsContent value="novedades">
          <PedidosTable
            pedidos={groups.novedades}
            showTipoFilter={false}
            emptyMessage="✓ Sin novedades en prepago"
            columns={["nivel", "orden", "cliente", "telefono", "ciudad", "dias", "novedad", "link"]}
            selectable
          />
        </TabsContent>
        <TabsContent value="entregados">
          <PedidosTable
            pedidos={groups.entregados}
            showTipoFilter={false}
            showNivelFilter={false}
            emptyMessage="Sin entregas registradas"
            columns={["orden", "cliente", "telefono", "ciudad", "dias", "estado", "link"]}
            selectable
          />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
