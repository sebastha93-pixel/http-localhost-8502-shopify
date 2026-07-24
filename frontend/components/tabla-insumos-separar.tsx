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
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { fmtDateTime } from "@/lib/utils";
import { MEDIDAS_CIERRES, TALLAS_CIERRES } from "@/lib/cierres";
import { CheckCircle, Loader2 } from "lucide-react";

const RESPONSABLES = ["BAY", "HENRY HURTADO"];

interface Item {
  item: string;
  total_requerido: number;
  total_teorico?: number;
}
interface Respuesta {
  items: Item[];
  cantidad_base?: number;
  margen_pct?: number;
}

export interface SeparacionEstado {
  items?: Record<string, boolean>;
  ok?: boolean;
  responsable?: string | null;
  completado_at?: string | null;
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
  const [responsable, setResponsable] = useState("");
  const [confirmado, setConfirmado] = useState<SeparacionEstado | null>(null);
  const [errSep, setErrSep] = useState("");
  const [impresion, setImpresion] = useState<"auto" | "agente" | "manual" | "">("");
  const [fichaEnviada, setFichaEnviada] = useState<boolean | null>(null);
  const [etiquetas, setEtiquetas] = useState<number | null>(null);

  async function imprimirRemision() {
    if (!remisionId) return;
    try {
      const r = await fetch(`${API_BASE}/api/produccion/remisiones/${remisionId}/pdf`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!r.ok) return;
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const win = window.open(url, "_blank");
      // Disparar el diálogo de impresión apenas cargue el PDF
      if (win) win.addEventListener("load", () => { try { win.print(); } catch { /* noop */ } });
    } catch { /* la remisión sigue imprimible desde el botón Imprimir */ }
  }

  // Cargar estado guardado de la hoja de ruta
  useEffect(() => {
    if (separacionInicial) {
      setMarcados(separacionInicial.items || {});
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
    mutationFn: (payload: { items: Record<string, boolean>; ok: boolean; responsable?: string }) => {
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

  function toggleItem(nombre: string) {
    if (confirmado?.ok) return; // ya cerrado
    const next = { ...marcados, [nombre]: !marcados[nombre] };
    setMarcados(next);
    if (rutaId) guardar.mutate({ items: next, ok: false });
  }

  const items = q.data?.items || [];
  const total = items.length;
  const contados = items.filter((it) => marcados[it.item]).length;
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
              const done = !!marcados[it.item];
              return (
                <tr key={i}
                  onClick={() => toggleItem(it.item)}
                  className={`border-b border-border/40 cursor-pointer ${done ? "bg-teal/[0.05]" : "hover:bg-cloud/40"} ${confirmado?.ok ? "cursor-default" : ""}`}>
                  <td className="px-3 py-1.5">
                    <input type="checkbox" checked={done} readOnly
                      disabled={!!confirmado?.ok}
                      aria-label={`Marcar ${it.item} como contado`}
                      className="h-4 w-4 cursor-pointer rounded border-graphite/40 accent-teal" />
                  </td>
                  <td className={`px-3 py-1.5 ${done ? "text-teal font-semibold" : "text-ink-900"}`}>
                    {it.item}
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular font-bold ${done ? "text-teal" : "text-navy-600"}`}>
                    {it.total_requerido.toLocaleString("es-CO")}
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
            onClick={() => guardar.mutate({ items: marcados, ok: true, responsable })}
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

      {/* Regla MALE'DENIM: medidas de cierres por talla según tipo de tiro */}
      {tipo === "confeccion" && (
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
      )}
    </div>
  );
}
