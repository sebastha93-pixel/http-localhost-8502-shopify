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
import { corregirEscaneo } from "@/lib/pos/escaneo";
import {
  conteoParaSiigo, consultarInventario, listarConteos, marcarConteoEnSiigo,
  type ConteoGuardado, type FilaInventario, type Inventario,
} from "@/lib/pos/api";
import { DialogoConteo } from "@/components/pos/dialogo-conteo";

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
  // Conteo cargado aquí mientras Siigo no deja cargarlo (29-oct-2026).
  const [conteoAbierto, setConteoAbierto] = useState(false);
  const [pendiente, setPendiente] = useState<ConteoGuardado | null>(null);
  const [recarga, setRecarga] = useState(0);
  const [avisoConteo, setAvisoConteo] = useState<string | null>(null);

  useEffect(() => {
    listarConteos(TIENDA)
      .then((l) => setPendiente(l.find((c) => c.estado === "pendiente_siigo") ?? null))
      .catch(() => setPendiente(null));
  }, [TIENDA, recarga]);

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
  }, [consulta, categoria, soloBajos, TIENDA, UBICACION, recarga]);

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
            onChange={(e) => setConsulta(corregirEscaneo(e.target.value))}
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

          <button
            onClick={() => setConteoAbierto(true)}
            title="Cuando Siigo no deja cargar el conteo de la tienda"
            className="h-11 border border-[var(--pos-divider)] bg-[var(--pos-surface)] px-4 text-[14px] font-medium text-[var(--pos-700)] hover:bg-[var(--pos-100)]"
          >
            Cargar conteo
          </button>

          {datos && datos.filas.length > 0 && (
            <button
              onClick={() => descargar(datos, TIENDA)}
              title="Descarga lo que está en pantalla, con los filtros puestos"
              className="h-11 border border-[var(--pos-divider)] bg-[var(--pos-surface)] px-4 text-[14px] font-medium text-[var(--pos-700)] hover:bg-[var(--pos-100)]"
            >
              Descargar
            </button>
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

        {pendiente && (
          <div role="status" className="mb-4 flex flex-wrap items-center gap-3 border-l-4 border-[var(--pos-accent)] bg-[var(--pos-100)] px-4 py-3 text-[14px]">
            <span>
              <strong>Conteo pendiente de cargar en Siigo</strong> (
              {new Date(pendiente.creado_en).toLocaleString("es-CO", { timeZone: "America/Bogota", dateStyle: "short", timeStyle: "short" })}
              ). Mientras tanto Siigo no le cambia el inventario a esta tienda.
            </span>
            <button
              className="pos-btn pos-btn-sec h-9 px-3 text-[13px]"
              onClick={async () => {
                try { await descargarParaSiigo(pendiente.id, TIENDA); }
                catch (e) { setAvisoConteo(e instanceof Error ? e.message : "No se pudo descargar."); }
              }}
            >
              Descargar para Siigo
            </button>
            <button
              className="pos-btn pos-btn-primario h-9 px-3 text-[13px]"
              onClick={async () => {
                if (!confirm("¿Ya quedó cargado en Siigo el archivo descargado? Desde ahora Siigo vuelve a mandar en el inventario de esta tienda.")) return;
                try { await marcarConteoEnSiigo(pendiente.id); setRecarga((n) => n + 1); }
                catch (e) { setAvisoConteo(e instanceof Error ? e.message : "No se pudo marcar."); }
              }}
            >
              Ya está en Siigo
            </button>
            {avisoConteo && <span role="alert">{avisoConteo}</span>}
          </div>
        )}

        {conteoAbierto && (
          <DialogoConteo
            tienda={TIENDA}
            onCerrar={() => setConteoAbierto(false)}
            onCargado={() => { setConteoAbierto(false); setRecarga((n) => n + 1); }}
          />
        )}

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


/**
 * El inventario que está en pantalla, a un archivo que Excel abre de una.
 *
 * CSV con punto y coma y con BOM: el Excel en español separa por «;» y, sin
 * la marca de UTF-8, convierte las tildes en jeroglíficos. Sale lo que se ve
 * —con el filtro y la categoría puestos—, una fila por referencia y una
 * columna por talla.
 */
/** Lo que hay que dejar en la bodega de Siigo: el inventario de AHORA, no el
 *  conteo (lo vendido después ya bajó Siigo con su factura). */
async function descargarParaSiigo(conteoId: string, tienda: string): Promise<void> {
  const d = await conteoParaSiigo(conteoId);
  const lineas = [["Código", "Nombre", "Cantidad", "Bodega Siigo"],
                  ...d.filas.map((f) => [f.sku, f.nombre, f.cantidad, d.bodega_siigo ?? ""])];
  const celda = (v: string | number) => {
    const t = String(v ?? "");
    return /[";\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const csv = "\uFEFF" + lineas.map((l) => l.map(celda).join(";")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  const hoy = new Date().toLocaleDateString("sv-SE", { timeZone: "America/Bogota" });
  a.href = url;
  a.download = `para-siigo-${tienda}-${hoy}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function descargar(datos: Inventario, tienda: string): void {
  const celda = (v: string | number) => {
    const t = String(v ?? "");
    return /[";\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const tallas = datos.columnas_talla;
  const lineas = [
    ["Referencia", "Nombre", "Color", "Categoría", "Precio con IVA",
     ...tallas.map((t) => `Talla ${t}`), "Total", "En otras tiendas", "Estado"],
    ...datos.filas.map((f) => {
      const por = new Map(f.tallas.map((c) => [c.talla, c.disponible]));
      return [f.referencia, f.nombre, f.color, f.categoria,
              Math.round(f.precio_con_iva_centavos / 100),
              ...tallas.map((t) => por.get(t) ?? ""),
              f.total, f.en_otras_ubicaciones, f.estado];
    }),
  ];
  const csv = "\uFEFF" + lineas.map((l) => l.map(celda).join(";")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  const hoy = new Date().toLocaleDateString("sv-SE", { timeZone: "America/Bogota" });
  a.href = url;
  a.download = `inventario-${tienda}-${hoy}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
