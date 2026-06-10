"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { ROL_LABEL, esAdmin } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, UserPlus, Shield, Edit, Check, X } from "lucide-react";

interface Usuario {
  id: string;
  email: string;
  nombre: string;
  rol: "admin" | "operador" | "lectura";
  activo: boolean;
  creado_en?: string;
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
        <Card>
          <CardContent className="p-10 text-center">
            <Shield className="h-10 w-10 mx-auto text-crimson mb-3" />
            <p className="text-ink font-semibold">Acceso restringido</p>
            <p className="text-sm text-graphite mt-1">Solo administradores pueden gestionar usuarios.</p>
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  if (usuariosQ.isLoading) return <LoadingState label="Cargando usuarios..." />;
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
          className="inline-flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black"
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
            <thead className="bg-concrete/50 border-b border-border">
              <tr>
                <th className="px-4 py-3 text-left text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Nombre</th>
                <th className="px-4 py-3 text-left text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Email</th>
                <th className="px-4 py-3 text-left text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Rol</th>
                <th className="px-4 py-3 text-left text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Estado</th>
                <th className="px-4 py-3 text-right text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Acciones</th>
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

function UsuarioForm({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [email, setEmail] = useState("");
  const [nombre, setNombre] = useState("");
  const [password, setPassword] = useState("");
  const [rol, setRol] = useState<Usuario["rol"]>("operador");
  const [err, setErr] = useState("");

  const mut = useMutation({
    mutationFn: () => api.post<Usuario>("/api/auth/usuarios", { email, nombre, password, rol }),
    onSuccess,
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <Card>
      <CardContent className="p-5">
        <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-3">Crear usuario</p>
        <form
          onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }}
          className="grid grid-cols-1 md:grid-cols-2 gap-3"
        >
          <Field label="Nombre" value={nombre} onChange={setNombre} required />
          <Field label="Email" type="email" value={email} onChange={setEmail} required />
          <Field label="Contraseña (mín. 8)" type="password" value={password} onChange={setPassword} required />
          <div>
            <label className="block text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-1.5">Rol</label>
            <select
              value={rol}
              onChange={(e) => setRol(e.target.value as Usuario["rol"])}
              className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
            >
              <option value="admin">Administrador</option>
              <option value="operador">Operador</option>
              <option value="lectura">Solo lectura</option>
            </select>
          </div>

          {err && <p className="md:col-span-2 text-sm text-crimson">{err}</p>}

          <div className="md:col-span-2 flex gap-2 justify-end">
            <button type="button" onClick={onClose} className="rounded-md border border-border bg-white px-4 py-2 text-xs font-semibold uppercase tracking-wider text-graphite hover:bg-concrete">
              Cancelar
            </button>
            <button type="submit" disabled={mut.isPending} className="rounded-md bg-ink px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50">
              {mut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Crear"}
            </button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function UsuarioRow({
  u, isEditing, isCurrentUser, onEdit, onSaved,
}: {
  u: Usuario; isEditing: boolean; isCurrentUser: boolean; onEdit: () => void; onSaved: () => void;
}) {
  const [nombre, setNombre] = useState(u.nombre);
  const [rol, setRol] = useState(u.rol);
  const [activo, setActivo] = useState(u.activo);
  const [password, setPassword] = useState("");

  const mut = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { nombre, rol, activo };
      if (password) body.password = password;
      return api.patch<Usuario>(`/api/auth/usuarios/${u.id}`, body);
    },
    onSuccess: () => onSaved(),
  });

  if (isEditing) {
    return (
      <tr className="border-b border-border bg-steel/5">
        <td className="px-4 py-2">
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} className="w-full rounded border border-border bg-white px-2 py-1 text-sm" />
        </td>
        <td className="px-4 py-2 text-xs text-graphite">{u.email}</td>
        <td className="px-4 py-2">
          <select value={rol} onChange={(e) => setRol(e.target.value as Usuario["rol"])} className="rounded border border-border bg-white px-2 py-1 text-sm">
            <option value="admin">Admin</option>
            <option value="operador">Operador</option>
            <option value="lectura">Lectura</option>
          </select>
        </td>
        <td className="px-4 py-2">
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={activo} onChange={(e) => setActivo(e.target.checked)} disabled={isCurrentUser} />
            {activo ? "Activo" : "Inactivo"}
          </label>
        </td>
        <td className="px-4 py-2">
          <div className="flex items-center justify-end gap-2">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Nueva contraseña (opcional)"
              className="rounded border border-border bg-white px-2 py-1 text-xs w-44"
            />
            <button onClick={() => mut.mutate()} disabled={mut.isPending} className="rounded bg-ink p-1.5 text-white hover:bg-black disabled:opacity-50" title="Guardar">
              {mut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            </button>
            <button onClick={onEdit} className="rounded border border-border p-1.5 text-graphite hover:bg-concrete" title="Cancelar">
              <X className="h-3 w-3" />
            </button>
          </div>
        </td>
      </tr>
    );
  }

  return (
    <tr className="border-b border-border hover:bg-concrete/30">
      <td className="px-4 py-3 font-semibold text-ink">
        {u.nombre} {isCurrentUser && <span className="text-[0.6rem] text-steel ml-1">(tú)</span>}
      </td>
      <td className="px-4 py-3 text-graphite">{u.email}</td>
      <td className="px-4 py-3">
        <Badge tone={u.rol === "admin" ? "critico" : u.rol === "operador" ? "info" : "neutral"}>
          {ROL_LABEL[u.rol]}
        </Badge>
      </td>
      <td className="px-4 py-3">
        <Badge tone={u.activo ? "normal" : "neutral"}>{u.activo ? "Activo" : "Inactivo"}</Badge>
      </td>
      <td className="px-4 py-3 text-right">
        <button onClick={onEdit} className="inline-flex items-center gap-1 text-xs font-semibold text-ink hover:text-navy">
          <Edit className="h-3 w-3" /> Editar
        </button>
      </td>
    </tr>
  );
}

function Field({
  label, value, onChange, type = "text", required = false,
}: { label: string; value: string; onChange: (v: string) => void; type?: string; required?: boolean }) {
  return (
    <div>
      <label className="block text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-1.5">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        minLength={type === "password" ? 8 : undefined}
        className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
      />
    </div>
  );
}
