"use client";

import { useMemo } from "react";
import { usePedidos } from "@/lib/hooks";
import { PedidosTable } from "@/components/pedidos-table";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiStrip } from "@/components/kpi-card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Pedido } from "@/lib/types";
import { formatMoneyShort } from "@/lib/utils";
import { AutorizarDespachoButton } from "@/components/autorizar-button";
import { PendientesCodFlow } from "@/components/pendientes-cod-flow";

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

  if (isLoading) return <LoadingState label="Cargando pedidos contraentrega…" />;
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
      <KpiStrip
        items={[
          { label: "Total COD",   value: `${groups.todos.length} · ${formatMoneyShort(valTotal)}` },
          { label: "Pendientes",  value: groups.pendientes.length },
          { label: "En proceso",  value: `${groups.proceso.length} · ${formatMoneyShort(valProceso)}` },
          { label: "En tránsito", value: `${groups.transito.length} · ${formatMoneyShort(valTransito)}` },
          { label: "Novedades",   value: `${groups.novedades.length} · ${formatMoneyShort(valNovedades)}`, tone: groups.novedades.length > 0 ? "danger" : "default" },
        ]}
      />

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
            emptyMessage="Sin pedidos pendientes de despacho."
            columns={["nivel", "orden", "cliente", "telefono", "producto", "ciudad", "dias", "valor", "estado"]}
            selectable
            renderAction={(p) => <PendientesCodFlow pedido={p} />}
          />
        </TabsContent>
        <TabsContent value="proceso">
          <PedidosTable
            pedidos={groups.proceso}
            showTipoFilter={false}
            emptyMessage="Sin pedidos en proceso."
            columns={["nivel", "orden", "cliente", "telefono", "producto", "ciudad", "dias", "valor", "estado"]}
            selectable
          />
        </TabsContent>
        <TabsContent value="transito">
          <PedidosTable
            pedidos={groups.transito}
            showTipoFilter={false}
            emptyMessage="Sin pedidos en tránsito."
            columns={["nivel", "orden", "cliente", "telefono", "ciudad", "zona", "envio", "dias", "valor", "estado", "link"]}
            selectable
          />
        </TabsContent>
        <TabsContent value="novedades">
          <PedidosTable
            pedidos={groups.novedades}
            showTipoFilter={false}
            emptyMessage="Sin novedades en COD. Todo va al día."
            columns={["nivel", "orden", "cliente", "telefono", "ciudad", "dias", "valor", "novedad", "link"]}
            selectable
          />
        </TabsContent>
        <TabsContent value="entregados">
          <PedidosTable
            pedidos={groups.entregados}
            showTipoFilter={false}
            showNivelFilter={false}
            emptyMessage="Sin entregas registradas en este período."
            columns={["orden", "cliente", "telefono", "ciudad", "dias", "valor", "estado", "link"]}
            selectable
          />
          <p className="mt-3 text-xs text-graphite">
            Total entregado <span className="font-medium text-ink-900 tabular-nums">{formatMoneyShort(valEntregado)}</span>
          </p>
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
