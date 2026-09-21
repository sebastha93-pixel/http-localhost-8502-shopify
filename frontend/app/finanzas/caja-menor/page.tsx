"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { useAuth } from "@/components/auth-provider";
import { tienePermiso } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney, fmtFecha, hoyBogotaISO } from "@/lib/utils";
import {
  Plus, Camera, RotateCcw, Settings2, Ban, X, Receipt, Wallet, Loader2,
} from "lucide-react";

interface Resumen {
  caja: {
    id: string;
    nombre: string;
    base: number;
    base_actualizada_por?: string | null;
    base_actualizada_at?: string | null;
  };
  saldo_disponible: number;
  gastado_periodo: number;
  n_gastos_periodo: number;
  categorias_sugeridas: string[];
}

interface Movimiento {
  id: string;
  tipo: "gasto" | "reembolso";
  monto: number;
  descripcion: string;
  categoria?: string | null;
  foto_url?: string | null;
  fecha: string;
  periodo_cerrado: boolean;
  anulado: boolean;
  anulado_por?: string | null;
  motivo_anulacion?: string | null;
  usuario_nombre?: string | null;
  creado_at: string;
}

const INPUT = "w-full rounded-sm border border-border bg-card px-3 py-2 text-sm";
const BTN_PRIMARY =
  "inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700 disabled:opacity-40";
const BTN_GHOST =
  "inline-flex items-center gap-2 rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud disabled:opacity-40";

export default function CajaMenorPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const puedeModificar = tienePermiso(user, "finanzas", "modificar");

  const resumenQ = useQuery({
    queryKey: ["caja-menor", "resumen"],
    queryFn: () => api.get<Resumen>("/api/finanzas/caja-menor"),
  });
  const movQ = useQuery({
    queryKey: ["caja-menor", "movimientos"],
    queryFn: () => api.get<{ movimientos: Movimiento[] }>("/api/finanzas/caja-menor/movimientos"),
  });

  // ── Formularios / estado local ──────────────────────────────────────
  const [abrirGasto, setAbrirGasto] = useState(false);
  const [abrirBase, setAbrirBase] = useState(false);
  const [confirmReponer, setConfirmReponer] = useState(false);
  const [foto, setFoto] = useState<File | null>(null);
  const [monto, setMonto] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [categoria, setCategoria] = useState("");
  const [fecha, setFecha] = useState<string>(hoyBogotaISO().slice(0, 10));
  const [baseInput, setBaseInput] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [lightbox, setLightbox] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const previewUrl = useMemo(() => (foto ? URL.createObjectURL(foto) : ""), [foto]);

  function limpiarGasto() {
    setFoto(null);
    setMonto("");
    setDescripcion("");
    setCategoria("");
    setFecha(hoyBogotaISO().slice(0, 10));
    if (fileRef.current) fileRef.current.value = "";
  }

  function refrescar() {
    qc.invalidateQueries({ queryKey: ["caja-menor"] });
  }

  async function registrarGasto(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setMsg("");
    if (!monto || Number(monto) <= 0) return setErr("El monto debe ser mayor a cero.");
    if (!descripcion.trim()) return setErr("La descripción es obligatoria.");
    if (!foto) return setErr("La foto del recibo es obligatoria.");
    setEnviando(true);
    try {
      const fd = new FormData();
      fd.append("monto", String(monto));
      fd.append("descripcion", descripcion.trim());
      fd.append("categoria", categoria.trim());
      fd.append("fecha", fecha);
      fd.append("file", foto);
      const res = await fetch(`${API_BASE}/api/finanzas/caja-menor/gasto`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      });
      if (!res.ok) throw new Error(await detalle(res));
      setMsg("Gasto registrado.");
      limpiarGasto();
      setAbrirGasto(false);
      refrescar();
    } catch (e: any) {
      setErr(e.message || "No se pudo registrar el gasto.");
    } finally {
      setEnviando(false);
    }
  }

  async function guardarBase(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setMsg("");
    const b = Number(baseInput);
    if (baseInput === "" || Number.isNaN(b) || b < 0) return setErr("La base debe ser un número válido.");
    setEnviando(true);
    try {
      await api.post("/api/finanzas/caja-menor/base", { base: b });
      setMsg("Base actualizada.");
      setAbrirBase(false);
      refrescar();
    } catch (e: any) {
      setErr(e.message || "No se pudo actualizar la base.");
    } finally {
      setEnviando(false);
    }
  }

  async function reponer() {
    setErr("");
    setMsg("");
    setEnviando(true);
    try {
      const r = await api.post<{ repuesto: number; n_gastos: number }>(
        "/api/finanzas/caja-menor/reponer",
      );
      setMsg(`Caja repuesta: ${formatMoney(r.repuesto)} de ${r.n_gastos} gasto(s).`);
      setConfirmReponer(false);
      refrescar();
    } catch (e: any) {
      setErr(e.message || "No se pudo reponer la caja.");
    } finally {
      setEnviando(false);
    }
  }

  async function anular(m: Movimiento) {
    if (!confirm(`¿Anular el gasto "${m.descripcion}" por ${formatMoney(m.monto)}?`)) return;
    const motivo = prompt("Motivo de la anulación (opcional):") || "";
    setErr("");
    try {
      await api.post(`/api/finanzas/caja-menor/movimiento/${m.id}/anular`, { motivo });
      refrescar();
    } catch (e: any) {
      setErr(e.message || "No se pudo anular el gasto.");
    }
  }

  if (resumenQ.isLoading) return <LoadingState label="Cargando caja menor…" />;
  if (resumenQ.isError || !resumenQ.data)
    return <ErrorState error={resumenQ.error} onRetry={() => resumenQ.refetch()} />;

  const r = resumenQ.data;
  const movimientos = (movQ.data?.movimientos || []).filter((m) => m.tipo === "gasto");
  const saldoBajo = r.saldo_disponible < r.caja.base * 0.15; // < 15% de la base

  return (
    <PageShell
      title="Caja menor"
      subtitle={r.caja.nombre}
      isFetching={resumenQ.isFetching || movQ.isFetching}
      onRefresh={refrescar}
    >
      {/* KPIs */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <KpiCard label="Base (fondo fijo)" value={formatMoney(r.caja.base)}
          meta={r.caja.base_actualizada_por ? `Fijada por ${r.caja.base_actualizada_por}` : "Sin definir"} />
        <KpiCard
          label="Saldo disponible"
          value={formatMoney(r.saldo_disponible)}
          variant={r.saldo_disponible < 0 ? "danger" : saldoBajo ? "danger" : "success"}
          meta={saldoBajo && r.caja.base > 0 ? "Conviene reponer" : "Efectivo en caja"}
        />
        <KpiCard label="Gastado en el periodo" value={formatMoney(r.gastado_periodo)}
          meta={`${r.n_gastos_periodo} gasto(s) sin reponer`} />
      </div>

      {/* Acciones */}
      {puedeModificar && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button className={BTN_PRIMARY} onClick={() => { setAbrirGasto((v) => !v); setErr(""); setMsg(""); }}>
            <Plus className="h-4 w-4" /> Registrar gasto
          </button>
          <button className={BTN_GHOST} disabled={r.gastado_periodo <= 0}
            onClick={() => { setConfirmReponer(true); setErr(""); setMsg(""); }}>
            <RotateCcw className="h-4 w-4" /> Reponer caja
          </button>
          <button className={BTN_GHOST}
            onClick={() => { setAbrirBase((v) => !v); setBaseInput(String(r.caja.base || "")); setErr(""); setMsg(""); }}>
            <Settings2 className="h-4 w-4" /> Configurar base
          </button>
        </div>
      )}

      {/* Mensajes */}
      {msg && <p className="mt-3 rounded-sm border border-sage/30 bg-sage/10 px-3 py-2 text-sm text-sage">{msg}</p>}
      {err && <p className="mt-3 rounded-sm border border-crimson/30 bg-crimson/10 px-3 py-2 text-sm text-crimson">{err}</p>}

      {/* Form: registrar gasto */}
      {abrirGasto && puedeModificar && (
        <Card className="mt-4">
          <CardContent className="p-4">
            <form onSubmit={registrarGasto} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="section-label">Monto</label>
                <input type="number" inputMode="decimal" min={0} step="any" value={monto}
                  onChange={(e) => setMonto(e.target.value)} placeholder="0" className={`${INPUT} mt-1`} />
              </div>
              <div>
                <label className="section-label">Fecha</label>
                <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)}
                  max={hoyBogotaISO().slice(0, 10)} className={`${INPUT} mt-1`} />
              </div>
              <div className="sm:col-span-2">
                <label className="section-label">Descripción</label>
                <input value={descripcion} onChange={(e) => setDescripcion(e.target.value)}
                  placeholder="¿En qué se gastó?" className={`${INPUT} mt-1`} />
              </div>
              <div>
                <label className="section-label">Categoría</label>
                <input list="caja-cats" value={categoria} onChange={(e) => setCategoria(e.target.value)}
                  placeholder="Opcional" className={`${INPUT} mt-1`} />
                <datalist id="caja-cats">
                  {r.categorias_sugeridas.map((c) => <option key={c} value={c} />)}
                </datalist>
              </div>
              <div>
                <label className="section-label">Foto del recibo</label>
                <input ref={fileRef} type="file" accept="image/*" capture="environment"
                  onChange={(e) => setFoto(e.target.files?.[0] || null)}
                  className={`${INPUT} mt-1 file:mr-3 file:rounded-sm file:border-0 file:bg-navy-600/10 file:px-2 file:py-1 file:text-navy-600`} />
              </div>
              {previewUrl && (
                <div className="sm:col-span-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={previewUrl} alt="Vista previa del recibo" className="max-h-48 rounded-sm border border-border" />
                </div>
              )}
              <div className="sm:col-span-2 flex items-center gap-2 pt-1">
                <button type="submit" className={BTN_PRIMARY} disabled={enviando}>
                  {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}
                  Guardar gasto
                </button>
                <button type="button" className={BTN_GHOST} onClick={() => { setAbrirGasto(false); limpiarGasto(); }}>
                  Cancelar
                </button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Form: configurar base */}
      {abrirBase && puedeModificar && (
        <Card className="mt-4">
          <CardContent className="p-4">
            <form onSubmit={guardarBase} className="flex flex-wrap items-end gap-3">
              <div>
                <label className="section-label">Base de la caja (fondo fijo)</label>
                <input type="number" inputMode="decimal" min={0} step="any" value={baseInput}
                  onChange={(e) => setBaseInput(e.target.value)} placeholder="0" className={`${INPUT} mt-1 w-56`} />
              </div>
              <button type="submit" className={BTN_PRIMARY} disabled={enviando}>
                {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Guardar base
              </button>
              <button type="button" className={BTN_GHOST} onClick={() => setAbrirBase(false)}>Cancelar</button>
            </form>
            <p className="mt-2 text-xs text-graphite">
              La base es el efectivo con que debe quedar llena la caja. El saldo disponible se calcula restándole los gastos del periodo.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Confirmar reponer */}
      {confirmReponer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/60 p-4" onClick={() => setConfirmReponer(false)}>
          <Card className="w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <CardContent className="p-5">
              <h3 className="font-display text-lg font-medium">Reponer caja</h3>
              <p className="mt-2 text-sm text-graphite">
                Se repondrá <strong className="text-ink-900 dark:text-foreground">{formatMoney(r.gastado_periodo)}</strong> de{" "}
                {r.n_gastos_periodo} gasto(s). Esos gastos se cerrarán y el saldo volverá a la base ({formatMoney(r.caja.base)}).
              </p>
              <div className="mt-4 flex items-center gap-2">
                <button className={BTN_PRIMARY} onClick={reponer} disabled={enviando}>
                  {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />} Confirmar reposición
                </button>
                <button className={BTN_GHOST} onClick={() => setConfirmReponer(false)}>Cancelar</button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Lista de gastos del periodo */}
      <Card className="mt-4">
        <CardContent className="p-0">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <p className="section-label flex items-center gap-2"><Receipt className="h-4 w-4" /> Gastos del periodo</p>
            <span className="text-xs text-graphite">{movimientos.length} gasto(s)</span>
          </div>
          {movimientos.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-graphite">
              <Wallet className="h-8 w-8 opacity-40" />
              <p className="text-sm">Aún no hay gastos en este periodo.</p>
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {movimientos.map((m) => (
                <li key={m.id} className={`flex items-center gap-3 px-4 py-3 ${m.anulado ? "opacity-50" : ""}`}>
                  {m.foto_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={m.foto_url} alt="Recibo" onClick={() => setLightbox(m.foto_url!)}
                      className="h-12 w-12 shrink-0 cursor-zoom-in rounded-sm border border-border object-cover" />
                  ) : (
                    <div className="grid h-12 w-12 shrink-0 place-items-center rounded-sm border border-border bg-cloud/40 text-graphite">
                      <Receipt className="h-5 w-5" />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className={`truncate text-sm font-medium ${m.anulado ? "line-through" : ""}`}>{m.descripcion}</p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-graphite">
                      <span>{fmtFecha(m.fecha)}</span>
                      {m.categoria && <span className="rounded-full bg-navy-600/10 px-2 py-0.5 text-navy-600">{m.categoria}</span>}
                      {m.usuario_nombre && <span>· {m.usuario_nombre}</span>}
                      {m.anulado && <span className="text-crimson">· Anulado{m.motivo_anulacion ? `: ${m.motivo_anulacion}` : ""}</span>}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className={`tabular text-sm font-semibold ${m.anulado ? "line-through text-graphite" : "text-ink-900 dark:text-foreground"}`}>
                      {formatMoney(m.monto)}
                    </p>
                    {puedeModificar && !m.anulado && (
                      <button onClick={() => anular(m)} title="Anular gasto"
                        className="mt-1 inline-flex items-center gap-1 text-[0.68rem] font-semibold uppercase tracking-widest text-graphite hover:text-crimson">
                        <Ban className="h-3 w-3" /> Anular
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Lightbox */}
      {lightbox && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/80 p-4" onClick={() => setLightbox(null)}>
          <button className="absolute right-4 top-4 text-white/80 hover:text-white" onClick={() => setLightbox(null)}>
            <X className="h-6 w-6" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={lightbox} alt="Recibo" className="max-h-[85vh] max-w-full rounded-sm" onClick={(e) => e.stopPropagation()} />
        </div>
      )}
    </PageShell>
  );

  async function detalle(res: Response): Promise<string> {
    const cuerpo = await res.text();
    try {
      const j = JSON.parse(cuerpo) as { detail?: unknown };
      if (j?.detail) return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* texto plano */ }
    return cuerpo.slice(0, 200) || `HTTP ${res.status}`;
  }
}
