"use client";

/**
 * Tablero de las tiendas — todas, lado a lado.
 *
 * El Panel es de UNA tienda y está amarrado a la caja del equipo: para mirar
 * otra tienda, el equipo pasa a trabajar como caja de esa tienda. Eso le
 * sirve a quien vende. Quien administra quiere abrir una pantalla, sin abrir
 * caja, y saber cuál tienda va adelante, cuál se quedó
 * quieta y si hoy va mejor o peor que antes.
 *
 * SÓLO ENTRA UN ADMINISTRADOR. Lo comprueba el servidor; aquí sólo se pinta
 * el «no puedes».
 *
 * NO PIDE CAJA. Por eso no va envuelto en `ConLaCaja`, como el Panel.
 *
 * SIN COLORES POR TIENDA. El POS es monocromo y tres grises pegados no se
 * distinguen en una tablet con reflejo. Las tiendas se comparan en filas con
 * la MISMA escala: la barra más alta de la pantalla es la hora (o el día) en
 * que más se vendió en cualquiera de ellas.
 */
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Panel as Marco } from "@/components/pos/marco";
import { Rail } from "@/components/pos/rail";
import { formatear } from "@/lib/pos/dinero";
import {
  tableroDeTiendas,
  type Tablero,
  type TiendaDelTablero,
} from "@/lib/pos/api";

const REFRESCO_MS = 60_000;

type Periodo = { desde?: string; hasta?: string };

export default function PantallaTablero() {
  const { user } = useAuth();
  const [periodo, setPeriodo] = useState<Periodo>({});
  const [datos, setDatos] = useState<Tablero | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actualizado, setActualizado] = useState<Date | null>(null);

  const cargar = useCallback(async () => {
    try {
      setDatos(await tableroDeTiendas(periodo));
      setError(null);
      setActualizado(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el tablero.");
    }
  }, [periodo]);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, REFRESCO_MS);
    return () => clearInterval(t);
  }, [cargar]);

  const tiendas = datos?.tiendas ?? [];
  const total = tiendas.reduce(
    (s, t) => ({
      ventas: s.ventas + t.ventas_centavos,
      anterior: s.anterior + t.ventas_anterior_centavos,
      transacciones: s.transacciones + t.transacciones,
      unidades: s.unidades + t.unidades,
      descuentos: s.descuentos + t.descuentos_centavos,
      anuladas: s.anuladas + t.anuladas,
      anulado: s.anulado + t.monto_anulado_centavos,
      devoluciones: s.devoluciones + t.devoluciones,
      devuelto: s.devuelto + t.monto_devuelto_centavos,
    }),
    { ventas: 0, anterior: 0, transacciones: 0, unidades: 0, descuentos: 0,
      anuladas: 0, anulado: 0, devoluciones: 0, devuelto: 0 },
  );
  const esHoy = Boolean(datos && datos.desde === datos.hoy && datos.hasta === datos.hoy);
  const contraQue = datos ? textoDelAnterior(datos) : "";

  return (
    <div className="pos-raiz flex h-screen overflow-hidden">
      <Rail cajera={user?.nombre || user?.email || ""} />

      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
        <header className="flex flex-wrap items-baseline gap-3">
          <h1 className="titular text-[22px] font-semibold tracking-tight">
            Tiendas
          </h1>
          {datos && (
            <p className="tabular text-[12px] text-[var(--pos-600)]">
              {datos.desde === datos.hasta
                ? fechaLarga(datos.desde)
                : `${fechaLarga(datos.desde)} – ${fechaLarga(datos.hasta)}`}
              {actualizado && (
                <span className="ml-2 text-[var(--pos-muted)]">
                  actualizado{" "}
                  {actualizado.toLocaleTimeString("es-CO", {
                    hour: "2-digit", minute: "2-digit",
                  })}
                </span>
              )}
            </p>
          )}
        </header>

        <Rangos hoy={datos?.hoy ?? ""} periodo={periodo}
                onCambiar={(p) => { setDatos(null); setPeriodo(p); }} />

        {error && (
          <p className="max-w-[560px] border-l-2 border-[var(--pos-800)] rounded-[var(--pos-r-sm)] bg-[var(--pos-800)]/10 py-3 pl-4 text-[13px] text-[var(--pos-900)]">
            {error}
          </p>
        )}
        {!datos && !error && (
          <p className="text-[13px] text-[var(--pos-600)]">Cargando…</p>
        )}

        {datos && (
          <>
            <div className="grid shrink-0 grid-cols-2 gap-3 lg:grid-cols-4">
              <Tarjeta
                titulo={esHoy ? "Ventas hoy · todas" : "Ventas del periodo · todas"}
                valor={formatear(total.ventas)}
                pie={variacion(total.ventas, total.anterior, contraQue)}
              />
              <Tarjeta
                titulo="Transacciones"
                valor={String(total.transacciones)}
                pie={total.transacciones
                  ? `ticket promedio ${enPesos(total.ventas / total.transacciones)}`
                  : "—"}
              />
              <Tarjeta
                titulo="Unidades"
                valor={String(total.unidades)}
                pie={total.transacciones
                  ? `${(total.unidades / total.transacciones).toFixed(1)} por venta · ${
                      total.descuentos ? `${formatear(total.descuentos)} en descuentos` : "sin descuentos"}`
                  : "—"}
              />
              <Tarjeta
                titulo="Anuladas y devoluciones"
                valor={`${total.anuladas} · ${total.devoluciones}`}
                pie={total.anuladas || total.devoluciones
                  ? `${formatear(total.anulado)} anulado · ${formatear(total.devuelto)} devuelto`
                  : "ninguna"}
                alerta={total.anuladas > 0}
              />
            </div>

            <div className="grid shrink-0 grid-cols-1 gap-3 lg:grid-cols-3">
              {tiendas.map((t) => (
                <TarjetaTienda key={t.id} t={t} total={total.ventas}
                               hoy={datos.hoy} contraQue={contraQue} />
              ))}
            </div>

            <Marco className="flex shrink-0 flex-col gap-4 p-6">
              <h2 className="titular text-[17px] font-semibold">
                {datos.serie_por === "hora" ? "Ventas por hora" : "Ventas por día"}
              </h2>
              <Serie datos={datos} />
              <p className="tabular text-[12px] text-[var(--pos-600)]">
                Todas las filas usan la misma escala: una barra alta en una
                tienda vale lo mismo que en otra.
                {datos.serie_por === "hora" && " Hora de la tienda."}
              </p>
            </Marco>

            <Marco className="flex shrink-0 flex-col gap-2 p-6">
              <h2 className="titular text-[17px] font-semibold">
                Lo más vendido · todas las tiendas
              </h2>
              {datos.mas_vendidos.length === 0 ? (
                <p className="text-[13px] text-[var(--pos-600)]">
                  Todavía no se ha vendido nada.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] text-[13px]">
                    <thead>
                      <tr className="kicker text-left text-[var(--pos-600)]">
                        <th className="py-2 pr-3 font-normal">Referencia</th>
                        {tiendas.map((t) => (
                          <th key={t.id} className="px-3 py-2 text-right font-normal">
                            {t.nombre}
                          </th>
                        ))}
                        <th className="px-3 py-2 text-right font-normal">Total</th>
                        <th className="py-2 pl-3 text-right font-normal">Valor</th>
                      </tr>
                    </thead>
                    <tbody>
                      {datos.mas_vendidos.map((m) => (
                        <tr key={m.referencia}
                            className="border-t border-[var(--pos-divider)]/60">
                          <td className="py-2 pr-3">
                            <span className="font-medium">{m.nombre}</span>
                            {m.color && (
                              <span className="ml-1.5 text-[var(--pos-600)]">{m.color}</span>
                            )}
                            <span className="tabular block text-[12px] text-[var(--pos-600)]">
                              {m.referencia}
                            </span>
                          </td>
                          {tiendas.map((t) => (
                            <td key={t.id}
                                className={`tabular px-3 py-2 text-right ${
                                  m.tiendas[t.id] ? "" : "text-[var(--pos-400)]"}`}>
                              {m.tiendas[t.id] ?? 0}
                            </td>
                          ))}
                          <td className="tabular px-3 py-2 text-right font-semibold">
                            {m.unidades}
                          </td>
                          <td className="tabular py-2 pl-3 text-right text-[var(--pos-600)]">
                            {formatear(m.valor_centavos)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="tabular mt-1 text-[12px] text-[var(--pos-600)]">
                En unidades, agrupado por referencia.
              </p>
            </Marco>
          </>
        )}
      </main>
    </div>
  );
}

/** Una tienda: cuánto, contra antes, con qué se pagó y quién vendió. */
function TarjetaTienda({
  t, total, hoy, contraQue,
}: {
  t: TiendaDelTablero; total: number; hoy: string; contraQue: string;
}) {
  const parte = total ? Math.round((t.ventas_centavos * 100) / total) : 0;
  const abierta = t.turnos_abiertos.length > 0;
  return (
    <Marco className="flex min-w-0 flex-col gap-3 p-6">
      <div className="flex items-baseline gap-2">
        <h2 className="titular text-[17px] font-semibold">{t.nombre}</h2>
        {/* El estado va con PALABRAS, no con un punto de color: «sin turno
            abierto» a las 11 a.m. es justo lo que hay que alcanzar a leer. */}
        <span
          className={`ml-auto shrink-0 whitespace-nowrap px-2 py-0.5 text-[12px] rounded-[var(--pos-r-pill)] ${
            abierta
              ? "bg-[var(--pos-accent)] text-white"
              : "border border-[var(--pos-divider)] text-[var(--pos-600)]"
          }`}
        >
          {abierta ? "Turno abierto" : "Sin turno abierto"}
        </span>
      </div>

      <div>
        <span className="titular block text-[28px] font-bold leading-none">
          {formatear(t.ventas_centavos)}
        </span>
        <span className="tabular mt-1 block text-[12px] text-[var(--pos-600)]">
          {variacion(t.ventas_centavos, t.ventas_anterior_centavos, contraQue)}
        </span>
      </div>

      <div className="flex items-center gap-2" title="Parte de las ventas de todas las tiendas">
        <span className="relative h-2 min-w-0 flex-1 bg-[var(--pos-100)]">
          <span className="absolute inset-y-0 left-0 bg-[var(--pos-accent)]"
                style={{ width: `${parte}%` }} />
        </span>
        <span className="tabular w-10 shrink-0 text-right text-[12px] text-[var(--pos-600)]">
          {parte}%
        </span>
      </div>

      <dl className="grid grid-cols-3 gap-2 text-[13px]">
        <Dato nombre="Ventas" valor={String(t.transacciones)} />
        <Dato nombre="Ticket" valor={t.transacciones ? enPesos(t.ticket_promedio_centavos) : "—"} />
        <Dato nombre="Unidades" valor={String(t.unidades)} />
      </dl>

      {abierta && (
        <p className="tabular -mb-2 text-[12px] text-[var(--pos-600)]">
          {t.turnos_abiertos.map((x) =>
            `${x.caja}: abrió ${x.abierta_por} · ${horaDe(x.desde, hoy)}`).join(" · ")}
        </p>
      )}
      <p className="tabular text-[12px] text-[var(--pos-600)]">
        {t.ultima_venta
          ? `Última venta: ${horaDe(t.ultima_venta, hoy)}`
          : "Sin ventas en este periodo"}
        {t.descuentos_centavos > 0 && ` · ${formatear(t.descuentos_centavos)} en descuentos`}
        {t.anuladas > 0 && ` · ${t.anuladas} anulada${t.anuladas === 1 ? "" : "s"} (${formatear(t.monto_anulado_centavos)})`}
        {t.devoluciones > 0 && ` · ${t.devoluciones} devoluci${t.devoluciones === 1 ? "ón" : "ones"} (${formatear(t.monto_devuelto_centavos)})`}
      </p>

      {t.medios.length > 0 && (
        <Lista titulo="Cómo pagaron"
               filas={t.medios.map((m) => [m.nombre, formatear(m.centavos)])} />
      )}
      {t.cajeras.length > 0 && (
        <Lista titulo="Quién vendió"
               filas={t.cajeras.map((c) => [
                 `${c.nombre} · ${c.transacciones} venta${c.transacciones === 1 ? "" : "s"}`,
                 formatear(c.ventas_centavos)])} />
      )}
    </Marco>
  );
}

function Dato({ nombre, valor }: { nombre: string; valor: string }) {
  return (
    <div>
      <dt className="kicker text-[var(--pos-600)]">{nombre}</dt>
      <dd className="tabular font-semibold">{valor}</dd>
    </div>
  );
}

function Lista({ titulo, filas }: { titulo: string; filas: [string, string][] }) {
  return (
    <div className="border-t border-[var(--pos-divider)]/60 pt-2">
      <span className="kicker text-[var(--pos-600)]">{titulo}</span>
      {filas.map(([a, b], i) => (
        <div key={i} className="flex items-baseline gap-2 py-0.5 text-[13px]">
          <span className="min-w-0 flex-1 truncate">{a}</span>
          <span className="tabular shrink-0 font-medium">{b}</span>
        </div>
      ))}
    </div>
  );
}

/** Una fila de barras por tienda, todas con la misma escala. */
function Serie({ datos }: { datos: Tablero }) {
  const pico = Math.max(
    1, ...datos.serie.flatMap((p) => Object.values(p.tiendas)));
  // En un mes las etiquetas no caben todas: se pinta una de cada tantas.
  const cada = Math.ceil(datos.serie.length / 16);
  return (
    <div className="flex flex-col gap-3">
      {datos.tiendas.map((t) => (
        <div key={t.id} className="flex items-end gap-3">
          <span className="w-[84px] shrink-0 truncate pb-5 text-[13px] font-medium">
            {t.nombre}
          </span>
          <div className="flex h-[84px] min-w-0 flex-1 items-end gap-1">
            {datos.serie.map((p, i) => {
              const v = p.tiendas[t.id] ?? 0;
              return (
                <div key={p.etiqueta}
                     className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1"
                     title={`${t.nombre} · ${etiquetaDe(p.etiqueta, datos.serie_por)} · ${v ? formatear(v) : "sin ventas"}`}>
                  <div className="w-full max-w-[38px] rounded-t-[2px]"
                       style={{
                         // Mínimo visible: «no se vendió» no es «no hay dato».
                         height: `${Math.max((v / pico) * 100, v ? 5 : 2)}%`,
                         background: v === pico
                           ? "var(--pos-accent)"
                           : v ? "var(--pos-muted)" : "var(--pos-divider)",
                       }} />
                  <span className="h-4 text-[11px] leading-4 text-[var(--pos-600)]">
                    {i % cada === 0 ? etiquetaCorta(p.etiqueta, datos.serie_por) : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Hoy, Ayer, 7 días, Este mes, o un rango a mano. */
function Rangos({
  hoy, periodo, onCambiar,
}: {
  hoy: string; periodo: Periodo; onCambiar: (p: Periodo) => void;
}) {
  // A partir del «hoy» DE LAS TIENDAS que manda el servidor, no del reloj del
  // navegador.
  const mover = (dias: number) => {
    if (!hoy) return "";
    const [a, m, d] = hoy.split("-").map(Number);
    const f = new Date(a, m - 1, d + dias);
    return `${f.getFullYear()}-${String(f.getMonth() + 1).padStart(2, "0")}-${String(f.getDate()).padStart(2, "0")}`;
  };
  const rangos = hoy ? [
    { etiqueta: "Hoy", desde: "", hasta: "" },
    { etiqueta: "Ayer", desde: mover(-1), hasta: mover(-1) },
    { etiqueta: "7 días", desde: mover(-6), hasta: hoy },
    { etiqueta: "Este mes", desde: `${hoy.slice(0, 8)}01`, hasta: hoy },
  ] : [];
  const activo = (r: { desde: string; hasta: string }) =>
    (periodo.desde ?? "") === r.desde && (periodo.hasta ?? "") === r.hasta;
  const campo = "h-9 border border-[var(--pos-divider)] bg-[var(--pos-surface)] px-2 text-[13px] text-[var(--pos-text)]";

  return (
    <div className="flex shrink-0 flex-wrap items-end gap-x-4 gap-y-2">
      <div className="flex gap-1.5">
        {rangos.map((r) => (
          <button key={r.etiqueta} aria-pressed={activo(r)}
                  onClick={() => onCambiar({ desde: r.desde || undefined, hasta: r.hasta || undefined })}
                  className={`h-9 border px-3 text-[13px] ${
                    activo(r)
                      ? "border-[var(--pos-accent)] bg-[var(--pos-accent)]/10 text-[var(--pos-text)]"
                      : "border-[var(--pos-divider)] bg-[var(--pos-surface)] text-[var(--pos-700)]"
                  }`}>
            {r.etiqueta}
          </button>
        ))}
      </div>
      <label className="flex flex-col gap-0.5">
        <span className="kicker text-[var(--pos-600)]">Desde</span>
        <input type="date" value={periodo.desde ?? ""} max={hoy || undefined}
               onChange={(e) => onCambiar({
                 desde: e.target.value || undefined,
                 hasta: periodo.hasta ?? (e.target.value ? hoy : undefined) })}
               className={campo} />
      </label>
      <label className="flex flex-col gap-0.5">
        <span className="kicker text-[var(--pos-600)]">Hasta</span>
        <input type="date" value={periodo.hasta ?? ""} max={hoy || undefined}
               onChange={(e) => onCambiar({ ...periodo, hasta: e.target.value || undefined })}
               className={campo} />
      </label>
    </div>
  );
}

function Tarjeta({
  titulo, valor, pie, alerta,
}: {
  titulo: string; valor: string; pie: string; alerta?: boolean;
}) {
  return (
    <Marco className="flex flex-col gap-1 p-6">
      <span className="kicker text-[var(--pos-700)]">{titulo}</span>
      <span className={`titular text-[28px] font-bold leading-none ${
        alerta ? "text-[var(--pos-accent)]" : ""}`}>
        {valor}
      </span>
      <span className="tabular text-[12px] text-[var(--pos-600)]">{pie}</span>
    </Marco>
  );
}

/** «▲ 12% vs. ayer a esta hora ($1.200.000)». Con palabras además de la
 *  flecha: la flecha sola no dice contra qué. */
function variacion(ahora: number, antes: number, contraQue: string): string {
  if (!antes) {
    // Sin «antes» no hay porcentaje: dividir por cero no es «subió infinito».
    return ahora ? "sin ventas antes para comparar" : "sin ventas, y antes tampoco";
  }
  const pct = Math.round(((ahora - antes) * 100) / antes);
  const flecha = pct > 0 ? "▲" : pct < 0 ? "▼" : "=";
  return `${flecha} ${Math.abs(pct)}% vs. ${contraQue} (${formatear(antes)})`;
}

/** Un promedio, en pesos enteros: «$188.297,50» de ticket es ruido. */
function enPesos(centavos: number): string {
  return formatear(Math.round(centavos / 100) * 100);
}

/** Contra qué se compara, dicho como se diría en voz alta. */
function textoDelAnterior(d: Tablero): string {
  const unDia = d.desde === d.hasta;
  if (unDia && d.hasta === d.hoy) return "ayer a esta hora";
  if (unDia) return "el día anterior";
  const dias = Math.round(
    (fecha(d.hasta).getTime() - fecha(d.desde).getTime()) / 86_400_000) + 1;
  return d.anterior_cortado
    ? `los ${dias} días anteriores, a esta hora`
    : `los ${dias} días anteriores`;
}

function fecha(iso: string): Date {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d);
}

/** `2026-08-12` → `mié, 12 ago`. A mano y no con `new Date(str)`: eso lee la
 *  fecha en UTC y en Bogotá la corre un día atrás. */
function fechaLarga(iso: string): string {
  return fecha(iso).toLocaleDateString("es-CO", {
    weekday: "short", day: "numeric", month: "short",
  });
}

/** `2026-11-13 11:10` → `11:10` si es de hoy; si no, `12 nov 11:10`. */
function horaDe(marca: string, hoy: string): string {
  const [dia, hora] = marca.split(" ");
  if (dia === hoy) return hora;
  return `${fecha(dia).toLocaleDateString("es-CO", { day: "numeric", month: "short" })} ${hora}`;
}

function etiquetaDe(etiqueta: string, por: "hora" | "dia"): string {
  return por === "hora" ? `${etiqueta.replace("h", "")}:00` : fechaLarga(etiqueta);
}

function etiquetaCorta(etiqueta: string, por: "hora" | "dia"): string {
  return por === "hora" ? etiqueta.replace("h", "") : String(Number(etiqueta.slice(8)));
}
