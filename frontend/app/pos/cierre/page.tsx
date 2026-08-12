"use client";

/**
 * Cierre de caja — vista 7 del handoff.
 *
 * POR QUÉ ESTA PANTALLA ANTES QUE STOCK O PANEL: sin ella el POS abre turnos
 * que no puede cerrar, y `ux_sesion_abierta` sólo admite uno abierto por caja.
 * Es decir: la tienda vende un día y al siguiente no puede abrir. Inventario y
 * panel son consultas; esto es la salida del ciclo.
 *
 * Dos columnas, máximo 900px, como el diseño: el resumen del turno a la
 * izquierda, el arqueo a la derecha.
 */
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Panel } from "@/components/pos/marco";
import { Rail } from "@/components/pos/rail";
import { Arqueo, DialogoDescuadre } from "@/components/pos/arqueo";
import {
  cerrarCaja,
  resumenCierre,
  turnoActual,
  type Cierre,
  type ResumenCierre,
  type Turno,
} from "@/lib/pos/api";
import { formatear, desdePesosTecleados } from "@/lib/pos/dinero";

const CAJA = process.env.NEXT_PUBLIC_POS_CAJA || "";

export default function PantallaCierre() {
  const { user } = useAuth();
  const [turno, setTurno] = useState<Turno | null>(null);
  const [resumen, setResumen] = useState<ResumenCierre | null>(null);
  const [contados, setContados] = useState<Record<string, string>>({});
  const [cerrando, setCerrando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);
  const [descuadre, setDescuadre] = useState<string | null>(null);
  const [errorPin, setErrorPin] = useState<string | null>(null);
  const [cerrado, setCerrado] = useState<Cierre | null>(null);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const t = await turnoActual(CAJA);
        if (!vivo) return;
        setTurno(t);
        if (t) setResumen(await resumenCierre(t.sesion_id));
      } catch (e) {
        if (vivo) setError(e instanceof Error ? e.message : "No se pudo cargar el turno.");
      } finally {
        if (vivo) setCargando(false);
      }
    })();
    return () => {
      vivo = false;
    };
  }, []);

  const enviar = useCallback(
    async (justificacion?: string) => {
      if (!resumen) return;
      setCerrando(true);
      setError(null);
      setErrorPin(null);
      try {
        const conteos = (resumen.medios.length
          ? resumen.medios
          : [{ medio_pago_id: "efectivo", entra_al_arqueo: true, total_centavos: 0 }]
        ).map((m) => ({
          medio_pago_id: m.medio_pago_id,
          contado_centavos: m.entra_al_arqueo
            ? desdePesosTecleados(contados[m.medio_pago_id] ?? "")
            : m.total_centavos,
        }));

        setCerrado(
          await cerrarCaja({
            sesion_id: resumen.sesion_id,
            conteos,
            ...(justificacion ? { justificacion } : {}),
          }),
        );
        setDescuadre(null);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "No se pudo cerrar la caja.";
        // El backend distingue «falta la firma» de «hay un error». Un descuadre
        // grande no es un fallo: es una operación que necesita autorización.
        const necesitaFirma = e instanceof Error && e.name === "SobreElTope";
        const pideJustificacion = /justificaci/i.test(msg);

        // Falta la justificación → se abre el diálogo para escribirla.
        // Falta el PERMISO → no hay diálogo que ayude: tiene que entrar otra
        // persona, y eso se dice donde ya está mirando.
        if (necesitaFirma) {
          if (descuadre) setErrorPin(msg);
          else setError(msg);
        } else if (pideJustificacion) {
          if (descuadre) setErrorPin(msg);
          else setDescuadre(msg);
        } else if (descuadre) {
          setErrorPin(msg);
        } else {
          setError(msg);
        }
      } finally {
        setCerrando(false);
      }
    },
    [resumen, contados, descuadre],
  );

  const cajera = user?.nombre || user?.email || "";

  return (
    <div className="pos-raiz flex h-screen overflow-hidden">
      <Rail cajera={cajera} />

      <main className="flex-1 overflow-y-auto p-6">
        <header className="mb-6">
          <h1 className="titular text-[22px] font-semibold tracking-tight">
            Cierre de caja
          </h1>
          {resumen && (
            <p className="mt-1 tabular text-[12px] text-[var(--pos-600)]">
              Turno #{resumen.numero_turno} · {resumen.cajera_nombre} · abierto{" "}
              {new Date(resumen.abierta_en).toLocaleString("es-CO", {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </p>
          )}
        </header>

        {cargando && <Aviso texto="Cargando el turno…" />}

        {!cargando && !turno && (
          <Aviso texto="Esta caja no tiene ningún turno abierto. No hay nada que cerrar." />
        )}

        {error && !resumen && <Aviso texto={error} tono="error" />}

        {cerrado && resumen && (
          <CajaCerrada cierre={cerrado} resumen={resumen} contados={contados} />
        )}

        {!cerrado && resumen && (
          <div className="grid max-w-[900px] grid-cols-1 gap-4 lg:grid-cols-2">
            <ResumenTurno resumen={resumen} />
            <Arqueo
              resumen={resumen}
              contados={contados}
              onContar={(id, texto) =>
                setContados((c) => ({ ...c, [id]: texto.replace(/[^\d]/g, "") }))
              }
              onCerrar={() => enviar()}
              cerrando={cerrando}
              error={error}
            />
          </div>
        )}
      </main>

      {descuadre && (
        <DialogoDescuadre
          mensaje={descuadre}
          error={errorPin}
          onCancelar={() => {
            setDescuadre(null);
            setErrorPin(null);
          }}
          onFirmar={(j) => enviar(j)}
        />
      )}
    </div>
  );
}

function ResumenTurno({ resumen }: { resumen: ResumenCierre }) {
  const netas = resumen.ventas_brutas_centavos - resumen.monto_anulado_centavos;

  return (
    <Panel className="flex flex-col gap-3 p-6">
      <h2 className="titular text-[17px] font-semibold">Resumen del turno</h2>

      <Linea label="Transacciones" valor={String(resumen.transacciones)} />
      <Linea label="Ventas brutas" valor={formatear(resumen.ventas_brutas_centavos)} />
      <Linea
        label="Descuentos"
        valor={conSigno(resumen.descuentos_centavos)}
        acento={resumen.descuentos_centavos > 0}
      />
      {/* El handoff pone aquí «Devoluciones». No existen en esta fase por
          decisión de alcance, así que la línea es de ANULACIONES: una venta
          anulada el mismo turno es lo que hoy sí puede restar. Poner una línea
          de devoluciones en cero haría creer que el módulo está y que hoy no
          hubo. */}
      <Linea
        label={`Anuladas (${resumen.anuladas})`}
        valor={conSigno(resumen.monto_anulado_centavos)}
        acento={resumen.anuladas > 0}
      />
      <Linea label="Ventas netas" valor={formatear(netas)} fuerte separador />

      <p className="kicker mt-2 text-[var(--pos-600)]">Por método de pago</p>
      {resumen.medios.length === 0 && (
        <p className="text-[13px] text-[var(--pos-600)]">
          Sin movimientos todavía. La base sigue en el cajón y hay que contarla.
        </p>
      )}
      {resumen.medios.map((m) => (
        <div
          key={m.medio_pago_id}
          className="flex justify-between border-b border-[var(--pos-divider)]/60 py-1.5 text-[13px]"
        >
          <span className="text-[var(--pos-700)]">{m.nombre}</span>
          {/* Ojo: el efectivo INCLUYE la base. Mostrarlo sin decirlo haría que
              la cajera lo leyera como «vendí esto en efectivo» y contara mal. */}
          <span className="tabular font-semibold">
            {formatear(m.total_centavos)}
            {m.es_efectivo && (
              <span className="ml-1.5 font-normal text-[var(--pos-600)]">
                (con base)
              </span>
            )}
          </span>
        </div>
      ))}

      {resumen.documentos_pendientes > 0 && (
        <p className="mt-3 border-l-2 border-[var(--pos-accent)] bg-[var(--pos-100)] py-2 pl-3 text-[12px] leading-relaxed text-[var(--pos-700)]">
          Quedan {resumen.documentos_pendientes} documento(s) fiscal(es) por
          emitir. Puedes cerrar igual: la venta ya está en el arqueo y la
          factura sale cuando vuelva Siigo.
        </p>
      )}
      {resumen.ventas_en_borrador > 0 && (
        <p className="mt-3 border-l-2 border-[var(--pos-800)] bg-[var(--pos-800)]/10 py-2 pl-3 text-[12px] leading-relaxed text-[var(--pos-900)]">
          Hay {resumen.ventas_en_borrador} venta(s) sin terminar. Ciérralas o
          descártalas antes de arquear.
        </p>
      )}
    </Panel>
  );
}

function CajaCerrada({
  cierre,
  resumen,
  contados,
}: {
  cierre: Cierre;
  resumen: ResumenCierre;
  contados: Record<string, string>;
}) {
  const dif = cierre.diferencia_centavos;

  return (
    <Panel className="max-w-[560px] p-8">
      <p className="kicker text-[var(--pos-600)]">Turno #{cierre.numero_turno}</p>
      <h2 className="titular mt-1 text-[26px] font-semibold tracking-tight">
        Caja cerrada
      </h2>

      <div className="mt-6 flex flex-col gap-3">
        <Linea
          label="Transacciones"
          valor={String(resumen.transacciones)}
        />
        <Linea label="Ventas brutas" valor={formatear(resumen.ventas_brutas_centavos)} />
        {resumen.medios.map((m) => (
          <Linea
            key={m.medio_pago_id}
            label={`${m.nombre} contado`}
            valor={formatear(
              m.entra_al_arqueo
                ? desdePesosTecleados(contados[m.medio_pago_id] ?? "")
                : m.total_centavos,
            )}
          />
        ))}
        <Linea
          label="Diferencia"
          valor={dif > 0 ? `+${formatear(dif)}` : formatear(dif)}
          fuerte
          separador
          acento={!cierre.cuadro}
        />
      </div>

      <p
        className={`mt-5 border-l-2 py-2.5 pl-3 text-[12.5px] leading-relaxed ${
          cierre.cuadro
            ? "border-[var(--pos-accent)] bg-[var(--pos-100)] text-[var(--pos-700)]"
            : "border-[var(--pos-800)] bg-[var(--pos-800)]/10 text-[var(--pos-900)]"
        }`}
      >
        {cierre.cuadro
          ? "El conteo coincide con lo esperado."
          : `El cierre quedó con diferencia y está marcado como crítico en la auditoría${
              cierre.autorizado_por_nombre
                ? `, autorizado por ${cierre.autorizado_por_nombre}`
                : ""
            }.`}
      </p>

      <p className="mt-4 tabular text-[10.5px] leading-relaxed text-[var(--pos-600)]">
        La caja queda libre para el siguiente turno.
      </p>

      <a
        href="/pos/venta"
        className="mt-6 flex h-12 items-center justify-center bg-[var(--pos-accent)] titular text-[13px] font-semibold tracking-[0.08em] text-white"
      >
        VOLVER A VENTA
      </a>
    </Panel>
  );
}

/** «−$0» se lee como un error de la pantalla. Un día sin descuentos ni
 *  anulaciones es $0, sin signo. */
function conSigno(centavos: number): string {
  return centavos > 0 ? `−${formatear(centavos)}` : formatear(0);
}

function Linea({
  label,
  valor,
  fuerte,
  separador,
  acento,
}: {
  label: string;
  valor: string;
  fuerte?: boolean;
  separador?: boolean;
  acento?: boolean;
}) {
  return (
    <div
      className={`flex items-baseline justify-between gap-2 ${
        fuerte ? "text-[14px]" : "text-[13px]"
      } ${separador ? "border-t border-[var(--pos-divider)] pt-3" : ""}`}
    >
      <span className="text-[var(--pos-700)]">{label}</span>
      <span
        className={`tabular whitespace-nowrap ${
          fuerte ? "titular text-[18px] font-semibold" : "font-medium"
        } ${acento ? "text-[var(--pos-800)]" : ""}`}
      >
        {valor}
      </span>
    </div>
  );
}

function Aviso({ texto, tono }: { texto: string; tono?: "error" }) {
  return (
    <p
      className={`max-w-[560px] border-l-2 py-3 pl-4 text-[13px] leading-relaxed ${
        tono === "error"
          ? "border-[var(--pos-800)] bg-[var(--pos-800)]/10 text-[var(--pos-900)]"
          : "border-[var(--pos-divider)] bg-[var(--pos-100)] text-[var(--pos-700)]"
      }`}
    >
      {texto}
    </p>
  );
}
