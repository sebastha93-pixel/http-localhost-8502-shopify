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
 * ES LA ENTRADA DEL ADMINISTRADOR AL POS (Sebastián, 2026-11-13). A quien
 * administra no se le pregunta «¿qué caja es este equipo?»: llega aquí, y
 * «Abrir» en una tienda deja el equipo trabajando como una caja de ESA
 * tienda —Venta, Cambios, Stock, Cierre y Panel pasan a ser de ella— y lo
 * lleva a su Panel.
 *
 * SIN COLORES POR TIENDA. El POS es monocromo y tres grises pegados no se
 * distinguen en una tablet con reflejo. Las tiendas se comparan en filas con
 * la MISMA escala: la barra más alta de la pantalla es la hora (o el día) en
 * que más se vendió en cualquiera de ellas.
 */
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { Panel as Marco } from "@/components/pos/marco";
import { Rail } from "@/components/pos/rail";
import { formatear } from "@/lib/pos/dinero";
import {
  cajaDeEsteEquipo,
  cambiarCajaDelEquipo,
  recordarCajaDeTienda,
} from "@/lib/pos/caja-del-equipo";
import {
  listarCajas,
  tableroDeTiendas,
  type CajaDelPos,
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
  const [verDetalle, setVerDetalle] = useState(false);

  // ABRIR UNA TIENDA. Las cajas salen del servidor (un administrador las ve
  // todas); la que este equipo es ahora, de `localStorage`, y por eso se lee
  // en un efecto: el servidor no la conoce y pintarla antes de hidratar
  // daría dos pantallas distintas.
  const router = useRouter();
  const [cajas, setCajas] = useState<CajaDelPos[]>([]);
  const [cajaEquipo, setCajaEquipo] = useState("");
  const [abriendo, setAbriendo] = useState<string | null>(null);
  useEffect(() => {
    setCajaEquipo(cajaDeEsteEquipo());
    // Sin la lista no hay botones de «Abrir», pero el tablero sigue sirviendo.
    listarCajas().then(setCajas).catch(() => setCajas([]));
  }, []);

  const abrir = useCallback(async (c: CajaDelPos) => {
    setAbriendo(c.caja_id);
    const actual = cajaDeEsteEquipo();
    if (actual !== c.caja_id) {
      // Igual que el Panel al cambiar de tienda: se anota qué caja era el
      // equipo en la tienda de la que sale, para devolverlo a ESA.
      const previa = cajas.find((x) => x.caja_id === actual);
      if (previa) recordarCajaDeTienda(previa.tienda_id, previa.caja_id);
      await cambiarCajaDelEquipo(c.caja_id);
    }
    recordarCajaDeTienda(c.tienda_id, c.caja_id);
    router.push("/pos/panel");
  }, [cajas, router]);

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
      cambios: s.cambios + t.cambios,
      enCambios: s.enCambios + t.monto_cambios_centavos,
      reembolsos: s.reembolsos + t.reembolsos,
      reembolsado: s.reembolsado + t.monto_reembolsado_centavos,
    }),
    { ventas: 0, anterior: 0, transacciones: 0, unidades: 0, descuentos: 0,
      anuladas: 0, anulado: 0, cambios: 0, enCambios: 0, reembolsos: 0,
      reembolsado: 0 },
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
            {/* Una columna en pantallas angostas: a dos, en un celular, el
                total de ventas se cortaba («$1.923…»). */}
            <div className="grid shrink-0 grid-cols-1 gap-3 min-[560px]:grid-cols-2 lg:grid-cols-4">
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
              {/* UN CAMBIO NO ES PLATA DEVUELTA. Casi todo lo que entra por
                  «Cambios» queda como crédito de tienda; decir «$924.420
                  devuelto» hacía leer plata que nunca salió de la caja. Lo
                  que sí se devolvió en dinero va aparte, y es lo que alerta.
                  Se toca para ver cuáles son: una cifra sin su lista sólo
                  deja la pregunta. */}
              <Tarjeta
                titulo="Anuladas y cambios"
                valor={`${total.anuladas} · ${total.cambios}`}
                pie={[
                  total.anuladas ? `${formatear(total.anulado)} anulado` : "ninguna anulada",
                  total.cambios ? `${formatear(total.enCambios)} en cambios` : "ningún cambio",
                  total.reembolsos
                    ? `${total.reembolsos} devoluci${total.reembolsos === 1 ? "ón" : "ones"} en dinero (${formatear(total.reembolsado)})`
                    : "",
                ].filter(Boolean).join(" · ")}
                alerta={total.anuladas > 0 || total.reembolsos > 0}
                abierto={verDetalle}
                onAbrir={total.anuladas + total.cambios + total.reembolsos > 0
                  ? () => setVerDetalle((v) => !v) : undefined}
              />
            </div>

            {verDetalle && <Detalle datos={datos} />}

            <div className="grid shrink-0 grid-cols-1 gap-3 lg:grid-cols-3">
              {tiendas.map((t) => (
                <TarjetaTienda key={t.id} t={t} total={total.ventas}
                               hoy={datos.hoy} contraQue={contraQue}
                               cajas={cajas.filter((c) => c.tienda_id === t.id)}
                               cajaEquipo={cajaEquipo} abriendo={abriendo}
                               onAbrir={(c) => { void abrir(c); }} />
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
  t, total, hoy, contraQue, cajas, cajaEquipo, abriendo, onAbrir,
}: {
  t: TiendaDelTablero; total: number; hoy: string; contraQue: string;
  /** Las cajas de ESTA tienda. Vacío si no se pudo traer la lista. */
  cajas: CajaDelPos[];
  /** La caja con la que este equipo trabaja ahora; vacío si ninguna. */
  cajaEquipo: string;
  abriendo: string | null;
  onAbrir: (c: CajaDelPos) => void;
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
        {t.cambios > 0 && ` · ${t.cambios} cambio${t.cambios === 1 ? "" : "s"} (${formatear(t.monto_cambios_centavos)})`}
        {t.reembolsos > 0 && ` · ${t.reembolsos} devoluci${t.reembolsos === 1 ? "ón" : "ones"} en dinero (${formatear(t.monto_reembolsado_centavos)})`}
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

      {/* ABRIR LA TIENDA. `mt-auto`: los botones quedan al pie aunque una
          tarjeta tenga menos renglones que la de al lado. Con varias cajas
          se elige cuál —Florida tiene dos mostradores y cada una lleva su
          arqueo—; con una, no se pregunta. */}
      {cajas.length > 0 && (
        <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-[var(--pos-divider)]/60 pt-3">
          {[...cajas].sort((x, y) => x.caja_id.localeCompare(y.caja_id)).map((c) => {
            const esEsta = c.caja_id === cajaEquipo;
            return (
              <button
                key={c.caja_id}
                type="button"
                disabled={abriendo !== null}
                onClick={() => onAbrir(c)}
                className={`pos-btn h-10 min-w-0 flex-1 px-3 text-[13px] ${
                  esEsta ? "pos-btn-primario" : "pos-btn-sec"}`}
              >
                {abriendo === c.caja_id
                  ? "Abriendo…"
                  : cajas.length > 1 ? `Abrir ${c.caja_nombre}` : `Abrir ${t.nombre}`}
              </button>
            );
          })}
          {/* Dicho con letras y no en un `title`: en una tableta no hay
              cursor que pasar por encima. */}
          <p className="tabular w-full text-[12px] text-[var(--pos-600)]">
            {cajas.some((c) => c.caja_id === cajaEquipo)
              ? "Este equipo está trabajando en esta tienda."
              : "Abre Venta, Cambios, Stock, Cierre y Panel de esta tienda."}
          </p>
        </div>
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
  titulo, valor, pie, alerta, abierto, onAbrir,
}: {
  titulo: string; valor: string; pie: string; alerta?: boolean;
  /** Con `onAbrir` la tarjeta es un botón que despliega su detalle. */
  abierto?: boolean; onAbrir?: () => void;
}) {
  const cuerpo = (
    <>
      <span className="kicker text-[var(--pos-700)]">{titulo}</span>
      <span className={`titular text-[28px] font-bold leading-none ${
        alerta ? "text-[var(--pos-accent)]" : ""}`}>
        {valor}
      </span>
      <span className="tabular text-[12px] text-[var(--pos-600)]">{pie}</span>
      {onAbrir && (
        <span className="tabular mt-1 text-[12px] font-medium text-[var(--pos-800)] underline">
          {abierto ? "Ocultar detalle" : "Ver detalle"}
        </span>
      )}
    </>
  );
  if (!onAbrir) {
    return <Marco className="flex flex-col gap-1 p-6">{cuerpo}</Marco>;
  }
  return (
    <Marco className="flex overflow-hidden">
      <button type="button" onClick={onAbrir} aria-expanded={Boolean(abierto)}
              // `!`: el sistema centra todo `button` del POS (pos.css); esta
              // tarjeta se lee como las de al lado, alineada a la izquierda.
              className="!flex w-full flex-col !items-start !justify-start gap-1 p-6 text-left hover:bg-[var(--pos-100)]">
        {cuerpo}
      </button>
    </Marco>
  );
}

const MOTIVOS: Record<string, string> = {
  talla: "Talla", defecto: "Defecto", no_le_gusto: "No le gustó",
  cambio_modelo: "Cambio de modelo",
};
const REEMBOLSOS: Record<string, string> = {
  credito_tienda: "Cambio (crédito de tienda)",
  efectivo: "Devolución en efectivo",
  metodo_original: "Devolución al medio de pago",
};

/** Cuáles son: los cambios y devoluciones, y las ventas anuladas. */
function Detalle({ datos }: { datos: Tablero }) {
  const celda = "px-3 py-2";
  const cabeza = "kicker text-left text-[var(--pos-600)]";
  return (
    <Marco className="flex shrink-0 flex-col gap-5 p-6">
      <div className="flex flex-col gap-2">
        <h2 className="titular text-[17px] font-semibold">Cambios y devoluciones</h2>
        {datos.detalle_devoluciones.length === 0 ? (
          <p className="text-[13px] text-[var(--pos-600)]">Ninguno en este periodo.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-[13px]">
              <thead>
                <tr className={cabeza}>
                  <th className="py-2 pr-3 font-normal">Cuándo</th>
                  <th className={`${celda} font-normal`}>Tienda</th>
                  <th className={`${celda} font-normal`}>Factura</th>
                  <th className={`${celda} font-normal`}>Motivo</th>
                  <th className={`${celda} font-normal`}>Qué fue</th>
                  <th className={`${celda} text-right font-normal`}>Prendas</th>
                  <th className={`${celda} text-right font-normal`}>Valor</th>
                  <th className="py-2 pl-3 font-normal">Quién</th>
                </tr>
              </thead>
              <tbody>
                {datos.detalle_devoluciones.map((d, i) => (
                  <tr key={i} className="border-t border-[var(--pos-divider)]/60">
                    <td className="tabular py-2 pr-3">{horaDe(d.cuando, datos.hoy)}</td>
                    <td className={celda}>{d.tienda}</td>
                    <td className={`tabular ${celda}`}>{d.numero_venta}</td>
                    <td className={celda}>{MOTIVOS[d.motivo] ?? d.motivo}</td>
                    {/* Lo que SÍ sacó plata va en negrita: es lo que hay
                        que alcanzar a ver entre una lista de cambios. */}
                    <td className={`${celda} ${d.reembolso === "credito_tienda" ? "" : "font-semibold"}`}>
                      {REEMBOLSOS[d.reembolso] ?? d.reembolso}
                    </td>
                    <td className={`tabular ${celda} text-right`}>{d.unidades}</td>
                    <td className={`tabular ${celda} text-right`}>{formatear(d.total_centavos)}</td>
                    <td className="py-2 pl-3">{d.quien}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="tabular text-[12px] text-[var(--pos-600)]">
          En un cambio la clienta se lleva otra prenda: de la caja no sale plata.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="titular text-[17px] font-semibold">Ventas anuladas</h2>
        {datos.detalle_anuladas.length === 0 ? (
          <p className="text-[13px] text-[var(--pos-600)]">Ninguna en este periodo.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-[13px]">
              <thead>
                <tr className={cabeza}>
                  <th className="py-2 pr-3 font-normal">Cuándo</th>
                  <th className={`${celda} font-normal`}>Tienda</th>
                  <th className={`${celda} font-normal`}>Venta</th>
                  <th className={`${celda} font-normal`}>Motivo</th>
                  <th className={`${celda} text-right font-normal`}>Valor</th>
                  <th className="py-2 pl-3 font-normal">Quién anuló</th>
                </tr>
              </thead>
              <tbody>
                {datos.detalle_anuladas.map((a, i) => (
                  <tr key={i} className="border-t border-[var(--pos-divider)]/60">
                    <td className="tabular py-2 pr-3">{horaDe(a.cuando, datos.hoy)}</td>
                    <td className={celda}>{a.tienda}</td>
                    <td className={`tabular ${celda}`}>{a.numero}</td>
                    <td className={celda}>{a.motivo || "—"}</td>
                    <td className={`tabular ${celda} text-right`}>{formatear(a.total_centavos)}</td>
                    <td className="py-2 pl-3">{a.quien || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
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
