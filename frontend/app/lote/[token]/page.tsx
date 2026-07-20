"use client";

/**
 * Vista pública del lote para el confeccionista — NO requiere login.
 * Se llega desde el link de WhatsApp con el token en la URL.
 */
import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE } from "@/lib/api";
import { fmtFecha } from "@/lib/utils";
import { CheckCircle, Loader2, AlertCircle, Package, Scissors } from "lucide-react";

interface Insumo {
  item: string;
  total_requerido: number;
}
interface LotePublico {
  consecutivo: string;
  referencia_codigo: string;
  referencia_nombre: string;
  tela?: string;
  color?: string;
  foto_url?: string;
  referencia_lote?: string;
  curva: Record<string, number>;
  unidades_cortadas?: Record<string, number>;
  total_unidades: number;
  fecha_entrega?: string;
  confeccionista_nombre: string;
  etapa: string;
  aceptado_at?: string;
  insumos: Insumo[];
}

async function fetchJSON(url: string, opts?: RequestInit) {
  const r = await fetch(url, opts);
  const text = await r.text();
  if (!r.ok) throw new Error(text.slice(0, 200) || `HTTP ${r.status}`);
  return JSON.parse(text);
}

export default function LotePublicoPage() {
  const params = useParams();
  const token = params?.token as string;
  const qc = useQueryClient();
  const [err, setErr] = useState("");

  const q = useQuery<LotePublico>({
    queryKey: ["lote-publico", token],
    queryFn: () => fetchJSON(`${API_BASE}/api/publico/lote/${token}`),
    enabled: !!token,
  });

  const [nota, setNota] = useState("");
  const [notaMsg, setNotaMsg] = useState("");
  const guardarNota = useMutation({
    mutationFn: () => fetchJSON(`${API_BASE}/api/publico/lote/${token}/nota`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nota: nota.trim() }),
    }),
    onSuccess: () => {
      setNotaMsg("Nota enviada.");
      setNota("");
      setTimeout(() => setNotaMsg(""), 3000);
    },
    onError: (e: Error) => setErr(e.message),
  });

  const aceptar = useMutation({
    mutationFn: () => fetchJSON(`${API_BASE}/api/publico/lote/${token}/aceptar`, {
      method: "POST",
    }),
    onSuccess: () => {
      setErr("");
      qc.invalidateQueries({ queryKey: ["lote-publico", token] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  if (q.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-cloud/30">
        <Loader2 className="h-6 w-6 animate-spin text-navy-600" />
      </div>
    );
  }
  if (q.isError || !q.data) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-cloud/30 p-4">
        <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] p-4 max-w-md">
          <p className="text-sm text-terracotta">
            No pudimos cargar este lote. Verifica el link con tu contacto de MALE&apos;DENIM.
          </p>
        </div>
      </div>
    );
  }

  const l = q.data;
  const yaAceptado = l.etapa !== "asignado";
  const unidades = Object.keys(l.unidades_cortadas || {}).length
    ? l.unidades_cortadas!
    : (l.curva || {});

  return (
    <div className="min-h-screen bg-cloud/20 py-6 px-4">
      <div className="max-w-2xl mx-auto space-y-4">
        {/* Header */}
        <div className="text-center">
          <p className="font-display text-2xl font-medium tracking-[0.28em] text-ink-900">
            MALE&apos;DENIM
          </p>
          <p className="text-[0.68rem] tracking-[0.35em] uppercase text-graphite mt-1">
            Ficha de lote
          </p>
        </div>

        {/* Confeccionista + estado */}
        <div className="rounded-sm border border-border bg-white p-4 flex items-center justify-between">
          <div>
            <p className="text-[0.7rem] uppercase tracking-widest text-graphite">Confeccionista</p>
            <p className="font-semibold text-ink-900">{l.confeccionista_nombre}</p>
          </div>
          <div className="text-right">
            <p className="text-[0.7rem] uppercase tracking-widest text-graphite">Estado</p>
            <span className={`inline-block mt-1 rounded-sm px-2 py-1 text-[0.65rem] font-bold uppercase tracking-widest ${yaAceptado ? "bg-teal/10 text-teal" : "bg-navy-600/10 text-navy-600"}`}>
              {yaAceptado ? "Aceptado" : "Pendiente"}
            </span>
          </div>
        </div>

        {/* Ficha técnica */}
        <div className="rounded-sm border border-border bg-white p-4 space-y-3">
          <div className="flex items-start gap-4">
            {l.foto_url ? (
              <img src={l.foto_url} alt={l.referencia_nombre}
                className="w-28 h-28 object-cover rounded-sm border border-border" />
            ) : (
              <div className="w-28 h-28 rounded-sm bg-cloud/60 border border-border grid place-items-center">
                <Scissors className="h-8 w-8 text-graphite" />
              </div>
            )}
            <div className="flex-1 min-w-0">
              <p className="text-[0.7rem] uppercase tracking-widest text-graphite">Referencia</p>
              <p className="font-display text-lg text-ink-900">{l.referencia_codigo}</p>
              <p className="text-sm text-graphite">{l.referencia_nombre}</p>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                {l.tela && <span><span className="text-graphite">Tela:</span> <span className="text-ink-900 font-semibold">{l.tela}</span></span>}
                {l.color && <span><span className="text-graphite">Color:</span> <span className="text-ink-900 font-semibold">{l.color}</span></span>}
                {l.referencia_lote && <span><span className="text-graphite">Lote:</span> <span className="text-ink-900 font-semibold">{l.referencia_lote}</span></span>}
              </div>
              <p className="text-[0.65rem] text-graphite mt-2 tabular">Consecutivo: {l.consecutivo}</p>
            </div>
          </div>
        </div>

        {/* Fecha de entrega (sin precios — el link al confeccionista no muestra valores) */}
        <div className="rounded-sm border border-border bg-white p-4">
          <p className="text-[0.7rem] uppercase tracking-widest text-graphite">Fecha de entrega</p>
          <p className="mt-1 font-display text-2xl text-ink-900 tabular">
            {fmtFecha(l.fecha_entrega)}
          </p>
        </div>

        {/* Prendas por talla */}
        <div className="rounded-sm border border-border bg-white p-4">
          <p className="text-[0.7rem] uppercase tracking-widest text-graphite mb-2">
            Prendas que recibe · Total: <span className="text-ink-900 font-bold tabular">{l.total_unidades}</span>
          </p>
          <div className="grid grid-cols-4 md:grid-cols-7 gap-2">
            {Object.entries(unidades).map(([t, n]) => (
              <div key={t} className="rounded-sm bg-cloud/40 border border-border p-2 text-center">
                <p className="text-[0.68rem] uppercase tracking-widest text-graphite">Talla {t}</p>
                <p className="font-display text-lg text-ink-900 tabular">{n}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Insumos */}
        <div className="rounded-sm border border-border bg-white">
          <div className="p-4 border-b border-border flex items-center gap-2">
            <Package className="h-4 w-4 text-navy-600" />
            <p className="text-[0.7rem] uppercase tracking-widest text-graphite">Insumos que se le envían</p>
          </div>
          {l.insumos.length === 0 ? (
            <div className="p-4 text-xs text-graphite">Sin insumos registrados.</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-cloud/40 border-b border-border">
                <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Insumo</th>
                  <th className="px-4 py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody>
                {l.insumos.map((it, i) => (
                  <tr key={i} className="border-b border-border/40">
                    <td className="px-4 py-2 text-ink-900">{it.item}</td>
                    <td className="px-4 py-2 text-right tabular font-semibold">
                      {it.total_requerido.toLocaleString("es-CO")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Error */}
        {err && (
          <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5" /> {err}
          </div>
        )}

        {/* Nota */}
        <div className="rounded-sm border border-border bg-white p-4 space-y-2">
          <p className="text-[0.7rem] uppercase tracking-widest text-graphite">Nota para MALE&apos;DENIM (opcional)</p>
          <textarea value={nota} onChange={(e) => setNota(e.target.value)}
            rows={3} maxLength={2000}
            placeholder="Ej. faltó un cierre, cambio de fecha, dudas del lote…"
            className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm" />
          <div className="flex items-center justify-between">
            {notaMsg && <p className="text-xs text-teal">{notaMsg}</p>}
            <button onClick={() => guardarNota.mutate()} disabled={guardarNota.isPending || !nota.trim()}
              className="ml-auto inline-flex items-center gap-1 rounded-sm border border-border bg-cloud px-3 py-1.5 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud/80 disabled:opacity-40">
              {guardarNota.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Enviar nota
            </button>
          </div>
        </div>

        {/* Botón aceptar */}
        {!yaAceptado ? (
          <button onClick={() => aceptar.mutate()} disabled={aceptar.isPending}
            className="w-full inline-flex items-center justify-center gap-2 rounded-sm bg-teal px-6 py-4 text-base font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
            {aceptar.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <CheckCircle className="h-5 w-5" />}
            Aceptar lote
          </button>
        ) : (
          <div className="rounded-sm border border-teal bg-teal/[0.04] p-4 text-center">
            <CheckCircle className="mx-auto h-6 w-6 text-teal" />
            <p className="mt-2 text-sm text-ink-900 font-semibold">
              Lote aceptado {l.aceptado_at ? `el ${new Date(l.aceptado_at).toLocaleDateString("es-CO")}` : ""}
            </p>
            <p className="mt-1 text-xs text-graphite">
              Cuando termines confección, escríbele a MALE&apos;DENIM por WhatsApp
              con la remisión de lavandería.
            </p>
          </div>
        )}

        <p className="text-center text-[0.68rem] text-graphite pt-2">
          MALE&apos;DENIM · Ficha de lote confidencial
        </p>
      </div>
    </div>
  );
}
