"use client";

/**
 * Pantalla de venta — reconstruida sobre el handoff de diseño.
 *
 * Layout del diseño: rail de 92px + columna principal + carrito de 360px.
 * Sistema "Industry" retemado: tema claro, Barlow, estética de plano.
 *
 * LO QUE SE CONSERVA DE LA IMPLEMENTACIÓN ANTERIOR, y por qué:
 *
 * **El escáner.** El handoff dice «busca por nombre o referencia» y no
 * menciona el lector. Pero todo el camino de los 30 segundos depende de que el
 * código de barras entre solo, sin un clic — y Producción ya imprime Code128
 * en cada etiqueta. El buscador mantiene el foco y una coincidencia exacta con
 * un SKU agrega la prenda sola.
 *
 * **El descuento con autorización.** El diseño lo pone como botones
 * 0/10/20% sin motivo ni firma. Eso quita el control anti-fraude: un descuento
 * sin rastro es la vía por la que se saca mercancía. Se conservan los chips
 * rápidos, pero por encima del tope siguen pidiendo motivo y PIN. El diseñador
 * no tenía por qué saberlo — es una regla de negocio, no una decisión visual.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Panel } from "@/components/pos/marco";
import { Rail } from "@/components/pos/rail";
import { RejillaReferencias } from "@/components/pos/rejilla-referencias";
import { CarritoPanel } from "@/components/pos/carrito-panel";
import { PanelCobro } from "@/components/pos/panel-cobro";
import { TicketCerrado } from "@/components/pos/ticket-cerrado";
import { DialogoDescuento, DialogoPin } from "@/components/pos/dialogo-descuento";
import { DialogoCliente } from "@/components/pos/dialogo-cliente";
import {
  cerrarVenta,
  listarCatalogo,
  pedirAutorizacion,
  RequiereAutorizacion,
  type Cliente,
  type Referencia,
  type Talla,
  type Ticket,
} from "@/lib/pos/api";
import { nuevoUlid } from "@/lib/pos/ulid";
import type { LineaCarrito } from "@/lib/pos/carrito";

const TIENDA = process.env.NEXT_PUBLIC_POS_TIENDA || "";
const CAJA = process.env.NEXT_PUBLIC_POS_CAJA || "";
const UBICACION = process.env.NEXT_PUBLIC_POS_UBICACION || "";
const SESION = process.env.NEXT_PUBLIC_POS_SESION || "";
const TOPE = Number(process.env.NEXT_PUBLIC_POS_TOPE || 10);
const CAJERA = process.env.NEXT_PUBLIC_POS_CAJERA || "María R.";

type Fase = "vendiendo" | "cobrando" | "cerrada";

export default function PantallaVenta() {
  const [consulta, setConsulta] = useState("");
  const [categoria, setCategoria] = useState("Todo");
  const [categorias, setCategorias] = useState<string[]>([]);
  const [referencias, setReferencias] = useState<Referencia[]>([]);
  const [lineas, setLineas] = useState<LineaCarrito[]>([]);
  const [fase, setFase] = useState<Fase>("vendiendo");
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [descontando, setDescontando] = useState<string | null>(null);
  const [pidiendoPin, setPidiendoPin] = useState<
    { sku: string; pct: number; motivo: string; mensaje: string } | null
  >(null);
  const [errorPin, setErrorPin] = useState<string | null>(null);
  const [cliente, setCliente] = useState<Cliente | null>(null);
  const [asignandoCliente, setAsignandoCliente] = useState(false);
  const ventaId = useRef<string>(nuevoUlid());
  const buscadorRef = useRef<HTMLInputElement>(null);

  const configurado = Boolean(TIENDA && CAJA && UBICACION && SESION);
  const hayDialogo = Boolean(descontando || pidiendoPin || asignandoCliente);

  const agregar = useCallback((r: Referencia, t: Talla) => {
    setLineas((prev) => {
      const i = prev.findIndex((l) => l.sku === t.sku);
      if (i >= 0) {
        const copia = [...prev];
        copia[i] = { ...copia[i], cantidad: copia[i].cantidad + 1 };
        return copia;
      }
      return [
        ...prev,
        {
          sku: t.sku,
          descripcion: r.nombre,
          talla: t.talla,
          cantidad: 1,
          precioUnitarioSinIva: r.precio_base_centavos,
          tasaIva: Number(r.tasa_iva),
          disponible: t.disponible,
        },
      ];
    });
  }, []);

  // ── Catálogo ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (!configurado) return;
    let vigente = true;
    const temporizador = setTimeout(async () => {
      try {
        const d = await listarCatalogo(UBICACION, consulta.trim(), categoria);
        if (!vigente) return;
        setCategorias(d.categorias);
        setReferencias(d.referencias);

        // Un escaneo no es una búsqueda: si lo tecleado es EXACTAMENTE un SKU,
        // la prenda entra sola. Ése es el camino de los 30 segundos.
        const texto = consulta.trim().toUpperCase();
        if (texto.length >= 6) {
          for (const r of d.referencias) {
            const talla = r.tallas.find((x) => x.sku.toUpperCase() === texto);
            if (talla) {
              agregar(r, talla);
              setConsulta("");
              break;
            }
          }
        }
      } catch (e) {
        if (vigente) {
          setAviso(e instanceof Error ? e.message : "No se pudo leer el catálogo.");
        }
      }
    }, 120);
    return () => {
      vigente = false;
      clearTimeout(temporizador);
    };
  }, [consulta, categoria, configurado, agregar]);

  // El foco vive en el buscador para que el lector escriba sin un clic — pero
  // lo SUELTA cuando hay un diálogo encima, o el motivo del descuento termina
  // apareciendo en la caja de búsqueda. (Me pasó.)
  useEffect(() => {
    if (hayDialogo || fase !== "vendiendo") return;
    const el = buscadorRef.current;
    el?.focus();
    const t = setInterval(() => {
      const activo = document.activeElement;
      if (activo?.tagName === "INPUT" || activo?.tagName === "TEXTAREA") return;
      if (activo?.closest?.("[role=dialog]")) return;
      el?.focus();
    }, 800);
    return () => clearInterval(t);
  }, [hayDialogo, fase]);

  const cambiarCantidad = (sku: string, cantidad: number) =>
    setLineas((prev) =>
      cantidad <= 0
        ? prev.filter((l) => l.sku !== sku)
        : prev.map((l) => (l.sku === sku ? { ...l, cantidad } : l)),
    );

  // ── Descuentos ─────────────────────────────────────────────────────────
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

  function ponerDescuento(
    sku: string,
    pct: number,
    motivo: string,
    firma: string | null,
  ) {
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
        // Autorizar no es un cheque en blanco: pasarse del tope de quien firma
        // es un NO definitivo, no otro «pide autorización» — eso dejaría a la
        // cajera en un bucle pidiendo una firma imposible.
        setErrorPin(
          `${firma.nombre} puede autorizar hasta ${firma.tope_descuento_pct}%. Este descuento necesita a alguien con más tope.`,
        );
        return;
      }
      ponerDescuento(
        pidiendoPin.sku,
        pidiendoPin.pct,
        pidiendoPin.motivo,
        firma.autorizado_por,
      );
      setPidiendoPin(null);
    } catch (e) {
      setErrorPin(e instanceof Error ? e.message : "PIN incorrecto.");
    }
  }

  // ── Totales ────────────────────────────────────────────────────────────
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
      // El IVA se calcula POR LÍNEA sobre la base ya descontada (INV-V12).
      iva += Math.round((gravable * l.tasaIva) / 100);
    }
    return { base, iva, descuento, total: base + iva };
  }, [lineas]);

  // ── Cierre ─────────────────────────────────────────────────────────────
  async function cobrar(
    pagos: { medio_pago_id: string; monto_centavos: number; es_efectivo: boolean }[],
  ) {
    setAviso(null);
    try {
      const t = await cerrarVenta({
        venta_id: ventaId.current,
        numero: `FV-20-${Date.now() % 100000}`,
        tienda_id: TIENDA,
        caja_id: CAJA,
        sesion_id: SESION,
        ubicacion_id: UBICACION,
        cliente_id: cliente?.id ?? null,
        tope_descuento: String(TOPE),
        lineas: lineas.map((l) => ({
          sku: l.sku,
          cantidad: l.cantidad,
          precio_unitario_centavos: l.precioUnitarioSinIva,
          tasa_iva: String(l.tasaIva),
          descripcion: `${l.descripcion} · Talla ${l.talla}`,
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
      setAviso(
        e instanceof RequiereAutorizacion
          ? e.mensaje
          : e instanceof Error
            ? e.message
            : "No se pudo cerrar la venta.",
      );
      setFase("vendiendo");
    }
  }

  function nuevaVenta() {
    setLineas([]);
    setTicket(null);
    setConsulta("");
    setAviso(null);
    setCliente(null);
    ventaId.current = nuevoUlid();
    setFase("vendiendo");
  }

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
  });

  if (!configurado) return <SinConfigurar />;
  if (fase === "cerrada" && ticket) {
    return <TicketCerrado ticket={ticket} onNueva={nuevaVenta} />;
  }

  const hoy = new Date().toLocaleDateString("es-CO", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  return (
    <div className="flex h-screen">
      <Rail cajera={CAJERA} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex items-baseline justify-between border-b px-6 py-4"
          style={{ borderColor: "var(--pos-divider)" }}
        >
          <h1 className="titular text-[20px]">Venta</h1>
          <p className="text-[12px]" style={{ color: "var(--pos-600)" }}>
            Tienda Principal · Caja 01 · {CAJERA} · {hoy}
          </p>
        </header>

        {/* Las columnas viven en pos.css: llevan media query, y una pista
            `minmax(0, …)` — no `1fr` a secas, que no baja de su contenido
            min-content y hacía desbordar las tarjetas. */}
        <div className="pos-cuerpo min-h-0 flex-1">
          <section className="flex min-w-0 flex-col gap-3 overflow-hidden p-6">
            <div
              className="flex h-11 items-center gap-2.5 rounded-[var(--pos-r-md)] border px-3"
              style={{ borderColor: "var(--pos-divider)" }}
            >
              <LupaIcono />
              <input
                ref={buscadorRef}
                value={consulta}
                onChange={(e) => setConsulta(e.target.value)}
                placeholder="Buscar por nombre o referencia"
                aria-label="Buscar producto"
                autoComplete="off"
                spellCheck={false}
                className="w-full bg-transparent text-[14px] outline-none placeholder:text-[var(--pos-500)]"
              />
            </div>

            <div className="flex flex-wrap gap-2">
              {["Todo", ...categorias].map((c) => {
                const activo = categoria === c;
                return (
                  <button
                    key={c}
                    onClick={() => setCategoria(c)}
                    className="kicker h-11 rounded-[var(--pos-r-md)] border px-4 transition-colors"
                    style={{
                      borderColor: activo ? "var(--pos-accent)" : "var(--pos-divider)",
                      background: activo ? "var(--pos-100)" : "transparent",
                      color: activo ? "var(--pos-800)" : "var(--pos-600)",
                    }}
                  >
                    {c}
                  </button>
                );
              })}
            </div>

            <RejillaReferencias referencias={referencias} onElegir={agregar} />
          </section>

          <aside className="min-h-0 p-6 pl-0">
            <Panel
              className="flex h-full flex-col p-4"
              style={{ background: "var(--pos-surface)" }}
            >
              {fase === "cobrando" ? (
                <PanelCobro
                  total={totales.total}
                  onCancelar={() => setFase("vendiendo")}
                  onConfirmar={cobrar}
                />
              ) : (
                <CarritoPanel
                  lineas={lineas}
                  totales={totales}
                  aviso={aviso}
                  onCantidad={cambiarCantidad}
                  onDescuento={setDescontando}
                  onCobrar={() => setFase("cobrando")}
                  cliente={cliente}
                  onAsignarCliente={() => setAsignandoCliente(true)}
                  onQuitarCliente={() => setCliente(null)}
                />
              )}
            </Panel>
          </aside>
        </div>
      </div>

      {asignandoCliente && (
        <DialogoCliente
          onCerrar={() => setAsignandoCliente(false)}
          onAsignar={(c) => {
            setCliente(c);
            setAsignandoCliente(false);
          }}
        />
      )}

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

function SinConfigurar() {
  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <Panel className="max-w-lg p-6" style={{ background: "var(--pos-surface)" }}>
        <p className="titular text-[18px]">Punto de venta sin configurar</p>
        <p className="mt-3 text-[14px]" style={{ color: "var(--pos-700)" }}>
          Faltan las variables del punto de venta. Sin ellas esta caja no sabe
          desde qué tienda vende, y adivinarlo facturaría contra el inventario
          equivocado.
        </p>
        <pre
          className="mt-4 overflow-x-auto rounded-[var(--pos-r-sm)] p-3 font-mono text-[11px]"
          style={{ background: "var(--pos-100)", color: "var(--pos-700)" }}
        >
{`NEXT_PUBLIC_POS_TIENDA=florida
NEXT_PUBLIC_POS_CAJA=florida_caja1
NEXT_PUBLIC_POS_UBICACION=tienda:florida
NEXT_PUBLIC_POS_SESION=<ulid del turno abierto>`}
        </pre>
      </Panel>
    </div>
  );
}

function LupaIcono() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--pos-500)"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}
