"use client";

/**
 * Cierre de bodega — el conteo final de cada lote.
 *
 * POR QUÉ (Sebastián, 2026-10-23/29): las prendas se perdían en el camino y solo
 * se descubría contando al final, por fuera del OS y sin saber en qué paso. Aquí
 * quien recibe en bodega cuenta POR TALLA lo que llegó de terminación; el OS lo
 * cruza contra lo que se cortó de ese lote y muestra la cadena completa
 * (corte → confección → lavandería → terminación → bodega) con el faltante
 * marcado en el paso donde se perdió.
 *
 * Reglas: el conteo entra "por confirmar" (sin alerta); al confirmarlo el lote
 * pasa a "en bodega" y, si falta algo, salta la campanita. Un faltante queda
 * abierto hasta que un admin lo justifique. Sin este conteo el lote no puede
 * pasar a bodega (el backend lo bloquea).
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { esAdmin, puedeAccionModulo } from "@/lib/auth";
import { useAuth } from "@/components/auth-provider";
import { ordenarTallas } from "@/lib/espigas";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, CheckCircle, Loader2, Search, ArrowRight } from "lucide-react";

type Tono = "critico" | "riesgo" | "normal" | "pendiente" | "info" | "neutral";

interface Paso {
  paso: string;
  nombre: string;
  total: number | null;
  por_talla: Record<string, number> | null;
  estado: string;
  faltan_vs_anterior: number | null;
  se_perdio_aqui: boolean;
  detalle?: { recibio: number | null; entrego: number | null };
}

interface Cruce {
  base: Record<string, number>;
  recibido: Record<string, number>;
  faltan: Record<string, number>;
  sobran: Record<string, number>;
  estado: string;
  total_faltan: number;
  total_sobran: number;
  cuadre_estado: "por_confirmar" | "confirmado" | "justificado" | null;
  base_fuente: string;
}

interface Lote {
  orden_corte_id: string;
  consecutivo: string | null;
  referencia_id: string | null;
  referencia: string | null;
  referencia_nombre: string | null;
  etapa: string | null;
  terminacion: string | null;
  base_fuente: string;
  pasos: Paso[];
  cruce_bodega: Cruce;
  cierre: string;
  total_cortado: number;
  total_faltan_bodega: number | null;
  donde_se_perdio: string[];
  justificado_motivo: string | null;
  /** Corte cortado que nunca tuvo hoja de ruta (se fue a confección sin remisión). */
  sin_hoja_ruta?: boolean;
}

const CIERRE: Record<string, { txt: string; tono: Tono }> = {
  sin_conteo_final: { txt: "Sin conteo final", tono: "pendiente" },
  por_confirmar:    { txt: "Por confirmar",    tono: "pendiente" },
  faltante:         { txt: "Faltan",           tono: "critico" },
  revisar:          { txt: "Revisar",          tono: "riesgo" },
  cerrado_limpio:   { txt: "Cerrado limpio",   tono: "normal" },
  justificado:      { txt: "Justificado",      tono: "neutral" },
};

const ETAPA: Record<string, string> = {
  asignado: "Asignado", aceptado: "Aceptado", en_confeccion: "En confección",
  lavanderia: "En lavandería", terminacion_recibida: "En terminación",
  terminacion_terminada: "Terminado", despachado: "En bodega",
};

function BadgeCierre({ l }: { l: Lote }) {
  const c = CIERRE[l.cierre] || { txt: l.cierre, tono: "neutral" as Tono };
  const n = l.cierre === "faltante" && l.total_faltan_bodega ? ` ${l.total_faltan_bodega}` : "";
  return <Badge tone={c.tono}>{c.txt}{n}</Badge>;
}

export default function CierreBodegaPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<"abiertos" | "cerrados">("abiertos");
  const [busca, setBusca] = useState("");
  const [sel, setSel] = useState<{ oc: string; ref: string } | null>(null);

  // Se lee ?lote=&ref= sin useSearchParams para no exigir un Suspense en el build
  // (mismo patrón que corte/nueva). Llega así desde la alerta y desde el corte.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const oc = p.get("lote");
    if (oc) setSel({ oc, ref: p.get("ref") || "" });
  }, []);

  const q = useQuery<{ lotes: Lote[] }>({
    queryKey: ["cierre-bodega", tab],
    queryFn: () => api.get(`/api/produccion/cierre-bodega?estado=${tab}`),
  });

  const lotes = useMemo(() => {
    const t = busca.trim().toLowerCase();
    const xs = q.data?.lotes || [];
    if (!t) return xs;
    return xs.filter((l) =>
      [l.consecutivo, l.referencia, l.referencia_nombre, l.terminacion]
        .some((v) => (v || "").toLowerCase().includes(t)));
  }, [q.data, busca]);

  const puedeContar = ["produccion_remisiones", "produccion_corte", "produccion_cortador"]
    .some((m) => puedeAccionModulo(user, m, "modificar"));

  function elegir(l: Lote) {
    const s = { oc: l.orden_corte_id, ref: l.referencia_id || "" };
    setSel(s);
    window.history.replaceState(null, "", `?lote=${s.oc}${s.ref ? `&ref=${s.ref}` : ""}`);
  }

  return (
    <PageShell title="Cierre de bodega"
      subtitle="Lo que llegó a bodega, por talla, contra lo que se cortó — y dónde se perdió lo que falta"
      isFetching={q.isFetching} onRefresh={() => q.refetch()} dataUpdatedAt={q.dataUpdatedAt}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            {(["abiertos", "cerrados"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`rounded-sm border px-3 py-1.5 text-xs font-semibold uppercase tracking-widest ${tab === t ? "border-navy-600 bg-navy-600 text-white" : "border-border bg-card text-graphite hover:bg-cloud"}`}>
                {t === "abiertos" ? "Por cerrar" : "Cerrados"}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 rounded-sm border border-border bg-card px-3 py-2">
            <Search className="h-3.5 w-3.5 flex-none text-graphite" />
            <input id="busca-lote" value={busca} onChange={(e) => setBusca(e.target.value)}
              placeholder="Buscar lote, referencia o taller…"
              className="w-full bg-transparent text-sm outline-none" />
          </div>

          {q.isLoading ? <LoadingState label="Cargando lotes…" />
            : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
            : lotes.length === 0 ? (
              <p className="rounded-sm border border-border bg-card p-4 text-xs text-graphite">
                {tab === "abiertos" ? "No hay lotes por cerrar." : "Todavía no hay lotes cerrados."}
              </p>
            ) : (
              <div className="space-y-2">
                {lotes.map((l) => {
                  const activo = sel?.oc === l.orden_corte_id && (sel.ref || "") === (l.referencia_id || "");
                  return (
                    <button key={`${l.orden_corte_id}-${l.referencia_id}`} onClick={() => elegir(l)}
                      className={`w-full rounded-sm border p-3 text-left transition-colors ${activo ? "border-navy-600 bg-navy-600/[0.05]" : "border-border bg-card hover:bg-cloud/50"}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-ink-900 tabular">{l.consecutivo || "—"}</span>
                        <BadgeCierre l={l} />
                      </div>
                      <p className="mt-0.5 truncate text-xs text-graphite">
                        {l.referencia || "—"}{l.referencia_nombre ? ` · ${l.referencia_nombre}` : ""}
                      </p>
                      <p className="mt-1 text-[0.7rem] text-graphite tabular">
                        {l.total_cortado} cortadas · {l.sin_hoja_ruta ? "sin hoja de ruta" : ETAPA[l.etapa || ""] || l.etapa || "—"}
                        {l.donde_se_perdio.length > 0 && (
                          <span className="text-terracotta font-semibold"> · se perdieron en {l.donde_se_perdio.join(", ")}</span>
                        )}
                      </p>
                    </button>
                  );
                })}
              </div>
            )}
        </div>

        <div>
          {sel ? (
            <DetalleLote key={`${sel.oc}-${sel.ref}`} oc={sel.oc} refId={sel.ref}
              puedeContar={puedeContar} puedeJustificar={esAdmin(user ?? undefined)} />
          ) : (
            <Card><CardContent className="p-6 text-sm text-graphite">
              Elige un lote para ver su cadena y hacer el conteo final.
            </CardContent></Card>
          )}
        </div>
      </div>
    </PageShell>
  );
}

function DetalleLote({ oc, refId, puedeContar, puedeJustificar }: {
  oc: string; refId: string; puedeContar: boolean; puedeJustificar: boolean;
}) {
  const qc = useQueryClient();
  const qs = refId ? `?referencia_id=${refId}` : "";
  const q = useQuery<Lote>({
    queryKey: ["cierre-bodega", "lote", oc, refId],
    queryFn: () => api.get(`/api/produccion/cierre-bodega/lote/${oc}${qs}`),
  });
  const refrescar = () => {
    qc.invalidateQueries({ queryKey: ["cierre-bodega"] });
    qc.invalidateQueries({ queryKey: ["produccion", "corte", oc] });
  };

  if (q.isLoading) return <LoadingState label="Cargando lote…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const l = q.data;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-5 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-lg font-semibold text-ink-900 tabular">{l.consecutivo}</p>
            <BadgeCierre l={l} />
          </div>
          <p className="text-sm text-graphite">
            {l.referencia || "—"}{l.referencia_nombre ? ` · ${l.referencia_nombre}` : ""}
            {l.terminacion ? ` · terminación: ${l.terminacion}` : ""}
            {` · ${l.sin_hoja_ruta ? "sin hoja de ruta" : ETAPA[l.etapa || ""] || l.etapa || "—"}`}
          </p>
          {l.sin_hoja_ruta && (
            <p className="text-xs text-graphite">
              Este corte se fue a confección sin remisión en el OS. Igual puedes contar lo que llegó a bodega.
            </p>
          )}
          {l.base_fuente === "programado" && (
            <p className="mt-2 flex items-start gap-2 rounded-sm border border-ochre/40 bg-ochre/10 px-3 py-2 text-xs text-ink-900">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-none" />
              Este corte no tiene unidades cortadas registradas: se compara contra lo programado.
              Revisa el informe de corte antes de dar el lote por cerrado.
            </p>
          )}
        </CardContent>
      </Card>

      <Cadena pasos={l.pasos} />
      <ConteoBodega l={l} oc={oc} refId={refId} qs={qs}
        puedeContar={puedeContar} puedeJustificar={puedeJustificar} onCambio={refrescar} />
    </div>
  );
}

function Cadena({ pasos }: { pasos: Paso[] }) {
  return (
    <Card>
      <CardContent className="p-5">
        <p className="section-label mb-3">Recorrido del lote</p>
        <ol className="grid grid-cols-1 gap-2 sm:grid-cols-5">
          {pasos.map((p, i) => (
            <li key={p.paso}
              className={`relative rounded-sm border p-3 ${p.se_perdio_aqui ? "border-terracotta/50 bg-terracotta/[0.06]" : "border-border bg-card"}`}>
              <div className="flex items-center justify-between gap-1">
                <span className="text-[0.7rem] font-semibold uppercase tracking-widest text-graphite">{p.nombre}</span>
                {i < pasos.length - 1 && <ArrowRight className="hidden h-3 w-3 text-graphite/50 sm:block" />}
              </div>
              <p className={`mt-1 text-xl font-semibold tabular ${p.total === null ? "text-graphite/50" : "text-ink-900"}`}>
                {p.estado === "omitido" ? "—" : p.total ?? "—"}
              </p>
              <p className="text-[0.68rem] text-graphite">
                {p.estado === "omitido" ? "no lleva"
                  : p.total === null ? "sin dato"
                  : p.estado === "por_confirmar" ? "por confirmar"
                  : p.estado === "programado" ? "programado"
                  : p.por_talla ? "por talla" : "total"}
              </p>
              {p.detalle && p.total !== null && (
                <p className="text-[0.65rem] text-graphite tabular">
                  recibió {p.detalle.recibio ?? "—"} · entregó {p.detalle.entrego ?? "—"}
                </p>
              )}
              {p.se_perdio_aqui && (
                <p className="mt-1 text-xs font-semibold text-terracotta tabular">−{p.faltan_vs_anterior} aquí</p>
              )}
            </li>
          ))}
        </ol>
        <p className="mt-3 text-[0.68rem] text-graphite">
          Confección y bodega se cuentan por talla. Lavandería y terminación traen el total que reportan en su enlace.
        </p>
      </CardContent>
    </Card>
  );
}

function ConteoBodega({ l, oc, refId, qs, puedeContar, puedeJustificar, onCambio }: {
  l: Lote; oc: string; refId: string; qs: string;
  puedeContar: boolean; puedeJustificar: boolean; onCambio: () => void;
}) {
  const c = l.cruce_bodega;
  const tallas = ordenarTallas(Array.from(new Set([...Object.keys(c.base), ...Object.keys(c.recibido)])));
  const [editando, setEditando] = useState(c.cuadre_estado === null);
  const [conteo, setConteo] = useState<Record<string, string>>({});
  const [motivo, setMotivo] = useState("");
  const [justificando, setJustificando] = useState(false);
  const [err, setErr] = useState("");

  const guardar = useMutation({
    mutationFn: () => {
      const unidades: Record<string, number> = {};
      for (const t of tallas) unidades[t] = parseInt((conteo[t] || "").replace(/\D/g, ""), 10) || 0;
      return api.post(`/api/produccion/cuadre/${oc}/bodega`,
        { unidades, fuente: "manual", referencia_id: refId || null });
    },
    onSuccess: () => { setEditando(false); setErr(""); onCambio(); },
    onError: (e: Error) => setErr(e.message),
  });
  const confirmar = useMutation({
    mutationFn: () => api.post(`/api/produccion/cuadre/${oc}/bodega/confirmar${qs}`, {}),
    onSuccess: () => { setErr(""); onCambio(); },
    onError: (e: Error) => setErr(e.message),
  });
  const justificar = useMutation({
    mutationFn: () => api.post(`/api/produccion/cuadre/${oc}/bodega/justificar`,
      { motivo: motivo.trim(), referencia_id: refId || null }),
    onSuccess: () => { setJustificando(false); setMotivo(""); setErr(""); onCambio(); },
    onError: (e: Error) => setErr(e.message),
  });

  const completo = tallas.length > 0 && tallas.every((t) => (conteo[t] ?? "").trim() !== "");
  const totalDigitado = tallas.reduce((s, t) => s + (parseInt((conteo[t] || "").replace(/\D/g, ""), 10) || 0), 0);
  const detalleFaltan = Object.entries(c.faltan).map(([t, n]) => `T${t} −${n}`).join(", ");

  function abrir() {
    const seed: Record<string, string> = {};
    for (const t of tallas) seed[t] = c.recibido[t] !== undefined ? String(c.recibido[t]) : "";
    setConteo(seed); setEditando(true); setErr("");
  }

  function pedirConfirmacion() {
    const msg = c.total_faltan > 0
      ? `Faltan ${c.total_faltan} prendas contra lo cortado (${detalleFaltan}).\n\n` +
        "Al confirmar, el lote queda EN BODEGA con el faltante abierto y se avisa a remisiones. ¿Confirmar?"
      : "Llegó todo lo que se cortó. ¿Confirmar el ingreso a bodega?";
    if (window.confirm(msg)) confirmar.mutate();
  }

  return (
    <Card>
      <CardContent className="p-5 space-y-3">
        <p className="section-label">Conteo final en bodega</p>

        {tallas.length === 0 ? (
          <p className="text-xs text-graphite">Este lote no tiene tallas cortadas ni programadas para comparar.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                  <th className="px-2 py-1.5">Talla</th>
                  <th className="px-2 py-1.5 text-right">Cortado</th>
                  <th className="px-2 py-1.5 text-right">Llegó</th>
                  <th className="px-2 py-1.5 text-right">Diferencia</th>
                </tr>
              </thead>
              <tbody>
                {tallas.map((t) => {
                  const cort = c.base[t] ?? 0;
                  const llego = editando
                    ? (conteo[t] ?? "").trim() === "" ? null : parseInt(conteo[t].replace(/\D/g, ""), 10) || 0
                    : c.cuadre_estado === null ? null : c.recibido[t] ?? 0;
                  const dif = llego === null ? null : llego - cort;
                  return (
                    <tr key={t} className="border-b border-border/40">
                      <td className="px-2 py-1 font-semibold text-ink-900">T{t}</td>
                      <td className="px-2 py-1 text-right tabular">{cort || "—"}</td>
                      <td className="px-2 py-1 text-right tabular">
                        {editando ? (
                          <input id={`llego-${t}`} value={conteo[t] ?? ""} inputMode="numeric"
                            onChange={(e) => setConteo((p) => ({ ...p, [t]: e.target.value }))}
                            placeholder={String(cort || 0)} aria-label={`Llegó talla ${t}`}
                            className="w-16 rounded-sm border border-border bg-white px-2 py-1 text-right text-xs tabular placeholder:text-graphite/40" />
                        ) : (llego ?? "—")}
                      </td>
                      <td className={`px-2 py-1 text-right tabular font-semibold ${dif === null ? "text-graphite/50" : dif < 0 ? "text-terracotta" : dif > 0 ? "text-ochre" : "text-teal"}`}>
                        {dif === null ? "" : dif === 0 ? "0" : dif > 0 ? `+${dif}` : `${dif}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t border-border">
                  <td className="px-2 py-1.5 text-[0.65rem] uppercase tracking-widest text-graphite">Total</td>
                  <td className="px-2 py-1.5 text-right tabular font-semibold">{l.total_cortado}</td>
                  <td className="px-2 py-1.5 text-right tabular font-semibold">
                    {editando ? totalDigitado : c.cuadre_estado === null ? "—" : Object.values(c.recibido).reduce((s, n) => s + n, 0)}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}

        {l.cierre === "cerrado_limpio" && (
          <p className="flex items-center gap-2 text-sm font-semibold text-teal">
            <CheckCircle className="h-4 w-4" /> Cerrado limpio: llegó todo lo que se cortó.
          </p>
        )}
        {l.cierre === "faltante" && (
          <p className="text-sm font-semibold text-terracotta">
            Faltan {c.total_faltan}: {detalleFaltan}.
            {l.donde_se_perdio.length > 0 && ` Se perdieron en ${l.donde_se_perdio.join(", ")}.`}
          </p>
        )}
        {l.cierre === "revisar" && c.total_sobran > 0 && (
          <p className="text-sm text-ink-900">Llegaron {c.total_sobran} prenda(s) más de las cortadas. Revisa el conteo.</p>
        )}
        {l.cierre === "justificado" && (
          <p className="text-sm text-graphite">Faltante justificado: <span className="font-medium text-ink-900">{l.justificado_motivo || "—"}</span></p>
        )}

        {err && (
          <div role="alert" className="flex items-center gap-2 rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
            <AlertCircle className="h-3.5 w-3.5" /> {err}
          </div>
        )}

        {puedeContar && tallas.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            {editando ? (
              <>
                <button onClick={() => guardar.mutate()} disabled={!completo || guardar.isPending}
                  className="inline-flex items-center gap-1 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40">
                  {guardar.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />} Guardar conteo
                </button>
                {c.cuadre_estado !== null && (
                  <button onClick={() => { setEditando(false); setErr(""); }}
                    className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-graphite hover:bg-cloud">
                    Cancelar
                  </button>
                )}
                {!completo && (
                  <span className="text-[0.7rem] text-graphite">Llena todas las tallas (pon 0 si no llegó ninguna).</span>
                )}
              </>
            ) : c.cuadre_estado === "por_confirmar" ? (
              <>
                <button onClick={pedirConfirmacion} disabled={confirmar.isPending}
                  className="inline-flex items-center gap-1 rounded-sm bg-teal px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-ink-900 disabled:opacity-40">
                  {confirmar.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />} Confirmar e ingresar a bodega
                </button>
                <button onClick={abrir}
                  className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud">
                  Corregir conteo
                </button>
              </>
            ) : null}
          </div>
        )}

        {c.cuadre_estado === "por_confirmar" && !editando && (
          <p className="text-[0.68rem] text-graphite">
            El conteo está <span className="font-semibold">por confirmar</span>: todavía no avisa ni pasa el lote a bodega.
          </p>
        )}

        {puedeJustificar && l.cierre === "faltante" && (
          justificando ? (
            <div className="flex flex-wrap items-center gap-2">
              <input id="motivo-justificar" value={motivo} onChange={(e) => setMotivo(e.target.value)}
                placeholder="Motivo (dañadas, segundas, re-conteo…)"
                className="min-w-[200px] flex-1 rounded-sm border border-border bg-white px-3 py-2 text-xs" />
              <button onClick={() => justificar.mutate()} disabled={!motivo.trim() || justificar.isPending}
                className="inline-flex items-center gap-1 rounded-sm bg-teal px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-ink-900 disabled:opacity-40">
                {justificar.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />} Justificar
              </button>
              <button onClick={() => { setJustificando(false); setMotivo(""); }}
                className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-graphite hover:bg-cloud">
                Cancelar
              </button>
            </div>
          ) : (
            <button onClick={() => setJustificando(true)}
              className="rounded-sm border border-terracotta/40 bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-terracotta hover:bg-terracotta/[0.06]">
              Justificar faltante
            </button>
          )
        )}
      </CardContent>
    </Card>
  );
}
