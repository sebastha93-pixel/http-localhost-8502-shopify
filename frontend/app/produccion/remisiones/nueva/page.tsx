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
import { api } from "@/lib/api";
import { PageShell, LoadingState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Save, Loader2, AlertCircle, Search, ChevronDown } from "lucide-react";

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
}

export default function NuevaRemisionPage() {
  const router = useRouter();
  const hoy = new Date().toISOString().slice(0, 10);

  const [confId, setConfId] = useState("");
  const [fechaRecogida, setFechaRecogida] = useState(hoy);
  const [ordenesSeleccionadas, setOrdenesSeleccionadas] = useState<Set<string>>(new Set());
  const [err, setErr] = useState("");

  // Confeccionistas activos
  const confQ = useQuery<{ confeccionistas: Confeccionista[] }>({
    queryKey: ["produccion", "confeccionistas", false],
    queryFn: () => api.get("/api/produccion/confeccionistas?incluir_inactivos=false"),
  });

  // Órdenes cortadas
  const ocQ = useQuery<{ ordenes: OrdenCorte[] }>({
    queryKey: ["produccion", "corte", "cortadas"],
    queryFn: () => api.get("/api/produccion/corte?estado=cortada"),
  });

  const confs = confQ.data?.confeccionistas || [];
  const ordenes = (ocQ.data?.ordenes || []).filter((o) => o.estado === "cortada");

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

  const mut = useMutation({
    mutationFn: () => {
      if (!confId) throw new Error("Selecciona un confeccionista");
      if (ordenesSeleccionadas.size === 0) throw new Error("Selecciona al menos una orden de corte");
      return api.post<{ ok: boolean; remision: { id: string } }>("/api/produccion/remisiones", {
        confeccionista_id: confId,
        fecha_recogida: fechaRecogida,
        orden_corte_ids: Array.from(ordenesSeleccionadas),
      });
    },
    onSuccess: (data) => router.push(`/produccion/remisiones/${data.remision.id}`),
    onError: (e: Error) => setErr(e.message),
  });

  if (confQ.isLoading || ocQ.isLoading) return <LoadingState label="Cargando…" />;

  return (
    <PageShell title="Nueva remisión" subtitle="Entrega al confeccionista">
      <form onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }} className="space-y-4">
        <Card>
          <CardContent className="p-5 space-y-4">
            <p className="section-label">Cabecera</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* Combobox confeccionista */}
              <div ref={confBoxRef} className="relative">
                <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                  Confeccionista *
                </label>
                <button type="button" onClick={() => setConfOpen((v) => !v)}
                  className="w-full flex items-center justify-between rounded-sm border border-border bg-card px-3 py-2 text-sm text-left hover:bg-cloud/30">
                  <span className={confSel ? "text-ink-900" : "text-graphite/60"}>
                    {confSel ? confSel.nombre : "Selecciona un confeccionista…"}
                  </span>
                  <ChevronDown className={`h-3.5 w-3.5 text-graphite transition-transform ${confOpen ? "rotate-180" : ""}`} />
                </button>
                {confOpen && (
                  <div className="absolute z-20 mt-1 w-full rounded-sm border border-border bg-white shadow-lg">
                    <div className="p-2 border-b border-border">
                      <div className="flex items-center gap-2 rounded-sm border border-border bg-cloud/30 px-2 py-1.5">
                        <Search className="h-3.5 w-3.5 text-graphite flex-none" />
                        <input autoFocus value={confBuscar} onChange={(e) => setConfBuscar(e.target.value)}
                          placeholder="Buscar taller…"
                          className="w-full bg-transparent text-sm outline-none" />
                      </div>
                    </div>
                    <div className="max-h-64 overflow-y-auto">
                      {confsFiltrados.length === 0 ? (
                        <div className="px-3 py-3 text-xs text-graphite">
                          {confs.length === 0
                            ? "No hay confeccionistas. Crea uno en /produccion/confeccionistas."
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
              <table className="w-full text-xs">
                <thead className="bg-cloud/40 border-b border-border">
                  <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                    <th className="px-4 py-2 w-[40px]"></th>
                    <th className="px-4 py-2">Consecutivo</th>
                    <th className="px-4 py-2">Referencia</th>
                    <th className="px-4 py-2">Lote</th>
                    <th className="px-4 py-2 text-right">Cantidad</th>
                    <th className="px-4 py-2">Entrega</th>
                  </tr>
                </thead>
                <tbody>
                  {ordenes.map((o) => (
                    <tr key={o.id} className={`border-b border-border/40 ${ordenesSeleccionadas.has(o.id) ? "bg-teal/5" : "hover:bg-cloud/30"}`}>
                      <td className="px-4 py-2">
                        <input type="checkbox" checked={ordenesSeleccionadas.has(o.id)}
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
                      <td className="px-4 py-2 text-graphite tabular text-[0.65rem]">{o.fecha_entrega || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        {err && (
          <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
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
