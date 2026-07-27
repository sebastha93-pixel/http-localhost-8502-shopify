"use client";

/**
 * Dashboard de Personal — la foto del día.
 * Fuente: GET /api/personal/dashboard (respeta el alcance del rol).
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { KpiCard } from "@/components/kpi-card";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, ArrowRight, CheckCircle2, Clock } from "lucide-react";
import {
  Dashboard, Jornada, etiquetaJornada, fechaCorta, fechaLarga, hora, hoyISO,
  minutosAHoras,
} from "@/lib/personal";

export default function PersonalDashboardPage() {
  const q = useQuery<Dashboard>({
    queryKey: ["personal", "dashboard"],
    queryFn: () => api.get("/api/personal/dashboard"),
    refetchInterval: 180_000,
  });

  const hoyQ = useQuery<{ jornadas: Jornada[] }>({
    queryKey: ["personal", "asistencia", "hoy"],
    queryFn: () =>
      api.get(`/api/personal/asistencia?desde=${hoyISO()}&hasta=${hoyISO()}&limit=200`),
  });

  // Las jornadas traen empleado_id, no el nombre. Mostrar un UUID recortado
  // sería inútil para quien lee el tablero.
  const empQ = useQuery<{ empleados: { id: string; nombre_completo: string }[] }>({
    queryKey: ["personal", "empleados", "nombres"],
    queryFn: () => api.get("/api/personal/empleados?solo_vigentes=true&limit=500"),
    staleTime: 10 * 60_000,
  });
  const nombre = (id: string) =>
    empQ.data?.empleados.find((e) => e.id === id)?.nombre_completo ?? "—";

  if (q.isLoading) return <LoadingState label="Calculando el día…" />;
  if (q.isError || !q.data)
    return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const d = q.data;
  const jornadas = hoyQ.data?.jornadas ?? [];
  const conNovedad = jornadas.filter((j) =>
    ["tarde", "salida_anticipada", "incompleta", "ausente"].includes(j.estado_asistencia),
  );

  return (
    <PageShell
      title="Personal"
      subtitle={fechaLarga(d.fecha)}
      isFetching={q.isFetching}
      onRefresh={() => { q.refetch(); hoyQ.refetch(); }}
    >
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <KpiCard label="Programados hoy" value={d.programados} accent="navy"
                 meta={`${d.descanso} en descanso o festivo`} />
        <KpiCard label="Presentes" value={d.presentes} accent="teal"
                 meta={d.en_permiso ? `${d.en_permiso} con permiso` : undefined} />
        <KpiCard label="Ausentes" value={d.ausentes}
                 variant={d.ausentes > 0 ? "danger" : "default"} />
        <KpiCard label="Llegadas tarde" value={d.tarde}
                 variant={d.tarde > 0 ? "danger" : "success"} />
        <KpiCard
          label="Puntualidad"
          value={d.puntualidad_pct === null ? "—" : `${d.puntualidad_pct}%`}
          meta={d.puntualidad_pct === null ? "sin marcaciones aún" : "de los que vinieron"}
          variant={
            d.puntualidad_pct === null ? "default"
              : d.puntualidad_pct >= 90 ? "success"
              : d.puntualidad_pct >= 75 ? "default" : "danger"
          }
        />
      </div>

      {/* Aviso honesto: sin jornada calculada NO es lo mismo que ausente. */}
      {d.sin_calcular > 0 && (
        <Card className="mt-3">
          <CardContent className="flex items-start gap-3 py-4">
            <Clock className="mt-0.5 h-4 w-4 shrink-0 text-ochre" />
            <p className="text-sm text-graphite">
              <span className="font-medium text-ink-900">
                {d.sin_calcular} empleado{d.sin_calcular > 1 ? "s" : ""} sin jornada
                calculada hoy.
              </span>{" "}
              No significa que estén ausentes: puede que aún no lleguen marcaciones
              del dispositivo, o que les falte horario asignado.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Pendiente
          titulo="Solicitudes por aprobar"
          valor={d.solicitudes_pendientes}
          href="/personal/permisos"
          vacio="Nada pendiente de aprobación"
        />
        <Pendiente
          titulo="Incidencias abiertas"
          valor={d.incidencias_abiertas}
          href="/personal/incidencias"
          vacio="Sin incidencias abiertas"
        />
        <Card>
          <CardContent>
            <p className="section-label">Tiempo por compensar</p>
            <p className="mt-2 font-display text-3xl tabular-nums text-ink-900">
              {minutosAHoras(d.minutos_por_compensar)}
            </p>
            <p className="mt-1 text-xs text-graphite">
              en planes de compensación activos
            </p>
            <Link
              href="/personal/compensaciones"
              className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-navy-600 hover:underline"
            >
              Ver planes <ArrowRight className="h-3 w-3" />
            </Link>
          </CardContent>
        </Card>
      </div>

      {/* Permanencia vs autorización — la distinción central del módulo */}
      {(d.posible_extra_hoy > 0 || d.extra_aprobada_hoy > 0) && (
        <Card className="mt-4">
          <CardContent>
            <p className="section-label">Tiempo adicional de hoy</p>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-[0.1em] text-graphite">
                  Permanencia observada
                </p>
                <p className="mt-1 font-display text-2xl tabular-nums text-ink-900">
                  {minutosAHoras(d.posible_extra_hoy)}
                </p>
                <p className="mt-1 text-xs text-graphite">
                  Es un hecho, no tiempo a favor. No se paga sin autorización.
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.1em] text-graphite">
                  Hora extra reconocida
                </p>
                <p className="mt-1 font-display text-2xl tabular-nums text-sage">
                  {minutosAHoras(d.extra_aprobada_hoy)}
                </p>
                <p className="mt-1 text-xs text-graphite">
                  Autorizada previamente y confirmada por las marcaciones.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Novedades del día ───────────────────────────────────────── */}
      <Card className="mt-4">
        <CardContent className="p-0">
          <div className="border-b border-border px-5 py-4">
            <p className="section-label">Novedades de hoy</p>
          </div>
          {hoyQ.isLoading ? (
            <p className="px-5 py-6 text-sm text-graphite">Cargando…</p>
          ) : conNovedad.length === 0 ? (
            <div className="flex items-center gap-2 px-5 py-6 text-sm text-graphite">
              <CheckCircle2 className="h-4 w-4 text-sage" />
              Sin novedades: nadie llegó tarde ni quedó con marcación incompleta.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border">
                  <tr className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                    <th className="px-5 py-2.5 text-left">Empleado</th>
                    <th className="px-3 py-2.5 text-left">Estado</th>
                    <th className="px-3 py-2.5 text-right">Entrada</th>
                    <th className="px-3 py-2.5 text-right">Trabajado</th>
                    <th className="px-5 py-2.5 text-right">Detalle</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {conNovedad.map((j) => {
                    const e = etiquetaJornada(j.estado_asistencia);
                    return (
                      <tr key={`${j.empleado_id}-${j.work_date}`} className="hover:bg-cloud/50">
                        <td className="px-5 py-2.5 text-ink-900">
                          {nombre(j.empleado_id)}
                        </td>
                        <td className="px-3 py-2.5"><Badge tone={e.tone}>{e.label}</Badge></td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-graphite">
                          {hora(j.primera_entrada_at)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-ink-900">
                          {minutosAHoras(j.minutos_trabajados)}
                        </td>
                        <td className="px-5 py-2.5 text-right">
                          <Link
                            href={`/personal/asistencia/${j.empleado_id}/${j.work_date.slice(0, 10)}`}
                            className="text-xs font-medium text-navy-600 hover:underline"
                          >
                            Ver
                          </Link>
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

function Pendiente({
  titulo, valor, href, vacio,
}: { titulo: string; valor: number; href: string; vacio: string }) {
  return (
    <Card>
      <CardContent>
        <p className="section-label">{titulo}</p>
        {valor === 0 ? (
          <div className="mt-3 flex items-center gap-2 text-sm text-graphite">
            <CheckCircle2 className="h-4 w-4 text-sage" /> {vacio}
          </div>
        ) : (
          <>
            <div className="mt-2 flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-ochre" />
              <span className="font-display text-3xl tabular-nums text-ink-900">
                {valor}
              </span>
            </div>
            <Link
              href={href}
              className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-navy-600 hover:underline"
            >
              Revisar <ArrowRight className="h-3 w-3" />
            </Link>
          </>
        )}
      </CardContent>
    </Card>
  );
}
