"use client";

/**
 * Tabla "Separar estos insumos" — se muestra al admin antes de enviar
 * WhatsApp al confeccionista o al proveedor de terminación.
 *
 * Fetch: /api/produccion/corte/:id/insumos-requeridos?tipo=confeccion|terminacion
 *
 * Uso:
 *   <TablaInsumosSeparar ordenCorteId={id} tipo="confeccion" />
 *   <TablaInsumosSeparar ordenCorteId={id} tipo="terminacion" />
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { MEDIDAS_CIERRES, TALLAS_CIERRES } from "@/lib/cierres";

interface Item {
  item: string;
  total_requerido: number;
}
interface Respuesta {
  items: Item[];
  cantidad_base?: number;
}

export function TablaInsumosSeparar({ ordenCorteId, tipo, className = "" }: {
  ordenCorteId: string;
  tipo: "confeccion" | "terminacion";
  className?: string;
}) {
  const q = useQuery<Respuesta>({
    queryKey: ["insumos-separar", tipo, ordenCorteId],
    queryFn: () => api.get(`/api/produccion/corte/${ordenCorteId}/insumos-requeridos?tipo=${tipo}`),
    enabled: !!ordenCorteId,
  });

  const label = tipo === "confeccion" ? "confección" : "terminación";

  return (
    <div className={`rounded-sm border border-navy-600/30 bg-navy-600/[0.03] ${className}`}>
      <div className="px-3 py-2 border-b border-navy-600/20 flex items-center justify-between">
        <p className="text-[0.6rem] uppercase tracking-widest text-navy-600 font-bold">
          Separar estos insumos ({label})
        </p>
        {q.data?.cantidad_base != null && (
          <p className="text-[0.6rem] text-graphite tabular">
            Base: {q.data.cantidad_base} prendas
          </p>
        )}
      </div>

      {q.isLoading ? (
        <div className="p-3 text-[0.7rem] text-graphite">Calculando…</div>
      ) : q.isError ? (
        <div className="p-3 text-[0.7rem] text-terracotta" role="alert">
          No se pudo calcular la lista de insumos (error de red).{" "}
          <button onClick={() => q.refetch()} className="underline font-semibold">Reintentar</button>
          {" "}— NO envíes el lote sin verificar los insumos.
        </div>
      ) : !q.data || q.data.items.length === 0 ? (
        <div className="p-3 text-[0.7rem] text-graphite">
          El precosteo no tiene insumos de {label} con cantidad. Edita el precosteo y agrega cantidades por prenda.
        </div>
      ) : (
        <table className="w-full text-[0.7rem]">
          <thead className="bg-cloud/40 border-b border-border">
            <tr className="text-left text-[0.55rem] uppercase tracking-widest text-graphite">
              <th className="px-3 py-1.5">Insumo</th>
              <th className="px-3 py-1.5 text-right">Cantidad a separar</th>
            </tr>
          </thead>
          <tbody>
            {q.data.items.map((it, i) => (
              <tr key={i} className="border-b border-border/40">
                <td className="px-3 py-1.5 text-ink-900">{it.item}</td>
                <td className="px-3 py-1.5 text-right tabular font-bold text-navy-600">
                  {it.total_requerido.toLocaleString("es-CO")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Regla MALE'DENIM: medidas de cierres por talla según tipo de tiro */}
      {tipo === "confeccion" && (
        <div className="border-t border-navy-600/20">
          <p className="px-3 pt-2 text-[0.55rem] uppercase tracking-widest text-graphite font-bold">
            Medidas cierres por talla (cm)
          </p>
          <table className="w-full text-[0.65rem] mt-1">
            <thead>
              <tr className="text-left text-[0.5rem] uppercase tracking-widest text-graphite border-b border-border/60">
                <th className="px-3 py-1">Tiro</th>
                {TALLAS_CIERRES.map((t) => (
                  <th key={t} className="px-1 py-1 text-center">T{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(MEDIDAS_CIERRES).map(([tiro, medidas]) => (
                <tr key={tiro} className="border-b border-border/30 last:border-0">
                  <td className="px-3 py-1 font-semibold text-ink-900 whitespace-nowrap">{tiro}</td>
                  {TALLAS_CIERRES.map((t) => (
                    <td key={t} className="px-1 py-1 text-center tabular text-graphite">
                      {medidas[t]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
