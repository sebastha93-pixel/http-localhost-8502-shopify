"use client";

/**
 * Lista de informes de corte — solo órdenes en estado 'cortada' con datos
 * del cierre: consumo real, unidades, precio.
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FileText, Lock } from "lucide-react";

interface OrdenCortada {
  id: string;
  consecutivo: string;
  referencia_lote?: string;
  cantidad_programada?: number;
  unidades_cortadas?: Record<string, number>;
  metros_consumidos?: number;
  consumo_real_cortador?: number;
  diferencia_pct?: number;
  precio_corte?: number;
  fecha_entrega?: string;
  responsable?: string;
  referencia?: { codigo_referencia: string; nombre: string; tela?: string };
}

export default function InformesCortePage() {
  const q = useQuery<{ ordenes: OrdenCortada[] }>({
    queryKey: ["produccion", "corte", "cortadas"],
    queryFn: () => api.get("/api/produccion/corte?estado=cortada&limit=200"),
  });

  if (q.isLoading) return <LoadingState label="Cargando informes…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const lista = q.data?.ordenes || [];

  return (
    <PageShell title="Informes de corte" subtitle="Órdenes cerradas con cierre del cortador">
      <div className="flex items-center justify-between">
        <p className="text-xs text-graphite">{lista.length} informe(s)</p>
      </div>

      {lista.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center">
            <FileText className="mx-auto h-8 w-8 text-graphite" />
            <p className="mt-3 text-sm text-graphite">
              Aún no hay órdenes cerradas. Cierra una orden en /produccion/corte para ver su informe aquí.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Consecutivo</th>
                  <th className="px-4 py-2">Referencia</th>
                  <th className="px-4 py-2">Lote</th>
                  <th className="px-4 py-2 text-right">Programado</th>
                  <th className="px-4 py-2 text-right">Cortado</th>
                  <th className="px-4 py-2 text-right">Metros real</th>
                  <th className="px-4 py-2 text-right">Δ %</th>
                  <th className="px-4 py-2 text-right">Precio</th>
                  <th className="px-4 py-2">Entrega</th>
                  <th className="px-4 py-2">Estado</th>
                </tr>
              </thead>
              <tbody>
                {lista.map((o) => {
                  const totalCortado = Object.values(o.unidades_cortadas || {})
                    .reduce<number>((s, n) => s + (Number(n) || 0), 0);
                  const diffTone = (o.diferencia_pct || 0) > 0 ? "text-terracotta" : (o.diferencia_pct || 0) < 0 ? "text-teal" : "text-graphite";
                  return (
                    <tr key={o.id} className="border-b border-border/40 hover:bg-cloud/40">
                      <td className="px-4 py-2 font-semibold tabular text-navy-600">
                        <Link href={`/produccion/corte/${o.id}`} className="hover:underline">
                          {o.consecutivo}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-ink-900">
                        {o.referencia?.codigo_referencia || "—"}
                        <div className="text-[0.6rem] text-graphite">
                          {o.referencia?.nombre} {o.referencia?.tela ? `· ${o.referencia.tela}` : ""}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-graphite">{o.referencia_lote || "—"}</td>
                      <td className="px-4 py-2 text-right tabular text-graphite">{o.cantidad_programada || "—"}</td>
                      <td className="px-4 py-2 text-right tabular font-semibold text-ink-900">{totalCortado || "—"}</td>
                      <td className="px-4 py-2 text-right tabular">{o.consumo_real_cortador != null ? `${o.consumo_real_cortador} m` : "—"}</td>
                      <td className={`px-4 py-2 text-right tabular font-semibold ${diffTone}`}>
                        {o.diferencia_pct != null ? `${o.diferencia_pct}%` : "—"}
                      </td>
                      <td className="px-4 py-2 text-right tabular">
                        {o.precio_corte != null ? `$${Number(o.precio_corte).toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}
                      </td>
                      <td className="px-4 py-2 text-graphite tabular text-[0.65rem]">{o.fecha_entrega || "—"}</td>
                      <td className="px-4 py-2">
                        <Badge tone="normal"><Lock className="inline h-2.5 w-2.5 mr-1" />Cortada</Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </PageShell>
  );
}
