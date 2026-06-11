"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { puedeEscribir } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { formatMoney, formatMoneyShort, fmtDateTime } from "@/lib/utils";
import { Search, CheckCircle, Loader2, X, DollarSign, AlertTriangle } from "lucide-react";

interface PedidoConc {
  orden_tienda: string;
  orden_melonn: string;
  nombre_comprador: string;
  ciudad_destino: string;
  zona: string;
  transportadora: string;
  fecha_entrega?: string | null;
  fecha_despacho?: string | null;
  valor_cod: number;
  dias_desde_entrega: number;
  liquidado: boolean;
  monto_liquidado?: number | null;
  fecha_liquidacion?: string | null;
  referencia?: string | null;
  diferencia?: number | null;
  autor_liquidacion?: string | null;
}

interface Resumen {
  total_entregado: number;
  total_liquidado: number;
  total_pendiente: number;
  n_total: number;
  n_liquidados: number;
  n_pendientes: number;
  n_con_diferencia: number;
}

interface CodResponse {
  resumen: Resumen;
  pedidos: PedidoConc[];
}

export default function ConciliacionPage() {
  const { user } = useAuth();
  const canWrite = puedeEscribir(user);
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [selectedOrden, setSelectedOrden] = useState<string | null>(null);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["conciliacion", "cod"],
    queryFn: () => api.get<CodResponse>("/api/conciliacion/cod"),
  });

  const filtered = useMemo(() => {
    if (!data) return { pendientes: [], liquidados: [], diferencias: [] };
    const term = q.trim().toLowerCase();
    const match = (p: PedidoConc) =>
      !term ||
      p.orden_tienda.toLowerCase().includes(term) ||
      p.orden_melonn.toLowerCase().includes(term) ||
      p.nombre_comprador.toLowerCase().includes(term) ||
      p.ciudad_destino.toLowerCase().includes(term);
    const all = data.pedidos.filter(match);
    return {
      pendientes:  all.filter((p) => !p.liquidado),
      liquidados:  all.filter((p) => p.liquidado),
      diferencias: all.filter((p) => p.liquidado && p.diferencia && Math.abs(p.diferencia) > 1),
    };
  }, [data, q]);

  if (isLoading) return <LoadingState label="Cargando conciliación..." />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  const r = data.resumen;

  return (
    <PageShell
      title="Conciliación COD"
      subtitle={`${r.n_total} pedidos COD entregados · ${r.n_liquidados} liquidados, ${r.n_pendientes} pendientes`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      {/* KPIs */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard
          label="Entregado total"
          value={formatMoneyShort(r.total_entregado)}
          meta={`${r.n_total} pedidos COD`}
          accent="navy"
        />
        <KpiCard
          label="Pendiente cobrar"
          value={formatMoneyShort(r.total_pendiente)}
          meta={`${r.n_pendientes} sin liquidar`}
          accent={r.total_pendiente > 0 ? "rust" : "steel"}
          danger={r.n_pendientes > 0}
        />
        <KpiCard
          label="Ya recibido"
          value={formatMoneyShort(r.total_liquidado)}
          meta={`${r.n_liquidados} liquidados`}
          accent="teal"
        />
        <KpiCard
          label="Con diferencia"
          value={r.n_con_diferencia}
          meta="Monto ≠ esperado"
          accent={r.n_con_diferencia ? "crimson" : "steel"}
          danger={r.n_con_diferencia > 0}
        />
      </div>

      {/* Buscador */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Buscar por orden, cliente o ciudad..."
          className="w-full rounded-md border border-border bg-white pl-9 pr-3 py-2 text-sm text-ink placeholder:text-graphite/60 focus:outline-none focus:ring-2 focus:ring-steel"
        />
      </div>

      <Tabs defaultValue="pendientes">
        <TabsList>
          <TabsTrigger value="pendientes">Pendientes ({filtered.pendientes.length})</TabsTrigger>
          <TabsTrigger value="liquidados">Liquidados ({filtered.liquidados.length})</TabsTrigger>
          {filtered.diferencias.length > 0 && (
            <TabsTrigger value="diferencias">Diferencias ({filtered.diferencias.length})</TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="pendientes">
          <Tabla
            pedidos={filtered.pendientes}
            modo="pendientes"
            canWrite={canWrite}
            onLiquidar={(orden) => setSelectedOrden(orden)}
          />
        </TabsContent>

        <TabsContent value="liquidados">
          <Tabla
            pedidos={filtered.liquidados}
            modo="liquidados"
            canWrite={canWrite}
            onLiquidar={(orden) => setSelectedOrden(orden)}
          />
        </TabsContent>

        {filtered.diferencias.length > 0 && (
          <TabsContent value="diferencias">
            <Tabla
              pedidos={filtered.diferencias}
              modo="diferencias"
              canWrite={canWrite}
              onLiquidar={(orden) => setSelectedOrden(orden)}
            />
          </TabsContent>
        )}
      </Tabs>

      {selectedOrden && (
        <LiquidarModal
          pedido={data.pedidos.find((p) => (p.orden_tienda || p.orden_melonn) === selectedOrden)!}
          onClose={() => setSelectedOrden(null)}
          onDone={() => {
            qc.invalidateQueries({ queryKey: ["conciliacion"] });
            setSelectedOrden(null);
          }}
        />
      )}
    </PageShell>
  );
}

// ── Tabla ────────────────────────────────────────────────────────────

function Tabla({
  pedidos, modo, canWrite, onLiquidar,
}: {
  pedidos: PedidoConc[];
  modo: "pendientes" | "liquidados" | "diferencias";
  canWrite: boolean;
  onLiquidar: (orden: string) => void;
}) {
  if (pedidos.length === 0) {
    return (
      <Card>
        <CardContent className="p-12 text-center text-graphite">
          {modo === "pendientes" ? "✓ Sin pedidos pendientes" : "Sin pedidos"}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-concrete/50 border-b border-border">
            <tr>
              <Th>Orden</Th>
              <Th>Cliente</Th>
              <Th>Ciudad</Th>
              <Th>Entregado</Th>
              <Th align="right">Esperado</Th>
              {modo !== "pendientes" && (
                <>
                  <Th align="right">Recibido</Th>
                  <Th>Liquidado</Th>
                </>
              )}
              {modo === "diferencias" && <Th align="right">Diferencia</Th>}
              {modo === "pendientes" && <Th align="right">Días</Th>}
              <Th></Th>
            </tr>
          </thead>
          <tbody>
            {pedidos.slice(0, 500).map((p) => {
              const orden = p.orden_tienda || p.orden_melonn;
              const diff = p.diferencia ?? 0;
              return (
                <tr key={orden} className="border-b border-border hover:bg-concrete/30">
                  <td className="px-3 py-2.5 font-semibold text-ink whitespace-nowrap">{orden}</td>
                  <td className="px-3 py-2.5 max-w-[180px] truncate">{p.nombre_comprador || "—"}</td>
                  <td className="px-3 py-2.5">{p.ciudad_destino || "—"}</td>
                  <td className="px-3 py-2.5 text-xs tabular-nums text-graphite">
                    {p.fecha_entrega || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums font-semibold">
                    {formatMoney(p.valor_cod)}
                  </td>
                  {modo !== "pendientes" && (
                    <>
                      <td className="px-3 py-2.5 text-right tabular-nums text-teal font-semibold">
                        {p.monto_liquidado != null ? formatMoney(p.monto_liquidado) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-xs tabular-nums">
                        {p.fecha_liquidacion || "—"}
                        {p.autor_liquidacion && (
                          <div className="text-[0.65rem] text-graphite">por {p.autor_liquidacion}</div>
                        )}
                      </td>
                    </>
                  )}
                  {modo === "diferencias" && (
                    <td className={`px-3 py-2.5 text-right tabular-nums font-semibold ${diff < 0 ? "text-crimson" : "text-teal"}`}>
                      {diff > 0 ? "+" : ""}{formatMoney(diff)}
                    </td>
                  )}
                  {modo === "pendientes" && (
                    <td className="px-3 py-2.5 text-right">
                      <span className={p.dias_desde_entrega > 14 ? "text-crimson font-semibold tabular-nums" : "tabular-nums"}>
                        {p.dias_desde_entrega}d
                      </span>
                    </td>
                  )}
                  <td className="px-3 py-2.5 text-right">
                    {canWrite && (
                      <button
                        onClick={() => onLiquidar(orden)}
                        className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold ${
                          p.liquidado
                            ? "border border-border bg-white text-graphite hover:bg-concrete"
                            : "bg-ink text-white hover:bg-black"
                        }`}
                      >
                        {p.liquidado ? "Editar" : <><DollarSign className="h-3 w-3" /> Liquidar</>}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function Th({ children, align = "left" }: { children?: React.ReactNode; align?: "left" | "right" }) {
  const cls = align === "right" ? "text-right" : "text-left";
  return <th className={`px-3 py-2.5 text-[0.6rem] font-bold uppercase tracking-[0.15em] text-graphite ${cls}`}>{children}</th>;
}

// ── Modal de liquidación ─────────────────────────────────────────────

function LiquidarModal({
  pedido, onClose, onDone,
}: { pedido: PedidoConc; onClose: () => void; onDone: () => void }) {
  const orden = pedido.orden_tienda || pedido.orden_melonn;
  const [monto, setMonto] = useState(String(pedido.monto_liquidado ?? pedido.valor_cod));
  const [fecha, setFecha] = useState(
    pedido.fecha_liquidacion || new Date().toISOString().slice(0, 10),
  );
  const [referencia, setReferencia] = useState(pedido.referencia || "");
  const [nota, setNota] = useState("");

  const saveMut = useMutation({
    mutationFn: () =>
      api.post(`/api/conciliacion/${orden}/liquidar`, {
        monto: parseFloat(monto),
        fecha,
        referencia,
        nota,
      }),
    onSuccess: onDone,
  });

  const delMut = useMutation({
    mutationFn: () =>
      fetch(`${process.env.NEXT_PUBLIC_API_URL || ""}/api/conciliacion/${orden}/liquidar`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${localStorage.getItem("maledenim_token")}` },
      }).then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))),
    onSuccess: onDone,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
      <div className="w-full max-w-md rounded-lg bg-white shadow-xl overflow-hidden">
        <div className="flex items-center justify-between bg-ink text-white px-5 py-3">
          <div>
            <p className="text-[0.6rem] font-bold uppercase tracking-[0.2em] text-steel/70">
              {pedido.liquidado ? "Editar liquidación" : "Registrar liquidación"}
            </p>
            <p className="text-base font-bold">Orden {orden}</p>
          </div>
          <button onClick={onClose} className="text-white/70 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-5 space-y-3">
          <div className="rounded-md bg-concrete/50 px-3 py-2 text-sm">
            <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Valor esperado</p>
            <p className="text-base font-bold text-navy">{formatMoney(pedido.valor_cod)}</p>
          </div>

          <Field label="Monto recibido" type="number" value={monto} onChange={setMonto} />
          <Field label="Fecha de liquidación" type="date" value={fecha} onChange={setFecha} />
          <Field label="Referencia / # transferencia" value={referencia} onChange={setReferencia} placeholder="opcional" />
          <Field label="Nota" value={nota} onChange={setNota} placeholder="opcional" />

          {saveMut.error && (
            <div className="flex items-center gap-2 rounded-md bg-crimson/10 border border-crimson/30 px-3 py-2 text-xs text-crimson">
              <AlertTriangle className="h-3.5 w-3.5" />
              {(saveMut.error as Error).message}
            </div>
          )}

          <div className="flex justify-between gap-2 pt-2">
            {pedido.liquidado ? (
              <button
                onClick={() => {
                  if (confirm("¿Eliminar esta liquidación?")) delMut.mutate();
                }}
                disabled={delMut.isPending}
                className="rounded-md border border-crimson/40 bg-white px-3 py-2 text-xs font-semibold text-crimson hover:bg-crimson/5 disabled:opacity-50"
              >
                {delMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Eliminar"}
              </button>
            ) : <div />}
            <div className="flex gap-2">
              <button onClick={onClose} className="rounded-md border border-border bg-white px-3 py-2 text-xs font-semibold text-graphite hover:bg-concrete">
                Cancelar
              </button>
              <button
                onClick={() => saveMut.mutate()}
                disabled={saveMut.isPending || !monto || !fecha}
                className="inline-flex items-center gap-1.5 rounded-md bg-ink px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50"
              >
                {saveMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <><CheckCircle className="h-3 w-3" /> Guardar</>}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({
  label, value, onChange, type = "text", placeholder,
}: {
  label: string; value: string; onChange: (v: string) => void;
  type?: string; placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
      />
    </div>
  );
}
