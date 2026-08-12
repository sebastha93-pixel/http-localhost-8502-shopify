"use client";

/**
 * Pantalla de venta — la que decide si este POS sirve.
 *
 * TRES DECISIONES QUE SE NOTAN EN LA TIENDA:
 *
 * 1. El buscador SIEMPRE tiene el foco. El lector de códigos de barras es un
 *    teclado: escribe ahí sin que nadie toque nada, y una coincidencia exacta
 *    agrega la prenda sola. Cero clics por prenda — es el camino de los 30
 *    segundos.
 *
 * 2. El carrito vive AQUÍ, en el dispositivo, no en el servidor. Es lo que
 *    permite seguir vendiendo cuando se cae internet (ADR-005), y por eso la
 *    venta viaja completa en una sola petición al cerrar.
 *
 * 3. Un solo rojo por pantalla: COBRAR. Si aparece un segundo, el diseño está
 *    mal.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Buscador } from "@/components/pos/buscador";
import { RejillaProductos } from "@/components/pos/rejilla-productos";
import { Carrito } from "@/components/pos/carrito";
import { PanelCobro } from "@/components/pos/panel-cobro";
import { TicketCerrado } from "@/components/pos/ticket-cerrado";
import { DialogoDescuento, DialogoPin } from "@/components/pos/dialogo-descuento";
import {
  buscar,
  cerrarVenta,
  pedirAutorizacion,
  RequiereAutorizacion,
  type Variante,
  type Ticket,
} from "@/lib/pos/api";
import { nuevoUlid } from "@/lib/pos/ulid";
import { conIva, formatear } from "@/lib/pos/dinero";
import type { LineaCarrito } from "@/lib/pos/carrito";

// Mientras no exista la pantalla de apertura de turno (Fase 5), el punto de
// venta se toma de la configuración. No se inventa un default silencioso: si
// falta, la pantalla lo dice en vez de vender contra la tienda equivocada.
const TIENDA = process.env.NEXT_PUBLIC_POS_TIENDA || "";
const CAJA = process.env.NEXT_PUBLIC_POS_CAJA || "";
const UBICACION = process.env.NEXT_PUBLIC_POS_UBICACION || "";
const SESION = process.env.NEXT_PUBLIC_POS_SESION || "";
// Tope de descuento de quien está en la caja. Fase 5: lo trae la apertura de
// turno desde `retail.permisos_pos`. Hasta entonces, el de una cajera.
const TOPE = Number(process.env.NEXT_PUBLIC_POS_TOPE || 10);

type Fase = "vendiendo" | "cobrando" | "cerrada";

export default function PantallaVenta() {
  const [consulta, setConsulta] = useState("");
  const [resultados, setResultados] = useState<Variante[]>([]);
  const [lineas, setLineas] = useState<LineaCarrito[]>([]);
  const [fase, setFase] = useState<Fase>("vendiendo");
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [descontando, setDescontando] = useState<string | null>(null);
  const [pidiendoPin, setPidiendoPin] = useState<
    { sku: string; pct: number; motivo: string; mensaje: string } | null
  >(null);
  const [errorPin, setErrorPin] = useState<string | null>(null);
  const ventaId = useRef<string>(nuevoUlid());
  const buscadorRef = useRef<HTMLInputElement>(null);

  const configurado = TIENDA && CAJA && UBICACION && SESION;

  // ── Búsqueda ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!consulta.trim() || !configurado) {
      setResultados([]);
      return;
    }
    let vigente = true;
    setBuscando(true);
    // 120 ms: por debajo de eso se dispara una petición por tecla; por encima
    // se siente lento. En operación real esto no viaja a la red (ADR-009).
    const t = setTimeout(async () => {
      try {
        const r = await buscar(consulta.trim(), UBICACION);
        if (!vigente) return;
        setResultados(r);
        // Un escaneo no es una búsqueda: la prenda entra sola.
        if (r.length === 1 && r[0].es_escaneo) {
          agregar(r[0]);
          setConsulta("");
        }
      } catch (e) {
        if (vigente) setAviso(e instanceof Error ? e.message : "No se pudo buscar.");
      } finally {
        if (vigente) setBuscando(false);
      }
    }, 120);
    return () => {
      vigente = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consulta, configurado]);

  // ── Carrito ───────────────────────────────────────────────────────────
  const agregar = useCallback((v: Variante) => {
    setLineas((prev) => {
      const i = prev.findIndex((l) => l.sku === v.sku);
      if (i >= 0) {
        const copia = [...prev];
        copia[i] = { ...copia[i], cantidad: copia[i].cantidad + 1 };
        return copia;
      }
      return [
        ...prev,
        {
          sku: v.sku,
          descripcion: `${v.nombre} · ${v.talla}`,
          cantidad: 1,
          precioUnitarioSinIva: v.precio_base_centavos,
          tasaIva: 19,
          disponible: v.disponible,
        },
      ];
    });
    buscadorRef.current?.focus();
  }, []);

  const cambiarCantidad = (sku: string, cantidad: number) =>
    setLineas((prev) =>
      cantidad <= 0
        ? prev.filter((l) => l.sku !== sku)
        : prev.map((l) => (l.sku === sku ? { ...l, cantidad } : l)),
    );

  const quitar = (sku: string) => setLineas((prev) => prev.filter((l) => l.sku !== sku));

  /** Dentro del tope se aplica y ya. Por encima, se pide la firma ANTES de
   *  tocar el carrito: aplicarlo y deshacerlo si el PIN falla dejaría el total
   *  bailando delante de la clienta. */
  function aplicarDescuento(sku: string, pct: number, motivo: string) {
    setDescontando(null);
    if (pct > TOPE) {
      setPidiendoPin({
        sku,
        pct,
        motivo,
        mensaje: `Un descuento del ${pct}% supera tu tope (${TOPE}%). Pide a un supervisor que ingrese su PIN.`,
      });
      return;
    }
    ponerDescuento(sku, pct, motivo, null);
  }

  function ponerDescuento(sku: string, pct: number, motivo: string, firma: string | null) {
    setLineas((prev) =>
      prev.map((l) =>
        l.sku === sku
          ? { ...l, descuentoPct: pct, descuentoMotivo: motivo, autorizadoPor: firma }
          : l,
      ),
    );
  }

  async function firmar(pin: string) {
    if (!pidiendoPin) return;
    setErrorPin(null);
    try {
      const firma = await pedirAutorizacion(pin, TIENDA);
      if (pidiendoPin.pct > Number(firma.tope_descuento_pct)) {
        // Autorizar no es un cheque en blanco: quien firma tiene su propio
        // tope, y pasarse es un NO definitivo — no otro «pide autorización»,
        // que dejaría a la cajera en un bucle pidiendo una firma imposible.
        setErrorPin(
          `${firma.nombre} puede autorizar hasta ${firma.tope_descuento_pct}%. Este descuento necesita a alguien con más tope.`,
        );
        return;
      }
      ponerDescuento(pidiendoPin.sku, pidiendoPin.pct, pidiendoPin.motivo, firma.autorizado_por);
      setPidiendoPin(null);
    } catch (e) {
      setErrorPin(e instanceof Error ? e.message : "PIN incorrecto.");
    }
  }

  // ── Totales ───────────────────────────────────────────────────────────
  const totales = useMemo(() => {
    let base = 0;
    let iva = 0;
    let descuento = 0;
    for (const l of lineas) {
      const sub = l.precioUnitarioSinIva * l.cantidad;
      const desc = l.descuentoPct ? Math.round((sub * l.descuentoPct) / 100) : 0;
      const gravable = sub - desc;
      base += gravable;
      descuento += desc;
      // El IVA se calcula POR LÍNEA sobre la base YA descontada, igual que en
      // el dominio (INV-V12). Calcularlo sobre el total da otro número.
      iva += Math.round((gravable * l.tasaIva) / 100);
    }
    return { base, iva, descuento, total: base + iva };
  }, [lineas]);

  // ── Cierre ────────────────────────────────────────────────────────────
  async function cobrar(pagos: { medio_pago_id: string; monto_centavos: number; es_efectivo: boolean }[]) {
    setAviso(null);
    try {
      const t = await cerrarVenta({
        venta_id: ventaId.current,
        // Provisional hasta que exista el arriendo de bloques de consecutivo.
        numero: `FV-20-${Date.now() % 100000}`,
        tienda_id: TIENDA,
        caja_id: CAJA,
        sesion_id: SESION,
        ubicacion_id: UBICACION,
        tope_descuento: String(TOPE),
        lineas: lineas.map((l) => ({
          sku: l.sku,
          cantidad: l.cantidad,
          precio_unitario_centavos: l.precioUnitarioSinIva,
          tasa_iva: String(l.tasaIva),
          descripcion: l.descripcion,
          ...(l.descuentoPct
            ? {
                descuento_porcentaje: String(l.descuentoPct),
                descuento_motivo: l.descuentoMotivo,
                autorizado_por: l.autorizadoPor ?? undefined,
              }
            : {}),
        })),
        pagos,
      });
      setTicket(t);
      setFase("cerrada");
    } catch (e) {
      if (e instanceof RequiereAutorizacion) {
        // Fase 5: aquí se abre el diálogo del PIN del supervisor.
        setAviso(e.mensaje);
      } else {
        setAviso(e instanceof Error ? e.message : "No se pudo cerrar la venta.");
      }
      setFase("vendiendo");
    }
  }

  function nuevaVenta() {
    setLineas([]);
    setTicket(null);
    setConsulta("");
    setAviso(null);
    ventaId.current = nuevoUlid();
    setFase("vendiendo");
    buscadorRef.current?.focus();
  }

  // ── Atajos ────────────────────────────────────────────────────────────
  useEffect(() => {
    function alTeclado(e: KeyboardEvent) {
      if (e.key === "F4" && lineas.length && fase === "vendiendo") {
        e.preventDefault();
        setFase("cobrando");
      }
      if (e.key === "Escape" && fase === "cobrando") setFase("vendiendo");
      if (e.key === "Enter" && fase === "cerrada") nuevaVenta();
    }
    window.addEventListener("keydown", alTeclado);
    return () => window.removeEventListener("keydown", alTeclado);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lineas.length, fase]);

  if (!configurado) {
    return (
      <div className="flex min-h-screen items-center justify-center p-8">
        <div className="max-w-lg border border-[#8A6A22] bg-[#8A6A22]/10 p-6">
          <p className="font-display text-lg text-[#C6A047]">Punto de venta sin configurar</p>
          <p className="mt-3 text-sm leading-relaxed text-[#A6BECC]">
            Faltan las variables del punto de venta. Sin ellas esta caja no sabe
            desde qué tienda vende, y adivinarlo facturaría contra el inventario
            equivocado.
          </p>
          <pre className="mt-4 overflow-x-auto bg-[#0E1417] p-3 font-mono text-xs text-[#6F92A6]">
{`NEXT_PUBLIC_POS_TIENDA=florida
NEXT_PUBLIC_POS_CAJA=florida_caja1
NEXT_PUBLIC_POS_UBICACION=tienda:florida
NEXT_PUBLIC_POS_SESION=<ulid del turno abierto>`}
          </pre>
        </div>
      </div>
    );
  }

  if (fase === "cerrada" && ticket) {
    return <TicketCerrado ticket={ticket} onNueva={nuevaVenta} />;
  }

  return (
    <div className="flex h-screen flex-col">
      <BarraSuperior tienda={TIENDA} caja={CAJA} />

      <div className="grid flex-1 grid-cols-[1.55fr_1fr] overflow-hidden">
        {/* ── Catálogo ── */}
        <section className="flex flex-col overflow-hidden border-r border-[#243036] p-4">
          <Buscador
            ref={buscadorRef}
            valor={consulta}
            onCambio={setConsulta}
            buscando={buscando}
            pausado={Boolean(descontando || pidiendoPin)}
          />
          <RejillaProductos
            resultados={resultados}
            consulta={consulta}
            onElegir={agregar}
          />
        </section>

        {/* ── Carrito ── */}
        <section className="flex flex-col overflow-hidden bg-[#131B1F] p-4">
          {fase === "cobrando" ? (
            <PanelCobro
              total={totales.total}
              onCancelar={() => setFase("vendiendo")}
              onConfirmar={cobrar}
            />
          ) : (
            <Carrito
              lineas={lineas}
              totales={totales}
              aviso={aviso}
              onCantidad={cambiarCantidad}
              onQuitar={quitar}
              onCobrar={() => setFase("cobrando")}
              onDescuento={setDescontando}
            />
          )}
        </section>
      </div>

      {descontando && (
        <DialogoDescuento
          sku={descontando}
          base={
            (lineas.find((l) => l.sku === descontando)?.precioUnitarioSinIva ?? 0) *
            (lineas.find((l) => l.sku === descontando)?.cantidad ?? 1)
          }
          tope={TOPE}
          onCancelar={() => setDescontando(null)}
          onAplicar={(pct, motivo) => aplicarDescuento(descontando, pct, motivo)}
        />
      )}

      {pidiendoPin && (
        <DialogoPin
          motivo={pidiendoPin.mensaje}
          error={errorPin}
          onCancelar={() => {
            setPidiendoPin(null);
            setErrorPin(null);
          }}
          onFirmar={firmar}
        />
      )}
    </div>
  );
}

function BarraSuperior({ tienda, caja }: { tienda: string; caja: string }) {
  return (
    <header className="flex items-center justify-between border-b border-[#243036] bg-[#131B1F] px-4 py-2.5">
      <div className="flex items-center gap-4 font-mono text-[11px] text-[#6F92A6]">
        <span className="font-display text-xs font-semibold tracking-widest text-[#F4F3F0]">
          MALE&apos;DENIM
        </span>
        <span>
          {tienda} · {caja}
        </span>
      </div>
      <IndicadorConexion />
    </header>
  );
}

/** Nunca un modal: detendría una venta que podía continuar. */
function IndicadorConexion() {
  const [enLinea, setEnLinea] = useState(true);
  useEffect(() => {
    const marcar = () => setEnLinea(navigator.onLine);
    marcar();
    window.addEventListener("online", marcar);
    window.addEventListener("offline", marcar);
    return () => {
      window.removeEventListener("online", marcar);
      window.removeEventListener("offline", marcar);
    };
  }, []);
  return (
    <span className={`font-mono text-[11px] ${enLinea ? "text-[#6E9169]" : "text-[#B08C2E]"}`}>
      {enLinea ? "● En línea" : "▲ Sin conexión · sigues vendiendo"}
    </span>
  );
}
