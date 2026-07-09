"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Plus, Lock } from "lucide-react";

interface Ref {
  id: string;
  codigo_referencia: string;
  nombre: string;
  tela?: string;
  color?: string;
  costo_total_con_iva: number;
  precio_sugerido_venta?: number;
  estado: string;
  bloqueada: boolean;
  autorizada_por?: string;
  fecha_autorizacion?: string;
  created_at?: string;
}

export default function PrecosteoListPage() {
  const [estado, setEstado] = useState<string>("");

  const q = useQuery<{ precosteos: Ref[] }>({
    queryKey: ["produccion", "precosteo", "list", estado],
    queryFn: () => api.get(`/api/produccion/precosteo${estado ? `?estado=${estado}` : ""}`),
  });

  if (q.isLoading) return <LoadingState label="Cargando precosteos…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const rows = q.data?.precosteos || [];

  return (
    <PageShell
      title="Precosteo"
      subtitle={`${rows.length} referencias · costeo por unidad`}
      onRefresh={() => q.refetch()}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {["", "borrador", "autorizada"].map((e) => (
            <button
              key={e}
              onClick={() => setEstado(e)}
              className={`rounded-sm px-3 py-1.5 text-xs font-medium uppercase tracking-wider transition-colors ${
                estado === e ? "bg-ink-900 text-white" : "bg-cloud text-ink-900 hover:bg-cloud/70"
              }`}
            >
              {e || "Todos"}
            </button>
          ))}
        </div>
        <Link
          href="/produccion/precosteo/nuevo"
          className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700"
        >
          <Plus className="h-4 w-4" /> Nueva referencia
        </Link>
      </div>

      <Card>
        <CardContent className="p-0">
          {rows.length === 0 ? (
            <p className="p-8 text-center text-sm text-graphite">
              Sin precosteos registrados. Empieza con "Nueva referencia".
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.7rem] uppercase tracking-[0.12em] text-graphite">
                  <th className="px-4 py-3">Código</th>
                  <th className="px-4 py-3">Nombre</th>
                  <th className="px-4 py-3">Tela</th>
                  <th className="px-4 py-3 text-right">Costo c/IVA</th>
                  <th className="px-4 py-3 text-right">Precio sug.</th>
                  <th className="px-4 py-3">Estado</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-b border-border hover:bg-cloud/50">
                    <td className="px-4 py-3 tabular font-medium">
                      <Link href={`/produccion/precosteo/${r.id}`} className="text-navy-600 hover:underline">
                        {r.codigo_referencia}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{r.nombre}</td>
                    <td className="px-4 py-3 text-graphite">{r.tela || "—"}</td>
                    <td className="px-4 py-3 text-right tabular">${r.costo_total_con_iva?.toLocaleString("es-CO", { maximumFractionDigits: 0 }) || "—"}</td>
                    <td className="px-4 py-3 text-right tabular">
                      {r.precio_sugerido_venta ? `$${r.precio_sugerido_venta.toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}
                    </td>
                    <td className="px-4 py-3">
                      {r.bloqueada ? (
                        <Badge tone="normal"><Lock className="inline h-2.5 w-2.5 mr-1" /> Autorizada</Badge>
                      ) : (
                        <Badge tone="pendiente">Borrador</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
