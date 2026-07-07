"use client";

/**
 * Vista unificada de LOTES — tarjetas grandes con pipeline visual.
 * Un lote = una orden de corte. Los tabs filtran por estado + etapa de ruta.
 * Pipeline: Corte → Confección → Lavandería → Terminación → Despacho.
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Clock, Scissors, User, Package, Check, ArrowRight } from "lucide-react";

interface OrdenCorte {
  id: string;
  consecutivo: string;
  estado: string;   // borrador | autorizada | en_proceso | cortada
  referencia_lote?: string;
  cantidad_programada?: number;
  unidades_cortadas?: Record<string, number>;
  fecha_entrega?: string;
  responsable?: string;
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
  lavanderia?: { nombre: string };
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
  { key: "terminados",  label: "En bodega" },
];

// ── Pipeline de etapas ────────────────────────────────────────────────
const PASOS = ["Corte", "Confección", "Lavandería", "Terminación", "Bodega"] as const;

/** Devuelve el índice del paso ACTUAL (0-4); -1 si ya despachó todo. */
function pasoActual(oc: OrdenCorte, ruta?: Ruta): number {
  if (oc.estado !== "cortada") return 0;
  if (!ruta) return 1; // cortada, esperando asignación a confección
  const e = ruta.etapa;
  if (["asignado", "aceptado", "en_confeccion"].includes(e)) return 1;
  if (e === "lavanderia") return 2;
  if (["terminacion_recibida", "terminacion_terminada"].includes(e)) return 3;
  if (e === "despachado") return -1; // completo
  return 1;
}

function etiquetaEstado(oc: OrdenCorte, ruta?: Ruta): { texto: string; tone: string } {
  if (oc.estado === "borrador")   return { texto: "Borrador",       tone: "bg-cloud text-graphite" };
  if (oc.estado === "autorizada") return { texto: "Autorizada",     tone: "bg-amber-100 text-amber-800" };
  if (oc.estado === "en_proceso") return { texto: "En proceso",     tone: "bg-amber-100 text-amber-800" };
  if (!ruta)                      return { texto: "Sin asignar",    tone: "bg-navy-600/10 text-navy-600" };
  const MAPA: Record<string, { texto: string; tone: string }> = {
    asignado:              { texto: "Asignado",              tone: "bg-navy-600/10 text-navy-600" },
    aceptado:              { texto: "Aceptado",              tone: "bg-navy-600/10 text-navy-600" },
    en_confeccion:         { texto: "En confección",         tone: "bg-navy-600/10 text-navy-600" },
    lavanderia:            { texto: "En lavandería",         tone: "bg-sky-100 text-sky-800" },
    terminacion_recibida:  { texto: "En terminación",        tone: "bg-teal/10 text-teal" },
    terminacion_terminada: { texto: "Terminación lista",     tone: "bg-teal/10 text-teal" },
    despachado:            { texto: "En bodega",             tone: "bg-emerald-100 text-emerald-800" },
  };
  return MAPA[ruta.etapa] || { texto: ruta.etapa, tone: "bg-cloud text-graphite" };
}

function diasDesde(iso?: string) {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

/** Qué sigue para este lote — para que se entienda la acción sin capacitación. */
function siguienteAccion(oc: OrdenCorte, ruta?: Ruta): { texto: string; hecho?: boolean } | null {
  if (oc.estado === "borrador")   return { texto: "Autoriza y pistolea los rollos para cortar" };
  if (oc.estado === "autorizada") return { texto: "Pistolea los rollos y sube el informe de corte" };
  if (oc.estado === "en_proceso") return { texto: "Sube el informe de corte para cerrar el lote" };
  if (oc.estado !== "cortada")    return null;
  if (!ruta)                      return { texto: "Cuenta los insumos y genera la remisión de confección" };
  const e = ruta.etapa;
  if (["asignado", "aceptado", "en_confeccion"].includes(e))
    return { texto: "Sube la remisión de recogida cuando salga a lavandería" };
  if (e === "lavanderia")            return { texto: "Marca recibido cuando llegue a terminación" };
  if (e === "terminacion_recibida")  return { texto: "Marca terminación lista al terminar el proceso" };
  if (e === "terminacion_terminada") return { texto: "Marca ingreso a bodega para cerrar el lote" };
  if (e === "despachado")            return { texto: "Lote completo — en bodega", hecho: true };
  return null;
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

  const filtrados = useMemo(() => {
    switch (tab) {
      case "por_cortar":
        return lotes.filter((l) => ["borrador", "autorizada", "en_proceso"].includes(l.oc.estado));
      case "cortadas":
        return lotes.filter((l) => l.oc.estado === "cortada" && !l.ruta);
      case "en_ruta":
        return lotes.filter((l) => l.ruta && l.ruta.etapa !== "despachado");
      case "terminados":
        return lotes.filter((l) => l.ruta?.etapa === "despachado");
      default:
        return lotes;
    }
  }, [lotes, tab]);

  const contadores = useMemo(() => {
    return {
      todas:      lotes.length,
      por_cortar: lotes.filter((l) => ["borrador", "autorizada", "en_proceso"].includes(l.oc.estado)).length,
      cortadas:   lotes.filter((l) => l.oc.estado === "cortada" && !l.ruta).length,
      en_ruta:    lotes.filter((l) => l.ruta && l.ruta.etapa !== "despachado").length,
      terminados: lotes.filter((l) => l.ruta?.etapa === "despachado").length,
    } as Record<string, number>;
  }, [lotes]);

  if (cortesQ.isLoading || rutasQ.isLoading) return <LoadingState label="Cargando lotes…" />;
  if (cortesQ.isError) return <ErrorState error={cortesQ.error} onRetry={() => cortesQ.refetch()} />;
  // Si SOLO fallan las rutas, mostramos los cortes pero con aviso — sin esto
  // todos los lotes aparecían "Sin asignar" en silencio.
  const rutasFallaron = rutasQ.isError;

  return (
    <PageShell
      title="Lotes"
      subtitle="Vista unificada · corte → ruta → ingreso a bodega"
    >
      {rutasFallaron && (
        <div role="alert" className="rounded-sm border border-ochre/40 bg-ochre/[0.06] px-3 py-2 text-xs text-ink-900">
          No se pudo cargar el estado de las rutas — los lotes pueden aparecer &quot;Sin asignar&quot; temporalmente.{" "}
          <button onClick={() => rutasQ.refetch()} className="underline font-semibold">Reintentar</button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => {
          const active = tab === t.key;
          const cnt = contadores[t.key] ?? 0;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`inline-flex items-center gap-2 rounded-sm border px-4 py-2 text-[0.68rem] font-semibold uppercase tracking-widest transition-colors ${active ? "bg-navy-600 border-navy-600 text-white" : "border-border bg-white text-ink-900 hover:bg-cloud"}`}>
              {t.label}
              <span className={`rounded-sm px-1.5 py-0.5 text-[0.58rem] tabular ${active ? "bg-white/20" : "bg-cloud text-graphite"}`}>
                {cnt}
              </span>
            </button>
          );
        })}
      </div>

      {filtrados.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <Scissors className="mx-auto h-8 w-8 text-graphite" />
            <p className="mt-3 text-sm text-graphite">Sin lotes en este filtro.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {filtrados.map(({ oc, ruta }) => (
            <LoteCard key={oc.id} oc={oc} ruta={ruta} />
          ))}
        </div>
      )}
    </PageShell>
  );
}

function LoteCard({ oc, ruta }: { oc: OrdenCorte; ruta?: Ruta }) {
  const cantidad = oc.cantidad_programada
    ?? Object.values(oc.unidades_cortadas || {}).reduce<number>((s, n) => s + (Number(n) || 0), 0);
  const dias = diasDesde(ruta?.asignado_at || oc.created_at);
  const actual = pasoActual(oc, ruta);
  const estado = etiquetaEstado(oc, ruta);
  const siguiente = siguienteAccion(oc, ruta);

  return (
    <Link href={`/produccion/corte/${oc.id}`} className="group block">
      <Card className="h-full transition-shadow group-hover:shadow-md">
        <CardContent className="p-5 space-y-4">
          {/* Cabecera: consecutivo + estado */}
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-display text-lg font-semibold tabular text-navy-600 group-hover:underline leading-none">
                {oc.consecutivo}
              </p>
              <p className="mt-1.5 text-sm font-semibold text-ink-900 truncate">
                {oc.referencia?.codigo_referencia || "—"}
                <span className="font-normal text-graphite"> · {oc.referencia?.nombre || ""}</span>
              </p>
              <p className="text-[0.68rem] text-graphite truncate">
                {oc.referencia?.tela || "sin tela"}
                {oc.referencia_lote ? ` · Lote ${oc.referencia_lote}` : ""}
              </p>
            </div>
            <span className={`shrink-0 rounded-sm px-2.5 py-1 text-[0.6rem] font-bold uppercase tracking-widest ${estado.tone}`}>
              {estado.texto}
            </span>
          </div>

          {/* Pipeline de etapas */}
          <div className="flex items-center gap-1">
            {PASOS.map((paso, i) => {
              const completo = actual === -1 || i < actual;
              const esActual = actual === i;
              return (
                <div key={paso} className="flex-1 min-w-0">
                  <div className={`h-1.5 rounded-full ${completo ? "bg-teal" : esActual ? "bg-navy-600" : "bg-cloud"}`} />
                  <p className={`mt-1 text-center text-[0.52rem] uppercase tracking-wider truncate ${completo ? "text-teal font-semibold" : esActual ? "text-navy-600 font-bold" : "text-graphite/50"}`}>
                    {completo ? <Check className="inline h-2.5 w-2.5 -mt-0.5 mr-0.5" /> : null}
                    {paso}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Datos clave */}
          <div className="grid grid-cols-3 gap-3 border-t border-border/60 pt-3">
            <div className="flex items-center gap-2 min-w-0">
              <Package className="h-4 w-4 text-graphite/60 flex-none" />
              <div className="min-w-0">
                <p className="text-[0.55rem] uppercase tracking-widest text-graphite">Cantidad</p>
                <p className="text-sm font-semibold tabular text-ink-900">{cantidad || "—"}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 min-w-0">
              <User className="h-4 w-4 text-graphite/60 flex-none" />
              <div className="min-w-0">
                <p className="text-[0.55rem] uppercase tracking-widest text-graphite">Confeccionista</p>
                <p className="text-sm font-semibold text-ink-900 truncate">
                  {ruta?.confeccionista?.nombre || "—"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 min-w-0">
              <Clock className="h-4 w-4 text-graphite/60 flex-none" />
              <div className="min-w-0">
                <p className="text-[0.55rem] uppercase tracking-widest text-graphite">Días</p>
                <p className="text-sm font-semibold tabular text-ink-900">{dias != null ? dias : "—"}</p>
              </div>
            </div>
          </div>

          {/* Qué sigue — acción clara para el operario */}
          {siguiente && (
            <div className={`flex items-center gap-2 rounded-sm px-3 py-2 text-[0.7rem] ${siguiente.hecho ? "bg-teal/[0.06] text-teal" : "bg-navy-600/[0.05] text-navy-600"}`}>
              {siguiente.hecho
                ? <Check className="h-3.5 w-3.5 flex-none" />
                : <ArrowRight className="h-3.5 w-3.5 flex-none" />}
              <span className="font-medium">{siguiente.texto}</span>
            </div>
          )}

          {/* Terminación si existe */}
          {(ruta?.lavanderia?.nombre || ruta?.terminacion?.nombre) && (
            <p className="text-[0.65rem] text-graphite">
              {ruta?.lavanderia?.nombre && (
                <>Lavandería: <span className="font-semibold text-ink-900">{ruta.lavanderia.nombre}</span></>
              )}
              {ruta?.lavanderia?.nombre && ruta?.terminacion?.nombre && " · "}
              {ruta?.terminacion?.nombre && (
                <>Terminación: <span className="font-semibold text-ink-900">{ruta.terminacion.nombre}</span></>
              )}
            </p>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
