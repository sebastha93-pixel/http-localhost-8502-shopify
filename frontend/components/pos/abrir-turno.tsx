"use client";

import { Panel } from "@/components/pos/marco";
import { formatear } from "@/lib/pos/dinero";

/**
 * Apertura de turno.
 *
 * NO pide credenciales: quien está aquí ya entró con su correo y contraseña
 * por el login del ERP. Volver a pedirle algo para abrir su propio turno es un
 * paso que no protege nada.
 *
 * Tampoco pide la base de caja: sale de la configuración de la tienda, como
 * decidió el diseño. Pedirla cada mañana es un dato que se responde en
 * automático hasta que un día se responde mal.
 */
export function AbrirTurno({
  tienda,
  caja,
  cajera,
  base,
  ocupadoPor,
  abriendo,
  error,
  onAbrir,
}: {
  tienda: string;
  caja: string;
  cajera: string;
  base: number | null;
  ocupadoPor: string | null;
  abriendo: boolean;
  error: string | null;
  onAbrir: () => void;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <Panel className="w-full max-w-[420px] p-6" style={{ background: "var(--pos-surface)" }}>
        <p className="titular text-[30px]" style={{ fontWeight: 700 }}>
          MALE&apos;DENIM
        </p>
        <p className="kicker mt-1" style={{ color: "var(--pos-600)" }}>
          Punto de venta · {tienda} · {caja}
        </p>

        <div className="my-6" style={{ borderTop: "1px solid var(--pos-divider)" }} />

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
              Vas a abrir turno como <b>{cajera}</b>.
            </p>
            {base !== null && (
              <p className="mt-2 text-[13px]" style={{ color: "var(--pos-600)" }}>
                Base de caja: <b className="tabular">{formatear(base)}</b> — la
                configurada para esta tienda.
              </p>
            )}
          </>
        )}

        {error && (
          <p
            className="mt-4 rounded-[var(--pos-r-sm)] border p-2.5 text-[13px]"
            style={{ borderColor: "var(--pos-700)", background: "var(--pos-100)", color: "var(--pos-900)" }}
          >
            {error}
          </p>
        )}

        <button
          onClick={onAbrir}
          disabled={abriendo || Boolean(ocupadoPor)}
          className="mt-6 h-12 w-full text-[14px] font-semibold tracking-[0.1em]"
          style={{
            background: ocupadoPor ? "var(--pos-300)" : "var(--pos-accent)",
            color: ocupadoPor ? "var(--pos-600)" : "#fff",
            borderRadius: "var(--pos-r-md)",
          }}
        >
          {abriendo ? "ABRIENDO…" : ocupadoPor ? "CAJA OCUPADA" : "ABRIR TURNO"}
        </button>
      </Panel>
    </div>
  );
}
