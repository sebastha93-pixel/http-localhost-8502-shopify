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
import { DialogoMovimiento } from "@/components/pos/dialogo-movimiento";
import { DialogoAnular, VentasDelTurno } from "@/components/pos/ventas-del-turno";
import { Tirilla } from "@/components/pos/tirilla";
import { totalDe } from "@/components/pos/contador-denominaciones";
import {
  anularVenta,
  cerrarCaja,
  moverCaja,
  pedirTirilla,
  resumenCierre,
  ventasDelTurno,
  type Tirilla as DatosTirilla,
  type VentaDelTurno,
  turnoActual,
  type Cierre,
  type ResumenCierre,
  type Turno,
} from "@/lib/pos/api";
import { formatear, desdePesosTecleados } from "@/lib/pos/dinero";
import { nuevoUlid } from "@/lib/pos/ulid";

const CAJA = process.env.NEXT_PUBLIC_POS_CAJA || "";

export default function PantallaCierre() {
  const { user } = useAuth();
  const [turno, setTurno] = useState<Turno | null>(null);
  const [resumen, setResumen] = useState<ResumenCierre | null>(null);
  const [contados, setContados] = useState<Record<string, string>>({});
  // El efectivo se cuenta por denominación; los demás medios siguen con total.
  const [piezas, setPiezas] = useState<Record<number, number>>({});
  const [cerrando, setCerrando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);
  const [descuadre, setDescuadre] = useState<string | null>(null);
  const [errorPin, setErrorPin] = useState<string | null>(null);
  const [cerrado, setCerrado] = useState<Cierre | null>(null);
  const [moviendo, setMoviendo] = useState(false);
  const [errorMovimiento, setErrorMovimiento] = useState<string | null>(null);
  const [guardandoMov, setGuardandoMov] = useState(false);
  const [ventas, setVentas] = useState<VentaDelTurno[]>([]);
  const [anulando, setAnulando] = useState<VentaDelTurno | null>(null);
  const [errorAnular, setErrorAnular] = useState<string | null>(null);
  const [enviandoAnulacion, setEnviandoAnulacion] = useState(false);
  const [tirillaAImprimir, setTirillaAImprimir] = useState<DatosTirilla | null>(null);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const t = await turnoActual(CAJA);
        if (!vivo) return;
        setTurno(t);
        if (t) {
          setResumen(await resumenCierre(t.sesion_id));
          setVentas(await ventasDelTurno(t.sesion_id));
        }
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
          : [{ medio_pago_id: "efectivo", es_efectivo: true,
               entra_al_arqueo: true, total_centavos: 0 }]
        ).map((m) =>
          // El efectivo va por PIEZAS: el total lo saca el servidor, así que
          // deja de ser un número que se pueda escribir de memoria. Los demás
          // medios no tienen billetes y su cifra sale del cierre del datáfono.
          m.es_efectivo
            ? { medio_pago_id: m.medio_pago_id, piezas }
            : {
                medio_pago_id: m.medio_pago_id,
                contado_centavos: m.entra_al_arqueo
                  ? desdePesosTecleados(contados[m.medio_pago_id] ?? "")
                  : m.total_centavos,
              },
        );

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
    [resumen, contados, piezas, descuadre],
  );

  async function registrarMovimiento(
    tipo: "retiro" | "gasto" | "ingreso",
    montoCentavos: number,
    motivo: string,
  ) {
    if (!resumen) return;
    setGuardandoMov(true);
    setErrorMovimiento(null);
    try {
      await moverCaja({
        movimiento_id: nuevoUlid(), sesion_id: resumen.sesion_id,
        tipo, monto_centavos: montoCentavos, motivo,
      });
      // Se recarga el resumen entero: el movimiento cambió el esperado, y
      // recalcularlo aquí sería una segunda versión de esa cuenta.
      setResumen(await resumenCierre(resumen.sesion_id));
      setMoviendo(false);
    } catch (e) {
      setErrorMovimiento(
        e instanceof Error ? e.message : "No se pudo registrar el movimiento.");
    } finally {
      setGuardandoMov(false);
    }
  }

  async function reimprimir(ventaId: string) {
    try {
      setTirillaAImprimir(await pedirTirilla(ventaId));
      // La misma pausa que en el cierre de venta: React tiene que pintar la
      // tirilla antes de abrir el diálogo, o sale una hoja en blanco.
      await new Promise((r) => setTimeout(r, 60));
      window.print();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo traer la tirilla.");
    }
  }

  async function confirmarAnulacion(motivo: string) {
    if (!anulando || !resumen) return;
    setEnviandoAnulacion(true);
    setErrorAnular(null);
    try {
      await anularVenta(anulando.venta_id, motivo);
      // Se recargan las DOS cosas: la anulación mueve el arqueo y la lista.
      setResumen(await resumenCierre(resumen.sesion_id));
      setVentas(await ventasDelTurno(resumen.sesion_id));
      setAnulando(null);
    } catch (e) {
      setErrorAnular(
        e instanceof Error ? e.message : "No se pudo anular la venta.");
    } finally {
      setEnviandoAnulacion(false);
    }
  }

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
          <CajaCerrada cierre={cerrado} resumen={resumen} contados={contados}
                       piezas={piezas} />
        )}

        {!cerrado && resumen && (
          <div className="grid max-w-[900px] grid-cols-1 gap-4 lg:grid-cols-2">
            <ResumenTurno resumen={resumen} onMover={() => setMoviendo(true)} />
            <div className="flex flex-col gap-4">
              <Arqueo
                resumen={resumen}
              contados={contados}
              onContar={(id, texto) =>
                setContados((c) => ({ ...c, [id]: texto.replace(/[^\d]/g, "") }))
              }
              piezas={piezas}
              onPiezas={setPiezas}
              onCerrar={() => enviar()}
                cerrando={cerrando}
                error={error}
              />
              <VentasDelTurno
                ventas={ventas}
                onReimprimir={reimprimir}
                onAnular={setAnulando}
                puedeAnular={resumen.puede_anular_venta}
              />
            </div>
          </div>
        )}
      </main>

      {/* Fuera de pantalla, no `display:none`: lo oculto no se imprime. */}
      {tirillaAImprimir && (
        <div className="absolute -left-[9999px] top-0" aria-hidden>
          <Tirilla datos={tirillaAImprimir} />
        </div>
      )}

      {anulando && (
        <DialogoAnular
          venta={anulando}
          onCancelar={() => { setAnulando(null); setErrorAnular(null); }}
          onConfirmar={confirmarAnulacion}
          error={errorAnular}
          anulando={enviandoAnulacion}
        />
      )}

      {moviendo && (
        <DialogoMovimiento
          onCancelar={() => { setMoviendo(false); setErrorMovimiento(null); }}
          onRegistrar={registrarMovimiento}
          error={errorMovimiento}
          guardando={guardandoMov}
        />
      )}

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

function ResumenTurno({
  resumen,
  onMover,
}: {
  resumen: ResumenCierre;
  onMover: () => void;
}) {
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

      {/* MOVIMIENTOS DE CAJA. Van aparte del desglose por medio de pago: son
          plata que entró o salió sin ser una venta, y mezclarlos haría que ese
          desglose no cuadre con lo vendido. */}
      <div className="mt-3 flex items-center justify-between">
        <p className="kicker text-[var(--pos-600)]">Movimientos de caja</p>
        <button
          onClick={onMover}
          className="border border-[var(--pos-divider)] px-2.5 py-1 text-[12px] text-[var(--pos-700)] hover:bg-[var(--pos-100)]"
        >
          + Registrar
        </button>
      </div>
      {resumen.movimientos.length === 0 && (
        <p className="text-[12.5px] text-[var(--pos-600)]">
          Ninguno. Si sacaste plata del cajón —domicilio, bolsas, sangría—
          regístralo aquí o el arqueo lo va a leer como faltante.
        </p>
      )}
      {resumen.movimientos.map((m) => (
        <div
          key={m.movimiento_id}
          className="flex justify-between gap-2 border-b border-[var(--pos-divider)]/60 py-1.5 text-[13px]"
        >
          <span className="min-w-0 flex-1 truncate text-[var(--pos-700)]">
            <span className="capitalize">{m.tipo}</span>
            <span className="ml-1.5 text-[var(--pos-600)]">{m.motivo}</span>
            <span className="ml-1.5 text-[12px] text-[var(--pos-muted)]">
              · {m.quien}
            </span>
          </span>
          {/* El monto viene CON SIGNO desde la base: negativo si salió. */}
          <span
            className={`tabular whitespace-nowrap font-semibold ${
              m.monto_centavos < 0 ? "text-[var(--pos-800)]" : ""
            }`}
          >
            {m.monto_centavos > 0 ? "+" : ""}
            {formatear(m.monto_centavos)}
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
  piezas,
}: {
  cierre: Cierre;
  resumen: ResumenCierre;
  contados: Record<string, string>;
  piezas: Record<number, number>;
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
              m.es_efectivo
                ? totalDe(piezas)
                : m.entra_al_arqueo
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

      <p className="mt-4 tabular text-[12px] leading-relaxed text-[var(--pos-600)]">
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
