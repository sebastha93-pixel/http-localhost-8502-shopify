"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight, Loader2, Printer } from "lucide-react";

interface ResumenLinea {
  descripcion_tela: string;
  tono: string;
  num_rollos: number;
  metros_disponible: number;
  metros_inicial: number;
  valor_estimado?: number;
}

interface Rollo {
  id: string;
  codigo_interno: string;
  descripcion_tela: string;
  tono?: string;
  ancho?: number;
  metros_inicial: number;
  metros_disponible: number;
  lote_fabrica?: string;
  estado: string;
}

export default function InventarioPage() {
  const resumenQ = useQuery<{ resumen: ResumenLinea[] }>({
    queryKey: ["produccion", "inventario", "resumen"],
    queryFn: () => api.get("/api/produccion/inventario/resumen"),
    staleTime: 60_000,
  });

  const [expandido, setExpandido] = useState<string | null>(null);
  // Selección GLOBAL de rollos (cruza telas) para imprimir etiquetas
  const [seleccion, setSeleccion] = useState<Set<string>>(new Set());
  const [imprimiendo, setImprimiendo] = useState(false);
  const [errPdf, setErrPdf] = useState("");

  function toggleRollo(id: string) {
    setSeleccion((prev) => {
      const s = new Set(prev);
      if (s.has(id)) s.delete(id); else s.add(id);
      return s;
    });
  }

  // Un solo PDF, una página por rollo (mismo endpoint que en Ingreso)
  async function imprimirSeleccion() {
    if (seleccion.size === 0) return;
    setImprimiendo(true);
    setErrPdf("");
    try {
      const r = await fetch(`${API_BASE}/api/produccion/rollos/etiquetas`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${getToken()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ rollo_ids: Array.from(seleccion) }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      window.open(URL.createObjectURL(blob), "_blank");
    } catch (e) {
      setErrPdf(`No se pudo generar el PDF: ${e instanceof Error ? e.message : "error"}`);
    } finally {
      setImprimiendo(false);
    }
  }

  if (resumenQ.isLoading) return <LoadingState label="Cargando inventario…" />;
  if (resumenQ.isError) return <ErrorState error={resumenQ.error} onRetry={() => resumenQ.refetch()} />;

  const resumen = resumenQ.data?.resumen || [];
  const totalMetros = resumen.reduce((s, r) => s + r.metros_disponible, 0);
  const totalRollos = resumen.reduce((s, r) => s + r.num_rollos, 0);
  const conValor = resumen.some((r) => r.valor_estimado != null);
  const totalValor = resumen.reduce((s, r) => s + (r.valor_estimado || 0), 0);

  return (
    <PageShell
      title="Inventario de tela"
      subtitle="Rollos agrupados por tela y tono"
      onRefresh={() => resumenQ.refetch()}
    >
      <Card>
        <CardContent className={`p-4 grid grid-cols-2 ${conValor ? "md:grid-cols-4" : "md:grid-cols-3"} gap-4`}>
          <Kpi label="Telas distintas" value={new Set(resumen.map((r) => r.descripcion_tela)).size.toString()} />
          <Kpi label="Rollos totales"  value={totalRollos.toString()} />
          <Kpi label="Metros disponibles" value={totalMetros.toLocaleString("es-CO", { maximumFractionDigits: 0 })} />
          {conValor && <Kpi label="Valor estimado" value={"$" + totalValor.toLocaleString("es-CO", { maximumFractionDigits: 0 })} />}
        </CardContent>
      </Card>

      {/* Barra de impresión — aparece al seleccionar rollos */}
      {seleccion.size > 0 && (
        <div className="sticky top-2 z-20 flex items-center justify-between gap-3 rounded-sm border border-navy-600/40 bg-navy-600/[0.06] backdrop-blur px-4 py-2.5">
          <p className="text-xs font-semibold text-navy-600 tabular">
            {seleccion.size} rollo(s) seleccionado(s)
          </p>
          <div className="flex items-center gap-2">
            <button onClick={() => setSeleccion(new Set())}
              className="text-[0.65rem] uppercase tracking-widest text-graphite hover:text-ink-900">
              Limpiar
            </button>
            <button onClick={imprimirSeleccion} disabled={imprimiendo}
              className="inline-flex items-center gap-1.5 rounded-sm bg-navy-600 px-3 py-1.5 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40">
              {imprimiendo ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Printer className="h-3.5 w-3.5" />}
              Imprimir etiquetas
            </button>
          </div>
        </div>
      )}

      {errPdf && (
        <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
          {errPdf}
        </div>
      )}

      <Card>
        <CardContent className="p-0">
          {resumen.length === 0 ? (
            <p className="p-8 text-center text-sm text-graphite">
              Sin telas en stock. Registra un{" "}
              <Link href="/produccion/ingreso/nuevo" className="text-navy-600 hover:underline">ingreso nuevo</Link>.
            </p>
          ) : (
            <div className="divide-y divide-border">
              {resumen.map((r) => {
                const key = `${r.descripcion_tela}||${r.tono}`;
                const isOpen = expandido === key;
                return (
                  <div key={key}>
                    <button
                      onClick={() => setExpandido(isOpen ? null : key)}
                      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-cloud/50 text-left"
                    >
                      {isOpen ? <ChevronDown className="h-4 w-4 text-graphite" /> : <ChevronRight className="h-4 w-4 text-graphite" />}
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-ink-900">{r.descripcion_tela}</p>
                        <p className="text-[0.65rem] text-graphite">
                          Tono: {r.tono} · {r.num_rollos} rollos
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="font-display text-base text-ink-900 tabular">
                          {r.metros_disponible.toLocaleString("es-CO", { maximumFractionDigits: 2 })} m
                        </p>
                        <p className="text-[0.6rem] text-graphite tabular">
                          de {r.metros_inicial.toLocaleString("es-CO", { maximumFractionDigits: 0 })}
                        </p>
                      </div>
                    </button>
                    {isOpen && (
                      <RollosDeTela tela={r.descripcion_tela} tono={r.tono}
                        seleccion={seleccion} onToggle={toggleRollo}
                        onSeleccionarTodos={(ids, marcar) => {
                          setSeleccion((prev) => {
                            const s = new Set(prev);
                            for (const id of ids) marcar ? s.add(id) : s.delete(id);
                            return s;
                          });
                        }} />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}

function RollosDeTela({ tela, tono, seleccion, onToggle, onSeleccionarTodos }: {
  tela: string;
  tono: string;
  seleccion: Set<string>;
  onToggle: (id: string) => void;
  onSeleccionarTodos: (ids: string[], marcar: boolean) => void;
}) {
  const q = useQuery<{ rollos: Rollo[] }>({
    queryKey: ["produccion", "rollos", tela, tono],
    queryFn: () => api.get(`/api/produccion/rollos?tela=${encodeURIComponent(tela)}${tono !== "—" ? `&tono=${encodeURIComponent(tono)}` : ""}`),
  });
  if (q.isLoading) return <p className="px-4 py-3 text-xs text-graphite">Cargando rollos…</p>;
  const rollos = (q.data?.rollos || []).filter((r) => r.estado !== "agotado");
  const ids = rollos.map((r) => r.id);
  const todosMarcados = ids.length > 0 && ids.every((id) => seleccion.has(id));
  return (
    <div className="bg-cloud/30 border-t border-border overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
            <th className="pl-8 pr-2 py-2 w-[40px]">
              <input type="checkbox" checked={todosMarcados}
                onChange={() => onSeleccionarTodos(ids, !todosMarcados)}
                aria-label={`Seleccionar todos los rollos de ${tela}`}
                className="h-4 w-4 cursor-pointer rounded border-graphite/40" />
            </th>
            <th className="px-2 py-2">Código</th>
            <th className="px-4 py-2 text-right">Metros</th>
            <th className="px-4 py-2">Lote</th>
            <th className="px-4 py-2">Estado</th>
          </tr>
        </thead>
        <tbody>
          {rollos.map((r) => (
            <tr key={r.id}
              className={`border-t border-border/40 ${seleccion.has(r.id) ? "bg-navy-600/[0.05]" : ""}`}>
              <td className="pl-8 pr-2 py-1.5">
                <input type="checkbox" checked={seleccion.has(r.id)} onChange={() => onToggle(r.id)}
                  aria-label={`Seleccionar rollo ${r.codigo_interno}`}
                  className="h-4 w-4 cursor-pointer rounded border-graphite/40" />
              </td>
              <td className="px-2 py-1.5">
                <Link href={`/produccion/rollos/${r.id}`} className="text-navy-600 hover:underline tabular text-xs">
                  {r.codigo_interno}
                </Link>
              </td>
              <td className="px-4 py-1.5 text-right tabular text-xs">{r.metros_disponible} / {r.metros_inicial}</td>
              <td className="px-4 py-1.5 text-xs text-graphite">{r.lote_fabrica || "—"}</td>
              <td className="px-4 py-1.5">
                <Badge tone={r.estado === "disponible" ? "normal" : "info"}>{r.estado}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.6rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className="mt-1 font-display text-xl text-ink-900 tabular">{value}</p>
    </div>
  );
}
