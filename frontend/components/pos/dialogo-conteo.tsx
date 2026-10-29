"use client";

/**
 * Cargar el conteo de la tienda en el POS (29-oct-2026: Siigo no lo dejaba).
 *
 * DOS PASOS A PROPÓSITO: primero se REVISA (el servidor dice qué cambiaría,
 * sin tocar nada) y sólo después se carga. Un conteo completo deja en cero lo
 * que no aparece, y así quedaron las bolsas de Florida el 28-oct: lo que no
 * es prenda y quedaría en cero sale en rojo, antes de confirmar.
 */
import { useMemo, useState } from "react";
import { Panel } from "@/components/pos/marco";
import { leerConteo } from "@/lib/pos/conteo";
import { nuevoUlid } from "@/lib/pos/ulid";
import {
  cargarConteo, ensayarConteo, type EnsayoConteo,
} from "@/lib/pos/api";

export function DialogoConteo({ tienda, onCerrar, onCargado }: {
  tienda: string;
  onCerrar: () => void;
  onCargado: () => void;
}) {
  const [texto, setTexto] = useState("");
  const [completo, setCompleto] = useState(true);
  const [ensayo, setEnsayo] = useState<EnsayoConteo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  // Uno por ventana: si la red se corta al cargar, reintentar no lo aplica dos veces.
  const [conteoId] = useState(() => nuevoUlid());
  const lectura = useMemo(() => leerConteo(texto), [texto]);

  async function revisar() {
    setOcupado(true); setError(null);
    try {
      setEnsayo(await ensayarConteo({ tienda_id: tienda, lineas: lectura.lineas, completo }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo revisar el conteo.");
    } finally {
      setOcupado(false);
    }
  }

  async function cargar() {
    setOcupado(true); setError(null);
    try {
      await cargarConteo({ conteo_id: conteoId, tienda_id: tienda,
                           lineas: lectura.lineas, completo });
      onCargado();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el conteo.");
      setOcupado(false);
    }
  }

  async function desdeArchivo(f: File | undefined) {
    if (!f) return;
    setTexto(await f.text());
    setEnsayo(null);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center pos-backdrop p-4">
      <Panel role="dialog" aria-modal="true" aria-label="Cargar conteo"
             className="pos-dialogo flex max-h-[90vh] w-full max-w-[720px] flex-col p-6">
        <h2 className="titular text-[15px] font-semibold">CARGAR CONTEO DE LA TIENDA</h2>
        <p className="mt-1 text-[13px]" style={{ color: "var(--pos-600)" }}>
          En el Excel del conteo selecciona las columnas de código y cantidad, cópialas
          y pégalas aquí. También sirve un archivo CSV.
        </p>

        {!ensayo ? (
          <>
            <textarea
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder={"26602-1T6\t3\n95613-1T12\t6\n5353\t60"}
              className="pos-input mt-4 h-48 w-full p-3 font-mono text-[13px]"
            />
            <div className="mt-3 flex flex-wrap items-center gap-4 text-[13px]">
              <label className="cursor-pointer underline">
                Subir archivo CSV
                <input type="file" accept=".csv,.txt,text/csv,text/plain" className="hidden"
                       onChange={(e) => desdeArchivo(e.target.files?.[0])} />
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={completo}
                       onChange={(e) => setCompleto(e.target.checked)} />
                Conteo completo: lo que no aparezca queda en 0
              </label>
              <span style={{ color: "var(--pos-600)" }}>
                {lectura.lineas.length} filas leídas
                {lectura.saltadas > 0 && ` · ${lectura.saltadas} sin cantidad (se ignoran)`}
              </span>
            </div>
          </>
        ) : (
          <Resumen ensayo={ensayo} completo={completo} />
        )}

        {error && (
          <p role="alert" className="mt-3 text-[13px] text-[var(--pos-accent)]">{error}</p>
        )}

        <div className="mt-5 flex justify-end gap-3">
          <button onClick={ensayo ? () => setEnsayo(null) : onCerrar} disabled={ocupado}
                  className="pos-btn pos-btn-sec h-11 px-4 text-[14px]">
            {ensayo ? "Volver" : "Cancelar"}
          </button>
          {!ensayo ? (
            <button onClick={revisar} disabled={ocupado || lectura.lineas.length === 0}
                    className="pos-btn pos-btn-primario h-11 px-5 text-[14px] font-semibold">
              {ocupado ? "Revisando…" : "Revisar"}
            </button>
          ) : (
            <button onClick={cargar} disabled={ocupado}
                    className="pos-btn pos-btn-primario h-11 px-5 text-[14px] font-semibold">
              {ocupado ? "Cargando…" : "Cargar conteo"}
            </button>
          )}
        </div>
      </Panel>
    </div>
  );
}

function Resumen({ ensayo: e, completo }: { ensayo: EnsayoConteo; completo: boolean }) {
  return (
    <div className="mt-4 min-h-0 flex-1 overflow-y-auto text-[14px]">
      <p>
        <strong>{e.referencias_contadas}</strong> referencias contadas ·{" "}
        <strong>{e.unidades_contadas}</strong> unidades. La tienda pasa de{" "}
        <strong>{e.unidades_antes}</strong> a <strong>{e.unidades_despues}</strong> unidades.
      </p>
      {e.no_prendas_a_cero.length > 0 && (
        <div role="alert" className="mt-3 border-l-4 border-[var(--pos-accent)] bg-[var(--pos-100)] p-3">
          <strong>Ojo: esto no es ropa y quedaría en 0.</strong> Si sí lo tienen, agrégalo al
          conteo antes de cargar:
          <ul className="mt-1 list-disc pl-5">
            {e.no_prendas_a_cero.map((f) => (
              <li key={f.sku}>{f.sku} {f.nombre} (hay {f.antes})</li>
            ))}
          </ul>
        </div>
      )}
      {e.desconocidos.length > 0 && (
        <p className="mt-3" style={{ color: "var(--pos-700)" }}>
          <strong>{e.desconocidos.length} códigos no existen en el catálogo y no se cargan:</strong>{" "}
          {e.desconocidos.slice(0, 30).join(", ")}{e.desconocidos.length > 30 && "…"}
        </p>
      )}
      {completo && e.a_cero.length > 0 && (
        <p className="mt-3">{e.a_cero.length} referencias que no aparecen en el conteo quedan en 0.</p>
      )}
      <table className="mt-3 w-full text-[13px]">
        <thead>
          <tr className="text-left" style={{ color: "var(--pos-600)" }}>
            <th className="py-1">Código</th><th>Prenda</th>
            <th className="text-right">Había</th><th className="text-right">Contado</th>
          </tr>
        </thead>
        <tbody>
          {e.cambios.slice(0, 300).map((f) => (
            <tr key={f.sku} className="border-t border-[var(--pos-divider)]">
              <td className="py-1 font-mono">{f.sku}</td>
              <td className="truncate pr-2">{f.nombre}</td>
              <td className="text-right">{f.antes}</td>
              <td className="text-right font-semibold">{f.contado}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {e.cambios.length === 0 && <p className="mt-2">No hay diferencias con lo que tiene el POS.</p>}
      {e.cambios.length > 300 && <p className="mt-2">…y {e.cambios.length - 300} cambios más.</p>}
    </div>
  );
}
