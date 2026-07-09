"use client";

/**
 * Mis despachos — control interno del cortador.
 * Por cada corte cerrado: unidades cortadas por talla + total y el estado
 * del despacho. Sin insumos, sin precios, sin datos de proveedores.
 * Al marcar el despacho se dispara el WhatsApp al confeccionista.
 */
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtFecha } from "@/lib/utils";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { CheckCircle, Loader2, Truck } from "lucide-react";

interface Despacho {
  id: string;
  consecutivo: string;
  referencia?: string;
  nombre?: string;
  responsable?: string;
  fecha_entrega?: string;
  unidades: Record<string, number>;
  total: number;
  remision?: {
    id: string;
    consecutivo?: string;
    despachada: boolean;
    fecha_recogida?: string;
  } | null;
}

interface WaSalida { referencia: string; enviado: boolean; wa_url: string }

export default function MisDespachosPage() {
  const qc = useQueryClient();
  const [err, setErr] = useState("");
  const [waInfo, setWaInfo] = useState<{ consecutivo: string; wa: WaSalida[] } | null>(null);

  const q = useQuery<{ despachos: Despacho[] }>({
    queryKey: ["produccion", "mis-despachos"],
    queryFn: () => api.get("/api/produccion/mis-despachos"),
  });

  const despachar = useMutation({
    mutationFn: (remId: string) =>
      api.post<{ ok: boolean; remision: { whatsapp?: WaSalida[]; consecutivo?: string } }>(
        `/api/produccion/remisiones/${remId}/recogida`),
    onSuccess: (data) => {
      setErr("");
      qc.invalidateQueries({ queryKey: ["produccion", "mis-despachos"] });
      const wa = data.remision?.whatsapp || [];
      setWaInfo({ consecutivo: data.remision?.consecutivo || "", wa });
      // Si la Cloud API no envió sola, abrir WhatsApp con el mensaje listo
      const pendiente = wa.find((w) => !w.enviado && w.wa_url);
      if (pendiente) window.open(pendiente.wa_url, "_blank");
    },
    onError: (e: Error) => setErr(`No se pudo marcar el despacho: ${e.message}`),
  });

  if (q.isLoading) return <LoadingState label="Cargando tus despachos…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const rows = q.data?.despachos || [];
  const totalDespachado = rows.filter((r) => r.remision?.despachada).reduce((s, r) => s + r.total, 0);
  const totalPendiente = rows.filter((r) => !r.remision?.despachada).reduce((s, r) => s + r.total, 0);

  return (
    <PageShell
      title="Mis despachos"
      subtitle="Unidades cortadas y entregadas por lote — control interno"
      onRefresh={() => q.refetch()}
    >
      <Card>
        <CardContent className="p-4 grid grid-cols-2 md:grid-cols-3 gap-4">
          <Kpi label="Cortes cerrados" value={rows.length.toString()} />
          <Kpi label="Unidades despachadas" value={totalDespachado.toLocaleString("es-CO")} />
          <Kpi label="Unidades por despachar" value={totalPendiente.toLocaleString("es-CO")} />
        </CardContent>
      </Card>

      {err && (
        <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
          {err}
        </div>
      )}
      {waInfo && (
        <div className="rounded-sm border border-teal/40 bg-teal/[0.06] px-3 py-2 text-xs text-teal flex flex-wrap items-center gap-2">
          <CheckCircle className="h-4 w-4 flex-none" />
          <span className="font-semibold">Despacho marcado.</span>
          {waInfo.wa.length === 0 ? (
            <span>El encargado notificará al confeccionista.</span>
          ) : waInfo.wa.every((w) => w.enviado) ? (
            <span>WhatsApp enviado al confeccionista para que acepte el lote.</span>
          ) : (
            <>
              <span>Envía el WhatsApp al confeccionista:</span>
              {waInfo.wa.filter((w) => !w.enviado).map((w, i) => (
                <a key={i} href={w.wa_url} target="_blank" rel="noopener noreferrer"
                  className="rounded-sm bg-[#25D366] px-2.5 py-1 text-[0.7rem] font-semibold uppercase tracking-widest text-white hover:opacity-90">
                  WhatsApp REF {w.referencia}
                </a>
              ))}
            </>
          )}
        </div>
      )}

      <Card>
        <CardContent className="p-0">
          {rows.length === 0 ? (
            <p className="p-8 text-center text-sm text-graphite">
              Aún no tienes cortes cerrados. Cierra el informe de corte en{" "}
              <Link href="/produccion/corte" className="text-navy-600 hover:underline">Orden de corte</Link>.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-cloud/40 border-b border-border">
                  <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                    <th className="px-4 py-2">Corte</th>
                    <th className="px-4 py-2">Referencia</th>
                    <th className="px-4 py-2">Unidades por talla</th>
                    <th className="px-4 py-2 text-right">Total</th>
                    <th className="px-4 py-2">Despacho</th>
                    <th className="px-4 py-2 text-right"></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const tallas = Object.entries(r.unidades)
                      .filter(([, v]) => Number(v) > 0)
                      .sort(([a], [b]) => Number(a) - Number(b));
                    return (
                      <tr key={r.id} className="border-b border-border/40 hover:bg-cloud/30">
                        <td className="px-4 py-2.5">
                          <Link href={`/produccion/corte/${r.id}`} className="font-semibold tabular text-navy-600 hover:underline">
                            {r.consecutivo}
                          </Link>
                        </td>
                        <td className="px-4 py-2.5 text-ink-900">
                          <span className="font-semibold">{r.referencia || "—"}</span>
                          {r.nombre && <span className="block text-[0.7rem] text-graphite">{r.nombre}</span>}
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex flex-wrap gap-1">
                            {tallas.length === 0 ? <span className="text-graphite">—</span> :
                              tallas.map(([t, v]) => (
                                <span key={t} className="rounded-sm bg-navy-600/[0.07] px-1.5 py-0.5 text-[0.7rem] font-semibold tabular text-navy-600">
                                  T{t}: {v}
                                </span>
                              ))}
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-right font-display text-sm tabular text-ink-900">
                          {r.total.toLocaleString("es-CO")}
                        </td>
                        <td className="px-4 py-2.5">
                          {!r.remision ? (
                            <span className="text-[0.7rem] text-graphite">Esperando remisión de insumos</span>
                          ) : r.remision.despachada ? (
                            <span className="inline-flex items-center gap-1 rounded-sm bg-teal/10 px-1.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-widest text-teal">
                              <CheckCircle className="h-3 w-3" /> Despachado
                            </span>
                          ) : (
                            <span className="rounded-sm bg-amber-500/10 px-1.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-widest text-amber-700">
                              Listo para entrega
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          {r.remision && !r.remision.despachada && (
                            <button
                              onClick={() => despachar.mutate(r.remision!.id)}
                              disabled={despachar.isPending}
                              className="inline-flex items-center gap-1.5 rounded-sm bg-navy-600 px-3 py-1.5 text-[0.7rem] font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40">
                              {despachar.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Truck className="h-3 w-3" />}
                              Marcar despachado
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.7rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className="mt-1 font-display text-xl text-ink-900 tabular">{value}</p>
    </div>
  );
}
