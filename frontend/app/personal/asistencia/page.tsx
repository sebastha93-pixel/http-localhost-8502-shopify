"use client";

/**
 * Asistencia — jornadas calculadas por día.
 *
 * Lo que se ve aquí es DERIVADO: se puede borrar y reconstruir desde los
 * eventos del dispositivo. Por eso el botón "Recalcular" no es peligroso.
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard } from "@/components/kpi-card";
import { Lock, RefreshCw } from "lucide-react";
import {
  Empleado, Jornada, etiquetaJornada, fechaCorta, hora, hoyISO, minutosAHoras,
} from "@/lib/personal";

const ESTADOS = [
  { k: "", label: "Todos" },
  { k: "completa", label: "Completas" },
  { k: "tarde", label: "Tarde" },
  { k: "salida_anticipada", label: "Salida antes" },
  { k: "incompleta", label: "Incompletas" },
  { k: "ausente", label: "Ausentes" },
];

export default function AsistenciaPage() {
  const qc = useQueryClient();
  const [desde, setDesde] = useState(hoyISO());
  const [hasta, setHasta] = useState(hoyISO());
  const [estado, setEstado] = useState("");
  const [err, setErr] = useState("");

  const q = useQuery<{ jornadas: Jornada[]; total: number }>({
    queryKey: ["personal", "asistencia", desde, hasta, estado],
    queryFn: () =>
      api.get(
        `/api/personal/asistencia?desde=${desde}&hasta=${hasta}` +
          (estado ? `&estado=${estado}` : "") + "&limit=1000",
      ),
  });

  const empQ = useQuery<{ empleados: Empleado[] }>({
    queryKey: ["personal", "empleados", "nombres"],
    queryFn: () => api.get("/api/personal/empleados?limit=500"),
    staleTime: 10 * 60_000,
  });

  const nombre = (id: string) =>
    empQ.data?.empleados.find((e) => e.id === id)?.nombre_completo ?? "—";

  const recalcular = useMutation({
    mutationFn: (empleadoId: string) =>
      api.post("/api/personal/asistencia/recalcular", {
        empleado_id: empleadoId, desde, hasta,
      }),
    onSuccess: () => {
      setErr("");
      qc.invalidateQueries({ queryKey: ["personal", "asistencia"] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  const resumen = useMemo(() => {
    const j = q.data?.jornadas ?? [];
    return {
      total: j.length,
      trabajado: j.reduce((s, x) => s + (x.minutos_trabajados || 0), 0),
      tarde: j.reduce((s, x) => s + (x.minutos_tarde || 0), 0),
      posible: j.reduce((s, x) => s + (x.minutos_posible_extra || 0), 0),
      aprobada: j.reduce((s, x) => s + (x.minutos_extra_aprobada || 0), 0),
    };
  }, [q.data]);

  if (q.isLoading) return <LoadingState label="Cargando jornadas…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const jornadas = q.data?.jornadas ?? [];

  return (
    <PageShell
      title="Asistencia"
      subtitle={`${resumen.total} jornada${resumen.total === 1 ? "" : "s"} en el rango`}
      isFetching={q.isFetching}
      onRefresh={() => q.refetch()}
    >
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard label="Tiempo trabajado" value={minutosAHoras(resumen.trabajado)} accent="teal" />
        <KpiCard label="Minutos tarde" value={resumen.tarde}
                 variant={resumen.tarde > 0 ? "danger" : "success"} />
        <KpiCard label="Permanencia adicional" value={minutosAHoras(resumen.posible)}
                 meta="hecho observado, no es crédito" />
        <KpiCard label="Extra reconocida" value={minutosAHoras(resumen.aprobada)}
                 meta="autorizada previamente" accent="navy" />
      </div>

      <Card className="mt-4">
        <CardContent className="flex flex-wrap items-end gap-3 py-4">
          <label className="text-xs text-graphite">
            Desde
            <input type="date" value={desde} onChange={(e) => setDesde(e.target.value)}
                   className="mt-1 block rounded-sm border border-border bg-card px-2 py-1 text-sm text-ink-900" />
          </label>
          <label className="text-xs text-graphite">
            Hasta
            <input type="date" value={hasta} onChange={(e) => setHasta(e.target.value)}
                   className="mt-1 block rounded-sm border border-border bg-card px-2 py-1 text-sm text-ink-900" />
          </label>
          <div className="flex flex-wrap gap-1">
            {ESTADOS.map((e) => (
              <button key={e.k} onClick={() => setEstado(e.k)}
                className={`rounded-sm border px-2 py-1 text-[0.7rem] font-medium transition-colors ${
                  estado === e.k
                    ? "border-navy-600 bg-navy-600 text-white"
                    : "border-border bg-card text-graphite hover:bg-cloud"
                }`}>
                {e.label}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {err && (
        <p role="alert" className="mt-3 rounded-sm border border-terracotta/25 bg-terracotta/10 px-3 py-2 text-sm text-terracotta">
          {err}
        </p>
      )}

      <Card className="mt-4">
        <CardContent className="p-0">
          {jornadas.length === 0 ? (
            <p className="px-5 py-8 text-sm text-graphite">
              No hay jornadas calculadas en este rango. Si esperabas ver algo,
              revisa que los empleados tengan horario asignado y que hayan
              llegado marcaciones.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border">
                  <tr className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                    <th className="px-5 py-2.5 text-left">Empleado</th>
                    <th className="px-3 py-2.5 text-left">Día</th>
                    <th className="px-3 py-2.5 text-left">Estado</th>
                    <th className="px-3 py-2.5 text-right">Entrada</th>
                    <th className="px-3 py-2.5 text-right">Salida</th>
                    <th className="px-3 py-2.5 text-right">Trabajado</th>
                    <th className="px-3 py-2.5 text-right">Tarde</th>
                    <th className="px-5 py-2.5 text-right"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {jornadas.map((j) => {
                    const e = etiquetaJornada(j.estado_asistencia);
                    const dia = j.work_date.slice(0, 10);
                    return (
                      <tr key={`${j.empleado_id}-${dia}`} className="hover:bg-cloud/50">
                        <td className="px-5 py-2.5 text-ink-900">
                          <div className="flex items-center gap-1.5">
                            {nombre(j.empleado_id)}
                            {j.bloqueado_at && (
                              <Lock className="h-3 w-3 text-graphite"
                                    aria-label="periodo cerrado" />
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-2.5 text-graphite">{fechaCorta(dia)}</td>
                        <td className="px-3 py-2.5"><Badge tone={e.tone}>{e.label}</Badge></td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-graphite">
                          {hora(j.primera_entrada_at)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-graphite">
                          {hora(j.ultima_salida_at)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-ink-900">
                          {minutosAHoras(j.minutos_trabajados)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          {j.minutos_tarde
                            ? <span className="text-terracotta">{j.minutos_tarde}</span>
                            : <span className="text-graphite">—</span>}
                        </td>
                        <td className="px-5 py-2.5 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Link href={`/personal/asistencia/${j.empleado_id}/${dia}`}
                                  className="text-xs font-medium text-navy-600 hover:underline">
                              Detalle
                            </Link>
                            {!j.bloqueado_at && (
                              <button
                                onClick={() => recalcular.mutate(j.empleado_id)}
                                disabled={recalcular.isPending}
                                title="Recalcular — es idempotente, no daña nada"
                                className="text-graphite transition-colors hover:text-ink-900 disabled:opacity-40"
                              >
                                <RefreshCw className={`h-3.5 w-3.5 ${
                                  recalcular.isPending ? "animate-spin" : ""}`} />
                              </button>
                            )}
                          </div>
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
