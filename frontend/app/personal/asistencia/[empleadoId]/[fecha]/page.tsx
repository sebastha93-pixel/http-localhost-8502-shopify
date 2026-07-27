"use client";

/**
 * Detalle de una jornada — el "por qué" detrás de cada cifra.
 *
 * Es la pantalla que convierte un número en una conversación posible. Si
 * alguien reclama "a mí no me contaron bien el día", aquí está la explicación
 * con los parámetros exactos que se usaron para calcularlo — que quedaron
 * guardados con la jornada, así las reglas cambien después.
 */
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard } from "@/components/kpi-card";
import { ArrowLeft, Info, Lock } from "lucide-react";
import {
  Empleado, Jornada, etiquetaJornada, fechaLarga, hora, minutosAHoras,
} from "@/lib/personal";

export default function DetalleJornadaPage() {
  const router = useRouter();
  const params = useParams<{ empleadoId: string; fecha: string }>();
  const empleadoId = params?.empleadoId ?? "";
  const fecha = params?.fecha ?? "";

  const q = useQuery<{ jornada: Jornada & { parametros_usados?: Record<string, any> } }>({
    queryKey: ["personal", "asistencia", empleadoId, fecha],
    queryFn: () => api.get(`/api/personal/asistencia/${empleadoId}/${fecha}`),
  });

  const empQ = useQuery<{ empleado: Empleado }>({
    queryKey: ["personal", "empleado", empleadoId],
    queryFn: () => api.get(`/api/personal/empleados/${empleadoId}`),
  });

  if (q.isLoading) return <LoadingState label="Cargando la jornada…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const j = q.data!.jornada;
  const e = etiquetaJornada(j.estado_asistencia);
  const emp = empQ.data?.empleado;

  return (
    <PageShell
      title={emp?.nombre_completo ?? "Jornada"}
      subtitle={fechaLarga(fecha)}
    >
      <button onClick={() => router.back()}
        className="mb-4 inline-flex items-center gap-1 text-xs font-medium text-graphite hover:text-ink-900">
        <ArrowLeft className="h-3.5 w-3.5" /> Volver
      </button>

      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={e.tone}>{e.label}</Badge>
        {j.bloqueado_at && (
          <span className="inline-flex items-center gap-1 text-xs text-graphite">
            <Lock className="h-3 w-3" /> Periodo cerrado — no se recalcula
          </span>
        )}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard label="Entrada" value={hora(j.primera_entrada_at)}
                 meta={j.minutos_tarde ? `${j.minutos_tarde} min tarde` : "A tiempo"}
                 variant={j.minutos_tarde ? "danger" : "default"} />
        <KpiCard label="Salida" value={hora(j.ultima_salida_at)}
                 meta={j.minutos_salida_anticipada
                   ? `${j.minutos_salida_anticipada} min antes` : "Completa"}
                 variant={j.minutos_salida_anticipada ? "danger" : "default"} />
        <KpiCard label="Trabajado" value={minutosAHoras(j.minutos_trabajados)}
                 meta={`de ${minutosAHoras(j.minutos_esperados)} esperados`} accent="teal" />
        <KpiCard label="Permiso autorizado"
                 value={minutosAHoras(j.minutos_permiso_autorizado)}
                 meta={j.minutos_permiso_autorizado ? "reduce lo esperado" : "sin permiso"} />
      </div>

      {/* La explicación legible: el corazón de esta pantalla */}
      {j.explicacion && (
        <Card className="mt-4">
          <CardContent className="flex items-start gap-3">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-navy-600" />
            <div>
              <p className="section-label">Cómo se calculó</p>
              <p className="mt-2 text-sm text-ink-900">{j.explicacion}</p>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {/* Permanencia vs autorización, lado a lado */}
        <Card>
          <CardContent>
            <p className="section-label">Tiempo adicional</p>
            <dl className="mt-3 space-y-3">
              <div>
                <dt className="text-xs uppercase tracking-[0.1em] text-graphite">
                  Permanencia observada
                </dt>
                <dd className="mt-0.5 font-display text-2xl tabular-nums text-ink-900">
                  {minutosAHoras(j.minutos_posible_extra)}
                </dd>
                <p className="mt-1 text-xs text-graphite">
                  Estuvo más allá de su jornada. Es un hecho, no tiempo a favor.
                </p>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-[0.1em] text-graphite">
                  Hora extra reconocida
                </dt>
                <dd className="mt-0.5 font-display text-2xl tabular-nums text-sage">
                  {minutosAHoras(j.minutos_extra_aprobada)}
                </dd>
                <p className="mt-1 text-xs text-graphite">
                  {j.minutos_extra_aprobada
                    ? "Autorizada antes y confirmada por las marcaciones."
                    : "Sin autorización previa no se reconoce nada."}
                </p>
              </div>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <p className="section-label">Otros conceptos</p>
            <dl className="mt-3 space-y-2 text-sm">
              <Fila k="Exceso de descanso" v={minutosAHoras(j.minutos_exceso_descanso)} />
              <Fila k="Compensación validada" v={minutosAHoras(j.minutos_compensacion_aprob)} />
              <Fila k="Recargo nocturno" v={minutosAHoras(j.minutos_recargo_nocturno)} />
              <Fila k="Dominical o festivo" v={minutosAHoras(j.minutos_dominical_festivo)} />
            </dl>
          </CardContent>
        </Card>
      </div>

      {/* Los parámetros con que se calculó: una cifra vieja sigue siendo
          explicable aunque las reglas hayan cambiado después. */}
      {j.parametros_usados && Object.keys(j.parametros_usados).length > 0 && (
        <Card className="mt-4">
          <CardContent>
            <p className="section-label">Reglas aplicadas ese día</p>
            <p className="mt-1 text-xs text-graphite">
              Se guardaron con la jornada. Si las reglas cambian mañana, esta
              cifra sigue siendo defendible.
            </p>
            <div className="mt-3 grid gap-x-6 gap-y-1 sm:grid-cols-2">
              {Object.entries(j.parametros_usados).map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-border py-1 text-xs">
                  <span className="text-graphite">{k.replace(/_/g, " ")}</span>
                  <span className="tabular-nums text-ink-900">{String(v)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </PageShell>
  );
}

function Fila({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between border-b border-border pb-2">
      <dt className="text-graphite">{k}</dt>
      <dd className="tabular-nums text-ink-900">{v}</dd>
    </div>
  );
}
