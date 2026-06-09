"use client";

import { useMemo, useState } from "react";
import { Pedido, NivelRiesgo } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatMoneyShort } from "@/lib/utils";
import { Search, ExternalLink } from "lucide-react";

const NIVELES: NivelRiesgo[] = ["CRITICO", "RIESGO", "NORMAL", "VENCIDO", "RESUELTO"];

interface Props {
  pedidos: Pedido[];
  showNivelFilter?: boolean;
  showTipoFilter?: boolean;
  emptyMessage?: string;
  limit?: number;
  /** Columnas visibles. Default todas. */
  columns?: Array<"nivel" | "orden" | "cliente" | "ciudad" | "zona" | "dias" | "valor" | "estado" | "tipo" | "novedad" | "link">;
}

const TIPO_FILTROS = ["Todos", "Contraentrega", "Prepago"] as const;
type TipoFiltro = (typeof TIPO_FILTROS)[number];

export function PedidosTable({
  pedidos,
  showNivelFilter = true,
  showTipoFilter = true,
  emptyMessage = "Sin resultados con los filtros aplicados",
  limit = 200,
  columns = ["nivel", "orden", "cliente", "ciudad", "zona", "dias", "valor", "estado", "tipo", "link"],
}: Props) {
  const [q, setQ] = useState("");
  const [nivel, setNivel] = useState<NivelRiesgo | "Todos">("Todos");
  const [tipo, setTipo] = useState<TipoFiltro>("Todos");

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
        p.ciudad_destino?.toLowerCase().includes(term)
      );
    });
  }, [pedidos, q, nivel, tipo, showNivelFilter, showTipoFilter]);

  const has = (c: Props["columns"] extends Array<infer T> ? T : never) => columns.includes(c);

  return (
    <div className="space-y-4">
      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar por orden, cliente o ciudad..."
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
                  {has("nivel")   && <Th>Nivel</Th>}
                  {has("orden")   && <Th>Orden</Th>}
                  {has("cliente") && <Th>Cliente</Th>}
                  {has("ciudad")  && <Th>Ciudad</Th>}
                  {has("zona")    && <Th>Zona</Th>}
                  {has("dias")    && <Th align="right">Días</Th>}
                  {has("valor")   && <Th align="right">Valor COD</Th>}
                  {has("estado")  && <Th>Estado</Th>}
                  {has("novedad") && <Th>Novedad</Th>}
                  {has("tipo")    && <Th>Tipo</Th>}
                  {has("link")    && <Th></Th>}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={columns.length} className="text-center py-12 text-graphite">
                      {emptyMessage}
                    </td>
                  </tr>
                ) : (
                  filtered.slice(0, limit).map((p) => (
                    <Row key={p.orden_melonn || p.orden_tienda} p={p} columns={columns} />
                  ))
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

function Row({ p, columns }: { p: Pedido; columns: NonNullable<Props["columns"]> }) {
  const has = (c: (typeof columns)[number]) => columns.includes(c);
  const dias = p.dias_real ?? 0;
  const sla  = p.sla_critico ?? 0;
  const overSla = sla > 0 && dias > sla;

  return (
    <tr className="border-b border-border hover:bg-concrete/30 transition-colors">
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
              title="Ver en Melonn"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : null}
        </Td>
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

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  const alignCls = align === "right" ? "text-right" : "text-left";
  return (
    <th className={`px-3 py-2.5 text-[0.6rem] font-bold uppercase tracking-[0.15em] text-graphite ${alignCls}`}>
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
  className = "",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  const alignCls = align === "right" ? "text-right" : "text-left";
  return <td className={`px-3 py-2.5 ${alignCls} ${className}`}>{children}</td>;
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
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
