"use client";

/**
 * Nueva orden de corte — UN tendido, VARIAS referencias.
 * El tendido comparte tela, rollos, largo de trazo y capas.
 * Cada referencia lleva su propio precosteo y su curva de tallas.
 * Al guardar → borrador. La pistola de rollos (compartidos) se hace en el detalle.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ESPIGAS, PAREJA_TALLA } from "@/lib/espigas";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Save, Loader2, AlertCircle, Search, ChevronDown, Plus, X } from "lucide-react";

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
const nuevaCurva = (): Record<string, string> =>
  Object.fromEntries(TALLAS_DEFAULT.map((t) => [t, ""]));

interface RefState { key: number; referenciaId: string; curva: Record<string, string> }

// Capas por la regla MALE'DENIM: cada espiga de 2 tallas aporta max; el resto su cantidad.
// Las parejas viven en lib/espigas.ts (única fuente: 4 sola · 6+16 · 8+10 · 12+14).
function capasDeCurva(curva: Record<string, number>): number {
  const pares = ESPIGAS.filter((e) => e.length === 2);
  let total = 0; const usadas = new Set<string>();
  for (const [a, b] of pares) {
    if (curva[a] !== undefined || curva[b] !== undefined) {
      total += Math.max(curva[a] || 0, curva[b] || 0); usadas.add(a); usadas.add(b);
    }
  }
  for (const [t, v] of Object.entries(curva)) if (!usadas.has(t)) total += v || 0;
  return total;
}

export default function NuevaOrdenCortePage() {
  const router = useRouter();

  const q = useQuery<{ precosteos?: Precosteo[] } | Precosteo[]>({
    queryKey: ["produccion", "precosteos", "disponibles-corte"],
    queryFn: () => api.get("/api/produccion/precosteo?disponibles_para_corte=true"),
  });
  const precosteos = useMemo<Precosteo[]>(() => {
    if (!q.data) return [];
    const arr = Array.isArray(q.data) ? q.data : ((q.data as { precosteos?: Precosteo[] }).precosteos || []);
    return arr.filter((p) => p.bloqueada || p.es_muestra_diseno);
  }, [q.data]);

  // Tendido (compartido)
  const [largoTrazo, setLargoTrazo] = useState("");
  const [numCapas, setNumCapas] = useState("");
  const [promedioTecnico, setPromedioTecnico] = useState("");
  const [responsable, setResponsable] = useState("");
  const [fechaEnvio, setFechaEnvio] = useState("");
  const [indicaciones, setIndicaciones] = useState("");
  const [destinatarios, setDestinatarios] = useState("");
  const [err, setErr] = useState("");

  // Referencias
  const [refs, setRefs] = useState<RefState[]>([{ key: 1, referenciaId: "", curva: nuevaCurva() }]);
  const nextKey = useRef(2);

  function addRef() { setRefs((r) => [...r, { key: nextKey.current++, referenciaId: "", curva: nuevaCurva() }]); }
  function removeRef(key: number) { setRefs((r) => (r.length > 1 ? r.filter((x) => x.key !== key) : r)); }
  function setRefPrecosteo(key: number, id: string) {
    setRefs((r) => r.map((x) => (x.key === key ? { ...x, referenciaId: id } : x)));
  }
  function setRefCurva(key: number, talla: string, val: string) {
    setRefs((r) => r.map((x) => {
      if (x.key !== key) return x;
      const curva = { ...x.curva, [talla]: val };
      const pareja = PAREJA_TALLA[talla];
      if (pareja && pareja in curva) curva[pareja] = val;   // la pareja se corta junta
      return { ...x, curva };
    }));
  }

  const idsUsados = refs.map((r) => r.referenciaId).filter(Boolean);
  const prendasDe = (rf: RefState) => Object.values(rf.curva).reduce((s, v) => s + (parseInt(v || "0", 10) || 0), 0);
  const totalPrendas = refs.reduce((s, rf) => s + prendasDe(rf), 0);

  const capasSugerida = useMemo(() => {
    const comb: Record<string, number> = {};
    for (const rf of refs) for (const [t, v] of Object.entries(rf.curva)) comb[t] = (comb[t] || 0) + (parseInt(v || "0", 10) || 0);
    return capasDeCurva(comb);
  }, [refs]);
  const capasEfectiva = numCapas ? (parseInt(numCapas, 10) || 0) : capasSugerida;

  const prom = parseFloat(promedioTecnico || "0") || 0;
  const metrosTeo = prom > 0 && totalPrendas > 0 ? prom * totalPrendas : 0;

  const mut = useMutation({
    mutationFn: () => {
      const largo = parseFloat(largoTrazo || "0");
      if (!(largo > 0)) throw new Error("Largo de trazo inválido");
      const referencias = refs.filter((rf) => rf.referenciaId).map((rf) => {
        const curva: Record<string, number> = {};
        for (const [t, v] of Object.entries(rf.curva)) { const n = parseInt(v || "0", 10); if (n > 0) curva[t] = n; }
        return { referencia_id: rf.referenciaId, curva_trazo: curva };
      });
      if (referencias.length === 0) throw new Error("Agrega al menos una referencia.");
      for (const r of referencias)
        if (Object.keys(r.curva_trazo).length === 0)
          throw new Error("Cada referencia necesita al menos una talla en la curva.");
      const destArr = destinatarios.split(/[,;\s]+/g).map((s) => s.trim()).filter(Boolean);
      return api.post<{ ok: boolean; orden_corte: { id: string } }>("/api/produccion/corte", {
        referencias,
        num_capas: numCapas ? parseInt(numCapas, 10) : capasSugerida,
        largo_trazo: largo,
        promedio_tecnico: promedioTecnico ? parseFloat(promedioTecnico) : null,
        responsable: responsable || null,
        fecha_envio: fechaEnvio || null,
        indicaciones: indicaciones || null,
        destinatarios_correo: destArr,
        trazos_url: null,
      });
    },
    onSuccess: (data) => router.push(`/produccion/corte/${data.orden_corte.id}`),
    onError: (e: Error) => setErr(e.message),
  });

  if (q.isLoading) return <LoadingState label="Cargando referencias…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  return (
    <PageShell title="Nueva orden de corte" subtitle="Un tendido · varias referencias">
      <form onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }} className="space-y-4">
        {/* ── Tendido (compartido) ── */}
        <Card>
          <CardContent className="p-5 space-y-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="inline-flex items-center gap-1.5 rounded-sm bg-navy-600/10 px-2.5 py-1 text-[0.62rem] font-bold uppercase tracking-widest text-navy-600">
                ▦ Tendido (compartido)
              </span>
              <span className="text-xs text-graphite">Mismo largo de trazo, capas y rollos para todas las referencias.</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Input label="Largo de trazo (m) *" value={largoTrazo} onChange={setLargoTrazo} inputMode="decimal" required />
              <div>
                <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                  Nº de capas del tendido
                </label>
                <input value={numCapas} onChange={(e) => setNumCapas(e.target.value)}
                  inputMode="numeric" placeholder={`sugerido ${capasSugerida}`}
                  className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
                <p className="mt-1 text-[0.68rem] text-graphite">Manual. Vacío = usa la sugerencia ({capasSugerida}).</p>
              </div>
              <Input label="Promedio técnico (m/prenda)" value={promedioTecnico} onChange={setPromedioTecnico} inputMode="decimal" placeholder="0.850" />
              <Input label="Cortador responsable" value={responsable} onChange={setResponsable} placeholder="Ej. Iván Rodríguez" />
              <Input label="Fecha de envío" type="date" value={fechaEnvio} onChange={setFechaEnvio} />
            </div>
            <div>
              <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">Indicaciones (opcional)</label>
              <textarea value={indicaciones} onChange={(e) => setIndicaciones(e.target.value)} rows={2}
                className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">Destinatarios correo de autorización</label>
              <input value={destinatarios} onChange={(e) => setDestinatarios(e.target.value)}
                placeholder="cortador@maledenim.com, produccion@maledenim.com"
                className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
            </div>
          </CardContent>
        </Card>

        {/* ── Referencias ── */}
        {refs.map((rf, i) => (
          <ReferenciaBloque key={rf.key} indice={i} total={refs.length}
            precosteos={precosteos} idsUsados={idsUsados}
            referenciaId={rf.referenciaId} curva={rf.curva}
            onPrecosteo={(id) => setRefPrecosteo(rf.key, id)}
            onCurva={(t, v) => setRefCurva(rf.key, t, v)}
            onQuitar={() => removeRef(rf.key)}
            prendas={prendasDe(rf)} />
        ))}

        <button type="button" onClick={addRef}
          className="w-full inline-flex items-center justify-center gap-2 rounded-sm border-[1.5px] border-dashed border-border-strong bg-transparent px-4 py-3 text-sm font-semibold text-navy-600 hover:bg-navy-600/[0.04]">
          <Plus className="h-4 w-4" /> Agregar otra referencia al tendido
        </button>

        {/* ── Resumen ── */}
        <Card>
          <CardContent className="p-5 space-y-4">
            <p className="section-label">Resumen del tendido</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Kpi label="Total prendas" value={totalPrendas.toString()} />
              <Kpi label="Capas del tendido" value={capasEfectiva.toString()} />
              <Kpi label="Metros teóricos" value={`${metrosTeo.toFixed(2)} m`} />
              <Kpi label="Referencias" value={idsUsados.length.toString()} />
            </div>
          </CardContent>
        </Card>

        {err && (
          <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5" /> {err}
          </div>
        )}

        <div className="sticky bottom-0 bg-white/95 backdrop-blur border-t border-border py-3 flex items-center justify-between gap-3">
          <p className="text-xs text-graphite">
            Se guardará como <span className="font-semibold text-ink-900">borrador</span>. Luego pistoleas los rollos (compartidos) en el detalle.
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

// ── Bloque de una referencia (selector de precosteo + curva) ──
function ReferenciaBloque({
  indice, total, precosteos, idsUsados, referenciaId, curva, onPrecosteo, onCurva, onQuitar, prendas,
}: {
  indice: number; total: number; precosteos: Precosteo[]; idsUsados: string[];
  referenciaId: string; curva: Record<string, string>;
  onPrecosteo: (id: string) => void; onCurva: (t: string, v: string) => void;
  onQuitar: () => void; prendas: number;
}) {
  const sel = precosteos.find((p) => p.id === referenciaId);
  return (
    <Card>
      <CardContent className="p-5 space-y-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="inline-grid place-items-center w-6 h-6 rounded-full border-[1.5px] border-navy-600 bg-navy-600/10 font-display text-sm text-navy-600">{indice + 1}</span>
            <p className="section-label">Referencia {indice + 1}{total > 1 ? ` de ${total}` : ""}</p>
            {sel?.tela && <span className="text-xs text-graphite">· Tela {sel.tela}</span>}
          </div>
          {total > 1 && (
            <button type="button" onClick={onQuitar} aria-label="Quitar referencia"
              className="p-2 -m-1 text-terracotta hover:text-crimson"><X className="h-4 w-4" /></button>
          )}
        </div>

        <PrecosteoSelector precosteos={precosteos} idsUsados={idsUsados} value={referenciaId} onChange={onPrecosteo} />

        <div>
          <div className="flex items-baseline justify-between mb-1">
            <label className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">Curva de tallas</label>
            <span className="text-xs text-graphite tabular">Prendas: <span className="font-semibold text-ink-900">{prendas}</span></span>
          </div>
          <div className="grid grid-cols-4 md:grid-cols-7 gap-2">
            {TALLAS_DEFAULT.map((t) => (
              <div key={t}>
                <label className="mb-1 block text-[0.7rem] uppercase tracking-widest text-graphite text-center">Talla {t}</label>
                <input value={curva[t] || ""} onChange={(e) => onCurva(t, e.target.value)}
                  inputMode="numeric" placeholder="0"
                  className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-sm text-center tabular" />
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Combobox de precosteo (buscable) — cada referencia tiene el suyo ──
function PrecosteoSelector({ precosteos, idsUsados, value, onChange }: {
  precosteos: Precosteo[]; idsUsados: string[]; value: string; onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [buscar, setBuscar] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);
  const sel = precosteos.find((p) => p.id === value);

  useEffect(() => {
    function afuera(e: MouseEvent) { if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false); }
    if (open) { document.addEventListener("mousedown", afuera); return () => document.removeEventListener("mousedown", afuera); }
  }, [open]);

  const filtrados = useMemo(() => {
    const s = buscar.trim().toUpperCase();
    if (!s) return precosteos;
    return precosteos.filter((p) => `${p.codigo_referencia} ${p.nombre} ${p.tela || ""}`.toUpperCase().includes(s));
  }, [precosteos, buscar]);

  function label(p: Precosteo) {
    const tag = !p.bloqueada && p.es_muestra_diseno ? " · MUESTRA" : "";
    return `${p.codigo_referencia} · ${p.nombre}${p.tela ? ` (${p.tela})` : ""}${tag}`;
  }

  return (
    <div ref={boxRef} className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between rounded-sm border border-border bg-card px-3 py-2 text-sm text-left hover:bg-cloud/30">
        <span className={sel ? "text-ink-900" : "text-graphite/60"}>{sel ? label(sel) : "Selecciona un precosteo…"}</span>
        <ChevronDown className={`h-3.5 w-3.5 text-graphite transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-sm border border-border bg-white shadow-lg">
          <div className="p-2 border-b border-border">
            <div className="flex items-center gap-2 rounded-sm border border-border bg-cloud/30 px-2 py-1.5">
              <Search className="h-3.5 w-3.5 text-graphite flex-none" />
              <input autoFocus value={buscar} onChange={(e) => setBuscar(e.target.value)}
                placeholder="Buscar por código, nombre o tela…" className="w-full bg-transparent text-sm outline-none" />
            </div>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {filtrados.length === 0 ? (
              <div className="px-3 py-3 text-xs text-graphite">
                {precosteos.length === 0 ? "No hay precosteos disponibles." : "Ninguna referencia coincide."}
              </div>
            ) : filtrados.map((p) => {
              const yaEnOtra = idsUsados.includes(p.id) && p.id !== value;
              const esMuestra = !p.bloqueada && p.es_muestra_diseno;
              return (
                <button key={p.id} type="button" disabled={yaEnOtra}
                  onClick={() => { if (!yaEnOtra) { onChange(p.id); setOpen(false); setBuscar(""); } }}
                  className={`w-full flex items-center justify-between px-3 py-2 text-left text-xs hover:bg-cloud/50 disabled:opacity-40 disabled:cursor-not-allowed ${value === p.id ? "bg-navy-600/[0.06]" : ""}`}>
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold text-ink-900 truncate">{p.codigo_referencia} · {p.nombre}</div>
                    <div className="text-[0.65rem] text-graphite truncate">
                      {p.tela || "sin tela"}{p.color ? ` · ${p.color}` : ""}{yaEnOtra ? " · ya en esta orden" : ""}
                    </div>
                  </div>
                  {esMuestra && (
                    <span className="ml-2 shrink-0 rounded-sm bg-navy-600/10 px-1.5 py-0.5 text-[0.68rem] font-bold uppercase tracking-widest text-navy-600">Muestra</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function Input({ label, value, onChange, required = false, placeholder = "", inputMode, type }: {
  label: string; value: string; onChange: (v: string) => void;
  required?: boolean; placeholder?: string; inputMode?: "decimal" | "numeric"; type?: string;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        required={required} placeholder={placeholder} inputMode={inputMode} type={type || "text"}
        className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
    </div>
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
