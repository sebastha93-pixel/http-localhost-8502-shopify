"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { esAdmin } from "@/lib/auth";
import { PageShell } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Package, Boxes, Ruler, Scissors, FileText, Users, BarChart3, Trash2, Loader2 } from "lucide-react";

const MODULOS = [
  { href: "/produccion/ingreso",       label: "Ingreso de tela", desc: "Recepción de textilera → rollos + etiquetas", icon: Package, activo: true },
  { href: "/produccion/inventario",    label: "Inventario",      desc: "Rollos por tela · metros disponibles",         icon: Boxes,   activo: true },
  { href: "/produccion/precosteo",     label: "Precosteo",       desc: "Costeo por referencia + firma",                icon: Ruler,   activo: true },
  { href: "/produccion/corte",         label: "Orden de corte",  desc: "Trazo, curva y consumo real (pistolea rollos)",  icon: Scissors, activo: true },
  { href: "/produccion/remisiones",    label: "Remisiones",      desc: "Entregas a confeccionista",                    icon: FileText, activo: true },
  { href: "/produccion/confeccionistas", label: "Proveedores", desc: "Confección · terminación · lavanderías",                       icon: Users,   activo: true },
  { href: "/produccion/tablero",       label: "Tablero",         desc: "Eficiencia · stock mínimo · valor",             icon: BarChart3, activo: true },
];

export default function ProduccionHome() {
  const { user } = useAuth();
  return (
    <PageShell title="Producción" subtitle="Inventario de tela · precosteo · corte · confección">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {MODULOS.map((m) => {
          const Icon = m.icon;
          const inner = (
            <CardContent className="p-5 flex items-start gap-3">
              <div className={`h-10 w-10 rounded-md grid place-items-center ${m.activo ? "bg-navy-600/10 text-navy-600" : "bg-cloud text-graphite"}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <p className={`font-display text-base font-medium ${m.activo ? "text-ink-900" : "text-graphite"}`}>
                  {m.label}
                  {!m.activo && <span className="ml-2 text-[0.6rem] uppercase tracking-widest text-graphite">Próximamente</span>}
                </p>
                <p className="text-xs text-graphite mt-0.5">{m.desc}</p>
              </div>
            </CardContent>
          );
          return m.activo ? (
            <Link key={m.href} href={m.href} className="block">
              <Card className="hover:border-navy-600/40 transition-colors">{inner}</Card>
            </Link>
          ) : (
            <Card key={m.href} className="opacity-60">{inner}</Card>
          );
        })}
      </div>
      {esAdmin(user) && <ResetProduccionCard />}
    </PageShell>
  );
}

/** Zona de peligro (solo admin): borra TODOS los datos del módulo para
 * arrancar de cero. Corre en el backend con la service key — no depende
 * del SQL Editor de Supabase. */
function ResetProduccionCard() {
  const qc = useQueryClient();
  const [confirmando, setConfirmando] = useState(false);
  const [texto, setTexto] = useState("");
  const [resultado, setResultado] = useState("");
  const [err, setErr] = useState("");

  const reset = useMutation({
    mutationFn: () => api.post<{ ok: boolean; borradas: Record<string, number>; errores: Record<string, string> }>(
      "/api/produccion/admin/reset-datos", { confirmacion: "RESET" }),
    onSuccess: (d) => {
      setErr("");
      setConfirmando(false);
      setTexto("");
      const total = Object.values(d.borradas || {}).reduce((s, n) => s + n, 0);
      const errores = Object.keys(d.errores || {});
      setResultado(errores.length
        ? `Se borraron ${total} registros, pero fallaron: ${errores.join(", ")}`
        : `Módulo en cero: ${total} registros borrados. Consecutivos reiniciados.`);
      qc.clear();
    },
    onError: (e: Error) => setErr(`No se pudo resetear: ${e.message}`),
  });

  return (
    <Card className="border-terracotta/40 mt-4">
      <CardContent className="p-5 space-y-3">
        <p className="text-[0.6rem] uppercase tracking-widest text-terracotta font-bold">Zona de peligro (solo admin)</p>
        <p className="text-xs text-graphite">
          Borra <strong>todos</strong> los datos del módulo: telas, cortes, remisiones, precosteos,
          insumos, proveedores y consecutivos. Conserva usuarios y permisos. <strong>Irreversible.</strong>
        </p>
        {resultado && (
          <div className="rounded-sm border border-teal/40 bg-teal/[0.06] px-3 py-2 text-xs text-teal">✓ {resultado}</div>
        )}
        {err && (
          <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">{err}</div>
        )}
        {!confirmando ? (
          <button onClick={() => { setConfirmando(true); setResultado(""); }}
            className="inline-flex items-center gap-1.5 rounded-sm border border-terracotta/50 bg-white px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-terracotta hover:bg-terracotta/10">
            <Trash2 className="h-3.5 w-3.5" /> Resetear módulo producción
          </button>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <input value={texto} onChange={(e) => setTexto(e.target.value)}
              placeholder={'Escribe RESET para confirmar'}
              className="rounded-sm border border-terracotta/50 bg-white px-2 py-1.5 text-xs w-[220px]" />
            <button onClick={() => reset.mutate()}
              disabled={texto !== "RESET" || reset.isPending}
              className="inline-flex items-center gap-1.5 rounded-sm bg-terracotta px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:bg-ink-900 disabled:opacity-40">
              {reset.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              Borrar todo
            </button>
            <button onClick={() => { setConfirmando(false); setTexto(""); }}
              className="text-[0.65rem] uppercase tracking-widest text-graphite hover:text-ink-900">
              Cancelar
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
