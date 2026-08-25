"use client";

import { useState } from "react";
import { Panel } from "@/components/pos/marco";
import {
  ContadorDenominaciones,
  totalDe,
} from "@/components/pos/contador-denominaciones";
import { formatear } from "@/lib/pos/dinero";
import type { Denominacion } from "@/lib/pos/api";

/**
 * Apertura de turno.
 *
 * NO pide credenciales: quien está aquí ya entró con su correo y contraseña
 * por el login del ERP. Volver a pedirle algo para abrir su propio turno es un
 * paso que no protege nada.
 *
 * SÍ PIDE CONTAR EL CAJÓN, y antes no. La base salía de la configuración de la
 * tienda y nadie miraba: un cajón que amaneció con $180.000 en vez de
 * $200.000 no desaparecía, reaparecía ocho horas después como faltante de
 * quien cerró. La persona equivocada, el momento equivocado, y ya sin forma de
 * saber dónde pasó.
 *
 * NO ES CIEGO, y no debería fingirlo. En el cierre lo esperado se esconde
 * porque depende del día; la base es la misma cifra cada mañana y la cajera se
 * la sabe. Lo que cambia no es que el número esté oculto: es que para
 * responder hay que tocar la plata.
 */
export function AbrirTurno({
  tienda,
  caja,
  cajera,
  base,
  denominaciones,
  ocupadoPor,
  abriendo,
  error,
  onAbrir,
}: {
  tienda: string;
  caja: string;
  cajera: string;
  base: number | null;
  denominaciones: Denominacion[];
  ocupadoPor: string | null;
  abriendo: boolean;
  error: string | null;
  onAbrir: (conteo: Record<number, number>, justificacion: string) => void;
}) {
  const [piezas, setPiezas] = useState<Record<number, number>>({});
  const [justificacion, setJustificacion] = useState("");

  const contado = totalDe(piezas);
  const conto = Object.keys(piezas).length > 0;
  const diferencia = base === null ? 0 : contado - base;
  // El umbral real lo pone el servidor con la configuración de la tienda; aquí
  // sólo se decide CUÁNDO mostrar el campo de explicación. Que el servidor la
  // exija y la pantalla no la haya pedido es un error que la cajera no puede
  // arreglar, así que se pide desde el primer peso de diferencia.
  const debeExplicar = conto && diferencia !== 0;
  const listo = conto && (!debeExplicar || justificacion.trim().length >= 5);

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <Panel
        className="w-full max-w-[560px] p-6"
        style={{ background: "var(--pos-surface)" }}
      >
        <p className="titular text-[30px]" style={{ fontWeight: 700 }}>
          MALE&apos;DENIM
        </p>
        <p className="kicker mt-1" style={{ color: "var(--pos-600)" }}>
          Punto de venta · {tienda} · {caja}
        </p>

        <div className="my-5" style={{ borderTop: "1px solid var(--pos-divider)" }} />

        {ocupadoPor ? (
          <>
            <p className="text-[14px] leading-relaxed" style={{ color: "var(--pos-800)" }}>
              Esta caja tiene un turno abierto a nombre de <b>{ocupadoPor}</b>.
            </p>
            <p className="mt-3 text-[13px] leading-relaxed" style={{ color: "var(--pos-600)" }}>
              El arqueo de ese turno es suyo. Ciérralo desde <b>Cierre</b> antes de
              abrir uno nuevo, o pide a un supervisor que lo haga.
            </p>
          </>
        ) : (
          <>
            <p className="text-[14px]" style={{ color: "var(--pos-800)" }}>
              Vas a abrir turno como <b>{cajera}</b>. Cuenta el cajón.
            </p>
            {base !== null && (
              <p className="mt-1 text-[13px]" style={{ color: "var(--pos-600)" }}>
                La base de esta tienda es{" "}
                <b className="tabular">{formatear(base)}</b>.
              </p>
            )}

            <div className="mt-4">
              <ContadorDenominaciones
                denominaciones={denominaciones}
                piezas={piezas}
                onCambio={setPiezas}
                deshabilitado={abriendo}
              />
            </div>

            {/* LA DIFERENCIA, en el momento en que todavía se puede averiguar
                qué pasó. Ocho horas después ya nadie se acuerda. */}
            {conto && base !== null && (
              <p
                className="mt-3 border-l-2 py-2 pl-3 text-[13px] leading-relaxed"
                style={
                  diferencia === 0
                    ? { borderColor: "var(--pos-divider)",
                        background: "var(--pos-100)", color: "var(--pos-700)" }
                    : { borderColor: "var(--pos-accent)",
                        background: "color-mix(in srgb, var(--pos-accent) 10%, transparent)",
                        color: "var(--pos-900)" }
                }
              >
                {diferencia === 0 ? (
                  <>Cuadra con la base de la tienda.</>
                ) : (
                  <>
                    <b>
                      {diferencia < 0 ? "Faltan" : "Sobran"}{" "}
                      {formatear(Math.abs(diferencia))}
                    </b>{" "}
                    frente a la base. El turno abre igual y con lo que contaste
                    — así este faltante no reaparece esta noche como tuyo.
                  </>
                )}
              </p>
            )}

            {debeExplicar && (
              <label className="mt-3 block">
                <span className="kicker" style={{ color: "var(--pos-600)" }}>
                  Qué pasó (queda en la auditoría)
                </span>
                <input
                  autoFocus
                  value={justificacion}
                  onChange={(e) => setJustificacion(e.target.value)}
                  placeholder="el sobre de la caja fuerte venía corto"
                  className="mt-1.5 h-11 w-full border px-3 text-[13px] outline-none"
                  style={{ borderColor: "var(--pos-divider)", background: "#fff",
                           color: "var(--pos-text)" }}
                />
              </label>
            )}
          </>
        )}

        {error && (
          <p
            className="mt-4 rounded-[var(--pos-r-sm)] border p-2.5 text-[13px] leading-relaxed"
            style={{ borderColor: "var(--pos-700)", background: "var(--pos-100)",
                     color: "var(--pos-900)" }}
          >
            {error}
          </p>
        )}

        <button
          onClick={() => onAbrir(piezas, justificacion.trim())}
          disabled={abriendo || Boolean(ocupadoPor) || !listo}
          className="mt-5 h-12 w-full text-[14px] font-semibold tracking-[0.1em] disabled:opacity-60"
          style={{
            background: ocupadoPor ? "var(--pos-300)" : "var(--pos-accent)",
            color: ocupadoPor ? "var(--pos-600)" : "#fff",
            borderRadius: "var(--pos-r-md)",
          }}
        >
          {abriendo
            ? "ABRIENDO…"
            : ocupadoPor
              ? "CAJA OCUPADA"
              : !conto
                ? "CUENTA EL CAJÓN"
                : "ABRIR TURNO"}
        </button>
      </Panel>
    </div>
  );
}
