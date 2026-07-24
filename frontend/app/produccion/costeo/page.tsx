"use client";

/**
 * Costeo real — cruce lotes vs Documentos Soporte de Siigo.
 * Compara: unidades × precio del precosteo VS cantidad × valor unitario del DS.
 * Fuente: GET /api/produccion/costeo-real
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { KpiCard } from "@/components/kpi-card";
import { AlertTriangle, CheckCircle, FileWarning } from "lucide-react";

interface DsInfo {
  ds: string;
  fecha: string;
  proveedor?: string;
  cantidad: number;
  valor_unitario: number;
  total_real: number;
  saldo_por_pagar: number;
}

interface Lote {
  orden_corte_id: string;
  consecutivo: string;
  referencia?: string;
  confeccionista?: string;
  unidades: number;
  precio_teorico: number;
  total_teorico: number;
  tiene_ruta: boolean;
  ds?: DsInfo | null;
  estado: string; // ok | sin_ds | sin_asignar | precio_distinto | cantidad_distinta
  desviacion?: number;
  // Margen planeado vs real (llega del backend cuando el precosteo tiene precio de venta).
  precio_venta_final?: number;
  costo_planeado_prenda?: number;
  costo_real_prenda?: number | null;
  margen_planeado?: number | null;
  margen_real?: number | null;
}

interface Respuesta {
  ok: boolean;
  error?: string;
  mensaje?: string;
  resumen?: {
    lotes: number; con_ds: number; ok: number; con_alerta: number;
    total_teorico: number; total_real: number; desviacion: number;
  };
  lotes?: Lote[];
  ds_sin_lote?: { ds: string; fecha: string; proveedor?: string; descripcion: string; total: number }[];
  alertas?: { tipo: string; severidad: string; mensaje: string }[];
}

const ESTADO_UI: Record<string, { texto: string; tone: string }> = {
  ok:                { texto: "OK",                 tone: "bg-emerald-100 text-emerald-800" },
  sin_ds:            { texto: "Sin DS",             tone: "bg-amber-100 text-amber-800" },
  sin_asignar:       { texto: "Sin asignar",        tone: "bg-cloud text-graphite" },
  precio_distinto:   { texto: "Precio distinto",    tone: "bg-terracotta/10 text-terracotta" },
  cantidad_distinta: { texto: "Cantidad distinta",  tone: "bg-terracotta/10 text-terracotta" },
};

const money = (n?: number) =>
  n != null
    ? `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("es-CO", { maximumFractionDigits: 0 })}`
    : "—";

const pct = (n?: number | null) => (n == null ? "—" : `${n.toFixed(1)}%`);

export default function CosteoRealPage() {
  const q = useQuery<Respuesta>({
    queryKey: ["produccion", "costeo-real"],
    queryFn: () => api.get("/api/produccion/costeo-real"),
    staleTime: 5 * 60_000,
  });

  if (q.isLoading) return <LoadingState label="Cruzando lotes con Siigo… (puede tardar unos segundos)" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const data = q.data!;

  if (!data.ok) {
    const siigoCaido = /503|502|504|unavailable|try in a few minutes/i.test(data.mensaje || "");
    return (
      <PageShell title="Costeo real" subtitle="Cruce con Siigo">
        <Card>
          <CardContent className="p-8 text-center space-y-3">
            <FileWarning className="mx-auto h-8 w-8 text-ochre" />
            <p className="text-sm font-semibold text-ink-900">
              {data.error === "siigo_no_configurado" ? "Siigo no está conectado"
                : siigoCaido ? "Siigo está temporalmente fuera de servicio"
                : "Error consultando Siigo"}
            </p>
            {siigoCaido && (
              <p className="text-xs text-graphite max-w-md mx-auto">
                Es una caída del lado de Siigo, no del sistema. Suele durar unos minutos —
                el calentador reintentará solo; también puedes reintentar ya.
              </p>
            )}
            <button onClick={() => q.refetch()}
              className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700">
              Reintentar
            </button>
            <p className="text-[0.65rem] text-graphite/70 max-w-md mx-auto break-all">{data.mensaje}</p>
            {data.error === "siigo_no_configurado" && (
              <p className="text-xs text-graphite max-w-md mx-auto">
                Copia las variables <code className="font-mono">SIIGO_USERNAME</code>,{" "}
                <code className="font-mono">SIIGO_ACCESS_KEY</code> y{" "}
                <code className="font-mono">SIIGO_PARTNER_ID</code> (las mismas de atlas en Vercel)
                a las Variables del backend en Railway y redespliega.
              </p>
            )}
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  const r = data.resumen ?? {
    lotes: 0, con_ds: 0, ok: 0, con_alerta: 0,
    total_teorico: 0, total_real: 0, desviacion: 0,
  };
  const lotes = data.lotes || [];
  const alertas = data.alertas || [];
  const dsSinLote = data.ds_sin_lote || [];

  return (
    <PageShell title="Costeo real" subtitle="Precosteo vs Documentos Soporte de Siigo (confección)">
      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <KpiCard label="Lotes cruzados" value={`${r.con_ds}/${r.lotes}`} meta="con documento soporte" accent="navy" />
        <KpiCard label="Costo teórico" value={money(r.total_teorico)} accent="steel" />
        <KpiCard label="Costo real (DS)" value={money(r.total_real)} accent="teal" />
        <KpiCard label="Desviación" value={money(r.desviacion)}
          variant={Math.abs(r.desviacion) > 0.01 * Math.max(r.total_teorico, 1) ? "danger" : "success"} />
        <KpiCard label="Alertas" value={alertas.length}
          variant={alertas.length > 0 ? "danger" : "success"} />
      </div>

      {/* Alertas */}
      {alertas.length > 0 && (
        <Card>
          <CardContent className="p-5 space-y-2">
            <p className="section-label flex items-center gap-2">
              <AlertTriangle className="h-3.5 w-3.5 text-terracotta" /> Alertas ({alertas.length})
            </p>
            {alertas.map((a, i) => (
              <div key={i}
                className={`rounded-sm border px-3 py-2 text-xs ${a.severidad === "alta" ? "border-terracotta/40 bg-terracotta/[0.05] text-terracotta" : "border-ochre/40 bg-ochre/[0.05] text-ink-900"}`}>
                {a.mensaje}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Tabla lotes */}
      <Card>
        <CardContent className="p-0">
          <div className="px-5 py-3 border-b border-border">
            <p className="section-label">Lotes · teórico vs contabilizado</p>
          </div>
          {lotes.length === 0 ? (
            <p className="p-8 text-center text-xs text-graphite">No hay lotes cortados aún.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-cloud/60 border-b border-border">
                  <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                    <th className="px-4 py-2">Lote</th>
                    <th className="px-4 py-2">Referencia</th>
                    <th className="px-4 py-2">Confeccionista</th>
                    <th className="px-4 py-2 text-right">Unid.</th>
                    <th className="px-4 py-2 text-right">$ Precosteo</th>
                    <th className="px-4 py-2 text-right">Total teórico</th>
                    <th className="px-4 py-2">DS Siigo</th>
                    <th className="px-4 py-2 text-right">$ Pagado</th>
                    <th className="px-4 py-2 text-right">Total real</th>
                    <th className="px-4 py-2 text-right">Desviación</th>
                    <th className="px-4 py-2 text-right">Margen plan.</th>
                    <th className="px-4 py-2 text-right">Margen real</th>
                    <th className="px-4 py-2">Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {lotes.map((l) => {
                    const ui = ESTADO_UI[l.estado] || ESTADO_UI.sin_asignar;
                    return (
                      <tr key={l.orden_corte_id} className="border-b border-border/40 hover:bg-cloud/30">
                        <td className="px-4 py-2 font-semibold tabular text-navy-600">
                          <Link href={`/produccion/corte/${l.orden_corte_id}`} className="hover:underline">
                            {l.consecutivo}
                          </Link>
                        </td>
                        <td className="px-4 py-2 text-ink-900">{l.referencia || "—"}</td>
                        <td className="px-4 py-2 text-graphite">{l.confeccionista || "—"}</td>
                        <td className="px-4 py-2 text-right tabular">{l.unidades || "—"}</td>
                        <td className="px-4 py-2 text-right tabular">{money(l.precio_teorico)}</td>
                        <td className="px-4 py-2 text-right tabular font-semibold">{money(l.total_teorico)}</td>
                        <td className="px-4 py-2 tabular text-graphite">{l.ds?.ds || "—"}</td>
                        <td className="px-4 py-2 text-right tabular">{l.ds ? money(l.ds.valor_unitario) : "—"}</td>
                        <td className="px-4 py-2 text-right tabular font-semibold">{l.ds ? money(l.ds.total_real) : "—"}</td>
                        <td className={`px-4 py-2 text-right tabular font-bold ${(l.desviacion || 0) > 0 ? "text-terracotta" : (l.desviacion || 0) < 0 ? "text-sage" : "text-graphite"}`}>
                          {l.desviacion != null ? money(l.desviacion) : "—"}
                        </td>
                        <td className="px-4 py-2 text-right tabular">{pct(l.margen_planeado)}</td>
                        <td className="px-4 py-2 text-right tabular font-semibold">
                          {l.margen_real == null ? <span className="text-graphite">—</span> : (
                            <span className={l.margen_real < 0 ? "text-terracotta" : l.margen_real < 50 ? "text-amber-600" : "text-sage"}>
                              {l.margen_real.toFixed(1)}%
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-2">
                          <span className={`rounded-sm px-2 py-0.5 text-[0.68rem] font-bold uppercase tracking-widest ${ui.tone}`}>
                            {ui.texto}
                          </span>
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

      {/* DS sin lote */}
      {dsSinLote.length > 0 && (
        <Card>
          <CardContent className="p-5 space-y-2">
            <p className="section-label">Documentos soporte sin lote en el OS ({dsSinLote.length})</p>
            <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <tbody>
                {dsSinLote.map((d, i) => (
                  <tr key={i} className="border-b border-border/40">
                    <td className="py-1.5 font-semibold tabular text-navy-600">{d.ds}</td>
                    <td className="py-1.5 tabular text-graphite">{d.fecha}</td>
                    <td className="py-1.5 text-ink-900">{d.proveedor || "—"}</td>
                    <td className="py-1.5 text-graphite truncate max-w-[300px]">{d.descripcion}</td>
                    <td className="py-1.5 text-right tabular font-semibold">{money(d.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            <p className="text-[0.65rem] text-graphite">
              Pueden ser lotes viejos (antes del OS), REF mal escrita en Siigo, o pagos de terminación/lavandería.
            </p>
          </CardContent>
        </Card>
      )}

      {alertas.length === 0 && lotes.length > 0 && (
        <p className="flex items-center gap-2 text-xs text-sage">
          <CheckCircle className="h-4 w-4" /> Todo cuadra: lo contabilizado coincide con el precosteo.
        </p>
      )}
    </PageShell>
  );
}
