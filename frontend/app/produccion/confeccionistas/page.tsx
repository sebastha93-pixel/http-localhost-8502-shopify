"use client";

/**
 * Directorio de confeccionistas (talleres). Alta / edición inline.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Plus, Loader2, AlertCircle, Save, X, Pencil, Check } from "lucide-react";

interface Confeccionista {
  id: string;
  nombre: string;
  telefono?: string;
  direccion?: string;
  tipo?: string;
  activo: boolean;
}

export default function ConfeccionistasPage() {
  const qc = useQueryClient();
  const [mostrarNuevo, setMostrarNuevo] = useState(false);
  const [nombre, setNombre] = useState("");
  const [telefono, setTelefono] = useState("");
  const [direccion, setDireccion] = useState("");
  const [tipo, setTipo] = useState("confeccion");
  const [err, setErr] = useState("");
  const [incluirInactivos, setIncluirInactivos] = useState(false);

  const q = useQuery<{ confeccionistas: Confeccionista[] }>({
    queryKey: ["produccion", "confeccionistas", incluirInactivos],
    queryFn: () => api.get(`/api/produccion/confeccionistas?incluir_inactivos=${incluirInactivos}`),
  });

  const crear = useMutation({
    mutationFn: () => api.post("/api/produccion/confeccionistas", {
      nombre: nombre.trim(),
      telefono: telefono.trim() || null,
      direccion: direccion.trim() || null,
      tipo,
    }),
    onSuccess: () => {
      setNombre(""); setTelefono(""); setDireccion(""); setTipo("confeccion");
      setMostrarNuevo(false);
      setErr("");
      qc.invalidateQueries({ queryKey: ["produccion", "confeccionistas"] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  if (q.isLoading) return <LoadingState label="Cargando confeccionistas…" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const lista = q.data?.confeccionistas || [];

  return (
    <PageShell title="Confeccionistas" subtitle="Directorio de talleres">
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-xs text-graphite">
          <input type="checkbox" checked={incluirInactivos} onChange={(e) => setIncluirInactivos(e.target.checked)} />
          Incluir inactivos
        </label>
        <button onClick={() => setMostrarNuevo(true)}
          className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700">
          <Plus className="h-3.5 w-3.5" /> Nuevo confeccionista
        </button>
      </div>

      {mostrarNuevo && (
        <Card>
          <CardContent className="p-5 space-y-3">
            <p className="section-label">Nuevo confeccionista</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Field label="Nombre *"    value={nombre}    onChange={setNombre}    placeholder="Taller Alba" />
              <Field label="Teléfono"    value={telefono}  onChange={setTelefono}  placeholder="3XXXXXXXXX" />
              <Field label="Dirección"   value={direccion} onChange={setDireccion} placeholder="Cll 10 #5-32, Medellín" />
            </div>
            <div>
              <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">Tipo de proveedor *</label>
              <div className="flex gap-4 text-sm">
                <label className="inline-flex items-center gap-2">
                  <input type="radio" name="tipo" value="confeccion" checked={tipo === "confeccion"} onChange={() => setTipo("confeccion")} />
                  Confección
                </label>
                <label className="inline-flex items-center gap-2">
                  <input type="radio" name="tipo" value="terminacion" checked={tipo === "terminacion"} onChange={() => setTipo("terminacion")} />
                  Terminación
                </label>
              </div>
            </div>
            {err && (
              <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
                <AlertCircle className="h-3.5 w-3.5" /> {err}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => { setMostrarNuevo(false); setErr(""); }}
                className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud">
                <X className="inline h-3.5 w-3.5 mr-1" /> Cancelar
              </button>
              <button onClick={() => crear.mutate()} disabled={crear.isPending || !nombre.trim()}
                className="inline-flex items-center gap-2 rounded-sm bg-teal px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
                {crear.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Guardar
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {lista.length === 0 ? (
            <div className="p-10 text-center text-sm text-graphite">
              No hay confeccionistas registrados aún.
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Nombre</th>
                  <th className="px-4 py-2">Tipo</th>
                  <th className="px-4 py-2">Teléfono</th>
                  <th className="px-4 py-2">Dirección</th>
                  <th className="px-4 py-2">Estado</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {lista.map((c) => <FilaConfeccionista key={c.id} c={c} />)}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}

function FilaConfeccionista({ c }: { c: Confeccionista }) {
  const qc = useQueryClient();
  const [editando, setEditando] = useState(false);
  const [nombre, setNombre] = useState(c.nombre);
  const [telefono, setTelefono] = useState(c.telefono || "");
  const [direccion, setDireccion] = useState(c.direccion || "");
  const [tipo, setTipo] = useState(c.tipo || "confeccion");

  const mut = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch(`/api/produccion/confeccionistas/${c.id}`, body),
    onSuccess: () => {
      setEditando(false);
      qc.invalidateQueries({ queryKey: ["produccion", "confeccionistas"] });
    },
  });

  if (editando) {
    return (
      <tr className="border-b border-border bg-cloud/30">
        <td className="px-4 py-2">
          <input value={nombre} onChange={(e) => setNombre(e.target.value)}
            className="w-full rounded-sm border border-border bg-white px-2 py-1 text-xs" />
        </td>
        <td className="px-4 py-2">
          <select value={tipo} onChange={(e) => setTipo(e.target.value)}
            className="w-full rounded-sm border border-border bg-white px-2 py-1 text-xs">
            <option value="confeccion">Confección</option>
            <option value="terminacion">Terminación</option>
          </select>
        </td>
        <td className="px-4 py-2">
          <input value={telefono} onChange={(e) => setTelefono(e.target.value)}
            className="w-full rounded-sm border border-border bg-white px-2 py-1 text-xs" />
        </td>
        <td className="px-4 py-2">
          <input value={direccion} onChange={(e) => setDireccion(e.target.value)}
            className="w-full rounded-sm border border-border bg-white px-2 py-1 text-xs" />
        </td>
        <td className="px-4 py-2"><Badge tone={c.activo ? "normal" : "neutral"}>{c.activo ? "Activo" : "Inactivo"}</Badge></td>
        <td className="px-4 py-2 text-right">
          <button onClick={() => mut.mutate({ nombre, telefono, direccion, tipo })} disabled={mut.isPending}
            className="text-teal hover:text-ink-900 mr-2" title="Guardar">
            {mut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          </button>
          <button onClick={() => setEditando(false)} className="text-graphite hover:text-ink-900" title="Cancelar">
            <X className="h-3.5 w-3.5" />
          </button>
        </td>
      </tr>
    );
  }

  return (
    <tr className="border-b border-border/40 hover:bg-cloud/30">
      <td className="px-4 py-2 font-semibold text-ink-900">{c.nombre}</td>
      <td className="px-4 py-2">
        <Badge tone={c.tipo === "terminacion" ? "info" : "neutral"}>
          {c.tipo === "terminacion" ? "Terminación" : "Confección"}
        </Badge>
      </td>
      <td className="px-4 py-2 text-graphite">{c.telefono || "—"}</td>
      <td className="px-4 py-2 text-graphite">{c.direccion || "—"}</td>
      <td className="px-4 py-2"><Badge tone={c.activo ? "normal" : "neutral"}>{c.activo ? "Activo" : "Inactivo"}</Badge></td>
      <td className="px-4 py-2 text-right">
        <button onClick={() => setEditando(true)} className="text-graphite hover:text-navy-600 mr-2" title="Editar">
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button onClick={() => mut.mutate({ activo: !c.activo })}
          className="text-graphite hover:text-terracotta text-[0.65rem] font-semibold uppercase tracking-widest">
          {c.activo ? "Desactivar" : "Activar"}
        </button>
      </td>
    </tr>
  );
}

function Field({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
    </div>
  );
}
