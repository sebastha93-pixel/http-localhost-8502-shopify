"use client";

/**
 * Panel de control de rutas de lote (confección → lavandería → terminación → despacho).
 * Cada fila = una orden de corte que va camino al despacho.
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Truck, Clock } from "lucide-react";

interface Ruta {
  id: string;
  token_publico: string;
  etapa: string;
  orden_corte_id: string;
  precio_confeccion?: number;
  precio_terminacion?: number;
  fecha_entrega_confeccion?: string;
  asignado_at: string;
  aceptado_at?: string;
  lavanderia_at?: string;
  terminacion_recibida_at?: string;
  terminacion_terminada_at?: string;
  despachado_at?: string;
  confeccionista?: { nombre: string };
  terminacion?: { nombre: string };
  orden_corte?: {
    consecutivo: string;
    referencia?: { codigo_referencia: string; nombre: string; tela?: string };
  };
}

const ETAPAS = [
  { key: "",                       label: "Todas" },
  { key: "asignado",               label: "Asignado" },
  { key: "aceptado",               label: "Aceptado" },
  { key: "en_confeccion",          label: "En confección" },
  { key: "lavanderia",             label: "En lavandería" },
  { key: "terminacion_recibida",   label: "En terminación" },
  { key: "terminacion_terminada",  label: "Terminado" },
  { key: "despachado",             label: "Despachado" },
];

function toneEtapa(etapa: string): "normal" | "pendiente" | "info" | "critico" | "neutral" {
  if (etapa === "despachado") return "normal";
  if (etapa === "terminacion_terminada") return "normal";
  if (etapa === "aceptado" || etapa === "en_confeccion") return "info";
  if (etapa === "lavanderia" || etapa === "terminacion_recibida") return "info";
  return "pendiente";
}

function diasDesde(iso?: string) {
  if (!iso) return null;
  const d = new Date(iso);
  const now = new Date();
  const ms = now.getTime() - d.getTime();
  return Math.floor(ms / (1000 * 60 * 60 * 24));
}

export default function RutasPage() {
  const [etapa, setEtapa] = useState("");

  const q = useQuery<{ rutas: Ruta[] }>({
    queryKey: ["rutas", etapa],
    queryFn: () => api.get(`/api/produccion/rutas${etapa ? `?etapa=${etapa}` : ""}`),
  });

  const rutas = q.data?.rutas || [];

  const kpis = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rutas) c[r.etapa] = (c[r.etapa] || 0) + 1;
    return c;
  }, [rutas]);

  if (q.isLoading) return <LoadingState label="Cargando rutas…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  return (
    <PageShell title="Rutas de lote" subtitle="Confección → lavandería → terminación → despacho">
      {/* KPIs por etapa */}
      <Card>
        <CardContent className="p-5 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
          {ETAPAS.filter((e) => e.key).map((e) => (
            <button key={e.key} onClick={() => setEtapa(etapa === e.key ? "" : e.key)}
              className={`text-left rounded-sm border p-3 transition-colors ${etapa === e.key ? "border-navy-600 bg-navy-600/[0.06]" : "border-border bg-cloud/20 hover:bg-cloud/40"}`}>
              <p className="text-[0.55rem] uppercase tracking-widest text-graphite">{e.label}</p>
              <p className="mt-1 font-display text-xl text-ink-900 tabular">{kpis[e.key] || 0}</p>
            </button>
          ))}
        </CardContent>
      </Card>

      {/* Filtro etapa */}
      <div className="flex items-center gap-2 flex-wrap">
        {ETAPAS.map((e) => (
          <button key={e.key} onClick={() => setEtapa(e.key)}
            className={`rounded-sm border px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest ${etapa === e.key ? "bg-navy-600 border-navy-600 text-white" : "border-border bg-white text-ink-900 hover:bg-cloud"}`}>
            {e.label}
          </button>
        ))}
      </div>

      {rutas.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center">
            <Truck className="mx-auto h-8 w-8 text-graphite" />
            <p className="mt-3 text-sm text-graphite">
              No hay rutas {etapa ? "en esta etapa" : "aún"}. Crea una remisión con órdenes cortadas para generarlas.
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
                  <th className="px-4 py-2">Confeccionista</th>
                  <th className="px-4 py-2">Terminación</th>
                  <th className="px-4 py-2">Etapa</th>
                  <th className="px-4 py-2 text-right">Días</th>
                  <th className="px-4 py-2">Fecha entrega</th>
                </tr>
              </thead>
              <tbody>
                {rutas.map((r) => {
                  const dias = diasDesde(r.asignado_at);
                  return (
                    <tr key={r.id} className="border-b border-border/40 hover:bg-cloud/30">
                      <td className="px-4 py-2 font-semibold tabular text-navy-600">
                        <Link href={`/produccion/corte/${r.orden_corte_id}`} className="hover:underline">
                          {r.orden_corte?.consecutivo || "—"}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-ink-900">
                        {r.orden_corte?.referencia?.codigo_referencia || "—"}
                        <div className="text-[0.6rem] text-graphite">
                          {r.orden_corte?.referencia?.nombre} {r.orden_corte?.referencia?.tela ? `· ${r.orden_corte.referencia.tela}` : ""}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-ink-900">{r.confeccionista?.nombre || "—"}</td>
                      <td className="px-4 py-2 text-graphite">{r.terminacion?.nombre || "—"}</td>
                      <td className="px-4 py-2">
                        <Badge tone={toneEtapa(r.etapa)}>{r.etapa}</Badge>
                      </td>
                      <td className="px-4 py-2 text-right tabular text-graphite">
                        {dias != null ? (
                          <span className="inline-flex items-center gap-1">
                            <Clock className="h-3 w-3" /> {dias}
                          </span>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-2 text-graphite text-[0.65rem] tabular">
                        {r.fecha_entrega_confeccion || "—"}
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
