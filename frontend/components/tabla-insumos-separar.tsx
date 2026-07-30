"use client";

/**
 * Tabla "Separar estos insumos" — checklist de conteo físico antes de
 * enviar al confeccionista o al proveedor de terminación.
 *
 * - Cada item se marca como contado/completado (se guarda en la hoja de ruta).
 * - Al tener todo marcado, se elige el responsable (BAY / HENRY HURTADO)
 *   y se confirma "Todo OK" — queda con fecha y quién contó.
 *
 * Fetch: /api/produccion/corte/:id/insumos-requeridos?tipo=...
 * Persistencia: POST /api/produccion/rutas/:rutaId/separacion
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useImprimirRemision } from "@/components/boton-imprimir-remision";
import { fmtDateTime } from "@/lib/utils";
import { MEDIDAS_CIERRES, TALLAS_CIERRES } from "@/lib/cierres";
import { CheckCircle, Loader2 } from "lucide-react";

const RESPONSABLES = ["BAY", "HENRY HURTADO"];

interface Item {
  item: string;
  total_requerido: number;
  total_teorico?: number;
  por_talla?: Record<string, number>;  // cierres/marquillas: cantidad por talla
}
interface Respuesta {
  items: Item[];
  cantidad_base?: number;
  margen_pct?: number;
}

export interface SeparacionEstado {
  items?: Record<string, boolean>;
  no_aplica?: string[];  // insumos que esta prenda NO lleva (ej. body sin cierre)
  ok?: boolean;
  responsable?: string | null;
  completado_at?: string | null;
}

// Desglose por talla ordenado (numérico si aplica), solo tallas con cantidad.
function ordenarPorTalla(pt?: Record<string, number>): { t: string; n: number }[] {
  if (!pt) return [];
  return Object.entries(pt)
    .map(([t, n]) => ({ t, n: Number(n) || 0 }))
    .filter((x) => x.n > 0)
    .sort((a, b) => {
      const na = parseFloat(a.t), nb = parseFloat(b.t);
      if (!isNaN(na) && !isNaN(nb)) return na - nb;
      return a.t.localeCompare(b.t);
    });
}

export function TablaInsumosSeparar({ ordenCorteId, tipo, rutaId, remisionId, separacionInicial, className = "" }: {
  ordenCorteId: string;
  tipo: "confeccion" | "terminacion";
  rutaId?: string;
  remisionId?: string;
  separacionInicial?: SeparacionEstado | null;
  className?: string;
}) {
  const qc = useQueryClient();
  const [marcados, setMarcados] = useState<Record<string, boolean>>({});
  // Insumos marcados "No aplica" (la prenda no los lleva; ej. body sin cierre).
  const [noAplica, setNoAplica] = useState<Record<string, boolean>>({});
  const [responsable, setResponsable] = useState("");
  const [confirmado, setConfirmado] = useState<SeparacionEstado | null>(null);
  const [errSep, setErrSep] = useState("");
  const [impresion, setImpresion] = useState<"auto" | "agente" | "manual" | "">("");
  const [fichaEnviada, setFichaEnviada] = useState<boolean | null>(null);
  const [etiquetas, setEtiquetas] = useState<number | null>(null);

  // Mismo camino que el botón Imprimir de las remisiones: iframe oculto +
  // print(). El addEventListener("load") sobre una pestaña nueva no dispara
  // el diálogo de forma fiable con un PDF, por eso se comparte el hook.
  const { imprimir: imprimirPdfRemision } = useImprimirRemision();

  function imprimirRemision() {
    if (!remisionId) return;
    imprimirPdfRemision(remisionId);
  }

  // Cargar estado guardado de la hoja de ruta
  useEffect(() => {
    if (separacionInicial) {
      setMarcados(separacionInicial.items || {});
      const na: Record<string, boolean> = {};
      (separacionInicial.no_aplica || []).forEach((n) => { na[n] = true; });
      setNoAplica(na);
      setResponsable(separacionInicial.responsable || "");
      setConfirmado(separacionInicial.ok ? separacionInicial : null);
    }
  }, [separacionInicial]);

  const q = useQuery<Respuesta>({
    queryKey: ["insumos-separar", tipo, ordenCorteId],
    queryFn: () => api.get(`/api/produccion/corte/${ordenCorteId}/insumos-requeridos?tipo=${tipo}`),
    enabled: !!ordenCorteId,
  });

  const guardar = useMutation({
    mutationFn: (payload: { items: Record<string, boolean>; no_aplica?: string[]; ok: boolean; responsable?: string }) => {
      if (!rutaId) return Promise.reject<{ impresion?: string; ficha_enviada?: { enviado?: boolean }[]; etiquetas_encoladas?: number }>(new Error("sin hoja de ruta"));
      return api.post(`/api/produccion/rutas/${rutaId}/separacion`, { tipo, ...payload }) as Promise<{ impresion?: string; ficha_enviada?: { enviado?: boolean }[]; etiquetas_encoladas?: number }>;
    },
    onSuccess: (d: { impresion?: string; ficha_enviada?: { enviado?: boolean }[]; etiquetas_encoladas?: number }, vars) => {
      setErrSep("");
      if (vars.ok) {
        setConfirmado({ ok: true, responsable: vars.responsable, completado_at: new Date().toISOString() });
        qc.invalidateQueries({ queryKey: ["ruta", ordenCorteId] });
        qc.invalidateQueries({ queryKey: ["ruta-corte", ordenCorteId] });
        // ¿Se avisó al proveedor con la ficha "Aceptar lote"? (flujo nuevo)
        const ficha = d?.ficha_enviada;
        if (Array.isArray(ficha)) setFichaEnviada(ficha.some((f) => f?.enviado));
        // Terminación: stickers (Honeywell) + lavado (SAT) encolados al separar.
        if (typeof d?.etiquetas_encoladas === "number") setEtiquetas(d.etiquetas_encoladas);
        // Impresión de la remisión en la RICOH:
        //  - "agente": el agente local la toma de la cola e imprime en la RICOH
        //    (flujo nuevo con impresión liberada). NO abrir diálogo del navegador.
        //  - "auto": el backend ya la mandó a la impresora (email-to-print)
        //  - "manual": abrimos el PDF con el diálogo de impresión listo
        if (d?.impresion === "agente") {
          setImpresion("agente");
        } else if (d?.impresion === "auto") {
          setImpresion("auto");
        } else if (remisionId) {
          setImpresion("manual");
          imprimirRemision();
        }
      }
    },
    onError: (e: Error) => setErrSep(
      e.message.includes("migracion") ? "Corre la migración de separación en Supabase."
        : `No se pudo guardar: ${e.message}`),
  });

  const naArray = (na: Record<string, boolean>) => Object.keys(na).filter((k) => na[k]);

  function toggleItem(nombre: string) {
    if (confirmado?.ok) return; // ya cerrado
    const next = { ...marcados, [nombre]: !marcados[nombre] };
    // Contar y "no aplica" son excluyentes.
    const na = { ...noAplica };
    if (next[nombre] && na[nombre]) { delete na[nombre]; setNoAplica(na); }
    setMarcados(next);
    if (rutaId) guardar.mutate({ items: next, no_aplica: naArray(na), ok: false });
  }

  function toggleNoAplica(nombre: string) {
    if (confirmado?.ok) return;
    const na = { ...noAplica, [nombre]: !noAplica[nombre] };
    const next = { ...marcados };
    if (na[nombre] && next[nombre]) { next[nombre] = false; setMarcados(next); }
    setNoAplica(na);
    if (rutaId) guardar.mutate({ items: next, no_aplica: naArray(na), ok: false });
  }

  const items = q.data?.items || [];
  const total = items.length;
  // Un insumo queda "resuelto" si se contó O si se marcó que no aplica.
  const contados = items.filter((it) => marcados[it.item] || noAplica[it.item]).length;
  const todoContado = total > 0 && contados === total;
  const label = tipo === "confeccion" ? "confección" : "terminación";

  return (
    <div className={`rounded-sm border border-navy-600/30 bg-navy-600/[0.03] ${className}`}>
      <div className="px-3 py-2 border-b border-navy-600/20 flex items-center justify-between gap-2">
        <p className="text-[0.7rem] uppercase tracking-widest text-navy-600 font-bold">
          Separar estos insumos ({label})
        </p>
        <div className="flex items-center gap-3">
          {total > 0 && !confirmado?.ok && (
            <p className="text-[0.7rem] text-graphite tabular">
              {contados}/{total} contados
            </p>
          )}
          {q.data?.cantidad_base != null && (
            <p className="text-[0.7rem] text-graphite tabular">
              Base: {q.data.cantidad_base} prendas{q.data?.margen_pct ? ` · botones, remaches, lavado y pretineras +${q.data.margen_pct}%` : ""}
            </p>
          )}
        </div>
      </div>

      {confirmado?.ok && (
        <div className="px-3 py-2 bg-teal/[0.08] border-b border-teal/30 flex items-center gap-2 text-xs text-teal flex-wrap">
          <CheckCircle className="h-4 w-4 flex-none" />
          <span className="font-semibold">Separación completa</span>
          · Responsable: <span className="font-bold">{confirmado.responsable}</span>
          {confirmado.completado_at && <span className="text-teal/70">· {fmtDateTime(confirmado.completado_at)}</span>}
          {(impresion === "auto" || impresion === "agente") && <span className="font-semibold">· 🖨 Remisión enviada a la RICOH</span>}
          {impresion === "manual" && <span>· Se abrió la remisión para imprimir</span>}
          {tipo === "terminacion" && (etiquetas ?? 0) > 0 && <span>· 🏷 Stickers + lavado enviados a impresión ({etiquetas})</span>}
          {fichaEnviada === true && <span>· 📲 Ficha enviada al proveedor (Aceptar lote)</span>}
          {fichaEnviada === false && <span className="text-amber-700">· ⚠ No se pudo avisar por WhatsApp — avísale manual</span>}
        </div>
      )}

      {q.isLoading ? (
        <div className="p-3 text-[0.7rem] text-graphite">Calculando…</div>
      ) : q.isError ? (
        <div className="p-3 text-[0.7rem] text-terracotta" role="alert">
          No se pudo calcular la lista de insumos (error de red).{" "}
          <button onClick={() => q.refetch()} className="underline font-semibold">Reintentar</button>
          {" "}— NO envíes el lote sin verificar los insumos.
        </div>
      ) : !q.data || items.length === 0 ? (
        <div className="p-3 text-[0.7rem] text-graphite">
          El precosteo no tiene insumos de {label} con cantidad. Edita el precosteo y agrega cantidades por prenda.
        </div>
      ) : (
        <table className="w-full text-[0.7rem]">
          <thead className="bg-cloud/40 border-b border-border">
            <tr className="text-left text-[0.68rem] uppercase tracking-widest text-graphite">
              <th className="px-3 py-1.5 w-[36px]">OK</th>
              <th className="px-3 py-1.5">Insumo</th>
              <th className="px-3 py-1.5 text-right">Cantidad a separar</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => {
              const na = !!noAplica[it.item];
              const done = !!marcados[it.item] && !na;
              return (
                <tr key={i}
                  className={`border-b border-border/40 ${na ? "bg-graphite/[0.04]" : done ? "bg-teal/[0.05]" : ""}`}>
                  <td className="px-3 py-1.5">
                    <input type="checkbox" checked={done} readOnly
                      onClick={() => toggleItem(it.item)}
                      disabled={!!confirmado?.ok || na}
                      aria-label={`Marcar ${it.item} como contado`}
                      className="h-4 w-4 cursor-pointer rounded border-graphite/40 accent-teal disabled:opacity-40" />
                  </td>
                  <td className={`px-3 py-1.5 ${na ? "text-graphite line-through" : done ? "text-teal font-semibold" : "text-ink-900"}`}>
                    {it.item}
                    {!na && ordenarPorTalla(it.por_talla).length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {ordenarPorTalla(it.por_talla).map(({ t, n }) => (
                          <span key={t} className="rounded-sm bg-navy-600/[0.08] px-1.5 py-0.5 text-[0.6rem] font-semibold text-navy-600 tabular">
                            T{t}: {n}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular font-bold ${na ? "text-graphite/50" : done ? "text-teal" : "text-navy-600"}`}>
                    {na ? "—" : it.total_requerido.toLocaleString("es-CO")}
                    {!confirmado?.ok && (
                      <button
                        onClick={() => toggleNoAplica(it.item)}
                        title="Esta prenda no lleva este insumo (ej. body sin cierre)"
                        className={`ml-2 rounded-sm border px-1.5 py-0.5 text-[0.6rem] font-semibold uppercase tracking-wide ${na ? "border-navy-600 bg-navy-600 text-white" : "border-border bg-card text-graphite hover:bg-cloud"}`}>
                        No aplica
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* Confirmación final: responsable + Todo OK */}
      {rutaId && total > 0 && !confirmado?.ok && (
        <div className="px-3 py-2 border-t border-navy-600/20 flex flex-wrap items-center gap-2">
          <select value={responsable} onChange={(e) => setResponsable(e.target.value)}
            className="rounded-sm border border-border bg-white px-2 py-1.5 text-xs">
            <option value="">Responsable del conteo…</option>
            {RESPONSABLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <button
            onClick={() => guardar.mutate({ items: marcados, no_aplica: naArray(noAplica), ok: true, responsable })}
            disabled={!todoContado || !responsable || guardar.isPending}
            title={!todoContado ? "Marca todos los insumos primero" : !responsable ? "Elige el responsable" : ""}
            className="inline-flex items-center gap-1.5 rounded-sm bg-teal px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:bg-ink-900 disabled:opacity-40">
            {guardar.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle className="h-3 w-3" />}
            Marcar todo OK
          </button>
          {!todoContado && total > 0 && (
            <span className="text-[0.7rem] text-graphite">Faltan {total - contados} por contar</span>
          )}
        </div>
      )}

      {errSep && (
        <p role="alert" className="px-3 py-1.5 text-[0.65rem] text-terracotta border-t border-terracotta/30">{errSep}</p>
      )}

      {/* Medidas (cm) del cierre por talla según el tiro — referencia.
          La CANTIDAD por talla ya va inline en la fila del insumo. Solo si la
          prenda lleva cierre (no en body sin cierre ni si se marcó "No aplica"). */}
      {tipo === "confeccion" && (() => {
        const cierreItem = items.find((it) => /CIERRE|CREMALLERA/i.test(it.item));
        if (!cierreItem || noAplica[cierreItem.item]) return null;
        return (
        <div className="border-t border-navy-600/20">
          <p className="px-3 pt-2 text-[0.68rem] uppercase tracking-widest text-graphite font-bold">
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
        );
      })()}
    </div>
  );
}
