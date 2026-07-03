"use client";

/**
 * Listado de remisiones a proveedores.
 * - Confección: el confeccionista RECOGE los insumos → estado "recogida".
 * - Terminación: MALE'DENIM DESPACHA los insumos → estado "despachada".
 * (En BD ambos usan el mismo estado 'recogida'; la etiqueta cambia por tipo.)
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Plus, FileText } from "lucide-react";

interface Remision {
  id: string;
  consecutivo: string;
  fecha_recogida: string;
  estado: string;
  tipo?: string; // 'confeccion' | 'terminacion'
  created_at: string;
  confeccionista?: { nombre: string };
}

function etiquetaEstado(r: Remision): string {
  const esTerm = r.tipo === "terminacion";
  if (r.estado === "recogida") return esTerm ? "Despachada" : "Recogida";
  return esTerm ? "Por despachar" : "Por recoger";
}

export default function RemisionesPage() {
  const q = useQuery<{ remisiones: Remision[] }>({
    queryKey: ["produccion", "remisiones"],
    queryFn: () => api.get("/api/produccion/remisiones"),
  });

  if (q.isLoading) return <LoadingState label="Cargando remisiones…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const lista = q.data?.remisiones || [];

  return (
    <PageShell title="Remisiones" subtitle="Entregas a confección y terminación">
      <div className="flex items-center justify-between">
        <p className="text-xs text-graphite">{lista.length} remisión(es)</p>
        <Link href="/produccion/remisiones/nueva"
          className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700">
          <Plus className="h-3.5 w-3.5" /> Nueva remisión
        </Link>
      </div>

      {lista.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center">
            <FileText className="mx-auto h-8 w-8 text-graphite" />
            <p className="mt-3 text-sm text-graphite">Aún no hay remisiones. Crea la primera.</p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Consecutivo</th>
                  <th className="px-4 py-2">Tipo</th>
                  <th className="px-4 py-2">Proveedor</th>
                  <th className="px-4 py-2">Fecha</th>
                  <th className="px-4 py-2">Creada</th>
                  <th className="px-4 py-2">Estado</th>
                </tr>
              </thead>
              <tbody>
                {lista.map((r) => {
                  const esTerm = r.tipo === "terminacion";
                  return (
                    <tr key={r.id} className="border-b border-border/40 hover:bg-cloud/40">
                      <td className="px-4 py-2 font-semibold tabular text-navy-600">
                        <Link href={`/produccion/remisiones/${r.id}`} className="hover:underline">
                          {r.consecutivo}
                        </Link>
                      </td>
                      <td className="px-4 py-2">
                        <span className={`rounded-sm px-1.5 py-0.5 text-[0.55rem] font-bold uppercase tracking-widest ${esTerm ? "bg-teal/10 text-teal" : "bg-navy-600/10 text-navy-600"}`}>
                          {esTerm ? "Terminación" : "Confección"}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-ink-900">{r.confeccionista?.nombre || "—"}</td>
                      <td className="px-4 py-2 tabular">{r.fecha_recogida}</td>
                      <td className="px-4 py-2 text-graphite tabular text-[0.65rem]">
                        {new Date(r.created_at).toLocaleDateString("es-CO")}
                      </td>
                      <td className="px-4 py-2">
                        <Badge tone={r.estado === "recogida" ? "normal" : "pendiente"}>
                          {etiquetaEstado(r)}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </PageShell>
  );
}
