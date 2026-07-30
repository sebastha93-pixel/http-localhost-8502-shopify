"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { PageShell } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { useQuery, useMutation } from "@tanstack/react-query";
import { formatMoney, fmtDateTime } from "@/lib/utils";
import { crearCaso, listarTiendas, comprasPorCedula, TIPOS, MOTIVOS, PRIORIDADES,
         type CasoPostventa, type Compra } from "@/lib/postventa";

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
    tienda: "",
    pago_excedente_id: "",
    cedula: "",
  });
  const [elegida, setElegida] = useState<Compra | null>(null);

  // La clienta casi nunca recuerda el nº de pedido, pero siempre tiene la
  // cédula: con ella se traen todas sus compras (online y de tienda).
  const buscar = useMutation({
    mutationFn: () => comprasPorCedula(f.cedula.trim()),
  });

  function usarCompra(c: Compra) {
    setElegida(c);
    setF((p) => ({
      ...p,
      shopify_order_name: c.pedido ?? "",
      // Si compró en una tienda, el caso se abre en ese mismo punto.
      tienda: c.canal && c.canal !== "online" ? c.canal : p.tienda,
    }));
  }
  const puntos = useQuery({ queryKey: ["postventa-tiendas"], queryFn: listarTiendas });
  const punto = (puntos.data ?? []).find((p) => p.clave === f.tienda);

  const set = (k: keyof typeof f) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => setF((prev) => ({ ...prev, [k]: e.target.value }));

  const mut = useMutation({
    mutationFn: () => {
      const { cedula, ...resto } = f;
      return crearCaso({
        ...resto, source: "interno", customer_cedula: cedula,
        pago_excedente_id: f.pago_excedente_id ? Number(f.pago_excedente_id) : null,
      });
    },
    onSuccess: (caso: CasoPostventa) => router.push(`/postventa/${caso.id}`),
  });

  const puedeGuardar = f.tipo !== "" && f.reason !== "" && !mut.isPending;

  return (
    <PageShell title="Nuevo caso" subtitle="Registrar un cambio, devolución o garantía">
      <Card className="max-w-2xl">
        <CardContent className="py-5 space-y-5">
          <Seccion titulo="Buscar la compra">
            <div className="flex gap-2 items-end">
              <div className="flex-1">
                <Campo label="Cédula de la clienta">
                  <input className={INPUT} value={f.cedula}
                    onChange={set("cedula")}
                    onKeyDown={(e) => { if (e.key === "Enter" && f.cedula.trim())
                                          { e.preventDefault(); buscar.mutate(); } }}
                    placeholder="1020409206" inputMode="numeric" />
                </Campo>
              </div>
              <button type="button" disabled={!f.cedula.trim() || buscar.isPending}
                onClick={() => buscar.mutate()}
                className="shrink-0 rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium
                           text-white hover:bg-navy-700 disabled:opacity-50">
                {buscar.isPending ? "Buscando…" : "Buscar compras"}
              </button>
            </div>

            {buscar.isError && (
              <p className="text-sm text-terracotta">No se pudo consultar Siigo.</p>
            )}
            {buscar.data?._error && (
              <p className="text-sm text-terracotta">
                {buscar.data._error === "sin_cedula" ? "Escribe la cédula."
                  : "No se pudo consultar Siigo."}
              </p>
            )}
            {buscar.data && !buscar.data._error && buscar.data.total === 0 && (
              <p className="text-sm text-graphite">
                Sin compras con esa cédula. Puedes seguir llenando el caso a mano.
              </p>
            )}

            {buscar.data?.compras?.map((c) => {
              const activa = elegida?.factura_id === c.factura_id;
              return (
                <button type="button" key={c.factura_id}
                  onClick={() => c.acreditable && usarCompra(c)}
                  disabled={!c.acreditable}
                  className={`w-full text-left rounded-sm border p-3 transition-colors ${
                    activa ? "border-navy-600 bg-cloud/60"
                    : c.acreditable ? "border-border hover:bg-cloud/40"
                    : "border-border opacity-60 cursor-not-allowed"}`}>
                  <div className="flex justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm text-ink-900">
                        <span className="font-display tabular-nums">{c.factura}</span>
                        <span className="text-graphite"> · {c.donde}</span>
                      </p>
                      <p className="text-xs text-graphite truncate">
                        {c.prendas.map((p) => p.descripcion).join(" · ") || "—"}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="font-display tabular-nums text-sm text-ink-900">
                        {formatMoney(c.total ?? 0)}
                      </p>
                      <p className="text-[0.68rem] text-graphite tabular-nums">
                        {fmtDateTime(c.fecha)}
                      </p>
                    </div>
                  </div>
                  {!c.acreditable && (
                    <p className="mt-1.5 text-[0.68rem] text-ochre">
                      {c.motivo_no_acreditable}
                    </p>
                  )}
                  {activa && (
                    <p className="mt-1.5 text-[0.68rem] text-sage">
                      ✓ Compra elegida{c.pedido ? ` · pedido ${c.pedido}` : ""}
                    </p>
                  )}
                </button>
              );
            })}
          </Seccion>

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

          <Seccion titulo="Dónde se atiende">
            <Campo label="Canal">
              <select className={INPUT} value={f.tienda}
                onChange={(e) => setF((p) => ({ ...p, tienda: e.target.value,
                                                pago_excedente_id: "" }))}>
                <option value="">Online · la prenda vuelve a la bodega web</option>
                {(puntos.data ?? []).map((p) => (
                  <option key={p.clave} value={p.clave} disabled={!p.lista}>
                    {p.nombre} · factura {p.prefijo_factura}
                    {p.lista ? "" : " (sin configurar)"}
                  </option>
                ))}
              </select>
            </Campo>
            {punto && (
              <>
                <p className="text-xs text-graphite">
                  La prenda devuelta entra al inventario de{" "}
                  <b className="text-ink-900">{punto.tienda}</b> y la factura del
                  reemplazo sale con el prefijo{" "}
                  <b className="font-display tabular-nums text-ink-900">
                    {punto.prefijo_factura}
                  </b>.
                </p>
                <Campo label="Si la prenda nueva vale más, ¿cómo paga la diferencia?">
                  <select className={INPUT} value={f.pago_excedente_id}
                    onChange={set("pago_excedente_id")}>
                    <option value="">Definir al facturar</option>
                    {punto.formas_pago.map((fp) => (
                      <option key={fp.id} value={fp.id}>{fp.nombre}</option>
                    ))}
                  </select>
                </Campo>
              </>
            )}
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
            <p className="text-sm text-terracotta">
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
      <h3 className="section-label">{titulo}</h3>
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
