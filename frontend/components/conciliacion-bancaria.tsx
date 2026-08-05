"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Landmark, Link2Off } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { formatMoney, formatMoneyShort } from "@/lib/utils";

/**
 * Lo que el módulo de conciliación bancaria sabe, dentro del OS.
 *
 * POR QUÉ EXISTE (2026-08-05): el OS podía decir cuánta plata de contraentrega
 * estaba "entregada", pero no cuánta ya había sido consignada — ese eslabón vive
 * en el servicio `male-denim-reconciliation`. Sin él, "en recaudo" era un
 * acumulado de 90 días que solo crecía ($169 M cuando lo medimos).
 *
 * `por_plataforma` responde la pregunta operativa real: cuánto esperar de ADDI,
 * de contraentrega, de MercadoPago, de Wompi.
 *
 * Si el otro servicio no responde, esto lo DICE. No pinta ceros: un tablero de
 * plata en ceros se lee como "no hay nada pendiente", y es la peor mentira que
 * puede contar una pantalla financiera.
 */

interface Plataforma {
  plataforma: string;
  pedidos: number;
  valor: number;
}

interface Resumen {
  disponible: boolean;
  obsoleto?: boolean;
  edad_s?: number;
  motivo?: string;
  pendiente_total?: number;
  excepciones_abiertas?: number;
  cruces?: number;
  banco?: { total?: number; matched?: number; unmatched?: number };
  por_plataforma?: Plataforma[];
}

const NOMBRE: Record<string, string> = {
  addi: "ADDI",
  cod: "Contraentrega",
  mercadopago: "MercadoPago",
  transferencia_bancolombia: "Transferencia Bancolombia",
  wompi: "Wompi",
  sumaspay: "Sumas Pay",
  sin_registro: "Sin registro",
  otro: "Otro",
};

export function ConciliacionBancaria() {
  const { data } = useQuery<Resumen>({
    queryKey: ["finanzas", "conciliacion", "resumen"],
    queryFn: () => api.get<Resumen>("/api/finanzas/conciliacion/resumen"),
    refetchInterval: 180_000,
    retry: 1,
  });

  if (!data) return null;

  // Servicio caído o sin configurar: se dice, no se disimula.
  if (!data.disponible) {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 py-4">
          <Link2Off className="mt-0.5 h-4 w-4 shrink-0 text-terracotta" aria-hidden />
          <div>
            <p className="text-sm font-semibold text-ink-900 dark:text-foreground">
              Conciliación bancaria sin conexión
            </p>
            <p className="mt-1 text-xs leading-snug text-graphite">
              No se pudo consultar el módulo de conciliación, así que estos números
              no se están mostrando — no son cero.
              {data.motivo ? ` Motivo: ${data.motivo}` : ""}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const plataformas = data.por_plataforma ?? [];
  const maxValor = Math.max(...plataformas.map((p) => p.valor), 1);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-lg font-medium text-ink-900 dark:text-foreground">
          <Landmark className="h-4 w-4 text-graphite" aria-hidden />
          Conciliación bancaria
        </h2>
        <div className="flex items-center gap-3 text-[0.68rem] text-graphite tabular-nums">
          {data.obsoleto && (
            <span className="text-amber-700 dark:text-amber-400">
              dato de hace {Math.round((data.edad_s ?? 0) / 60)} min — el servicio no
              respondió ahora
            </span>
          )}
          <span>{data.cruces?.toLocaleString("es-CO")} cruces hechos</span>
        </div>
      </div>

      <Card>
        <CardContent className="space-y-4 py-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Pendiente por recibir
              </p>
              <p className="mt-0.5 font-display text-xl tabular-nums text-ink-900 dark:text-foreground">
                {formatMoney(data.pendiente_total ?? 0)}
              </p>
            </div>
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Movimientos del banco sin cruzar
              </p>
              <p className="mt-0.5 font-display text-xl tabular-nums text-ink-900 dark:text-foreground">
                {data.banco?.unmatched ?? "—"}
                <span className="ml-1 text-xs text-graphite">
                  de {data.banco?.total ?? "—"}
                </span>
              </p>
            </div>
            <div>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">
                Excepciones abiertas
              </p>
              <p className="mt-0.5 flex items-center gap-1.5 font-display text-xl tabular-nums text-ink-900 dark:text-foreground">
                {(data.excepciones_abiertas ?? 0) > 0 && (
                  <AlertTriangle className="h-4 w-4 text-amber-600" aria-hidden />
                )}
                {data.excepciones_abiertas ?? 0}
              </p>
            </div>
          </div>

          {plataformas.length > 0 && (
            <div className="border-t border-border/60 pt-3">
              <p className="mb-2 text-[0.68rem] uppercase tracking-widest text-graphite">
                Cuánto esperar de cada plataforma
              </p>
              <ul className="space-y-1.5">
                {plataformas.map((p) => (
                  <li key={p.plataforma} className="flex items-center gap-3">
                    <span className="w-44 shrink-0 truncate text-xs text-ink-900 dark:text-foreground">
                      {NOMBRE[p.plataforma] ?? p.plataforma}
                    </span>
                    {/* La barra es comparativa, no un porcentaje del total. */}
                    <span className="h-1.5 min-w-[2px] flex-1 rounded-full bg-cloud">
                      <span
                        className="block h-1.5 rounded-full bg-navy-600"
                        style={{ width: `${Math.max((p.valor / maxValor) * 100, 1)}%` }}
                      />
                    </span>
                    <span className="w-24 shrink-0 text-right text-xs tabular-nums text-ink-900 dark:text-foreground">
                      {formatMoneyShort(p.valor)}
                    </span>
                    <span className="w-14 shrink-0 text-right text-[0.68rem] tabular-nums text-graphite">
                      {p.pedidos}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
