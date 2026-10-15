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

/**
 * NO RECIBE PROPS. Se trae sus propios datos.
 *
 * La primera versión los recibía del resumen de /finanzas, y el resultado fue
 * que arreglé una pantalla y dejé la de Contraentrega —que es LA pantalla del
 * COD— mostrando el bruto de siempre. Un bloque que solo funciona donde le
 * pasan los props se olvida en la siguiente pantalla.
 *
 * Usa el mismo queryKey que la página de Finanzas, así que cuando conviven no
 * se pide dos veces: React Query comparte la respuesta.
 */
interface ResumenCartera {
  cartera_disponible?: boolean;
  cartera_motivo?: string | null;
  cod_facturado_credito?: number;
  n_cod_facturado_credito?: number;
  cod_cobrado_directo?: number;
  n_cod_cobrado_directo?: number;
  cod_sin_facturar?: number;
  n_cod_sin_facturar?: number;
  cod_recaudo_medible?: boolean;
  cod_nota_recaudo?: string | null;
  cod_melonn_debe?: number;
  n_cod_melonn_debe?: number;
  cod_melonn_recaudado?: number;
  n_cod_melonn_recaudado?: number;
  cod_entregados?: number;
}

// Cruce PERSISTIDO por orden (tabla cruce_cod_siigo) — completo, sin capar.
// `clasificacion` traduce el saldo contable de Siigo a la VERDAD operativa:
// para COD el saldo NO es deuda (la factura se cierra contra la cuenta crédito
// a 10 días y el recibo se postea con 1-3 meses de atraso). Ver backend
// cartera_cod._clasificar.
interface OrdenCruce {
  orden: string; estado: string; clasificacion?: string; fuente_pago?: string | null;
  facturado: number; saldo: number; a_credito: boolean; medio?: string | null;
  entrega?: string | null; ciudad?: string | null; dias?: number | null;
  facturas?: string[];
}
interface OrdenesResp {
  ordenes: OrdenCruce[];
  resumen: Record<string, { n: number; facturado: number; saldo: number }>;
  total: number;
  nota?: string;
}

type Clasif = "pendiente" | "pagado" | "revisar" | "sin_factura";
const CLASIF_META: Record<Clasif, { label: string; chip: string; hint: string }> = {
  pendiente:   { label: "Pendiente de pago", chip: "bg-amber-500/15 text-amber-600",
                 hint: "Entregado y sin conciliar — pendiente de pago/recaudo por Melonn" },
  pagado:      { label: "Pagado",            chip: "bg-sage/15 text-sage",
                 hint: "Conciliado por el archivo de Melonn, o recibo ya posteado en Siigo" },
  revisar:     { label: "A revisar",         chip: "bg-terracotta/15 text-terracotta",
                 hint: "Sin conciliar y ya viejo (o medio directo con saldo) — anomalía real" },
  sin_factura: { label: "Sin factura",       chip: "bg-terracotta/15 text-terracotta",
                 hint: "Salió mercancía sin factura de venta — lo cierra contabilidad" },
};
const CLASIF_ORDEN: Clasif[] = ["pendiente", "revisar", "sin_factura", "pagado"];

export function CarteraCod() {
  const [abierto, setAbierto] = useState(false);
  const [busca, setBusca] = useState("");
  const [fEst, setFEst] = useState<"todas" | Clasif>("todas");

  const { data: res, isLoading } = useQuery<ResumenCartera>({
    queryKey: ["finanzas", "resumen"],
    queryFn: () => api.get<ResumenCartera>("/api/finanzas/resumen"),
    staleTime: 5 * 60_000,
  });

  const disponible     = res?.cartera_disponible;
  const motivo         = res?.cartera_motivo;
  const credito        = res?.cod_facturado_credito ?? 0;
  const nCredito       = res?.n_cod_facturado_credito ?? 0;
  const directo        = res?.cod_cobrado_directo ?? 0;
  const nDirecto       = res?.n_cod_cobrado_directo ?? 0;
  const sinFacturar    = res?.cod_sin_facturar ?? 0;
  const nSinFacturar   = res?.n_cod_sin_facturar ?? 0;
  const nota           = res?.cod_nota_recaudo;
  const medible        = res?.cod_recaudo_medible ?? false;
  const debe           = res?.cod_melonn_debe ?? 0;
  const nDebe          = res?.n_cod_melonn_debe ?? 0;
  const recaudado      = res?.cod_melonn_recaudado ?? 0;
  const nRecaudado     = res?.n_cod_melonn_recaudado ?? 0;
  const brutoEntregado = res?.cod_entregados ?? 0;

  // Cruce COMPLETO por orden (tabla persistida cruce_cod_siigo) — 0 llamadas a
  // Siigo/Melonn, ya clasificado por la verdad operativa. Reemplaza al viejo
  // detalle en vivo, que capaba a 300 y pintaba el saldo como si fuera deuda.
  const { data: ords } = useQuery<OrdenesResp>({
    queryKey: ["finanzas", "cartera-cod", "ordenes"],
    queryFn: () => api.get<OrdenesResp>("/api/finanzas/cartera-cod/ordenes"),
    enabled: abierto,
    staleTime: 10 * 60_000,
  });

  // El `useQuery` va ANTES de cualquier return: un hook detrás de un `if`
  // cambia el orden de hooks entre renders y React revienta con "Rendered more
  // hooks than during the previous render". El build no lo marca; el navegador
  // sí, en cuanto llegan los datos.
  if (isLoading || !res) return null;

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

  // Filtrado de la tabla por orden desde el cruce persistido, ya clasificado.
  const ordenes = ords?.ordenes ?? [];
  const q = busca.trim().toLowerCase();
  const filtradas = ordenes.filter((o) => {
    const c = (o.clasificacion ?? "") as Clasif;
    if (fEst !== "todas" && c !== fEst) return false;
    if (!q) return true;
    return (
      o.orden.toLowerCase().includes(q) ||
      (o.ciudad ?? "").toLowerCase().includes(q) ||
      (o.facturas ?? []).some((f) => f.toLowerCase().includes(q))
    );
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-lg font-medium text-ink-900 dark:text-foreground">
          <Wallet className="h-4 w-4 text-graphite" aria-hidden />
          Cartera contraentrega
        </h2>
        <span className="text-[0.68rem] text-graphite">
          Melonn + Siigo, cruzados por número de orden
        </span>
      </div>

      <Card>
        <CardContent className="space-y-4 py-4">
          {/* LA DEUDA REAL, primero y grande. Sale de restarle a lo entregado
              lo que Melonn REPORTA haber recaudado (módulo de conciliación).
              Siigo no sirve para esto: sus facturas COD se cierran contra la
              cuenta de crédito a 10 días, no contra un banco. */}
          {medible && (
            <div className="grid gap-4 border-b border-border/60 pb-4 sm:grid-cols-2">
              <div>
                <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                  Melonn no ha reportado recaudo
                </p>
                <p className={`mt-0.5 font-display text-3xl tabular-nums ${debe > 0 ? "text-terracotta" : "text-sage"}`}>
                  {formatMoney(debe)}
                </p>
                <p className="text-[0.68rem] text-graphite">
                  {nDebe} pedidos entregados · esto es lo que se reclama
                </p>
              </div>
              <div>
                <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                  Recaudo reportado
                </p>
                <p className="mt-0.5 font-display text-2xl tabular-nums text-sage">
                  {formatMoney(recaudado)}
                </p>
                <p className="text-[0.68rem] text-graphite">
                  {nRecaudado} pedidos · Melonn confirma haber cobrado
                </p>
              </div>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Facturado a crédito COD
              </p>
              <p className="mt-0.5 font-display text-2xl tabular-nums text-ink-900 dark:text-foreground">
                {formatMoney(credito)}
              </p>
              <p className="text-[0.68rem] text-graphite">
                {nCredito} facturas · cuenta «contraentrega 10 días»
              </p>
            </div>
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Cobrado por otro medio
              </p>
              <p className="mt-0.5 font-display text-xl tabular-nums text-sage">
                {formatMoney(directo)}
              </p>
              <p className="text-[0.68rem] text-graphite">
                {nDirecto} facturas · banco, ADDI, efectivo…
              </p>
            </div>
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Entregado sin factura
              </p>
              <p className={`mt-0.5 flex items-center gap-1.5 font-display text-xl tabular-nums ${nSinFacturar > 0 ? "text-terracotta" : "text-ink-900 dark:text-foreground"}`}>
                {nSinFacturar > 0 && <FileWarning className="h-4 w-4" aria-hidden />}
                {formatMoney(sinFacturar)}
              </p>
              <p className="text-[0.68rem] text-graphite">
                {nSinFacturar} pedidos · de {formatMoneyShort(brutoEntregado)} entregado
              </p>
            </div>
          </div>

          {/* LO QUE ESTA PANTALLA NO SABE, DICHO. La primera versión afirmaba
              "Melonn nos debe X" usando el saldo de la factura, y estaba mal:
              esas facturas se cierran contra la cuenta de crédito a 10 días, no
              contra un banco. Un número redondo y falso se usa para decidir. */}
          {nota && (
            <p className="flex items-start gap-2 rounded-sm border border-border/60 bg-cloud/40 px-3 py-2 text-[0.7rem] leading-snug text-graphite dark:bg-ink-800/40">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden />
              {nota}
            </p>
          )}

          <button
            type="button"
            onClick={() => setAbierto((v) => !v)}
            className="flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-navy-600 hover:underline"
          >
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${abierto ? "rotate-180" : ""}`} />
            {abierto ? "Ocultar detalle" : "Ver detalle por orden"}
          </button>

          {abierto && !ords && (
            <p className="text-xs text-graphite">Cargando cruce por orden…</p>
          )}

          {abierto && ords && (
            <div className="space-y-4 border-t border-border/60 pt-4">
              {/* La aclaración que evita leer el saldo como deuda. */}
              {ords.nota && (
                <p className="flex items-start gap-2 rounded-sm border border-border/60 bg-cloud/40 px-3 py-2 text-[0.7rem] leading-snug text-graphite dark:bg-ink-800/40">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden />
                  {ords.nota}
                </p>
              )}

              {/* Clasificación operativa: pendiente de pago / pagado / a
                  revisar / sin factura. Se filtra la tabla haciendo clic. */}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {CLASIF_ORDEN.map((c) => {
                  const b = ords.resumen[c] ?? { n: 0, facturado: 0, saldo: 0 };
                  const monto = c === "pagado" ? b.facturado : b.saldo;
                  const activo = fEst === c;
                  return (
                    <button
                      key={c}
                      type="button"
                      title={CLASIF_META[c].hint}
                      onClick={() => setFEst(activo ? "todas" : c)}
                      className={`rounded-md border px-2.5 py-2 text-left transition ${
                        activo ? "border-navy-600 ring-1 ring-navy-600/40" : "border-border/60 hover:border-navy-600/50"
                      }`}
                    >
                      <span className={`inline-block rounded-full px-1.5 py-0.5 text-[0.6rem] font-semibold ${CLASIF_META[c].chip}`}>
                        {CLASIF_META[c].label}
                      </span>
                      <p className="mt-1 font-display text-lg tabular-nums text-ink-900 dark:text-foreground">{b.n}</p>
                      <p className="text-[0.62rem] tabular-nums text-graphite">
                        {monto > 0 ? formatMoneyShort(monto) : "—"}
                      </p>
                    </button>
                  );
                })}
              </div>

              {/* Buscador por orden / ciudad / factura. */}
              <div className="flex items-center gap-2">
                <input
                  type="search"
                  value={busca}
                  onChange={(e) => setBusca(e.target.value)}
                  placeholder="Buscar orden, ciudad o factura…"
                  className="w-full rounded-md border border-border/60 bg-transparent px-3 py-1.5 text-xs text-ink-900 outline-none focus:border-navy-600 dark:text-foreground"
                />
                {(fEst !== "todas" || q) && (
                  <button
                    type="button"
                    onClick={() => { setFEst("todas"); setBusca(""); }}
                    className="shrink-0 text-[0.68rem] font-semibold text-navy-600 hover:underline"
                  >
                    Limpiar
                  </button>
                )}
              </div>

              <p className="text-[0.68rem] text-graphite">
                {filtradas.length} de {ords.total} órdenes
              </p>

              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-background">
                    <tr className="text-left text-[0.62rem] uppercase tracking-wider text-graphite">
                      <th className="py-1 pr-2 font-medium">Orden</th>
                      <th className="py-1 pr-2 font-medium">Estado</th>
                      <th className="py-1 pr-2 text-right font-medium">Días</th>
                      <th className="py-1 pr-2 font-medium">Ciudad</th>
                      <th className="py-1 pr-2 text-right font-medium">Facturado</th>
                      <th className="py-1 text-right font-medium">Saldo Siigo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtradas.map((o) => {
                      const c = (o.clasificacion ?? "pendiente") as Clasif;
                      const meta = CLASIF_META[c] ?? CLASIF_META.pendiente;
                      return (
                        <tr key={o.orden} className="border-b border-border/40">
                          <td className="py-1.5 pr-2 font-semibold tabular-nums text-ink-900 dark:text-foreground">#{o.orden}</td>
                          <td className="py-1.5 pr-2 whitespace-nowrap">
                            <span className={`inline-block rounded-full px-1.5 py-0.5 text-[0.58rem] font-semibold ${meta.chip}`}>
                              {meta.label}
                            </span>
                            {c === "pagado" && o.fuente_pago && (
                              <span className="ml-1 text-[0.55rem] text-graphite">
                                {o.fuente_pago === "archivo" ? "· archivo" : "· Siigo"}
                              </span>
                            )}
                          </td>
                          <td className="py-1.5 pr-2 text-right tabular-nums text-graphite">
                            {o.dias == null ? "—" : `${o.dias}d`}
                          </td>
                          <td className="py-1.5 pr-2 max-w-[7rem] truncate text-graphite">{o.ciudad || "—"}</td>
                          <td className="py-1.5 pr-2 text-right tabular-nums text-graphite">{formatMoney(o.facturado)}</td>
                          <td className={`py-1.5 text-right tabular-nums font-semibold ${
                            o.saldo > 0 ? (c === "revisar" ? "text-terracotta" : "text-amber-600") : "text-sage"
                          }`}>
                            {formatMoney(o.saldo)}
                          </td>
                        </tr>
                      );
                    })}
                    {!filtradas.length && (
                      <tr>
                        <td colSpan={6} className="py-4 text-center text-graphite">Sin resultados</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
