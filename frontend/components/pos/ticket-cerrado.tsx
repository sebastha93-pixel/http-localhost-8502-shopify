"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { formatear } from "@/lib/pos/dinero";
import { pedirTirilla, type Ticket, type Tirilla as DatosTirilla } from "@/lib/pos/api";
import { Tirilla } from "@/components/pos/tirilla";

/**
 * Venta cerrada — con la tirilla A LA VISTA.
 *
 * ANTES SE IMPRIMÍA A CIEGAS. La tirilla se pintaba fuera de pantalla, en
 * `left: -9999px`, y se mandaba a imprimir. La cajera no veía nunca lo que
 * salía por el papel: si la impresora se quedaba sin rollo, si el nombre de la
 * clienta estaba mal, si el total no era el que acababa de cobrar, se enteraba
 * cuando la clienta ya se había ido — o no se enteraba.
 *
 * Ahora la tirilla se ve al tamaño real del papel (80 mm) mientras se imprime.
 * No hace falta leerla: basta con que esté ahí para reconocer de un vistazo
 * que salió lo correcto.
 *
 * SIGUE IMPRIMIENDO SOLA Y SIGUE AVANZANDO SOLA. La vista previa no añade un
 * paso: es lo que se mira mientras la impresora trabaja. Obligar a pulsar
 * «imprimir» delante de cada clienta serían dos segundos de los treinta, cien
 * veces al día.
 *
 * El estado fiscal se muestra como lo que es —«emitiendo»— y no se espera. La
 * clienta ya se fue con su prenda y su papel (ADR-002).
 */
export function TicketCerrado({
  ticket,
  onNueva,
  tirillaLocal,
}: {
  ticket: Ticket;
  onNueva: () => void;
  /** Armada en el dispositivo cuando no hubo red. Si viene, NO se le pregunta
   *  al servidor: preguntar sin conexión sólo gasta el tiempo del timeout y
   *  acaba en el mismo sitio, con la clienta esperando el papel. */
  tirillaLocal?: DatosTirilla | null;
}) {
  const [restan, setRestan] = useState(8);
  const [tirilla, setTirilla] = useState<DatosTirilla | null>(null);
  const [errorImpresion, setErrorImpresion] = useState<string | null>(null);
  const [imprimiendo, setImprimiendo] = useState(true);
  const yaImprimio = useRef(false);

  const imprimir = useCallback(async () => {
    setImprimiendo(true);
    setErrorImpresion(null);
    try {
      const d = tirillaLocal ?? (await pedirTirilla(ticket.venta_id));
      setTirilla(d);
      // Una pausa para que React pinte la tirilla antes de abrir el diálogo:
      // sin ella el navegador manda una hoja en blanco.
      //
      // CON `setTimeout`, NO CON `requestAnimationFrame`. Lo tuve con rAF y
      // no dispara en una pestaña oculta: si la cajera cambiaba de app justo
      // al cerrar la venta, la tirilla no salía Y la pantalla se quedaba en
      // «Imprimiendo…» para siempre, bloqueando el paso a la venta siguiente.
      // Un `setTimeout` corre igual en segundo plano.
      await new Promise((r) => setTimeout(r, 60));
      window.print();
    } catch (e) {
      setErrorImpresion(
        e instanceof Error ? e.message : "No se pudo preparar la tirilla.",
      );
    } finally {
      setImprimiendo(false);
    }
  }, [ticket.venta_id, tirillaLocal]);

  useEffect(() => {
    if (yaImprimio.current) return;
    yaImprimio.current = true;
    imprimir();
  }, [imprimir]);

  useEffect(() => {
    // El reloj arranca cuando la impresión terminó. Si se pasa a la venta
    // siguiente mientras el diálogo está abierto, se imprime a medias o nada.
    if (imprimiendo) return;
    if (restan <= 0) {
      onNueva();
      return;
    }
    const t = setTimeout(() => setRestan((r) => r - 1), 1000);
    return () => clearTimeout(t);
  }, [restan, onNueva, imprimiendo]);

  return (
    <div className="flex min-h-screen items-start justify-center gap-10 overflow-y-auto p-8">
      {/* EL PAPEL, al ancho real de 80 mm. Se ve, no se adivina. */}
      <div className="hidden shrink-0 pt-2 md:block">
        <p className="kicker mb-2 text-center text-[var(--pos-600)]">
          {imprimiendo ? "Saliendo por la impresora" : "Lo que salió por el papel"}
        </p>
        <div
          className="w-[302px] border bg-white p-1"
          style={{ borderColor: "var(--pos-divider)",
                   boxShadow: "0 1px 3px rgba(0,0,0,.08)" }}
        >
          {tirilla ? (
            <Tirilla datos={tirilla} />
          ) : (
            <div className="flex h-[420px] items-center justify-center px-6 text-center text-[12px] leading-relaxed"
                 style={{ color: "var(--pos-600)" }}>
              {errorImpresion ? "No se pudo preparar la tirilla." : "Preparando…"}
            </div>
          )}
        </div>
      </div>

      <div className="max-w-[420px] pt-2 text-center md:pt-16">
        <h1 className="titular text-[26px] tracking-wide">VENTA CERRADA</h1>
        <p className="mt-1 tabular text-[13px] text-[var(--pos-700)]">{ticket.numero}</p>

        <div className="mt-6 tabular text-[40px] font-semibold tabular-nums">
          {formatear(ticket.total_centavos)}
        </div>

        {ticket.vuelto_centavos > 0 && (
          <div className="mt-4">
            <div className="titular text-[12px] tracking-[0.14em] text-[var(--pos-600)]">
              VUELTO
            </div>
            <div className="tabular text-[34px] font-semibold tabular-nums text-[var(--pos-800)]">
              {formatear(ticket.vuelto_centavos)}
            </div>
          </div>
        )}

        <div className="mt-6 space-y-1.5 text-[12px] text-[var(--pos-600)]">
          <Estado
            texto={
              imprimiendo
                ? "Imprimiendo tirilla…"
                : errorImpresion
                  ? "La tirilla no salió"
                  : "Tirilla impresa"
            }
            alerta={Boolean(errorImpresion)}
          />
          <Estado
            texto={
              ticket.pendiente_de_envio
                ? "Guardada sin conexión · se envía sola"
                : ticket.estado_fiscal === "emitido"
                  ? "Factura electrónica emitida"
                  : "Factura electrónica: emitiendo…"
            }
            alerta={Boolean(ticket.pendiente_de_envio)}
          />
          {ticket.duplicada && <Estado texto="Esta venta ya estaba registrada" />}
        </div>

        {errorImpresion && (
          <p className="mt-4 border border-[var(--pos-800)] bg-[var(--pos-800)]/10 p-2.5 text-left text-[12px] leading-relaxed text-[var(--pos-900)]">
            {/* Decir «la venta SÍ quedó registrada» cuando está en la cola local
                es mentir en el peor momento: la cajera lo lee, se queda
                tranquila, y no sabe que hay algo que vigilar. Sin red la venta
                está GUARDADA, que no es lo mismo que registrada. */}
            {ticket.pendiente_de_envio
              ? "Sin conexión no se pudo imprimir. La venta está guardada en este "
                + "equipo y se envía sola al volver la red — no hay que repetirla."
              : `${errorImpresion} La venta SÍ quedó registrada — esto es sólo el papel.`}
          </p>
        )}

        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <button
            onClick={imprimir}
            disabled={imprimiendo}
            className="border border-[var(--pos-divider)] px-6 py-3.5 titular text-[13.5px] tracking-[0.12em] text-[var(--pos-700)] transition-colors duration-[var(--pos-transicion)] disabled:opacity-50"
          >
            {errorImpresion ? "REINTENTAR" : "REIMPRIMIR"}
          </button>
          <button
            onClick={onNueva}
            className="bg-[var(--pos-accent)] px-10 py-3.5 titular text-[13.5px] font-semibold tracking-[0.12em] text-white"
          >
            NUEVA VENTA · Enter
          </button>
        </div>
        {!imprimiendo && (
          <p className="mt-3 tabular text-[12px] text-[var(--pos-muted)]">
            Vuelve solo en {restan} s
          </p>
        )}
      </div>
    </div>
  );
}

/** Un punto y una frase. Antes eran emoji (🧾 ⏳ ⚠️): se ven distintos en cada
 *  sistema, no se pueden colorear con los tokens, y un lector de pantalla los
 *  lee en voz alta como «etiqueta» o «reloj de arena». */
function Estado({ texto, alerta }: { texto: string; alerta?: boolean }) {
  return (
    <div className="flex items-center justify-center gap-2">
      <span
        aria-hidden
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: alerta ? "var(--pos-accent)" : "var(--pos-400)" }}
      />
      <span>{texto}</span>
    </div>
  );
}
