"use client";

/**
 * Módulo de IMPRESIÓN de etiquetas — trabaja en segundo plano.
 * Encola etiquetas de nylon a demanda y el agente local las imprime y CORTA:
 *   · Stickers de código de barras (ref + talla)  → Honeywell PC42E-T
 *   · Instrucciones de lavado (texto por tela/ref) → SAT TT448
 * También muestra la cola en vivo (lo que encolan las remisiones de
 * terminación aparece aquí) y permite reimprimir.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { puedeAccionModulo } from "@/lib/auth";
import { useAuth } from "@/components/auth-provider";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Printer, Loader2, AlertCircle, CheckCircle, RotateCcw, Scissors, Tag, Droplets } from "lucide-react";

interface Precosteo {
  id: string;
  codigo_referencia: string;
  nombre: string;
  tela?: string;
  instrucciones_lavado?: string;
}

interface Trabajo {
  id: string;
  tipo: string;
  destino: string;
  payload?: {
    codigo_referencia?: string;
    tallas?: Record<string, number>;
    copias?: number;
  };
  impresa_at?: string | null;
  created_at: string;
}

const TALLAS_INFERIOR = ["4", "6", "8", "10", "12", "14", "16"];
const TALLAS_SUPERIOR = ["S", "M", "L", "XL"];

function fmtHora(iso?: string | null) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

function cantidadDe(t: Trabajo): number {
  const porTallas = Object.values(t.payload?.tallas || {}).reduce((s, n) => s + (n || 0), 0);
  return porTallas || t.payload?.copias || 0;
}

export default function ModuloImpresionPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const puedeImprimir = user?.rol === "admin" || user?.rol === "operador"
    || puedeAccionModulo(user, "produccion_remisiones", "modificar")
    || puedeAccionModulo(user, "produccion_corte", "modificar");

  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  // Formulario
  const [tipo, setTipo] = useState<"sticker_codigo" | "instruccion_lavado">("sticker_codigo");
  const [refId, setRefId] = useState("");
  const [tallas, setTallas] = useState<Record<string, string>>({});
  const [cortar, setCortar] = useState(true);
  // Tallaje: inferiores 4–16 · superiores (bodys/camisetas) S–XL
  const [tallaje, setTallaje] = useState<"inferior" | "superior">("inferior");

  // ── Vista previa de la etiqueta de lavado (iterar sin gastar etiqueta) ──
  const [prevRef, setPrevRef] = useState("96613-1");
  const [prevComp, setPrevComp] = useState("98% ALGODON 2% ELASTANO");
  const [prevUrl, setPrevUrl] = useState("");
  const [prevCargando, setPrevCargando] = useState(false);
  const prevUrlRef = useRef("");
  useEffect(() => {
    let vivo = true;
    setPrevCargando(true);
    const t = setTimeout(async () => {
      try {
        const url = await api.blobUrl(
          `/api/produccion/impresion/lavado/preview?codigo=${encodeURIComponent(prevRef)}&composicion=${encodeURIComponent(prevComp)}`);
        if (!vivo) { URL.revokeObjectURL(url); return; }
        if (prevUrlRef.current) URL.revokeObjectURL(prevUrlRef.current);
        prevUrlRef.current = url;
        setPrevUrl(url);
      } catch { /* silencioso */ } finally {
        if (vivo) setPrevCargando(false);
      }
    }, 450);   // debounce: espera a que dejes de escribir
    return () => { vivo = false; clearTimeout(t); };
  }, [prevRef, prevComp]);
  const TALLAS = tallaje === "superior" ? TALLAS_SUPERIOR : TALLAS_INFERIOR;

  const refsQ = useQuery<{ precosteos?: Precosteo[] } | Precosteo[]>({
    queryKey: ["produccion", "precosteos", "modulo-impresion"],
    queryFn: () => api.get("/api/produccion/precosteo"),
  });
  const referencias = useMemo<Precosteo[]>(() => {
    if (!refsQ.data) return [];
    return Array.isArray(refsQ.data) ? refsQ.data : (refsQ.data.precosteos || []);
  }, [refsQ.data]);
  const refSel = referencias.find((r) => r.id === refId);

  // Cola en vivo: refresca sola cada 8 s (el agente imprime en segundo plano)
  const colaQ = useQuery<{ trabajos: Trabajo[] }>({
    queryKey: ["produccion", "impresion", "historial"],
    queryFn: () => api.get("/api/produccion/impresion/trabajos/historial"),
    refetchInterval: 8000,
  });
  const trabajos = colaQ.data?.trabajos || [];
  const pendientes = trabajos.filter((t) => !t.impresa_at).length;

  // Signos vitales: ¿el agente local está reportándose? ¿hay cola represada?
  const estadoQ = useQuery<{ agente_en_linea: boolean; agente_hace_s: number | null; pendientes: number; mas_viejo_min: number }>({
    queryKey: ["produccion", "impresion", "estado"],
    queryFn: () => api.get("/api/produccion/impresion/estado"),
    refetchInterval: 15000,
  });
  const salud = estadoQ.data;

  const totalStickers = TALLAS.reduce((s, t) => s + (parseInt(tallas[t] || "0", 10) || 0), 0);

  const imprimirMut = useMutation({
    mutationFn: () => {
      const tallasLimpias: Record<string, number> = {};
      for (const t of TALLAS) {
        const n = parseInt(tallas[t] || "0", 10);
        if (n > 0) tallasLimpias[t] = n;
      }
      return api.post("/api/produccion/impresion/trabajos/crear", {
        tipo,
        referencia_id: refId,
        tallas: tallasLimpias,
        cortar,
      });
    },
    onSuccess: () => {
      setMsg("Encolado — la impresora lo saca en segundos (segundo plano).");
      setErr("");
      setTallas({});
      qc.invalidateQueries({ queryKey: ["produccion", "impresion"] });
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  const reimprimirMut = useMutation({
    mutationFn: (id: string) => api.post(`/api/produccion/impresion/trabajos/${id}/reimprimir`),
    onSuccess: () => {
      setMsg("Reencolado para reimprimir.");
      qc.invalidateQueries({ queryKey: ["produccion", "impresion"] });
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  if (refsQ.isLoading) return <LoadingState label="Cargando módulo de impresión…" />;
  if (refsQ.isError) return <ErrorState error={refsQ.error} onRetry={() => refsQ.refetch()} />;

  const listo = !!refId && totalStickers > 0;

  return (
    <PageShell title="Impresión de etiquetas" subtitle="Nylon · imprime y corta en segundo plano — Honeywell (stickers) · SAT (lavado)">
      {/* Signos vitales del circuito: agente + cola. Verde = todo fluye. */}
      {salud && (
        <div className="flex flex-wrap items-center gap-2">
          <span className={`inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1 text-[0.65rem] font-semibold uppercase tracking-widest ${
            salud.agente_en_linea
              ? "border-teal/40 bg-teal/5 text-teal"
              : "border-terracotta/40 bg-terra-soft text-terracotta"
          }`}>
            <span className={`h-1.5 w-1.5 rounded-full ${salud.agente_en_linea ? "bg-teal" : "bg-terracotta"}`} />
            {salud.agente_en_linea
              ? `Agente de impresión en línea · hace ${salud.agente_hace_s}s`
              : salud.agente_hace_s == null
                ? "Agente de impresión sin reportarse desde el último reinicio"
                : `Agente de impresión SIN CONEXIÓN · hace ${Math.round(salud.agente_hace_s / 60)} min — revisa que el Mac del agente esté prendido`}
          </span>
          {salud.pendientes > 0 && salud.mas_viejo_min >= 5 && (
            <span className="inline-flex items-center gap-1.5 rounded-sm border border-amber-400/50 bg-amber-50 px-2.5 py-1 text-[0.65rem] font-semibold uppercase tracking-widest text-amber-700">
              <AlertCircle className="h-3 w-3" />
              {salud.pendientes} trabajo(s) esperando hace {salud.mas_viejo_min} min — ¿impresora apagada o sin cinta?
            </span>
          )}
        </div>
      )}
      {msg && (
        <div className="rounded-sm border border-teal/30 bg-teal-soft px-4 py-2.5 text-xs text-teal flex items-center gap-2">
          <CheckCircle className="h-4 w-4 flex-none" /> {msg}
        </div>
      )}
      {err && (
        <div className="rounded-sm border border-terracotta/30 bg-terra-soft px-4 py-2.5 text-xs text-terracotta flex items-center gap-2">
          <AlertCircle className="h-4 w-4 flex-none" /> {err}
        </div>
      )}

      {/* Vista previa de la etiqueta de lavado — editar y ver sin imprimir */}
      <Card>
        <CardContent className="p-5">
          <p className="section-label mb-3 flex items-center gap-2">
            <Droplets className="h-3.5 w-3.5" /> Vista previa · etiqueta de lavado
          </p>
          <div className="grid gap-5 md:grid-cols-[1fr_auto]">
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-[0.68rem] uppercase tracking-widest text-graphite">Referencia</span>
                <input value={prevRef} onChange={(e) => setPrevRef(e.target.value)}
                  className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-sm" />
              </label>
              <label className="block">
                <span className="mb-1 block text-[0.68rem] uppercase tracking-widest text-graphite">Composición de la tela</span>
                <input value={prevComp} onChange={(e) => setPrevComp(e.target.value)}
                  placeholder="98% ALGODON 2% ELASTANO"
                  className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-sm" />
              </label>
              <p className="text-[0.7rem] text-graphite leading-relaxed">
                Esta es exactamente la imagen que se imprime en la SAT (a escala).
                Edita y la vista se actualiza sola. Dime qué ajustar aquí antes de imprimir.
              </p>
            </div>
            <div className="flex flex-col items-center gap-2">
              <div className="relative rounded-sm border border-border bg-white p-2"
                style={{ width: 150 }}>
                {prevCargando && (
                  <span className="absolute right-3 top-3 text-graphite"><Loader2 className="h-3.5 w-3.5 animate-spin" /></span>
                )}
                {prevUrl
                  ? <img src={prevUrl} alt="Vista previa etiqueta de lavado"
                      className="w-full h-auto" style={{ imageRendering: "pixelated" }} />
                  : <div className="h-[600px] grid place-items-center text-[0.65rem] text-graphite">Cargando…</div>}
              </div>
              <span className="text-[0.6rem] text-graphite">27.5 × 130 mm</span>
              <a href="/produccion/impresion/editor-lavado"
                className="mt-1 inline-flex items-center gap-1.5 rounded-sm border border-navy-600 bg-navy-600 px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:bg-navy-700">
                <Tag className="h-3 w-3" /> Editar diseño
              </a>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Imprimir ahora */}
      {puedeImprimir && (
        <Card>
          <CardContent className="p-5 space-y-4">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <p className="section-label">Imprimir ahora</p>
              <label className="inline-flex items-center gap-2 text-xs text-graphite cursor-pointer">
                <input type="checkbox" checked={cortar} onChange={(e) => setCortar(e.target.checked)}
                  className="h-3.5 w-3.5 accent-teal" />
                <Scissors className="h-3.5 w-3.5" /> Cortar cada etiqueta
              </label>
            </div>

            {/* Tipo */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <button onClick={() => setTipo("sticker_codigo")}
                className={`rounded-sm border px-4 py-3 text-left transition-colors ${tipo === "sticker_codigo"
                  ? "border-teal bg-teal-soft" : "border-border bg-card hover:bg-cloud"}`}>
                <p className="flex items-center gap-2 text-sm font-semibold text-ink-900">
                  <Tag className="h-4 w-4 text-teal" /> Stickers de código de barras
                </p>
                <p className="mt-0.5 text-[0.7rem] text-graphite">Ref + talla · 1 por prenda (bolsa de empaque) → Honeywell</p>
              </button>
              <button onClick={() => setTipo("instruccion_lavado")}
                className={`rounded-sm border px-4 py-3 text-left transition-colors ${tipo === "instruccion_lavado"
                  ? "border-teal bg-teal-soft" : "border-border bg-card hover:bg-cloud"}`}>
                <p className="flex items-center gap-2 text-sm font-semibold text-ink-900">
                  <Droplets className="h-4 w-4 text-navy-600" /> Instrucciones de lavado
                </p>
                <p className="mt-0.5 text-[0.7rem] text-graphite">Texto por tela/referencia → SAT</p>
              </button>
            </div>

            {/* Referencia */}
            <div>
              <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                Referencia
              </label>
              <select value={refId} onChange={(e) => setRefId(e.target.value)}
                className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm text-ink-900">
                <option value="">Selecciona la referencia…</option>
                {referencias.map((r) => (
                  <option key={r.id} value={r.id}>{r.codigo_referencia} · {r.nombre}</option>
                ))}
              </select>
              {tipo === "instruccion_lavado" && refSel && !refSel.instrucciones_lavado && (
                <p className="mt-1 text-[0.7rem] text-terracotta">
                  Esta referencia no tiene composición guardada (ej. 100%ALGODON) — la etiqueta saldrá sin esa línea. Se agrega editando el precosteo.
                </p>
              )}
            </div>

            {/* Cantidades por talla (los dos tipos llevan talla en la etiqueta) */}
            <div>
              <div className="mb-1.5 flex items-center gap-3">
                <p className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                  Cantidad por talla
                </p>
                <div className="inline-flex rounded-sm border border-border overflow-hidden">
                  {([["inferior", "4–16"], ["superior", "S–XL"]] as ["inferior" | "superior", string][]).map(([tj, label]) => (
                    <button key={tj} type="button"
                      onClick={() => { setTallaje(tj); setTallas({}); }}
                      className={`px-2.5 py-1 text-[0.65rem] font-semibold uppercase tracking-widest ${tallaje === tj
                        ? "bg-navy-600 text-white" : "bg-card text-graphite hover:bg-cloud"}`}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-4 md:grid-cols-7 gap-2">
                {TALLAS.map((t) => (
                  <div key={t}>
                    <label className="mb-1 block text-center text-[0.68rem] uppercase tracking-widest text-graphite">T{t}</label>
                    <input value={tallas[t] || ""} onChange={(e) => setTallas({ ...tallas, [t]: e.target.value })}
                      inputMode="numeric" placeholder="0"
                      className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-center text-sm tabular" />
                  </div>
                ))}
              </div>
              <p className="mt-1 text-[0.7rem] text-graphite">
                Total: <span className="font-semibold text-ink-900 tabular">{totalStickers}</span> etiqueta(s)
                {tipo === "instruccion_lavado" && " · el lavado imprime +1% de margen"}
              </p>
            </div>

            <div className="flex justify-end">
              <button onClick={() => imprimirMut.mutate()} disabled={!listo || imprimirMut.isPending}
                className="inline-flex items-center gap-2 rounded-sm bg-teal px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
                {imprimirMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Printer className="h-4 w-4" />}
                Imprimir
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Cola en vivo */}
      <Card>
        <CardContent className="p-5">
          <div className="mb-3 flex items-center justify-between flex-wrap gap-2">
            <p className="section-label">Cola de impresión</p>
            <span className="text-[0.7rem] text-graphite">
              {pendientes > 0
                ? <span className="inline-flex items-center gap-1.5 text-teal font-semibold">
                    <span className="h-2 w-2 rounded-full bg-teal animate-pulse" /> {pendientes} pendiente(s) — imprimiendo en segundo plano
                  </span>
                : "Al día — sin pendientes"}
            </span>
          </div>
          {trabajos.length === 0 ? (
            <p className="text-xs text-graphite">Aún no hay trabajos. Lo que imprimas aquí o encolen las remisiones de terminación aparecerá en esta lista.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-[0.62rem] uppercase tracking-widest text-graphite">
                    <th className="py-2 pr-3">Hora</th>
                    <th className="py-2 pr-3">Tipo</th>
                    <th className="py-2 pr-3">Referencia</th>
                    <th className="py-2 pr-3">Impresora</th>
                    <th className="py-2 pr-3 text-right">Cant.</th>
                    <th className="py-2 pr-3">Estado</th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody>
                  {trabajos.map((t) => (
                    <tr key={t.id} className="border-b border-border/60 hover:bg-cloud/40">
                      <td className="py-2 pr-3 tabular text-graphite">{fmtHora(t.created_at)}</td>
                      <td className="py-2 pr-3">
                        {t.tipo === "sticker_codigo"
                          ? <span className="inline-flex items-center gap-1"><Tag className="h-3 w-3 text-teal" /> Stickers</span>
                          : <span className="inline-flex items-center gap-1"><Droplets className="h-3 w-3 text-navy-600" /> Lavado</span>}
                      </td>
                      <td className="py-2 pr-3 font-semibold text-ink-900">{t.payload?.codigo_referencia || "—"}</td>
                      <td className="py-2 pr-3 uppercase text-graphite">{t.destino}</td>
                      <td className="py-2 pr-3 text-right tabular">{cantidadDe(t)}</td>
                      <td className="py-2 pr-3">
                        {t.impresa_at
                          ? <Badge tone="normal">Impresa {fmtHora(t.impresa_at)}</Badge>
                          : <Badge tone="pendiente">Pendiente</Badge>}
                      </td>
                      <td className="py-2 text-right">
                        {puedeImprimir && t.impresa_at && (
                          <button onClick={() => reimprimirMut.mutate(t.id)} disabled={reimprimirMut.isPending}
                            title="Volver a imprimir"
                            className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-2 py-1 text-[0.65rem] font-semibold uppercase tracking-widest text-graphite hover:bg-cloud hover:text-ink-900 disabled:opacity-40">
                            <RotateCcw className="h-3 w-3" /> Reimprimir
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
