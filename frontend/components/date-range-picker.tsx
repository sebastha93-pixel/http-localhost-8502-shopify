"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Calendar, ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";

/**
 * DateRangePicker — filtro de fecha estilo Shopify.
 * Botón desplegable → panel con presets a la izquierda y calendario de rango a
 * la derecha. Emite {periodo, desde, hasta} (ISO YYYY-MM-DD). Los presets usan
 * los mismos nombres que resuelve el backend (hoy/ayer/7d/30d/mes/ytd/custom).
 */

export type Periodo = "hoy" | "ayer" | "7d" | "30d" | "mes" | "ytd" | "custom";

export interface RangoValor {
  periodo: Periodo;
  desde: string; // ISO YYYY-MM-DD
  hasta: string; // ISO YYYY-MM-DD
}

const PRESETS: Array<{ id: Periodo; label: string }> = [
  { id: "hoy", label: "Hoy" },
  { id: "ayer", label: "Ayer" },
  { id: "7d", label: "Últimos 7 días" },
  { id: "30d", label: "Últimos 30 días" },
  { id: "mes", label: "Mes en curso" },
  { id: "ytd", label: "Año en curso" },
];

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const MESES_LARGO = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
const DIAS = ["L", "M", "M", "J", "V", "S", "D"]; // semana inicia lunes

function toISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}
function parseISO(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}
function hoyDate(): Date {
  const n = new Date();
  return new Date(n.getFullYear(), n.getMonth(), n.getDate());
}
function addDias(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}

/** Resuelve el rango (desde,hasta ISO) de un preset. Debe coincidir con el backend. */
export function rangoDePreset(periodo: Periodo): { desde: string; hasta: string } {
  const hoy = hoyDate();
  switch (periodo) {
    case "hoy":
      return { desde: toISO(hoy), hasta: toISO(hoy) };
    case "ayer": {
      const a = addDias(hoy, -1);
      return { desde: toISO(a), hasta: toISO(a) };
    }
    case "7d":
      return { desde: toISO(addDias(hoy, -6)), hasta: toISO(hoy) };
    case "30d":
      return { desde: toISO(addDias(hoy, -29)), hasta: toISO(hoy) };
    case "mes":
      return { desde: toISO(new Date(hoy.getFullYear(), hoy.getMonth(), 1)), hasta: toISO(hoy) };
    case "ytd":
      return { desde: toISO(new Date(hoy.getFullYear(), 0, 1)), hasta: toISO(hoy) };
    default:
      return { desde: toISO(hoy), hasta: toISO(hoy) };
  }
}

function fmtCorto(iso: string): string {
  const d = parseISO(iso);
  return `${d.getDate()} ${MESES[d.getMonth()]}`;
}
function labelBoton(v: RangoValor): { titulo: string; rango: string } {
  const preset = PRESETS.find((p) => p.id === v.periodo);
  const titulo = preset ? preset.label : "Personalizado";
  const rango = v.desde === v.hasta ? fmtCorto(v.desde) : `${fmtCorto(v.desde)} – ${fmtCorto(v.hasta)}`;
  return { titulo, rango };
}

/** Celdas (6 semanas) del mes que contiene `refDate`, inicio en lunes. */
function celdasMes(refDate: Date): Array<Date | null> {
  const primero = new Date(refDate.getFullYear(), refDate.getMonth(), 1);
  const offset = (primero.getDay() + 6) % 7; // lunes=0
  const celdas: Array<Date | null> = [];
  for (let i = 0; i < offset; i++) celdas.push(null);
  const diasEnMes = new Date(refDate.getFullYear(), refDate.getMonth() + 1, 0).getDate();
  for (let d = 1; d <= diasEnMes; d++) celdas.push(new Date(refDate.getFullYear(), refDate.getMonth(), d));
  while (celdas.length % 7 !== 0) celdas.push(null);
  while (celdas.length < 42) celdas.push(null);
  return celdas;
}

export function DateRangePicker({ value, onChange, className }: {
  value: RangoValor;
  onChange: (v: RangoValor) => void;
  className?: string;
}) {
  const [abierto, setAbierto] = useState(false);
  const [mesVista, setMesVista] = useState<Date>(() => parseISO(value.hasta || toISO(hoyDate())));
  // Selección en curso dentro del calendario
  const [selDesde, setSelDesde] = useState<string | null>(value.desde);
  const [selHasta, setSelHasta] = useState<string | null>(value.hasta);
  const ref = useRef<HTMLDivElement>(null);
  const hoyISO = toISO(hoyDate());

  useEffect(() => {
    if (!abierto) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setAbierto(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [abierto]);

  // Al abrir, sincroniza la selección con el valor externo
  useEffect(() => {
    if (abierto) {
      setSelDesde(value.desde);
      setSelHasta(value.hasta);
      setMesVista(parseISO(value.hasta || hoyISO));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abierto]);

  const { titulo, rango } = labelBoton(value);

  function aplicarPreset(p: Periodo) {
    const r = rangoDePreset(p);
    onChange({ periodo: p, desde: r.desde, hasta: r.hasta });
    setAbierto(false);
  }

  function clickDia(iso: string) {
    // Sin rango o rango completo → empieza uno nuevo
    if (!selDesde || (selDesde && selHasta)) {
      setSelDesde(iso);
      setSelHasta(null);
      return;
    }
    // Segundo click
    if (iso >= selDesde) {
      setSelHasta(iso);
      onChange({ periodo: "custom", desde: selDesde, hasta: iso });
      setAbierto(false);
    } else {
      setSelDesde(iso); // click anterior al inicio → reinicia
      setSelHasta(null);
    }
  }

  const celdas = useMemo(() => celdasMes(mesVista), [mesVista]);
  const enRango = (iso: string) =>
    selDesde && selHasta ? iso >= selDesde && iso <= selHasta : false;

  return (
    <div ref={ref} className={`relative inline-block ${className || ""}`}>
      <button
        type="button"
        onClick={() => setAbierto((a) => !a)}
        className="inline-flex items-center gap-2 rounded-sm border border-border bg-card px-3 py-1.5 text-xs font-medium text-ink-900 transition-colors hover:bg-cloud/60"
      >
        <Calendar className="h-3.5 w-3.5 text-graphite" />
        <span>{titulo}</span>
        <span className="text-graphite">·</span>
        <span className="text-graphite tabular-nums">{rango}</span>
        <ChevronDown className="h-3.5 w-3.5 text-graphite" />
      </button>

      {abierto && (
        <div className="absolute left-0 z-50 mt-1.5 flex flex-col overflow-hidden rounded-md border border-border bg-card shadow-lg sm:flex-row">
          {/* Presets */}
          <div className="flex shrink-0 flex-col border-b border-border p-1.5 sm:w-40 sm:border-b-0 sm:border-r">
            {PRESETS.map((p) => {
              const activo = value.periodo === p.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => aplicarPreset(p.id)}
                  className={`rounded-sm px-2.5 py-1.5 text-left text-xs font-medium transition-colors ${
                    activo ? "bg-ink-900 text-white" : "text-ink-900 hover:bg-cloud/70"
                  }`}
                >
                  {p.label}
                </button>
              );
            })}
            <div className={`rounded-sm px-2.5 py-1.5 text-left text-xs font-medium ${
              value.periodo === "custom" ? "bg-ink-900 text-white" : "text-graphite"
            }`}>
              Personalizado
            </div>
          </div>

          {/* Calendario */}
          <div className="p-3">
            <div className="mb-2 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setMesVista(new Date(mesVista.getFullYear(), mesVista.getMonth() - 1, 1))}
                className="rounded-sm p-1 text-graphite hover:bg-cloud"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="text-xs font-semibold text-ink-900">
                {MESES_LARGO[mesVista.getMonth()]} {mesVista.getFullYear()}
              </span>
              <button
                type="button"
                onClick={() => setMesVista(new Date(mesVista.getFullYear(), mesVista.getMonth() + 1, 1))}
                disabled={mesVista.getFullYear() === hoyDate().getFullYear() && mesVista.getMonth() >= hoyDate().getMonth()}
                className="rounded-sm p-1 text-graphite hover:bg-cloud disabled:opacity-30 disabled:hover:bg-transparent"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
            <div className="grid grid-cols-7 gap-0.5">
              {DIAS.map((d, i) => (
                <div key={i} className="py-1 text-center text-[0.6rem] font-semibold uppercase text-graphite">{d}</div>
              ))}
              {celdas.map((c, i) => {
                if (!c) return <div key={i} />;
                const iso = toISO(c);
                const futuro = iso > hoyISO;
                const esInicio = iso === selDesde;
                const esFin = iso === selHasta;
                const dentro = enRango(iso);
                return (
                  <button
                    key={i}
                    type="button"
                    disabled={futuro}
                    onClick={() => clickDia(iso)}
                    className={`h-8 w-8 rounded-sm text-xs tabular-nums transition-colors ${
                      esInicio || esFin
                        ? "bg-ink-900 font-semibold text-white"
                        : dentro
                        ? "bg-navy-600/15 text-ink-900"
                        : futuro
                        ? "text-graphite/30"
                        : "text-ink-900 hover:bg-cloud"
                    }`}
                  >
                    {c.getDate()}
                  </button>
                );
              })}
            </div>
            <div className="mt-2 flex items-center justify-between border-t border-border pt-2 text-[0.62rem] text-graphite">
              <span className="tabular-nums">
                {selDesde ? fmtCorto(selDesde) : "—"} → {selHasta ? fmtCorto(selHasta) : "…"}
              </span>
              <span>Elige inicio y fin</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
