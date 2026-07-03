"use client";

/**
 * Nueva remisión a confeccionista.
 * - Escoge confeccionista (combobox con lupa).
 * - Elige N órdenes de corte en estado 'cortada' (checkboxes).
 * - Fecha de recogida.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { fmtFecha, hoyBogotaISO } from "@/lib/utils";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Save, Loader2, AlertCircle, Search, ChevronDown, Printer, CheckCircle, MessageCircle, ArrowRight } from "lucide-react";

interface Confeccionista {
  id: string;
  nombre: string;
  telefono?: string;
  activo: boolean;
}

interface OrdenCorte {
  id: string;
  consecutivo: string;
  estado: string;
  referencia_lote?: string;
  cantidad_programada?: number;
  fecha_entrega?: string;
  referencia?: { codigo_referencia: string; nombre: string; tela?: string };
  tiene_remision_confeccion?: boolean;
  tiene_remision_terminacion?: boolean;
}

export default function NuevaRemisionPage() {
  const router = useRouter();
  const hoy = hoyBogotaISO(); // Bogotá — toISOString saltaba al día siguiente después de las 7 PM

  const [tipo, setTipo] = useState<"confeccion" | "terminacion">("confeccion");
  const [confId, setConfId] = useState("");
  const [fechaRecogida, setFechaRecogida] = useState(hoy);
  const [ordenesSeleccionadas, setOrdenesSeleccionadas] = useState<Set<string>>(new Set());
  const [err, setErr] = useState("");

  // Proveedores activos del tipo seleccionado (confección o terminación)
  const confQ = useQuery<{ confeccionistas: Confeccionista[] }>({
    queryKey: ["produccion", "confeccionistas", tipo],
    queryFn: () => api.get(`/api/produccion/confeccionistas?incluir_inactivos=false&tipo=${tipo}`),
  });

  // Órdenes cortadas anotadas con qué remisiones ya tienen. Las que ya
  // tienen remisión del tipo elegido se muestran MARCADAS pero deshabilitadas
  // — un lote no se remite dos veces al mismo proceso.
  const ocQ = useQuery<{ ordenes: OrdenCorte[] }>({
    queryKey: ["produccion", "corte", "cortadas", "marcadas"],
    queryFn: () => api.get("/api/produccion/corte?estado=cortada&marcar_remisiones=true"),
  });

  const confs = confQ.data?.confeccionistas || [];
  const ordenes = (ocQ.data?.ordenes || []).filter((o) => o.estado === "cortada");

  function yaRemitida(o: OrdenCorte): boolean {
    return tipo === "terminacion" ? !!o.tiene_remision_terminacion : !!o.tiene_remision_confeccion;
  }

  // Combobox confeccionista con lupa
  const [confBuscar, setConfBuscar] = useState("");
  const [confOpen, setConfOpen] = useState(false);
  const confBoxRef = useRef<HTMLDivElement>(null);
  const confSel = useMemo(() => confs.find((c) => c.id === confId), [confs, confId]);
  const confsFiltrados = useMemo(() => {
    const q = confBuscar.trim().toUpperCase();
    if (!q) return confs;
    return confs.filter((c) => c.nombre.toUpperCase().includes(q));
  }, [confs, confBuscar]);
  useEffect(() => {
    function h(e: MouseEvent) {
      if (confBoxRef.current && !confBoxRef.current.contains(e.target as Node)) setConfOpen(false);
    }
    if (confOpen) { document.addEventListener("mousedown", h); return () => document.removeEventListener("mousedown", h); }
  }, [confOpen]);

  function toggleOrden(id: string) {
    setOrdenesSeleccionadas((prev) => {
      const s = new Set(prev);
      if (s.has(id)) s.delete(id); else s.add(id);
      return s;
    });
  }

  interface WaSalida { referencia: string; enviado: boolean; wa_url: string }
  interface RespuestaCrear {
    ok: boolean;
    remision: { id: string; consecutivo?: string };
    impresion?: string;          // "auto" | "manual" (solo terminación)
    whatsapp?: WaSalida[];       // links al proveedor de terminación
  }
  // Resultado de la creación de una remisión de TERMINACIÓN: en vez de
  // redirigir, mostramos el panel con impresión + envío de WhatsApp.
  const [creada, setCreada] = useState<RespuestaCrear | null>(null);

  async function imprimirRemision(remId: string) {
    try {
      const r = await fetch(`${API_BASE}/api/produccion/remisiones/${remId}/pdf`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!r.ok) return;
      const blob = await r.blob();
      const win = window.open(URL.createObjectURL(blob), "_blank");
      if (win) win.addEventListener("load", () => { try { win.print(); } catch { /* noop */ } });
    } catch { /* el botón Imprimir sigue disponible */ }
  }

  const mut = useMutation({
    mutationFn: () => {
      if (!confId) throw new Error(tipo === "terminacion" ? "Selecciona un proveedor de terminación" : "Selecciona un confeccionista");
      if (ordenesSeleccionadas.size === 0) throw new Error("Selecciona al menos una orden de corte");
      return api.post<RespuestaCrear>("/api/produccion/remisiones", {
        confeccionista_id: confId,
        fecha_recogida: fechaRecogida,
        orden_corte_ids: Array.from(ordenesSeleccionadas),
        tipo,
      });
    },
    onSuccess: (data) => {
      if (tipo === "terminacion") {
        setCreada(data);
        // Impresión de la remisión de insumos de terminación:
        // "auto" = ya salió por la RICOH; "manual" = abrimos el diálogo.
        if (data.impresion !== "auto") imprimirRemision(data.remision.id);
      } else {
        router.push(`/produccion/remisiones/${data.remision.id}`);
      }
    },
    onError: (e: Error) => setErr(e.message),
  });

  if (creada) {
    const wa = creada.whatsapp || [];
    const nombreProv = confs.find((c) => c.id === confId)?.nombre || "el proveedor";
    return (
      <PageShell title="Remisión de terminación creada" subtitle={creada.remision.consecutivo || ""}>
        <Card>
          <CardContent className="p-6 space-y-4">
            <div className="flex items-center gap-2 text-teal">
              <CheckCircle className="h-5 w-5" />
              <p className="text-sm font-semibold">Lote asignado a terminación ({nombreProv})</p>
            </div>

            {/* Impresión */}
            <div className="rounded-sm border border-border bg-cloud/30 px-4 py-3 flex flex-wrap items-center gap-3 text-xs">
              <Printer className="h-4 w-4 text-navy-600 flex-none" />
              {creada.impresion === "auto" ? (
                <span className="text-teal font-semibold">Remisión de insumos enviada a la RICOH 🖨</span>
              ) : (
                <>
                  <span className="text-graphite">Se abrió el PDF con el diálogo de impresión.</span>
                  <button onClick={() => imprimirRemision(creada.remision.id)}
                    className="rounded-sm border border-border bg-white px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest hover:bg-cloud">
                    Volver a imprimir
                  </button>
                </>
              )}
            </div>

            {/* WhatsApp al proveedor de terminación */}
            <div className="rounded-sm border border-border bg-cloud/30 px-4 py-3 space-y-2 text-xs">
              <div className="flex items-center gap-2 text-graphite">
                <MessageCircle className="h-4 w-4 text-[#25D366] flex-none" />
                <span>Link del lote para {nombreProv}:</span>
              </div>
              {wa.length === 0 ? (
                <p className="text-terracotta">No se pudo armar el link (¿el lote tiene hoja de ruta?). Envíalo desde el detalle de la remisión.</p>
              ) : wa.map((w, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-ink-900">REF {w.referencia}</span>
                  {w.enviado ? (
                    <span className="text-teal font-semibold">✓ WhatsApp enviado automáticamente</span>
                  ) : (
                    <a href={w.wa_url} target="_blank" rel="noopener noreferrer"
                      className="rounded-sm bg-[#25D366] px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:opacity-90">
                      Enviar WhatsApp
                    </a>
                  )}
                </div>
              ))}
            </div>

            <div className="flex items-center gap-2 pt-1">
              <button onClick={() => router.push(`/produccion/remisiones/${creada.remision.id}`)}
                className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700">
                Ver la remisión <ArrowRight className="h-3.5 w-3.5" />
              </button>
              <button onClick={() => router.push("/produccion/remisiones")}
                className="rounded-sm border border-border bg-white px-4 py-2 text-xs font-semibold uppercase tracking-widest text-graphite hover:bg-cloud">
                Ir a remisiones
              </button>
            </div>
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  if (confQ.isLoading || ocQ.isLoading) return <LoadingState label="Cargando…" />;
  if (confQ.isError) return <ErrorState error={confQ.error} onRetry={() => confQ.refetch()} />;
  if (ocQ.isError) return <ErrorState error={ocQ.error} onRetry={() => ocQ.refetch()} />;

  return (
    <PageShell
      title="Nueva remisión"
      subtitle={tipo === "terminacion" ? "Entrega al proveedor de terminación" : "Entrega al confeccionista"}
    >
      <form onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }} className="space-y-4">
        <Card>
          <CardContent className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <p className="section-label">Cabecera</p>
              {/* Toggle tipo de remisión */}
              <div className="inline-flex rounded-sm border border-border overflow-hidden">
                <button type="button"
                  onClick={() => { setTipo("confeccion"); setConfId(""); setOrdenesSeleccionadas(new Set()); }}
                  className={`px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest ${tipo === "confeccion" ? "bg-navy-600 text-white" : "bg-white text-graphite hover:bg-cloud"}`}>
                  Confección
                </button>
                <button type="button"
                  onClick={() => { setTipo("terminacion"); setConfId(""); setOrdenesSeleccionadas(new Set()); }}
                  className={`px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest border-l border-border ${tipo === "terminacion" ? "bg-navy-600 text-white" : "bg-white text-graphite hover:bg-cloud"}`}>
                  Terminación
                </button>
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* Combobox confeccionista */}
              <div ref={confBoxRef} className="relative">
                <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                  {tipo === "terminacion" ? "Proveedor terminación *" : "Confeccionista *"}
                </label>
                <button type="button" onClick={() => setConfOpen((v) => !v)}
                  className="w-full flex items-center justify-between rounded-sm border border-border bg-card px-3 py-2 text-sm text-left hover:bg-cloud/30">
                  <span className={confSel ? "text-ink-900" : "text-graphite/60"}>
                    {confSel ? confSel.nombre : (tipo === "terminacion" ? "Selecciona un proveedor…" : "Selecciona un confeccionista…")}
                  </span>
                  <ChevronDown className={`h-3.5 w-3.5 text-graphite transition-transform ${confOpen ? "rotate-180" : ""}`} />
                </button>
                {confOpen && (
                  <div className="absolute z-20 mt-1 w-full rounded-sm border border-border bg-white shadow-lg">
                    <div className="p-2 border-b border-border">
                      <div className="flex items-center gap-2 rounded-sm border border-border bg-cloud/30 px-2 py-1.5">
                        <Search className="h-3.5 w-3.5 text-graphite flex-none" />
                        <input autoFocus value={confBuscar} onChange={(e) => setConfBuscar(e.target.value)}
                          placeholder={tipo === "terminacion" ? "Buscar proveedor…" : "Buscar taller…"}
                          className="w-full bg-transparent text-sm outline-none" />
                      </div>
                    </div>
                    <div className="max-h-64 overflow-y-auto">
                      {confsFiltrados.length === 0 ? (
                        <div className="px-3 py-3 text-xs text-graphite">
                          {confs.length === 0
                            ? (tipo === "terminacion"
                                ? "No hay proveedores de terminación. Créalos en /produccion/confeccionistas con tipo 'Terminación'."
                                : "No hay confeccionistas. Créalos en /produccion/confeccionistas.")
                            : "Ninguno coincide."}
                        </div>
                      ) : confsFiltrados.map((c) => (
                        <button key={c.id} type="button"
                          onClick={() => { setConfId(c.id); setConfOpen(false); setConfBuscar(""); }}
                          className={`w-full flex items-center justify-between px-3 py-2 text-left text-xs hover:bg-cloud/50 ${confId === c.id ? "bg-navy-600/[0.06]" : ""}`}>
                          <span className="font-semibold text-ink-900">{c.nombre}</span>
                          {c.telefono && <span className="text-graphite text-[0.65rem]">{c.telefono}</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              <div>
                <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                  Fecha de recogida *
                </label>
                <input type="date" value={fechaRecogida} onChange={(e) => setFechaRecogida(e.target.value)} required
                  className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Órdenes de corte disponibles */}
        <Card>
          <CardContent className="p-0">
            <div className="px-4 py-3 border-b border-border flex items-center justify-between">
              <p className="section-label">Órdenes cortadas ({ordenesSeleccionadas.size} seleccionadas)</p>
              <p className="text-[0.65rem] text-graphite">Selecciona las que van a este confeccionista</p>
            </div>
            {ordenes.length === 0 ? (
              <div className="p-8 text-center text-xs text-graphite">
                No hay órdenes de corte cerradas disponibles.
              </div>
            ) : (
              <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-cloud/40 border-b border-border">
                  <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                    <th className="px-4 py-2 w-[40px]"></th>
                    <th className="px-4 py-2">Consecutivo</th>
                    <th className="px-4 py-2">Referencia</th>
                    <th className="px-4 py-2">Lote</th>
                    <th className="px-4 py-2 text-right">Cantidad</th>
                    <th className="px-4 py-2">Entrega</th>
                    <th className="px-4 py-2 text-right">Remisiones</th>
                  </tr>
                </thead>
                <tbody>
                  {ordenes.map((o) => {
                    const bloqueada = yaRemitida(o);
                    return (
                      <tr key={o.id}
                        className={`border-b border-border/40 ${bloqueada ? "opacity-50 bg-cloud/20" : ordenesSeleccionadas.has(o.id) ? "bg-teal/5" : "hover:bg-cloud/30"}`}>
                        <td className="px-4 py-2">
                          <input type="checkbox" checked={ordenesSeleccionadas.has(o.id)}
                            disabled={bloqueada}
                            onChange={() => toggleOrden(o.id)} />
                        </td>
                        <td className="px-4 py-2 font-semibold tabular text-navy-600">{o.consecutivo}</td>
                        <td className="px-4 py-2 text-ink-900">
                          {o.referencia?.codigo_referencia || "—"}
                          <div className="text-[0.6rem] text-graphite">
                            {o.referencia?.nombre} {o.referencia?.tela ? `· ${o.referencia.tela}` : ""}
                          </div>
                        </td>
                        <td className="px-4 py-2 text-graphite">{o.referencia_lote || "—"}</td>
                        <td className="px-4 py-2 text-right tabular">{o.cantidad_programada || "—"}</td>
                        <td className="px-4 py-2 text-graphite tabular text-[0.65rem]">{fmtFecha(o.fecha_entrega)}</td>
                        <td className="px-4 py-2">
                          <div className="flex flex-wrap gap-1 justify-end">
                            {o.tiene_remision_confeccion && (
                              <span className="rounded-sm bg-navy-600/10 px-1.5 py-0.5 text-[0.52rem] font-bold uppercase tracking-widest text-navy-600">
                                ✓ Confección
                              </span>
                            )}
                            {o.tiene_remision_terminacion && (
                              <span className="rounded-sm bg-teal/10 px-1.5 py-0.5 text-[0.52rem] font-bold uppercase tracking-widest text-teal">
                                ✓ Terminación
                              </span>
                            )}
                          </div>
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

        {err && (
          <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5" /> {err}
          </div>
        )}

        <div className="sticky bottom-0 bg-white/95 backdrop-blur border-t border-border py-3 flex items-center justify-between gap-3">
          <p className="text-xs text-graphite">
            Se generará el consecutivo <span className="font-semibold text-ink-900">REM-YYYY-NNNN</span>.
          </p>
          <button type="submit" disabled={mut.isPending || !confId || ordenesSeleccionadas.size === 0}
            className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700 disabled:opacity-40">
            {mut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Crear remisión
          </button>
        </div>
      </form>
    </PageShell>
  );
}
