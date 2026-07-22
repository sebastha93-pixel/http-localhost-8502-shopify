"use client";

/**
 * Detalle de precosteo. Si es borrador, permite firmar (con permiso) o subir foto.
 * Si está bloqueada, muestra inmutable con badge "Autorizada por X".
 */
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { getToken, esAdmin, puedeAccionModulo } from "@/lib/auth";
import { useAuth } from "@/components/auth-provider";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Lock, Camera, CheckCircle, Loader2, AlertCircle, Pencil, Plus, Trash2, X, Copy } from "lucide-react";

// Mismas categorías del backend (CATEGORIAS_PRECOSTEO)
const CATEGORIAS = ["MATERIA PRIMA", "PROCESO EN MATERIA PRIMA", "INSUMO CONFECCION", "INSUMO TERMINACION"];

// Línea editable del costeo (los totales los recalcula el backend al guardar)
interface LineaEdit {
  categoria: string;
  item: string;
  valor_unitario: string;
  cantidad: string;
  iva: string;
}

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
  instrucciones_lavado?: string;
  items: Item[];
}

export default function PrecosteoDetallePage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const { user } = useAuth();
  const [editando, setEditando] = useState(false);
  const [form, setForm] = useState({ nombre: "", codigo_referencia: "", tela: "", instrucciones_lavado: "" });
  // Líneas del costeo editables (al duplicar una referencia los valores
  // cambian aunque la tela sea la misma — por eso el duplicado se edita).
  const [editLineas, setEditLineas] = useState<LineaEdit[]>([]);

  function lineasDesde(items: Item[]): LineaEdit[] {
    return items.map((it) => ({
      categoria: it.categoria,
      item: it.item,
      valor_unitario: String(it.valor_unitario ?? ""),
      cantidad: String(it.cantidad ?? ""),
      iva: String(it.iva ?? "0"),
    }));
  }

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
      qc.invalidateQueries({ queryKey: ["produccion", "precosteo"] });
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  const guardarMut = useMutation({
    mutationFn: () => {
      // Los totales por línea y globales los recalcula el backend.
      const items = editLineas
        .filter((l) => l.item.trim() && (parseFloat(l.valor_unitario || "0") > 0 || parseFloat(l.cantidad || "0") > 0))
        .map((l) => ({
          categoria: l.categoria,
          item: l.item.trim(),
          valor_unitario: parseFloat(l.valor_unitario || "0") || 0,
          cantidad: parseFloat(l.cantidad || "0") || 1,
          iva: parseFloat(l.iva || "0") || 0,
        }));
      if (items.length === 0) throw new Error("El costeo necesita al menos una línea con valor.");
      return api.patch(`/api/produccion/precosteo/${id}`, {
        nombre: form.nombre.trim(),
        codigo_referencia: form.codigo_referencia.trim(),
        tela: form.tela.trim(),
        instrucciones_lavado: form.instrucciones_lavado.trim(),
        items,
      });
    },
    onSuccess: () => {
      setMsg("Cambios guardados.");
      setErr("");
      setEditando(false);
      qc.invalidateQueries({ queryKey: ["produccion", "precosteo"] });
    },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  const duplicarMut = useMutation({
    mutationFn: () => api.post<{ id: string }>(`/api/produccion/precosteo/${id}/duplicar`),
    // Abre la copia directo en modo edición para ponerle su nombre/código real
    // y quitarle el "-COPIA" de una vez.
    onSuccess: (nuevo) => { router.push(`/produccion/precosteo/${nuevo.id}?editar=1`); },
    onError: (e: Error) => { setErr(e.message); setMsg(""); },
  });

  // Si se llega con ?editar=1 (p. ej. tras duplicar), abrir edición al cargar.
  const autoEditRef = useRef(false);
  useEffect(() => {
    if (autoEditRef.current || !q.data) return;
    if (typeof window !== "undefined"
        && new URLSearchParams(window.location.search).get("editar") === "1") {
      autoEditRef.current = true;
      setForm({
        nombre: q.data.nombre || "",
        codigo_referencia: q.data.codigo_referencia || "",
        tela: q.data.tela || "",
        instrucciones_lavado: q.data.instrucciones_lavado || "",
      });
      setEditLineas(lineasDesde(q.data.items || []));
      setEditando(true);
    }
  }, [q.data]);

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
      qc.invalidateQueries({ queryKey: ["produccion", "precosteo"] });
    } catch (e: any) {
      setErr(e.message || "Error subiendo foto");
    }
  }

  if (q.isLoading) return <LoadingState label="Cargando precosteo…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const p = q.data;

  // Borrador → lo edita el diseñador (produccion_costos modificar).
  // Autorizado (bloqueado) → SOLO admin (hoy = Sebastián / María Alejandra).
  const puedeEditar = p.bloqueada
    ? esAdmin(user)
    : puedeAccionModulo(user, "produccion_costos", "modificar");
  // Duplicar crea un borrador NUEVO (no toca el original): lo puede hacer
  // cualquiera que cree precosteos, aunque el original esté autorizado.
  const puedeCrear = puedeAccionModulo(user, "produccion_costos", "modificar");

  function abrirEdicion() {
    setForm({
      nombre: p.nombre || "",
      codigo_referencia: p.codigo_referencia || "",
      tela: p.tela || "",
      instrucciones_lavado: p.instrucciones_lavado || "",
    });
    setEditLineas(lineasDesde(p.items || []));
    setErr(""); setMsg("");
    setEditando(true);
  }

  function setLinea(i: number, campo: keyof LineaEdit, v: string) {
    setEditLineas((ls) => ls.map((l, j) => (j === i ? { ...l, [campo]: v } : l)));
  }

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
          {puedeCrear && !editando && (
            <button onClick={() => duplicarMut.mutate()} disabled={duplicarMut.isPending}
              title="Crear un borrador nuevo a partir de este (para reprogramar o una referencia parecida)"
              className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-3 py-1.5 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud disabled:opacity-40">
              {duplicarMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Copy className="h-3.5 w-3.5" />} Duplicar
            </button>
          )}
          {puedeEditar && !editando && (
            <button onClick={abrirEdicion}
              className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-3 py-1.5 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud">
              <Pencil className="h-3.5 w-3.5" /> Editar
            </button>
          )}
        </div>
      </div>

      {editando && (
        <Card>
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="section-label">Editar producto</p>
              {p.bloqueada && (
                <span className="text-[0.7rem] text-graphite inline-flex items-center gap-1">
                  <Lock className="h-3 w-3" /> Autorizado — solo tú o María Alejandra pueden editar
                </span>
              )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <FieldEdit label="Referencia (código)" value={form.codigo_referencia}
                onChange={(v) => setForm({ ...form, codigo_referencia: v })} />
              <FieldEdit label="Nombre" value={form.nombre}
                onChange={(v) => setForm({ ...form, nombre: v })} />
              <FieldEdit label="Tela" value={form.tela}
                onChange={(v) => setForm({ ...form, tela: v })} />
            </div>
            <div>
              <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                Composición — etiqueta de lavado (la imprime la SAT)
              </label>
              <textarea value={form.instrucciones_lavado}
                onChange={(e) => setForm({ ...form, instrucciones_lavado: e.target.value })}
                rows={2}
                placeholder="Ej: 100%ALGODON  ·  o  98% ALGODON 2% ELASTANO. Los cuidados (lavadora, agua tibia…) son fijos en la etiqueta."
                className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm text-ink-900 placeholder:text-graphite/50" />
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => { setEditando(false); setErr(""); }}
                className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-4 py-2 text-xs font-semibold uppercase tracking-widest text-graphite hover:bg-cloud">
                <X className="h-3.5 w-3.5" /> Cancelar
              </button>
              <button onClick={() => guardarMut.mutate()}
                disabled={guardarMut.isPending || !form.nombre.trim() || !form.codigo_referencia.trim()}
                className="inline-flex items-center gap-2 rounded-sm bg-teal px-5 py-2 text-xs font-semibold uppercase tracking-widest text-white hover:bg-ink-900 disabled:opacity-40">
                {guardarMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />}
                Guardar
              </button>
            </div>
          </CardContent>
        </Card>
      )}

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
            {puedeEditar && (
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
            <p className="section-label">Líneas ({editando ? editLineas.length : p.items.length})</p>
            {editando && (
              <button
                onClick={() => setEditLineas((ls) => [...ls, { categoria: CATEGORIAS[0], item: "", valor_unitario: "", cantidad: "1", iva: "0" }])}
                className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-3 py-1.5 text-[0.68rem] font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud">
                <Plus className="h-3.5 w-3.5" /> Agregar línea
              </button>
            )}
          </div>
          {editando ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-cloud/60 border-b border-border">
                  <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                    <th className="px-2 py-2">Categoría</th>
                    <th className="px-2 py-2">Item</th>
                    <th className="px-2 py-2 text-right">Valor unit.</th>
                    <th className="px-2 py-2 text-right">Cantidad</th>
                    <th className="px-2 py-2 text-right">IVA ($)</th>
                    <th className="px-2 py-2 text-right">Total</th>
                    <th className="px-2 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {editLineas.map((l, i) => {
                    const tot = (parseFloat(l.valor_unitario || "0") || 0) * (parseFloat(l.cantidad || "0") || 0) + (parseFloat(l.iva || "0") || 0);
                    return (
                      <tr key={i} className="border-b border-border/40">
                        <td className="px-2 py-1">
                          <select value={l.categoria} onChange={(e) => setLinea(i, "categoria", e.target.value)}
                            className="w-full rounded-sm border border-border bg-white px-1.5 py-1 text-[0.7rem]">
                            {CATEGORIAS.map((c) => <option key={c} value={c}>{c}</option>)}
                          </select>
                        </td>
                        <td className="px-2 py-1">
                          <input value={l.item} onChange={(e) => setLinea(i, "item", e.target.value)}
                            placeholder="Nombre del insumo/proceso"
                            className="w-full rounded-sm border border-border bg-white px-2 py-1 text-xs" />
                        </td>
                        <td className="px-2 py-1">
                          <input value={l.valor_unitario} onChange={(e) => setLinea(i, "valor_unitario", e.target.value)}
                            inputMode="decimal" placeholder="0"
                            className="w-24 rounded-sm border border-border bg-white px-2 py-1 text-right text-xs tabular" />
                        </td>
                        <td className="px-2 py-1">
                          <input value={l.cantidad} onChange={(e) => setLinea(i, "cantidad", e.target.value)}
                            inputMode="decimal" placeholder="1"
                            className="w-16 rounded-sm border border-border bg-white px-2 py-1 text-right text-xs tabular" />
                        </td>
                        <td className="px-2 py-1">
                          <input value={l.iva} onChange={(e) => setLinea(i, "iva", e.target.value)}
                            inputMode="decimal" placeholder="0"
                            className="w-20 rounded-sm border border-border bg-white px-2 py-1 text-right text-xs tabular" />
                        </td>
                        <td className="px-2 py-1 text-right tabular text-ink-900">
                          ${tot.toLocaleString("es-CO", { maximumFractionDigits: 0 })}
                        </td>
                        <td className="px-2 py-1 text-right">
                          <button onClick={() => setEditLineas((ls) => ls.filter((_, j) => j !== i))}
                            title="Quitar línea"
                            className="rounded-sm border border-border bg-card p-1 text-graphite hover:bg-terra-soft hover:text-terracotta">
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-border">
                    <td colSpan={5} className="px-2 py-2 text-right text-[0.7rem] uppercase tracking-widest text-graphite">Costo total (se recalcula al guardar)</td>
                    <td className="px-2 py-2 text-right tabular font-semibold text-ink-900">
                      ${editLineas.reduce((s, l) => s + (parseFloat(l.valor_unitario || "0") || 0) * (parseFloat(l.cantidad || "0") || 0) + (parseFloat(l.iva || "0") || 0), 0).toLocaleString("es-CO", { maximumFractionDigits: 0 })}
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : (
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
          )}
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

function FieldEdit({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="mb-1 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-sm border border-border bg-white px-3 py-2 text-sm" />
    </div>
  );
}
