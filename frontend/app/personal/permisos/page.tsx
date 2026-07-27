"use client";

/**
 * Permisos — bandeja de solicitudes con las dos aprobaciones.
 *
 * El jefe evalúa la AFECTACIÓN OPERATIVA ("¿puedo cubrir la tienda?").
 * Talento Humano valida la CLASIFICACIÓN ("¿esto es calamidad o permiso
 * personal?"). Por eso los botones dicen cosas distintas en cada etapa.
 */
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Check, Plus, X } from "lucide-react";
import {
  Empleado, Permiso, TipoPermiso, etiquetaPermiso, fechaCorta, hora,
  minutosAHoras, siguientePaso,
} from "@/lib/personal";

const TABS = [
  { k: "pendiente_jefe", label: "Esperan al jefe" },
  { k: "pendiente_th",   label: "Esperan a TH" },
  { k: "en_compensacion", label: "Por compensar" },
  { k: "aprobada",       label: "Aprobadas" },
  { k: "",               label: "Todas" },
];

export default function PermisosPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState("pendiente_jefe");
  const [err, setErr] = useState("");
  const [notas, setNotas] = useState<Record<string, string>>({});

  const q = useQuery<{ permisos: Permiso[] }>({
    queryKey: ["personal", "permisos", tab],
    queryFn: () => {
      const p = new URLSearchParams({ limit: "300" });
      if (tab) p.set("estado", tab);
      return api.get(`/api/personal/permisos?${p}`);
    },
  });

  const empQ = useQuery<{ empleados: Empleado[] }>({
    queryKey: ["personal", "empleados", "nombres"],
    queryFn: () => api.get("/api/personal/empleados?limit=500"),
    staleTime: 10 * 60_000,
  });
  const tiposQ = useQuery<{ tipos: TipoPermiso[] }>({
    queryKey: ["personal", "permisos", "tipos"],
    queryFn: () => api.get("/api/personal/permisos/tipos"),
    staleTime: 30 * 60_000,
  });

  const nombre = (id: string) =>
    empQ.data?.empleados.find((e) => e.id === id)?.nombre_completo ?? "—";
  const tipo = (id: string) =>
    tiposQ.data?.tipos.find((t) => t.id === id);

  const decidir = useMutation({
    mutationFn: ({ id, accion, nota }: { id: string; accion: string; nota?: string }) =>
      api.post(`/api/personal/permisos/${id}/${accion}`, { notas: nota ?? "" }),
    onSuccess: () => {
      setErr("");
      qc.invalidateQueries({ queryKey: ["personal", "permisos"] });
      qc.invalidateQueries({ queryKey: ["personal", "dashboard"] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  if (q.isLoading) return <LoadingState label="Cargando solicitudes…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const permisos = q.data?.permisos ?? [];

  return (
    <PageShell
      title="Permisos"
      subtitle={`${permisos.length} solicitud${permisos.length === 1 ? "" : "es"}`}
      isFetching={q.isFetching}
      onRefresh={() => q.refetch()}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
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
        <Link href="/personal/permisos/nuevo"
          className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-3 py-1.5 text-xs font-medium text-graphite transition-colors hover:bg-cloud hover:text-ink-900">
          <Plus className="h-3.5 w-3.5" /> Nueva solicitud
        </Link>
      </div>

      {err && (
        <p role="alert" className="mt-3 rounded-sm border border-terracotta/25 bg-terracotta/10 px-3 py-2 text-sm text-terracotta">
          {err}
        </p>
      )}

      {permisos.length === 0 ? (
        <Card className="mt-4">
          <CardContent className="py-8">
            <p className="text-sm text-graphite">
              No hay solicitudes en esta bandeja.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="mt-4 space-y-3">
          {permisos.map((p) => {
            const e = etiquetaPermiso(p.estado);
            const t = tipo(p.tipo_permiso_id);
            const paso = siguientePaso(p.estado);
            const esperaJefe = p.estado === "pendiente_jefe";
            const esperaTH = p.estado === "pendiente_th";

            return (
              <Card key={p.id}>
                <CardContent>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-ink-900">
                          {nombre(p.empleado_id)}
                        </span>
                        <Badge tone={e.tone}>{e.label}</Badge>
                        {t?.es_compensable && (
                          <Badge tone="riesgo">Compensable</Badge>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-graphite">
                        {t?.nombre ?? "Permiso"} · {minutosAHoras(p.minutos_solicitados)}
                      </p>
                      <p className="mt-0.5 text-xs text-graphite">
                        {fechaCorta(p.inicio_solicitado_at)} de{" "}
                        {hora(p.inicio_solicitado_at)} a {hora(p.fin_solicitado_at)}
                      </p>
                      <p className="mt-2 text-sm text-ink-900">{p.motivo}</p>
                      {paso && (
                        <p className="mt-1 text-xs text-graphite">→ {paso}</p>
                      )}
                    </div>

                    {(esperaJefe || esperaTH) && (
                      <div className="w-full sm:w-72">
                        <p className="text-[0.68rem] uppercase tracking-[0.1em] text-graphite">
                          {esperaJefe
                            ? "¿Se puede cubrir la operación?"
                            : "¿La clasificación es correcta?"}
                        </p>
                        <textarea
                          rows={2}
                          placeholder={esperaJefe
                            ? "Notas de cobertura (obligatorio si rechazas)"
                            : "Notas de clasificación (obligatorio si rechazas)"}
                          value={notas[p.id] ?? ""}
                          onChange={(ev) =>
                            setNotas({ ...notas, [p.id]: ev.target.value })}
                          className="mt-1 w-full rounded-sm border border-border bg-card px-2 py-1.5 text-sm text-ink-900"
                        />
                        <div className="mt-2 flex gap-2">
                          <button
                            disabled={decidir.isPending}
                            onClick={() => decidir.mutate({
                              id: p.id,
                              accion: esperaJefe ? "aprobar-jefe" : "aprobar-th",
                              nota: notas[p.id],
                            })}
                            className="inline-flex flex-1 items-center justify-center gap-1 rounded-sm border border-sage/30 bg-sage/10 px-3 py-1.5 text-xs font-medium text-sage transition-colors hover:bg-sage/20 disabled:opacity-50"
                          >
                            <Check className="h-3.5 w-3.5" /> Aprobar
                          </button>
                          <button
                            disabled={decidir.isPending}
                            onClick={() => decidir.mutate({
                              id: p.id,
                              accion: esperaJefe ? "rechazar-jefe" : "rechazar-th",
                              nota: notas[p.id],
                            })}
                            className="inline-flex flex-1 items-center justify-center gap-1 rounded-sm border border-terracotta/30 bg-terracotta/10 px-3 py-1.5 text-xs font-medium text-terracotta transition-colors hover:bg-terracotta/20 disabled:opacity-50"
                          >
                            <X className="h-3.5 w-3.5" /> Rechazar
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </PageShell>
  );
}
