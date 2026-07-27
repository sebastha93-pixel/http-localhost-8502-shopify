"use client";

/**
 * Incidencias — lo que el motor no pudo interpretar solo.
 *
 * El sistema nunca "arregla" una marcación en silencio: cuando algo no cuadra
 * levanta una incidencia y espera decisión humana. Esta es esa bandeja.
 */
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2 } from "lucide-react";
import {
  Empleado, SEVERIDAD, TIPO_INCIDENCIA, fechaCorta,
} from "@/lib/personal";

interface Incidencia {
  id: string;
  empleado_id?: string | null;
  work_date?: string | null;
  tipo_incidencia: string;
  severidad: string;
  descripcion: string;
  estado: string;
  detectada_at: string;
}

const TABS = [
  { k: "abierta", label: "Abiertas" },
  { k: "en_revision", label: "En revisión" },
  { k: "resuelta", label: "Resueltas" },
  { k: "", label: "Todas" },
];

export default function IncidenciasPage() {
  const [tab, setTab] = useState("abierta");

  const q = useQuery<{ incidencias: Incidencia[] }>({
    queryKey: ["personal", "incidencias", tab],
    queryFn: () => {
      const p = new URLSearchParams({ limit: "300" });
      if (tab) p.set("estado", tab);
      return api.get(`/api/personal/incidencias?${p}`);
    },
  });

  const empQ = useQuery<{ empleados: Empleado[] }>({
    queryKey: ["personal", "empleados", "nombres"],
    queryFn: () => api.get("/api/personal/empleados?limit=500"),
    staleTime: 10 * 60_000,
  });
  const nombre = (id?: string | null) =>
    id ? empQ.data?.empleados.find((e) => e.id === id)?.nombre_completo ?? "—"
       : "Sin empleado asignado";

  if (q.isLoading) return <LoadingState label="Cargando incidencias…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const incidencias = q.data?.incidencias ?? [];

  return (
    <PageShell
      title="Incidencias"
      subtitle={`${incidencias.length} en esta bandeja`}
      isFetching={q.isFetching}
      onRefresh={() => q.refetch()}
    >
      <div className="flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button key={t.k} onClick={() => setTab(t.k)}
            className={`rounded-sm border px-3 py-1.5 text-xs font-medium transition-colors ${
              tab === t.k
                ? "border-navy-600 bg-navy-600 text-white"
                : "border-border bg-card text-graphite hover:bg-cloud"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      <Card className="mt-4">
        <CardContent className="p-0">
          {incidencias.length === 0 ? (
            <div className="flex items-center gap-2 px-5 py-8 text-sm text-graphite">
              <CheckCircle2 className="h-4 w-4 text-sage" />
              Nada por revisar en esta bandeja.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border">
                  <tr className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                    <th className="px-5 py-2.5 text-left">Tipo</th>
                    <th className="px-3 py-2.5 text-left">Empleado</th>
                    <th className="px-3 py-2.5 text-left">Día</th>
                    <th className="px-3 py-2.5 text-left">Detalle</th>
                    <th className="px-5 py-2.5 text-right">Severidad</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {incidencias.map((i) => (
                    <tr key={i.id} className="hover:bg-cloud/50">
                      <td className="px-5 py-2.5 text-ink-900">
                        {TIPO_INCIDENCIA[i.tipo_incidencia] ?? i.tipo_incidencia}
                      </td>
                      <td className="px-3 py-2.5 text-graphite">
                        {i.empleado_id && i.work_date ? (
                          <Link
                            href={`/personal/asistencia/${i.empleado_id}/${i.work_date.slice(0, 10)}`}
                            className="text-navy-600 hover:underline">
                            {nombre(i.empleado_id)}
                          </Link>
                        ) : nombre(i.empleado_id)}
                      </td>
                      <td className="px-3 py-2.5 text-graphite">
                        {fechaCorta(i.work_date)}
                      </td>
                      <td className="max-w-md px-3 py-2.5 text-graphite">
                        {i.descripcion}
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        <Badge tone={SEVERIDAD[i.severidad] ?? "neutral"}>
                          {i.severidad}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
