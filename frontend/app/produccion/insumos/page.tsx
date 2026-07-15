"use client";

/**
 * Inventario de INSUMOS — cierres, botones, marquillas, bolsas…
 * Entradas: ingreso manual acá. Salidas: AUTOMÁTICAS al marcar una remisión
 * como recogida/despachada (descuenta lo calculado del precosteo).
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { getToken } from "@/lib/auth";
import { fmtDateTime } from "@/lib/utils";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Plus, Loader2, AlertCircle, Save, Trash2, PackagePlus, QrCode, Pencil, Check, X } from "lucide-react";

interface Insumo {
  id: string;
  nombre: string;
  categoria: string;
  unidad: string;
  codigo?: string;
  cantidad_disponible: number;
}

interface Movimiento {
  id: string;
  tipo: string;
  cantidad: number;
  doc_ref?: string;
  nota?: string;
  usuario?: string;
  created_at: string;
  insumo?: { nombre: string; unidad: string };
}

interface LineaIngreso {
  nombre: string;
  categoria: string;
  cantidad: string;
}

const CATEGORIAS = ["INSUMO CONFECCION", "INSUMO TERMINACION", "OTRO"];
const CAT_LABEL: Record<string, string> = {
  "INSUMO CONFECCION": "Confección",
  "INSUMO TERMINACION": "Terminación",
  OTRO: "Otro",
};

export default function InsumosPage() {
  const qc = useQueryClient();
  const [mostrarIngreso, setMostrarIngreso] = useState(false);
  const [docRef, setDocRef] = useState("");
  const [lineas, setLineas] = useState<LineaIngreso[]>([
    { nombre: "", categoria: "INSUMO CONFECCION", cantidad: "" },
  ]);
  const [err, setErr] = useState("");
  // Selección de insumos para imprimir etiquetas QR (cajas/estantes)
  const [seleccion, setSeleccion] = useState<Set<string>>(new Set());
  const [imprimiendo, setImprimiendo] = useState(false);

  function toggleSeleccion(id: string) {
    setSeleccion((prev) => {
      const s = new Set(prev);
      if (s.has(id)) s.delete(id); else s.add(id);
      return s;
    });
  }

  async function imprimirEtiquetas(ids: string[]) {
    if (ids.length === 0) return;
    setImprimiendo(true);
    setErr("");
    try {
      const r = await fetch(`${API_BASE}/api/produccion/insumos/etiquetas`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
        body: JSON.stringify({ insumo_ids: ids }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      window.open(URL.createObjectURL(blob), "_blank");
    } catch (e) {
      setErr(`No se pudo generar el PDF de etiquetas: ${e instanceof Error ? e.message : "error"}`);
    } finally {
      setImprimiendo(false);
    }
  }

  const q = useQuery<{ insumos: Insumo[] }>({
    queryKey: ["produccion", "insumos"],
    queryFn: () => api.get("/api/produccion/insumos"),
  });
  const movQ = useQuery<{ movimientos: Movimiento[] }>({
    queryKey: ["produccion", "insumos", "movimientos"],
    queryFn: () => api.get("/api/produccion/insumos/movimientos?limit=50"),
  });

  const { user } = useAuth();
  const esAdmin = user?.rol === "admin";

  const [editId, setEditId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<{ nombre: string; categoria: string; unidad: string; cantidad: string }>({ nombre: "", categoria: "", unidad: "", cantidad: "" });
  function abrirEdicion(i: Insumo) {
    setEditForm({ nombre: i.nombre, categoria: i.categoria, unidad: i.unidad || "", cantidad: String(i.cantidad_disponible) });
    setEditId(i.id);
    setErr("");
  }
  const editar = useMutation({
    mutationFn: (id: string) => api.patch(`/api/produccion/insumos/${id}`, {
      nombre: editForm.nombre.trim(),
      categoria: editForm.categoria,
      unidad: editForm.unidad.trim() || "und",
      cantidad_disponible: editForm.cantidad === "" ? undefined : parseFloat(editForm.cantidad),
    }),
    onSuccess: () => { setEditId(null); setErr(""); qc.invalidateQueries({ queryKey: ["produccion", "insumos"] }); },
    onError: (e: Error) => setErr(`No se pudo editar: ${e.message}`),
  });

  const corregirMov = useMutation({
    mutationFn: ({ id, cantidad }: { id: string; cantidad: number }) =>
      api.patch(`/api/produccion/insumos/movimientos/${id}`, { cantidad }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["produccion", "insumos"] });
    },
    onError: (e: Error) => setErr(`No se pudo corregir: ${e.message}`),
  });
  const eliminarMov = useMutation({
    mutationFn: (id: string) => api.del(`/api/produccion/insumos/movimientos/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["produccion", "insumos"] });
    },
    onError: (e: Error) => setErr(`No se pudo eliminar: ${e.message}`),
  });
  function corregirIngreso(id: string, actual: number, nombre: string) {
    const v = window.prompt(`Nueva cantidad para el ingreso de ${nombre}:`, String(actual));
    if (v === null) return;
    const n = parseFloat(v.replace(",", "."));
    if (!n || n <= 0) { setErr("Cantidad inválida."); return; }
    corregirMov.mutate({ id, cantidad: n });
  }
  function eliminarIngreso(id: string, nombre: string, cantidad: number) {
    if (!window.confirm(`¿Eliminar el ingreso de ${cantidad} de ${nombre}?\n\nEl stock se revierte. Esta acción requiere autorización de administrador y no se puede deshacer.`)) return;
    eliminarMov.mutate(id);
  }

  const ingresar = useMutation({
    mutationFn: () => {
      const items = lineas
        .filter((l) => l.nombre.trim() && parseFloat(l.cantidad || "0") > 0)
        .map((l) => ({
          nombre: l.nombre.trim(),
          categoria: l.categoria,
          cantidad: parseFloat(l.cantidad),
          unidad: "und",
        }));
      if (items.length === 0) throw new Error("Llena al menos un insumo con cantidad.");
      return api.post("/api/produccion/insumos/ingreso", { items, doc_ref: docRef.trim() || null });
    },
    onSuccess: () => {
      setLineas([{ nombre: "", categoria: "INSUMO CONFECCION", cantidad: "" }]);
      setDocRef("");
      setMostrarIngreso(false);
      setErr("");
      qc.invalidateQueries({ queryKey: ["produccion", "insumos"] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  function setLinea(i: number, campo: keyof LineaIngreso, v: string) {
    setLineas((prev) => prev.map((l, idx) => (idx === i ? { ...l, [campo]: v } : l)));
  }

  if (q.isLoading) return <LoadingState label="Cargando insumos…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const insumos = q.data?.insumos || [];
  const negativos = insumos.filter((i) => i.cantidad_disponible < 0);

  return (
    <PageShell title="Insumos" subtitle="Entradas manuales · salidas automáticas al entregar remisiones">
      <div className="flex items-center justify-between">
        <p className="text-xs text-graphite">{insumos.length} insumo(s) en inventario</p>
        <button onClick={() => setMostrarIngreso(true)}
          className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700">
          <PackagePlus className="h-3.5 w-3.5" /> Registrar ingreso
        </button>
      </div>

      {seleccion.size > 0 && (
        <div className="sticky top-2 z-20 flex items-center justify-between gap-3 rounded-sm border border-navy-600/40 bg-navy-600/[0.06] backdrop-blur px-4 py-2.5">
          <p className="text-xs font-semibold text-navy-600 tabular">{seleccion.size} insumo(s) seleccionado(s)</p>
          <div className="flex items-center gap-2">
            <button onClick={() => setSeleccion(new Set())}
              className="text-[0.65rem] uppercase tracking-widest text-graphite hover:text-ink-900">Limpiar</button>
            <button onClick={() => imprimirEtiquetas(Array.from(seleccion))} disabled={imprimiendo}
              className="inline-flex items-center gap-1.5 rounded-sm bg-navy-600 px-3 py-1.5 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40">
              {imprimiendo ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <QrCode className="h-3.5 w-3.5" />}
              Imprimir etiquetas QR
            </button>
          </div>
        </div>
      )}

      {negativos.length > 0 && (
        <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
          {negativos.length} insumo(s) en negativo — se entregaron remisiones sin haber registrado
          el ingreso: {negativos.map((n) => n.nombre).join(", ")}. Registra los ingresos para cuadrar.
        </div>
      )}

      {mostrarIngreso && (
        <Card>
          <CardContent className="p-5 space-y-3">
            <p className="section-label">Ingreso de insumos</p>
            <div className="max-w-xs">
              <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                Documento (factura/remisión del proveedor)
              </label>
              <input value={docRef} onChange={(e) => setDocRef(e.target.value)} placeholder="FC-1234 (opcional)"
                className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
            </div>
            <div className="space-y-2">
              {lineas.map((l, i) => (
                <div key={i} className="grid grid-cols-1 md:grid-cols-[1fr_180px_120px_36px] gap-2 items-center">
                  <input value={l.nombre} onChange={(e) => setLinea(i, "nombre", e.target.value)}
                    placeholder="Ej. Cierre, Botón 27 L, Bolsa…" list="insumos-conocidos"
                    className="rounded-sm border border-border bg-white px-3 py-2 text-sm" />
                  <select value={l.categoria} onChange={(e) => setLinea(i, "categoria", e.target.value)}
                    className="rounded-sm border border-border bg-white px-2 py-2 text-xs">
                    {CATEGORIAS.map((c) => <option key={c} value={c}>{CAT_LABEL[c]}</option>)}
                  </select>
                  <input value={l.cantidad} onChange={(e) => setLinea(i, "cantidad", e.target.value)}
                    inputMode="decimal" placeholder="Cantidad"
                    className="rounded-sm border border-border bg-white px-3 py-2 text-sm text-right tabular" />
                  <button type="button" aria-label="Quitar línea"
                    onClick={() => setLineas((prev) => prev.filter((_, idx) => idx !== i))}
                    disabled={lineas.length === 1}
                    className="p-2 text-terracotta hover:text-crimson disabled:opacity-30">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
              <datalist id="insumos-conocidos">
                {insumos.map((i) => <option key={i.id} value={i.nombre} />)}
              </datalist>
              <button type="button"
                onClick={() => setLineas((prev) => [...prev, { nombre: "", categoria: prev[prev.length - 1]?.categoria || "INSUMO CONFECCION", cantidad: "" }])}
                className="inline-flex items-center gap-1 text-xs text-navy-600 hover:underline">
                <Plus className="h-3.5 w-3.5" /> Agregar línea
              </button>
            </div>
            {err && (
              <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
                <AlertCircle className="h-3.5 w-3.5" /> {err}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => { setMostrarIngreso(false); setErr(""); }}
                className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud">
                Cancelar
              </button>
              <button onClick={() => ingresar.mutate()} disabled={ingresar.isPending}
                className="inline-flex items-center gap-2 rounded-sm bg-teal px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
                {ingresar.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Guardar ingreso
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Inventario */}
      <Card>
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border">
            <p className="section-label">Inventario actual</p>
          </div>
          {insumos.length === 0 ? (
            <div className="p-10 text-center text-sm text-graphite">
              Sin insumos aún. Registra el primer ingreso.
            </div>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2 w-[36px]">
                    <input type="checkbox"
                      checked={insumos.length > 0 && seleccion.size === insumos.length}
                      onChange={() => setSeleccion(seleccion.size === insumos.length ? new Set() : new Set(insumos.map((x) => x.id)))}
                      aria-label="Seleccionar todos" className="h-4 w-4 cursor-pointer" />
                  </th>
                  <th className="px-4 py-2">Código</th>
                  <th className="px-4 py-2">Insumo</th>
                  <th className="px-4 py-2">Categoría</th>
                  <th className="px-4 py-2 text-right">Disponible</th>
                  <th className="px-4 py-2">Unidad</th>
                  <th className="px-4 py-2 text-right"></th>
                </tr>
              </thead>
              <tbody>
                {insumos.map((i) => (
                  <tr key={i.id} className={`border-b border-border/40 ${seleccion.has(i.id) ? "bg-navy-600/[0.05]" : "hover:bg-cloud/30"}`}>
                    <td className="px-4 py-2">
                      <input type="checkbox" checked={seleccion.has(i.id)} onChange={() => toggleSeleccion(i.id)}
                        aria-label={`Seleccionar ${i.nombre}`} className="h-4 w-4 cursor-pointer" />
                    </td>
                    <td className="px-4 py-2 tabular text-navy-600 font-semibold">{i.codigo || "—"}</td>
                    {editId === i.id ? (
                      <>
                        <td className="px-4 py-2">
                          <input value={editForm.nombre} onChange={(e) => setEditForm((f) => ({ ...f, nombre: e.target.value }))}
                            className="w-full rounded-sm border border-navy-600/50 bg-card px-2 py-1 text-xs" />
                        </td>
                        <td className="px-4 py-2">
                          <select value={editForm.categoria} onChange={(e) => setEditForm((f) => ({ ...f, categoria: e.target.value }))}
                            className="rounded-sm border border-border bg-card px-2 py-1 text-xs">
                            {CATEGORIAS.map((c) => <option key={c} value={c}>{CAT_LABEL[c] || c}</option>)}
                          </select>
                        </td>
                        <td className="px-4 py-2 text-right">
                          <input type="number" step="0.001" value={editForm.cantidad} onChange={(e) => setEditForm((f) => ({ ...f, cantidad: e.target.value }))}
                            className="w-24 rounded-sm border border-border bg-card px-2 py-1 text-right text-xs tabular" />
                        </td>
                        <td className="px-4 py-2">
                          <input value={editForm.unidad} onChange={(e) => setEditForm((f) => ({ ...f, unidad: e.target.value }))}
                            className="w-16 rounded-sm border border-border bg-card px-2 py-1 text-xs" />
                        </td>
                        <td className="px-4 py-2 text-right">
                          <span className="inline-flex items-center gap-2">
                            <button onClick={() => editar.mutate(i.id)} disabled={editar.isPending} title="Guardar"
                              className="text-teal hover:text-teal/70 disabled:opacity-40">
                              {editar.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                            </button>
                            <button onClick={() => setEditId(null)} title="Cancelar" className="text-graphite hover:text-terracotta">
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </span>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-4 py-2 font-semibold text-ink-900">{i.nombre}</td>
                        <td className="px-4 py-2 text-graphite">{CAT_LABEL[i.categoria] || i.categoria}</td>
                        <td className={`px-4 py-2 text-right tabular font-bold ${i.cantidad_disponible < 0 ? "text-terracotta" : i.cantidad_disponible === 0 ? "text-graphite" : "text-ink-900"}`}>
                          {i.cantidad_disponible.toLocaleString("es-CO")}
                        </td>
                        <td className="px-4 py-2 text-graphite">{i.unidad}</td>
                        <td className="px-4 py-2 text-right">
                          <button onClick={() => abrirEdicion(i)} title="Editar insumo"
                            className="text-graphite transition-colors hover:text-navy-600">
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Movimientos recientes */}
      <Card>
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border">
            <p className="section-label">Últimos movimientos</p>
          </div>
          {(movQ.data?.movimientos || []).length === 0 ? (
            <div className="p-8 text-center text-xs text-graphite">Sin movimientos.</div>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Fecha</th>
                  <th className="px-4 py-2">Insumo</th>
                  <th className="px-4 py-2">Tipo</th>
                  <th className="px-4 py-2 text-right">Cantidad</th>
                  <th className="px-4 py-2">Documento</th>
                  <th className="px-4 py-2 text-right"></th>
                </tr>
              </thead>
              <tbody>
                {(movQ.data?.movimientos || []).map((m) => (
                  <tr key={m.id} className="border-b border-border/40 hover:bg-cloud/30">
                    <td className="px-4 py-2 text-graphite tabular text-[0.65rem]">{fmtDateTime(m.created_at)}</td>
                    <td className="px-4 py-2 text-ink-900">{m.insumo?.nombre || "—"}</td>
                    <td className="px-4 py-2">
                      <span className={`rounded-sm px-1.5 py-0.5 text-[0.68rem] font-bold uppercase tracking-widest ${m.tipo === "ingreso" ? "bg-teal/10 text-teal" : m.tipo === "salida" ? "bg-terracotta/10 text-terracotta" : "bg-cloud text-graphite"}`}>
                        {m.tipo}
                      </span>
                    </td>
                    <td className={`px-4 py-2 text-right tabular font-semibold ${m.cantidad < 0 ? "text-terracotta" : "text-teal"}`}>
                      {m.cantidad > 0 ? "+" : ""}{m.cantidad.toLocaleString("es-CO")}
                    </td>
                    <td className="px-4 py-2 text-graphite">{m.doc_ref || "—"}</td>
                    <td className="px-4 py-2 text-right">
                      {m.tipo === "ingreso" && (
                        <span className="inline-flex items-center gap-2.5">
                          <button onClick={() => corregirIngreso(m.id, m.cantidad, m.insumo?.nombre || "insumo")}
                            title="Corregir cantidad del ingreso"
                            className="text-graphite transition-colors hover:text-navy-600">
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          {esAdmin && (
                            <button onClick={() => eliminarIngreso(m.id, m.insumo?.nombre || "insumo", m.cantidad)}
                              title="Eliminar ingreso (revierte stock) — solo administrador"
                              className="text-graphite transition-colors hover:text-terracotta">
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
