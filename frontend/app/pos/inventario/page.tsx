"use client";

/**
 * Inventario — vista 6 del handoff.
 *
 * Responde la pregunta que hoy obliga a la cajera a dejar el mostrador:
 * «¿tienes la 10 en azul?».
 *
 * DOS COSAS QUE EL PROTOTIPO NO PODÍA SABER:
 *
 * **Las columnas no son T24…T32.** Ese es tallaje de jean americano; los SKU
 * reales de MALE parsean a 4, 6, 8, 10, 12. Las columnas se pintan con lo que
 * devuelve el servidor, así que el día que entre una talla nueva aparece sola.
 *
 * **El aviso tiene dos orígenes.** El total de la referencia contra el umbral
 * de la tienda —como el prototipo— y, además, una talla concreta que alguien
 * marcó con su propio mínimo. Lo segundo es lo que el total no puede ver: una
 * referencia con 40 unidades a la que le falta justamente la 10.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Rail } from "@/components/pos/rail";
import { ConLaCaja } from "@/components/pos/elegir-caja";
import { formatear } from "@/lib/pos/dinero";
import { consultarInventario, type FilaInventario, type Inventario } from "@/lib/pos/api";

// La tienda y la ubicación salen de la caja del equipo, no de variables.
export default function PaginaInventario() {
  return (
    <ConLaCaja>
      {(c) => (
        <PantallaInventario TIENDA={c.tienda_id} UBICACION={c.ubicacion_id ?? ""} />
      )}
    </ConLaCaja>
  );
}

function PantallaInventario({ TIENDA, UBICACION }: {
  TIENDA: string;
  UBICACION: string;
}) {
  const { user } = useAuth();
  const [datos, setDatos] = useState<Inventario | null>(null);
  const [consulta, setConsulta] = useState("");
  const [categoria, setCategoria] = useState("Todo");
  const [soloBajos, setSoloBajos] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const buscador = useRef<HTMLInputElement>(null);

  // El filtro se aplica con retraso: teclear «pantalón» son ocho consultas si
  // cada letra dispara una, y la última en volver puede no ser la última
  // escrita — la tabla parpadearía con resultados viejos.
  useEffect(() => {
    let vivo = true;
    const t = setTimeout(async () => {
      try {
        const d = await consultarInventario({
          ubicacionId: UBICACION, tiendaId: TIENDA,
          q: consulta, categoria, soloBajos,
        });
        if (vivo) { setDatos(d); setError(null); }
      } catch (e) {
        if (vivo) setError(e instanceof Error ? e.message : "No se pudo consultar el stock.");
      } finally {
        if (vivo) setCargando(false);
      }
    }, consulta ? 250 : 0);
    return () => { vivo = false; clearTimeout(t); };
  }, [consulta, categoria, soloBajos, TIENDA, UBICACION]);

  useEffect(() => { buscador.current?.focus(); }, []);

  const columnas = datos?.columnas_talla ?? [];

  return (
    <div className="pos-raiz flex h-screen overflow-hidden">
      <Rail cajera={user?.nombre || user?.email || ""} />

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden p-6">
        <header className="mb-4 flex flex-wrap items-center gap-3">
          <input
            ref={buscador}
            value={consulta}
            onChange={(e) => setConsulta(e.target.value)}
            placeholder="Filtrar por nombre o referencia"
            className="h-11 w-[320px] pos-input px-3 text-[14px] text-[var(--pos-text)]"
          />
          {datos && (
            <>
              <Etiqueta>{datos.referencias} referencias</Etiqueta>
              {/* `compacto` es la salida deliberada del suelo de 44px: esto es
                  una píldora de 24 que además filtra. Va marcada porque el
                  sistema obliga a decidirlo, no a saltárselo por descuido. */}
              <button
                onClick={() => setSoloBajos((v) => !v)}
                title="Lo que hay que reponer"
                aria-pressed={soloBajos}
                className={`compacto pos-tag transition-colors ${
                  soloBajos ? "pos-tag-acento" : "pos-tag-neutro"
                }`}
              >
                {datos.con_stock_bajo} con stock bajo
              </button>
            </>
          )}

          <div className="ml-auto flex gap-1.5">
            {["Todo", ...(datos?.categorias ?? [])].map((c) => (
              // Mismo chip que en Venta: píldora, tinte + borde de acento
              // cuando está activo. Eran dos dibujos distintos para el mismo
              // gesto en dos pantallas contiguas.
              <button
                key={c}
                onClick={() => setCategoria(c)}
                aria-pressed={categoria === c}
                className="h-11 rounded-[var(--pos-r-pill)] border px-4 text-[14px] font-medium transition-colors"
                style={{
                  borderColor:
                    categoria === c ? "var(--pos-accent)" : "var(--pos-divider)",
                  background:
                    categoria === c ? "var(--pos-100)" : "var(--pos-surface)",
                  color: categoria === c ? "var(--pos-800)" : "var(--pos-700)",
                }}
              >
                {c}
              </button>
            ))}
          </div>
        </header>

        {error && (
          <p className="border-l-2 border-[var(--pos-800)] rounded-[var(--pos-r-sm)] bg-[var(--pos-800)]/10 py-3 pl-4 text-[13px] text-[var(--pos-900)]">
            {error}
          </p>
        )}

        {/* La tabla scrollea DENTRO de su caja. Sin `min-w-0` en el padre, una
            tienda con doce tallas empuja el rail fuera de la pantalla. */}
        <div className="blueprint min-h-0 flex-1 overflow-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead className="sticky top-0 z-10 bg-[var(--pos-100)]">
              <tr className="text-left">
                <Th>Ref</Th>
                <Th>Producto</Th>
                <Th>Categoría</Th>
                <Th alineado="right">Precio</Th>
                {columnas.map((t) => (
                  <Th key={t} alineado="center" estrecha>
                    T{t}
                  </Th>
                ))}
                <Th alineado="center">Total</Th>
                <Th alineado="center">Otras</Th>
                <Th>Estado</Th>
              </tr>
            </thead>
            <tbody>
              {datos?.filas.map((f) => (
                <Fila key={f.referencia} fila={f} columnas={columnas} />
              ))}
            </tbody>
          </table>

          {!cargando && datos?.filas.length === 0 && (
            <p className="p-8 text-center text-[13px] text-[var(--pos-600)]">
              {soloBajos
                ? "Nada por reponer con los mínimos de hoy."
                : "Ninguna referencia coincide."}
            </p>
          )}
          {cargando && (
            <p className="p-8 text-center text-[13px] text-[var(--pos-600)]">
              Consultando…
            </p>
          )}
        </div>

        {datos && (
          <p className="mt-2 tabular text-[12px] text-[var(--pos-600)]">
            Avisa cuando el total de la referencia baja de {datos.umbral_tienda}{" "}
            unidades, y cuando una talla con mínimo propio cae por debajo del
            suyo. Lo apartado por otra caja ya está descontado.
          </p>
        )}
      </main>
    </div>
  );
}

function Fila({ fila, columnas }: { fila: FilaInventario; columnas: string[] }) {
  const porTalla = useMemo(
    () => Object.fromEntries(fila.tallas.map((t) => [t.talla, t])),
    [fila.tallas],
  );

  return (
    <tr className="border-t border-[var(--pos-divider)]/70 hover:bg-[var(--pos-100)]/60">
      <Td className="tabular text-[12px]">{fila.referencia}</Td>
      <Td className="font-medium">
        {fila.nombre}
        <span className="ml-1.5 font-normal text-[var(--pos-600)]">{fila.color}</span>
      </Td>
      <Td className="text-[var(--pos-700)]">{fila.categoria}</Td>
      <Td alineado="right" className="tabular">
        {formatear(fila.precio_con_iva_centavos)}
      </Td>

      {columnas.map((t) => {
        const celda = porTalla[t];
        if (!celda) {
          // Esta referencia no se fabrica en esta talla. Un 0 diría «se acabó»,
          // que es una respuesta distinta y manda a pedir lo que no existe.
          return (
            <Td key={t} alineado="center" className="text-[var(--pos-muted)]">
              ·
            </Td>
          );
        }
        // Un NEGATIVO no es «poco stock»: es el sistema y el cajón
        // contradiciéndose. La tienda permite vender en negativo para no
        // frenar el mostrador, pero pintarlo como un número más lo entierra —
        // y es justo lo que hay que ajustar antes de pedir mercancía.
        const negativo = celda.disponible < 0;
        return (
          <Td
            key={t}
            alineado="center"
            className={`tabular ${
              negativo
                ? "font-semibold text-[var(--pos-accent)]"
                : celda.disponible === 0
                  ? "text-[var(--pos-muted)]"
                  : celda.es_bajo
                    ? "font-semibold text-[var(--pos-900)]"
                    : ""
            }`}
          >
            <span
              title={
                negativo
                  ? "Se vendió más de lo que el sistema tenía. Hay que ajustar el inventario."
                  : celda.es_bajo
                    ? `Por debajo del mínimo (${celda.minimo})`
                    : undefined
              }
              className={
                negativo
                  ? "border-b-2 border-[var(--pos-accent)] px-1"
                  : celda.es_bajo
                    ? "bg-[var(--pos-800)]/12 px-1.5 py-0.5"
                    : ""
              }
            >
              {celda.disponible}
            </span>
          </Td>
        );
      })}

      <Td alineado="center" className="tabular font-semibold">
        {fila.total}
      </Td>
      <Td alineado="center" className="tabular text-[var(--pos-600)]">
        {/* Traslados quedan fuera de esta fase: esto informa, no promete. */}
        {fila.en_otras_ubicaciones || "—"}
      </Td>
      <Td>
        <Estado estado={fila.estado} />
      </Td>
    </tr>
  );
}

function Estado({ estado }: { estado: "ok" | "bajo" | "agotado" }) {
  const estilo = {
    ok: "border-[var(--pos-divider)] text-[var(--pos-600)]",
    bajo: "border-[var(--pos-800)]/30 rounded-[var(--pos-r-sm)] bg-[var(--pos-800)]/10 text-[var(--pos-900)]",
    agotado: "border-[var(--pos-accent)] bg-[var(--pos-accent)] text-white",
  }[estado];
  const texto = { ok: "OK", bajo: "Stock bajo", agotado: "Agotado" }[estado];

  return (
    <span
      className={`inline-block whitespace-nowrap border px-2 py-0.5 text-[12px] ${estilo}`}
    >
      {texto}
    </span>
  );
}

function Etiqueta({ children }: { children: React.ReactNode }) {
  return (
    <span className="pos-tag pos-tag-neutro">{children}</span>
  );
}

function Th({
  children,
  alineado = "left",
  estrecha,
}: {
  children: React.ReactNode;
  alineado?: "left" | "right" | "center";
  estrecha?: boolean;
}) {
  return (
    <th
      className={`whitespace-nowrap border-b border-[var(--pos-divider)] px-3 py-2.5 text-[12px] font-medium uppercase text-[var(--pos-600)] ${
        estrecha ? "w-[52px]" : ""
      }`}
      style={{ textAlign: alineado }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  alineado = "left",
  className = "",
}: {
  children: React.ReactNode;
  alineado?: "left" | "right" | "center";
  className?: string;
}) {
  return (
    <td
      className={`whitespace-nowrap px-3 py-2.5 ${className}`}
      style={{ textAlign: alineado }}
    >
      {children}
    </td>
  );
}
