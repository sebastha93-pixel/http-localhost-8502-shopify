"use client";

/**
 * Detalle de orden de corte.
 * - Info cabecera + curva
 * - Pistola de rollos: input que recibe el barcode + metros a usar → agrega al corte
 * - Botón cerrar → registra consumo real, descuenta inventario, marca 'cortada'
 */
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { fmtFecha, hoyBogotaISO } from "@/lib/utils";
import { TimelineNotas } from "@/components/timeline-notas";
import { getToken, puedeAccionModulo } from "@/lib/auth";
import { useAuth } from "@/components/auth-provider";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, ScanLine, Trash2, Lock, Loader2, AlertCircle, CheckCircle, Paperclip, Send, X } from "lucide-react";

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
    numero_rollo?: string;
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
  trazos_filename?: string;
  precio_corte_sugerido?: number | null;
  trazos_archivos?: { url: string; filename?: string; path?: string }[];
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

  // Pre-llena lo derivable para que el cortador no tenga que digitarlo:
  // referencia de lote (= consecutivo del corte) y fecha de entrega planeada.
  useEffect(() => {
    const d = q.data;
    if (!d) return;
    setRefLote((prev) => prev || d.consecutivo || "");
    const fplan = (d.fecha_envio || d.fecha_limite || "").slice(0, 10);
    if (fplan) setFechaEntrega((prev) => prev || fplan);
    if (d.precio_corte_sugerido != null) setPrecioCorte((prev) => prev || String(d.precio_corte_sugerido));
  }, [q.data]);
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

  // Asignación MANUAL directa desde la tabla de rollos (sin pistola): el
  // diseñador elige el rollo y escribe los metros en la misma fila.
  const asignarDirecto = useMutation({
    mutationFn: (v: { barcode: string; metros: number }) =>
      api.post(`/api/produccion/corte/${id}/pistolear`, {
        barcode: v.barcode, metros_reservar: v.metros,
      }),
    onSuccess: (_d, v) => {
      setMsg(`✓ Rollo asignado (${v.metros} m)`);
      setErr("");
      qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  // Rol: cortador puro = tiene produccion_cortador pero NO produccion_corte
  // (mismo criterio que el backend _es_solo_cortador). Solo verifica y descarga.
  const { user } = useAuth();
  const _perms = (user?.permisos || {}) as Record<string, unknown>;
  const esAdmin = user?.rol === "admin" || user?.rol === "operador";
  const esCortador = !esAdmin && !!_perms["produccion_cortador"] && !_perms["produccion_corte"];

  const [verifResult, setVerifResult] = useState<{ asignado: boolean; mensaje: string; rollo?: { codigo_interno?: string; descripcion_tela?: string; tono?: string; barcode?: string; numero_rollo?: string } } | null>(null);
  const [verificados, setVerificados] = useState<Set<string>>(new Set());
  const verificar = useMutation({
    mutationFn: (bc: string) => api.post<{ asignado: boolean; mensaje: string; rollo?: { codigo_interno?: string; descripcion_tela?: string; tono?: string; barcode?: string; numero_rollo?: string } }>(`/api/produccion/corte/${id}/verificar-rollo`, { barcode: bc }),
    onSuccess: (r) => {
      setVerifResult(r);
      if (r.asignado && r.rollo?.barcode) setVerificados((prev) => new Set(prev).add(r.rollo!.barcode!));
      setBarcode(""); setErr(""); setTimeout(() => barcodeRef.current?.focus(), 50);
    },
    onError: (e: Error) => { setErr(e.message); setVerifResult(null); },
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
    // Solo trae los insumos cuando el corte YA está cerrado (unidades reales).
    // Antes del cierre no tiene sentido — la cantidad real solo se conoce al cierre.
    enabled: !!id && q.data?.estado === "cortada",
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
        setMsg(`Asignados ${n} rollo(s) · reserva +5% de colchón. Al cerrar el informe se descuenta el consumo real y el sobrante vuelve al inventario.`);
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
      // CONSUMO Y PROMEDIO REALES: los calcula el cortador manualmente
      //   (contando capas/espigas en piso) y los digita en el informe.
      //   El promedio, si no lo escribe, se deriva de metros ÷ unidades.
      const totalUnid = Object.values(unidadesFinal).reduce((s, n) => s + n, 0);
      const retazosM = parseFloat(retazos || "0") || 0;
      const consumoFinal = parseFloat(consumoReal || "0") || 0;
      const promedioManual = parseFloat(promedioReal || "0") || 0;
      const promedioDerivado = totalUnid > 0 && consumoFinal > 0 ? consumoFinal / totalUnid : 0;
      const promedioFinal = promedioManual || promedioDerivado;
      return api.post(`/api/produccion/corte/${id}/cerrar`, {
        consumo_real_cortador: consumoFinal,
        merma_tipo: mermaTipo || null,
        merma_valor: mermaValor ? parseFloat(mermaValor) : null,
        referencia_lote: refLote || null,
        capas_real: capasReal ? parseInt(capasReal, 10) : null,
        promedio_real: promedioFinal ? Number(promedioFinal.toFixed(4)) : null,
        unidades_cortadas: unidadesFinal,
        retazos_metros: retazosM || null,
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

  const MAX_TRAZOS = 10;
  async function subirTrazos(fileList: FileList) {
    setErr(""); setMsg("");
    const seleccion = Array.from(fileList);
    const yaHay = q.data?.trazos_archivos?.length || 0;
    const cupo = MAX_TRAZOS - yaHay;
    if (cupo <= 0) { setErr(`Máximo ${MAX_TRAZOS} archivos por corte.`); if (trazosRef.current) trazosRef.current.value = ""; return; }
    const aSubir = seleccion.slice(0, cupo);
    setSubiendoTrazos(true);
    try {
      const fd = new FormData();
      aSubir.forEach((f) => fd.append("files", f));
      const res = await fetch(`${API_BASE}/api/produccion/corte/${id}/trazos`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      });
      const text = await res.text();
      if (!res.ok) throw new Error(text.slice(0, 200) || `HTTP ${res.status}`);
      const sobran = seleccion.length - aSubir.length;
      setMsg(`${aSubir.length} archivo(s) subido(s).${sobran > 0 ? ` ${sobran} no cupieron (máx ${MAX_TRAZOS}).` : ""}`);
      qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error subiendo trazos");
    } finally {
      setSubiendoTrazos(false);
      if (trazosRef.current) trazosRef.current.value = "";
    }
  }
  async function eliminarTrazo(url: string) {
    setErr(""); setMsg("");
    try {
      await api.del(`/api/produccion/corte/${id}/trazos?url=${encodeURIComponent(url)}`);
      qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error eliminando trazo");
    }
  }

  // ── Autorizar + correo ─────────────────────────
  const [destinatariosEdit, setDestinatariosEdit] = useState("");
  const [mensajeExtra, setMensajeExtra] = useState("");
  const usuariosCorreoQ = useQuery<{ usuarios: { nombre: string; email: string; es_cortador: boolean }[] }>({
    queryKey: ["produccion", "usuarios-correo"],
    queryFn: () => api.get("/api/produccion/usuarios-correo"),
    enabled: !esCortador,
    staleTime: 5 * 60_000,
  });
  const agregarDestinatario = (email: string) => {
    if (!email) return;
    const actuales = destinatariosEdit.split(",").map((s) => s.trim()).filter(Boolean);
    if (!actuales.includes(email)) setDestinatariosEdit([...actuales, email].join(", "));
  };

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
          {cerrada
            ? <><Lock className="inline h-2.5 w-2.5 mr-1" />Cortada</>
            : ({ borrador: "Borrador", autorizada: "Autorizada", en_proceso: "En proceso" }[oc.estado] || oc.estado)}
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

      {/* Cortador: solo DESCARGA de trazos/Optitex para plotear */}
      {esCortador && (oc.trazos_archivos?.length || oc.trazos_url) && (
        <Card>
          <CardContent className="p-5 space-y-2">
            <p className="section-label">Trazos / molde (Optitex) — para plotear</p>
            <ul className="space-y-1">
              {(oc.trazos_archivos && oc.trazos_archivos.length > 0
                ? oc.trazos_archivos
                : (oc.trazos_url ? [{ url: oc.trazos_url, filename: oc.trazos_filename }] : [])
              ).map((t) => (
                <li key={t.url}>
                  <a href={t.url} target="_blank" rel="noopener noreferrer" download
                    className="inline-flex items-center gap-2 rounded-sm border border-navy-600 bg-white px-3 py-2 text-xs font-semibold text-navy-600 hover:bg-navy-600 hover:text-white">
                    <Paperclip className="h-3.5 w-3.5" /> {t.filename || "archivo"}
                  </a>
                </li>
              ))}
            </ul>
            <p className="text-[0.7rem] text-graphite">Descárgalos y envíalos a plotear. Aquí no se suben ni se modifican.</p>
          </CardContent>
        </Card>
      )}

      {/* Trazos + destinatarios + autorizar */}
      {!cerrada && !esCortador && (
        <Card>
          <CardContent className="p-5 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Trazos */}
              <div>
                {(() => { const n = oc.trazos_archivos?.length || 0; return (
                <>
                <div className="mb-2 flex items-center justify-between">
                  <p className="section-label">Trazos / molde (Optitex)</p>
                  <span className="text-[0.7rem] text-graphite tabular">{n}/10</span>
                </div>
                <input ref={trazosRef} type="file" multiple
                  accept="application/pdf,image/*,.mrk,.mark,.plt,.dxf,.dsn,.pds,.rul,.ord,.plx,.hpgl,.cut,.ai,.eps,.dwg,.zip"
                  className="hidden"
                  onChange={(e) => { const fl = e.target.files; if (fl && fl.length) subirTrazos(fl); }} />
                <button type="button" onClick={() => trazosRef.current?.click()}
                  disabled={subiendoTrazos || n >= 10}
                  className="inline-flex items-center gap-2 rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud disabled:opacity-40">
                  {subiendoTrazos ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Paperclip className="h-3.5 w-3.5" />}
                  {n >= 10 ? "Máx 10 alcanzado" : n > 0 ? "Agregar archivos" : "Subir archivos"}
                </button>
                {n > 0 && (
                  <ul className="mt-2 space-y-1">
                    {oc.trazos_archivos!.map((t) => (
                      <li key={t.url} className="flex items-center justify-between gap-2 rounded-sm border border-border bg-card px-2 py-1.5">
                        <a href={t.url} target="_blank" rel="noopener noreferrer" download
                          className="inline-flex items-center gap-1.5 truncate text-xs text-teal hover:underline">
                          <CheckCircle className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">{t.filename || "archivo"}</span>
                        </a>
                        <button type="button" onClick={() => eliminarTrazo(t.url)}
                          title="Eliminar este archivo"
                          className="shrink-0 text-graphite transition-colors hover:text-terracotta">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-1 text-[0.7rem] text-graphite">Hasta 10 archivos: Optitex (.mrk .plt .dxf …), PDF o imagen · máx 15MB c/u. El cortador los recibe en «Mis despachos».</p>
                </>
                ); })()}
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
                    {usuariosCorreoQ.data && usuariosCorreoQ.data.usuarios.length > 0 && (
                      <select value="" onChange={(e) => { agregarDestinatario(e.target.value); e.target.value = ""; }}
                        className="mb-2 w-full rounded-sm border border-border bg-white px-3 py-2 text-xs">
                        <option value="">+ Agregar destinatario del equipo…</option>
                        {usuariosCorreoQ.data.usuarios.map((u) => (
                          <option key={u.email} value={u.email}>
                            {u.nombre}{u.es_cortador ? " · CORTADOR" : ""} — {u.email}
                          </option>
                        ))}
                      </select>
                    )}
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
                    <p className="mt-1 text-[0.7rem] text-graphite">
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

      {/* Insumos requeridos — cálculo automático desde el precosteo. (oculto al cortador: tiene costos)
          Solo aparece cuando el informe está CERRADO (unidades reales conocidas).
          Sirve para adelantar la remisión de insumos al confeccionista. */}
      {cerrada && (
      <Card>
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <p className="section-label">Insumos requeridos (auto desde precosteo)</p>
            {insumosQ.data?.cantidad_base != null && (
              <p className="text-[0.65rem] text-graphite">
                Base: {insumosQ.data.cantidad_base} unidades cortadas
              </p>
            )}
          </div>
          {insumosQ.isLoading ? (
            <div className="p-6 text-xs text-graphite">Calculando insumos…</div>
          ) : !insumosQ.data || insumosQ.data.items.length === 0 ? (
            <div className="p-6 text-xs text-graphite">
              El precosteo no tiene insumos con cantidad definida. Edita el precosteo y agrega cantidades por prenda (para 1 unidad) para que el sistema calcule automáticamente.
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-cloud/60 border-b border-border">
                  <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
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
                      <td className="px-4 py-2 text-graphite text-[0.7rem] uppercase tracking-widest">{it.categoria}</td>
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
                      <td colSpan={5} className="px-4 py-2 text-right text-[0.7rem] uppercase tracking-widest text-graphite">Costo total insumos</td>
                      <td className="px-4 py-2 text-right tabular font-bold text-ink-900">
                        ${(insumosQ.data.total_costo || 0).toLocaleString("es-CO", { maximumFractionDigits: 0 })}
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
              </div>
              <div className="px-4 py-3 border-t border-border text-[0.65rem] text-graphite">
                Lista para la remisión al confeccionista. El conteo físico solo debe verificar estos totales.
              </div>
            </>
          )}
        </CardContent>
      </Card>
      )}

      {/* Auto-asignar por tono — mismo color en todo el trazo (solo diseñador) */}
      {!cerrada && !esCortador && telaRef && (
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

      {/* Rollos disponibles en inventario (asignación — solo diseñador) */}
      {!cerrada && !esCortador && (
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
                asignando={asignarDirecto.isPending}
                onAsignar={(rollo, metros) => asignarDirecto.mutate({ barcode: rollo.barcode, metros })}
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

      {/* Cortador: verificar tela asignada (NO asigna) */}
      {!cerrada && esCortador && (
        <Card>
          <CardContent className="p-5 space-y-3">
            <div className="flex items-center gap-2">
              <ScanLine className="h-5 w-5 text-navy-600" />
              <p className="section-label">Verificar tela asignada</p>
            </div>
            <p className="text-xs text-graphite">
              Escanea cada rollo antes de cortar para confirmar que es una tela asignada a este corte.
              Sirve el código interno (ROLLO-…) o el N° de rollo original del proveedor.
            </p>
            <form
              onSubmit={(e) => { e.preventDefault(); setErr(""); if (barcode.trim()) verificar.mutate(barcode.trim()); }}
              className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-2 items-end"
            >
              <div>
                <label className="mb-1 block text-[0.7rem] uppercase tracking-widest text-graphite">Código interno o N° de rollo</label>
                <input ref={barcodeRef} value={barcode} onChange={(e) => setBarcode(e.target.value)}
                  autoFocus placeholder="Escanea aquí…"
                  className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm tabular" />
              </div>
              <button type="submit" disabled={verificar.isPending || !barcode.trim()}
                className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700 disabled:opacity-40">
                {verificar.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanLine className="h-4 w-4" />}
                Verificar
              </button>
            </form>
            {verifResult && (
              <div className={`rounded-sm border px-3 py-2.5 text-sm ${verifResult.asignado ? "border-teal/40 bg-teal/[0.06] text-teal" : "border-terracotta/40 bg-terracotta/[0.06] text-terracotta"}`}>
                <div className="flex items-center gap-2 font-semibold">
                  {verifResult.asignado ? <CheckCircle className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                  {verifResult.mensaje}
                </div>
                {verifResult.rollo?.codigo_interno && (
                  <p className="mt-1 text-xs">
                    {verifResult.rollo.codigo_interno}
                    {verifResult.rollo.numero_rollo ? ` · N° ${verifResult.rollo.numero_rollo}` : ""}
                    {" · "}{verifResult.rollo.descripcion_tela}{verifResult.rollo.tono ? ` · ${verifResult.rollo.tono}` : ""}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Pistola de rollos (asignación — solo diseñador) */}
      {!cerrada && !esCortador && (
        <Card>
          <CardContent className="p-5 space-y-3">
            <div className="flex items-center gap-2">
              <ScanLine className="h-5 w-5 text-navy-600" />
              <p className="section-label">Pistolear rollo</p>
            </div>
            <p className="text-xs text-graphite">
              Escanea el rollo con la pistola (código interno ROLLO-… o el N° original del proveedor), o toca "Usar" en la tabla de arriba. Después escribe cuántos metros vas a usar.
            </p>
            <form
              onSubmit={(e) => { e.preventDefault(); setErr(""); pistolar.mutate(); }}
              className="grid grid-cols-1 md:grid-cols-[1fr_150px_auto] gap-2 items-end"
            >
              <div>
                <label className="mb-1 block text-[0.7rem] uppercase tracking-widest text-graphite">Barcode del rollo</label>
                <input ref={barcodeRef} value={barcode} onChange={(e) => setBarcode(e.target.value)}
                  autoFocus placeholder="Escanea aquí…"
                  className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm tabular" />
              </div>
              <div>
                <label className="mb-1 block text-[0.7rem] uppercase tracking-widest text-graphite">Metros a usar</label>
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
            <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Código</th>
                  <th className="px-4 py-2">N° rollo</th>
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
                    <td className="px-4 py-2 text-graphite tabular">{l.rollo?.numero_rollo || "—"}</td>
                    <td className="px-4 py-2 text-ink-900">{l.rollo?.descripcion_tela || "—"}</td>
                    <td className="px-4 py-2 text-graphite">{l.rollo?.tono || "—"}</td>
                    <td className="px-4 py-2 text-right tabular text-graphite">
                      {l.rollo?.metros_disponible ?? "—"} m
                    </td>
                    <td className="px-4 py-2 text-right tabular font-semibold text-ink-900">
                      {Number(l.metros_usados).toFixed(2)} m
                    </td>
                    <td className="px-4 py-2 text-right">
                      {!cerrada && !esCortador && (
                        <button onClick={() => quitar.mutate(l.rollo_id)}
                          disabled={quitar.isPending}
                          aria-label="Quitar rollo del corte"
                          className="p-2 -m-1 text-terracotta hover:text-crimson disabled:opacity-40">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                      {!cerrada && esCortador && (
                        verificados.has(l.rollo?.barcode || "") ? (
                          <span className="inline-flex items-center gap-1 text-[0.7rem] font-semibold text-teal">
                            <CheckCircle className="h-3.5 w-3.5" /> Verificado
                          </span>
                        ) : (
                          <span className="text-[0.7rem] text-graphite/60">Sin verificar</span>
                        )
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

      {/* INFORME DE CORTE — solo el CORTADOR lo llena */}
      {!cerrada && !esCortador && (oc.rollos || []).length > 0 && (
        <Card><CardContent className="p-5 text-sm text-graphite">
          El informe de corte lo diligencia el cortador. Cuando lo cierre, aquí verás el informe con las diferencias (teórico vs real).
        </CardContent></Card>
      )}
      {!cerrada && esCortador && (oc.rollos || []).length > 0 && (
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
      {/* Tras confirmar el informe, el cortador (o el encargado de remisiones)
          genera la remisión de confección, la imprime y la marca recogida. */}
      {cerrada && <GenerarRemisionCard ordenCorteId={oc.id} esCortador={esCortador} />}
      {cerrada && !esCortador && <HojaRutaCard ordenCorteId={oc.id} consecutivo={oc.consecutivo} />}
    </PageShell>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.7rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className="mt-1 font-display text-lg text-ink-900 tabular">{value}</p>
    </div>
  );
}

function RollosTabla({ match, otros, telaRef, oc, onUsar, onAsignar, asignando }: {
  match: RolloInv[];
  otros: RolloInv[];
  telaRef: string;
  oc: OrdenCorte;
  onUsar: (r: RolloInv) => void;
  onAsignar: (r: RolloInv, metros: number) => void;
  asignando: boolean;
}) {
  const [mostrarOtros, setMostrarOtros] = useState(false);
  const [metrosFila, setMetrosFila] = useState<Record<string, string>>({});
  const yaAsignado = (rolloId: string) => (oc.rollos || []).some((l) => l.rollo_id === rolloId);
  const asignarFila = (r: RolloInv) => {
    // Por defecto se asigna el ROLLO COMPLETO; el campo viene pre-llenado con
    // el disponible y es editable por si quieren asignar una parte.
    const raw = metrosFila[r.id];
    const m = (raw === undefined || raw === "") ? Number(r.metros_disponible) : parseFloat(raw);
    if (!m || m <= 0) return;
    onAsignar(r, m);
    setMetrosFila((prev) => { const n = { ...prev }; delete n[r.id]; return n; });
  };

  const renderFila = (r: RolloInv, esOtro = false) => (
    <tr key={r.id} className={`border-b border-border/40 ${yaAsignado(r.id) ? "bg-teal/5" : "hover:bg-cloud/30"} ${esOtro ? "text-graphite/90" : ""}`}>
      <td className="px-4 py-2 font-semibold tabular text-navy-600">{r.codigo_interno}</td>
      <td className="px-4 py-2 text-graphite tabular">{r.numero_rollo || "—"}</td>
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
          <div className="inline-flex items-center gap-1.5">
            <input
              type="number" inputMode="decimal" step="0.01" min="0"
              max={Number(r.metros_disponible)}
              value={metrosFila[r.id] !== undefined ? metrosFila[r.id] : String(r.metros_disponible)}
              onChange={(e) => setMetrosFila((prev) => ({ ...prev, [r.id]: e.target.value }))}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); asignarFila(r); } }}
              title="Rollo completo por defecto — puedes editar a una parte"
              placeholder="metros"
              className="w-20 rounded-sm border border-border bg-card px-2 py-1 text-right text-[0.7rem] tabular" />
            <button type="button" onClick={() => asignarFila(r)} disabled={asignando}
              title="Asignar estos metros de este rollo al corte"
              className="rounded-sm border border-navy-600 bg-navy-600 px-2 py-1 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40">
              Asignar
            </button>
          </div>
        )}
      </td>
    </tr>
  );

  return (
    <>
      <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-cloud/40 border-b border-border">
          <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
            <th className="px-4 py-2">Código interno</th>
            <th className="px-4 py-2">N° rollo</th>
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
              <td colSpan={8} className="px-4 py-3 text-[0.7rem] text-terracotta">
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
                <td colSpan={8} className="px-4 py-2">
                  <button type="button" onClick={() => setMostrarOtros((v) => !v)}
                    className="text-[0.7rem] font-semibold uppercase tracking-widest text-graphite hover:text-ink-900">
                    {mostrarOtros ? "▼ Ocultar" : "▶ Mostrar"} otros rollos disponibles ({otros.length})
                  </button>
                </td>
              </tr>
              {mostrarOtros && otros.map((r) => renderFila(r, true))}
            </>
          )}
        </tbody>
      </table>
      </div>
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

  // El cortador calcula el consumo, las capas y el promedio manualmente
  // (contando en piso) y los digita aquí para cruzarlos contra el teórico.
  // El promedio, si no lo escribe, se deriva de metros ÷ unidades.
  const metrosRealN = parseFloat(consumoReal || "0") || 0;
  const promedioDerivado = totalUnidades > 0 && metrosRealN > 0 ? metrosRealN / totalUnidades : 0;
  const promedioRealN = parseFloat(promedioReal || "0") || promedioDerivado;

  // Deltas contra el teórico
  const promTeo = Number(oc.promedio_tecnico || 0);
  const metrosTeo = Number(oc.metros_consumidos || 0);
  const capasTeo = Number(oc.num_capas || 0);

  const promDelta = promedioRealN > 0 && promTeo > 0 ? promedioRealN - promTeo : null;
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
            <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
              Ref. interna (auto)
            </label>
            <div className="w-full rounded-sm border border-border bg-cloud/40 px-3 py-2 text-sm text-ink-900 tabular font-semibold">
              {oc.consecutivo}
            </div>
          </div>
          <FieldText label="Referencia de lote"    value={refLote}       onChange={setRefLote} placeholder="Lote-XXX" />
          <FieldText label="Fecha entrega corte"   value={fechaEntrega}  onChange={setFechaEntrega} type="date" />
          <FieldText label="Precio del corte"      value={precioCorte}   onChange={setPrecioCorte} inputMode="decimal" placeholder="Auto del precosteo" />
        </div>

        {/* Promedios reales: cálculo manual del cortador */}
        <div className="rounded-sm border border-dashed border-border bg-cloud/20 p-3">
          <p className="text-[0.7rem] leading-relaxed text-graphite">
            <span className="font-semibold text-ink-900">Promedio real:</span> el cortador lo saca manualmente
            (metros realmente consumidos ÷ unidades cortadas, contando capas y espigas en piso) y digita
            <span className="font-semibold text-ink-900"> Capas</span>,
            <span className="font-semibold text-ink-900"> Promedio</span> y
            <span className="font-semibold text-ink-900"> Metros</span> abajo para cruzarlos contra el teórico.
            Si deja el promedio vacío, se calcula solo con metros ÷ unidades.
          </p>
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
            valueReal={promedioReal || (promedioDerivado > 0 ? promedioDerivado.toFixed(3) : "")}
            onChangeReal={setPromedioReal}
            inputMode="decimal"
            delta={promDelta}
            fmt={(n) => n.toFixed(3)}
            hint={!promedioReal && promedioDerivado > 0 ? "Derivado de metros ÷ unidades" : ""}
          />
          <ComparativoBloque
            label="Metros"
            teorico={metrosTeo}
            valueReal={consumoReal}
            onChangeReal={setConsumoReal}
            inputMode="decimal"
            delta={metrosDelta}
            fmt={(n) => n.toFixed(2)}
          />
        </div>

        {/* Fila 3: retazos + merma */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <FieldText label="Retazos (metros)" value={retazos}    onChange={setRetazos}    inputMode="decimal" placeholder="0.0" />
          <FieldText label="Merma tipo (opc.)"  value={mermaTipo}   onChange={setMermaTipo}  placeholder="Ej. borde, defecto" />
          <FieldText label="Merma valor (opc.)" value={mermaValor}  onChange={setMermaValor} inputMode="decimal" placeholder="0" />
        </div>

        {/* Unidades cortadas por talla */}
        <div>
          <p className="section-label mb-2">Unidades cortadas por talla</p>
          <div className="grid grid-cols-4 md:grid-cols-8 gap-2">
            {tallas.map((t) => (
              <div key={t}>
                <label className="mb-1 block text-[0.7rem] uppercase tracking-widest text-graphite text-center">
                  Talla {t}
                  <div className="text-[0.68rem] text-graphite/70 normal-case tracking-normal">
                    prog. {oc.curva_trazo?.[t] ?? 0}
                  </div>
                </label>
                <input value={unidadesReal[t] || ""} onChange={(e) => setUnidad(t, e.target.value)}
                  inputMode="numeric" placeholder="0"
                  className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-sm text-center tabular" />
              </div>
            ))}
          </div>
          <p className="mt-1 text-[0.7rem] text-graphite">
            Total cortadas: <span className="font-semibold text-ink-900 tabular">{totalUnidades}</span>
            {oc.cantidad_programada
              ? ` / programadas ${oc.cantidad_programada}` : ""}
          </p>
        </div>

        <div className="flex justify-end">
          <button onClick={onCerrar} disabled={isPending || !consumoReal}
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
      <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">{label}</label>
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
      <p className="text-[0.7rem] uppercase tracking-widest text-graphite mb-2">{label}</p>
      <div className="grid grid-cols-3 gap-2 items-end">
        <div>
          <p className="text-[0.68rem] text-graphite">Teórico</p>
          <div className="rounded-sm border border-border bg-cloud/60 px-2 py-1.5 text-sm tabular text-graphite">
            {teorico > 0 ? fmt(teorico) : "—"}
          </div>
        </div>
        <div>
          <p className="text-[0.68rem] text-graphite">Real</p>
          <input value={valueReal} onChange={(e) => onChangeReal(e.target.value)}
            inputMode={inputMode} placeholder="0"
            className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-sm text-right tabular" />
        </div>
        <div>
          <p className="text-[0.68rem] text-graphite">Δ</p>
          <div className={`rounded-sm border border-border bg-white px-2 py-1.5 text-sm text-right tabular font-semibold ${tono}`}>
            {delta == null ? "—" : (delta > 0 ? `+${fmt(delta)}` : fmt(delta))}
          </div>
        </div>
      </div>
      {hint && <p className="mt-1 text-[0.68rem] text-graphite italic">{hint}</p>}
    </div>
  );
}

function InformeCerradoCard({ oc }: { oc: OrdenCorte }) {
  const promTeo = Number(oc.promedio_tecnico || 0);
  const promReal = Number(oc.promedio_real || 0);
  const metrosTeo = Number(oc.metros_consumidos || 0);
  const metrosReal = Number(oc.consumo_real_cortador || 0);
  const capasTeo = Number(oc.num_capas || 0);
  const capasReal = Number(oc.capas_real || 0);
  const curva = oc.curva_trazo || {};
  const unidades = oc.unidades_cortadas || {};
  const totalProgramado = Object.values(curva).reduce<number>((sum, n) => sum + (Number(n) || 0), 0);
  const totalCortado = Object.values(unidades).reduce<number>((sum, n) => sum + (Number(n) || 0), 0);

  const diffs = [
    { label: "Unidades", teo: totalProgramado, real: totalCortado, fmt: (n: number) => String(Math.round(n)) },
    { label: "Capas", teo: capasTeo, real: capasReal, fmt: (n: number) => String(Math.round(n)) },
    { label: "Promedio m/prenda", teo: promTeo, real: promReal, fmt: (n: number) => n.toFixed(3) },
    { label: "Consumo (m)", teo: metrosTeo, real: metrosReal, fmt: (n: number) => n.toFixed(2) },
  ];

  return (
    <Card>
      <CardContent className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <p className="section-label">Informe de corte · cerrado</p>
          <Badge tone="normal"><Lock className="inline h-2.5 w-2.5 mr-1" />Cortada</Badge>
        </div>

        {/* Identificación en una línea */}
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-graphite">
          <span>Ref: <span className="font-semibold text-ink-900 tabular">{oc.consecutivo}</span></span>
          <span>Lote: <span className="font-semibold text-ink-900">{oc.referencia_lote || "—"}</span></span>
          <span>Entrega: <span className="font-semibold text-ink-900">{fmtFecha(oc.fecha_entrega)}</span></span>
          <span>Cortador: <span className="font-semibold text-ink-900">{oc.responsable || "—"}</span></span>
          {oc.precio_corte != null && (
            <span>Precio: <span className="font-semibold text-ink-900">${Number(oc.precio_corte).toLocaleString("es-CO", { maximumFractionDigits: 0 })}</span></span>
          )}
        </div>

        {/* Diferencias teórico → real → Δ (lo importante) */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {diffs.map((d) => {
            const delta = d.real > 0 && d.teo > 0 ? d.real - d.teo : null;
            const tono = delta == null || delta === 0 ? "text-graphite" : (delta > 0 ? "text-terracotta" : "text-teal");
            return (
              <div key={d.label} className="rounded-sm border border-border bg-cloud/30 p-2.5">
                <p className="text-[0.68rem] uppercase tracking-widest text-graphite">{d.label}</p>
                <p className="mt-1 font-display text-lg tabular text-ink-900">{d.real > 0 ? d.fmt(d.real) : "—"}</p>
                <p className="text-[0.7rem] text-graphite tabular">
                  teórico {d.teo > 0 ? d.fmt(d.teo) : "—"}
                  {delta != null && delta !== 0 && (
                    <span className={`ml-1 font-semibold ${tono}`}>({delta > 0 ? "+" : ""}{d.fmt(delta)})</span>
                  )}
                </p>
              </div>
            );
          })}
        </div>

        {/* Merma / retazos en una línea */}
        {(oc.merma_tipo || oc.merma_valor != null || oc.retazos_cantidad != null) && (
          <p className="text-xs text-graphite">
            Merma: <span className="text-ink-900">{oc.merma_tipo || "—"}{oc.merma_valor != null ? ` · ${oc.merma_valor}` : ""}</span>
            <span className="mx-2 text-graphite/50">·</span>
            Retazos: <span className="text-ink-900">{oc.retazos_cantidad != null ? oc.retazos_cantidad : "—"}</span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}


interface RutaCorte {
  id: string;
  token_publico: string;
  token_publico_terminacion?: string;
  etapa: string;
  precio_confeccion?: number;
  precio_terminacion?: number;
  fecha_entrega_confeccion?: string;
  remision_lavanderia_url?: string;
  terminacion_id?: string;
  asignado_at?: string;
  aceptado_at?: string;
  confeccion_iniciada_at?: string;
  lavanderia_at?: string;
  terminacion_recibida_at?: string;
  terminacion_terminada_at?: string;
  despachado_at?: string;
  confeccionista?: { nombre?: string; telefono?: string };
  terminacion?: { nombre?: string; telefono?: string };
  lavanderia_id?: string;
  lavanderia?: { nombre?: string; telefono?: string };
}

interface ProveedorTerminacion {
  id: string;
  nombre: string;
  telefono?: string;
}

// Notificar a los admins de operación. Ajustar aquí si cambian.
const ADMINS_WA = [
  { nombre: "Karina",    tel: "573005710671" },
  { nombre: "Sebastián", tel: "573122951520" },
  { nombre: "Alejandro", tel: "573008740405" },
];

function HojaRutaCard({ ordenCorteId, consecutivo }: { ordenCorteId: string; consecutivo: string }) {
  const qc = useQueryClient();
  const [urlLav, setUrlLav] = useState("");
  const [errRuta, setErrRuta] = useState("");
  const [lavanderiaId, setLavanderiaId] = useState("");

  const q = useQuery<RutaCorte>({
    queryKey: ["ruta-corte", ordenCorteId],
    queryFn: () => api.get(`/api/produccion/rutas/por-corte/${ordenCorteId}`),
    enabled: !!ordenCorteId,
    retry: false,
  });

  // Lavanderías del directorio — para marcar a cuál se envía el lote
  const lavanderiasQ = useQuery<{ confeccionistas: { id: string; nombre: string }[] }>({
    queryKey: ["confeccionistas", "lavanderia"],
    queryFn: () => api.get("/api/produccion/confeccionistas?tipo=lavanderia&incluir_inactivos=false"),
  });

  // Subir la remisión de recogida de la lavandería (foto/PDF) —
  // al subirla, el backend marca la etapa "lavanderia" INMEDIATAMENTE.
  const [subiendoLav, setSubiendoLav] = useState(false);
  async function subirRemisionLavanderia(file: File) {
    if (!q.data?.id) return;
    setSubiendoLav(true);
    setErrRuta("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (lavanderiaId) fd.append("lavanderia_id", lavanderiaId);
      const r = await fetch(`${API_BASE}/api/produccion/rutas/${q.data.id}/remision-lavanderia`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${r.status}`);
      }
      qc.invalidateQueries({ queryKey: ["ruta-corte", ordenCorteId] });
    } catch (e) {
      setErrRuta(`No se pudo subir la remisión de lavandería: ${e instanceof Error ? e.message : "error"}`);
    } finally {
      setSubiendoLav(false);
    }
  }

  const cambiarEtapa = useMutation({
    mutationFn: (etapa: string) => api.post(`/api/produccion/rutas/${q.data?.id}/etapa`, { etapa }),
    onSuccess: () => { setErrRuta(""); qc.invalidateQueries({ queryKey: ["ruta-corte", ordenCorteId] }); },
    onError: (e: Error) => setErrRuta(`No se pudo cambiar la etapa: ${e.message}`),
  });
  const guardarUrl = useMutation({
    mutationFn: () => api.patch(`/api/produccion/rutas/${q.data?.id}`, {
      remision_lavanderia_url: urlLav || null,
    }),
    onSuccess: () => { setErrRuta(""); qc.invalidateQueries({ queryKey: ["ruta-corte", ordenCorteId] }); },
    onError: (e: Error) => setErrRuta(`No se pudo guardar la remisión de lavandería: ${e.message}`),
  });

  if (q.isLoading) {
    return (
      <Card>
        <CardContent className="p-5 text-xs text-graphite">Cargando hoja de ruta…</CardContent>
      </Card>
    );
  }
  if (!q.data) {
    return (
      <Card>
        <CardContent className="p-5 text-xs text-terracotta">
          No hay hoja de ruta para este lote. Crea una remisión desde /produccion/remisiones para generarla automáticamente.
        </CardContent>
      </Card>
    );
  }

  const r = q.data;
  const etapas = [
    { key: "asignado",              label: "Asignado",         ts: r.asignado_at },
    { key: "aceptado",              label: "Aceptado",         ts: r.aceptado_at },
    { key: "en_confeccion",         label: "En confección",    ts: r.confeccion_iniciada_at },
    { key: "lavanderia",            label: "Lavandería",       ts: r.lavanderia_at },
    { key: "terminacion_recibida",  label: "En terminación",   ts: r.terminacion_recibida_at },
    { key: "terminacion_terminada", label: "Terminado",        ts: r.terminacion_terminada_at },
    { key: "despachado",            label: "Ingreso a bodega", ts: r.despachado_at },
  ];
  const idxActual = etapas.findIndex((e) => e.key === r.etapa);

  const notifMsg = `MALE'DENIM · Lote *${consecutivo}* pasó a etapa *${r.etapa}*. Ver detalle: ${typeof window !== "undefined" ? window.location.origin : ""}/produccion/corte/${ordenCorteId}`;
  function waNotifUrl(tel: string) {
    return `https://wa.me/${tel}?text=${encodeURIComponent(notifMsg)}`;
  }

  const linkPublico = typeof window !== "undefined"
    ? `${window.location.origin}/lote/${r.token_publico}`
    : "";

  // Botón siguiente etapa según la actual
  function botonSiguiente() {
    if (r.etapa === "asignado") return null; // solo confeccionista puede aceptar
    if (r.etapa === "aceptado" || r.etapa === "en_confeccion") {
      return (
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="mb-1 block text-[0.7rem] uppercase tracking-widest text-graphite">Lavandería *</label>
            <select value={lavanderiaId} onChange={(e) => setLavanderiaId(e.target.value)}
              className="rounded-sm border border-border bg-card px-3 py-2 text-xs min-w-[180px]">
              <option value="">Selecciona lavandería…</option>
              {(lavanderiasQ.data?.confeccionistas || []).map((l) => (
                <option key={l.id} value={l.id}>{l.nombre}</option>
              ))}
            </select>
            {(lavanderiasQ.data?.confeccionistas || []).length === 0 && !lavanderiasQ.isLoading && (
              <p className="mt-1 text-[0.7rem] text-terracotta">
                No hay lavanderías. Créalas en Proveedores con tipo &ldquo;Lavandería&rdquo;.
              </p>
            )}
          </div>
          <div>
            <label className="rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700 cursor-pointer inline-flex items-center gap-2 aria-disabled:opacity-40"
              aria-disabled={!lavanderiaId || subiendoLav}>
              {subiendoLav ? "Subiendo…" : "Subir remisión de recogida"}
              <input type="file" accept=".pdf,image/*" className="hidden"
                disabled={!lavanderiaId || subiendoLav}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) subirRemisionLavanderia(f);
                  e.target.value = "";
                }} />
            </label>
            <p className="mt-1 text-[0.7rem] text-graphite">
              Al subir la foto/PDF, el lote queda en <strong>Lavandería</strong> de una vez.
            </p>
          </div>
        </div>
      );
    }
    if (r.etapa === "lavanderia") {
      return (
        <button onClick={() => cambiarEtapa.mutate("terminacion_recibida")} disabled={cambiarEtapa.isPending}
          className="rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40">
          Marcar como recibido en terminación
        </button>
      );
    }
    if (r.etapa === "terminacion_recibida") {
      return (
        <button onClick={() => cambiarEtapa.mutate("terminacion_terminada")} disabled={cambiarEtapa.isPending}
          className="rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40">
          Marcar terminación terminada
        </button>
      );
    }
    if (r.etapa === "terminacion_terminada") {
      return (
        <button onClick={() => cambiarEtapa.mutate("despachado")} disabled={cambiarEtapa.isPending}
          className="rounded-sm bg-teal px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-ink-900 disabled:opacity-40">
          Marcar ingreso a bodega
        </button>
      );
    }
    return null;
  }

  return (
    <Card>
      <CardContent className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <p className="section-label">Hoja de ruta del lote</p>
          <a href={linkPublico} target="_blank" rel="noopener noreferrer"
            className="text-[0.65rem] text-navy-600 hover:underline">Ver ficha pública</a>
        </div>

        {errRuta && (
          <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
            {errRuta}
          </div>
        )}

        {/* Timeline visual */}
        <ol className="grid grid-cols-2 md:grid-cols-7 gap-2">
          {etapas.map((e, i) => {
            const pasada = i <= idxActual;
            const actual = i === idxActual;
            return (
              <li key={e.key} className={`rounded-sm border p-2 ${actual ? "border-navy-600 bg-navy-600/[0.06]" : pasada ? "border-teal/40 bg-teal/[0.04]" : "border-border bg-cloud/20"}`}>
                <p className={`text-[0.68rem] uppercase tracking-widest ${actual ? "text-navy-600" : pasada ? "text-teal" : "text-graphite"}`}>
                  {e.label}
                </p>
                <p className="text-[0.65rem] tabular text-ink-900 mt-1">
                  {e.ts ? new Date(e.ts).toLocaleDateString("es-CO") : "—"}
                </p>
              </li>
            );
          })}
        </ol>

        {/* Info general */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div><span className="text-graphite">Confeccionista:</span> <span className="text-ink-900 font-semibold">{r.confeccionista?.nombre || "—"}</span></div>
          <div><span className="text-graphite">Lavandería:</span> <span className="text-ink-900 font-semibold">{r.lavanderia?.nombre || "—"}</span></div>
          <div><span className="text-graphite">Terminación:</span> <span className="text-ink-900 font-semibold">{r.terminacion?.nombre || "—"}</span></div>
          <div><span className="text-graphite">Precio confección:</span> <span className="text-ink-900 font-semibold tabular">{r.precio_confeccion != null ? `$${Number(r.precio_confeccion).toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}</span></div>
          <div><span className="text-graphite">Fecha entrega:</span> <span className="text-ink-900 font-semibold tabular">{fmtFecha(r.fecha_entrega_confeccion)}</span></div>
        </div>

        {/* Remisión de lavandería */}
        {(r.etapa === "aceptado" || r.etapa === "en_confeccion" || r.etapa === "lavanderia" || r.remision_lavanderia_url) && (
          <div>
            <p className="text-[0.7rem] uppercase tracking-widest text-graphite mb-1">
              Remisión de lavandería (URL / referencia) — al guardarla el lote pasa a Lavandería
            </p>
            <div className="flex items-center gap-2">
              <input value={urlLav} onChange={(e) => setUrlLav(e.target.value)}
                placeholder={r.remision_lavanderia_url || "Pega el link o número de remisión"}
                className="flex-1 rounded-sm border border-border bg-white px-2 py-1.5 text-xs" />
              <button onClick={() => guardarUrl.mutate()} disabled={guardarUrl.isPending || !urlLav}
                className="rounded-sm border border-border bg-cloud px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest hover:bg-cloud/80 disabled:opacity-40">
                Guardar
              </button>
              {r.remision_lavanderia_url && (
                <a href={r.remision_lavanderia_url} target="_blank" rel="noopener noreferrer"
                  className="text-[0.65rem] text-navy-600 hover:underline">Ver actual</a>
              )}
            </div>
          </div>
        )}

        {/* Acciones + notificación */}
        <div className="border-t border-border pt-3 flex flex-wrap items-center gap-2">
          {botonSiguiente()}
          <div className="flex-1" />
          <span className="text-[0.7rem] text-graphite uppercase tracking-widest">Notificar:</span>
          {ADMINS_WA.map((a) => (
            <a key={a.nombre} href={waNotifUrl(a.tel)} target="_blank" rel="noopener noreferrer"
              className="rounded-sm bg-[#25D366] px-2 py-1 text-[0.7rem] font-semibold uppercase tracking-widest text-white hover:opacity-90">
              {a.nombre}
            </a>
          ))}
        </div>

        {/* Timeline de notas — histórico completo (confeccionista + terminación + admin) */}
        <div className="border-t border-border pt-3">
          <TimelineNotas rutaId={r.id} />
        </div>
      </CardContent>
    </Card>
  );
}


/** Generar la remisión de insumos de CONFECCIÓN directo desde el corte cerrado.
 * Los insumos salen de las UNIDADES REALES cortadas por talla (el cálculo del
 * backend usa unidades_cortadas cuando la orden ya está cerrada).
 * Solo aparece si el lote aún no tiene hoja de ruta (= no tiene remisión). */
function GenerarRemisionCard({ ordenCorteId, esCortador }: { ordenCorteId: string; esCortador?: boolean }) {
  const router = useRouter();
  const { user } = useAuth();
  const [confId, setConfId] = useState("");
  const [errRem, setErrRem] = useState("");

  // ¿Ya tiene ruta? (la crea la remisión de confección) → no mostrar
  const rutaQ = useQuery<{ id: string }>({
    queryKey: ["ruta-corte", ordenCorteId],
    queryFn: () => api.get(`/api/produccion/rutas/por-corte/${ordenCorteId}`),
    enabled: !!ordenCorteId,
    retry: false,
  });

  const confsQ = useQuery<{ confeccionistas: { id: string; nombre: string }[] }>({
    queryKey: ["confeccionistas", "confeccion"],
    queryFn: () => api.get("/api/produccion/confeccionistas?tipo=confeccion&incluir_inactivos=false"),
  });

  const crear = useMutation({
    mutationFn: () => api.post<{ ok: boolean; remision: { id: string } }>("/api/produccion/remisiones", {
      confeccionista_id: confId,
      fecha_recogida: hoyBogotaISO(),
      orden_corte_ids: [ordenCorteId],
      tipo: "confeccion",
    }),
    onSuccess: (data) => router.push(`/produccion/remisiones/${data.remision.id}`),
    onError: (e: Error) => setErrRem(e.message),
  });

  // La genera el cortador (tras confirmar el informe) o el encargado de remisiones.
  const puedeGenerar = puedeAccionModulo(user, "produccion_remisiones", "modificar")
    || puedeAccionModulo(user, "produccion_cortador", "modificar");
  if (!puedeGenerar) return null;
  // Si ya hay ruta (remisión creada), no mostrar nada
  if (rutaQ.isLoading || rutaQ.data) return null;

  const confs = confsQ.data?.confeccionistas || [];

  return (
    <Card>
      <CardContent className="p-5 space-y-3">
        <p className="section-label">Generar remisión de confección</p>
        <p className="text-xs text-graphite">
          {esCortador
            ? <>Confirmaste el informe — ahora <strong>genera la remisión</strong>, imprímela
               (sale con las <strong>unidades cortadas por talla</strong> y la
               <strong> medida del retazo</strong>) y márcala como <strong>recogida</strong> al entregarla.</>
            : <>El cortador guardó el informe — este lote está <strong>listo para remisión</strong>.
               Cuenta los insumos de confección y genera la remisión con las
               <strong> unidades reales cortadas por talla</strong>.</>}
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="mb-1 block text-[0.7rem] uppercase tracking-widest text-graphite">Confeccionista *</label>
            <select value={confId} onChange={(e) => setConfId(e.target.value)}
              className="rounded-sm border border-border bg-card px-3 py-2 text-sm min-w-[200px]">
              <option value="">Selecciona…</option>
              {confs.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </select>
            {confs.length === 0 && !confsQ.isLoading && (
              <p className="mt-1 text-[0.7rem] text-terracotta">No hay confeccionistas activos.</p>
            )}
          </div>
          <button onClick={() => crear.mutate()} disabled={crear.isPending || !confId}
            className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40">
            {crear.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Generar remisión
          </button>
        </div>
        {errRem && (
          <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
            {errRem}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
