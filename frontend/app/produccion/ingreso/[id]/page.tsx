"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Printer, ArrowLeft, Tag, Loader2, Pencil, Trash2, Check, X } from "lucide-react";
import { useAuth } from "@/components/auth-provider";

interface Rollo {
  id: string;
  codigo_interno: string;
  barcode: string;
  descripcion_tela: string;
  tono?: string;
  ancho?: number;
  metros_inicial: number;
  metros_disponible: number;
  lote_fabrica?: string;
  estado: string;
}

interface Ingreso {
  id: string;
  numero_ingreso: string;
  textilera: string;
  tipo_documento: string;
  numero_documento: string;
  fecha: string;
  total_rollos: number;
  total_metros: number;
  estado: string;
  orden_compra?: string | null;
  observaciones?: string | null;
  rollos: Rollo[];
}

export default function DetalleIngresoPage() {
  const params = useParams();
  const id = params?.id as string;
  const [seleccion, setSeleccion] = useState<Set<string>>(new Set());
  const [imprimiendo, setImprimiendo] = useState(false);
  const [errPdf, setErrPdf] = useState("");

  const q = useQuery<Ingreso>({
    queryKey: ["produccion", "ingreso", id],
    queryFn: () => api.get(`/api/produccion/ingreso/${id}`),
    enabled: !!id,
  });

  const router = useRouter();
  const qc = useQueryClient();
  const { user } = useAuth();
  const esAdmin = user?.rol === "admin";
  const [editando, setEditando] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [errAccion, setErrAccion] = useState("");

  const guardarCabecera = useMutation({
    mutationFn: () => api.patch(`/api/produccion/ingreso/${id}`, form),
    onSuccess: () => {
      setEditando(false);
      setErrAccion("");
      qc.invalidateQueries({ queryKey: ["produccion", "ingreso", id] });
    },
    onError: (e: Error) => setErrAccion(`No se pudo guardar: ${e.message}`),
  });
  const corregirRollo = useMutation({
    mutationFn: ({ rolloId, metros }: { rolloId: string; metros: number }) =>
      api.patch(`/api/produccion/ingreso/rollos/${rolloId}`, { metros_inicial: metros }),
    onSuccess: () => {
      setErrAccion("");
      qc.invalidateQueries({ queryKey: ["produccion", "ingreso", id] });
    },
    onError: (e: Error) => setErrAccion(`No se pudo corregir el rollo: ${e.message}`),
  });
  const eliminarIng = useMutation({
    mutationFn: () => api.del(`/api/produccion/ingreso/${id}`),
    onSuccess: () => router.push("/produccion/ingreso"),
    onError: (e: Error) => setErrAccion(`No se pudo eliminar: ${e.message}`),
  });

  function abrirEdicion(ing: Ingreso) {
    setForm({
      textilera: ing.textilera,
      numero_documento: ing.numero_documento,
      fecha: ing.fecha,
      orden_compra: ing.orden_compra || "",
      observaciones: ing.observaciones || "",
    });
    setEditando(true);
  }
  function corregirMetros(r: Rollo) {
    if (r.metros_disponible !== r.metros_inicial || r.estado !== "disponible") {
      setErrAccion(`El rollo ${r.codigo_interno} ya fue consumido — no se pueden cambiar los metros.`);
      return;
    }
    const v = window.prompt(`Metros del rollo ${r.codigo_interno}:`, String(r.metros_inicial));
    if (v === null) return;
    const n = parseFloat(v.replace(",", "."));
    if (!n || n <= 0) { setErrAccion("Metros inválidos."); return; }
    corregirRollo.mutate({ rolloId: r.id, metros: n });
  }
  function confirmarEliminar(ing: Ingreso) {
    if (!window.confirm(
      `¿Eliminar el ingreso ${ing.numero_ingreso} completo (${ing.total_rollos} rollos, ${ing.total_metros} m)?\n\n` +
      "Se revierte el inventario y se borran los rollos. Solo es posible si ningún rollo fue consumido. No se puede deshacer."
    )) return;
    eliminarIng.mutate();
  }

  // Un solo PDF con UNA PÁGINA POR ROLLO — cada etiqueta con su info.
  async function imprimirEtiquetas(rolloIds: string[]) {
    if (rolloIds.length === 0) return;
    setImprimiendo(true);
    setErrPdf("");
    try {
      const r = await fetch(`${API_BASE}/api/produccion/rollos/etiquetas`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${getToken()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ rollo_ids: rolloIds }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      window.open(URL.createObjectURL(blob), "_blank");
    } catch (e) {
      setErrPdf(`No se pudo generar el PDF: ${e instanceof Error ? e.message : "error"}`);
    } finally {
      setImprimiendo(false);
    }
  }

  function toggle(rid: string) {
    setSeleccion((prev) => {
      const s = new Set(prev);
      if (s.has(rid)) s.delete(rid); else s.add(rid);
      return s;
    });
  }

  if (q.isLoading) return <LoadingState label="Cargando ingreso…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const ing = q.data;
  const todosMarcados = ing.rollos.length > 0 && ing.rollos.every((r) => seleccion.has(r.id));

  function toggleTodos() {
    setSeleccion(todosMarcados ? new Set() : new Set(ing.rollos.map((r) => r.id)));
  }

  return (
    <PageShell
      title={`Ingreso ${ing.numero_ingreso}`}
      subtitle={`${ing.textilera} · ${ing.tipo_documento} ${ing.numero_documento} · ${ing.fecha}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href="/produccion/ingreso" className="inline-flex items-center gap-1 text-xs text-graphite hover:text-ink-900">
          <ArrowLeft className="h-3.5 w-3.5" /> Volver a ingresos
        </Link>
        <div className="flex items-center gap-2">
          <button onClick={() => (editando ? setEditando(false) : abrirEdicion(ing))}
            className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-3 py-1.5 text-xs font-medium text-ink-900 transition-colors hover:bg-cloud">
            {editando ? <><X className="h-3.5 w-3.5" /> Cancelar</> : <><Pencil className="h-3.5 w-3.5" /> Editar</>}
          </button>
          {esAdmin && (
            <button onClick={() => confirmarEliminar(ing)} disabled={eliminarIng.isPending}
              title="Eliminar ingreso completo (revierte inventario) — solo administrador"
              className="inline-flex items-center gap-1.5 rounded-sm border border-terracotta/40 bg-card px-3 py-1.5 text-xs font-medium text-terracotta transition-colors hover:bg-terracotta/[0.06] disabled:opacity-50">
              {eliminarIng.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              Eliminar ingreso
            </button>
          )}
        </div>
      </div>

      {errAccion && (
        <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
          {errAccion}
        </div>
      )}

      {editando && (
        <Card>
          <CardContent className="space-y-3 p-4">
            <p className="section-label">Editar datos del ingreso</p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {([
                ["textilera", "Textilera"],
                ["numero_documento", "N° documento"],
                ["fecha", "Fecha (YYYY-MM-DD)"],
                ["orden_compra", "Orden de compra"],
                ["observaciones", "Observaciones"],
              ] as const).map(([k, label]) => (
                <div key={k} className={k === "observaciones" ? "md:col-span-3" : ""}>
                  <label className="mb-1 block text-[0.7rem] uppercase tracking-[0.1em] text-graphite">{label}</label>
                  <input value={form[k] || ""} onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
                    className="w-full rounded-sm border border-border bg-card px-2 py-1.5 text-sm" />
                </div>
              ))}
            </div>
            <button onClick={() => guardarCabecera.mutate()} disabled={guardarCabecera.isPending}
              className="inline-flex items-center gap-1.5 rounded-sm bg-navy-600 px-3.5 py-1.5 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-50">
              {guardarCabecera.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              Guardar cambios
            </button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-4 grid grid-cols-2 md:grid-cols-4 gap-4">
          <Kpi label="Rollos"          value={ing.total_rollos.toString()} />
          <Kpi label="Metros"          value={ing.total_metros.toLocaleString("es-CO", { maximumFractionDigits: 2 })} />
          <Kpi label="Fecha"           value={ing.fecha} />
          <Kpi label="Estado"          value={ing.estado.replace(/_/g, " ")} />
        </CardContent>
      </Card>

      {errPdf && (
        <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
          {errPdf}
        </div>
      )}

      <Card>
        <CardContent className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-border">
            <p className="section-label">Rollos ({ing.rollos.length})</p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => imprimirEtiquetas(Array.from(seleccion))}
                disabled={imprimiendo || seleccion.size === 0}
                className="inline-flex items-center gap-1.5 rounded-sm border border-navy-600 bg-white px-3 py-1.5 text-xs font-semibold uppercase tracking-widest text-navy-600 hover:bg-navy-600/5 disabled:opacity-40"
              >
                {imprimiendo ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Printer className="h-3.5 w-3.5" />}
                Imprimir seleccionadas ({seleccion.size})
              </button>
              <button
                onClick={() => imprimirEtiquetas(ing.rollos.map((r) => r.id))}
                disabled={imprimiendo || ing.rollos.length === 0}
                className="inline-flex items-center gap-1.5 rounded-sm bg-navy-600 px-3 py-1.5 text-xs font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40"
              >
                {imprimiendo ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Printer className="h-3.5 w-3.5" />}
                Imprimir todas
              </button>
            </div>
          </div>
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-cloud/60 border-b border-border">
              <tr className="text-left text-[0.7rem] uppercase tracking-[0.12em] text-graphite">
                <th className="px-4 py-2 w-[36px]">
                  <input type="checkbox" checked={todosMarcados} onChange={toggleTodos}
                    aria-label="Seleccionar todos los rollos"
                    className="h-4 w-4 cursor-pointer rounded border-graphite/40" />
                </th>
                <th className="px-4 py-2">Código interno</th>
                <th className="px-4 py-2">Descripción</th>
                <th className="px-4 py-2">Tono</th>
                <th className="px-4 py-2 text-right">Metros</th>
                <th className="px-4 py-2">Lote</th>
                <th className="px-4 py-2">Estado</th>
                <th className="px-4 py-2 text-right">Etiqueta</th>
              </tr>
            </thead>
            <tbody>
              {ing.rollos.map((r) => (
                <tr key={r.id}
                  className={`border-b border-border hover:bg-cloud/50 ${seleccion.has(r.id) ? "bg-navy-600/[0.04]" : ""}`}>
                  <td className="px-4 py-2">
                    <input type="checkbox" checked={seleccion.has(r.id)} onChange={() => toggle(r.id)}
                      aria-label={`Seleccionar rollo ${r.codigo_interno}`}
                      className="h-4 w-4 cursor-pointer rounded border-graphite/40" />
                  </td>
                  <td className="px-4 py-2 tabular">
                    <div className="font-semibold text-navy-600">{r.codigo_interno}</div>
                    <div className="text-[0.7rem] text-graphite mt-0.5">Barcode: {r.barcode}</div>
                  </td>
                  <td className="px-4 py-2">{r.descripcion_tela}</td>
                  <td className="px-4 py-2 text-graphite">{r.tono || "—"}</td>
                  <td className="px-4 py-2 text-right tabular">
                    <span className="inline-flex items-center gap-1.5">
                      {r.metros_disponible} / {r.metros_inicial}
                      <button onClick={() => corregirMetros(r)} title="Corregir metros (solo si el rollo está intacto)"
                        className="text-graphite transition-colors hover:text-navy-600">
                        <Pencil className="h-3 w-3" />
                      </button>
                    </span>
                  </td>
                  <td className="px-4 py-2 text-graphite text-xs">{r.lote_fabrica || "—"}</td>
                  <td className="px-4 py-2">
                    <Badge tone={r.estado === "disponible" ? "normal" : "info"}>{r.estado}</Badge>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => imprimirEtiquetas([r.id])}
                      disabled={imprimiendo}
                      className="inline-flex items-center gap-1 text-xs text-navy-600 hover:text-navy-700 disabled:opacity-40"
                    >
                      <Tag className="h-3 w-3" /> PDF
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </CardContent>
      </Card>
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
