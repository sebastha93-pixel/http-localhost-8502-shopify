"use client";

/**
 * Nueva orden de corte.
 * 1. Escoge un precosteo FIRMADO como referencia.
 * 2. Define tono, largo trazo, prendas x trazo, capas.
 * 3. Curva de tallas 4-6-8-10-12-14-16 (editable).
 * Al guardar → borrador. La pistola de rollos se hace en el detalle.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PAREJA_TALLA } from "@/lib/espigas";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Save, Loader2, AlertCircle, Search, ChevronDown } from "lucide-react";

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
  const [promedioTecnico, setPromedioTecnico] = useState("");
  const [largoTrazo, setLargoTrazo] = useState("");
  const [cantidadProgramada, setCantidadProgramada] = useState("");
  const [responsable, setResponsable] = useState("");
  const [fechaEnvio, setFechaEnvio] = useState("");
  const [indicaciones, setIndicaciones] = useState("");
  const [destinatarios, setDestinatarios] = useState("");
  const [curva, setCurva] = useState<Record<string, string>>(
    Object.fromEntries(TALLAS_DEFAULT.map((t) => [t, ""]))
  );
  const [tallaExtra, setTallaExtra] = useState("");
  const [err, setErr] = useState("");

  // Precosteo seleccionado (para mostrar la tela automáticamente en la cabecera)
  const precosteoSel = useMemo<Precosteo | undefined>(
    () => precosteos.find((p) => p.id === referenciaId),
    [precosteos, referenciaId],
  );

  // Combobox precosteo — buscador con lupa
  const [refBuscar, setRefBuscar] = useState("");
  const [refOpen, setRefOpen] = useState(false);
  const refBoxRef = useRef<HTMLDivElement>(null);

  const precosteosFiltrados = useMemo(() => {
    const q = refBuscar.trim().toUpperCase();
    if (!q) return precosteos;
    return precosteos.filter((p) => {
      const hay = `${p.codigo_referencia} ${p.nombre} ${p.tela || ""}`.toUpperCase();
      return hay.includes(q);
    });
  }, [precosteos, refBuscar]);

  useEffect(() => {
    function handleClickAfuera(e: MouseEvent) {
      if (refBoxRef.current && !refBoxRef.current.contains(e.target as Node)) {
        setRefOpen(false);
      }
    }
    if (refOpen) {
      document.addEventListener("mousedown", handleClickAfuera);
      return () => document.removeEventListener("mousedown", handleClickAfuera);
    }
  }, [refOpen]);

  function precosteoLabel(p: Precosteo): string {
    const tag = !p.bloqueada && p.es_muestra_diseno ? " · MUESTRA" : "";
    return `${p.codigo_referencia} · ${p.nombre}${p.tela ? ` (${p.tela})` : ""}${tag}`;
  }

  // Auto-calcula # capas desde la curva con la regla MALE'DENIM:
  //   Pares fijos: (6,12), (8,10), (14,16) — cada par aporta max(par).
  //   Talla 4 sola (y cualquier talla no mapeada) → aporta su cantidad.
  const capasAutoCalc = useMemo(() => {
    const PARES: [string, string][] = [["6", "12"], ["8", "10"], ["14", "16"]];
    const q = (t: string) => parseInt(curva[t] || "0", 10) || 0;
    let total = 0;
    const consumidas = new Set<string>();
    for (const [a, b] of PARES) {
      if (curva[a] !== undefined || curva[b] !== undefined) {
        total += Math.max(q(a), q(b));
        consumidas.add(a); consumidas.add(b);
      }
    }
    for (const [t, v] of Object.entries(curva)) {
      if (!consumidas.has(t)) {
        total += parseInt(v || "0", 10) || 0;
      }
    }
    return total;
  }, [curva]);

  const totalCurva = Object.values(curva).reduce((s, v) => s + (parseInt(v || "0", 10) || 0), 0);

  const mut = useMutation({
    mutationFn: () => {
      const largo = parseFloat(largoTrazo || "0");
      const cant = parseInt(cantidadProgramada || "0", 10);
      if (!referenciaId)   throw new Error("Selecciona una referencia");
      if (!(largo > 0))    throw new Error("Largo de trazo inválido");
      // Curva: solo tallas con valor > 0
      const curvaFinal: Record<string, number> = {};
      for (const [talla, val] of Object.entries(curva)) {
        const n = parseInt(val || "0", 10);
        if (n > 0) curvaFinal[talla] = n;
      }
      if (Object.keys(curvaFinal).length === 0)
        throw new Error("Llena al menos una talla en la curva.");
      const destArr = destinatarios
        .split(/[,;\s]+/g).map((s) => s.trim()).filter(Boolean);
      return api.post<{ ok: boolean; orden_corte: { id: string } }>("/api/produccion/corte", {
        referencia_id: referenciaId,
        largo_trazo: largo,
        curva_trazo: curvaFinal,
        cantidad_programada: cant || totalCurva || null,
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

  function actualizarCurva(t: string, v: string) {
    setCurva((prev) => {
      const next = { ...prev, [t]: v };
      // Espigas: la pareja se corta junta → misma cantidad automática
      const pareja = PAREJA_TALLA[t];
      if (pareja && pareja in next) next[pareja] = v;
      return next;
    });
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

  // Totales derivados (para la card de KPIs)
  //   Metros teóricos = promedio_tecnico × cantidad_programada
  //   Rendimiento    = metros_teoricos / cantidad_programada (= promedio_tecnico)
  const prom = parseFloat(promedioTecnico || "0") || 0;
  const prendasEst = parseInt(cantidadProgramada || "0", 10) || totalCurva || 0;
  const metrosTeo = prom > 0 && prendasEst > 0 ? prom * prendasEst : 0;
  const rendimiento = prendasEst > 0 ? metrosTeo / prendasEst : 0;

  if (q.isLoading) return <LoadingState label="Cargando referencias…" />;
  // Error de red ≠ "no hay precosteos" — antes mandaba a firmar precosteos que sí existían.
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  return (
    <PageShell title="Nueva orden de corte" subtitle="Trazo + curva de tallas">
      <form onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }} className="space-y-4">
        {/* Cabecera */}
        <Card>
          <CardContent className="p-5 space-y-4">
            <p className="section-label">Referencia</p>
            <div ref={refBoxRef} className="relative">
              <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                Precosteo firmado *
              </label>
              <button type="button" onClick={() => setRefOpen((v) => !v)}
                className="w-full flex items-center justify-between rounded-sm border border-border bg-card px-3 py-2 text-sm text-left hover:bg-cloud/30">
                <span className={precosteoSel ? "text-ink-900" : "text-graphite/60"}>
                  {precosteoSel ? precosteoLabel(precosteoSel) : "Selecciona una referencia…"}
                </span>
                <ChevronDown className={`h-3.5 w-3.5 text-graphite transition-transform ${refOpen ? "rotate-180" : ""}`} />
              </button>
              {refOpen && (
                <div className="absolute z-20 mt-1 w-full rounded-sm border border-border bg-white shadow-lg">
                  <div className="p-2 border-b border-border">
                    <div className="flex items-center gap-2 rounded-sm border border-border bg-cloud/30 px-2 py-1.5">
                      <Search className="h-3.5 w-3.5 text-graphite flex-none" />
                      <input autoFocus value={refBuscar} onChange={(e) => setRefBuscar(e.target.value)}
                        placeholder="Buscar por código, nombre o tela…"
                        className="w-full bg-transparent text-sm outline-none" />
                    </div>
                  </div>
                  <div className="max-h-64 overflow-y-auto">
                    {q.isLoading ? (
                      <div className="px-3 py-3 text-xs text-graphite">Cargando referencias…</div>
                    ) : precosteosFiltrados.length === 0 ? (
                      <div className="px-3 py-3 text-xs text-graphite">
                        {precosteos.length === 0
                          ? "No hay precosteos disponibles."
                          : "Ninguna referencia coincide."}
                      </div>
                    ) : precosteosFiltrados.map((p) => {
                      const esMuestra = !p.bloqueada && p.es_muestra_diseno;
                      return (
                        <button key={p.id} type="button"
                          onClick={() => { setReferenciaId(p.id); setRefOpen(false); setRefBuscar(""); }}
                          className={`w-full flex items-center justify-between px-3 py-2 text-left text-xs hover:bg-cloud/50 ${referenciaId === p.id ? "bg-navy-600/[0.06]" : ""}`}>
                          <div className="min-w-0 flex-1">
                            <div className="font-semibold text-ink-900 truncate">
                              {p.codigo_referencia} · {p.nombre}
                            </div>
                            <div className="text-[0.65rem] text-graphite truncate">
                              {p.tela || "sin tela"}{p.color ? ` · ${p.color}` : ""}
                            </div>
                          </div>
                          {esMuestra && (
                            <span className="ml-2 shrink-0 rounded-sm bg-navy-600/10 px-1.5 py-0.5 text-[0.68rem] font-bold uppercase tracking-widest text-navy-600">
                              Muestra
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              {precosteos.length === 0 && (
                <p className="mt-1 text-[0.7rem] text-terracotta">
                  No hay precosteos disponibles. Firma uno o marca uno como muestra de diseño en /produccion/precosteo.
                </p>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {/* Nombre de tela — trae automático del precosteo */}
              <div>
                <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                  Nombre de tela (auto)
                </label>
                <input readOnly value={precosteoSel?.tela || ""}
                  placeholder={referenciaId ? "—" : "Selecciona referencia primero"}
                  className="w-full rounded-sm border border-border bg-cloud/40 px-3 py-2 text-sm text-graphite" />
              </div>
              <Input label="Promedio técnico (m/prenda)" value={promedioTecnico} onChange={setPromedioTecnico} inputMode="decimal" placeholder="0.850" />
              <Input label="Largo de trazo (m) *" value={largoTrazo}    onChange={setLargoTrazo}    inputMode="decimal" required />
              <Input label="Cantidad programada"   value={cantidadProgramada} onChange={setCantidadProgramada} inputMode="numeric" placeholder={totalCurva > 0 ? String(totalCurva) : "0"} />
              {/* Nº capas — auto desde curva (readonly) */}
              <div>
                <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                  Nº de capas (auto)
                </label>
                <div className="w-full rounded-sm border border-border bg-cloud/40 px-3 py-2 text-sm text-ink-900 tabular font-semibold">
                  {capasAutoCalc}
                </div>
              </div>
              <Input label="Cortador responsable"  value={responsable}   onChange={setResponsable}   placeholder="Ej. Ivan Rodríguez" />
              <Input label="Fecha de envío"        type="date" value={fechaEnvio} onChange={setFechaEnvio} />
            </div>

            <div>
              <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                Indicaciones (opcional)
              </label>
              <textarea value={indicaciones} onChange={(e) => setIndicaciones(e.target.value)}
                rows={2} className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
            </div>

            {/* Destinatarios correo — se envían al autorizar */}
            <div>
              <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                Destinatarios correo de autorización
              </label>
              <input value={destinatarios} onChange={(e) => setDestinatarios(e.target.value)}
                placeholder="cortador@maledenim.com, produccion@maledenim.com"
                className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
              <p className="mt-1 text-[0.7rem] text-graphite">
                Emails separados por coma. Al autorizar la orden se enviará el correo con asunto{" "}
                <span className="font-semibold text-ink-900">
                  &ldquo;Orden de corte referencia {precosteoSel?.codigo_referencia || "XXXX"}&rdquo;
                </span>.
              </p>
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
                  <label className="mb-1 block text-[0.7rem] uppercase tracking-widest text-graphite text-center">
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
            <Kpi label="Cantidad programada" value={prendasEst.toString()} />
            <Kpi label="Nº capas (auto)"     value={capasAutoCalc.toString()} />
            <Kpi label="Metros teóricos"     value={`${metrosTeo.toFixed(2)} m`} />
            <Kpi label="Rendimiento (m/prenda)" value={prendasEst ? rendimiento.toFixed(3) : "—"} />
          </CardContent>
        </Card>

        {err && (
          <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
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
