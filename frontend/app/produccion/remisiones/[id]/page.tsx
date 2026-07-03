"use client";

/**
 * Detalle de remisión a confeccionista.
 */
import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TablaInsumosSeparar } from "@/components/tabla-insumos-separar";
import { ArrowLeft, Truck, Loader2, MessageCircle, Copy } from "lucide-react";

interface Item {
  id: string;
  orden_corte_id: string;
  orden_corte?: {
    consecutivo: string;
    referencia_lote?: string;
    cantidad_programada?: number;
    unidades_cortadas?: Record<string, number>;
    fecha_entrega?: string;
    referencia?: { codigo_referencia: string; nombre: string; tela?: string };
  };
}

interface Remision {
  id: string;
  consecutivo: string;
  fecha_recogida: string;
  estado: string;
  tipo?: string; // 'confeccion' | 'terminacion'
  created_at: string;
  confeccionista?: { nombre: string; telefono?: string; direccion?: string };
  items: Item[];
}

export default function RemisionDetallePage() {
  const params = useParams();
  const id = params?.id as string;
  const qc = useQueryClient();

  const q = useQuery<Remision>({
    queryKey: ["produccion", "remision", id],
    queryFn: () => api.get(`/api/produccion/remisiones/${id}`),
    enabled: !!id,
  });

  const recogida = useMutation({
    mutationFn: () => api.post(`/api/produccion/remisiones/${id}/recogida`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["produccion", "remision", id] }),
  });

  if (q.isLoading) return <LoadingState label="Cargando remisión…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const rem = q.data;
  const yaRecogida = rem.estado === "recogida";

  const totalUnidades = (rem.items || []).reduce((s, it) => {
    const u = it.orden_corte?.unidades_cortadas || {};
    return s + Object.values(u).reduce((x, y) => x + (Number(y) || 0), 0);
  }, 0);

  return (
    <PageShell title={rem.consecutivo} subtitle={rem.confeccionista?.nombre || "—"}>
      <div className="flex items-center justify-between">
        <Link href="/produccion/remisiones" className="inline-flex items-center gap-1 text-xs text-graphite hover:text-ink-900">
          <ArrowLeft className="h-3.5 w-3.5" /> Volver a remisiones
        </Link>
        <Badge tone={yaRecogida ? "normal" : "pendiente"}>{rem.estado}</Badge>
      </div>

      {/* Info general */}
      <Card>
        <CardContent className="p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
          <Info label="Confeccionista"   value={rem.confeccionista?.nombre || "—"} />
          <Info label="Teléfono"         value={rem.confeccionista?.telefono || "—"} />
          <Info label="Dirección"        value={rem.confeccionista?.direccion || "—"} />
          <Info label="Fecha recogida"   value={rem.fecha_recogida} />
          <Info label="Órdenes"          value={String(rem.items?.length || 0)} />
          <Info label="Total unidades"   value={String(totalUnidades)} />
        </CardContent>
      </Card>

      {/* Items */}
      <Card>
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border">
            <p className="section-label">Órdenes de corte entregadas</p>
          </div>
          {(rem.items || []).length === 0 ? (
            <div className="p-8 text-center text-xs text-graphite">Sin órdenes.</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Consecutivo</th>
                  <th className="px-4 py-2">Referencia</th>
                  <th className="px-4 py-2">Lote</th>
                  <th className="px-4 py-2 text-right">Cantidad</th>
                  <th className="px-4 py-2">Entrega corte</th>
                </tr>
              </thead>
              <tbody>
                {(rem.items || []).map((it) => {
                  const totalOC = Object.values(it.orden_corte?.unidades_cortadas || {})
                    .reduce((x, y) => x + (Number(y) || 0), 0);
                  return (
                    <tr key={it.id} className="border-b border-border/40 hover:bg-cloud/40">
                      <td className="px-4 py-2 font-semibold tabular text-navy-600">
                        <Link href={`/produccion/corte/${it.orden_corte_id}`} className="hover:underline">
                          {it.orden_corte?.consecutivo || "—"}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-ink-900">
                        {it.orden_corte?.referencia?.codigo_referencia || "—"}
                        <div className="text-[0.6rem] text-graphite">
                          {it.orden_corte?.referencia?.nombre}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-graphite">{it.orden_corte?.referencia_lote || "—"}</td>
                      <td className="px-4 py-2 text-right tabular">
                        {totalOC || it.orden_corte?.cantidad_programada || "—"}
                      </td>
                      <td className="px-4 py-2 text-graphite text-[0.65rem] tabular">
                        {it.orden_corte?.fecha_entrega || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {!yaRecogida && (
        <div className="flex justify-end">
          <button onClick={() => recogida.mutate()} disabled={recogida.isPending}
            className="inline-flex items-center gap-2 rounded-sm bg-teal px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
            {recogida.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Truck className="h-4 w-4" />}
            Marcar como recogida
          </button>
        </div>
      )}

      {/* Envío por WhatsApp por cada lote */}
      <Card>
        <CardContent className="p-5 space-y-3">
          <p className="section-label">
            {rem.tipo === "terminacion" ? "Ficha para terminación" : "Ficha para el confeccionista"}
          </p>
          <p className="text-xs text-graphite">
            Para cada lote hay un link público con la ficha técnica, precio, cantidad e insumos.
            Configura el precio + fecha entrega y envía el link por WhatsApp.
          </p>
          <div className="space-y-3">
            {(rem.items || []).map((it) => (
              <RutaCard key={it.id} ordenCorteId={it.orden_corte_id}
                consecutivo={it.orden_corte?.consecutivo || ""}
                tipo={rem.tipo === "terminacion" ? "terminacion" : "confeccion"}
                telefono={rem.confeccionista?.telefono}
                confeccionistaNombre={rem.confeccionista?.nombre} />
            ))}
          </div>
        </CardContent>
      </Card>
    </PageShell>
  );
}

interface Ruta {
  id: string;
  token_publico: string;
  token_publico_terminacion?: string;
  precio_confeccion?: number;
  precio_terminacion?: number;
  fecha_entrega_confeccion?: string;
  terminacion_id?: string;
  terminacion?: { nombre?: string; telefono?: string };
  etapa: string;
  aceptado_at?: string;
}

function RutaCard({ ordenCorteId, consecutivo, tipo, telefono, confeccionistaNombre }: {
  ordenCorteId: string;
  consecutivo: string;
  tipo: "confeccion" | "terminacion";
  telefono?: string;
  confeccionistaNombre?: string;
}) {
  const esTerminacion = tipo === "terminacion";
  const qc = useQueryClient();
  const [fecha, setFecha] = useState("");
  const [copiado, setCopiado] = useState(false);

  const q = useQuery<Ruta>({
    queryKey: ["ruta", ordenCorteId],
    queryFn: () => api.get(`/api/produccion/rutas/por-corte/${ordenCorteId}`),
    enabled: !!ordenCorteId,
    retry: false,
  });

  // La tabla de insumos vive en el componente compartido <TablaInsumosSeparar />.

  const guardar = useMutation({
    mutationFn: () => {
      if (!q.data) return Promise.reject(new Error("ruta no cargada"));
      // El precio viene del precosteo (bloqueado) — solo se edita la fecha.
      return api.patch(`/api/produccion/rutas/${q.data.id}`, {
        fecha_entrega_confeccion: fecha || null,
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ruta", ordenCorteId] }),
  });

  if (q.isLoading) {
    return <div className="rounded-sm border border-border bg-cloud/20 p-3 text-xs text-graphite">Cargando ficha…</div>;
  }
  if (!q.data) {
    return (
      <div className="rounded-sm border border-terracotta/40 bg-terracotta/5 p-3 text-xs text-terracotta">
        Este lote no tiene ficha creada aún. Corre la migración de hoja_ruta_lote en Supabase y refresca.
      </div>
    );
  }

  const r = q.data;
  const publicoBase = typeof window !== "undefined" ? window.location.origin : "";
  const linkPublico = esTerminacion
    ? `${publicoBase}/terminacion/${r.token_publico_terminacion || ""}`
    : `${publicoBase}/lote/${r.token_publico}`;

  const mensajeWA = `Hola${confeccionistaNombre ? " " + confeccionistaNombre : ""}, te comparto la ficha del lote *${consecutivo}* de MALE'DENIM. Ahí ves referencia, cantidad, insumos y valor acordado. Cuando abras confirma con "Aceptar lote":\n\n${linkPublico}`;
  const telClean = (telefono || "").replace(/\D/g, "");
  const telFinal = telClean.startsWith("57") ? telClean : telClean ? `57${telClean}` : "";
  const waUrl = telFinal
    ? `https://wa.me/${telFinal}?text=${encodeURIComponent(mensajeWA)}`
    : `https://wa.me/?text=${encodeURIComponent(mensajeWA)}`;

  async function copiarLink() {
    try {
      await navigator.clipboard.writeText(linkPublico);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch { /* noop */ }
  }

  return (
    <div className="rounded-sm border border-border bg-white p-3 space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-semibold text-ink-900 tabular text-sm">{consecutivo}</p>
        <Badge tone={r.etapa === "asignado" ? "pendiente" : "normal"}>{r.etapa}</Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <div>
          <label className="mb-1 block text-[0.6rem] uppercase tracking-widest text-graphite">
            {esTerminacion ? "Precio terminación (del precosteo)" : "Precio confección (del precosteo)"}
          </label>
          <div className="w-full rounded-sm border border-border bg-cloud/40 px-2 py-1.5 text-xs text-right tabular font-semibold text-ink-900">
            {(() => {
              const p = esTerminacion ? r.precio_terminacion : r.precio_confeccion;
              return p != null
                ? `$${Number(p).toLocaleString("es-CO")}`
                : "— sin precio en el precosteo";
            })()}
          </div>
        </div>
        {!esTerminacion && (
          <div>
            <label className="mb-1 block text-[0.6rem] uppercase tracking-widest text-graphite">Fecha entrega</label>
            <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)}
              placeholder={r.fecha_entrega_confeccion || ""}
              className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs" />
          </div>
        )}
      </div>

      {/* Insumos que hay que SEPARAR físicamente antes de enviar */}
      <TablaInsumosSeparar ordenCorteId={ordenCorteId} tipo={tipo} />

      <div className="flex flex-wrap items-center gap-2">
        {!esTerminacion && (
          <button onClick={() => guardar.mutate()} disabled={guardar.isPending || !fecha}
            className="inline-flex items-center gap-1 rounded-sm border border-border bg-cloud px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud/80 disabled:opacity-40">
            {guardar.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            Guardar fecha
          </button>
        )}
        {esTerminacion && !r.token_publico_terminacion ? (
          <p className="text-[0.65rem] text-terracotta">
            Este lote aún no tiene link de terminación. Corre la migración de proveedores en Supabase y refresca.
          </p>
        ) : (
          <>
            <a href={waUrl} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-sm bg-[#25D366] px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:opacity-90">
              <MessageCircle className="h-3 w-3" /> Enviar por WhatsApp
            </a>
            <button type="button" onClick={copiarLink}
              className="inline-flex items-center gap-1 rounded-sm border border-border bg-white px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-graphite hover:bg-cloud">
              <Copy className="h-3 w-3" /> {copiado ? "Copiado" : "Copiar link"}
            </button>
            <a href={linkPublico} target="_blank" rel="noopener noreferrer"
              className="text-[0.65rem] text-navy-600 hover:underline">Ver ficha</a>
          </>
        )}
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.6rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className="mt-1 text-sm text-ink-900">{value}</p>
    </div>
  );
}
