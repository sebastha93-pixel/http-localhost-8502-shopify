"use client";

import { useMemo, useState } from "react";
import { Pedido, NivelRiesgo } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatMoneyShort } from "@/lib/utils";
import { Search, ExternalLink, Phone, MessageCircle } from "lucide-react";
import { PedidoDetalle } from "@/components/pedido-detalle";
import { trackingUrl } from "@/lib/carriers";
import { tipoEnvio } from "@/lib/envio-tipo";
import { estadoMelonnCorto } from "@/lib/estado-melonn";
import { ClienteBadge, PrioridadCodBadge } from "@/components/cliente-badge";

const NIVELES: NivelRiesgo[] = ["CRITICO", "RIESGO", "NORMAL", "VENCIDO", "RESUELTO"];

type ColumnKey =
  | "select" | "nivel" | "orden" | "cliente" | "telefono" | "ciudad" | "zona"
  | "dias" | "valor" | "estado" | "tipo" | "novedad" | "link" | "action"
  | "producto" | "envio" | "cliente_tier" | "prioridad_cod";

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

const DATOS_FILTROS = ["Todos", "Completos", "Sin datos"] as const;
type DatosFiltro = (typeof DATOS_FILTROS)[number];

function sinDatosCliente(p: { nombre_comprador?: string; telefono_comprador?: string; ciudad_destino?: string }): boolean {
  return !p.nombre_comprador && !p.telefono_comprador && !p.ciudad_destino;
}

const DEFAULT_COLS: ColumnKey[] = ["nivel", "orden", "cliente", "telefono", "ciudad", "zona", "dias", "valor", "estado", "tipo", "link"];

export function PedidosTable({
  pedidos,
  showNivelFilter = true,
  showTipoFilter = true,
  emptyMessage = "Sin pedidos con estos filtros. Cambia el período o limpia los filtros.",
  limit = 200,
  columns = DEFAULT_COLS,
  selectable = false,
  renderAction,
}: Props) {
  const [q, setQ] = useState("");
  const [nivel, setNivel] = useState<NivelRiesgo | "Todos">("Todos");
  const [tipo, setTipo] = useState<TipoFiltro>("Todos");
  const [datos, setDatos] = useState<DatosFiltro>("Todos");
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
      if (datos === "Sin datos" && !sinDatosCliente(p)) return false;
      if (datos === "Completos" && sinDatosCliente(p)) return false;
      if (!term) return true;
      return (
        p.orden_tienda?.toLowerCase().includes(term) ||
        p.orden_melonn?.toLowerCase().includes(term) ||
        p.nombre_comprador?.toLowerCase().includes(term) ||
        p.ciudad_destino?.toLowerCase().includes(term) ||
        p.telefono_comprador?.toLowerCase().includes(term)
      );
    });
  }, [pedidos, q, nivel, tipo, datos, showNivelFilter, showTipoFilter]);

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
            placeholder="Buscar (/) orden, cliente, ciudad o teléfono"
            className="w-full rounded-sm border border-border bg-card pl-9 pr-3 py-2 text-sm text-ink-900 placeholder:text-graphite/60 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
          />
        </div>
        {showNivelFilter && (
          <Select label="Nivel" value={nivel} onChange={(v) => setNivel(v as NivelRiesgo | "Todos")} options={["Todos", ...NIVELES]} />
        )}
        {showTipoFilter && (
          <Select label="Tipo" value={tipo} onChange={(v) => setTipo(v as TipoFiltro)} options={TIPO_FILTROS as unknown as string[]} />
        )}
        <Select label="Datos" value={datos} onChange={(v) => setDatos(v as DatosFiltro)} options={DATOS_FILTROS as unknown as string[]} />
      </div>

      {/* Detalle del pedido seleccionado (entre buscador y tabla) */}
      {expanded && (
        <PedidoDetalle pedido={expanded} onClose={() => setExpanded(null)} />
      )}

      {/* Barra de selección eliminada — la info del pedido se ve al tocarlo */}

      {/* Resultados */}
      <p className="text-xs text-graphite tabular-nums">
        {filtered.length} de {pedidos.length} pedidos
      </p>

      {/* Tabla */}
      <Card>
        <CardContent className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-cloud/60 border-b border-border">
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
                  {has("cliente_tier") && <Th>Tier</Th>}
                  {has("prioridad_cod") && <Th>Prioridad</Th>}
                  {has("telefono") && <Th>Teléfono</Th>}
                  {has("producto") && <Th>Producto</Th>}
                  {has("ciudad")   && <Th>Ciudad</Th>}
                  {has("zona")     && <Th>Zona</Th>}
                  {has("envio")    && <Th>Envío</Th>}
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
      className={`border-b border-border hover:bg-cloud/50 transition-colors cursor-pointer ${isSelected ? "bg-steel-300/10" : ""} ${isExpanded ? "bg-steel-300/20 border-l-2 border-l-navy-600" : ""}`}>
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
          <div className="font-medium text-ink-900 tabular-nums">{p.orden_tienda || p.orden_melonn}</div>
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
      {has("cliente_tier") && (
        <Td>
          <ClienteBadge email={p.email_comprador as string} telefono={p.telefono_comprador} />
        </Td>
      )}
      {has("prioridad_cod") && (
        <Td>
          <PrioridadCodBadge email={p.email_comprador as string} telefono={p.telefono_comprador} />
        </Td>
      )}
      {has("telefono") && (
        <Td>
          {tel ? (
            <div className="flex items-center gap-1.5">
              <a href={`tel:+57${tel}`} className="text-ink-900 hover:text-navy-600" title="Llamar">
                <Phone className="h-3.5 w-3.5" />
              </a>
              <a
                href={`https://wa.me/57${tel}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sage hover:text-ink-900"
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
      {has("producto") && (
        <Td>
          <div className="flex items-center gap-2 min-w-0">
            {p.imagen_producto ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={p.imagen_producto as string}
                alt=""
                className="h-9 w-9 rounded object-cover border border-border flex-none bg-concrete"
              />
            ) : null}
            <div className="min-w-0 text-xs">
              <div className="font-medium text-ink-900 truncate max-w-[150px]">{p.sku || "—"}</div>
              <div className="text-graphite">
                {p.variante && <span>Talla {p.variante}</span>}
                {p.items && p.items.length > 1 && (
                  <span className="ml-1 inline-block rounded-sm bg-steel-300/20 px-1 py-0.5 text-[0.6rem] font-semibold text-navy-700">
                    +{p.items.length - 1} más
                  </span>
                )}
              </div>
            </div>
          </div>
        </Td>
      )}
      {has("ciudad") && <Td>{p.ciudad_destino || "—"}</Td>}
      {has("zona")   && <Td className="text-xs text-graphite">{p.zona || "—"}</Td>}
      {has("envio") && (
        <Td className="whitespace-nowrap">
          {(() => {
            const te = tipoEnvio(p.transportadora as string);
            if (!te) return <span className="text-graphite">—</span>;
            return <Badge tone={te.tone}>{te.short}</Badge>;
          })()}
        </Td>
      )}
      {has("dias") && (
        <Td align="right">
          <span className={overSla ? "text-terracotta font-semibold tabular-nums" : "tabular-nums"}>
            {dias}d{sla > 0 && ` / ${sla}`}
          </span>
        </Td>
      )}
      {has("valor") && (
        <Td align="right" className="tabular-nums">
          {p.valor_num ? formatMoneyShort(p.valor_num) : "—"}
        </Td>
      )}
      {has("estado")  && (
        <Td className="text-xs whitespace-nowrap">
          <span title={p.estado_melonn || ""}>
            {estadoMelonnCorto(p.estado_melonn, p.estado_melonn_code)}
          </span>
        </Td>
      )}
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
          {(() => {
            // Si hay guía + carrier → link directo a la transportadora.
            // Si no → fallback al tracking de Melonn.
            const directo = trackingUrl(p.carrier_real as string, p.guia_real as string);
            const href = directo || (p.link_guia as string) || "";
            if (!href) return null;
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center text-graphite hover:text-navy-600"
                title={directo ? `Rastrear en ${p.carrier_real}` : "Ver en Melonn"}
              >
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            );
          })()}
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
  const map: Record<NivelRiesgo, { tone: "critico" | "riesgo" | "normal" | "neutral"; label: string }> = {
    CRITICO:  { tone: "critico", label: "Crítico" },
    RIESGO:   { tone: "riesgo",  label: "Riesgo"  },
    NORMAL:   { tone: "normal",  label: "Normal"  },
    VENCIDO:  { tone: "critico", label: "Vencido" },
    RESUELTO: { tone: "neutral", label: "Resuelto" },
  };
  const cfg = map[nivel];
  return <Badge tone={cfg.tone}>{cfg.label}</Badge>;
}

function Th({ children, align = "left" }: { children?: React.ReactNode; align?: "left" | "right" }) {
  const alignCls = align === "right" ? "text-right" : "text-left";
  return (
    <th className={`px-3 py-2.5 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite ${alignCls}`}>
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
      <span className="font-semibold uppercase tracking-[0.12em] text-[0.62rem]">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-sm border border-border bg-card px-3 py-2 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
      >
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </label>
  );
}
