"use client";

/**
 * Mi tiempo — autoservicio del empleado.
 *
 * Es la única página del módulo que NO exige permiso: la ve todo usuario con
 * login. Por eso también la alcanzan cuentas de servicio y terceros, y para
 * ellos el backend responde `aplica: false` — no es un error, simplemente no
 * les aplica, y aquí se muestra en tono neutro.
 *
 * El aislamiento es por dato: el backend deriva el empleado del JWT, nunca de
 * un parámetro. Esta pantalla no puede pedir el tiempo de otra persona.
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { KpiCard } from "@/components/kpi-card";
import { Badge } from "@/components/ui/badge";
import { CalendarClock, Clock, Info, Plus } from "lucide-react";
import {
  Empleado, Jornada, MovimientoTiempo, Permiso,
  etiquetaJornada, etiquetaPermiso, fechaCorta, fechaLarga, hora, hoyISO,
  minutosAHoras, siguientePaso,
} from "@/lib/personal";

interface PerfilResp {
  aplica: boolean;
  empleado: Empleado | null;
  sede?: { nombre: string } | null;
  area?: { nombre: string } | null;
  supervisor?: { nombre_completo: string } | null;
  motivo?: string;
}

export default function MiTiempoPage() {
  const perfilQ = useQuery<PerfilResp>({
    queryKey: ["personal", "mi-tiempo", "perfil"],
    queryFn: () => api.get("/api/personal/mi-tiempo/perfil"),
  });

  const aplica = perfilQ.data?.aplica === true;

  const saldoQ = useQuery<{ resumen: any; movimientos: MovimientoTiempo[] }>({
    queryKey: ["personal", "mi-tiempo", "saldo"],
    queryFn: () => api.get("/api/personal/mi-tiempo/saldo"),
    enabled: aplica,
  });

  const histQ = useQuery<{ jornadas: Jornada[] }>({
    queryKey: ["personal", "mi-tiempo", "historial"],
    queryFn: () => api.get("/api/personal/mi-tiempo/historial?limit=30"),
    enabled: aplica,
  });

  const permQ = useQuery<{ permisos: Permiso[] }>({
    queryKey: ["personal", "mi-tiempo", "permisos"],
    queryFn: () => api.get("/api/personal/mi-tiempo/permisos"),
    enabled: aplica,
  });

  if (perfilQ.isLoading) return <LoadingState label="Cargando tu tiempo…" />;
  if (perfilQ.isError)
    return <ErrorState error={perfilQ.error} onRetry={() => perfilQ.refetch()} />;

  // Cuentas de servicio y terceros: no es un error, no les aplica.
  if (!aplica) {
    return (
      <PageShell title="Mi tiempo">
        <Card>
          <CardContent className="flex items-start gap-3">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-graphite" />
            <div>
              <p className="text-sm font-medium text-ink-900">
                Esta sección no aplica para tu cuenta
              </p>
              <p className="mt-1 text-sm text-graphite">
                El control de asistencia es para el personal de nómina. Si crees
                que deberías tener ficha de empleado, habla con Talento Humano.
              </p>
            </div>
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  const yo = perfilQ.data!.empleado!;
  const jornadas = histQ.data?.jornadas ?? [];
  const hoy = jornadas.find((j) => j.work_date?.slice(0, 10) === hoyISO());
  const permisos = permQ.data?.permisos ?? [];
  const activos = permisos.filter(
    (p) => !["completada", "rechazada", "cancelada", "enviada_a_nomina"].includes(p.estado),
  );
  const saldo = saldoQ.data?.resumen;

  return (
    <PageShell
      title="Mi tiempo"
      subtitle={`${yo.nombre_completo}${yo.cargo ? ` · ${yo.cargo}` : ""}`}
      isFetching={histQ.isFetching}
      onRefresh={() => {
        histQ.refetch(); saldoQ.refetch(); permQ.refetch();
      }}
    >
      {/* ── Hoy ─────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard
          label="Hoy"
          value={hoy ? etiquetaJornada(hoy.estado_asistencia).label : "Sin registro"}
          meta={fechaLarga(hoyISO())}
          accent="navy"
        />
        <KpiCard
          label="Entrada"
          value={hora(hoy?.primera_entrada_at)}
          meta={hoy?.minutos_tarde ? `${hoy.minutos_tarde} min tarde` : "A tiempo"}
          variant={hoy?.minutos_tarde ? "danger" : "default"}
        />
        <KpiCard
          label="Salida"
          value={hora(hoy?.ultima_salida_at)}
          meta={
            hoy?.minutos_salida_anticipada
              ? `${hoy.minutos_salida_anticipada} min antes`
              : hoy?.ultima_salida_at ? "Jornada cerrada" : "Aún sin salida"
          }
        />
        <KpiCard
          label="Trabajado hoy"
          value={minutosAHoras(hoy?.minutos_trabajados)}
          meta={hoy ? `de ${minutosAHoras(hoy.minutos_esperados)} esperados` : "—"}
          accent="teal"
        />
      </div>

      {/* La explicación es lo que vuelve discutible un número. */}
      {hoy?.explicacion && (
        <Card className="mt-3">
          <CardContent className="flex items-start gap-3 py-4">
            <Clock className="mt-0.5 h-4 w-4 shrink-0 text-graphite" />
            <p className="text-sm text-graphite">{hoy.explicacion}</p>
          </CardContent>
        </Card>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {/* ── Saldo de tiempo ───────────────────────────────────────── */}
        <Card>
          <CardContent>
            <p className="section-label">Mi cuenta de tiempo</p>
            {saldoQ.isLoading ? (
              <p className="mt-3 text-sm text-graphite">Cargando…</p>
            ) : (
              <>
                <div className="mt-3 flex items-baseline gap-2">
                  <span className="font-display text-3xl tabular-nums text-ink-900">
                    {minutosAHoras(saldo?.saldo_pendiente ?? 0)}
                  </span>
                  <span className="text-sm text-graphite">por reponer</span>
                </div>
                <p className="mt-1 text-xs text-graphite">
                  Este saldo no se edita: sale de la suma de tus movimientos.
                </p>

                {(saldoQ.data?.movimientos?.length ?? 0) === 0 ? (
                  <p className="mt-4 text-sm text-graphite">
                    No tienes movimientos registrados.
                  </p>
                ) : (
                  <ul className="mt-4 divide-y divide-border">
                    {saldoQ.data!.movimientos.slice(0, 6).map((m) => (
                      <li key={m.id} className="flex items-center justify-between py-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm text-ink-900">{m.descripcion}</p>
                          <p className="text-xs text-graphite">
                            {fechaCorta(m.fecha)}
                            {m.aprobado_por ? ` · aprobó ${m.aprobado_por}` : ""}
                          </p>
                        </div>
                        <span
                          className={`ml-3 shrink-0 text-sm tabular-nums ${
                            m.direccion === "debito" ? "text-terracotta" : "text-sage"
                          }`}
                        >
                          {m.direccion === "debito" ? "−" : "+"}
                          {minutosAHoras(m.minutos)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* ── Permisos ──────────────────────────────────────────────── */}
        <Card>
          <CardContent>
            <div className="flex items-center justify-between">
              <p className="section-label">Mis permisos</p>
              <Link
                href="/personal/permisos/nuevo"
                className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-2 py-1 text-[0.68rem] font-medium text-graphite transition-colors hover:bg-cloud hover:text-ink-900"
              >
                <Plus className="h-3 w-3" /> Solicitar
              </Link>
            </div>

            {activos.length === 0 ? (
              <p className="mt-4 text-sm text-graphite">
                No tienes permisos en trámite.
              </p>
            ) : (
              <ul className="mt-3 divide-y divide-border">
                {activos.slice(0, 6).map((p) => {
                  const e = etiquetaPermiso(p.estado);
                  const paso = siguientePaso(p.estado);
                  return (
                    <li key={p.id} className="py-2.5">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm text-ink-900">{p.motivo}</p>
                          <p className="text-xs text-graphite">
                            {fechaCorta(p.inicio_solicitado_at)} ·{" "}
                            {minutosAHoras(p.minutos_solicitados)}
                          </p>
                        </div>
                        <Badge tone={e.tone}>{e.label}</Badge>
                      </div>
                      {paso && (
                        <p className="mt-1 text-xs text-graphite">→ {paso}</p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Historial ───────────────────────────────────────────────── */}
      <Card className="mt-4">
        <CardContent className="p-0">
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            <CalendarClock className="h-4 w-4 text-graphite" />
            <p className="section-label">Últimos días</p>
          </div>

          {histQ.isLoading ? (
            <p className="px-5 py-6 text-sm text-graphite">Cargando…</p>
          ) : jornadas.length === 0 ? (
            <p className="px-5 py-6 text-sm text-graphite">
              Todavía no hay jornadas calculadas para ti.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border">
                  <tr className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                    <th className="px-5 py-2.5 text-left">Día</th>
                    <th className="px-3 py-2.5 text-left">Estado</th>
                    <th className="px-3 py-2.5 text-right">Entrada</th>
                    <th className="px-3 py-2.5 text-right">Salida</th>
                    <th className="px-3 py-2.5 text-right">Trabajado</th>
                    <th className="px-5 py-2.5 text-right">Tarde</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {jornadas.map((j) => {
                    const e = etiquetaJornada(j.estado_asistencia);
                    return (
                      <tr key={j.work_date} className="hover:bg-cloud/50">
                        <td className="px-5 py-2.5 text-ink-900">
                          {fechaCorta(j.work_date)}
                        </td>
                        <td className="px-3 py-2.5">
                          <Badge tone={e.tone}>{e.label}</Badge>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-graphite">
                          {hora(j.primera_entrada_at)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-graphite">
                          {hora(j.ultima_salida_at)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-ink-900">
                          {minutosAHoras(j.minutos_trabajados)}
                        </td>
                        <td className="px-5 py-2.5 text-right tabular-nums">
                          {j.minutos_tarde ? (
                            <span className="text-terracotta">{j.minutos_tarde} min</span>
                          ) : (
                            <span className="text-graphite">—</span>
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
