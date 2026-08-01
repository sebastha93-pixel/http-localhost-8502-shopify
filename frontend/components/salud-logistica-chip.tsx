"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AlertTriangle, CheckCircle2, CircleAlert } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Semáforo de confiabilidad del tablero logístico.
 *
 * POR QUÉ EXISTE (2026-08-01): "Actualizado hace un momento" se refiere a cuándo
 * el navegador pidió los datos, NO a cuándo la app le preguntó a Melonn. Ese
 * mismo malentendido, pero en el backend, es lo que dejó los estados congelados
 * durante horas sin que nada se viera raro. Este chip muestra la edad REAL del
 * dato —minutos desde el último fetch al listado de Melonn— y se pone en rojo
 * cuando el tablero no se puede auditar.
 *
 * La regla: que no haya que contar pedidos a mano para saber si el dato sirve.
 */

interface Hallazgo {
  nivel: "rojo" | "amarillo";
  clave: string;
  mensaje: string;
}

interface Salud {
  semaforo: "verde" | "amarillo" | "rojo";
  hallazgos?: Hallazgo[];
  medidas?: {
    minutos_desde_fetch?: number | null;
    total_tablero?: number;
    pedidos_de_hoy?: number;
  };
}

const ESTILO = {
  verde:    "border-border text-graphite",
  amarillo: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  rojo:     "border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400",
} as const;

function edadTexto(min?: number | null): string {
  if (min === null || min === undefined) return "sin registro";
  if (min < 1) return "hace un momento";
  if (min < 60) return `hace ${Math.round(min)} min`;
  const h = Math.floor(min / 60);
  return h === 1 ? "hace 1 h" : `hace ${h} h`;
}

export function SaludLogisticaChip() {
  const [abierto, setAbierto] = useState(false);
  const { data } = useQuery<Salud>({
    queryKey: ["salud-logistica"],
    queryFn: () => api.get<Salud>("/api/melonn/salud"),
    // Cada 2 min: es un chequeo sobre el caché, no llama a Melonn.
    refetchInterval: 120_000,
    staleTime: 60_000,
    retry: 1,
  });

  if (!data) return null;

  const sem = data.semaforo ?? "verde";
  const hallazgos = data.hallazgos ?? [];
  const Icono = sem === "verde" ? CheckCircle2 : sem === "amarillo" ? CircleAlert : AlertTriangle;
  const min = data.medidas?.minutos_desde_fetch;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setAbierto((v) => !v)}
        title={
          sem === "verde"
            ? "El tablero está al día con Melonn"
            : "Hay problemas de confiabilidad — clic para ver"
        }
        className={`flex shrink-0 items-center gap-1.5 rounded-sm border px-2.5 py-1 text-[0.68rem] tabular-nums transition-colors ${ESTILO[sem]}`}
      >
        <Icono className="h-3 w-3" aria-hidden />
        <span>Melonn {edadTexto(min)}</span>
        {hallazgos.length > 0 && (
          <span className="font-semibold">· {hallazgos.length}</span>
        )}
      </button>

      {abierto && (
        <div className="absolute right-0 top-full z-30 mt-1.5 w-80 rounded-sm border border-border bg-card p-3 text-left shadow-lg">
          <p className="mb-2 text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-graphite">
            Confiabilidad del tablero
          </p>
          {hallazgos.length === 0 ? (
            <p className="text-xs leading-snug text-graphite">
              Sin hallazgos. El tablero tiene {data.medidas?.total_tablero ?? "?"} pedidos
              {typeof data.medidas?.pedidos_de_hoy === "number"
                ? `, ${data.medidas.pedidos_de_hoy} creados hoy`
                : ""}
              , y el listado de Melonn se pidió {edadTexto(min)}.
            </p>
          ) : (
            <ul className="space-y-2">
              {hallazgos.map((h) => (
                <li key={h.clave} className="flex gap-2 text-xs leading-snug">
                  <span
                    className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                      h.nivel === "rojo" ? "bg-red-500" : "bg-amber-500"
                    }`}
                    aria-hidden
                  />
                  <span className="text-ink-900 dark:text-foreground">{h.mensaje}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
