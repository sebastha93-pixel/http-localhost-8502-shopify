"use client";

import { useMemo, useState } from "react";
import { Pedido, NivelRiesgo } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatMoneyShort } from "@/lib/utils";
import { Search, ExternalLink, Phone, MessageCircle } from "lucide-react";
import { PedidoDetalle } from "@/components/pedido-detalle";

const NIVELES: NivelRiesgo[] = ["CRITICO", "RIESGO", "NORMAL", "VENCIDO", "RESUELTO"];

type ColumnKey =
  | "select" | "nivel" | "orden" | "cliente" | "telefono" | "ciudad" | "zona"
  | "dias" | "valor" | "estado" | "tipo" | "novedad" | "link" | "action";

interface Props {
  pedidos: Pedido[];
  showNivelFilter?: boolean;
  showTipoFilter?: boolean;
  emptyMessage?: string;
  limit?: number;
  columns?: ColumnKey[];
  /** Habilita checkboxes y barra de acciones bulk */
  selectable?: boolean;
  /** Acción render-prop por fila (ej. botón Autorizar despacho) */
  renderAction?: (p: Pedido) => React.ReactNode;
}

const TIPO_FILTROS = ["Todos", "Contraentrega", "Prepago"] as const;
type TipoFiltro = (typeof TIPO_FILTROS)[number];

const DEFAULT_COLS: ColumnKey[] = ["nivel", "orden", "cliente", "telefono", "ciudad", "zona", "dias", "valor", "estado", "tipo", "link"];

export function PedidosTable({
  pedidos,
  showNivelFilter = true,
  showTipoFilter = true,
  emptyMessage = "Sin resultados con los filtros aplicados",
  limit = 200,
  columns = DEFAULT_COLS,
  selectable = false,
  renderAction,
}: Props) {
  const [q, setQ] = useState("");
  const [nivel, setNivel] = useState<NivelRiesgo | "Todos">("Todos");
  const [tipo, setTipo] = useState<TipoFiltro>("Todos");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Pedido | null>(null);

  // Auto-añadir columnas según props
  const cols = useMemo<ColumnKey[]>(() => {
    const c = [...columns];
    if (selectable && !c.includes("select")) c.unshift("select");
    if (renderAction && !c.includes("action")) c.push("action");
    return c;
  }, [columns, selectable, renderAction]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    return pedidos.filter((p) => {
      if (showNivelFilter && nivel !== "Todos" && p.nivel !== nivel) return false;
      if (showTipoFilter && tipo !== "Todos" && p.tipo_recaudo !== tipo) return false;
      if (!term) return true;
      return (
        p.orden_tienda?.toLowerCase().includes(term) ||
        p.orden_melonn?.toLowerCase().includes(term) ||
        p.nombre_comprador?.toLowerCase().includes(term) ||
        p.ciudad_destino?.toLowerCase().includes(term) ||
        p.telefono_comprador?.toLowerCase().includes(term)
      );
    });
  }, [pedidos, q, nivel, tipo, showNivelFilter, showTipoFilter]);

  const has = (c: ColumnKey) => cols.includes(c);

  const toggleOne = (orden: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(orden) ? next.delete(orden) : next.add(orden);
      return next;
    });
  };
  const toggleAll = () => {
    if (selected.size === filtered.length) setSelected(new Set());
    else setSelected(new Set(filtered.slice(0, limit).map((p) => p.orden_melonn || p.orden_tienda)));
  };

  const abrirGuiasSeleccionadas = () => {
    filtered
      .filter((p) => selected.has(p.orden_melonn || p.orden_tienda) && p.link_guia)
      .forEach((p) => window.open(p.link_guia as string, "_blank"));
  };

  return (
    <div className="space-y-4">
      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar por orden, cliente, ciudad o teléfono..."
            className="w-full rounded-md border border-border bg-white pl-9 pr-3 py-2 text-sm text-ink placeholder:text-graphite/60 focus:outline-none focus:ring-2 focus:ring-steel"
          />
        </div>
        {showNivelFilter && (
          <Select label="Nivel" value={nivel} onChange={(v) => setNivel(v as NivelRiesgo | "Todos")} options={["Todos", ...NIVELES]} />
        )}
        {showTipoFilter && (
          <Select label="Tipo" value={tipo} onChange={(v) => setTipo(v as TipoFiltro)} options={TIPO_FILTROS as unknown as string[]} />
        )}
      </div>

      {/* Detalle del pedido seleccionado (entre buscador y tabla) */}
      {expanded && (
        <PedidoDetalle pedido={expanded} onClose={() => setExpanded(null)} />
      )}

      {/* Barra de selección */}
      {selectable && selected.size > 0 && (
        <div className="flex items-center justify-between rounded-md border border-steel/40 bg-steel/10 px-4 py-2.5">
          <p className="text-sm font-semibold text-ink">
            {selected.size} {selected.size === 1 ? "pedido seleccionado" : "pedidos seleccionados"}
          </p>
          <div className="flex gap-2">
            <button
              onClick={abrirGuiasSeleccionadas}
              className="rounded-md bg-navy px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-white hover:bg-ink"
            >
              Abrir guías ({selected.size})
            </button>
            <button
              onClick={() => setSelected(new Set())}
              className="rounded-md border border-border bg-white px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-graphite hover:bg-concrete"
            >
              Limpiar
            </button>
          </div>
        </div>
      )}

      {/* Resultados */}
      <p className="text-xs text-graphite">
        {filtered.length} de {pedidos.length} pedidos
      </p>

      {/* Tabla */}
      <Card>
        <CardContent className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-concrete/50 border-b border-border">
                <tr>
                  {has("select")   && (
                    <Th>
                      <input
                        type="checkbox"
                        checked={selected.size > 0 && selected.size === Math.min(filtered.length, limit)}
                        onChange={toggleAll}
                        className="rounded border-graphite/40"
                      />
                    </Th>
                  )}
                  {has("nivel")    && <Th>Nivel</Th>}
                  {has("orden")    && <Th>Orden</Th>}
                  {has("cliente")  && <Th>Cliente</Th>}
                  {has("telefono") && <Th>Teléfono</Th>}
                  {has("ciudad")   && <Th>Ciudad</Th>}
                  {has("zona")     && <Th>Zona</Th>}
                  {has("dias")     && <Th align="right">Días</Th>}
                  {has("valor")    && <Th align="right">Valor COD</Th>}
                  {has("estado")   && <Th>Estado</Th>}
                  {has("novedad")  && <Th>Novedad</Th>}
                  {has("tipo")     && <Th>Tipo</Th>}
                  {has("link")     && <Th>{""}</Th>}
                  {has("action")   && <Th align="right">Acción</Th>}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={cols.length} className="text-center py-12 text-graphite">
                      {emptyMessage}
                    </td>
                  </tr>
                ) : (
                  filtered.slice(0, limit).map((p) => {
                    const key = p.orden_melonn || p.orden_tienda;
                    return (
                      <Row
                        key={key}
                        p={p}
                        cols={cols}
                        isSelected={selected.has(key)}
                        isExpanded={expanded?.orden_melonn === p.orden_melonn}
                        onToggle={() => toggleOne(key)}
                        onExpand={() => setExpanded(expanded?.orden_melonn === p.orden_melonn ? null : p)}
                        renderAction={renderAction}
                      />
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          {filtered.length > limit && (
            <p className="text-xs text-graphite text-center py-3 border-t border-border">
              Mostrando {limit} de {filtered.length} · refina filtros para ver más
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Row({
  p, cols, isSelected, isExpanded, onToggle, onExpand, renderAction,
}: {
  p: Pedido;
  cols: ColumnKey[];
  isSelected: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  onExpand: () => void;
  renderAction?: (p: Pedido) => React.ReactNode;
}) {
  const has = (c: ColumnKey) => cols.includes(c);
  const dias = p.dias_real ?? 0;
  const sla  = p.sla_critico ?? 0;
  const overSla = sla > 0 && dias > sla;
  const tel = (p.telefono_comprador || "").replace(/\D/g, "");

  // Click en cualquier celda excepto checkboxes/enlaces expande el detalle
  const handleRowClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.closest('input, a, button, label')) return;
    onExpand();
  };

  return (
    <tr
      onClick={handleRowClick}
      className={`border-b border-border hover:bg-concrete/30 transition-colors cursor-pointer ${isSelected ? "bg-steel/5" : ""} ${isExpanded ? "bg-steel/15 border-l-2 border-l-steel" : ""}`}>
      {has("select") && (
        <Td>
          <input
            type="checkbox"
            checked={isSelected}
            onChange={onToggle}
            className="rounded border-graphite/40"
          />
        </Td>
      )}
      {has("nivel") && <Td><NivelBadge nivel={p.nivel} /></Td>}
      {has("orden") && (
        <Td>
          <div className="font-semibold text-ink">{p.orden_tienda || p.orden_melonn}</div>
          {p.orden_tienda && p.orden_melonn && p.orden_tienda !== p.orden_melonn && (
            <div className="text-[0.65rem] text-graphite">{p.orden_melonn}</div>
          )}
        </Td>
      )}
      {has("cliente") && (
        <Td>
          <div className="truncate max-w-[180px]">{p.nombre_comprador || "—"}</div>
        </Td>
      )}
      {has("telefono") && (
        <Td>
          {tel ? (
            <div className="flex items-center gap-1.5">
              <a href={`tel:+57${tel}`} className="text-ink hover:text-navy" title="Llamar">
                <Phone className="h-3.5 w-3.5" />
              </a>
              <a
                href={`https://wa.me/57${tel}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-teal hover:text-ink"
                title="WhatsApp"
              >
                <MessageCircle className="h-3.5 w-3.5" />
              </a>
              <span className="text-xs text-graphite tabular-nums">{p.telefono_comprador}</span>
            </div>
          ) : (
            <span className="text-graphite">—</span>
          )}
        </Td>
      )}
      {has("ciudad") && <Td>{p.ciudad_destino || "—"}</Td>}
      {has("zona")   && <Td className="text-xs text-graphite">{p.zona || "—"}</Td>}
      {has("dias") && (
        <Td align="right">
          <span className={overSla ? "text-crimson font-semibold tabular-nums" : "tabular-nums"}>
            {dias}d{sla > 0 && ` / ${sla}`}
          </span>
        </Td>
      )}
      {has("valor") && (
        <Td align="right" className="tabular-nums">
          {p.valor_num ? formatMoneyShort(p.valor_num) : "—"}
        </Td>
      )}
      {has("estado")  && <Td className="text-xs">{p.estado_melonn || "—"}</Td>}
      {has("novedad") && <Td className="text-xs">{(p.incidencia && p.incidencia !== "NINGUNO" ? p.incidencia : "—") as string}</Td>}
      {has("tipo") && (
        <Td>
          <Badge tone={p.tipo_recaudo === "Contraentrega" ? "info" : "neutral"}>
            {p.tipo_recaudo === "Contraentrega" ? "COD" : "PRE"}
          </Badge>
        </Td>
      )}
      {has("link") && (
        <Td>
          {p.link_guia ? (
            <a
              href={p.link_guia as string}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center text-steel hover:text-navy"
              title="Ver guía en Melonn"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : null}
        </Td>
      )}
      {has("action") && renderAction && (
        <Td align="right">{renderAction(p)}</Td>
      )}
    </tr>
  );
}

function NivelBadge({ nivel }: { nivel?: NivelRiesgo }) {
  if (!nivel) return <span className="text-graphite">—</span>;
  const map: Record<NivelRiesgo, "critico" | "riesgo" | "normal" | "neutral"> = {
    CRITICO: "critico",
    RIESGO:  "riesgo",
    NORMAL:  "normal",
    VENCIDO: "critico",
    RESUELTO:"neutral",
  };
  return <Badge tone={map[nivel]}>{nivel}</Badge>;
}

function Th({ children, align = "left" }: { children?: React.ReactNode; align?: "left" | "right" }) {
  const alignCls = align === "right" ? "text-right" : "text-left";
  return (
    <th className={`px-3 py-2.5 text-[0.6rem] font-bold uppercase tracking-[0.15em] text-graphite ${alignCls}`}>
      {children}
    </th>
  );
}

function Td({
  children, align = "left", className = "",
}: {
  children?: React.ReactNode; align?: "left" | "right"; className?: string;
}) {
  const alignCls = align === "right" ? "text-right" : "text-left";
  return <td className={`px-3 py-2.5 ${alignCls} ${className}`}>{children}</td>;
}

function Select({
  label, value, onChange, options,
}: {
  label: string; value: string; onChange: (v: string) => void; options: string[];
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-graphite">
      <span className="font-semibold uppercase tracking-wider text-[0.6rem]">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-white px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
      >
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </label>
  );
}
