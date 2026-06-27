"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import {
  ROL_LABEL, esAdmin, GRUPOS, GRUPO_LABEL, ACCIONES, ACCION_LABEL,
  type Rol, type Accion,
} from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, UserPlus, Shield, Edit, Check, X } from "lucide-react";

interface Usuario {
  id: string;
  email: string;
  nombre: string;
  cargo?: string;
  rol: Rol;
  permisos?: Record<string, string[]>;
  activo: boolean;
  creado_en?: string;
}

const ROLES_NUEVOS: Rol[] = ["admin", "lector", "user"];

// Preset por defecto cuando se crea un user: solo ver en todos los grupos.
// El admin lo ajusta luego con la matriz.
function permisosPorDefecto(): Record<string, string[]> {
  const p: Record<string, string[]> = {};
  for (const g of GRUPOS) p[g] = ["ver"];
  return p;
}

export default function UsuariosPage() {
  const { user } = useAuth();
  const qc = useQueryClient();

  const usuariosQ = useQuery({
    queryKey: ["usuarios"],
    queryFn: () => api.get<Usuario[]>("/api/auth/usuarios"),
    enabled: esAdmin(user),
  });

  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);

  if (!esAdmin(user)) {
    return (
      <PageShell title="Usuarios">
        <Card className="border-terracotta/25 bg-terracotta/[0.03]">
          <CardContent className="p-10 text-center">
            <Shield className="mx-auto mb-3 h-10 w-10 text-terracotta" />
            <p className="font-display text-base font-medium text-ink-900">Acceso restringido</p>
            <p className="mt-1 text-sm text-graphite">Solo administradores pueden gestionar usuarios.</p>
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  if (usuariosQ.isLoading) return <LoadingState label="Cargando usuarios…" />;
  if (usuariosQ.error) return <ErrorState error={usuariosQ.error} onRetry={() => usuariosQ.refetch()} />;

  const usuarios = usuariosQ.data || [];

  return (
    <PageShell
      title="Usuarios"
      subtitle={`${usuarios.length} usuarios · gestión de accesos y permisos`}
      onRefresh={() => usuariosQ.refetch()}
    >
      <div className="flex justify-end">
        <button
          onClick={() => { setShowForm(!showForm); setEditId(null); }}
          className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-white transition-colors hover:bg-navy-700"
        >
          <UserPlus className="h-3.5 w-3.5" />
          {showForm ? "Cancelar" : "Nuevo usuario"}
        </button>
      </div>

      {showForm && (
        <UsuarioForm
          onClose={() => setShowForm(false)}
          onSuccess={() => {
            setShowForm(false);
            qc.invalidateQueries({ queryKey: ["usuarios"] });
          }}
        />
      )}

      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="bg-cloud/60 border-b border-border">
              <tr>
                {[
                  ["Nombre", "left"], ["Cargo", "left"], ["Email", "left"],
                  ["Rol", "left"], ["Estado", "left"], ["Acciones", "right"],
                ].map(([h, align]) => (
                  <th key={h} className={`px-4 py-3 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite text-${align}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {usuarios.map((u) => (
                <UsuarioRow
                  key={u.id}
                  u={u}
                  isEditing={editId === u.id}
                  isCurrentUser={user?.id === u.id}
                  onEdit={() => setEditId(editId === u.id ? null : u.id)}
                  onSaved={() => {
                    setEditId(null);
                    qc.invalidateQueries({ queryKey: ["usuarios"] });
                  }}
                />
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </PageShell>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Formulario crear usuario
// ──────────────────────────────────────────────────────────────────────

function UsuarioForm({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [email, setEmail] = useState("");
  const [nombre, setNombre] = useState("");
  const [cargo, setCargo] = useState("");
  const [password, setPassword] = useState("");
  const [rol, setRol] = useState<Rol>("user");
  const [permisos, setPermisos] = useState<Record<string, string[]>>(permisosPorDefecto());
  const [err, setErr] = useState("");

  const mut = useMutation({
    mutationFn: () => api.post<Usuario>("/api/auth/usuarios", {
      email, nombre, cargo, password, rol,
      permisos: rol === "user" ? permisos : {},
    }),
    onSuccess,
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <Card>
      <CardContent className="p-5 space-y-4">
        <p className="section-label">Crear usuario</p>
        <form
          onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }}
          className="space-y-4"
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Nombre completo" value={nombre} onChange={setNombre} required placeholder="ej. Kelly Pérez" />
            <Field label="Cargo en la empresa" value={cargo} onChange={setCargo} placeholder="ej. Asesora de ventas" />
            <Field label="Email" type="email" value={email} onChange={setEmail} required />
            <Field label="Contraseña (mín. 8)" type="password" value={password} onChange={setPassword} required />
            <div className="md:col-span-2">
              <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">Tipo de acceso</label>
              <select
                value={rol}
                onChange={(e) => setRol(e.target.value as Rol)}
                className="w-full md:w-1/2 rounded-sm border border-border bg-card px-3 py-2 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
              >
                <option value="admin">Administrador — acceso total</option>
                <option value="lector">Lector — solo ver en todos los módulos</option>
                <option value="user">Usuario — permisos granulares (configurar abajo)</option>
              </select>
            </div>
          </div>

          {rol === "user" && (
            <PermisosMatrix permisos={permisos} onChange={setPermisos} />
          )}

          {err && <p className="text-sm text-terracotta">{err}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="rounded-sm border border-border bg-card px-4 py-2 text-[0.7rem] font-medium uppercase tracking-[0.12em] text-graphite transition-colors hover:bg-cloud">
              Cancelar
            </button>
            <button type="submit" disabled={mut.isPending} className="rounded-sm bg-navy-600 px-4 py-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-white transition-colors hover:bg-navy-700 disabled:opacity-50">
              {mut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Crear usuario"}
            </button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Matriz de permisos (módulos × acciones)
// ──────────────────────────────────────────────────────────────────────

function PermisosMatrix({
  permisos,
  onChange,
}: {
  permisos: Record<string, string[]>;
  onChange: (p: Record<string, string[]>) => void;
}) {
  function toggle(grupo: string, accion: Accion) {
    const actual = new Set(permisos[grupo] || []);
    if (actual.has(accion)) {
      actual.delete(accion);
      // Si quitan "ver", también quitar las acciones de escritura
      // (no tiene sentido modificar sin ver).
      if (accion === "ver") {
        actual.delete("modificar");
        actual.delete("borrar");
      }
    } else {
      actual.add(accion);
      // Si marcan modificar/borrar, asegurar que "ver" esté.
      if (accion !== "ver") actual.add("ver");
    }
    onChange({ ...permisos, [grupo]: Array.from(actual) });
  }

  function presetTodo() {
    const p: Record<string, string[]> = {};
    for (const g of GRUPOS) p[g] = ["ver", "modificar"];
    onChange(p);
  }
  function presetSoloVer() {
    const p: Record<string, string[]> = {};
    for (const g of GRUPOS) p[g] = ["ver"];
    onChange(p);
  }
  function presetNada() {
    onChange({});
  }

  return (
    <div className="border border-border rounded-sm bg-cloud/30">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <p className="text-[0.62rem] font-semibold uppercase tracking-[0.14em] text-ink-900">
          Permisos por área
        </p>
        <div className="flex items-center gap-2">
          <button type="button" onClick={presetSoloVer} className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite hover:text-ink-900">
            Solo ver todo
          </button>
          <span className="text-graphite">·</span>
          <button type="button" onClick={presetTodo} className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite hover:text-ink-900">
            Ver + modificar todo
          </button>
          <span className="text-graphite">·</span>
          <button type="button" onClick={presetNada} className="text-[0.62rem] uppercase tracking-[0.1em] text-graphite hover:text-ink-900">
            Limpiar
          </button>
        </div>
      </div>
      <table className="w-full text-sm">
        <thead className="bg-card border-b border-border">
          <tr>
            <th className="px-4 py-2 text-left text-[0.6rem] font-semibold uppercase tracking-[0.1em] text-graphite">Área</th>
            {ACCIONES.map((a) => (
              <th key={a} className="px-3 py-2 text-center text-[0.6rem] font-semibold uppercase tracking-[0.1em] text-graphite">
                {ACCION_LABEL[a]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {GRUPOS.map((g) => {
            const acciones = permisos[g] || [];
            return (
              <tr key={g} className="border-b border-border/40 hover:bg-card/60">
                <td className="px-4 py-2 text-sm text-ink-900 max-w-[420px]">
                  <div className="font-medium">{GRUPO_LABEL[g] || g}</div>
                </td>
                {ACCIONES.map((a) => (
                  <td key={a} className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={acciones.includes(a)}
                      onChange={() => toggle(g, a)}
                      className="rounded border-graphite/40 cursor-pointer h-4 w-4"
                    />
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="px-4 py-2 text-[0.62rem] text-graphite italic border-t border-border">
        Cada área agrupa varios módulos. "Modificar" y "Borrar" implican "Ver" automáticamente. Borrar es destructivo: úsalo solo cuando sea necesario.
      </p>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Fila de tabla (edición inline)
// ──────────────────────────────────────────────────────────────────────

function UsuarioRow({
  u, isEditing, isCurrentUser, onEdit, onSaved,
}: {
  u: Usuario; isEditing: boolean; isCurrentUser: boolean; onEdit: () => void; onSaved: () => void;
}) {
  const [nombre, setNombre] = useState(u.nombre);
  const [cargo, setCargo] = useState(u.cargo || "");
  const [rol, setRol] = useState<Rol>(u.rol);
  const [permisos, setPermisos] = useState<Record<string, string[]>>(
    (u.permisos as Record<string, string[]>) || permisosPorDefecto()
  );
  const [activo, setActivo] = useState(u.activo);
  const [password, setPassword] = useState("");
  const [errEdit, setErrEdit] = useState("");

  const mut = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { nombre, cargo, rol, activo };
      if (rol === "user") body.permisos = permisos;
      if (password) body.password = password;
      return api.patch<Usuario>(`/api/auth/usuarios/${u.id}`, body);
    },
    onSuccess: () => { setErrEdit(""); onSaved(); },
    onError: (e: Error) => setErrEdit(e.message || "Error desconocido"),
  });

  if (isEditing) {
    return (
      <tr className="border-b border-border bg-steel-300/15">
        <td colSpan={6} className="p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className="mb-1 block text-[0.6rem] uppercase tracking-[0.1em] text-graphite">Nombre</label>
              <input value={nombre} onChange={(e) => setNombre(e.target.value)} className="w-full rounded-sm border border-border bg-card px-2 py-1 text-sm" />
            </div>
            <div>
              <label className="mb-1 block text-[0.6rem] uppercase tracking-[0.1em] text-graphite">Cargo</label>
              <input value={cargo} onChange={(e) => setCargo(e.target.value)} placeholder="ej. Asesora" className="w-full rounded-sm border border-border bg-card px-2 py-1 text-sm" />
            </div>
            <div>
              <label className="mb-1 block text-[0.6rem] uppercase tracking-[0.1em] text-graphite">Rol</label>
              <select value={rol} onChange={(e) => setRol(e.target.value as Rol)} className="w-full rounded-sm border border-border bg-card px-2 py-1 text-sm">
                <option value="admin">Administrador</option>
                <option value="lector">Lector</option>
                <option value="user">Usuario (granular)</option>
              </select>
            </div>
          </div>

          {rol === "user" && (
            <PermisosMatrix permisos={permisos} onChange={setPermisos} />
          )}

          <div className="flex items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-xs">
              <input type="checkbox" checked={activo} onChange={(e) => setActivo(e.target.checked)} disabled={isCurrentUser} />
              {activo ? "Activo" : "Inactivo"} {isCurrentUser && <span className="text-[0.6rem] text-graphite">(no puedes desactivarte)</span>}
            </label>
            <div className="flex items-center gap-2">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Nueva contraseña (opcional)"
                className="w-52 rounded-sm border border-border bg-card px-2 py-1 text-xs"
              />
              <button onClick={() => mut.mutate()} disabled={mut.isPending} className="inline-flex items-center gap-1 rounded-sm bg-navy-600 px-3 py-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-white transition-colors hover:bg-navy-700 disabled:opacity-50">
                {mut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                Guardar
              </button>
              <button onClick={onEdit} className="rounded-sm border border-border p-1.5 text-graphite transition-colors hover:bg-cloud" title="Cancelar">
                <X className="h-3 w-3" />
              </button>
            </div>
          </div>
          {errEdit && (
            <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
              {errEdit}
            </div>
          )}
        </td>
      </tr>
    );
  }

  return (
    <tr className="border-b border-border transition-colors hover:bg-cloud/50">
      <td className="px-4 py-3 font-medium text-ink-900">
        {u.nombre} {isCurrentUser && <span className="ml-1 text-[0.6rem] text-steel-500">(tú)</span>}
      </td>
      <td className="px-4 py-3 text-graphite text-xs">{u.cargo || "—"}</td>
      <td className="px-4 py-3 text-graphite">{u.email}</td>
      <td className="px-4 py-3">
        <Badge tone={u.rol === "admin" ? "critico" : (u.rol === "lector" || u.rol === "lectura") ? "neutral" : "info"}>
          {ROL_LABEL[u.rol] || u.rol}
        </Badge>
      </td>
      <td className="px-4 py-3">
        <Badge tone={u.activo ? "normal" : "neutral"}>{u.activo ? "Activo" : "Inactivo"}</Badge>
      </td>
      <td className="px-4 py-3 text-right">
        <button onClick={onEdit} className="inline-flex items-center gap-1 text-xs font-medium text-ink-900 transition-colors hover:text-navy-600">
          <Edit className="h-3 w-3" /> Editar
        </button>
      </td>
    </tr>
  );
}

function Field({
  label, value, onChange, type = "text", required = false, placeholder = "",
}: { label: string; value: string; onChange: (v: string) => void; type?: string; required?: boolean; placeholder?: string }) {
  return (
    <div>
      <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        placeholder={placeholder}
        minLength={type === "password" ? 8 : undefined}
        className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
      />
    </div>
  );
}
