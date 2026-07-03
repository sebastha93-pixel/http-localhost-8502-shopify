"use client";

/**
 * Vista unificada de LOTES — reemplaza la navegación fragmentada entre
 * /produccion/corte, /produccion/informes-corte, /produccion/rutas.
 *
 * Un lote = una orden de corte. Los tabs filtran por estado + etapa de ruta.
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Clock, Scissors } from "lucide-react";

interface OrdenCorte {
  id: string;
  consecutivo: string;
  estado: string;   // borrador | autorizada | en_proceso | cortada
  referencia_lote?: string;
  cantidad_programada?: number;
  unidades_cortadas?: Record<string, number>;
  precio_corte?: number;
  fecha_entrega?: string;
  responsable?: string;
  diferencia_pct?: number;
  created_at: string;
  referencia?: {
    codigo_referencia: string;
    nombre: string;
    tela?: string;
  };
}

interface Ruta {
  id: string;
  orden_corte_id: string;
  etapa: string;
  asignado_at?: string;
  aceptado_at?: string;
  despachado_at?: string;
  confeccionista?: { nombre: string };
  terminacion?: { nombre: string };
}

interface LoteRow {
  oc: OrdenCorte;
  ruta?: Ruta;
}

const TABS = [
  { key: "todas",       label: "Todas" },
  { key: "por_cortar",  label: "Por cortar" },
  { key: "cortadas",    label: "Cortadas" },
  { key: "en_ruta",     label: "En ruta" },
  { key: "terminados",  label: "Despachados" },
];

function toneEstadoCorte(e: string): "normal" | "pendiente" | "info" | "neutral" {
  if (e === "cortada") return "info";
  if (e === "autorizada") return "pendiente";
  if (e === "borrador") return "neutral";
  return "info";
}
function toneEtapaRuta(e?: string): "normal" | "pendiente" | "info" | "neutral" {
  if (!e) return "neutral";
  if (e === "despachado" || e === "terminacion_terminada") return "normal";
  if (e === "asignado") return "pendiente";
  return "info";
}
function diasDesde(iso?: string) {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

export default function LotesPage() {
  const [tab, setTab] = useState<string>("todas");

  const cortesQ = useQuery<{ ordenes: OrdenCorte[] }>({
    queryKey: ["produccion", "corte", "lista-lotes"],
    queryFn: () => api.get("/api/produccion/corte?limit=500"),
  });
  const rutasQ = useQuery<{ rutas: Ruta[] }>({
    queryKey: ["produccion", "rutas", "todas"],
    queryFn: () => api.get("/api/produccion/rutas?limit=500"),
  });

  // Merge: cada OC con su ruta opcional
  const lotes = useMemo<LoteRow[]>(() => {
    const cortes = cortesQ.data?.ordenes || [];
    const rutas = rutasQ.data?.rutas || [];
    const rutaMap = new Map<string, Ruta>();
    for (const r of rutas) if (r.orden_corte_id) rutaMap.set(r.orden_corte_id, r);
    return cortes.map((oc) => ({ oc, ruta: rutaMap.get(oc.id) }));
  }, [cortesQ.data, rutasQ.data]);

  // Filtros por tab
  const filtrados = useMemo(() => {
    switch (tab) {
      case "por_cortar":
        return lotes.filter((l) => ["borrador", "autorizada", "en_proceso"].includes(l.oc.estado));
      case "cortadas":
        return lotes.filter((l) => l.oc.estado === "cortada" && !l.ruta);
      case "en_ruta":
        return lotes.filter((l) => l.ruta && !["despachado"].includes(l.ruta.etapa));
      case "terminados":
        return lotes.filter((l) => l.ruta?.etapa === "despachado");
      default:
        return lotes;
    }
  }, [lotes, tab]);

  // Contadores por tab (para chips)
  const contadores = useMemo(() => {
    return {
      todas:      lotes.length,
      por_cortar: lotes.filter((l) => ["borrador", "autorizada", "en_proceso"].includes(l.oc.estado)).length,
      cortadas:   lotes.filter((l) => l.oc.estado === "cortada" && !l.ruta).length,
      en_ruta:    lotes.filter((l) => l.ruta && !["despachado"].includes(l.ruta.etapa)).length,
      terminados: lotes.filter((l) => l.ruta?.etapa === "despachado").length,
    } as Record<string, number>;
  }, [lotes]);

  if (cortesQ.isLoading || rutasQ.isLoading) return <LoadingState label="Cargando lotes…" />;
  if (cortesQ.isError) return <ErrorState error={cortesQ.error} onRetry={() => cortesQ.refetch()} />;

  return (
    <PageShell
      title="Lotes"
      subtitle="Vista unificada · corte → ruta → despacho"
    >
      {/* Tabs */}
      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => {
          const active = tab === t.key;
          const cnt = contadores[t.key] ?? 0;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`inline-flex items-center gap-2 rounded-sm border px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest ${active ? "bg-navy-600 border-navy-600 text-white" : "border-border bg-white text-ink-900 hover:bg-cloud"}`}>
              {t.label}
              <span className={`rounded-sm px-1.5 py-0.5 text-[0.55rem] tabular ${active ? "bg-white/20" : "bg-cloud text-graphite"}`}>
                {cnt}
              </span>
            </button>
          );
        })}
      </div>

      {filtrados.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center">
            <Scissors className="mx-auto h-8 w-8 text-graphite" />
            <p className="mt-3 text-sm text-graphite">Sin lotes en este filtro.</p>
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
                  <th className="px-4 py-2">Lote</th>
                  <th className="px-4 py-2 text-right">Cantidad</th>
                  <th className="px-4 py-2">Corte</th>
                  <th className="px-4 py-2">Ruta</th>
                  <th className="px-4 py-2">Confeccionista</th>
                  <th className="px-4 py-2 text-right">Días</th>
                </tr>
              </thead>
              <tbody>
                {filtrados.map(({ oc, ruta }) => {
                  const cantidad = oc.cantidad_programada
                    ?? Object.values(oc.unidades_cortadas || {}).reduce<number>((s, n) => s + (Number(n) || 0), 0);
                  const dias = diasDesde(ruta?.asignado_at || oc.created_at);
                  return (
                    <tr key={oc.id} className="border-b border-border/40 hover:bg-cloud/30">
                      <td className="px-4 py-2 font-semibold tabular text-navy-600">
                        <Link href={`/produccion/corte/${oc.id}`} className="hover:underline">
                          {oc.consecutivo}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-ink-900">
                        {oc.referencia?.codigo_referencia || "—"}
                        <div className="text-[0.6rem] text-graphite">
                          {oc.referencia?.nombre} {oc.referencia?.tela ? `· ${oc.referencia.tela}` : ""}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-graphite">{oc.referencia_lote || "—"}</td>
                      <td className="px-4 py-2 text-right tabular">{cantidad || "—"}</td>
                      <td className="px-4 py-2">
                        <Badge tone={toneEstadoCorte(oc.estado)}>{oc.estado}</Badge>
                      </td>
                      <td className="px-4 py-2">
                        {ruta ? <Badge tone={toneEtapaRuta(ruta.etapa)}>{ruta.etapa}</Badge> : <span className="text-[0.65rem] text-graphite">—</span>}
                      </td>
                      <td className="px-4 py-2 text-graphite">{ruta?.confeccionista?.nombre || "—"}</td>
                      <td className="px-4 py-2 text-right tabular text-graphite">
                        {dias != null ? (
                          <span className="inline-flex items-center gap-1">
                            <Clock className="h-3 w-3" /> {dias}
                          </span>
                        ) : "—"}
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
