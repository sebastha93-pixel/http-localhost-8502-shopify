"use client";

/**
 * Tablero de Producción — eficiencia de corte, stock de tela y ruta de lotes.
 * Fuente: GET /api/produccion/tablero (cache 60s en backend).
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { KpiCard } from "@/components/kpi-card";
import { AlertTriangle, CheckCircle, Clock } from "lucide-react";

interface Tablero {
  inventario: {
    metros_disponibles: number;
    valor_estimado: number;
    num_telas: number;
    telas_bajas: { descripcion_tela: string; tono: string; metros_disponible: number; num_rollos: number }[];
    stock_minimo: number;
  };
  corte: {
    ordenes_cortadas: number;
    unidades_mes: number;
    eficiencia_pct: number | null;
    metros_teoricos: number;
    metros_reales: number;
    ultimos: {
      id: string; consecutivo: string; referencia?: string; nombre?: string;
      unidades: number; metros_teorico: number; metros_real: number;
      diferencia_pct?: number; promedio_real?: number;
    }[];
  };
  ruta: {
    por_etapa: Record<string, number>;
    en_proceso: number;
    en_bodega: number;
    estancados: { consecutivo?: string; etapa: string; dias: number }[];
  };
}

const ETAPA_LABEL: Record<string, string> = {
  asignado:              "Asignado",
  aceptado:              "Aceptado",
  en_confeccion:         "En confección",
  lavanderia:            "Lavandería",
  terminacion_recibida:  "En terminación",
  terminacion_terminada: "Terminación lista",
  despachado:            "En bodega",
};
const ETAPA_ORDEN = [
  "asignado", "aceptado", "en_confeccion", "lavanderia",
  "terminacion_recibida", "terminacion_terminada", "despachado",
];

const fmt = (n: number, dec = 0) =>
  n.toLocaleString("es-CO", { maximumFractionDigits: dec });

export default function TableroProduccionPage() {
  const q = useQuery<Tablero>({
    queryKey: ["produccion", "tablero"],
    queryFn: () => api.get("/api/produccion/tablero"),
    refetchInterval: 120_000,
  });

  if (q.isLoading) return <LoadingState label="Calculando tablero…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const t = q.data;
  const ef = t.corte.eficiencia_pct;

  return (
    <PageShell title="Tablero de producción" subtitle="Eficiencia · stock · valor · ruta de lotes">
      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <KpiCard label="Metros disponibles" value={`${fmt(t.inventario.metros_disponibles)} m`}
          meta={`${t.inventario.num_telas} telas/tonos`} accent="navy" />
        <KpiCard label="Valor inventario" value={`$${fmt(t.inventario.valor_estimado)}`} accent="teal" />
        <KpiCard label="Unidades cortadas (mes)" value={fmt(t.corte.unidades_mes)}
          meta={`${t.corte.ordenes_cortadas} órdenes históricas`} accent="navy" />
        <KpiCard label="Consumo real vs teórico" value={ef != null ? `${ef > 0 ? "+" : ""}${ef}%` : "—"}
          variant={ef != null && ef > 3 ? "danger" : ef != null && ef <= 0 ? "success" : "default"}
          meta={`${fmt(t.corte.metros_reales)} m reales / ${fmt(t.corte.metros_teoricos)} m teóricos`} />
        <KpiCard label="Lotes en proceso" value={t.ruta.en_proceso}
          meta={`${t.ruta.en_bodega} en bodega`} accent="khaki" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Ruta por etapa */}
        <Card>
          <CardContent className="p-5 space-y-3">
            <p className="section-label">Lotes por etapa</p>
            {ETAPA_ORDEN.map((e) => {
              const n = t.ruta.por_etapa[e] || 0;
              const max = Math.max(1, ...Object.values(t.ruta.por_etapa));
              return (
                <div key={e} className="flex items-center gap-3">
                  <p className="w-36 text-[0.65rem] uppercase tracking-widest text-graphite">{ETAPA_LABEL[e]}</p>
                  <div className="flex-1 h-2.5 rounded-full bg-cloud overflow-hidden">
                    <div className={`h-full rounded-full ${e === "despachado" ? "bg-teal" : "bg-navy-600"}`}
                      style={{ width: `${(n / max) * 100}%` }} />
                  </div>
                  <p className="w-8 text-right text-sm font-semibold tabular text-ink-900">{n}</p>
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Lotes estancados */}
        <Card>
          <CardContent className="p-5 space-y-3">
            <p className="section-label flex items-center gap-2">
              <Clock className="h-3.5 w-3.5 text-terracotta" /> Lotes estancados (&gt;7 días sin llegar a bodega)
            </p>
            {t.ruta.estancados.length === 0 ? (
              <p className="flex items-center gap-1.5 text-xs text-sage"><CheckCircle className="h-3.5 w-3.5" /> Ninguno — todo fluye.</p>
            ) : (
              <table className="w-full text-xs">
                <tbody>
                  {t.ruta.estancados.map((l, i) => (
                    <tr key={i} className="border-b border-border/40">
                      <td className="py-1.5 font-semibold tabular text-navy-600">{l.consecutivo || "—"}</td>
                      <td className="py-1.5 text-graphite">{ETAPA_LABEL[l.etapa] || l.etapa}</td>
                      <td className="py-1.5 text-right tabular font-bold text-terracotta">{l.dias} días</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Telas bajo stock mínimo */}
      <Card>
        <CardContent className="p-5 space-y-3">
          <p className="section-label flex items-center gap-2">
            <AlertTriangle className="h-3.5 w-3.5 text-ochre" />
            Telas bajo stock mínimo ({t.inventario.stock_minimo} m)
          </p>
          {t.inventario.telas_bajas.length === 0 ? (
            <p className="text-xs text-graphite">Ninguna tela por debajo del mínimo.</p>
          ) : (
            <table className="w-full text-xs">
              <thead className="border-b border-border">
                <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                  <th className="py-1.5">Tela</th>
                  <th className="py-1.5">Tono</th>
                  <th className="py-1.5 text-right">Rollos</th>
                  <th className="py-1.5 text-right">Metros</th>
                </tr>
              </thead>
              <tbody>
                {t.inventario.telas_bajas.map((tela, i) => (
                  <tr key={i} className="border-b border-border/40">
                    <td className="py-1.5 text-ink-900">{tela.descripcion_tela}</td>
                    <td className="py-1.5 text-graphite">{tela.tono}</td>
                    <td className="py-1.5 text-right tabular">{tela.num_rollos}</td>
                    <td className="py-1.5 text-right tabular font-bold text-ochre">{fmt(tela.metros_disponible, 1)} m</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* Últimos cortes — eficiencia */}
      <Card>
        <CardContent className="p-0">
          <div className="px-5 py-3 border-b border-border">
            <p className="section-label">Últimos cortes · teórico vs real</p>
          </div>
          {t.corte.ultimos.length === 0 ? (
            <p className="p-8 text-center text-xs text-graphite">Aún no hay cortes cerrados.</p>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                  <th className="px-5 py-2">Consecutivo</th>
                  <th className="px-5 py-2">Referencia</th>
                  <th className="px-5 py-2 text-right">Unidades</th>
                  <th className="px-5 py-2 text-right">M. teórico</th>
                  <th className="px-5 py-2 text-right">M. real</th>
                  <th className="px-5 py-2 text-right">Δ %</th>
                  <th className="px-5 py-2 text-right">Prom. real</th>
                </tr>
              </thead>
              <tbody>
                {t.corte.ultimos.map((oc) => {
                  const d = oc.diferencia_pct;
                  return (
                    <tr key={oc.id} className="border-b border-border/40 hover:bg-cloud/30">
                      <td className="px-5 py-2 font-semibold tabular text-navy-600">
                        <Link href={`/produccion/corte/${oc.id}`} className="hover:underline">{oc.consecutivo}</Link>
                      </td>
                      <td className="px-5 py-2 text-ink-900">
                        {oc.referencia || "—"}
                        <span className="text-graphite"> · {oc.nombre || ""}</span>
                      </td>
                      <td className="px-5 py-2 text-right tabular">{fmt(oc.unidades)}</td>
                      <td className="px-5 py-2 text-right tabular">{fmt(oc.metros_teorico, 1)}</td>
                      <td className="px-5 py-2 text-right tabular">{fmt(oc.metros_real, 1)}</td>
                      <td className={`px-5 py-2 text-right tabular font-bold ${d != null && d > 3 ? "text-terracotta" : d != null && d <= 0 ? "text-sage" : "text-ink-900"}`}>
                        {d != null ? `${d > 0 ? "+" : ""}${d}%` : "—"}
                      </td>
                      <td className="px-5 py-2 text-right tabular">{oc.promedio_real ?? "—"}</td>
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
