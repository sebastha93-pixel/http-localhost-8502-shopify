"use client";

import { useMemo } from "react";
import { usePedidos } from "@/lib/hooks";
import { PedidosTable } from "@/components/pedidos-table";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Pedido } from "@/lib/types";
import { formatMoneyShort } from "@/lib/utils";

// Detección heurística de devoluciones: incidencias con keywords típicos.
// Cuando el backend exponga categoría DEVOLUCION explícita, simplificar.
const RX_DEVOLUCION = /devolu|rechaz|retorn|no acept|no quiso|reembols|cancel/i;

function esDevolucion(p: Pedido): boolean {
  const inc = (p.incidencia || "").toString();
  if (inc && inc !== "NINGUNO" && RX_DEVOLUCION.test(inc)) return true;
  if ((p.motivo_riesgo || "").match(RX_DEVOLUCION)) return true;
  return false;
}

export default function DevolucionesPage() {
  const { data, isLoading, error, refetch, isFetching } = usePedidos();

  const groups = useMemo(() => {
    const all = data?.pedidos ?? [];
    const devs = all.filter(esDevolucion);
    return {
      todas:    devs,
      activas:  devs.filter((p) => p.sub_estado_logistico === "novedad"),
      enRuta:   devs.filter((p) => p.sub_estado_logistico === "en_transito"),
      resueltas:devs.filter((p) => p.sub_estado_logistico === "resuelto" || p.sub_estado_logistico === "entregado"),
    };
  }, [data]);

  if (isLoading) return <LoadingState label="Cargando devoluciones..." />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  const sumVal = (arr: Pedido[]) => arr.reduce((s, p) => s + (p.valor_num ?? 0), 0);
  const valComprometido = sumVal(groups.activas) + sumVal(groups.enRuta);

  return (
    <PageShell
      title="Devoluciones"
      subtitle={`${groups.todas.length} pedidos con flujo de retorno · ${formatMoneyShort(valComprometido)} comprometido`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard label="Total"          value={groups.todas.length}     meta="Histórico activo"        accent="rust" />
        <KpiCard label="Activas"        value={groups.activas.length}   meta="Sin resolver"            accent={groups.activas.length ? "crimson" : "steel"} danger={groups.activas.length > 0} />
        <KpiCard label="En ruta"        value={groups.enRuta.length}    meta="Regresando a bodega"     accent="khaki" />
        <KpiCard label="Resueltas"      value={groups.resueltas.length} meta="Recuperadas / cerradas"  accent="teal" />
      </div>

      {groups.todas.length === 0 ? (
        <div className="rounded-lg border border-border bg-white p-10 text-center text-sm text-graphite">
          ✓ Sin devoluciones detectadas en operación actual.
          <p className="mt-2 text-[0.65rem] text-graphite/70">
            Detección por keywords en incidencia. Próxima iteración: categoría explícita desde backend.
          </p>
        </div>
      ) : (
        <Tabs defaultValue="activas">
          <TabsList>
            <TabsTrigger value="activas">Activas ({groups.activas.length})</TabsTrigger>
            <TabsTrigger value="enRuta">En ruta ({groups.enRuta.length})</TabsTrigger>
            <TabsTrigger value="resueltas">Resueltas ({groups.resueltas.length})</TabsTrigger>
            <TabsTrigger value="todas">Todas ({groups.todas.length})</TabsTrigger>
          </TabsList>

          <TabsContent value="activas">
            <PedidosTable
              pedidos={groups.activas}
              emptyMessage="✓ Sin devoluciones activas"
              columns={["nivel", "orden", "cliente", "telefono", "ciudad", "dias", "valor", "novedad", "tipo", "link"]}
              selectable
            />
          </TabsContent>
          <TabsContent value="enRuta">
            <PedidosTable
              pedidos={groups.enRuta}
              emptyMessage="Sin devoluciones en tránsito"
              columns={["nivel", "orden", "cliente", "telefono", "ciudad", "dias", "valor", "estado", "tipo", "link"]}
              selectable
            />
          </TabsContent>
          <TabsContent value="resueltas">
            <PedidosTable
              pedidos={groups.resueltas}
              showNivelFilter={false}
              emptyMessage="Sin devoluciones resueltas"
              columns={["orden", "cliente", "telefono", "ciudad", "valor", "novedad", "tipo", "link"]}
              selectable
            />
          </TabsContent>
          <TabsContent value="todas">
            <PedidosTable
              pedidos={groups.todas}
              columns={["nivel", "orden", "cliente", "telefono", "ciudad", "dias", "valor", "novedad", "tipo", "link"]}
              selectable
            />
          </TabsContent>
        </Tabs>
      )}
    </PageShell>
  );
}
