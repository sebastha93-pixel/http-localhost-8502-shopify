"use client";

/**
 * Quién puede hacer qué en el POS.
 *
 * Hasta ahora esto se editaba con `psql`. Dar de alta una cajera —o quitarle el
 * permiso a alguien que se fue— dependía de que alguien con acceso a la base lo
 * hiciera a mano, que es tanto como decir que el sistema no se puede operar sin
 * quien lo construyó.
 *
 * SÓLO ENTRA UN ADMINISTRADOR DEL ERP. No basta con los permisos del POS:
 * quien puede anular ventas no tiene por qué poder darse a sí mismo el permiso
 * de ver la auditoría. Lo comprueba el servidor; aquí sólo se pinta el error.
 *
 * SE DESACTIVA, NO SE BORRA. La fila sigue explicando las ventas y los
 * descuentos que esa persona hizo: borrarla dejaría la auditoría llena de
 * identificadores sin nombre.
 */
import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Panel } from "@/components/pos/marco";
import { Rail } from "@/components/pos/rail";
import {
  guardarPermisos,
  listarPermisos,
  type PermisosUsuario,
} from "@/lib/pos/api";

const CASILLAS: { campo: keyof PermisosUsuario; etiqueta: string; ayuda: string }[] = [
  { campo: "puede_anular_venta", etiqueta: "Anular ventas",
    ayuda: "deshacer una venta cobrada" },
  { campo: "puede_mover_caja", etiqueta: "Mover caja",
    ayuda: "sacar plata del cajón" },
  { campo: "puede_cerrar_con_descuadre", etiqueta: "Cerrar con descuadre",
    ayuda: "firmar un faltante grande" },
  { campo: "puede_ver_esperado", etiqueta: "Ver el esperado",
    ayuda: "saltarse el conteo ciego" },
  { campo: "puede_ver_auditoria", etiqueta: "Ver auditoría",
    ayuda: "quién descontó, anuló y sacó plata" },
];

export default function PantallaPermisos() {
  const { user } = useAuth();
  const [usuarios, setUsuarios] = useState<PermisosUsuario[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const l = await listarPermisos();
        if (vivo) { setUsuarios(l); setError(null); }
      } catch (e) {
        if (vivo) setError(e instanceof Error ? e.message : "No se pudo leer.");
      } finally {
        if (vivo) setCargando(false);
      }
    })();
    return () => { vivo = false; };
  }, []);

  async function cambiar(u: PermisosUsuario, cambios: Partial<PermisosUsuario>) {
    setGuardando(u.usuario_id);
    setError(null);
    // Optimista: el cambio se ve al instante y se revierte si el servidor dice
    // que no. Esperar la respuesta para pintar una casilla hace que parezca
    // que el clic no funcionó.
    const previo = usuarios;
    setUsuarios((l) => l.map((x) =>
      x.usuario_id === u.usuario_id ? { ...x, ...cambios } : x));
    try {
      const { usuario_id: _id, ...resto } = { ...u, ...cambios };
      const guardado = await guardarPermisos(u.usuario_id, resto);
      setUsuarios((l) => l.map((x) =>
        x.usuario_id === u.usuario_id ? guardado : x));
    } catch (e) {
      setUsuarios(previo);
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    } finally {
      setGuardando(null);
    }
  }

  return (
    <div className="pos-raiz flex h-screen overflow-hidden">
      <Rail cajera={user?.nombre || user?.email || ""} />

      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
        <header>
          <h1 className="titular text-[22px] font-semibold tracking-tight">
            Permisos del POS
          </h1>
          <p className="mt-1 text-[12px] text-[var(--pos-600)]">
            Cada cambio queda en la auditoría como crítico, con tu nombre.
          </p>
        </header>

        {error && (
          <p className="max-w-[620px] border-l-2 border-[var(--pos-800)] bg-[var(--pos-800)]/10 py-3 pl-4 text-[13px] leading-relaxed text-[var(--pos-900)]">
            {error}
          </p>
        )}

        {cargando && (
          <p className="text-[13px] text-[var(--pos-600)]">Cargando…</p>
        )}

        {usuarios.map((u) => (
          <Panel
            key={u.usuario_id}
            className={`flex flex-col gap-3 p-6 ${u.activo ? "" : "opacity-60"}`}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <div>
                <p className="titular text-[16px] font-semibold">
                  {u.nombre}
                  {!u.activo && (
                    <span className="ml-2 text-[12px] font-normal text-[var(--pos-600)]">
                      · inactiva
                    </span>
                  )}
                </p>
                <p className="tabular text-[12px] text-[var(--pos-600)]">
                  {u.usuario_id}
                  {u.rol ? ` · ${u.rol}` : ""}
                  {u.tiendas.length ? ` · ${u.tiendas.join(", ")}` : ""}
                </p>
              </div>

              <label className="flex items-center gap-2 text-[12px]">
                <span className="text-[var(--pos-700)]">Tope de descuento</span>
                <input
                  inputMode="decimal"
                  defaultValue={u.tope_descuento_pct}
                  onBlur={(e) => {
                    const v = e.target.value.trim();
                    if (v !== u.tope_descuento_pct) {
                      void cambiar(u, { tope_descuento_pct: v });
                    }
                  }}
                  className="h-9 w-[70px] border border-[var(--pos-divider)] bg-white px-2 tabular text-[13px] text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
                />
                <span className="text-[var(--pos-600)]">%</span>
              </label>
            </div>

            <div className="flex flex-wrap gap-2">
              {CASILLAS.map((c) => {
                const activo = Boolean(u[c.campo]);
                return (
                  <button
                    key={String(c.campo)}
                    disabled={guardando === u.usuario_id}
                    onClick={() => void cambiar(u, { [c.campo]: !activo })}
                    title={c.ayuda}
                    className={`border px-3 py-2 text-left text-[12px] transition-colors disabled:opacity-50 ${
                      activo
                        ? "border-[var(--pos-800)] bg-[var(--pos-800)] text-white"
                        : "border-[var(--pos-divider)] text-[var(--pos-700)]"
                    }`}
                  >
                    <span className="block font-medium">{c.etiqueta}</span>
                    <span className="block text-[12px] opacity-70">{c.ayuda}</span>
                  </button>
                );
              })}

              <button
                disabled={guardando === u.usuario_id}
                onClick={() => void cambiar(u, { activo: !u.activo })}
                className="ml-auto border border-[var(--pos-accent)]/40 px-3 py-2 text-[12px] text-[var(--pos-accent)] disabled:opacity-50"
              >
                {u.activo ? "Desactivar" : "Reactivar"}
              </button>
            </div>
          </Panel>
        ))}

        {!cargando && usuarios.length === 0 && !error && (
          <p className="text-[13px] text-[var(--pos-600)]">
            Nadie tiene permisos del POS todavía.
          </p>
        )}
      </main>
    </div>
  );
}
