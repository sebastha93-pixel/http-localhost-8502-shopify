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
 * SI LA TIENDA FACTURA, SE ESPERA LA FACTURA — unos segundos. La factura es
 * lo que hay que entregar, y la DIAN la valida en lo que la cajera empaca. Se
 * espera con tope: si Siigo o la DIAN tardan, sale el comprobante (que dice
 * que la factura está en trámite) y la venta sigue. La venta nunca depende de
 * que un tercero conteste (ADR-002); el papel sí puede esperarlo un momento.
 */

/** Cuánto se espera la factura antes de imprimir el comprobante. */
const ESPERA_FACTURA_MS = 20_000;
const CADA_MS = 1_500;
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
  const [esperandoFactura, setEsperandoFactura] = useState(false);
  const yaImprimio = useRef(false);
  const noEsperar = useRef(false);
  // Si la cajera pasa a la venta siguiente mientras se espera la factura,
  // este componente ya no está: imprimir entonces sacaría por el papel la
  // pantalla de venta en vez de la tirilla.
  const vivo = useRef(true);
  useEffect(() => {
    vivo.current = true;
    return () => { vivo.current = false; noEsperar.current = true; };
  }, []);

  const imprimir = useCallback(async (esperar = false) => {
    setImprimiendo(true);
    setErrorImpresion(null);
    try {
      let d = tirillaLocal ?? (await pedirTirilla(ticket.venta_id));
      setTirilla(d);
      if (esperar && !tirillaLocal) {
        // Con `Date.now()` y no contando vueltas: una petición lenta no puede
        // estirar la espera más allá del tope.
        const tope = Date.now() + ESPERA_FACTURA_MS;
        noEsperar.current = false;
        while (d.factura_en_camino && !d.es_documento_fiscal
               && Date.now() < tope && !noEsperar.current) {
          setEsperandoFactura(true);
          await new Promise((r) => setTimeout(r, CADA_MS));
          try {
            d = await pedirTirilla(ticket.venta_id);
            setTirilla(d);
          } catch {
            // Se cayó la red esperando: se imprime lo que ya se tenía.
            break;
          }
        }
        setEsperandoFactura(false);
      }
      if (!vivo.current) return;
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
      setEsperandoFactura(false);
      setImprimiendo(false);
    }
  }, [ticket.venta_id, tirillaLocal]);

  useEffect(() => {
    if (yaImprimio.current) return;
    yaImprimio.current = true;
    imprimir(true);
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
          {esperandoFactura
            ? "Esperando la factura"
            : imprimiendo ? "Saliendo por la impresora" : "Lo que salió por el papel"}
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
            <div className="kicker">
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
              esperandoFactura
                ? "Esperando la factura…"
                : imprimiendo
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
                : tirilla?.es_documento_fiscal
                  ? `Factura electrónica ${tirilla.documento_fiscal ?? ""}`
                  // «En trámite» sólo si de verdad viene. Decirlo cuando la
                  // tienda no emite deja a la cajera prometiéndole a la
                  // clienta una factura que no llega.
                  : tirilla?.factura_en_camino
                    ? esperandoFactura
                      ? "Factura electrónica: validando en la DIAN…"
                      : "Factura en trámite · salió el comprobante. Reimprime en un momento."
                    : "Comprobante interno · sin factura electrónica"
            }
            alerta={Boolean(ticket.pendiente_de_envio)
                    || Boolean(tirilla?.factura_en_camino && !esperandoFactura
                               && !imprimiendo)}
          />
          {ticket.duplicada && <Estado texto="Esta venta ya estaba registrada" />}
        </div>

        {errorImpresion && (
          <p className="mt-4 border border-[var(--pos-800)] rounded-[var(--pos-r-sm)] bg-[var(--pos-800)]/10 p-2.5 text-left text-[12px] leading-relaxed text-[var(--pos-900)]">
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
          {esperandoFactura ? (
            // La salida para cuando hay fila: no se obliga a nadie a esperar.
            <button
              onClick={() => { noEsperar.current = true; }}
              className="pos-btn pos-btn-sec px-6 py-3.5 text-[13.5px] transition-colors duration-[var(--pos-transicion)]"
            >
              IMPRIMIR YA
            </button>
          ) : (
            <button
              onClick={() => imprimir(false)}
              disabled={imprimiendo}
              className="pos-btn pos-btn-sec px-6 py-3.5 text-[13.5px] transition-colors duration-[var(--pos-transicion)] disabled:opacity-50"
            >
              {errorImpresion ? "REINTENTAR" : "REIMPRIMIR"}
            </button>
          )}
          <button
            onClick={onNueva}
            className="pos-btn pos-btn-primario px-10 py-3.5 text-[13.5px]"
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
