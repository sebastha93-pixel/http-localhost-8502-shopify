"use client";

/* Cierre diario de postventa.
   El excedente de un cambio se cobra en el datáfono o la caja de la tienda,
   pero la factura sale por FV-5 desde Siigo Nube: el POS no lo ve. Esta
   pantalla es lo que la cajera SUMA a su arqueo para que el día cuadre. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney, hoyBogotaISO } from "@/lib/utils";
import { cierreCaja, type CierrePunto } from "@/lib/postventa";

export default function CierreCajaPage() {
  const [fecha, setFecha] = useState(hoyBogotaISO());
  const q = useQuery({ queryKey: ["postventa-cierre", fecha],
                       queryFn: () => cierreCaja(fecha) });

  return (
    <PageShell title="Cierre de caja · Postventa"
      subtitle="Lo que se cobró por cambios y no aparece en el cierre del POS">
      <div className="mb-4">
        <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)}
          className="rounded-sm border border-border bg-card px-3 py-2 text-sm
                     text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30" />
      </div>

      {q.isLoading && <LoadingState />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(q.data?.puntos ?? []).map((p) => <Punto key={p.tienda} p={p} />)}
      </div>
    </PageShell>
  );
}

function Punto({ p }: { p: CierrePunto }) {
  const hubo = p.total_cobrado > 0 || p.notas_credito.cantidad > 0;
  return (
    <Card>
      <CardContent className="py-4 space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <p className="section-label">{p.nombre}</p>
          <p className="font-display tabular-nums text-lg text-ink-900">
            {formatMoney(p.total_cobrado)}
          </p>
        </div>

        {!hubo && <p className="text-sm text-graphite">Sin movimiento.</p>}

        {p.por_medio.length > 0 && (
          <dl className="rounded-sm border border-border bg-cloud/40 p-3 text-sm space-y-1.5">
            {p.por_medio.map((m) => (
              <div key={m.id} className="flex justify-between gap-3">
                <dt className="text-graphite">{m.nombre}</dt>
                <dd className="tabular-nums text-ink-900">{formatMoney(m.total)}</dd>
              </div>
            ))}
          </dl>
        )}

        {p.casos.length > 0 && (
          <div className="space-y-1">
            <p className="text-[0.68rem] text-graphite">
              Casos ({p.casos.length}) — para auditar si el arqueo no cuadra
            </p>
            {p.casos.map((c) => (
              <div key={c.caso} className="flex justify-between gap-3 text-xs">
                <span className="font-display tabular-nums text-ink-900">{c.caso}</span>
                <span className="text-graphite truncate">{c.factura}</span>
                <span className="tabular-nums text-ink-900">{formatMoney(c.cobrado)}</span>
              </div>
            ))}
          </div>
        )}

        {p.notas_credito.cantidad > 0 && (
          <p className="border-t border-border pt-2 text-[0.68rem] text-graphite">
            {p.notas_credito.cantidad} nota(s) crédito por {formatMoney(p.notas_credito.total)}.
            <span className="text-ochre"> No es plata</span> — explica las prendas
            que entraron al inventario.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
