"use client";

/**
 * Nueva orden de corte.
 * 1. Escoge un precosteo FIRMADO como referencia.
 * 2. Define tono, largo trazo, prendas x trazo, capas.
 * 3. Curva de tallas 4-6-8-10-12-14-16 (editable).
 * Al guardar → borrador. La pistola de rollos se hace en el detalle.
 */
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Save, Loader2, AlertCircle } from "lucide-react";

interface Precosteo {
  id: string;
  codigo_referencia: string;
  nombre: string;
  tela?: string;
  color?: string;
  bloqueada: boolean;
  estado: string;
  es_muestra_diseno?: boolean;
}

const TALLAS_DEFAULT: string[] = ["4", "6", "8", "10", "12", "14", "16"];

export default function NuevaOrdenCortePage() {
  const router = useRouter();

  // Precosteos disponibles para corte:
  //   - autorizados (bloqueada=true), o
  //   - borradores marcados como muestra de diseño.
  const q = useQuery<{ precosteos?: Precosteo[] } | Precosteo[]>({
    queryKey: ["produccion", "precosteos", "disponibles-corte"],
    queryFn: () => api.get("/api/produccion/precosteo?disponibles_para_corte=true"),
  });
  const precosteos = useMemo<Precosteo[]>(() => {
    if (!q.data) return [];
    const arr = Array.isArray(q.data)
      ? q.data
      : ((q.data as { precosteos?: Precosteo[] }).precosteos || []);
    return arr.filter((p) => p.bloqueada || p.es_muestra_diseno);
  }, [q.data]);

  const [referenciaId, setReferenciaId] = useState("");
  const [tono, setTono] = useState("");
  const [largoTrazo, setLargoTrazo] = useState("");
  const [prendasTrazo, setPrendasTrazo] = useState("");
  const [numCapas, setNumCapas] = useState("");
  const [responsable, setResponsable] = useState("");
  const [fechaLimite, setFechaLimite] = useState("");
  const [indicaciones, setIndicaciones] = useState("");
  const [curva, setCurva] = useState<Record<string, string>>(
    Object.fromEntries(TALLAS_DEFAULT.map((t) => [t, ""]))
  );
  const [tallaExtra, setTallaExtra] = useState("");
  const [err, setErr] = useState("");

  const mut = useMutation({
    mutationFn: () => {
      const largo = parseFloat(largoTrazo || "0");
      const prendas = parseInt(prendasTrazo || "0", 10);
      const capas = parseInt(numCapas || "0", 10);
      if (!referenciaId)         throw new Error("Selecciona una referencia (precosteo firmado)");
      if (!(largo > 0))          throw new Error("Largo de trazo inválido");
      if (!(prendas > 0))        throw new Error("Prendas por trazo inválido");
      if (!(capas > 0))          throw new Error("Número de capas inválido");
      // Curva: solo tallas con valor > 0
      const curvaFinal: Record<string, number> = {};
      for (const [talla, val] of Object.entries(curva)) {
        const n = parseInt(val || "0", 10);
        if (n > 0) curvaFinal[talla] = n;
      }
      return api.post<{ ok: boolean; orden_corte: { id: string } }>("/api/produccion/corte", {
        referencia_id: referenciaId,
        tono: tono || null,
        largo_trazo: largo,
        prendas_por_trazo: prendas,
        curva_trazo: curvaFinal,
        num_capas: capas,
        responsable: responsable || null,
        fecha_limite: fechaLimite || null,
        indicaciones: indicaciones || null,
      });
    },
    onSuccess: (data) => router.push(`/produccion/corte/${data.orden_corte.id}`),
    onError: (e: Error) => setErr(e.message),
  });

  function actualizarCurva(t: string, v: string) {
    setCurva((prev) => ({ ...prev, [t]: v }));
  }
  function agregarTalla() {
    const t = tallaExtra.trim();
    if (!t) return;
    if (t in curva) { setTallaExtra(""); return; }
    setCurva((prev) => ({ ...prev, [t]: "" }));
    setTallaExtra("");
  }
  function quitarTalla(t: string) {
    setCurva((prev) => {
      const copy = { ...prev };
      delete copy[t];
      return copy;
    });
  }

  // Totales derivados
  const largoN = parseFloat(largoTrazo || "0") || 0;
  const capasN = parseInt(numCapas || "0", 10) || 0;
  const prendasN = parseInt(prendasTrazo || "0", 10) || 0;
  const prendasEst = prendasN * capasN;
  const metrosTeo = largoN * capasN;
  const totalCurva = Object.values(curva).reduce((s, v) => s + (parseInt(v || "0", 10) || 0), 0);

  if (q.isLoading) return <LoadingState label="Cargando referencias…" />;

  return (
    <PageShell title="Nueva orden de corte" subtitle="Trazo + curva de tallas">
      <form onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }} className="space-y-4">
        {/* Cabecera */}
        <Card>
          <CardContent className="p-5 space-y-4">
            <p className="section-label">Referencia</p>
            <div>
              <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                Precosteo firmado *
              </label>
              <select value={referenciaId} onChange={(e) => setReferenciaId(e.target.value)} required
                className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm">
                <option value="">Selecciona una referencia…</option>
                {precosteos.map((p) => {
                  const tag = !p.bloqueada && p.es_muestra_diseno ? " · MUESTRA" : "";
                  return (
                    <option key={p.id} value={p.id}>
                      {p.codigo_referencia} · {p.nombre}{p.tela ? ` (${p.tela})` : ""}{tag}
                    </option>
                  );
                })}
              </select>
              {precosteos.length === 0 && (
                <p className="mt-1 text-[0.62rem] text-terracotta">
                  No hay precosteos disponibles. Firma uno o marca uno como muestra de diseño en /produccion/precosteo.
                </p>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Input label="Tono"                value={tono}          onChange={setTono}          placeholder="Ej. índigo oscuro" />
              <Input label="Largo de trazo (m) *" value={largoTrazo}    onChange={setLargoTrazo}    inputMode="decimal" required />
              <Input label="Prendas por trazo *"  value={prendasTrazo}  onChange={setPrendasTrazo}  inputMode="numeric" required />
              <Input label="Nº de capas *"        value={numCapas}      onChange={setNumCapas}      inputMode="numeric" required />
              <Input label="Responsable"          value={responsable}   onChange={setResponsable}   placeholder="Ej. cortador" />
              <Input label="Fecha límite"         type="date" value={fechaLimite} onChange={setFechaLimite} />
            </div>

            <div>
              <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                Indicaciones (opcional)
              </label>
              <textarea value={indicaciones} onChange={(e) => setIndicaciones(e.target.value)}
                rows={2} className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
            </div>
          </CardContent>
        </Card>

        {/* Curva de tallas */}
        <Card>
          <CardContent className="p-5 space-y-3">
            <div className="flex items-baseline justify-between">
              <p className="section-label">Curva de tallas</p>
              <p className="text-xs text-graphite tabular">
                Total por trazo: <span className="font-semibold text-ink-900">{totalCurva}</span>
              </p>
            </div>

            <div className="grid grid-cols-4 md:grid-cols-8 gap-2">
              {Object.entries(curva).map(([t, v]) => (
                <div key={t}>
                  <label className="mb-1 block text-[0.6rem] uppercase tracking-widest text-graphite text-center">
                    Talla {t}
                    <button type="button" onClick={() => quitarTalla(t)}
                      className="ml-1 text-terracotta hover:text-crimson" title="Quitar talla">×</button>
                  </label>
                  <input value={v} onChange={(e) => actualizarCurva(t, e.target.value)}
                    inputMode="numeric" placeholder="0"
                    className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-sm text-center tabular" />
                </div>
              ))}
              {/* Agregar talla extra */}
              <div className="flex items-end gap-1">
                <input value={tallaExtra} onChange={(e) => setTallaExtra(e.target.value)}
                  placeholder="S, XL…"
                  className="w-full rounded-sm border border-dashed border-border bg-white px-2 py-1.5 text-xs text-center" />
                <button type="button" onClick={agregarTalla}
                  className="rounded-sm border border-border bg-cloud px-2 py-1.5 text-xs hover:bg-cloud/80">+</button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Cálculos teóricos */}
        <Card>
          <CardContent className="p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
            <Kpi label="Prendas estimadas" value={prendasEst.toString()} />
            <Kpi label="Metros teóricos"   value={`${metrosTeo.toFixed(2)} m`} />
            <Kpi label="Prendas curva/trazo" value={totalCurva.toString()} />
            <Kpi label="Rendimiento (m/prenda)" value={prendasEst ? (metrosTeo / prendasEst).toFixed(3) : "—"} />
          </CardContent>
        </Card>

        {err && (
          <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5" /> {err}
          </div>
        )}

        <div className="sticky bottom-0 bg-white/95 backdrop-blur border-t border-border py-3 flex items-center justify-between gap-3">
          <p className="text-xs text-graphite">
            Se guardará como <span className="font-semibold text-ink-900">borrador</span>.
            Luego pistoleas los rollos en el detalle.
          </p>
          <button type="submit" disabled={mut.isPending}
            className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700 disabled:opacity-40">
            {mut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Crear orden
          </button>
        </div>
      </form>
    </PageShell>
  );
}

function Input({ label, value, onChange, required = false, placeholder = "", inputMode, type }: {
  label: string; value: string; onChange: (v: string) => void;
  required?: boolean; placeholder?: string;
  inputMode?: "decimal" | "numeric"; type?: string;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        required={required} placeholder={placeholder} inputMode={inputMode} type={type || "text"}
        className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
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
