"use client";

/**
 * Detalle de remisión a confeccionista.
 */
import { useParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Truck, Loader2 } from "lucide-react";

interface Item {
  id: string;
  orden_corte_id: string;
  orden_corte?: {
    consecutivo: string;
    referencia_lote?: string;
    cantidad_programada?: number;
    unidades_cortadas?: Record<string, number>;
    fecha_entrega?: string;
    referencia?: { codigo_referencia: string; nombre: string; tela?: string };
  };
}

interface Remision {
  id: string;
  consecutivo: string;
  fecha_recogida: string;
  estado: string;
  created_at: string;
  confeccionista?: { nombre: string; telefono?: string; direccion?: string };
  items: Item[];
}

export default function RemisionDetallePage() {
  const params = useParams();
  const id = params?.id as string;
  const qc = useQueryClient();

  const q = useQuery<Remision>({
    queryKey: ["produccion", "remision", id],
    queryFn: () => api.get(`/api/produccion/remisiones/${id}`),
    enabled: !!id,
  });

  const recogida = useMutation({
    mutationFn: () => api.post(`/api/produccion/remisiones/${id}/recogida`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["produccion", "remision", id] }),
  });

  if (q.isLoading) return <LoadingState label="Cargando remisión…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const rem = q.data;
  const yaRecogida = rem.estado === "recogida";

  const totalUnidades = (rem.items || []).reduce((s, it) => {
    const u = it.orden_corte?.unidades_cortadas || {};
    return s + Object.values(u).reduce((x, y) => x + (Number(y) || 0), 0);
  }, 0);

  return (
    <PageShell title={rem.consecutivo} subtitle={rem.confeccionista?.nombre || "—"}>
      <div className="flex items-center justify-between">
        <Link href="/produccion/remisiones" className="inline-flex items-center gap-1 text-xs text-graphite hover:text-ink-900">
          <ArrowLeft className="h-3.5 w-3.5" /> Volver a remisiones
        </Link>
        <Badge tone={yaRecogida ? "normal" : "pendiente"}>{rem.estado}</Badge>
      </div>

      {/* Info general */}
      <Card>
        <CardContent className="p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
          <Info label="Confeccionista"   value={rem.confeccionista?.nombre || "—"} />
          <Info label="Teléfono"         value={rem.confeccionista?.telefono || "—"} />
          <Info label="Dirección"        value={rem.confeccionista?.direccion || "—"} />
          <Info label="Fecha recogida"   value={rem.fecha_recogida} />
          <Info label="Órdenes"          value={String(rem.items?.length || 0)} />
          <Info label="Total unidades"   value={String(totalUnidades)} />
        </CardContent>
      </Card>

      {/* Items */}
      <Card>
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border">
            <p className="section-label">Órdenes de corte entregadas</p>
          </div>
          {(rem.items || []).length === 0 ? (
            <div className="p-8 text-center text-xs text-graphite">Sin órdenes.</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Consecutivo</th>
                  <th className="px-4 py-2">Referencia</th>
                  <th className="px-4 py-2">Lote</th>
                  <th className="px-4 py-2 text-right">Cantidad</th>
                  <th className="px-4 py-2">Entrega corte</th>
                </tr>
              </thead>
              <tbody>
                {(rem.items || []).map((it) => {
                  const totalOC = Object.values(it.orden_corte?.unidades_cortadas || {})
                    .reduce((x, y) => x + (Number(y) || 0), 0);
                  return (
                    <tr key={it.id} className="border-b border-border/40 hover:bg-cloud/40">
                      <td className="px-4 py-2 font-semibold tabular text-navy-600">
                        <Link href={`/produccion/corte/${it.orden_corte_id}`} className="hover:underline">
                          {it.orden_corte?.consecutivo || "—"}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-ink-900">
                        {it.orden_corte?.referencia?.codigo_referencia || "—"}
                        <div className="text-[0.6rem] text-graphite">
                          {it.orden_corte?.referencia?.nombre}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-graphite">{it.orden_corte?.referencia_lote || "—"}</td>
                      <td className="px-4 py-2 text-right tabular">
                        {totalOC || it.orden_corte?.cantidad_programada || "—"}
                      </td>
                      <td className="px-4 py-2 text-graphite text-[0.65rem] tabular">
                        {it.orden_corte?.fecha_entrega || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {!yaRecogida && (
        <div className="flex justify-end">
          <button onClick={() => recogida.mutate()} disabled={recogida.isPending}
            className="inline-flex items-center gap-2 rounded-sm bg-teal px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
            {recogida.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Truck className="h-4 w-4" />}
            Marcar como recogida
          </button>
        </div>
      )}
    </PageShell>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.6rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className="mt-1 text-sm text-ink-900">{value}</p>
    </div>
  );
}
