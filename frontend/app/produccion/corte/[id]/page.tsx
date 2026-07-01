"use client";

/**
 * Detalle de orden de corte.
 * - Info cabecera + curva
 * - Pistola de rollos: input que recibe el barcode + metros a usar → agrega al corte
 * - Botón cerrar → registra consumo real, descuenta inventario, marca 'cortada'
 */
import { useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft, ScanLine, Trash2, Lock, Loader2, AlertCircle, CheckCircle,
} from "lucide-react";

interface RolloLink {
  id: string;
  rollo_id: string;
  metros_usados: number;
  rollo?: {
    codigo_interno: string;
    barcode: string;
    descripcion_tela: string;
    tono?: string;
    metros_disponible: number;
    metros_inicial: number;
    costo_metro?: number;
  };
}

interface RolloInv {
  id: string;
  codigo_interno: string;
  barcode: string;
  descripcion_tela: string;
  tono?: string;
  metros_disponible: number;
  metros_inicial: number;
  costo_metro?: number;
  estado: string;
  lote_fabrica?: string;
  numero_rollo?: string;
}

interface OrdenCorte {
  id: string;
  consecutivo: string;
  tono?: string;
  largo_trazo: number;
  prendas_por_trazo: number;
  curva_trazo: Record<string, number>;
  num_capas: number;
  prendas_estimadas: number;
  metros_consumidos: number;   // teórico
  rendimiento_teorico?: number;
  consumo_real_cortador?: number;
  diferencia_pct?: number;
  merma_tipo?: string;
  merma_valor?: number;
  responsable?: string;
  fecha_limite?: string;
  indicaciones?: string;
  estado: string;
  referencia?: {
    codigo_referencia: string;
    nombre: string;
    tela?: string;
    color?: string;
    foto_url?: string;
  };
  rollos: RolloLink[];
}

export default function DetalleOrdenCortePage() {
  const params = useParams();
  const id = params?.id as string;
  const qc = useQueryClient();
  const barcodeRef = useRef<HTMLInputElement>(null);
  const metrosRef = useRef<HTMLInputElement>(null);

  const [barcode, setBarcode] = useState("");
  const [metros, setMetros] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const [consumoReal, setConsumoReal] = useState("");
  const [mermaTipo, setMermaTipo] = useState("");
  const [mermaValor, setMermaValor] = useState("");

  const q = useQuery<OrdenCorte>({
    queryKey: ["produccion", "corte", id],
    queryFn: () => api.get(`/api/produccion/corte/${id}`),
    enabled: !!id,
  });

  // Trae TODOS los rollos disponibles y los partimos en cliente:
  //   - "match" (coinciden con la tela del precosteo, se muestran arriba)
  //   - "otros" (por si el nombre no está idéntico, opción manual)
  const telaRef = (q.data?.referencia?.tela || "").trim();
  const rollosInvQ = useQuery<{ rollos: RolloInv[] }>({
    queryKey: ["produccion", "rollos", "disponibles"],
    queryFn: () => api.get(`/api/produccion/rollos?estado=disponible&limit=500`),
    enabled: !!q.data && q.data.estado !== "cortada",
  });

  // Normaliza: mayúsculas, sin acentos ni signos, colapsando espacios.
  function norm(s?: string) {
    return (s || "")
      .toString()
      .normalize("NFD").replace(/[̀-ͯ]/g, "")
      .toUpperCase()
      .replace(/[^A-Z0-9 ]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }
  const telaNorm = norm(telaRef);
  const telaTokens = telaNorm.split(" ").filter((t) => t.length >= 3);
  function matcheaTela(descripcion?: string) {
    if (!telaNorm) return false;
    const d = norm(descripcion);
    if (!d) return false;
    if (d.includes(telaNorm) || telaNorm.includes(d)) return true;
    // Coincide si comparten al menos 1 token significativo (≥3 chars)
    return telaTokens.some((t) => d.includes(t));
  }

  const todosRollos = rollosInvQ.data?.rollos || [];
  const rollosMatch = todosRollos.filter((r) => matcheaTela(r.descripcion_tela));
  const rollosOtros = todosRollos.filter((r) => !matcheaTela(r.descripcion_tela));

  const pistolar = useMutation({
    mutationFn: () =>
      api.post(`/api/produccion/corte/${id}/pistolear`, {
        barcode: barcode.trim(),
        metros_reservar: parseFloat(metros || "0"),
      }),
    onSuccess: () => {
      setMsg(`✓ Rollo agregado (${metros} m)`);
      setErr("");
      setBarcode("");
      setMetros("");
      qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
      setTimeout(() => barcodeRef.current?.focus(), 50);
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  const quitar = useMutation({
    mutationFn: (rollo_id: string) =>
      api.del(`/api/produccion/corte/${id}/rollo/${rollo_id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["produccion", "corte", id] }),
    onError: (e: Error) => setErr(e.message),
  });

  const cerrar = useMutation({
    mutationFn: () =>
      api.post(`/api/produccion/corte/${id}/cerrar`, {
        consumo_real_cortador: parseFloat(consumoReal || "0"),
        merma_tipo: mermaTipo || null,
        merma_valor: mermaValor ? parseFloat(mermaValor) : null,
      }),
    onSuccess: () => {
      setMsg("Orden cerrada. Inventario descontado.");
      setErr("");
      qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  if (q.isLoading) return <LoadingState label="Cargando orden de corte…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const oc = q.data;
  const cerrada = oc.estado === "cortada";
  const totalMetrosAsignados = (oc.rollos || []).reduce(
    (s, l) => s + (Number(l.metros_usados) || 0), 0,
  );

  return (
    <PageShell
      title={oc.consecutivo}
      subtitle={`${oc.referencia?.codigo_referencia || ""} · ${oc.referencia?.nombre || ""}`}
    >
      <div className="flex items-center justify-between">
        <Link href="/produccion/corte" className="inline-flex items-center gap-1 text-xs text-graphite hover:text-ink-900">
          <ArrowLeft className="h-3.5 w-3.5" /> Volver a órdenes
        </Link>
        <Badge tone={cerrada ? "normal" : "pendiente"}>
          {cerrada ? <><Lock className="inline h-2.5 w-2.5 mr-1" />Cortada</> : oc.estado}
        </Badge>
      </div>

      {msg && (
        <div className="rounded-sm border border-teal/40 bg-teal/5 px-3 py-2 text-xs text-teal flex items-center gap-2">
          <CheckCircle className="h-3.5 w-3.5" /> {msg}
        </div>
      )}
      {err && (
        <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
          <AlertCircle className="h-3.5 w-3.5" /> {err}
        </div>
      )}

      {/* KPIs y curva */}
      <Card>
        <CardContent className="p-5 grid grid-cols-2 md:grid-cols-5 gap-4">
          <Kpi label="Largo trazo"     value={`${oc.largo_trazo} m`} />
          <Kpi label="Capas"           value={oc.num_capas.toString()} />
          <Kpi label="Prendas est."    value={oc.prendas_estimadas.toString()} />
          <Kpi label="Metros teóricos" value={`${oc.metros_consumidos} m`} />
          <Kpi label="Metros asignados" value={`${totalMetrosAsignados.toFixed(2)} m`} />
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-5">
          <p className="section-label mb-2">Curva</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(oc.curva_trazo || {}).map(([t, n]) => (
              <div key={t} className="rounded-sm border border-border bg-cloud/40 px-3 py-1.5 text-xs">
                <span className="text-graphite">Talla {t}: </span>
                <span className="font-semibold text-ink-900 tabular">{n}</span>
              </div>
            ))}
            {Object.keys(oc.curva_trazo || {}).length === 0 && (
              <p className="text-xs text-graphite">Sin curva definida.</p>
            )}
          </div>
          {oc.indicaciones && (
            <div className="mt-4">
              <p className="section-label mb-1">Indicaciones</p>
              <p className="text-xs text-graphite whitespace-pre-wrap">{oc.indicaciones}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Rollos disponibles en inventario, agrupados: coinciden con la tela del precosteo primero */}
      {!cerrada && (
        <Card>
          <CardContent className="p-0">
            <div className="px-4 py-3 border-b border-border flex items-center justify-between">
              <p className="section-label">Rollos disponibles{telaRef ? ` · ${telaRef}` : ""}</p>
              <p className="text-[0.65rem] text-graphite">
                {rollosMatch.length} coinciden · {rollosOtros.length} otros
              </p>
            </div>
            {rollosInvQ.isLoading ? (
              <div className="p-6 text-xs text-graphite">Buscando rollos…</div>
            ) : todosRollos.length === 0 ? (
              <div className="p-6 text-xs text-terracotta">
                No hay rollos disponibles en el inventario. Registra un ingreso.
              </div>
            ) : (
              <RollosTabla
                match={rollosMatch}
                otros={rollosOtros}
                telaRef={telaRef}
                oc={oc}
                onUsar={(rollo) => {
                  setBarcode(rollo.barcode);
                  setMetros("");
                  setErr("");
                  setTimeout(() => metrosRef.current?.focus(), 30);
                }}
              />
            )}
          </CardContent>
        </Card>
      )}

      {/* Pistola de rollos */}
      {!cerrada && (
        <Card>
          <CardContent className="p-5 space-y-3">
            <div className="flex items-center gap-2">
              <ScanLine className="h-5 w-5 text-navy-600" />
              <p className="section-label">Pistolear rollo</p>
            </div>
            <p className="text-xs text-graphite">
              Escanea el código de barras del rollo con la pistola, o toca "Usar" en la tabla de arriba. Después escribe cuántos metros vas a usar.
            </p>
            <form
              onSubmit={(e) => { e.preventDefault(); setErr(""); pistolar.mutate(); }}
              className="grid grid-cols-1 md:grid-cols-[1fr_150px_auto] gap-2 items-end"
            >
              <div>
                <label className="mb-1 block text-[0.6rem] uppercase tracking-widest text-graphite">Barcode del rollo</label>
                <input ref={barcodeRef} value={barcode} onChange={(e) => setBarcode(e.target.value)}
                  autoFocus placeholder="Escanea aquí…"
                  className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm tabular" />
              </div>
              <div>
                <label className="mb-1 block text-[0.6rem] uppercase tracking-widest text-graphite">Metros a usar</label>
                <input ref={metrosRef} value={metros} onChange={(e) => setMetros(e.target.value)}
                  inputMode="decimal" placeholder="0"
                  className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm text-right tabular" />
              </div>
              <button type="submit" disabled={pistolar.isPending || !barcode.trim() || !metros}
                className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700 disabled:opacity-40">
                {pistolar.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanLine className="h-4 w-4" />}
                Agregar
              </button>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Rollos asignados */}
      <Card>
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border">
            <p className="section-label">Rollos asignados ({(oc.rollos || []).length})</p>
          </div>
          {(oc.rollos || []).length === 0 ? (
            <div className="p-8 text-center text-xs text-graphite">
              Aún no hay rollos pistoleados.
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Código</th>
                  <th className="px-4 py-2">Descripción</th>
                  <th className="px-4 py-2">Tono</th>
                  <th className="px-4 py-2 text-right">Disponible</th>
                  <th className="px-4 py-2 text-right">Usará</th>
                  <th className="px-4 py-2 text-right"></th>
                </tr>
              </thead>
              <tbody>
                {(oc.rollos || []).map((l) => (
                  <tr key={l.id} className="border-b border-border/40 hover:bg-cloud/40">
                    <td className="px-4 py-2 font-semibold tabular text-navy-600">
                      {l.rollo?.codigo_interno || "—"}
                    </td>
                    <td className="px-4 py-2 text-ink-900">{l.rollo?.descripcion_tela || "—"}</td>
                    <td className="px-4 py-2 text-graphite">{l.rollo?.tono || "—"}</td>
                    <td className="px-4 py-2 text-right tabular text-graphite">
                      {l.rollo?.metros_disponible ?? "—"} m
                    </td>
                    <td className="px-4 py-2 text-right tabular font-semibold text-ink-900">
                      {Number(l.metros_usados).toFixed(2)} m
                    </td>
                    <td className="px-4 py-2 text-right">
                      {!cerrada && (
                        <button onClick={() => quitar.mutate(l.rollo_id)}
                          className="text-terracotta hover:text-crimson">
                          <Trash2 className="h-3 w-3" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* Cierre */}
      {!cerrada && (oc.rollos || []).length > 0 && (
        <Card>
          <CardContent className="p-5 space-y-3">
            <p className="section-label">Cierre de orden</p>
            <p className="text-xs text-graphite">
              El cortador reporta el consumo real total. Al cerrar se descuentan los metros de cada rollo
              y se calcula la diferencia contra el teórico ({oc.metros_consumidos} m).
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">Consumo real (m) *</label>
                <input value={consumoReal} onChange={(e) => setConsumoReal(e.target.value)}
                  inputMode="decimal" placeholder={`${oc.metros_consumidos}`}
                  className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm text-right tabular" />
              </div>
              <div>
                <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">Merma tipo (opcional)</label>
                <input value={mermaTipo} onChange={(e) => setMermaTipo(e.target.value)}
                  placeholder="Ej. defecto, borde, otro"
                  className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">Merma valor (opcional)</label>
                <input value={mermaValor} onChange={(e) => setMermaValor(e.target.value)}
                  inputMode="decimal" placeholder="0"
                  className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm text-right tabular" />
              </div>
            </div>
            <div className="flex justify-end">
              <button onClick={() => cerrar.mutate()} disabled={cerrar.isPending || !consumoReal}
                className="inline-flex items-center gap-2 rounded-sm bg-teal px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
                {cerrar.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
                Cerrar y descontar inventario
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Comparación al cerrar */}
      {cerrada && (
        <Card>
          <CardContent className="p-5 space-y-3">
            <p className="section-label">Comparación teórico vs real</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Kpi label="Teórico"        value={`${oc.metros_consumidos} m`} />
              <Kpi label="Real cortador"  value={`${oc.consumo_real_cortador} m`} />
              <Kpi label="Diferencia"     value={oc.diferencia_pct != null ? `${oc.diferencia_pct}%` : "—"} />
              <Kpi label="Rendimiento (m/prenda)" value={oc.rendimiento_teorico ? oc.rendimiento_teorico.toFixed(3) : "—"} />
            </div>
          </CardContent>
        </Card>
      )}
    </PageShell>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.6rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className="mt-1 font-display text-lg text-ink-900 tabular">{value}</p>
    </div>
  );
}

function RollosTabla({ match, otros, telaRef, oc, onUsar }: {
  match: RolloInv[];
  otros: RolloInv[];
  telaRef: string;
  oc: OrdenCorte;
  onUsar: (r: RolloInv) => void;
}) {
  const [mostrarOtros, setMostrarOtros] = useState(false);
  const yaAsignado = (rolloId: string) => (oc.rollos || []).some((l) => l.rollo_id === rolloId);

  const renderFila = (r: RolloInv, esOtro = false) => (
    <tr key={r.id} className={`border-b border-border/40 ${yaAsignado(r.id) ? "bg-teal/5" : "hover:bg-cloud/30"} ${esOtro ? "text-graphite/90" : ""}`}>
      <td className="px-4 py-2 font-semibold tabular text-navy-600">{r.codigo_interno}</td>
      <td className="px-4 py-2 text-ink-900">{r.descripcion_tela}</td>
      <td className="px-4 py-2 text-graphite">{r.tono || "—"}</td>
      <td className="px-4 py-2 text-graphite">{r.lote_fabrica || "—"}</td>
      <td className="px-4 py-2 text-right tabular text-ink-900">{Number(r.metros_disponible).toFixed(2)} m</td>
      <td className="px-4 py-2 text-[0.65rem] text-graphite tabular">{r.barcode}</td>
      <td className="px-4 py-2 text-right">
        {yaAsignado(r.id) ? (
          <span className="inline-flex items-center gap-1 text-[0.65rem] text-teal">
            <CheckCircle className="h-3 w-3" /> Asignado
          </span>
        ) : (
          <button type="button" onClick={() => onUsar(r)}
            className="rounded-sm border border-navy-600 bg-white px-2 py-1 text-[0.65rem] font-semibold uppercase tracking-widest text-navy-600 hover:bg-navy-600 hover:text-white">
            Usar
          </button>
        )}
      </td>
    </tr>
  );

  return (
    <>
      <table className="w-full text-xs">
        <thead className="bg-cloud/40 border-b border-border">
          <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
            <th className="px-4 py-2">Código interno</th>
            <th className="px-4 py-2">Descripción</th>
            <th className="px-4 py-2">Tono</th>
            <th className="px-4 py-2">Lote</th>
            <th className="px-4 py-2 text-right">Disponible</th>
            <th className="px-4 py-2 tabular">Barcode</th>
            <th className="px-4 py-2 text-right"></th>
          </tr>
        </thead>
        <tbody>
          {match.length === 0 && (
            <tr>
              <td colSpan={7} className="px-4 py-3 text-[0.7rem] text-terracotta">
                Ningún rollo coincide con “{telaRef || "—"}”. Revisa que el nombre
                de la tela en el precosteo coincida con la descripción del ingreso,
                o usa uno de los otros rollos.
              </td>
            </tr>
          )}
          {match.map((r) => renderFila(r, false))}

          {otros.length > 0 && (
            <>
              <tr className="bg-cloud/30 border-y border-border">
                <td colSpan={7} className="px-4 py-2">
                  <button type="button" onClick={() => setMostrarOtros((v) => !v)}
                    className="text-[0.6rem] font-semibold uppercase tracking-widest text-graphite hover:text-ink-900">
                    {mostrarOtros ? "▼ Ocultar" : "▶ Mostrar"} otros rollos disponibles ({otros.length})
                  </button>
                </td>
              </tr>
              {mostrarOtros && otros.map((r) => renderFila(r, true))}
            </>
          )}
        </tbody>
      </table>
    </>
  );
}
