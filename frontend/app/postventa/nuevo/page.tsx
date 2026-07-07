"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { PageShell } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { crearCaso, TIPOS, MOTIVOS, PRIORIDADES, type CasoPostventa } from "@/lib/postventa";

const INPUT =
  "w-full rounded-sm border border-border bg-card px-3 py-2 text-sm text-ink-900 " +
  "focus:outline-none focus:ring-2 focus:ring-navy-600/30";

export default function NuevoCasoPage() {
  const router = useRouter();
  const [f, setF] = useState({
    customer_name: "",
    customer_email: "",
    customer_phone: "",
    shopify_order_name: "",
    shopify_order_id: "",
    tipo: "",
    reason: "",
    priority: "media",
  });

  const set = (k: keyof typeof f) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => setF((prev) => ({ ...prev, [k]: e.target.value }));

  const mut = useMutation({
    mutationFn: () => crearCaso({ ...f, source: "interno" }),
    onSuccess: (caso: CasoPostventa) => router.push(`/postventa/${caso.id}`),
  });

  const puedeGuardar = f.tipo !== "" && f.reason !== "" && !mut.isPending;

  return (
    <PageShell title="Nuevo caso" subtitle="Registrar un cambio, devolución o garantía">
      <Card className="max-w-2xl">
        <CardContent className="py-5 space-y-5">
          <Seccion titulo="Cliente">
            <Campo label="Nombre">
              <input className={INPUT} value={f.customer_name} onChange={set("customer_name")} />
            </Campo>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Campo label="Email">
                <input className={INPUT} type="email" value={f.customer_email}
                       onChange={set("customer_email")} />
              </Campo>
              <Campo label="Teléfono (para WhatsApp)">
                <input className={INPUT} value={f.customer_phone} onChange={set("customer_phone")} />
              </Campo>
            </div>
          </Seccion>

          <Seccion titulo="Pedido Shopify">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Campo label="Número de pedido (ej. #1052)">
                <input className={INPUT} value={f.shopify_order_name}
                       onChange={set("shopify_order_name")} />
              </Campo>
              <Campo label="ID de pedido (opcional)">
                <input className={INPUT} value={f.shopify_order_id}
                       onChange={set("shopify_order_id")} />
              </Campo>
            </div>
          </Seccion>

          <Seccion titulo="Solicitud">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Campo label="Tipo *">
                <select className={INPUT} value={f.tipo} onChange={set("tipo")}>
                  <option value="">Selecciona…</option>
                  {TIPOS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </Campo>
              <Campo label="Motivo *">
                <select className={INPUT} value={f.reason} onChange={set("reason")}>
                  <option value="">Selecciona…</option>
                  {MOTIVOS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </Campo>
              <Campo label="Prioridad">
                <select className={INPUT} value={f.priority} onChange={set("priority")}>
                  {PRIORIDADES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                </select>
              </Campo>
            </div>
          </Seccion>

          <div className="flex items-center gap-3 pt-2">
            <button disabled={!puedeGuardar} onClick={() => mut.mutate()}
                    className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white
                               transition-colors hover:bg-navy-700 disabled:opacity-50">
              {mut.isPending ? "Creando…" : "Crear caso"}
            </button>
            <button onClick={() => router.push("/postventa")}
                    className="rounded-sm border border-border bg-card px-4 py-2 text-sm
                               font-medium text-graphite transition-colors hover:bg-cloud">
              Cancelar
            </button>
          </div>
          {mut.isError && (
            <p className="text-sm text-destructive">
              No se pudo crear el caso. Revisa que tipo y motivo sean válidos.
            </p>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}

function Seccion({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-graphite">{titulo}</h3>
      {children}
    </div>
  );
}

function Campo({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="block text-xs text-graphite">{label}</span>
      {children}
    </label>
  );
}
