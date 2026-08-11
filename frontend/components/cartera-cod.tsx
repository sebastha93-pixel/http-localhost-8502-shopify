"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, FileWarning, Link2Off, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney, formatMoneyShort } from "@/lib/utils";

/**
 * Cartera de contraentrega: lo que Melonn debe DE VERDAD.
 *
 * POR QUÉ EXISTE (2026-08-10): el tablero mostraba $168.388.033 de "COD
 * entregado". Ese número suma todo lo entregado en la ventana de 90 días y
 * nunca descuenta lo que Melonn ya consignó, así que solo crece. La deuda real
 * ese mismo día era $36.552.345 — inflado 4,6 veces. Con esa cifra no se puede
 * reclamar ni proyectar caja.
 *
 * El dato sale del `balance` de cada factura de venta en Siigo: si está en 0,
 * la plata entró; si no, Melonn la tiene. No se calcula, se lee.
 *
 * Las dos listas son para PERSEGUIR, no para mirar:
 *   · las facturas con saldo, de la más vieja primero → se le reclama a Melonn
 *   · los entregados sin factura → lo arregla contabilidad, no Melonn
 */

interface Props {
  disponible?: boolean;
  motivo?: string | null;
  melonnDebe?: number;
  nMelonnDebe?: number;
  yaCobrado?: number;
  sinFacturar?: number;
  nSinFacturar?: number;
  enTransito?: number;
  brutoEntregado?: number;
}

interface Abierta {
  factura: string; fecha: string; orden: string; saldo: number;
  dias: number | null; entrega: string; ciudad?: string | null; url?: string | null;
}
interface SinFactura {
  orden: string; valor: number; entrega: string; ciudad?: string | null;
}
interface Detalle {
  disponible: boolean;
  antiguedad?: Record<string, number>;
  abiertas?: Abierta[];
  sin_factura?: SinFactura[];
}

export function CarteraCod({
  disponible, motivo, melonnDebe = 0, nMelonnDebe = 0, yaCobrado = 0,
  sinFacturar = 0, nSinFacturar = 0, enTransito = 0, brutoEntregado = 0,
}: Props) {
  const [abierto, setAbierto] = useState(false);

  // El detalle solo se pide cuando se despliega: son ~90 páginas de Siigo del
  // lado del backend y no tiene sentido pagarlas si nadie va a mirar la lista.
  const { data: det } = useQuery<Detalle>({
    queryKey: ["finanzas", "cartera-cod"],
    queryFn: () => api.get<Detalle>("/api/finanzas/cartera-cod"),
    enabled: abierto,
    staleTime: 10 * 60_000,
  });

  // Siigo no respondió: se dice. NO se pintan ceros — un tablero de plata en
  // cero se lee como "no nos deben nada", que es la peor mentira que puede
  // contar esta pantalla.
  if (disponible === false) {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 py-4">
          <Link2Off className="mt-0.5 h-4 w-4 shrink-0 text-terracotta" aria-hidden />
          <div>
            <p className="text-sm font-semibold text-ink-900 dark:text-foreground">
              No se pudo consultar la cartera en Siigo
            </p>
            <p className="mt-1 text-xs leading-snug text-graphite">
              Estos números no se están mostrando — no son cero. Lo de arriba
              («Entregados») es el bruto de 90 días, que incluye lo que Melonn
              ya consignó.{motivo ? ` Motivo: ${motivo}` : ""}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const tramos = det?.antiguedad ?? {};
  const viejo = (tramos["31-60"] ?? 0) + (tramos["60+"] ?? 0);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-lg font-medium text-ink-900 dark:text-foreground">
          <Wallet className="h-4 w-4 text-graphite" aria-hidden />
          Cartera contraentrega · cruzada con Siigo
        </h2>
        <span className="text-[0.68rem] text-graphite">
          saldo de cada factura, no el bruto entregado
        </span>
      </div>

      <Card>
        <CardContent className="space-y-4 py-4">
          <div className="grid gap-4 sm:grid-cols-4">
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Melonn nos debe
              </p>
              <p className="mt-0.5 font-display text-2xl tabular-nums text-ink-900 dark:text-foreground">
                {formatMoney(melonnDebe)}
              </p>
              <p className="text-[0.68rem] text-graphite">{nMelonnDebe} facturas con saldo</p>
            </div>
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Ya consignado
              </p>
              <p className="mt-0.5 font-display text-xl tabular-nums text-sage">
                {formatMoney(yaCobrado)}
              </p>
              <p className="text-[0.68rem] text-graphite">
                de {formatMoneyShort(brutoEntregado)} entregado
              </p>
            </div>
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Entregado sin facturar
              </p>
              <p className={`mt-0.5 flex items-center gap-1.5 font-display text-xl tabular-nums ${nSinFacturar > 0 ? "text-terracotta" : "text-ink-900 dark:text-foreground"}`}>
                {nSinFacturar > 0 && <FileWarning className="h-4 w-4" aria-hidden />}
                {formatMoney(sinFacturar)}
              </p>
              <p className="text-[0.68rem] text-graphite">{nSinFacturar} pedidos sin factura</p>
            </div>
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Aún en tránsito
              </p>
              <p className="mt-0.5 font-display text-xl tabular-nums text-graphite">
                {formatMoney(enTransito)}
              </p>
              <p className="text-[0.68rem] text-graphite">facturado, no entregado</p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setAbierto((v) => !v)}
            className="flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-navy-600 hover:underline"
          >
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${abierto ? "rotate-180" : ""}`} />
            {abierto ? "Ocultar detalle" : "Ver qué reclamar"}
          </button>

          {abierto && !det && (
            <p className="text-xs text-graphite">Consultando Siigo…</p>
          )}

          {abierto && det && (
            <div className="space-y-5 border-t border-border/60 pt-4">
              {/* Antigüedad: una deuda de 5 días es el ciclo normal de Melonn;
                  una de 60 es plata que alguien tiene que ir a buscar. */}
              <div>
                <p className="mb-2 text-[0.68rem] uppercase tracking-widest text-graphite">
                  Antigüedad de la deuda
                </p>
                <div className="flex flex-wrap gap-4 text-xs">
                  {["0-15", "16-30", "31-60", "60+"].map((k) => (
                    <span key={k} className="tabular-nums">
                      <span className="text-graphite">{k} días: </span>
                      <span className={k === "31-60" || k === "60+"
                        ? "font-semibold text-terracotta"
                        : "font-semibold text-ink-900 dark:text-foreground"}>
                        {formatMoneyShort(tramos[k] ?? 0)}
                      </span>
                    </span>
                  ))}
                </div>
                {viejo > 0 && (
                  <p className="mt-1.5 flex items-center gap-1.5 text-[0.7rem] text-terracotta">
                    <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                    {formatMoney(viejo)} llevan más de 30 días. El ciclo normal de
                    Melonn es de días, no de meses.
                  </p>
                )}
              </div>

              {!!det.abiertas?.length && (
                <div>
                  <p className="mb-2 text-[0.68rem] uppercase tracking-widest text-graphite">
                    Facturas con saldo, de la más vieja ({det.abiertas.length})
                  </p>
                  <div className="max-h-72 overflow-y-auto">
                    <table className="w-full text-xs">
                      <tbody>
                        {det.abiertas.map((f) => (
                          <tr key={f.factura} className="border-b border-border/40">
                            <td className="py-1.5 pr-3 font-semibold tabular-nums text-navy-600">{f.factura}</td>
                            <td className="py-1.5 pr-3 tabular-nums text-graphite">{f.fecha}</td>
                            <td className={`py-1.5 pr-3 text-right tabular-nums ${(f.dias ?? 0) > 30 ? "font-semibold text-terracotta" : "text-graphite"}`}>
                              {f.dias == null ? "—" : `${f.dias}d`}
                            </td>
                            <td className="py-1.5 pr-3 tabular-nums text-graphite">#{f.orden}</td>
                            <td className="py-1.5 pr-3 truncate text-graphite">{f.ciudad || "—"}</td>
                            <td className="py-1.5 text-right tabular-nums font-semibold text-ink-900 dark:text-foreground">
                              {formatMoney(f.saldo)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {!!det.sin_factura?.length && (
                <div>
                  <p className="mb-1 text-[0.68rem] uppercase tracking-widest text-terracotta">
                    Entregados SIN factura de venta ({det.sin_factura.length})
                  </p>
                  <p className="mb-2 text-[0.68rem] leading-snug text-graphite">
                    Salió mercancía y el cliente pagó, pero no hay factura en Siigo.
                    Esto no lo debe Melonn: lo debe cerrar contabilidad.
                  </p>
                  <div className="max-h-56 overflow-y-auto">
                    <table className="w-full text-xs">
                      <tbody>
                        {det.sin_factura.map((s) => (
                          <tr key={s.orden} className="border-b border-border/40">
                            <td className="py-1.5 pr-3 tabular-nums font-semibold text-ink-900 dark:text-foreground">#{s.orden}</td>
                            <td className="py-1.5 pr-3 tabular-nums text-graphite">{s.entrega || "—"}</td>
                            <td className="py-1.5 pr-3 truncate text-graphite">{s.ciudad || "—"}</td>
                            <td className="py-1.5 text-right tabular-nums text-ink-900 dark:text-foreground">
                              {formatMoney(s.valor)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
