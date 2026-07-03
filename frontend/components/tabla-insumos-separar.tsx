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
    </div>
  );
}
