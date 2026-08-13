"use client";

/**
 * Panel de ventas del día — vista 8 del handoff.
 *
 * Lo mira la administradora entre clientas: cómo va el día, a qué horas se
 * vende y qué se está llevando la gente.
 *
 * SE REFRESCA SOLO, cada 60 segundos. Un panel que hay que recargar a mano
 * termina mostrando la cifra de hace dos horas mientras alguien la lee como si
 * fuera de ahora. El minuto no es capricho: es más rápido que el ritmo al que
 * cambia una tienda y más lento que el ritmo al que molesta.
 *
 * LA FECHA ESTÁ A LA VISTA a propósito. En UTC−5 el corte del día no coincide
 * con el del servidor, y ese es el error que este panel puede cometer sin que
 * se note. Ponerla arriba hace que un desfase se vea en vez de esconderse.
 */
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Panel as Marco } from "@/components/pos/marco";
import { Auditoria } from "@/components/pos/auditoria";
import { Rail } from "@/components/pos/rail";
import { formatear } from "@/lib/pos/dinero";
import { panelDelDia, type Panel as Datos } from "@/lib/pos/api";

const TIENDA = process.env.NEXT_PUBLIC_POS_TIENDA || "";
const REFRESCO_MS = 60_000;

export default function PantallaPanel() {
  const { user } = useAuth();
  const [datos, setDatos] = useState<Datos | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actualizado, setActualizado] = useState<Date | null>(null);

  const cargar = useCallback(async () => {
    try {
      setDatos(await panelDelDia(TIENDA));
      setError(null);
      setActualizado(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el panel.");
    }
  }, []);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, REFRESCO_MS);
    return () => clearInterval(t);
  }, [cargar]);

  const pico = Math.max(1, ...(datos?.horas ?? []).map((h) => h.ventas_centavos));

  return (
    <div className="pos-raiz flex h-screen overflow-hidden">
      <Rail cajera={user?.nombre || user?.email || ""} />

      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
        <header className="flex flex-wrap items-baseline gap-3">
          <h1 className="titular text-[22px] font-semibold tracking-tight">
            Panel de ventas
          </h1>
          {/* Los permisos no van en el rail: no es pantalla de cajera. Pero
              tienen que ser alcanzables sin teclear la URL a mano. */}
          <a
            href="/pos/permisos"
            className="ml-auto border border-[var(--pos-divider)] px-2.5 py-1 text-[11px] text-[var(--pos-700)] hover:bg-[var(--pos-100)]"
          >
            Permisos
          </a>
          {datos && (
            <p className="tabular text-[12px] text-[var(--pos-600)]">
              {datos.tienda_nombre} · {fechaLarga(datos.fecha)}
              {actualizado && (
                <span className="ml-2 text-[var(--pos-500)]">
                  actualizado{" "}
                  {actualizado.toLocaleTimeString("es-CO", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              )}
            </p>
          )}
        </header>

        {error && (
          <p className="max-w-[560px] border-l-2 border-[var(--pos-800)] bg-[var(--pos-800)]/10 py-3 pl-4 text-[13px] text-[var(--pos-900)]">
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
                titulo="Ventas hoy"
                valor={formatear(datos.ventas_centavos)}
                pie={
                  datos.descuentos_centavos
                    ? `${formatear(datos.descuentos_centavos)} en descuentos`
                    : "sin descuentos"
                }
              />
              <Tarjeta
                titulo="Transacciones"
                valor={String(datos.transacciones)}
                pie={
                  datos.transacciones
                    ? `ticket promedio ${formatear(datos.ticket_promedio_centavos)}`
                    : "—"
                }
              />
              <Tarjeta
                titulo="Unidades"
                valor={String(datos.unidades)}
                pie={
                  datos.transacciones
                    ? `${(datos.unidades / datos.transacciones).toFixed(1)} por venta`
                    : "—"
                }
              />
              {/* El handoff pone «Devoluciones». No existen en esta fase por
                  decisión de alcance; poner la tarjeta en cero haría creer que
                  el módulo está y que hoy no hubo ninguna. */}
              <Tarjeta
                titulo="Anuladas"
                valor={String(datos.anuladas)}
                pie={
                  datos.anuladas
                    ? formatear(datos.monto_anulado_centavos)
                    : "ninguna"
                }
                alerta={datos.anuladas > 0}
              />
            </div>

            {/* `shrink-0`: en una columna flex los hijos se encogen por defecto, y
                con `min-h-0` pueden bajar de su contenido. Mientras esta fue la
                última sección no se notó; al añadir la auditoría debajo, el
                grid cedió espacio y el gráfico se salió por encima de ella.
                La columna ya tiene `overflow-y-auto`: que scrollee la página. */}
            <div className="grid shrink-0 grid-cols-1 gap-3 lg:grid-cols-[1.6fr_1fr]">
              <Marco className="flex min-w-0 flex-col gap-3 p-6">
                <h2 className="titular text-[17px] font-semibold">
                  Ventas por hora
                </h2>
                <div className="flex h-[180px] items-end gap-2 pt-2">
                  {datos.horas.map((h) => {
                    const alto = (h.ventas_centavos / pico) * 100;
                    const esPico =
                      h.ventas_centavos === pico && h.ventas_centavos > 0;
                    return (
                      <div
                        key={h.hora}
                        className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1.5"
                        title={
                          h.transacciones
                            ? `${h.etiqueta} · ${h.transacciones} venta(s) · ${formatear(h.ventas_centavos)}`
                            : `${h.etiqueta} · sin ventas`
                        }
                      >
                        <div
                          className="w-full max-w-[38px] rounded-t-[2px]"
                          style={{
                            // Mínimo 2px: una barra de altura cero desaparece y
                            // «no se vendió» se vuelve indistinguible de «no
                            // hay dato». Son cosas distintas.
                            height: `${Math.max(alto, h.ventas_centavos ? 4 : 2)}%`,
                            background: esPico
                              ? "var(--pos-accent)"
                              : h.ventas_centavos
                                ? "var(--pos-500)"
                                : "var(--pos-divider)",
                          }}
                        />
                        <span className="text-[10px] text-[var(--pos-600)]">
                          {h.hora}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <p className="tabular text-[10.5px] text-[var(--pos-600)]">
                  Hora de la tienda. Las barras vacías son horas sin ventas, no
                  horas sin datos.
                </p>
              </Marco>

              <Marco className="flex flex-col gap-2 p-6">
                <h2 className="titular text-[17px] font-semibold">
                  Más vendidos hoy
                </h2>
                {datos.mas_vendidos.length === 0 && (
                  <p className="text-[13px] text-[var(--pos-600)]">
                    Todavía no se ha vendido nada.
                  </p>
                )}
                {datos.mas_vendidos.map((m) => (
                  <div
                    key={m.referencia}
                    className="flex items-center gap-3 border-b border-[var(--pos-divider)]/60 py-2 last:border-0"
                  >
                    <span className="titular w-6 shrink-0 text-[15px] font-bold text-[var(--pos-700)]">
                      {String(m.posicion).padStart(2, "0")}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium">
                        {m.nombre}
                        {m.color && (
                          <span className="ml-1.5 font-normal text-[var(--pos-600)]">
                            {m.color}
                          </span>
                        )}
                      </p>
                      <p className="tabular text-[11px] text-[var(--pos-600)]">
                        {m.referencia}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="tabular text-[13px] font-semibold">
                        {m.unidades} u
                      </p>
                      <p className="tabular text-[11px] text-[var(--pos-600)]">
                        {formatear(m.valor_centavos)}
                      </p>
                    </div>
                  </div>
                ))}
                {datos.mas_vendidos.length > 0 && (
                  <p className="tabular mt-1 text-[10.5px] text-[var(--pos-600)]">
                    Por unidades y agrupado por referencia: es lo que hay que
                    reponer.
                  </p>
                )}
              </Marco>
            </div>

            {/* La auditoría vive AQUÍ y no en el rail: no es una pantalla de
                cajera. Quien la abre ya está mirando cómo va el día, y la
                consulta justo cuando algo de arriba no cuadra. */}
            <div className="shrink-0">
              <Auditoria tiendaId={TIENDA} />
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function Tarjeta({
  titulo,
  valor,
  pie,
  alerta,
}: {
  titulo: string;
  valor: string;
  pie: string;
  alerta?: boolean;
}) {
  return (
    <Marco className="flex flex-col gap-1 p-6">
      <span className="kicker text-[var(--pos-700)]">{titulo}</span>
      <span
        className={`titular text-[28px] font-bold leading-none ${
          alerta ? "text-[var(--pos-accent)]" : ""
        }`}
      >
        {valor}
      </span>
      <span className="tabular text-[11px] text-[var(--pos-600)]">{pie}</span>
    </Marco>
  );
}

/** `2026-08-12` → `mié, 12 ago`. Se construye a mano y no con `new Date(str)`
 *  porque eso interpreta la fecha en UTC y en Bogotá la corre un día atrás —
 *  justo el error que este panel existe para no cometer. */
function fechaLarga(iso: string): string {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d).toLocaleDateString("es-CO", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}
