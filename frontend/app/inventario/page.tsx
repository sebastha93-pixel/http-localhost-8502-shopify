"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard, KpiStrip } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Search, ExternalLink } from "lucide-react";
import { formatMoney } from "@/lib/utils";

interface ResumenResp {
  activos: number;
  borrador: number;
  archivados: number;
  total_skus: number;
  total_unidades: number;
  sin_stock: number;
  stock_bajo: number;
}

interface Producto {
  id: number;
  titulo: string;
  handle: string;
  sku_principal: string;
  status: string;
  vendor: string;
  tipo: string;
  imagen: string;
  total_stock: number;
  num_variantes: number;
  sin_stock: boolean;
  stock_bajo: boolean;
  precio_min?: number;
  precio_max?: number;
  descuento_max_pct?: number;
  published_at?: string;
  dias_publicado?: number | null;
  stock_melonn?: number | null;             // null si no se cruzó con Melonn
  diferencia_shopify_melonn?: number | null; // Shopify - Melonn (positivo = Shopify dice más)
  updated_at: string;
  variantes: Array<{
    id: number;
    sku: string;
    titulo: string;
    precio: number;
    precio_full?: number;
    descuento_pct?: number;
    stock: number;
    stock_melonn?: number | null;
  }>;
}

interface ProductosResp {
  status: string;
  total: number;
  productos: Producto[];
}

interface PorTiendaResp {
  bodegas: string[];
  referencias: Array<{ code: string; referencia: string; talla: string; nombre: string; stock: Record<string, number>; total: number }>;
  total_referencias: number;
}

type Filtro = "todos" | "con_stock" | "sin_stock" | "stock_bajo";

function shopifyAdminUrl(handle: string): string {
  return `https://admin.shopify.com/store/me-fits/products?query=${encodeURIComponent(handle)}`;
}

/**
 * Devuelve el SKU "raíz" común de todas las variantes de un producto.
 * Ej: ["93617-1T6","93617-1T8","93617-1T10"] → "93617-1T"
 * Si solo hay 1 variante o no comparten prefijo, devuelve el SKU principal.
 */
function skuAgrupado(p: Producto): string {
  const skus = p.variantes.map((v) => v.sku).filter(Boolean);
  if (skus.length <= 1) return p.sku_principal || "—";
  // Prefijo común más largo
  let prefijo = skus[0];
  for (let i = 1; i < skus.length; i++) {
    let j = 0;
    while (j < prefijo.length && j < skus[i].length && prefijo[j] === skus[i][j]) j++;
    prefijo = prefijo.slice(0, j);
    if (!prefijo) break;
  }
  // Limpia separadores colgantes al final (- _ /) y dígitos sueltos
  prefijo = prefijo.replace(/[-_/]+$/, "");
  if (prefijo.length < 3) return p.sku_principal || "—";  // muy corto → mejor mostrar el principal
  return prefijo;
}

/** Extrae la "talla" o sufijo único de una variante quitando el prefijo común. */
function tallaDeVariante(skuVariante: string, raiz: string): string {
  if (!skuVariante) return "—";
  if (!raiz || raiz === "—") return skuVariante;
  let resto = skuVariante.startsWith(raiz) ? skuVariante.slice(raiz.length) : skuVariante;
  resto = resto.replace(/^[-_/]+/, "");
  return resto || skuVariante;
}

function TablaProductos({ productos, mostrarStock = true }: { productos: Producto[]; mostrarStock?: boolean }) {
  const [q, setQ] = useState("");
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [expandido, setExpandido] = useState<number | null>(null);

  const filtrados = useMemo(() => {
    const term = q.trim().toLowerCase();
    return productos.filter((p) => {
      if (filtro === "con_stock" && p.sin_stock) return false;
      if (filtro === "sin_stock" && !p.sin_stock) return false;
      if (filtro === "stock_bajo" && !p.stock_bajo) return false;
      if (!term) return true;
      return (
        p.titulo.toLowerCase().includes(term) ||
        p.sku_principal.toLowerCase().includes(term) ||
        p.vendor.toLowerCase().includes(term) ||
        p.tipo.toLowerCase().includes(term)
      );
    });
  }, [productos, q, filtro]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar producto, SKU, vendor o tipo"
            className="w-full rounded-sm border border-border bg-card pl-9 pr-3 py-2 text-sm text-ink-900 placeholder:text-graphite/60 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
          />
        </div>
        {mostrarStock && (
          <div className="inline-flex overflow-hidden rounded-sm border border-border bg-card">
            {([
              { id: "todos", label: "Todos" },
              { id: "con_stock", label: "Con stock" },
              { id: "sin_stock", label: "Sin stock" },
              { id: "stock_bajo", label: "Stock bajo" },
            ] as Array<{ id: Filtro; label: string }>).map((f) => (
              <button
                key={f.id}
                onClick={() => setFiltro(f.id)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  filtro === f.id ? "bg-ink-900 text-white" : "text-graphite hover:bg-cloud"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <p className="text-xs text-graphite tabular-nums">{filtrados.length} de {productos.length} productos</p>

      <Card>
        <CardContent className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                  <th className="px-3 py-2.5"></th>
                  <th className="px-3 py-2.5">Producto</th>
                  <th className="px-3 py-2.5">SKU</th>
                  <th className="px-3 py-2.5">Tipo</th>
                  <th className="px-3 py-2.5 text-right">Precio</th>
                  <th className="px-3 py-2.5 text-right">Descuento</th>
                  <th className="px-3 py-2.5 text-right">Variantes</th>
                  {mostrarStock && <th className="px-3 py-2.5 text-right">Stock</th>}
                  <th className="px-3 py-2.5 text-right" title="Días desde el lanzamiento en Shopify">Lanzamiento</th>
                  <th className="px-3 py-2.5 text-right" title="Stock real en bodega Melonn (MED-2). Comparación con Stock Shopify para detectar discrepancias.">Stock Melonn</th>
                  <th className="px-3 py-2.5">Estado</th>
                  <th className="px-3 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filtrados.length === 0 ? (
                  <tr><td colSpan={12} className="px-3 py-8 text-center text-sm text-graphite">Sin productos con estos filtros.</td></tr>
                ) : filtrados.map((p) => (
                  <>
                    <tr
                      key={p.id}
                      className="hover:bg-cloud/50 cursor-pointer transition-colors"
                      onClick={() => setExpandido(expandido === p.id ? null : p.id)}
                    >
                      <td className="px-3 py-2.5">
                        {p.imagen ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={p.imagen} alt="" className="h-10 w-10 rounded object-cover" />
                        ) : (
                          <div className="h-10 w-10 rounded bg-concrete" />
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <p className="font-medium text-ink-900">{p.titulo}</p>
                        <p className="text-xs text-graphite">{p.vendor || "—"}</p>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-graphite tabular-nums">{skuAgrupado(p)}</td>
                      <td className="px-3 py-2.5 text-xs text-graphite">{p.tipo || "—"}</td>
                      <td className="px-3 py-2.5 text-right text-xs">
                        {(() => {
                          const min = p.precio_min || 0;
                          const max = p.precio_max || 0;
                          if (!min && !max) return <span className="text-graphite">—</span>;
                          const tienePrecioFull = (p.descuento_max_pct || 0) > 0;
                          return (
                            <div className="flex flex-col items-end">
                              <span className="font-medium text-ink-900 tabular-nums">
                                {min === max ? formatMoney(min) : `${formatMoney(min)} – ${formatMoney(max)}`}
                              </span>
                              {tienePrecioFull && (
                                <span className="text-[0.65rem] text-graphite line-through tabular-nums">
                                  {/* precio full más alto entre variantes con descuento */}
                                  {(() => {
                                    const fulls = (p.variantes || []).map(v => v.precio_full || 0).filter(x => x > 0);
                                    return fulls.length ? formatMoney(Math.max(...fulls)) : "";
                                  })()}
                                </span>
                              )}
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {(p.descuento_max_pct || 0) > 0 ? (
                          <Badge tone="riesgo">-{(p.descuento_max_pct || 0).toFixed(0)}%</Badge>
                        ) : (
                          <span className="text-graphite">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{p.num_variantes}</td>
                      {mostrarStock && (
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          <span className={p.sin_stock ? "text-terracotta font-semibold" : p.stock_bajo ? "text-ochre font-semibold" : "text-ink-900"}>
                            {p.total_stock}
                          </span>
                        </td>
                      )}
                      <td className="px-3 py-2.5 text-right text-xs">
                        {p.dias_publicado != null ? (
                          <span className="text-ink-900 tabular-nums" title={p.published_at}>{p.dias_publicado}d</span>
                        ) : (
                          <span className="text-graphite">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right text-xs">
                        {p.stock_melonn != null ? (
                          (() => {
                            const diff = p.diferencia_shopify_melonn ?? 0;
                            const hayDif = Math.abs(diff) > 0;
                            return (
                              <span
                                className={hayDif ? "text-terracotta font-semibold tabular-nums" : "text-ink-900 tabular-nums"}
                                title={hayDif ? `Shopify dice ${p.total_stock}, Melonn tiene ${p.stock_melonn}. Diferencia ${diff > 0 ? "+" : ""}${diff}.` : "Cuadra con Shopify"}
                              >
                                {p.stock_melonn}
                                {hayDif && <span className="ml-1 text-[0.65rem]">({diff > 0 ? "+" : ""}{diff})</span>}
                              </span>
                            );
                          })()
                        ) : (
                          <span className="text-graphite italic" title="SKU sin match en Melonn (no está en bodega o el SKU no coincide)">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        {p.sin_stock ? <Badge tone="critico">Sin stock</Badge> :
                         p.stock_bajo ? <Badge tone="riesgo">Stock bajo</Badge> :
                         p.status === "draft" ? <Badge tone="pendiente">Borrador</Badge> :
                         <Badge tone="normal">{p.status}</Badge>}
                      </td>
                      <td className="px-3 py-2.5">
                        <a
                          href={shopifyAdminUrl(p.handle)}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="inline-flex items-center text-graphite hover:text-navy-600"
                          title="Abrir en Shopify admin"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      </td>
                    </tr>
                    {expandido === p.id && (
                      <tr key={`${p.id}-vars`} className="bg-cloud/40">
                        <td colSpan={12} className="px-6 py-3">
                          <div className="mb-2 flex items-center justify-between">
                            <p className="text-[0.65rem] uppercase tracking-[0.12em] text-graphite">Tallas del SKU <span className="font-medium text-ink-900 tabular-nums">{skuAgrupado(p)}</span></p>
                            <p className="text-[0.65rem] text-graphite">{p.variantes.length} {p.variantes.length === 1 ? "variante" : "variantes"}</p>
                          </div>
                          <table className="w-full text-xs">
                            <thead className="text-graphite">
                              <tr>
                                <th className="text-left py-1 font-medium">Talla</th>
                                <th className="text-left py-1 font-medium">Variante</th>
                                <th className="text-left py-1 font-medium">SKU completo</th>
                                <th className="text-right py-1 font-medium">Precio</th>
                                <th className="text-right py-1 font-medium">Precio full</th>
                                <th className="text-right py-1 font-medium">Descuento</th>
                                <th className="text-right py-1 font-medium">Stock Shopify</th>
                                <th className="text-right py-1 font-medium">Stock Melonn</th>
                              </tr>
                            </thead>
                            <tbody>
                              {p.variantes.map((v) => {
                                const raiz = skuAgrupado(p);
                                const desc = v.descuento_pct || 0;
                                const full = v.precio_full || 0;
                                const sm = v.stock_melonn;
                                const diff = sm != null ? v.stock - sm : 0;
                                return (
                                  <tr key={v.id}>
                                    <td className="py-1 font-medium text-ink-900">{tallaDeVariante(v.sku, raiz)}</td>
                                    <td className="py-1 text-graphite">{v.titulo || "—"}</td>
                                    <td className="py-1 text-graphite tabular-nums">{v.sku || "—"}</td>
                                    <td className="py-1 text-right font-medium text-ink-900 tabular-nums">{formatMoney(v.precio)}</td>
                                    <td className="py-1 text-right text-graphite tabular-nums">
                                      {full > 0 ? <span className="line-through">{formatMoney(full)}</span> : "—"}
                                    </td>
                                    <td className="py-1 text-right tabular-nums">
                                      {desc > 0 ? <span className="text-terracotta font-semibold">-{desc.toFixed(0)}%</span> : <span className="text-graphite">—</span>}
                                    </td>
                                    <td className={`py-1 text-right tabular-nums ${v.stock <= 0 ? "text-terracotta font-semibold" : v.stock <= 5 ? "text-ochre" : "text-ink-900"}`}>{v.stock}</td>
                                    <td className="py-1 text-right tabular-nums">
                                      {sm == null ? (
                                        <span className="text-graphite italic" title="Sin match en Melonn">—</span>
                                      ) : (
                                        <span
                                          className={diff !== 0 ? "text-terracotta font-semibold" : "text-ink-900"}
                                          title={diff !== 0 ? `Shopify: ${v.stock} · Melonn: ${sm} · Diferencia ${diff > 0 ? "+" : ""}${diff}` : "Cuadra"}
                                        >
                                          {sm}{diff !== 0 && <span className="ml-1 text-[0.65rem]">({diff > 0 ? "+" : ""}{diff})</span>}
                                        </span>
                                      )}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}


/** RF-06 - Inventario por tienda/bodega desde Siigo (Florida, Arrayanes, Melonn). */
function TablaPorTienda({ data }: { data: PorTiendaResp }) {
  const [q, setQ] = useState("");
  const [tienda, setTienda] = useState<string>("todas");
  const orden = ["Florida", "Arrayanes"];
  const bodegas = [...data.bodegas].sort((a, b) => {
    const ia = orden.indexOf(a), ib = orden.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  // Chips: Todas + cada tienda física disponible
  const fisicas = bodegas.filter((b) => ["Florida", "Arrayanes"].includes(b));
  // Reset del filtro si la tienda seleccionada ya no está en los datos
  const tiendaActiva = tienda !== "todas" && !fisicas.includes(tienda) ? "todas" : tienda;
  // Columnas visibles según el filtro
  const bodegasVis = tiendaActiva === "todas" ? bodegas : [tiendaActiva];
  const filas = useMemo(() => {
    const term = q.trim().toUpperCase();
    return data.referencias
      .filter((r) => !term || r.referencia.toUpperCase().includes(term) || r.code.toUpperCase().includes(term) || r.nombre.toUpperCase().includes(term))
      // Al filtrar por una tienda, solo referencias con stock en esa tienda
      .filter((r) => tiendaActiva === "todas" || (r.stock[tiendaActiva] || 0) > 0)
      .sort((a, b) => (tiendaActiva === "todas" ? b.total - a.total : (b.stock[tiendaActiva] || 0) - (a.stock[tiendaActiva] || 0)));
  }, [data.referencias, q, tiendaActiva]);
  // Totales por bodega SIEMPRE sobre todas las físicas (el KPI muestra el panorama completo)
  const totalesBodega = useMemo(() => {
    const t: Record<string, number> = {};
    const term = q.trim().toUpperCase();
    const base = data.referencias.filter((r) => !term || r.referencia.toUpperCase().includes(term) || r.code.toUpperCase().includes(term) || r.nombre.toUpperCase().includes(term));
    for (const r of base) for (const b of bodegas) t[b] = (t[b] || 0) + (r.stock[b] || 0);
    return t;
  }, [data.referencias, q, bodegas]);
  // Total visible por fila = suma de las columnas mostradas (no de tiendas ocultas)
  const totalFila = (r: PorTiendaResp["referencias"][number]) => bodegasVis.reduce((a, b) => a + (r.stock[b] || 0), 0);
  return (
    <div className="space-y-3">
      <KpiStrip
        items={fisicas.map((b) => ({
          label: `Stock ${b}`, value: Math.round(totalesBodega[b] || 0),
        }))}
      />
      <div className="flex flex-wrap items-center gap-2">
        {/* Filtro por tienda: por defecto muestra todo */}
        <div className="flex items-center gap-1 rounded-sm border border-border bg-card p-0.5">
          {["todas", ...fisicas].map((t) => {
            const activo = tiendaActiva === t;
            return (
              <button key={t} onClick={() => setTienda(t)}
                className={`rounded-sm px-2.5 py-1 text-xs font-medium capitalize transition-colors ${activo ? "bg-ink-900 text-white" : "text-graphite hover:bg-cloud/60"}`}>
                {t === "todas" ? "Todas" : t}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2 rounded-sm border border-border bg-card px-2 py-1.5">
          <Search className="h-3.5 w-3.5 text-graphite" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Referencia, SKU o nombre..."
            className="w-48 bg-transparent text-xs outline-none" />
        </div>
        <span className="text-xs text-graphite tabular-nums">
          {filas.length} referencia(s) con stock{tiendaActiva !== "todas" ? ` en ${tiendaActiva}` : ""}
        </span>
      </div>
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-cloud/40">
              <tr className="text-left text-[0.7rem] uppercase tracking-[0.12em] text-graphite">
                <th className="px-3 py-2">Referencia</th>
                <th className="px-3 py-2">Talla</th>
                {bodegasVis.map((b) => <th key={b} className="px-3 py-2 text-right">{b}</th>)}
                <th className="px-3 py-2 text-right">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filas.length === 0 ? (
                <tr><td colSpan={bodegasVis.length + 3} className="px-3 py-8 text-center text-sm text-graphite">Sin referencias con stock.</td></tr>
              ) : filas.map((r) => (
                <tr key={r.code} className="hover:bg-cloud/40">
                  <td className="px-3 py-2.5">
                    <span className="font-medium text-ink-900 tabular-nums">{r.referencia}</span>
                    <span className="block text-[0.68rem] text-graphite truncate max-w-[280px]">{r.nombre}</span>
                  </td>
                  <td className="px-3 py-2.5 text-graphite tabular-nums">{r.talla ? `T${r.talla}` : "-"}</td>
                  {bodegasVis.map((b) => (
                    <td key={b} className={`px-3 py-2.5 text-right tabular-nums ${r.stock[b] ? "text-ink-900" : "text-graphite/40"}`}>
                      {r.stock[b] ? Math.round(r.stock[b]) : "."}
                    </td>
                  ))}
                  <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-navy-600">{Math.round(totalFila(r))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <p className="text-[0.7rem] text-graphite/70">
        Solo tiendas físicas (Florida y Arrayanes). El stock online/Melonn está en la pestaña Activos. Fuente: Siigo. Fit y Color se agregaran cruzando con Shopify por SKU.
      </p>
    </div>
  );
}

/** RF-07 — Antigüedad de inventario: referencias ordenadas por días desde su
 * lanzamiento (Shopify), con buckets de envejecimiento y stock por canal. */
function TablaAntiguedad({ productos }: { productos: Producto[] }) {
  const [q, setQ] = useState("");
  const [tipo, setTipo] = useState("");

  const tipos = useMemo(
    () => Array.from(new Set(productos.map((p) => p.tipo).filter(Boolean))).sort(),
    [productos],
  );

  // Solo productos con stock (los agotados no son "inventario" que envejece)
  const filas = useMemo(() => {
    const term = q.trim().toUpperCase();
    return productos
      .filter((p) => p.total_stock > 0 || (p.stock_melonn ?? 0) > 0)
      .filter((p) => (tipo ? p.tipo === tipo : true))
      .filter((p) => !term || p.titulo.toUpperCase().includes(term) || (p.sku_principal || "").toUpperCase().includes(term))
      .map((p) => ({ ...p, dias: p.dias_publicado ?? -1 }))
      .sort((a, b) => b.dias - a.dias);
  }, [productos, q, tipo]);

  const buckets = useMemo(() => {
    const b = { b0: 0, b30: 0, b60: 0, b90: 0 };
    for (const p of filas) {
      const d = p.dias_publicado ?? 0;
      if (d <= 30) b.b0++;
      else if (d <= 60) b.b30++;
      else if (d <= 90) b.b60++;
      else b.b90++;
    }
    return b;
  }, [filas]);

  const fmtFechaLanz = (iso?: string) =>
    iso ? new Date(iso).toLocaleDateString("es-CO", { day: "2-digit", month: "short", year: "numeric" }) : "—";

  const toneDias = (d: number) =>
    d > 90 ? "text-terracotta" : d > 60 ? "text-ochre" : "text-ink-900";

  return (
    <div className="space-y-3">
      <KpiStrip
        items={[
          { label: "0–30 días",  value: buckets.b0 },
          { label: "31–60 días", value: buckets.b30 },
          { label: "61–90 días", value: buckets.b60, tone: buckets.b60 > 0 ? "default" : "default" },
          { label: "+90 días",   value: buckets.b90, tone: buckets.b90 > 0 ? "danger" : "default" },
        ]}
      />
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 rounded-sm border border-border bg-card px-2 py-1.5">
          <Search className="h-3.5 w-3.5 text-graphite" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Referencia o SKU…"
            className="w-40 bg-transparent text-xs outline-none" />
        </div>
        <select value={tipo} onChange={(e) => setTipo(e.target.value)}
          className="rounded-sm border border-border bg-card px-3 py-1.5 text-xs">
          <option value="">Todos los fit</option>
          {tipos.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <span className="text-xs text-graphite tabular-nums">{filas.length} referencia(s)</span>
      </div>
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-cloud/40">
              <tr className="text-left text-[0.7rem] uppercase tracking-[0.12em] text-graphite">
                <th className="px-3 py-2">Referencia</th>
                <th className="px-3 py-2">Fit</th>
                <th className="px-3 py-2">Lanzamiento</th>
                <th className="px-3 py-2 text-right">Días en inventario</th>
                <th className="px-3 py-2 text-right">Stock Shopify</th>
                <th className="px-3 py-2 text-right">Stock Melonn</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filas.length === 0 ? (
                <tr><td colSpan={6} className="px-3 py-8 text-center text-sm text-graphite">Sin referencias con stock.</td></tr>
              ) : filas.map((p) => (
                <tr key={p.id} className="hover:bg-cloud/40">
                  <td className="px-3 py-2.5">
                    <span className="font-medium text-ink-900">{p.titulo}</span>
                    {p.sku_principal && <span className="block text-[0.7rem] text-graphite tabular-nums">{skuAgrupado(p)}</span>}
                  </td>
                  <td className="px-3 py-2.5 text-graphite">{p.tipo || "—"}</td>
                  <td className="px-3 py-2.5 text-graphite tabular-nums">{fmtFechaLanz(p.published_at)}</td>
                  <td className={`px-3 py-2.5 text-right font-semibold tabular-nums ${p.dias_publicado != null ? toneDias(p.dias_publicado) : "text-graphite"}`}>
                    {p.dias_publicado != null ? `${p.dias_publicado} d` : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-ink-900">{p.total_stock}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-graphite">{p.stock_melonn ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <p className="text-[0.7rem] text-graphite/70">
        Antigüedad = días desde la fecha de lanzamiento en Shopify. Florida y Arrayanes se sumarán cuando se conecte el inventario de Siigo.
      </p>
    </div>
  );
}

export default function InventarioPage() {
  const resumen = useQuery<ResumenResp>({
    queryKey: ["inv-resumen"],
    queryFn: () => api.get<ResumenResp>("/api/inventario/resumen"),
    staleTime: 30 * 60_000,
    refetchOnWindowFocus: false,
  });

  const activos = useQuery<ProductosResp>({
    queryKey: ["inv-prod-active"],
    queryFn: () => api.get<ProductosResp>("/api/inventario/productos?status=active&limit=250"),
    staleTime: 30 * 60_000,
    refetchOnWindowFocus: false,
  });

  const borradores = useQuery<ProductosResp>({
    queryKey: ["inv-prod-draft"],
    queryFn: () => api.get<ProductosResp>("/api/inventario/productos?status=draft&limit=250"),
    staleTime: 30 * 60_000,
    refetchOnWindowFocus: false,
  });

  const [tab, setTab] = useState("activos");
  const porTienda = useQuery<PorTiendaResp>({
    queryKey: ["inv-por-tienda"],
    queryFn: () => api.get<PorTiendaResp>("/api/inventario/por-tienda"),
    staleTime: 30 * 60_000,
    refetchOnWindowFocus: false,
    enabled: tab === "tiendas",
  });

  if (resumen.isLoading) return <LoadingState label="Cargando inventario…" />;
  if (resumen.error) return <ErrorState error={resumen.error} onRetry={() => resumen.refetch()} />;

  const r = resumen.data;

  return (
    <PageShell
      title="Inventario Shopify"
      subtitle="Gestión del catálogo · activos, borradores y stock"
      isFetching={activos.isFetching || borradores.isFetching}
      dataUpdatedAt={Math.max(resumen.dataUpdatedAt || 0, activos.dataUpdatedAt || 0)}
      onRefresh={() => { resumen.refetch(); activos.refetch(); borradores.refetch(); }}
    >
      {/* KPIs principales */}
      {r && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <KpiCard label="Productos activos"     value={r.activos}    meta="Visibles en tienda"  variant="success" />
            <KpiCard label="Productos en borrador" value={r.borrador}   meta="Pendientes de publicar" />
            <KpiCard label="Archivados"            value={r.archivados} meta="Descontinuados" />
          </div>
          <KpiStrip
            items={[
              { label: "SKUs activos",      value: r.total_skus },
              { label: "Unidades en stock", value: r.total_unidades },
              { label: "Sin stock",         value: r.sin_stock,  tone: r.sin_stock > 10 ? "danger" : "default" },
              { label: "Stock bajo",        value: r.stock_bajo, tone: r.stock_bajo > 0 ? "danger" : "default" },
            ]}
          />
        </>
      )}

      {/* Tabla con tabs activos / borradores */}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="activos">Activos ({activos.data?.total || 0})</TabsTrigger>
          <TabsTrigger value="borradores">Borradores ({borradores.data?.total || 0})</TabsTrigger>
          <TabsTrigger value="tiendas">Por tienda</TabsTrigger>
          <TabsTrigger value="antiguedad">Antigüedad</TabsTrigger>
        </TabsList>

        <TabsContent value="activos">
          {activos.isLoading || !activos.data ? (
            <Card><CardContent className="p-8 text-center text-sm text-graphite">Cargando productos activos…</CardContent></Card>
          ) : (
            <TablaProductos productos={activos.data.productos} />
          )}
        </TabsContent>

        <TabsContent value="borradores">
          {borradores.isLoading || !borradores.data ? (
            <Card><CardContent className="p-8 text-center text-sm text-graphite">Cargando borradores…</CardContent></Card>
          ) : (
            <TablaProductos productos={borradores.data.productos} mostrarStock={false} />
          )}
        </TabsContent>

        <TabsContent value="tiendas">
          {porTienda.isLoading || !porTienda.data ? (
            <Card><CardContent className="p-8 text-center text-sm text-graphite">Cargando inventario por tienda desde Siigo... (puede tardar la primera vez)</CardContent></Card>
          ) : porTienda.error ? (
            <ErrorState error={porTienda.error} onRetry={() => porTienda.refetch()} />
          ) : (
            <TablaPorTienda data={porTienda.data} />
          )}
        </TabsContent>

        <TabsContent value="antiguedad">
          {activos.isLoading || !activos.data ? (
            <Card><CardContent className="p-8 text-center text-sm text-graphite">Cargando antigüedad…</CardContent></Card>
          ) : (
            <TablaAntiguedad productos={activos.data.productos} />
          )}
        </TabsContent>
      </Tabs>

      <p className="text-[0.65rem] text-graphite/70 mt-2">
        Próximamente: productos sin venta en 90 días · reposición sugerida basada en velocidad de venta.
      </p>
    </PageShell>
  );
}
