"use client";

import { useMemo } from "react";
import { usePedidos } from "@/lib/hooks";
import { PedidosTable } from "@/components/pedidos-table";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Pedido } from "@/lib/types";
import { formatMoneyShort } from "@/lib/utils";

function esB2B(p: Pedido): boolean {
  if (p.es_b2b) return true;
  const m = (p.transportadora || "").toLowerCase();
  const canal = (p.canal_venta || "").toLowerCase();
  return /b2b/.test(m) || /b2b|mayoris|wholesale/.test(canal);
}

export default function B2BPage() {
  const { data, isLoading, error, refetch, isFetching } = usePedidos();

  const groups = useMemo(() => {
    const b2b = (data?.pedidos ?? []).filter(esB2B);
    const code = (p: Pedido) => p.estado_melonn_code;
    return {
      todos:      b2b,
      proceso:    b2b.filter((p) => [1, 2, 5, 24, 26, 28, 29].includes(code(p)) && !p.es_novedad_visible),
      transito:   b2b.filter((p) => code(p) === 7 && !p.es_novedad_visible),
      novedades:  b2b.filter((p) => p.es_novedad_visible),
      entregados: b2b.filter((p) => [6, 8].includes(code(p))),
    };
  }, [data]);

  if (isLoading) return <LoadingState label="Cargando órdenes B2B..." />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  const sumVal = (arr: Pedido[]) => arr.reduce((s, p) => s + (p.valor_num ?? 0), 0);

  const cols: Array<"nivel" | "orden" | "cliente" | "telefono" | "ciudad" | "zona" | "envio" | "dias" | "valor" | "estado" | "link"> =
    ["nivel", "orden", "cliente", "telefono", "ciudad", "envio", "dias", "valor", "estado", "link"];

  return (
    <PageShell
      title="B2B"
      subtitle={`${groups.todos.length} órdenes B2B (mayoristas / distribuidores)`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      {groups.todos.length === 0 ? (
        <div className="rounded-lg border border-border bg-white p-10 text-center text-sm text-graphite">
          No hay órdenes B2B activas en este momento.
          <p className="mt-2 text-[0.65rem] text-graphite/70">
            Se identifican por el flag B2B de Melonn o el método "Estándar B2B".
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
            <KpiCard label="Total B2B"   value={groups.todos.length}      meta={formatMoneyShort(sumVal(groups.todos))} accent="navy" />
            <KpiCard label="En proceso"  value={groups.proceso.length}    meta="Alistamiento → listo"  accent="steel" />
            <KpiCard label="En tránsito" value={groups.transito.length}   meta="Camino al destino"     accent="navy" />
            <KpiCard label="Novedades"   value={groups.novedades.length}  meta="Requieren gestión"     accent={groups.novedades.length ? "rust" : "steel"} danger={groups.novedades.length > 0} />
            <KpiCard label="Entregados"  value={groups.entregados.length} meta="Completados"           accent="teal" />
          </div>

          <Tabs defaultValue="proceso">
            <TabsList>
              <TabsTrigger value="proceso">En proceso ({groups.proceso.length})</TabsTrigger>
              <TabsTrigger value="transito">Tránsito ({groups.transito.length})</TabsTrigger>
              <TabsTrigger value="novedades">Novedades ({groups.novedades.length})</TabsTrigger>
              <TabsTrigger value="entregados">Entregados ({groups.entregados.length})</TabsTrigger>
            </TabsList>

            <TabsContent value="proceso">
              <PedidosTable pedidos={groups.proceso} showTipoFilter={false} emptyMessage="No hay B2B en proceso" columns={cols} selectable />
            </TabsContent>
            <TabsContent value="transito">
              <PedidosTable pedidos={groups.transito} showTipoFilter={false} emptyMessage="No hay B2B en tránsito" columns={cols} selectable />
            </TabsContent>
            <TabsContent value="novedades">
              <PedidosTable pedidos={groups.novedades} showTipoFilter={false} emptyMessage="✓ Sin novedades B2B" columns={cols} selectable />
            </TabsContent>
            <TabsContent value="entregados">
              <PedidosTable pedidos={groups.entregados} showTipoFilter={false} showNivelFilter={false} emptyMessage="Sin entregas B2B" columns={cols} selectable />
            </TabsContent>
          </Tabs>
        </>
      )}
    </PageShell>
  );
}
