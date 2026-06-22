"use client";

import { useMemo } from "react";
import { usePedidos } from "@/lib/hooks";
import { PedidosTable } from "@/components/pedidos-table";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiStrip } from "@/components/kpi-card";
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

  if (isLoading) return <LoadingState label="Cargando órdenes B2B…" />;
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
        <div className="rounded-md border border-border bg-card p-10 text-center text-sm text-graphite">
          Sin órdenes B2B activas en este momento.
          <p className="mt-2 text-[0.65rem] text-graphite/70">
            Se identifican por el flag B2B de Melonn o el método "Estándar B2B".
          </p>
        </div>
      ) : (
        <>
          <KpiStrip
            items={[
              { label: "Total B2B",   value: `${groups.todos.length} · ${formatMoneyShort(sumVal(groups.todos))}` },
              { label: "En proceso",  value: groups.proceso.length },
              { label: "En tránsito", value: groups.transito.length },
              { label: "Novedades",   value: groups.novedades.length, tone: groups.novedades.length > 0 ? "danger" : "default" },
              { label: "Entregados",  value: groups.entregados.length, tone: "success" },
            ]}
          />

          <Tabs defaultValue="proceso">
            <TabsList>
              <TabsTrigger value="proceso">En proceso ({groups.proceso.length})</TabsTrigger>
              <TabsTrigger value="transito">Tránsito ({groups.transito.length})</TabsTrigger>
              <TabsTrigger value="novedades">Novedades ({groups.novedades.length})</TabsTrigger>
              <TabsTrigger value="entregados">Entregados ({groups.entregados.length})</TabsTrigger>
            </TabsList>

            <TabsContent value="proceso">
              <PedidosTable pedidos={groups.proceso} showTipoFilter={false} emptyMessage="Sin B2B en proceso." columns={cols} selectable />
            </TabsContent>
            <TabsContent value="transito">
              <PedidosTable pedidos={groups.transito} showTipoFilter={false} emptyMessage="Sin B2B en tránsito." columns={cols} selectable />
            </TabsContent>
            <TabsContent value="novedades">
              <PedidosTable pedidos={groups.novedades} showTipoFilter={false} emptyMessage="Sin novedades B2B. Todo va al día." columns={cols} selectable />
            </TabsContent>
            <TabsContent value="entregados">
              <PedidosTable pedidos={groups.entregados} showTipoFilter={false} showNivelFilter={false} emptyMessage="Sin entregas B2B registradas." columns={cols} selectable />
            </TabsContent>
          </Tabs>
        </>
      )}
    </PageShell>
  );
}
