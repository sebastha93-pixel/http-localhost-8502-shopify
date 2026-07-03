"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Plus } from "lucide-react";

interface Ingreso {
  id: string;
  numero_ingreso: string;
  textilera: string;
  numero_documento: string;
  tipo_documento: string;
  fecha: string;
  total_rollos: number;
  total_metros: number;
  estado: string;
}

export default function IngresosPage() {
  const router = useRouter();
  const q = useQuery<{ ingresos: Ingreso[] }>({
    queryKey: ["produccion", "ingresos"],
    queryFn: () => api.get("/api/produccion/ingreso?limit=100"),
  });

  if (q.isLoading) return <LoadingState label="Cargando ingresos…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const ingresos = q.data?.ingresos || [];

  return (
    <PageShell
      title="Ingresos de tela"
      subtitle={`${ingresos.length} órdenes de ingreso registradas`}
      onRefresh={() => q.refetch()}
    >
      <div className="flex justify-end">
        <Link
          href="/produccion/ingreso/nuevo"
          className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700"
        >
          <Plus className="h-4 w-4" /> Nuevo ingreso
        </Link>
      </div>

      <Card>
        <CardContent className="p-0">
          {ingresos.length === 0 ? (
            <p className="p-8 text-center text-sm text-graphite">
              No hay ingresos registrados aún. Toca "Nuevo ingreso" para arrancar.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.62rem] uppercase tracking-[0.12em] text-graphite">
                  <th className="px-4 py-3">Número</th>
                  <th className="px-4 py-3">Textilera</th>
                  <th className="px-4 py-3">Doc</th>
                  <th className="px-4 py-3">Fecha</th>
                  <th className="px-4 py-3 text-right">Rollos</th>
                  <th className="px-4 py-3 text-right">Metros</th>
                  <th className="px-4 py-3">Estado</th>
                </tr>
              </thead>
              <tbody>
                {ingresos.map((i) => (
                  <tr key={i.id}
                    onClick={() => router.push(`/produccion/ingreso/${i.id}`)}
                    className="border-b border-border hover:bg-cloud/50 cursor-pointer">
                    <td className="px-4 py-3 tabular">
                      <Link href={`/produccion/ingreso/${i.id}`}
                        className="font-semibold text-navy-600 hover:underline"
                        onClick={(e) => e.stopPropagation()}>
                        {i.numero_ingreso}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-ink-900">{i.textilera}</td>
                    <td className="px-4 py-3 text-graphite text-xs">
                      {i.tipo_documento} · {i.numero_documento}
                    </td>
                    <td className="px-4 py-3 text-graphite tabular">{i.fecha}</td>
                    <td className="px-4 py-3 text-right tabular">{i.total_rollos}</td>
                    <td className="px-4 py-3 text-right tabular">{i.total_metros?.toLocaleString("es-CO", { maximumFractionDigits: 2 })}</td>
                    <td className="px-4 py-3">
                      <Badge tone={i.estado === "recibida_completa" ? "normal" : "info"}>
                        {i.estado.replace(/_/g, " ")}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
