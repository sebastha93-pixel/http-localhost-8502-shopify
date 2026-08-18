"use client";

/**
 * Vista pública para la LAVANDERÍA — NO requiere login.
 *
 * POR QUÉ EXISTE (2026-08-18). La pregunta era cómo traer a la app la
 * información que hoy vive en un grupo de WhatsApp: estado del lote, remisión
 * de lavandería. La API oficial de grupos de Meta no sirve para el grupo que ya
 * existe (exige Official Business Account, tope de 8 participantes, y solo
 * funciona con grupos creados por la propia API). Entonces el dato no se
 * extrae del chat: entra por acá, igual que el de confección y terminación.
 *
 * La ganancia real no es evitar la API. Es que un "ya salió" en el chat hay que
 * interpretarlo, mientras que acá cada hecho queda con lote, autor y hora.
 *
 * Se usa `fetch` directo contra API_BASE y NO el cliente de lib/api, igual que
 * las otras vistas públicas: ese cliente manda al login ante un 401, que es lo
 * último que quiere alguien que nunca tuvo sesión.
 */
import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE } from "@/lib/api";
import { fmtFecha } from "@/lib/utils";
import { CheckCircle, Loader2, Upload, Droplets, Truck, AlertCircle } from "lucide-react";

interface LoteLav {
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
  lavanderia_nombre?: string;
  etapa: string;
  recibido_at?: string;
  entregado_at?: string;
  cantidad_recibida?: number;
  cantidad_entregada?: number;
  fecha_estimada?: string;
  tiene_remision: boolean;
}

async function fetchJSON(url: string, opts?: RequestInit) {
  const r = await fetch(url, opts);
  const text = await r.text();
  if (!r.ok) throw new Error(text.slice(0, 200) || `HTTP ${r.status}`);
  return text ? JSON.parse(text) : {};
}

export default function LavanderiaPublicaPage() {
  const params = useParams();
  const token = params?.token as string;
  const qc = useQueryClient();

  const [cantidad, setCantidad] = useState("");
  const [nota, setNota] = useState("");
  const [fechaEstimada, setFechaEstimada] = useState("");
  const [error, setError] = useState("");
  const [subiendo, setSubiendo] = useState(false);

  const q = useQuery<LoteLav>({
    queryKey: ["lavanderia-publica", token],
    queryFn: () => fetchJSON(`${API_BASE}/api/publico/lavanderia/${token}`),
    enabled: !!token,
    retry: false,
  });

  const registrar = useMutation({
    mutationFn: (accion: "recibi" | "entregue") =>
      fetchJSON(`${API_BASE}/api/publico/lavanderia/${token}/registrar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accion,
          cantidad: cantidad ? Number(cantidad) : null,
          nota,
          fecha_estimada: accion === "recibi" ? fechaEstimada : "",
        }),
      }),
    onSuccess: () => {
      setCantidad(""); setNota(""); setFechaEstimada(""); setError("");
      qc.invalidateQueries({ queryKey: ["lavanderia-publica", token] });
    },
    onError: (e: Error) => setError(e.message),
  });

  async function subirRemision(archivo: File) {
    setError(""); setSubiendo(true);
    try {
      const fd = new FormData();
      fd.append("archivo", archivo);
      await fetchJSON(`${API_BASE}/api/publico/lavanderia/${token}/remision`,
                      { method: "POST", body: fd });
      qc.invalidateQueries({ queryKey: ["lavanderia-publica", token] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubiendo(false);
    }
  }

  if (q.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cream">
        <Loader2 className="h-6 w-6 animate-spin text-graphite" />
      </div>
    );
  }

  if (q.isError || !q.data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cream p-6">
        <p className="max-w-sm text-center text-sm text-graphite">
          Este enlace no corresponde a ningún lote. Pídele uno nuevo a MALE&apos;DENIM.
        </p>
      </div>
    );
  }

  const d = q.data;
  const tallas = d.unidades_cortadas && Object.keys(d.unidades_cortadas).length
    ? d.unidades_cortadas : d.curva;

  return (
    <div className="min-h-screen bg-cream pb-16">
      <header className="bg-ink px-5 py-4">
        <p className="text-[0.95rem] font-extrabold tracking-[0.3em] text-white leading-none">
          MALE&apos;DENIM
        </p>
        <p className="mt-1 text-[0.62rem] font-semibold tracking-[0.35em] text-steel/70 uppercase">
          Lavandería
        </p>
      </header>

      <main className="mx-auto max-w-md space-y-4 p-5">
        {/* Qué lote es. Va primero y grande: es lo que la persona necesita
            confirmar antes de tocar cualquier botón. */}
        <section className="rounded-sm border border-border bg-card p-4">
          <p className="text-[0.68rem] font-bold uppercase tracking-wider text-graphite">
            Lote
          </p>
          <p className="text-2xl font-extrabold text-ink">{d.consecutivo}</p>
          <p className="mt-1 text-sm font-semibold text-ink">
            {d.referencia_codigo} · {d.referencia_nombre}
          </p>
          <p className="text-xs text-graphite">
            {[d.tela, d.color].filter(Boolean).join(" · ")}
            {d.referencia_lote ? ` · ${d.referencia_lote}` : ""}
          </p>
          {d.foto_url && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img src={d.foto_url} alt={d.referencia_nombre}
                 className="mt-3 max-h-52 w-full rounded-sm object-contain" />
          )}
          <p className="mt-3 text-sm">
            <span className="font-bold text-ink">{d.total_unidades}</span>
            <span className="text-graphite"> unidades según corte</span>
          </p>
          {tallas && Object.keys(tallas).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(tallas).map(([t, n]) => (
                <span key={t} className="rounded-sm bg-cream px-2 py-0.5 text-[0.7rem] text-ink">
                  {t}: <strong>{n}</strong>
                </span>
              ))}
            </div>
          )}
        </section>

        {error && (
          <p className="flex items-start gap-2 rounded-sm border border-crimson/30 bg-crimson/10 px-3 py-2 text-sm text-crimson">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            {error}
          </p>
        )}

        {/* PASO 1 · Recibí */}
        <section className="rounded-sm border border-border bg-card p-4">
          <p className="flex items-center gap-2 text-sm font-bold text-ink">
            <Droplets className="h-4 w-4" /> 1 · Recibí el lote
          </p>
          {d.recibido_at ? (
            <p className="mt-2 flex items-center gap-1.5 text-sm text-teal">
              <CheckCircle className="h-4 w-4" />
              Recibido {fmtFecha(d.recibido_at)}
              {d.cantidad_recibida != null && ` · ${d.cantidad_recibida} und`}
            </p>
          ) : (
            <div className="mt-3 space-y-3">
              <div>
                <label htmlFor="cant-r" className="block text-[0.68rem] font-bold uppercase tracking-wider text-graphite mb-1">
                  ¿Cuántas unidades recibiste?
                </label>
                <input id="cant-r" type="number" inputMode="numeric" min={0}
                       value={cantidad} onChange={(e) => setCantidad(e.target.value)}
                       placeholder={String(d.total_unidades)}
                       className="w-full rounded-sm border border-border bg-white px-3 py-2.5 text-base text-ink" />
                <p className="mt-1 text-[0.68rem] text-graphite">
                  Si es distinto a {d.total_unidades}, escríbelo tal cual llegó y cuéntalo en la novedad.
                </p>
              </div>
              <div>
                <label htmlFor="fecha-e" className="block text-[0.68rem] font-bold uppercase tracking-wider text-graphite mb-1">
                  ¿Para cuándo lo entregas?
                </label>
                <input id="fecha-e" type="date" value={fechaEstimada}
                       onChange={(e) => setFechaEstimada(e.target.value)}
                       className="w-full rounded-sm border border-border bg-white px-3 py-2.5 text-base text-ink" />
              </div>
              <div>
                <label htmlFor="nota-r" className="block text-[0.68rem] font-bold uppercase tracking-wider text-graphite mb-1">
                  Novedad (opcional)
                </label>
                <textarea id="nota-r" rows={2} value={nota}
                          onChange={(e) => setNota(e.target.value)}
                          placeholder="Manchas, faltantes, algo que reprocesar…"
                          className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm text-ink" />
              </div>
              <button type="button" disabled={registrar.isPending}
                      onClick={() => registrar.mutate("recibi")}
                      className="w-full rounded-sm bg-ink py-3 text-sm font-bold uppercase tracking-wider text-white disabled:opacity-50">
                {registrar.isPending ? "Guardando…" : "Confirmar que recibí"}
              </button>
            </div>
          )}
        </section>

        {/* PASO 2 · Remisión */}
        <section className="rounded-sm border border-border bg-card p-4">
          <p className="flex items-center gap-2 text-sm font-bold text-ink">
            <Upload className="h-4 w-4" /> 2 · Remisión de lavandería
          </p>
          {d.tiene_remision ? (
            <p className="mt-2 flex items-center gap-1.5 text-sm text-teal">
              <CheckCircle className="h-4 w-4" /> Remisión recibida
            </p>
          ) : (
            <>
              <p className="mt-1 text-xs text-graphite">
                Tómale una foto a la remisión, o sube el PDF.
              </p>
              <label className="mt-3 flex cursor-pointer items-center justify-center gap-2 rounded-sm border border-dashed border-border bg-cream py-4 text-sm font-semibold text-ink">
                {subiendo ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {subiendo ? "Subiendo…" : "Tomar foto o elegir archivo"}
                <input type="file" accept="image/*,application/pdf" className="hidden"
                       disabled={subiendo}
                       onChange={(e) => {
                         const f = e.target.files?.[0];
                         if (f) subirRemision(f);
                       }} />
              </label>
            </>
          )}
        </section>

        {/* PASO 3 · Entregué. Bloqueado hasta que confirme el recibo: entregar
            algo que nunca dijo haber recibido deja un hueco en la historia. */}
        <section className="rounded-sm border border-border bg-card p-4">
          <p className="flex items-center gap-2 text-sm font-bold text-ink">
            <Truck className="h-4 w-4" /> 3 · Entregué el lote
          </p>
          {d.entregado_at ? (
            <p className="mt-2 flex items-center gap-1.5 text-sm text-teal">
              <CheckCircle className="h-4 w-4" />
              Entregado {fmtFecha(d.entregado_at)}
              {d.cantidad_entregada != null && ` · ${d.cantidad_entregada} und`}
            </p>
          ) : !d.recibido_at ? (
            <p className="mt-2 text-xs text-graphite">
              Primero confirma que recibiste el lote.
            </p>
          ) : (
            <div className="mt-3 space-y-3">
              <div>
                <label htmlFor="cant-e" className="block text-[0.68rem] font-bold uppercase tracking-wider text-graphite mb-1">
                  ¿Cuántas unidades entregaste?
                </label>
                <input id="cant-e" type="number" inputMode="numeric" min={0}
                       value={cantidad} onChange={(e) => setCantidad(e.target.value)}
                       placeholder={String(d.cantidad_recibida ?? d.total_unidades)}
                       className="w-full rounded-sm border border-border bg-white px-3 py-2.5 text-base text-ink" />
              </div>
              <div>
                <label htmlFor="nota-e" className="block text-[0.68rem] font-bold uppercase tracking-wider text-graphite mb-1">
                  Novedad (opcional)
                </label>
                <textarea id="nota-e" rows={2} value={nota}
                          onChange={(e) => setNota(e.target.value)}
                          className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm text-ink" />
              </div>
              <button type="button" disabled={registrar.isPending}
                      onClick={() => registrar.mutate("entregue")}
                      className="w-full rounded-sm bg-ink py-3 text-sm font-bold uppercase tracking-wider text-white disabled:opacity-50">
                {registrar.isPending ? "Guardando…" : "Confirmar que entregué"}
              </button>
            </div>
          )}
          {d.fecha_estimada && !d.entregado_at && (
            <p className="mt-2 text-[0.7rem] text-graphite">
              Prometido para {fmtFecha(d.fecha_estimada)}
            </p>
          )}
        </section>
      </main>
    </div>
  );
}
