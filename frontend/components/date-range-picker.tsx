"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Calendar, ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";

/**
 * DateRangePicker — filtro de fecha estilo Shopify.
 * Botón desplegable → panel con presets a la izquierda y (opcional) calendario
 * de rango a la derecha. Emite {periodo, desde, hasta} (ISO YYYY-MM-DD).
 *
 * Dos modos:
 *  - Con calendario (default): presets de fecha + rango personalizado (Comercial).
 *  - Solo presets (showCalendar={false}): dropdown de presets sin calendario,
 *    para módulos de ventana rolling como Revenue (1h/4h/12h/Hoy/7d…).
 */

export type Periodo = "hoy" | "ayer" | "7d" | "30d" | "mes" | "ytd" | "custom";

export interface RangoValor {
  periodo: string;
  desde?: string; // ISO YYYY-MM-DD
  hasta?: string; // ISO YYYY-MM-DD
}

export interface PresetItem {
  id: string;
  label: string;
}

const PRESETS_FECHA: PresetItem[] = [
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
const IDS_FECHA = new Set(["hoy", "ayer", "7d", "30d", "mes", "ytd"]);

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

/** Resuelve el rango (desde,hasta ISO) de un preset de fecha. Coincide con el backend. */
export function rangoDePreset(periodo: string): { desde: string; hasta: string } {
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

export function DateRangePicker({ value, onChange, presets, showCalendar = true, className }: {
  value: RangoValor;
  onChange: (v: RangoValor) => void;
  presets?: PresetItem[];
  showCalendar?: boolean;
  className?: string;
}) {
  const listaPresets = presets ?? PRESETS_FECHA;
  const [abierto, setAbierto] = useState(false);
  const hoyISO = toISO(hoyDate());

  // Rango efectivo: para un preset de fecha conocido, se deriva; si es custom,
  // usa value.desde/hasta. Así el botón nunca muestra un rango desactualizado.
  const rangoEfectivo = useMemo(() => {
    if (showCalendar && IDS_FECHA.has(value.periodo)) return rangoDePreset(value.periodo);
    return { desde: value.desde || hoyISO, hasta: value.hasta || hoyISO };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.periodo, value.desde, value.hasta, showCalendar]);

  const [mesVista, setMesVista] = useState<Date>(() => parseISO(rangoEfectivo.hasta));
  const [selDesde, setSelDesde] = useState<string | null>(rangoEfectivo.desde);
  const [selHasta, setSelHasta] = useState<string | null>(rangoEfectivo.hasta);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!abierto) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setAbierto(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [abierto]);

  // Al abrir, sincroniza la selección con el rango efectivo actual
  useEffect(() => {
    if (abierto) {
      setSelDesde(rangoEfectivo.desde);
      setSelHasta(rangoEfectivo.hasta);
      setMesVista(parseISO(rangoEfectivo.hasta));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abierto]);

  const presetActivo = listaPresets.find((p) => p.id === value.periodo);
  const titulo = presetActivo ? presetActivo.label : "Personalizado";
  const rangoTxt = rangoEfectivo.desde === rangoEfectivo.hasta
    ? fmtCorto(rangoEfectivo.desde)
    : `${fmtCorto(rangoEfectivo.desde)} – ${fmtCorto(rangoEfectivo.hasta)}`;

  function aplicarPreset(id: string) {
    if (showCalendar && IDS_FECHA.has(id)) {
      const r = rangoDePreset(id);
      onChange({ periodo: id, desde: r.desde, hasta: r.hasta });
    } else {
      onChange({ periodo: id });
    }
    setAbierto(false);
  }

  function clickDia(iso: string) {
    if (!selDesde || (selDesde && selHasta)) {
      setSelDesde(iso);
      setSelHasta(null);
      return;
    }
    if (iso >= selDesde) {
      setSelHasta(iso);
      onChange({ periodo: "custom", desde: selDesde, hasta: iso });
      setAbierto(false);
    } else {
      setSelDesde(iso);
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
        {showCalendar && (
          <>
            <span className="text-graphite">·</span>
            <span className="text-graphite tabular-nums">{rangoTxt}</span>
          </>
        )}
        <ChevronDown className="h-3.5 w-3.5 text-graphite" />
      </button>

      {abierto && (
        <div className="absolute left-0 z-50 mt-1.5 flex flex-col overflow-hidden rounded-md border border-border bg-card shadow-lg sm:flex-row">
          {/* Presets */}
          <div className="flex shrink-0 flex-col gap-0.5 border-b border-border p-1.5 sm:w-44 sm:border-b-0 sm:border-r">
            {listaPresets.map((p) => {
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
            {showCalendar && (
              <div className={`rounded-sm px-2.5 py-1.5 text-left text-xs font-medium ${
                value.periodo === "custom" ? "bg-ink-900 text-white" : "text-graphite"
              }`}>
                Personalizado
              </div>
            )}
          </div>

          {/* Calendario */}
          {showCalendar && (
            <div className="w-[17rem] p-3">
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
                  <div key={i} className="flex h-7 items-center justify-center text-[0.6rem] font-semibold uppercase text-graphite">{d}</div>
                ))}
                {celdas.map((c, i) => {
                  if (!c) return <div key={i} className="h-8" />;
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
                      className={`flex h-8 items-center justify-center rounded-sm text-xs tabular-nums transition-colors ${
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
          )}
        </div>
      )}
    </div>
  );
}
