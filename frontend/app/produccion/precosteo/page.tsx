"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Plus, Lock, Sheet, Loader2, CheckCircle } from "lucide-react";

interface Ref {
  id: string;
  codigo_referencia: string;
  nombre: string;
  tela?: string;
  color?: string;
  costo_total_sin_iva?: number;
  costo_total_con_iva: number;
  iva_pct?: number;
  precio_sugerido_venta?: number;
  precio_venta_final?: number | null;
  estado: string;
  bloqueada: boolean;
  autorizada_por?: string;
  fecha_autorizacion?: string;
  created_at?: string;
}

// Margen % = (precio_sin_iva − costo_sin_iva) / precio_sin_iva. El precio_venta_final
// es PVP con IVA → se le quita el IVA antes de comparar. Devuelve null si no hay precio.
function margenDe(r: Ref): number | null {
  const pvp = Number(r.precio_venta_final || 0);
  if (pvp <= 0) return null;
  const iva = Number(r.iva_pct || 19);
  const precioSin = pvp / (1 + iva / 100);
  const costoSin = Number(r.costo_total_sin_iva || 0);
  if (precioSin <= 0) return null;
  return ((precioSin - costoSin) / precioSin) * 100;
}

export default function PrecosteoListPage() {
  const [estado, setEstado] = useState<string>("");

  const [syncMsg, setSyncMsg] = useState("");

  const q = useQuery<{ precosteos: Ref[] }>({
    queryKey: ["produccion", "precosteo", "list", estado],
    queryFn: () => api.get(`/api/produccion/precosteo${estado ? `?estado=${estado}` : ""}`),
  });

  // ¿Está configurada la sincronización a Google Sheet? (muestra el botón)
  const driveQ = useQuery<{ configurado: boolean }>({
    queryKey: ["produccion", "precosteo", "drive-estado"],
    queryFn: () => api.get("/api/produccion/precosteo-drive/estado"),
    staleTime: 5 * 60_000,
  });

  const syncMut = useMutation({
    mutationFn: () => api.post<{ ok: boolean; sincronizados?: number; motivo?: string }>("/api/produccion/precosteo-drive/sync"),
    onSuccess: (d) => setSyncMsg(d.ok ? `✓ ${d.sincronizados} referencias sincronizadas a la Sheet.` : `No se pudo: ${d.motivo}`),
    onError: (e: Error) => setSyncMsg(`Error: ${e.message}`),
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
        <div className="flex items-center gap-2">
          {driveQ.data?.configurado && (
            <button
              onClick={() => { setSyncMsg(""); syncMut.mutate(); }}
              disabled={syncMut.isPending}
              title="Reescribe la Google Sheet con todas las referencias (el día a día se sincroniza solo al guardar)"
              className="inline-flex items-center gap-2 rounded-sm border border-border bg-card px-4 py-2 text-sm font-semibold uppercase tracking-[0.12em] text-ink-900 hover:bg-cloud disabled:opacity-40"
            >
              {syncMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sheet className="h-4 w-4" />}
              Sincronizar a Drive
            </button>
          )}
          <Link
            href="/produccion/precosteo/nuevo"
            className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700"
          >
            <Plus className="h-4 w-4" /> Nueva referencia
          </Link>
        </div>
      </div>
      {syncMsg && (
        <div className="rounded-sm border border-teal/40 bg-teal/5 px-3 py-2 text-xs text-teal flex items-center gap-2">
          <CheckCircle className="h-3.5 w-3.5" /> {syncMsg}
        </div>
      )}

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
                  <th className="px-4 py-3 text-right">Precio venta</th>
                  <th className="px-4 py-3 text-right">Margen</th>
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
                      {r.precio_venta_final ? `$${Number(r.precio_venta_final).toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular">
                      {(() => {
                        const m = margenDe(r);
                        if (m === null) return <span className="text-graphite">—</span>;
                        const cls = m < 0 ? "text-terracotta" : m < 50 ? "text-amber-600" : "text-teal";
                        return <span className={`font-semibold ${cls}`}>{m.toFixed(1)}%</span>;
                      })()}
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
