"use client";

/**
 * Pedidos con envío a domicilio — la pantalla de la oficina.
 *
 * Lo vende la caja (la Feria) y lo despacha Melonn. Cuando algo se tuerce —
 * Melonn no tenía la prenda, la dirección no sirvió, la clienta se arrepintió
 * al otro día— no lo resuelve la vendedora: lo resuelve la oficina, aquí
 * (Sebastián, 2026-11-17). Primero lo que necesita a alguien.
 *
 * Trae a quién y a dónde va cada pedido: hace falta para resolverlo. Por eso
 * es sólo para administradores, y lo decide el servidor.
 */
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Panel as Marco } from "@/components/pos/marco";
import { Rail } from "@/components/pos/rail";
import { formatear } from "@/lib/pos/dinero";
import {
  cancelarPedidoConEnvio,
  despachosDeLasTiendas,
  NOMBRE_DESPACHO,
  reintentarPedidoConEnvio,
  type Despacho,
} from "@/lib/pos/api";

/** Lo que todavía se puede cancelar: no ha salido de la bodega. */
const CANCELABLE = new Set(["pendiente", "en_melonn", "no_creado"]);

export default function PantallaDespachos() {
  const { user } = useAuth();
  const [abiertos, setAbiertos] = useState(true);
  const [lista, setLista] = useState<Despacho[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [cancelando, setCancelando] = useState<Despacho | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      setLista(await despachosDeLasTiendas(abiertos));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo traer la lista.");
    }
  }, [abiertos]);

  useEffect(() => {
    setLista(null);
    void cargar();
    // Cada minuto: el estado lo cambian Melonn y la cola, no esta pantalla.
    const t = setInterval(() => { void cargar(); }, 60_000);
    return () => clearInterval(t);
  }, [cargar]);

  async function reintentar(d: Despacho) {
    setOcupado(d.venta_id);
    setAviso(null);
    try {
      await reintentarPedidoConEnvio(d.venta_id);
      setAviso(`${d.numero}: se le vuelve a pedir a Melonn en un momento.`);
      await cargar();
    } catch (e) {
      setAviso(e instanceof Error ? e.message : "No se pudo reintentar.");
    } finally {
      setOcupado(null);
    }
  }

  const porResolver = (lista ?? []).filter((d) => d.requiere_atencion).length;

  return (
    <div className="pos-raiz flex h-screen overflow-hidden">
      <Rail cajera={user?.nombre || user?.email || ""} />

      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
        <header className="flex flex-wrap items-baseline gap-3">
          <h1 className="titular text-[22px] font-semibold tracking-tight">
            Pedidos con envío
          </h1>
          {lista && (
            <p className="tabular text-[12px] text-[var(--pos-600)]">
              {porResolver
                ? `${porResolver} por resolver · ${lista.length} en la lista`
                : `${lista.length} en la lista · nada por resolver`}
            </p>
          )}
          <div role="radiogroup" aria-label="Qué pedidos ver"
               className="ml-auto inline-flex gap-1.5">
            {[{ v: true, t: "En curso" }, { v: false, t: "Todos" }].map((o) => (
              <button key={o.t} role="radio" aria-checked={abiertos === o.v}
                      onClick={() => setAbiertos(o.v)}
                      className={`h-11 border px-4 text-[13px] ${
                        abiertos === o.v
                          ? "border-[var(--pos-accent)] bg-[var(--pos-accent)]/10 text-[var(--pos-text)]"
                          : "border-[var(--pos-divider)] bg-[var(--pos-surface)] text-[var(--pos-700)]"}`}>
                {o.t}
              </button>
            ))}
          </div>
        </header>

        {error && <Nota>{error}</Nota>}
        {aviso && <Nota suave>{aviso}</Nota>}
        {!lista && !error && (
          <p className="text-[13px] text-[var(--pos-600)]">Cargando…</p>
        )}
        {lista && !lista.length && (
          <p className="text-[13px] text-[var(--pos-600)]">
            {abiertos ? "No hay pedidos con envío en curso." : "Todavía no hay pedidos con envío."}
          </p>
        )}

        <div className="grid min-w-0 grid-cols-1 gap-3 xl:grid-cols-2">
          {(lista ?? []).map((d) => (
            <TarjetaDespacho
              key={d.venta_id} d={d} ocupado={ocupado === d.venta_id}
              onReintentar={() => { void reintentar(d); }}
              onCancelar={() => setCancelando(d)}
            />
          ))}
        </div>
      </main>

      {cancelando && (
        <DialogoCancelar
          d={cancelando}
          onCerrar={() => setCancelando(null)}
          onHecho={async (mensaje) => {
            setCancelando(null);
            setAviso(mensaje);
            await cargar();
          }}
        />
      )}
    </div>
  );
}

function TarjetaDespacho({ d, ocupado, onReintentar, onCancelar }: {
  d: Despacho; ocupado: boolean;
  onReintentar: () => void; onCancelar: () => void;
}) {
  const reintentable = d.estado === "no_creado"
    || (d.estado === "pendiente" && d.requiere_atencion);
  return (
    <Marco className="flex min-w-0 flex-col gap-2 p-5"
           style={d.requiere_atencion ? { boxShadow: "inset 3px 0 0 var(--pos-accent)" } : undefined}>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="tabular text-[15px] font-semibold">{d.numero}</span>
        <span className="tabular text-[12px] text-[var(--pos-600)]">
          {d.tienda_id} · {d.vendida_en} · {formatear(d.total_centavos)}
        </span>
        <span className={`ml-auto pos-tag whitespace-nowrap ${
          d.requiere_atencion ? "pos-tag-acento" : "pos-tag-neutro"}`}>
          {NOMBRE_DESPACHO[d.estado]}
        </span>
      </div>

      {d.ultimo_error && (
        <p className="rounded-[var(--pos-r-sm)] bg-[var(--pos-accent)]/10 px-3 py-2 text-[13px] leading-snug text-[var(--pos-900)]">
          {d.ultimo_error}
        </p>
      )}

      <dl className="grid grid-cols-[96px_1fr] gap-x-3 gap-y-1 text-[13px]">
        <dt className="text-[var(--pos-600)]">Recibe</dt>
        <dd>{d.destinatario} · <span className="tabular">{d.telefono}</span></dd>
        <dt className="text-[var(--pos-600)]">Dirección</dt>
        <dd>
          {d.direccion}{d.complemento ? ` · ${d.complemento}` : ""} — {d.ciudad}, {d.departamento}
        </dd>
        <dt className="text-[var(--pos-600)]">Prendas</dt>
        <dd className="tabular">{d.prendas.join(" · ")}</dd>
        <dt className="text-[var(--pos-600)]">Melonn</dt>
        <dd>
          {d.melonn_numero
            ? <>
                <span className="tabular">{d.melonn_numero}</span>
                {d.melonn_estado ? ` · ${d.melonn_estado}` : ""}
                {d.seguimiento_url && (
                  <a href={d.seguimiento_url} target="_blank" rel="noreferrer"
                     className="ml-2 underline">seguimiento</a>
                )}
              </>
            : <span className="text-[var(--pos-600)]">sin pedido todavía</span>}
        </dd>
        <dt className="text-[var(--pos-600)]">Factura</dt>
        <dd className="tabular">{d.factura ?? (d.estado_fiscal === "emitido" ? "emitida" : "en camino")}</dd>
        {d.resolucion && (
          <>
            <dt className="text-[var(--pos-600)]">Resolución</dt>
            <dd>{d.resolucion}</dd>
          </>
        )}
      </dl>

      {(reintentable || CANCELABLE.has(d.estado)) && (
        <div className="mt-1 flex flex-wrap gap-2">
          {reintentable && (
            <button onClick={onReintentar} disabled={ocupado}
                    className="pos-btn pos-btn-sec h-11 px-4 text-[14px] disabled:opacity-60">
              {ocupado ? "Pidiendo…" : "Volver a pedir a Melonn"}
            </button>
          )}
          {CANCELABLE.has(d.estado) && (
            <button onClick={onCancelar} disabled={ocupado}
                    className="pos-btn pos-btn-sec h-11 px-4 text-[14px] disabled:opacity-60">
              Cancelar pedido con envío
            </button>
          )}
        </div>
      )}
    </Marco>
  );
}

/**
 * Cancelar desde la oficina. Pide DOS cosas escritas: por qué, y cómo se le
 * devolvió la plata —eso pasa por fuera de la caja (transferencia, reverso en
 * Wompi) y sin esto no quedaría rastro de dónde salió—.
 */
function DialogoCancelar({ d, onCerrar, onHecho }: {
  d: Despacho; onCerrar: () => void; onHecho: (mensaje: string) => void;
}) {
  const [motivo, setMotivo] = useState("");
  const [resolucion, setResolucion] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listo = motivo.trim().length >= 5 && resolucion.trim().length >= 5;

  async function confirmar() {
    setEnviando(true);
    setError(null);
    try {
      const r = await cancelarPedidoConEnvio(d.venta_id, motivo.trim(), resolucion.trim());
      onHecho(`${r.numero} cancelado. Melonn no lo despacha`
        + (r.exige_nota_credito ? " y su factura recibe la nota crédito." : "."));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cancelar.");
      setEnviando(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
         role="dialog" aria-modal="true" aria-label={`Cancelar ${d.numero}`}>
      <Marco className="w-full max-w-[480px] p-6" style={{ background: "var(--pos-surface)" }}>
        <h2 className="titular text-[18px]">Cancelar {d.numero}</h2>
        <p className="mt-2 text-[13px] leading-relaxed text-[var(--pos-700)]">
          Se le pide a Melonn que no lo despache; si ya salió, no se cancela.
          La venta se anula, su factura recibe la nota crédito y la caja{" "}
          <b>no</b> se toca: la plata se le devuelve por fuera.
        </p>
        <label className="mt-4 block">
          <span className="kicker" style={{ color: "var(--pos-600)" }}>Por qué se cancela</span>
          <input value={motivo} onChange={(e) => setMotivo(e.target.value)}
                 placeholder="Melonn no tenía la talla" autoFocus
                 className="mt-1 h-11 w-full pos-input px-3 text-[14px]" />
        </label>
        <label className="mt-3 block">
          <span className="kicker" style={{ color: "var(--pos-600)" }}>Cómo se le devolvió la plata</span>
          <input value={resolucion} onChange={(e) => setResolucion(e.target.value)}
                 placeholder="Transferencia a Bancolombia el 19-nov"
                 className="mt-1 h-11 w-full pos-input px-3 text-[14px]" />
        </label>
        {error && <p className="mt-3 text-[13px] text-[var(--pos-accent)]">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCerrar} disabled={enviando}
                  className="pos-btn pos-btn-sec h-11 px-4 text-[14px]">Volver</button>
          <button onClick={() => { void confirmar(); }} disabled={!listo || enviando}
                  className="pos-btn pos-btn-primario h-11 px-4 text-[14px] disabled:cursor-not-allowed">
            {enviando ? "Cancelando…" : "Cancelar pedido"}
          </button>
        </div>
      </Marco>
    </div>
  );
}

function Nota({ children, suave = false }: { children: React.ReactNode; suave?: boolean }) {
  return (
    <p className={`max-w-[640px] rounded-[var(--pos-r-sm)] border-l-2 py-3 pl-4 text-[13px] text-[var(--pos-900)] ${
      suave ? "border-[var(--pos-600)] bg-[var(--pos-100)]"
            : "border-[var(--pos-800)] bg-[var(--pos-800)]/10"}`}>
      {children}
    </p>
  );
}
