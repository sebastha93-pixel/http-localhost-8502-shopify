"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight, Package } from "lucide-react";

interface ResumenLinea {
  descripcion_tela: string;
  tono: string;
  num_rollos: number;
  metros_disponible: number;
  metros_inicial: number;
  valor_estimado: number;
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

  if (resumenQ.isLoading) return <LoadingState label="Cargando inventario…" />;
  if (resumenQ.isError) return <ErrorState error={resumenQ.error} onRetry={() => resumenQ.refetch()} />;

  const resumen = resumenQ.data?.resumen || [];
  const totalMetros = resumen.reduce((s, r) => s + r.metros_disponible, 0);
  const totalRollos = resumen.reduce((s, r) => s + r.num_rollos, 0);
  const totalValor = resumen.reduce((s, r) => s + r.valor_estimado, 0);

  return (
    <PageShell
      title="Inventario de tela"
      subtitle="Rollos agrupados por tela y tono"
      onRefresh={() => resumenQ.refetch()}
    >
      <Card>
        <CardContent className="p-4 grid grid-cols-2 md:grid-cols-4 gap-4">
          <Kpi label="Telas distintas" value={new Set(resumen.map((r) => r.descripcion_tela)).size.toString()} />
          <Kpi label="Rollos totales"  value={totalRollos.toString()} />
          <Kpi label="Metros disponibles" value={totalMetros.toLocaleString("es-CO", { maximumFractionDigits: 0 })} />
          <Kpi label="Valor estimado" value={"$" + totalValor.toLocaleString("es-CO", { maximumFractionDigits: 0 })} />
        </CardContent>
      </Card>

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
                    {isOpen && <RollosDeTela tela={r.descripcion_tela} tono={r.tono} />}
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

function RollosDeTela({ tela, tono }: { tela: string; tono: string }) {
  const q = useQuery<{ rollos: Rollo[] }>({
    queryKey: ["produccion", "rollos", tela, tono],
    queryFn: () => api.get(`/api/produccion/rollos?tela=${encodeURIComponent(tela)}${tono !== "—" ? `&tono=${encodeURIComponent(tono)}` : ""}`),
  });
  if (q.isLoading) return <p className="px-4 py-3 text-xs text-graphite">Cargando rollos…</p>;
  const rollos = (q.data?.rollos || []).filter((r) => r.estado !== "agotado");
  return (
    <div className="bg-cloud/30 border-t border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
            <th className="px-8 py-2">Código</th>
            <th className="px-4 py-2 text-right">Metros</th>
            <th className="px-4 py-2">Lote</th>
            <th className="px-4 py-2">Ancho</th>
            <th className="px-4 py-2">Estado</th>
          </tr>
        </thead>
        <tbody>
          {rollos.map((r) => (
            <tr key={r.id} className="border-t border-border/40">
              <td className="px-8 py-1.5">
                <Link href={`/produccion/rollos/${r.id}`} className="text-navy-600 hover:underline tabular text-xs">
                  {r.codigo_interno}
                </Link>
              </td>
              <td className="px-4 py-1.5 text-right tabular text-xs">{r.metros_disponible} / {r.metros_inicial}</td>
              <td className="px-4 py-1.5 text-xs text-graphite">{r.lote_fabrica || "—"}</td>
              <td className="px-4 py-1.5 text-xs text-graphite">{r.ancho || "—"}</td>
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
