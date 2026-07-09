"use client";

/**
 * Detalle de precosteo. Si es borrador, permite firmar (con permiso) o subir foto.
 * Si está bloqueada, muestra inmutable con badge "Autorizada por X".
 */
import { useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Lock, Camera, CheckCircle, Loader2, AlertCircle } from "lucide-react";

interface Item {
  id: string;
  categoria: string;
  item: string;
  valor_unitario: number;
  cantidad: number;
  iva: number;
  total_sin_iva: number;
  total_con_iva: number;
  orden: number;
}
interface Precosteo {
  id: string;
  codigo_referencia: string;
  nombre: string;
  tela?: string;
  color?: string;
  foto_url?: string;
  iva_pct: number;
  margen: number;
  costo_total_sin_iva: number;
  costo_total_con_iva: number;
  precio_sugerido_venta?: number;
  estado: string;
  bloqueada: boolean;
  autorizada_por?: string;
  fecha_autorizacion?: string;
  es_muestra_diseno?: boolean;
  items: Item[];
}

export default function PrecosteoDetallePage() {
  const params = useParams();
  const id = params?.id as string;
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const q = useQuery<Precosteo>({
    queryKey: ["produccion", "precosteo", id],
    queryFn: () => api.get(`/api/produccion/precosteo/${id}`),
    enabled: !!id,
  });

  const firmarMut = useMutation({
    mutationFn: () => api.post(`/api/produccion/precosteo/${id}/firmar`),
    onSuccess: () => {
      setMsg("Firmado y bloqueado.");
      setErr("");
      qc.invalidateQueries({ queryKey: ["produccion", "precosteo", id] });
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  async function subirFoto(f: File) {
    setErr("");
    try {
      const fd = new FormData();
      fd.append("file", f);
      const token = getToken();
      const res = await fetch(`${API_BASE}/api/produccion/precosteo/${id}/foto`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (!res.ok) throw new Error((await res.text()).slice(0, 150));
      setMsg("Foto subida.");
      qc.invalidateQueries({ queryKey: ["produccion", "precosteo", id] });
    } catch (e: any) {
      setErr(e.message || "Error subiendo foto");
    }
  }

  if (q.isLoading) return <LoadingState label="Cargando precosteo…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const p = q.data;

  return (
    <PageShell title={`${p.codigo_referencia} · ${p.nombre}`} subtitle={p.tela || "—"}>
      <div className="flex items-center justify-between">
        <Link href="/produccion/precosteo" className="inline-flex items-center gap-1 text-xs text-graphite hover:text-ink-900">
          <ArrowLeft className="h-3.5 w-3.5" /> Volver a precosteos
        </Link>
        <div className="flex items-center gap-2">
          {p.es_muestra_diseno && (
            <Badge tone="info">Muestra de diseño</Badge>
          )}
          {p.bloqueada ? (
            <Badge tone="normal"><Lock className="inline h-2.5 w-2.5 mr-1" /> Autorizada · {p.autorizada_por}</Badge>
          ) : (
            <Badge tone="pendiente">Borrador · editable</Badge>
          )}
        </div>
      </div>

      {msg && <div className="rounded-sm border border-teal/40 bg-teal/5 px-3 py-2 text-xs text-teal flex items-center gap-2"><CheckCircle className="h-3.5 w-3.5" /> {msg}</div>}
      {err && <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2"><AlertCircle className="h-3.5 w-3.5" /> {err}</div>}

      <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-4">
        {/* Foto + acciones */}
        <Card>
          <CardContent className="p-3">
            {p.foto_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={p.foto_url} alt={p.codigo_referencia} className="w-full rounded-sm border border-border" />
            ) : (
              <div className="aspect-square w-full flex items-center justify-center bg-cloud rounded-sm border border-border text-graphite">
                <Camera className="h-8 w-8" />
              </div>
            )}
            {!p.bloqueada && (
              <>
                <input ref={fileRef} type="file" accept="image/*" className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) subirFoto(f); }} />
                <button onClick={() => fileRef.current?.click()}
                  className="mt-2 w-full inline-flex items-center justify-center gap-2 rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest hover:bg-cloud">
                  <Camera className="h-3.5 w-3.5" /> {p.foto_url ? "Cambiar foto" : "Subir foto"}
                </button>
              </>
            )}
          </CardContent>
        </Card>

        {/* KPIs */}
        <Card>
          <CardContent className="p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
            <Kpi label="Costo sin IVA"     value={`$${p.costo_total_sin_iva.toLocaleString("es-CO", { maximumFractionDigits: 0 })}`} />
            <Kpi label="Costo con IVA"     value={`$${p.costo_total_con_iva.toLocaleString("es-CO", { maximumFractionDigits: 0 })}`} />
            <Kpi label={`Margen ${p.margen}%`} value={p.precio_sugerido_venta ? `$${p.precio_sugerido_venta.toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"} />
            <Kpi label="Estado"            value={p.estado.toUpperCase()} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border">
            <p className="section-label">Líneas ({p.items.length})</p>
          </div>
          <table className="w-full text-xs">
            <thead className="bg-cloud/60 border-b border-border">
              <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                <th className="px-3 py-2">Categoría</th>
                <th className="px-3 py-2">Item</th>
                <th className="px-3 py-2 text-right">Valor unit.</th>
                <th className="px-3 py-2 text-right">Cantidad</th>
                <th className="px-3 py-2 text-right">IVA</th>
                <th className="px-3 py-2 text-right">Total sin IVA</th>
                <th className="px-3 py-2 text-right">Total con IVA</th>
              </tr>
            </thead>
            <tbody>
              {p.items.map((it) => (
                <tr key={it.id} className="border-b border-border/40 hover:bg-cloud/50">
                  <td className="px-3 py-1.5 text-graphite">{it.categoria}</td>
                  <td className="px-3 py-1.5 text-ink-900">{it.item}</td>
                  <td className="px-3 py-1.5 text-right tabular">${it.valor_unitario.toLocaleString("es-CO", { maximumFractionDigits: 0 })}</td>
                  <td className="px-3 py-1.5 text-right tabular">{it.cantidad}</td>
                  <td className="px-3 py-1.5 text-right tabular">${it.iva.toLocaleString("es-CO", { maximumFractionDigits: 0 })}</td>
                  <td className="px-3 py-1.5 text-right tabular">${it.total_sin_iva.toLocaleString("es-CO", { maximumFractionDigits: 0 })}</td>
                  <td className="px-3 py-1.5 text-right tabular font-medium">${it.total_con_iva.toLocaleString("es-CO", { maximumFractionDigits: 0 })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {!p.bloqueada && (
        <div className="flex justify-end">
          <button onClick={() => firmarMut.mutate()} disabled={firmarMut.isPending}
            className="inline-flex items-center gap-2 rounded-sm bg-teal px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
            {firmarMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
            Firmar y bloquear
          </button>
        </div>
      )}
    </PageShell>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.7rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className="mt-1 font-display text-xl text-ink-900 tabular">{value}</p>
    </div>
  );
}
