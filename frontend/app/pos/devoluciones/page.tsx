"use client";

/**
 * Devoluciones y cambios — vista 5 del handoff.
 *
 * EL FLUJO ES EL DEL PROTOTIPO: buscar el ticket, marcar qué vuelve, decir por
 * qué y cómo se reembolsa. Con dos diferencias que el prototipo no podía
 * conocer, y que no son de estilo:
 *
 * **Se devuelven CANTIDADES, no artículos.** El prototipo pone una casilla por
 * línea, o sea todo o nada. Pero una venta puede llevar dos jeans iguales y la
 * clienta devolver uno; con casilla, la cajera tendría que devolver los dos y
 * volver a vender uno — y eso son dos documentos fiscales donde debía haber
 * ninguno. Cuando la línea tiene una sola unidad se comporta exactamente como
 * la casilla del prototipo.
 *
 * **El efectivo se apaga si no hay turno abierto.** La regla vive en el
 * agregado (INV-D4) y aquí sólo se refleja, porque una regla que sólo se ve al
 * final es una regla que se descubre con la clienta delante.
 *
 * La NOTA CRÉDITO no sale de esta pantalla ni de este módulo: la emite
 * Postventa. Aquí se registra la devolución y se encola el caso.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Rail } from "@/components/pos/rail";
import { ElegirCaja } from "@/components/pos/elegir-caja";
import { useCajaDelEquipo } from "@/lib/pos/caja-del-equipo";
import { formatear } from "@/lib/pos/dinero";
import { nuevoUlid } from "@/lib/pos/ulid";
import {
  buscarTicket,
  registrarDevolucion,
  type Devolucion,
  type MotivoDevolucion,
  type Reembolso,
  type TicketDevolucion,
} from "@/lib/pos/api";

const MOTIVOS: { valor: MotivoDevolucion; etiqueta: string }[] = [
  { valor: "talla", etiqueta: "Talla" },
  { valor: "defecto", etiqueta: "Defecto" },
  { valor: "no_le_gusto", etiqueta: "No le gustó" },
  { valor: "cambio_modelo", etiqueta: "Cambio de modelo" },
];

const REEMBOLSOS: { valor: Reembolso; etiqueta: string }[] = [
  { valor: "efectivo", etiqueta: "Efectivo" },
  { valor: "metodo_original", etiqueta: "Método original" },
  { valor: "credito_tienda", etiqueta: "Crédito tienda" },
];

// Se devuelve en la caja de ESTE equipo, que puede no ser la que vendió:
// de su cajón sale la plata y a su tienda entra la prenda.
export default function PaginaDevoluciones() {
  const caja = useCajaDelEquipo();
  if (caja.estado.fase !== "lista") return <ElegirCaja caja={caja} />;
  return <PantallaDevoluciones key={caja.estado.caja} CAJA={caja.estado.caja} />;
}

function PantallaDevoluciones({ CAJA }: { CAJA: string }) {
  const { user } = useAuth();
  const [consulta, setConsulta] = useState("");
  const [ticket, setTicket] = useState<TicketDevolucion | null>(null);
  const [seleccion, setSeleccion] = useState<Record<string, number>>({});
  const [motivo, setMotivo] = useState<MotivoDevolucion | null>(null);
  const [reembolso, setReembolso] = useState<Reembolso | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hecha, setHecha] = useState<Devolucion | null>(null);
  const buscador = useRef<HTMLInputElement>(null);

  useEffect(() => { buscador.current?.focus(); }, []);

  const buscar = useCallback(async () => {
    const n = consulta.trim();
    if (!n) return;
    setBuscando(true);
    setError(null);
    setTicket(null);
    setSeleccion({});
    setMotivo(null);
    setReembolso(null);
    try {
      const t = await buscarTicket(n, CAJA);
      setTicket(t);
      if (t.anulada) {
        setError(
          `El ticket ${t.numero} está anulado: su plata ya volvió por el ` +
          `arqueo. No se puede devolver otra vez.`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos buscar ese ticket.");
    } finally {
      setBuscando(false);
    }
  }, [consulta]);

  const cambiar = (sku: string, cantidad: number, tope: number) => {
    const n = Math.max(0, Math.min(tope, cantidad));
    setSeleccion((s) => {
      const copia = { ...s };
      if (n === 0) delete copia[sku];
      else copia[sku] = n;
      return copia;
    });
  };

  const lineas = ticket?.lineas ?? [];
  const total = lineas.reduce(
    (suma, l) => suma + (seleccion[l.sku] ?? 0) * l.precio_unitario_con_iva_centavos,
    0);
  const unidades = Object.values(seleccion).reduce((a, b) => a + b, 0);
  // Los tres a la vez, como pide el handoff. Se calcula aquí y no en el
  // `disabled` del botón para poder DECIR qué falta, que es lo que evita el
  // clic a ciegas contra un botón apagado.
  const falta = !unidades
    ? "Marca al menos un artículo."
    : !motivo
      ? "Elige el motivo."
      : !reembolso
        ? "Elige cómo se le devuelve la plata."
        : null;

  const procesar = async () => {
    if (!ticket || !motivo || !reembolso || falta) return;
    setEnviando(true);
    setError(null);
    try {
      const r = await registrarDevolucion({
        // El id lo genera el DISPOSITIVO: hace la petición idempotente, así
        // que un reintento en un mostrador con mala señal produce UNA
        // devolución, no tres.
        devolucion_id: nuevoUlid(),
        venta_id: ticket.venta_id,
        seleccion,
        motivo,
        reembolso,
        caja_id: CAJA,
      });
      setHecha(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo registrar la devolución.");
    } finally {
      setEnviando(false);
    }
  };

  const empezarDeNuevo = () => {
    setHecha(null);
    setTicket(null);
    setConsulta("");
    setSeleccion({});
    setMotivo(null);
    setReembolso(null);
    setError(null);
    buscador.current?.focus();
  };

  return (
    <div className="pos-raiz flex h-screen overflow-hidden">
      <Rail cajera={user?.nombre || user?.email || ""} />

      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto p-6">
        <h1 className="titular mb-5 text-[20px]">Devoluciones y cambios</h1>

        {hecha ? (
          <Exito devolucion={hecha} onNueva={empezarDeNuevo} />
        ) : (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <input
                ref={buscador}
                value={consulta}
                onChange={(e) => setConsulta(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void buscar(); }}
                placeholder="Número de ticket, ej. FL-1537"
                aria-label="Número de ticket"
                autoComplete="off"
                spellCheck={false}
                className="pos-input h-11 w-[320px] px-3 text-[14px]"
              />
              <button
                onClick={() => void buscar()}
                disabled={!consulta.trim() || buscando}
                className="pos-btn pos-btn-primario px-6 text-[14px]"
              >
                {buscando ? "Buscando…" : "Buscar ticket"}
              </button>
            </div>

            {error && (
              <p className="mb-4 rounded-[var(--pos-r-sm)] bg-[var(--pos-800)]/10 px-4 py-3 text-[13px] leading-relaxed text-[var(--pos-900)]">
                {error}
              </p>
            )}

            {!ticket && !error && (
              <div className="blueprint px-6 py-12 text-center">
                <p className="text-[15px] font-semibold">
                  Busca el ticket de la compra
                </p>
                <p className="mx-auto mt-1.5 max-w-[46ch] text-[13px] leading-relaxed text-[var(--pos-muted)]">
                  Está impreso arriba en la tirilla. Con él aparecen los
                  artículos y podrás marcar cuáles vuelven.
                </p>
              </div>
            )}

            {ticket && !ticket.anulada && (
              <>
                <div className="blueprint mb-4 p-5">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="titular text-[17px]">{ticket.numero}</span>
                    <span className="text-[13px] text-[var(--pos-muted)]">
                      {fechaLegible(ticket.fecha)}
                      {ticket.cajera ? ` · ${ticket.cajera}` : ""}
                    </span>
                  </div>

                  <ul className="mt-4 flex flex-col gap-2">
                    {lineas.map((l) => (
                      <ArticuloDevolvible
                        key={l.sku}
                        linea={l}
                        cantidad={seleccion[l.sku] ?? 0}
                        onCambiar={(n) => cambiar(l.sku, n, l.cantidad_devolvible)}
                      />
                    ))}
                  </ul>
                </div>

                <Grupo titulo="Motivo">
                  {MOTIVOS.map((m) => (
                    <Chip
                      key={m.valor}
                      activo={motivo === m.valor}
                      onClick={() => setMotivo(m.valor)}
                    >
                      {m.etiqueta}
                    </Chip>
                  ))}
                </Grupo>

                <Grupo titulo="Reembolso">
                  {REEMBOLSOS.map((r) => {
                    // El efectivo necesita un cajón abierto (INV-D4). Se apaga
                    // aquí, no al confirmar: descubrirlo al final es descubrirlo
                    // con la clienta delante.
                    const apagado = r.valor === "efectivo" && !ticket.puede_efectivo;
                    return (
                      <Chip
                        key={r.valor}
                        activo={reembolso === r.valor}
                        deshabilitado={apagado}
                        titulo={apagado
                          ? "Necesita un turno abierto en esta caja"
                          : undefined}
                        onClick={() => setReembolso(r.valor)}
                      >
                        {r.etiqueta}
                      </Chip>
                    );
                  })}
                </Grupo>

                <div className="blueprint mt-5 flex flex-wrap items-center justify-between gap-4 p-5">
                  <div>
                    <div className="kicker">Total a devolver</div>
                    <div className="tabular mt-1 text-[26px] font-bold tracking-[-0.02em]">
                      {formatear(total)}
                    </div>
                    <div className="mt-0.5 text-[12px] text-[var(--pos-muted)]">
                      {unidades === 1 ? "1 unidad" : `${unidades} unidades`}
                      {falta ? ` · ${falta}` : ""}
                    </div>
                  </div>
                  <button
                    onClick={() => void procesar()}
                    disabled={!!falta || enviando}
                    className="pos-btn pos-btn-primario h-14 px-8 text-[15px]"
                  >
                    {enviando ? "Registrando…" : "Procesar devolución"}
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}

/**
 * Una línea que puede volver.
 *
 * Con una sola unidad disponible se comporta como la casilla del prototipo;
 * con más, aparece el contador. No son dos controles distintos por capricho:
 * una casilla que representa «2 de 3» no existe, y un contador para una sola
 * unidad son dos toques donde bastaba uno.
 */
function ArticuloDevolvible({
  linea,
  cantidad,
  onCambiar,
}: {
  linea: import("@/lib/pos/api").LineaDevolvible;
  cantidad: number;
  onCambiar: (n: number) => void;
}) {
  const agotada = linea.cantidad_devolvible === 0;
  const marcada = cantidad > 0;

  return (
    <li
      className="flex items-center gap-3 rounded-[var(--pos-r-md)] border px-3 py-2.5 transition-colors"
      style={{
        borderColor: marcada ? "var(--pos-accent)" : "var(--pos-divider)",
        background: marcada ? "var(--pos-100)" : "var(--pos-surface)",
        opacity: agotada ? 0.4 : 1,
      }}
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] font-medium">{linea.nombre}</div>
        <div className="text-[12px] text-[var(--pos-muted)]">
          {linea.talla ? `Talla ${linea.talla} · ` : ""}
          {formatear(linea.precio_unitario_con_iva_centavos)}
          {/* Lo ya devuelto se DICE, no se esconde: es la explicación de por
              qué el tope de esta línea no es lo que dice la tirilla. */}
          {linea.cantidad_devuelta > 0 && (
            <span> · ya devueltas {linea.cantidad_devuelta} de {linea.cantidad_vendida}</span>
          )}
        </div>
      </div>

      {agotada ? (
        <span className="pos-tag pos-tag-neutro">Ya devuelta</span>
      ) : linea.cantidad_devolvible === 1 ? (
        <button
          role="checkbox"
          aria-checked={marcada}
          aria-label={`Devolver ${linea.nombre}`}
          onClick={() => onCambiar(marcada ? 0 : 1)}
          className="compacto grid h-[26px] w-[26px] shrink-0 place-items-center rounded-[6px] border text-[14px] toque-44"
          style={{
            borderColor: marcada ? "var(--pos-accent)" : "var(--pos-300)",
            background: marcada ? "var(--pos-accent)" : "var(--pos-surface)",
            color: "#fff",
          }}
        >
          {marcada ? "✓" : ""}
        </button>
      ) : (
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            onClick={() => onCambiar(cantidad - 1)}
            disabled={cantidad === 0}
            aria-label="Una menos"
            className="compacto h-8 w-8 rounded-full border border-[var(--pos-divider)] text-[15px] toque-44"
          >
            −
          </button>
          <span className="tabular w-8 text-center text-[14px]">
            {cantidad}
            <span className="text-[var(--pos-muted)]">/{linea.cantidad_devolvible}</span>
          </span>
          <button
            onClick={() => onCambiar(cantidad + 1)}
            disabled={cantidad >= linea.cantidad_devolvible}
            aria-label="Una más"
            className="compacto h-8 w-8 rounded-full border border-[var(--pos-divider)] text-[15px] toque-44"
          >
            +
          </button>
        </div>
      )}
    </li>
  );
}

function Grupo({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div className="mt-4">
      <div className="kicker mb-2">{titulo}</div>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}

function Chip({
  activo,
  deshabilitado,
  titulo,
  onClick,
  children,
}: {
  activo: boolean;
  deshabilitado?: boolean;
  titulo?: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={deshabilitado}
      title={titulo}
      aria-pressed={activo}
      className="h-11 rounded-[var(--pos-r-pill)] border px-4 text-[14px] font-medium transition-colors"
      style={{
        borderColor: activo ? "var(--pos-accent)" : "var(--pos-divider)",
        background: activo ? "var(--pos-100)" : "var(--pos-surface)",
        color: activo ? "var(--pos-800)" : "var(--pos-700)",
      }}
    >
      {children}
    </button>
  );
}

function Exito({
  devolucion,
  onNueva,
}: {
  devolucion: Devolucion;
  onNueva: () => void;
}) {
  return (
    <div className="blueprint mx-auto w-full max-w-[520px] p-8 text-center">
      <div
        className="mx-auto grid h-14 w-14 place-items-center rounded-[var(--pos-r-md)] text-[26px] text-white"
        style={{ background: "var(--pos-accent)" }}
        aria-hidden
      >
        ✓
      </div>
      <p className="titular mt-4 text-[20px]">Devolución registrada</p>
      <p className="mt-1 text-[13px] text-[var(--pos-muted)]">
        Ticket {devolucion.numero_venta} ·{" "}
        {devolucion.unidades === 1 ? "1 unidad" : `${devolucion.unidades} unidades`}
      </p>
      <p className="tabular mt-4 text-[30px] font-bold tracking-[-0.02em]">
        {formatear(devolucion.total_centavos)}
      </p>

      {/* LO QUE LA CAJERA TIENE QUE HACER AHORA, escrito distinto según el
          método. «Devolución registrada» a secas deja sin decir lo único
          accionable: si abre el cajón o no. */}
      <p className="mx-auto mt-3 max-w-[42ch] text-[13px] leading-relaxed text-[var(--pos-muted)]">
        {devolucion.salio_del_cajon
          ? `Entrégale ${formatear(devolucion.total_centavos)} en efectivo. Ya salió del arqueo de este turno.`
          : devolucion.reembolso === "credito_tienda"
            ? "Queda como crédito a favor de la clienta. No sale plata del cajón."
            : "Se reversa por el mismo medio con el que pagó. No sale plata del cajón."}
      </p>
      <p className="mx-auto mt-2 max-w-[42ch] text-[12px] leading-relaxed text-[var(--pos-muted)]">
        La nota crédito la emite Postventa; el caso ya quedó en cola.
      </p>

      <button onClick={onNueva} className="pos-btn pos-btn-primario mt-6 h-12 w-full text-[14px]">
        Nueva devolución
      </button>
    </div>
  );
}

/** «11 ago 2026, 2:00 p. m.» — el formato que ya usa el resto del POS. */
function fechaLegible(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("es-CO", {
    day: "numeric", month: "short", year: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}
