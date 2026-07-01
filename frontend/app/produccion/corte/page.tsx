"use client";

/**
 * Lista de órdenes de corte. Estado: borrador → autorizada → en_proceso → cortada.
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Plus, Scissors } from "lucide-react";

interface OrdenCorte {
  id: string;
  consecutivo: string;
  tono?: string;
  largo_trazo: number;
  num_capas: number;
  prendas_estimadas: number;
  metros_consumidos: number;
  consumo_real_cortador?: number;
  diferencia_pct?: number;
  responsable?: string;
  fecha_limite?: string;
  estado: string;
  created_at: string;
  referencia?: {
    codigo_referencia: string;
    nombre: string;
    tela?: string;
  };
}

function tonoBadge(estado: string): "normal" | "pendiente" | "critico" | "info" {
  if (estado === "cortada") return "normal";
  if (estado === "en_proceso") return "info";
  if (estado === "autorizada") return "info";
  return "pendiente";
}

export default function CortesPage() {
  const q = useQuery<{ ordenes: OrdenCorte[] }>({
    queryKey: ["produccion", "corte"],
    queryFn: () => api.get("/api/produccion/corte"),
  });

  if (q.isLoading) return <LoadingState label="Cargando órdenes de corte…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const ordenes = q.data?.ordenes || [];

  return (
    <PageShell title="Órdenes de corte" subtitle="Trazo · curva · consumo real">
      <div className="flex items-center justify-between">
        <p className="text-xs text-graphite">{ordenes.length} orden(es)</p>
        <Link href="/produccion/corte/nueva"
          className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700">
          <Plus className="h-3.5 w-3.5" /> Nueva orden
        </Link>
      </div>

      {ordenes.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center">
            <Scissors className="mx-auto h-8 w-8 text-graphite" />
            <p className="mt-3 text-sm text-graphite">Aún no hay órdenes de corte. Crea la primera.</p>
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
                  <th className="px-4 py-2">Tono</th>
                  <th className="px-4 py-2 text-right">Trazo m</th>
                  <th className="px-4 py-2 text-right">Capas</th>
                  <th className="px-4 py-2 text-right">Prendas est.</th>
                  <th className="px-4 py-2 text-right">Δ Real</th>
                  <th className="px-4 py-2">Responsable</th>
                  <th className="px-4 py-2">Estado</th>
                </tr>
              </thead>
              <tbody>
                {ordenes.map((o) => (
                  <tr key={o.id} className="border-b border-border/40 hover:bg-cloud/40">
                    <td className="px-4 py-2 font-semibold tabular text-navy-600">
                      <Link href={`/produccion/corte/${o.id}`} className="hover:underline">
                        {o.consecutivo}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-ink-900">
                      {o.referencia?.codigo_referencia || "—"}
                      <div className="text-[0.6rem] text-graphite">{o.referencia?.nombre || ""}</div>
                    </td>
                    <td className="px-4 py-2 text-graphite">{o.tono || "—"}</td>
                    <td className="px-4 py-2 text-right tabular">{o.largo_trazo}</td>
                    <td className="px-4 py-2 text-right tabular">{o.num_capas}</td>
                    <td className="px-4 py-2 text-right tabular">{o.prendas_estimadas}</td>
                    <td className={`px-4 py-2 text-right tabular ${(o.diferencia_pct || 0) > 0 ? "text-terracotta" : "text-teal"}`}>
                      {o.diferencia_pct != null ? `${o.diferencia_pct}%` : "—"}
                    </td>
                    <td className="px-4 py-2 text-graphite">{o.responsable || "—"}</td>
                    <td className="px-4 py-2">
                      <Badge tone={tonoBadge(o.estado)}>{o.estado}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </PageShell>
  );
}
