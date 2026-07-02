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
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft, ScanLine, Trash2, Lock, Loader2, AlertCircle, CheckCircle,
  Paperclip, Send,
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
  cantidad_programada?: number;
  promedio_tecnico?: number;
  metros_consumidos: number;   // teórico
  rendimiento_teorico?: number;
  consumo_real_cortador?: number;
  diferencia_pct?: number;
  merma_tipo?: string;
  merma_valor?: number;
  referencia_lote?: string;
  capas_real?: number;
  promedio_real?: number;
  unidades_cortadas?: Record<string, number>;
  retazos_cantidad?: number;
  fecha_entrega?: string;
  precio_corte?: number;
  responsable?: string;
  fecha_limite?: string;
  fecha_envio?: string;
  indicaciones?: string;
  trazos_url?: string;
  destinatarios_correo?: string[];
  autorizada_por?: string;
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
  // Informe del cortador
  const [refLote, setRefLote] = useState("");
  const [capasReal, setCapasReal] = useState("");
  const [promedioReal, setPromedioReal] = useState("");
  const [retazos, setRetazos] = useState("");
  const [fechaEntrega, setFechaEntrega] = useState("");
  const [precioCorte, setPrecioCorte] = useState("");
  const [unidadesReal, setUnidadesReal] = useState<Record<string, string>>({});

  const q = useQuery<OrdenCorte>({
    queryKey: ["produccion", "corte", id],
    queryFn: () => api.get(`/api/produccion/corte/${id}`),
    enabled: !!id,
  });

  // Trae rollos filtrados por tela (mucho más rápido que traer los 500 disponibles).
  // La búsqueda ilike del backend hace un match parcial (%tela%) que cubre la mayoría
  // de casos. El fallback "Otros rollos" se dispara solo si el usuario lo pide.
  const telaRef = (q.data?.referencia?.tela || "").trim();
  const rollosInvQ = useQuery<{ rollos: RolloInv[] }>({
    queryKey: ["produccion", "rollos", "disponibles-tela", telaRef],
    queryFn: () => {
      const p = new URLSearchParams({ estado: "disponible", limit: "200" });
      if (telaRef) p.set("tela", telaRef);
      return api.get(`/api/produccion/rollos?${p}`);
    },
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

  // Insumos requeridos: item.cantidad × cantidad_a_cortar por cada insumo del precosteo
  interface InsumoReq {
    categoria: string;
    item: string;
    cantidad_por_prenda: number;
    total_requerido: number;
    valor_unitario: number;
    costo_total: number;
  }
  interface InsumosResp {
    orden_corte?: string;
    referencia?: string;
    nombre?: string;
    cantidad_base?: number;
    origen_cantidad?: string;
    items: InsumoReq[];
    total_costo?: number;
  }
  const insumosQ = useQuery<InsumosResp>({
    queryKey: ["produccion", "corte", id, "insumos-requeridos"],
    queryFn: () => api.get(`/api/produccion/corte/${id}/insumos-requeridos`),
    enabled: !!id,
  });

  // Auto-asignar rollos por tono (evita mezclar colores en el trazo).
  const [tonoAuto, setTonoAuto] = useState("");
  const autoAsignar = useMutation({
    mutationFn: () => api.post<{
      ok: boolean;
      resultado: { asignados: Array<{codigo_interno: string; tono?: string; metros_usados: number}>; faltantes: number; tono_usado?: string; tela: string };
    }>(`/api/produccion/corte/${id}/auto-asignar`, { tono: tonoAuto || null }),
    onSuccess: (data) => {
      const r = data.resultado;
      const n = r.asignados.length;
      if (r.faltantes > 0) {
        setMsg(`Asignados ${n} rollo(s) · faltan ${r.faltantes.toFixed(2)} m (stock insuficiente del tono).`);
      } else {
        setMsg(`Asignados ${n} rollo(s) automáticamente · cubre los metros teóricos.`);
      }
      setErr("");
      qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  const cerrar = useMutation({
    mutationFn: () => {
      const unidadesFinal: Record<string, number> = {};
      for (const [t, v] of Object.entries(unidadesReal)) {
        const n = parseInt(v || "0", 10);
        if (n > 0) unidadesFinal[t] = n;
      }
      return api.post(`/api/produccion/corte/${id}/cerrar`, {
        consumo_real_cortador: parseFloat(consumoReal || "0"),
        merma_tipo: mermaTipo || null,
        merma_valor: mermaValor ? parseFloat(mermaValor) : null,
        referencia_lote: refLote || null,
        capas_real: capasReal ? parseInt(capasReal, 10) : null,
        promedio_real: promedioReal ? parseFloat(promedioReal) : null,
        unidades_cortadas: unidadesFinal,
        retazos_cantidad: retazos ? parseInt(retazos, 10) : null,
        fecha_entrega: fechaEntrega || null,
        precio_corte: precioCorte ? parseFloat(precioCorte) : null,
      });
    },
    onSuccess: () => {
      setMsg("Informe guardado. Inventario descontado y orden cerrada.");
      setErr("");
      qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  // ── Trazos ─────────────────────────────────────
  const trazosRef = useRef<HTMLInputElement>(null);
  const [subiendoTrazos, setSubiendoTrazos] = useState(false);

  async function subirTrazos(f: File) {
    setErr(""); setMsg("");
    setSubiendoTrazos(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await fetch(`${API_BASE}/api/produccion/corte/${id}/trazos`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      });
      const text = await res.text();
      if (!res.ok) throw new Error(text.slice(0, 200) || `HTTP ${res.status}`);
      setMsg("Trazos subidos.");
      qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error subiendo trazos");
    } finally {
      setSubiendoTrazos(false);
      if (trazosRef.current) trazosRef.current.value = "";
    }
  }

  // ── Autorizar + correo ─────────────────────────
  const [destinatariosEdit, setDestinatariosEdit] = useState("");
  const [mensajeExtra, setMensajeExtra] = useState("");

  const autorizar = useMutation({
    mutationFn: () => {
      const dest = destinatariosEdit
        .split(/[,;\s]+/g).map((s) => s.trim()).filter(Boolean);
      return api.post<{
        ok: boolean;
        correo?: { asunto: string; body: string; destinatarios: string[]; enviado_por: string; mailto_url?: string };
      }>(`/api/produccion/corte/${id}/autorizar`, {
        destinatarios: dest.length > 0 ? dest : null,
        mensaje_extra: mensajeExtra || null,
      });
    },
    onSuccess: (data) => {
      setErr("");
      const c = data.correo;
      if (c?.enviado_por === "resend") {
        setMsg(`Orden autorizada. Correo enviado a ${c.destinatarios.join(", ")}.`);
      } else if (c?.mailto_url) {
        setMsg("Orden autorizada. Abriendo tu cliente de correo…");
        window.location.href = c.mailto_url;
      } else {
        setMsg("Orden autorizada.");
      }
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

      {/* Trazos + destinatarios + autorizar */}
      {!cerrada && (
        <Card>
          <CardContent className="p-5 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Trazos */}
              <div>
                <p className="section-label mb-2">Trazos</p>
                <input ref={trazosRef} type="file" accept="application/pdf,image/*" className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) subirTrazos(f); }} />
                <div className="flex items-center gap-2">
                  <button type="button" onClick={() => trazosRef.current?.click()}
                    disabled={subiendoTrazos}
                    className="inline-flex items-center gap-2 rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud disabled:opacity-40">
                    {subiendoTrazos ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Paperclip className="h-3.5 w-3.5" />}
                    {oc.trazos_url ? "Cambiar" : "Subir archivo"}
                  </button>
                  {oc.trazos_url && (
                    <a href={oc.trazos_url} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-teal hover:underline">
                      <CheckCircle className="h-3.5 w-3.5" /> Ver trazos
                    </a>
                  )}
                </div>
                <p className="mt-1 text-[0.62rem] text-graphite">PDF/JPG/PNG · máx 15MB</p>
              </div>

              {/* Autorizar */}
              <div>
                <p className="section-label mb-2">Autorizar orden</p>
                {oc.estado === "autorizada" ? (
                  <div className="rounded-sm border border-teal/40 bg-teal/5 px-3 py-2 text-xs text-teal flex items-center gap-2">
                    <CheckCircle className="h-3.5 w-3.5" /> Autorizada por {oc.autorizada_por || "—"}
                  </div>
                ) : (
                  <>
                    <input value={destinatariosEdit}
                      onChange={(e) => setDestinatariosEdit(e.target.value)}
                      placeholder={(oc.destinatarios_correo || []).join(", ") || "correos@destinatarios.com"}
                      className="w-full rounded-sm border border-border bg-white px-3 py-2 text-xs" />
                    <textarea value={mensajeExtra}
                      onChange={(e) => setMensajeExtra(e.target.value)}
                      rows={2} placeholder="Mensaje adicional (opcional)"
                      className="mt-2 w-full rounded-sm border border-border bg-white px-3 py-2 text-xs" />
                    <button type="button" onClick={() => autorizar.mutate()}
                      disabled={autorizar.isPending}
                      className="mt-2 w-full inline-flex items-center justify-center gap-2 rounded-sm bg-teal px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
                      {autorizar.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                      Autorizar y enviar correo
                    </button>
                    <p className="mt-1 text-[0.62rem] text-graphite">
                      Asunto: <span className="font-semibold text-ink-900">
                        Orden de corte referencia {oc.referencia?.codigo_referencia || "—"}
                      </span>
                    </p>
                  </>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Insumos requeridos — cálculo automático desde el precosteo */}
      <Card>
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <p className="section-label">Insumos requeridos (auto desde precosteo)</p>
            {insumosQ.data?.cantidad_base != null && (
              <p className="text-[0.65rem] text-graphite">
                Base: {insumosQ.data.cantidad_base} unidades{" "}
                <span className="text-graphite/60">
                  ({insumosQ.data.origen_cantidad === "unidades_cortadas" ? "cortadas" :
                    insumosQ.data.origen_cantidad === "cantidad_programada" ? "programadas" :
                    "suma curva"})
                </span>
              </p>
            )}
          </div>
          {insumosQ.isLoading ? (
            <div className="p-6 text-xs text-graphite">Calculando insumos…</div>
          ) : !insumosQ.data || insumosQ.data.items.length === 0 ? (
            <div className="p-6 text-xs text-graphite">
              El precosteo no tiene insumos con cantidad definida. Edita el precosteo y agrega cantidades por prenda para que el sistema calcule automáticamente.
            </div>
          ) : (
            <>
              <table className="w-full text-xs">
                <thead className="bg-cloud/60 border-b border-border">
                  <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                    <th className="px-4 py-2">Categoría</th>
                    <th className="px-4 py-2">Insumo</th>
                    <th className="px-4 py-2 text-right">×/prenda</th>
                    <th className="px-4 py-2 text-right">× {insumosQ.data.cantidad_base}</th>
                    <th className="px-4 py-2 text-right">Total requerido</th>
                    <th className="px-4 py-2 text-right">Costo total</th>
                  </tr>
                </thead>
                <tbody>
                  {insumosQ.data.items.map((it, i) => (
                    <tr key={i} className="border-b border-border/40 hover:bg-cloud/30">
                      <td className="px-4 py-2 text-graphite text-[0.6rem] uppercase tracking-widest">{it.categoria}</td>
                      <td className="px-4 py-2 text-ink-900 font-medium">{it.item}</td>
                      <td className="px-4 py-2 text-right tabular text-graphite">{it.cantidad_por_prenda}</td>
                      <td className="px-4 py-2 text-right tabular text-graphite">{insumosQ.data?.cantidad_base}</td>
                      <td className="px-4 py-2 text-right tabular font-semibold text-navy-600">
                        {it.total_requerido.toLocaleString("es-CO")}
                      </td>
                      <td className="px-4 py-2 text-right tabular">
                        {it.costo_total > 0
                          ? `$${it.costo_total.toLocaleString("es-CO", { maximumFractionDigits: 0 })}`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
                {(insumosQ.data.total_costo || 0) > 0 && (
                  <tfoot>
                    <tr className="bg-cloud/40 border-t-2 border-border">
                      <td colSpan={5} className="px-4 py-2 text-right text-[0.6rem] uppercase tracking-widest text-graphite">Costo total insumos</td>
                      <td className="px-4 py-2 text-right tabular font-bold text-ink-900">
                        ${(insumosQ.data.total_costo || 0).toLocaleString("es-CO", { maximumFractionDigits: 0 })}
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
              <div className="px-4 py-3 border-t border-border text-[0.65rem] text-graphite">
                Lista para la remisión al confeccionista. El conteo físico solo debe verificar estos totales.
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Auto-asignar por tono — mismo color en todo el trazo */}
      {!cerrada && telaRef && (
        <Card>
          <CardContent className="p-5">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
              <div>
                <p className="section-label">Auto-asignar por tono</p>
                <p className="mt-1 text-[0.7rem] text-graphite">
                  El sistema escogerá rollos de la misma tela + mismo tono hasta cubrir los metros teóricos.
                  Evita mezclar tonos en el trazo.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <select value={tonoAuto} onChange={(e) => setTonoAuto(e.target.value)}
                  className="rounded-sm border border-border bg-card px-3 py-2 text-xs">
                  <option value="">Cualquier tono disponible</option>
                  {Array.from(new Set(rollosMatch.map((r) => r.tono).filter(Boolean) as string[]))
                    .map((t) => {
                      const stockTono = rollosMatch
                        .filter((r) => r.tono === t)
                        .reduce((s, r) => s + Number(r.metros_disponible || 0), 0);
                      return (
                        <option key={t} value={t}>{t} ({stockTono.toFixed(0)} m)</option>
                      );
                    })}
                </select>
                <button type="button" onClick={() => autoAsignar.mutate()}
                  disabled={autoAsignar.isPending}
                  className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700 disabled:opacity-40">
                  {autoAsignar.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />}
                  Auto-asignar
                </button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

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

      {/* INFORME DE CORTE */}
      {!cerrada && (oc.rollos || []).length > 0 && (
        <InformeCorteCard
          oc={oc}
          refLote={refLote} setRefLote={setRefLote}
          capasReal={capasReal} setCapasReal={setCapasReal}
          promedioReal={promedioReal} setPromedioReal={setPromedioReal}
          retazos={retazos} setRetazos={setRetazos}
          fechaEntrega={fechaEntrega} setFechaEntrega={setFechaEntrega}
          precioCorte={precioCorte} setPrecioCorte={setPrecioCorte}
          unidadesReal={unidadesReal} setUnidadesReal={setUnidadesReal}
          consumoReal={consumoReal} setConsumoReal={setConsumoReal}
          mermaTipo={mermaTipo} setMermaTipo={setMermaTipo}
          mermaValor={mermaValor} setMermaValor={setMermaValor}
          onCerrar={() => cerrar.mutate()}
          isPending={cerrar.isPending}
        />
      )}

      {/* Comparación al cerrar */}
      {cerrada && <InformeCerradoCard oc={oc} />}
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

interface OrdenCorteForInforme {
  consecutivo: string;
  curva_trazo: Record<string, number>;
  num_capas: number;
  cantidad_programada?: number;
  promedio_tecnico?: number;
  metros_consumidos: number;
  referencia?: { codigo_referencia: string };
}

function InformeCorteCard({
  oc, refLote, setRefLote, capasReal, setCapasReal, promedioReal, setPromedioReal,
  retazos, setRetazos, fechaEntrega, setFechaEntrega, precioCorte, setPrecioCorte,
  unidadesReal, setUnidadesReal, consumoReal, setConsumoReal,
  mermaTipo, setMermaTipo, mermaValor, setMermaValor,
  onCerrar, isPending,
}: {
  oc: OrdenCorteForInforme;
  refLote: string; setRefLote: (v: string) => void;
  capasReal: string; setCapasReal: (v: string) => void;
  promedioReal: string; setPromedioReal: (v: string) => void;
  retazos: string; setRetazos: (v: string) => void;
  fechaEntrega: string; setFechaEntrega: (v: string) => void;
  precioCorte: string; setPrecioCorte: (v: string) => void;
  unidadesReal: Record<string, string>; setUnidadesReal: (v: Record<string, string>) => void;
  consumoReal: string; setConsumoReal: (v: string) => void;
  mermaTipo: string; setMermaTipo: (v: string) => void;
  mermaValor: string; setMermaValor: (v: string) => void;
  onCerrar: () => void;
  isPending: boolean;
}) {
  // Tallas de la curva original (para mostrar los inputs de unidades cortadas)
  const tallas = Object.keys(oc.curva_trazo || {});

  const totalUnidades = Object.values(unidadesReal)
    .reduce((s, v) => s + (parseInt(v || "0", 10) || 0), 0);
  const promedioRealN = parseFloat(promedioReal || "0") || 0;
  const consumoAuto = promedioRealN * totalUnidades;

  // Auto-llena el campo consumo real (metros reales) cuando cambian promedio o unidades
  const consumoAutoStr = consumoAuto > 0 ? consumoAuto.toFixed(2) : "";
  const consumoBind = consumoReal || consumoAutoStr;

  // Deltas contra el teórico
  const promTeo = Number(oc.promedio_tecnico || 0);
  const metrosTeo = Number(oc.metros_consumidos || 0);
  const capasTeo = Number(oc.num_capas || 0);

  const promDelta = promedioRealN > 0 && promTeo > 0 ? promedioRealN - promTeo : null;
  const metrosRealN = parseFloat(consumoBind || "0") || 0;
  const metrosDelta = metrosRealN > 0 && metrosTeo > 0 ? metrosRealN - metrosTeo : null;
  const capasRealN = parseInt(capasReal || "0", 10) || 0;
  const capasDelta = capasRealN > 0 && capasTeo > 0 ? capasRealN - capasTeo : null;

  function setUnidad(t: string, v: string) {
    setUnidadesReal({ ...unidadesReal, [t]: v });
  }

  return (
    <Card>
      <CardContent className="p-5 space-y-4">
        <p className="section-label">Informe del cortador</p>

        {/* Fila 1: referencia interna + lote + fecha entrega + precio */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">
              Ref. interna (auto)
            </label>
            <div className="w-full rounded-sm border border-border bg-cloud/40 px-3 py-2 text-sm text-ink-900 tabular font-semibold">
              {oc.consecutivo}
            </div>
          </div>
          <FieldText label="Referencia de lote"    value={refLote}       onChange={setRefLote} placeholder="Lote-XXX" />
          <FieldText label="Fecha entrega corte"   value={fechaEntrega}  onChange={setFechaEntrega} type="date" />
          <FieldText label="Precio del corte"      value={precioCorte}   onChange={setPrecioCorte} inputMode="decimal" placeholder="0" />
        </div>

        {/* Fila 2: capas real vs teorico, promedio real vs teorico */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <ComparativoBloque
            label="Capas"
            teorico={capasTeo}
            valueReal={capasReal}
            onChangeReal={setCapasReal}
            inputMode="numeric"
            delta={capasDelta}
            fmt={(n) => n.toString()}
          />
          <ComparativoBloque
            label="Promedio (m/prenda)"
            teorico={promTeo}
            valueReal={promedioReal}
            onChangeReal={setPromedioReal}
            inputMode="decimal"
            delta={promDelta}
            fmt={(n) => n.toFixed(3)}
          />
          <ComparativoBloque
            label="Metros"
            teorico={metrosTeo}
            valueReal={consumoBind}
            onChangeReal={setConsumoReal}
            inputMode="decimal"
            delta={metrosDelta}
            fmt={(n) => n.toFixed(2)}
            hint={consumoAuto > 0 && !consumoReal ? `Auto = ${promedioRealN.toFixed(3)} × ${totalUnidades}` : ""}
          />
        </div>

        {/* Fila 3: retazos + merma */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <FieldText label="Cantidad de retazos" value={retazos}    onChange={setRetazos}    inputMode="numeric" placeholder="0" />
          <FieldText label="Merma tipo (opc.)"  value={mermaTipo}   onChange={setMermaTipo}  placeholder="Ej. borde, defecto" />
          <FieldText label="Merma valor (opc.)" value={mermaValor}  onChange={setMermaValor} inputMode="decimal" placeholder="0" />
        </div>

        {/* Unidades cortadas por talla */}
        <div>
          <p className="section-label mb-2">Unidades cortadas por talla</p>
          <div className="grid grid-cols-4 md:grid-cols-8 gap-2">
            {tallas.map((t) => (
              <div key={t}>
                <label className="mb-1 block text-[0.6rem] uppercase tracking-widest text-graphite text-center">
                  Talla {t}
                  <div className="text-[0.55rem] text-graphite/70 normal-case tracking-normal">
                    prog. {oc.curva_trazo?.[t] ?? 0}
                  </div>
                </label>
                <input value={unidadesReal[t] || ""} onChange={(e) => setUnidad(t, e.target.value)}
                  inputMode="numeric" placeholder="0"
                  className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-sm text-center tabular" />
              </div>
            ))}
          </div>
          <p className="mt-1 text-[0.62rem] text-graphite">
            Total cortadas: <span className="font-semibold text-ink-900 tabular">{totalUnidades}</span>
            {oc.cantidad_programada
              ? ` / programadas ${oc.cantidad_programada}` : ""}
          </p>
        </div>

        <div className="flex justify-end">
          <button onClick={onCerrar} disabled={isPending || !consumoBind}
            className="inline-flex items-center gap-2 rounded-sm bg-teal px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
            {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
            Guardar informe y cerrar
          </button>
        </div>
      </CardContent>
    </Card>
  );
}

function FieldText({ label, value, onChange, placeholder, inputMode, type }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; inputMode?: "decimal" | "numeric"; type?: string;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder} inputMode={inputMode} type={type || "text"}
        className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm" />
    </div>
  );
}

function ComparativoBloque({ label, teorico, valueReal, onChangeReal, inputMode, delta, fmt, hint }: {
  label: string;
  teorico: number;
  valueReal: string;
  onChangeReal: (v: string) => void;
  inputMode?: "decimal" | "numeric";
  delta: number | null;
  fmt: (n: number) => string;
  hint?: string;
}) {
  const tono = delta == null ? "text-graphite" : (delta > 0 ? "text-terracotta" : delta < 0 ? "text-teal" : "text-graphite");
  return (
    <div className="rounded-sm border border-border bg-cloud/30 p-3">
      <p className="text-[0.6rem] uppercase tracking-widest text-graphite mb-2">{label}</p>
      <div className="grid grid-cols-3 gap-2 items-end">
        <div>
          <p className="text-[0.55rem] text-graphite">Teórico</p>
          <div className="rounded-sm border border-border bg-cloud/60 px-2 py-1.5 text-sm tabular text-graphite">
            {teorico > 0 ? fmt(teorico) : "—"}
          </div>
        </div>
        <div>
          <p className="text-[0.55rem] text-graphite">Real</p>
          <input value={valueReal} onChange={(e) => onChangeReal(e.target.value)}
            inputMode={inputMode} placeholder="0"
            className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-sm text-right tabular" />
        </div>
        <div>
          <p className="text-[0.55rem] text-graphite">Δ</p>
          <div className={`rounded-sm border border-border bg-white px-2 py-1.5 text-sm text-right tabular font-semibold ${tono}`}>
            {delta == null ? "—" : (delta > 0 ? `+${fmt(delta)}` : fmt(delta))}
          </div>
        </div>
      </div>
      {hint && <p className="mt-1 text-[0.55rem] text-graphite italic">{hint}</p>}
    </div>
  );
}

function InformeCerradoCard({ oc }: { oc: OrdenCorte }) {
  const promTeo = Number(oc.promedio_tecnico || 0);
  const promReal = Number(oc.promedio_real || 0);
  const promDelta = promReal > 0 && promTeo > 0 ? promReal - promTeo : null;

  const metrosTeo = Number(oc.metros_consumidos || 0);
  const metrosReal = Number(oc.consumo_real_cortador || 0);
  const metrosDelta = metrosReal > 0 && metrosTeo > 0 ? metrosReal - metrosTeo : null;

  const capasTeo = Number(oc.num_capas || 0);
  const capasReal = Number(oc.capas_real || 0);
  const capasDelta = capasReal > 0 && capasTeo > 0 ? capasReal - capasTeo : null;

  const curva = oc.curva_trazo || {};
  const unidades = oc.unidades_cortadas || {};
  const tallas = Object.keys(curva);
  const totalProgramado = Object.values(curva).reduce<number>((s, n) => s + (Number(n) || 0), 0);
  const totalCortado = Object.values(unidades).reduce<number>((s, n) => s + (Number(n) || 0), 0);

  return (
    <Card>
      <CardContent className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <p className="section-label">Informe del cortador · cerrado</p>
          <Badge tone="normal"><Lock className="inline h-2.5 w-2.5 mr-1" />Cortada</Badge>
        </div>

        {/* Identificación */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <ReadKV label="Ref. interna"     value={oc.consecutivo} bold />
          <ReadKV label="Referencia lote"  value={oc.referencia_lote || "—"} />
          <ReadKV label="Fecha entrega"    value={oc.fecha_entrega || "—"} />
          <ReadKV label="Precio del corte" value={oc.precio_corte != null ? `$${Number(oc.precio_corte).toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"} />
        </div>

        {/* Comparativos teórico vs real con Δ */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <CompRead label="Capas"              teorico={capasTeo}   real={capasReal}   delta={capasDelta}   fmt={(n) => String(n)} />
          <CompRead label="Promedio (m/prenda)" teorico={promTeo}    real={promReal}    delta={promDelta}    fmt={(n) => n.toFixed(3)} />
          <CompRead label="Metros"             teorico={metrosTeo}  real={metrosReal}  delta={metrosDelta}  fmt={(n) => `${n.toFixed(2)} m`} />
        </div>

        {/* Retazos + merma */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <ReadKV label="Cantidad de retazos" value={oc.retazos_cantidad != null ? String(oc.retazos_cantidad) : "—"} />
          <ReadKV label="Merma tipo"          value={oc.merma_tipo || "—"} />
          <ReadKV label="Merma valor"         value={oc.merma_valor != null ? String(oc.merma_valor) : "—"} />
        </div>

        {/* Unidades cortadas por talla */}
        <div>
          <p className="section-label mb-2">Unidades cortadas por talla</p>
          {tallas.length === 0 ? (
            <p className="text-xs text-graphite">Sin curva registrada.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-cloud/60 border-b border-border">
                  <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                    <th className="px-3 py-2">Talla</th>
                    {tallas.map((t) => (
                      <th key={t} className="px-3 py-2 text-center">{t}</th>
                    ))}
                    <th className="px-3 py-2 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-border/40">
                    <td className="px-3 py-1.5 text-graphite">Programado</td>
                    {tallas.map((t) => (
                      <td key={t} className="px-3 py-1.5 text-center tabular text-graphite">
                        {curva[t] ?? 0}
                      </td>
                    ))}
                    <td className="px-3 py-1.5 text-right tabular font-semibold">{totalProgramado}</td>
                  </tr>
                  <tr className="border-b border-border/40">
                    <td className="px-3 py-1.5 text-ink-900 font-semibold">Cortado real</td>
                    {tallas.map((t) => (
                      <td key={t} className="px-3 py-1.5 text-center tabular font-semibold text-ink-900">
                        {unidades[t] ?? 0}
                      </td>
                    ))}
                    <td className="px-3 py-1.5 text-right tabular font-bold text-navy-600">{totalCortado}</td>
                  </tr>
                  <tr>
                    <td className="px-3 py-1.5 text-graphite">Δ</td>
                    {tallas.map((t) => {
                      const d = (Number(unidades[t] || 0) - Number(curva[t] || 0));
                      const cls = d > 0 ? "text-terracotta" : d < 0 ? "text-terracotta" : "text-graphite";
                      return (
                        <td key={t} className={`px-3 py-1.5 text-center tabular ${cls}`}>
                          {d === 0 ? "0" : (d > 0 ? `+${d}` : `${d}`)}
                        </td>
                      );
                    })}
                    <td className={`px-3 py-1.5 text-right tabular font-semibold ${(totalCortado - totalProgramado) === 0 ? "text-graphite" : "text-terracotta"}`}>
                      {(totalCortado - totalProgramado) > 0
                        ? `+${totalCortado - totalProgramado}`
                        : `${totalCortado - totalProgramado}`}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="border-t border-border pt-3 text-[0.65rem] text-graphite grid grid-cols-1 md:grid-cols-3 gap-2">
          <p>Autorizada por: <span className="text-ink-900 font-semibold">{oc.autorizada_por || "—"}</span></p>
          <p>Cortador: <span className="text-ink-900 font-semibold">{oc.responsable || "—"}</span></p>
          <p>Fecha envío: <span className="text-ink-900 font-semibold">{oc.fecha_envio || oc.fecha_limite || "—"}</span></p>
        </div>
      </CardContent>
    </Card>
  );
}

function ReadKV({ label, value, bold = false }: { label: string; value: string; bold?: boolean }) {
  return (
    <div>
      <p className="text-[0.6rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className={`mt-1 text-sm tabular ${bold ? "font-semibold text-navy-600" : "text-ink-900"}`}>{value}</p>
    </div>
  );
}

function CompRead({ label, teorico, real, delta, fmt }: {
  label: string; teorico: number; real: number; delta: number | null; fmt: (n: number) => string;
}) {
  const tono = delta == null ? "text-graphite" : (delta > 0 ? "text-terracotta" : delta < 0 ? "text-teal" : "text-graphite");
  return (
    <div className="rounded-sm border border-border bg-cloud/30 p-3">
      <p className="text-[0.6rem] uppercase tracking-widest text-graphite mb-2">{label}</p>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <p className="text-[0.55rem] text-graphite">Teórico</p>
          <div className="tabular text-sm text-graphite">{teorico > 0 ? fmt(teorico) : "—"}</div>
        </div>
        <div>
          <p className="text-[0.55rem] text-graphite">Real</p>
          <div className="tabular text-sm text-ink-900 font-semibold">{real > 0 ? fmt(real) : "—"}</div>
        </div>
        <div>
          <p className="text-[0.55rem] text-graphite">Δ</p>
          <div className={`tabular text-sm font-semibold ${tono}`}>
            {delta == null ? "—" : (delta > 0 ? `+${fmt(delta)}` : fmt(delta))}
          </div>
        </div>
      </div>
    </div>
  );
}
