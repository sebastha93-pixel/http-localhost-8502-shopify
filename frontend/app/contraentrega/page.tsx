"use client";

import { useMemo } from "react";
import { usePedidos } from "@/lib/hooks";
import { PedidosTable } from "@/components/pedidos-table";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Pedido } from "@/lib/types";
import { formatMoneyShort } from "@/lib/utils";
import { AutorizarDespachoButton } from "@/components/autorizar-button";

export default function ContraentregaPage() {
  const { data, isLoading, error, refetch, isFetching } = usePedidos();

  const groups = useMemo(() => {
    const cods = (data?.pedidos ?? []).filter((p) => p.tipo_recaudo === "Contraentrega");
    const code = (p: Pedido) => p.estado_melonn_code;
    return {
      todos:      cods,
      pendientes: cods.filter((p) => [26, 29].includes(code(p)) && !p.es_novedad_visible),
      // En proceso: alistamiento → empacado → preparado, ANTES de transportadora
      proceso:    cods.filter((p) => [1, 2, 5, 24, 28].includes(code(p)) && !p.es_novedad_visible),
      // En tránsito: ya entregado a la transportadora (en ruta al cliente)
      transito:   cods.filter((p) => code(p) === 7 && !p.es_novedad_visible),
      novedades:  cods.filter((p) => p.es_novedad_visible),
      entregados: cods.filter((p) => [6, 8].includes(code(p))),
    };
  }, [data]);

  if (isLoading) return <LoadingState label="Cargando pedidos contraentrega..." />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  const sumVal = (arr: Pedido[]) => arr.reduce((s, p) => s + (p.valor_num ?? 0), 0);
  const valTotal = sumVal(groups.todos);
  const valProceso = sumVal(groups.proceso);
  const valTransito = sumVal(groups.transito);
  const valNovedades = sumVal(groups.novedades);
  const valEntregado = sumVal(groups.entregados);

  return (
    <PageShell
      title="Contraentrega"
      subtitle={`${groups.todos.length} pedidos COD activos · recaudo pendiente`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      {/* KPIs COD */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <KpiCard label="Total COD"        value={groups.todos.length}        meta={formatMoneyShort(valTotal)}     accent="navy" />
        <KpiCard label="Pendientes"       value={groups.pendientes.length}   meta="Esperan despacho"               accent="khaki" />
        <KpiCard label="En proceso"       value={groups.proceso.length}      meta={formatMoneyShort(valProceso)}   accent="steel" />
        <KpiCard label="En tránsito"      value={groups.transito.length}     meta={formatMoneyShort(valTransito)}  accent="navy" />
        <KpiCard label="Novedades"        value={groups.novedades.length}    meta={formatMoneyShort(valNovedades)} accent={groups.novedades.length ? "rust" : "steel"} danger={groups.novedades.length > 0} />
      </div>

      <Tabs defaultValue="pendientes">
        <TabsList>
          <TabsTrigger value="pendientes">Pendientes ({groups.pendientes.length})</TabsTrigger>
          <TabsTrigger value="proceso">En proceso ({groups.proceso.length})</TabsTrigger>
          <TabsTrigger value="transito">Tránsito ({groups.transito.length})</TabsTrigger>
          <TabsTrigger value="novedades">Novedades ({groups.novedades.length})</TabsTrigger>
          <TabsTrigger value="entregados">Entregados ({groups.entregados.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="pendientes">
          <PedidosTable
            pedidos={groups.pendientes}
            showTipoFilter={false}
            emptyMessage="No hay pedidos pendientes de despacho"
            columns={["nivel", "orden", "cliente", "cliente_tier", "telefono", "producto", "ciudad", "dias", "valor", "estado"]}
            selectable
            renderAction={(p) => <AutorizarDespachoButton pedido={p} />}
          />
        </TabsContent>
        <TabsContent value="proceso">
          <PedidosTable
            pedidos={groups.proceso}
            showTipoFilter={false}
            emptyMessage="No hay pedidos en proceso"
            columns={["nivel", "orden", "cliente", "telefono", "producto", "ciudad", "envio", "dias", "valor", "estado"]}
            selectable
          />
        </TabsContent>
        <TabsContent value="transito">
          <PedidosTable
            pedidos={groups.transito}
            showTipoFilter={false}
            emptyMessage="No hay pedidos en tránsito"
            columns={["nivel", "orden", "cliente", "telefono", "ciudad", "zona", "envio", "dias", "valor", "estado", "link"]}
            selectable
          />
        </TabsContent>
        <TabsContent value="novedades">
          <PedidosTable
            pedidos={groups.novedades}
            showTipoFilter={false}
            emptyMessage="✓ Sin novedades en COD"
            columns={["nivel", "orden", "cliente", "telefono", "ciudad", "dias", "valor", "novedad", "link"]}
            selectable
          />
        </TabsContent>
        <TabsContent value="entregados">
          <PedidosTable
            pedidos={groups.entregados}
            showTipoFilter={false}
            showNivelFilter={false}
            emptyMessage="Sin entregas registradas"
            columns={["orden", "cliente", "telefono", "ciudad", "dias", "valor", "estado", "link"]}
            selectable
          />
          <p className="text-xs text-graphite mt-3">
            Total entregado: <span className="font-semibold text-ink">{formatMoneyShort(valEntregado)}</span>
          </p>
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
