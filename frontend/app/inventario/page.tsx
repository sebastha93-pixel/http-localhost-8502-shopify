"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Search, ExternalLink } from "lucide-react";

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
  updated_at: string;
  variantes: Array<{ id: number; sku: string; titulo: string; precio: number; stock: number }>;
}

interface ProductosResp {
  status: string;
  total: number;
  productos: Producto[];
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
            placeholder="Buscar por producto, SKU, vendor o tipo..."
            className="w-full rounded-md border border-border bg-white pl-9 pr-3 py-2 text-sm text-ink placeholder:text-graphite/60 focus:outline-none focus:ring-2 focus:ring-steel"
          />
        </div>
        {mostrarStock && (
          <div className="flex gap-1">
            {([
              { id: "todos", label: "Todos" },
              { id: "con_stock", label: "Con stock" },
              { id: "sin_stock", label: "Sin stock" },
              { id: "stock_bajo", label: "Stock bajo" },
            ] as Array<{ id: Filtro; label: string }>).map((f) => (
              <button
                key={f.id}
                onClick={() => setFiltro(f.id)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold uppercase tracking-wider transition-colors ${
                  filtro === f.id ? "bg-navy text-white" : "bg-concrete text-graphite hover:bg-concrete/70"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <p className="text-xs text-graphite">{filtrados.length} de {productos.length} productos</p>

      <Card>
        <CardContent className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-concrete/50 border-b border-border">
                <tr className="text-left text-[0.65rem] font-bold uppercase tracking-wider text-graphite">
                  <th className="px-3 py-2.5"></th>
                  <th className="px-3 py-2.5">Producto</th>
                  <th className="px-3 py-2.5">SKU</th>
                  <th className="px-3 py-2.5">Tipo</th>
                  <th className="px-3 py-2.5 text-right">Variantes</th>
                  {mostrarStock && <th className="px-3 py-2.5 text-right">Stock</th>}
                  <th className="px-3 py-2.5">Estado</th>
                  <th className="px-3 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filtrados.length === 0 ? (
                  <tr><td colSpan={8} className="px-3 py-8 text-center text-sm text-graphite">Sin resultados.</td></tr>
                ) : filtrados.map((p) => (
                  <>
                    <tr
                      key={p.id}
                      className="hover:bg-concrete/30 cursor-pointer"
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
                        <p className="font-medium text-ink">{p.titulo}</p>
                        <p className="text-xs text-graphite">{p.vendor || "—"}</p>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-graphite tabular-nums">{skuAgrupado(p)}</td>
                      <td className="px-3 py-2.5 text-xs text-graphite">{p.tipo || "—"}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{p.num_variantes}</td>
                      {mostrarStock && (
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          <span className={p.sin_stock ? "text-rust font-semibold" : p.stock_bajo ? "text-khaki font-semibold" : "text-ink"}>
                            {p.total_stock}
                          </span>
                        </td>
                      )}
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
                          className="inline-flex items-center text-steel hover:text-navy"
                          title="Abrir en Shopify admin"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      </td>
                    </tr>
                    {expandido === p.id && (
                      <tr key={`${p.id}-vars`} className="bg-concrete/20">
                        <td colSpan={8} className="px-6 py-3">
                          <div className="flex items-center justify-between mb-2">
                            <p className="text-[0.65rem] uppercase tracking-wider text-graphite">Tallas del SKU <span className="font-bold text-ink">{skuAgrupado(p)}</span></p>
                            <p className="text-[0.65rem] text-graphite">{p.variantes.length} {p.variantes.length === 1 ? "variante" : "variantes"}</p>
                          </div>
                          <table className="w-full text-xs">
                            <thead className="text-graphite">
                              <tr>
                                <th className="text-left py-1 font-medium">Talla</th>
                                <th className="text-left py-1 font-medium">Variante</th>
                                <th className="text-left py-1 font-medium">SKU completo</th>
                                <th className="text-right py-1 font-medium">Precio</th>
                                <th className="text-right py-1 font-medium">Stock</th>
                              </tr>
                            </thead>
                            <tbody>
                              {p.variantes.map((v) => {
                                const raiz = skuAgrupado(p);
                                return (
                                  <tr key={v.id}>
                                    <td className="py-1 text-ink font-semibold">{tallaDeVariante(v.sku, raiz)}</td>
                                    <td className="py-1 text-graphite">{v.titulo || "—"}</td>
                                    <td className="py-1 text-graphite tabular-nums">{v.sku || "—"}</td>
                                    <td className="py-1 text-right text-ink tabular-nums">${v.precio.toLocaleString()}</td>
                                    <td className={`py-1 text-right tabular-nums ${v.stock <= 0 ? "text-rust font-semibold" : v.stock <= 5 ? "text-khaki" : "text-ink"}`}>{v.stock}</td>
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

  if (resumen.isLoading) return <LoadingState label="Cargando inventario..." />;
  if (resumen.error) return <ErrorState error={resumen.error} onRetry={() => resumen.refetch()} />;

  const r = resumen.data;

  return (
    <PageShell
      title="Inventario Shopify"
      subtitle="Gestión del catálogo · activos, borradores y stock"
      isFetching={activos.isFetching || borradores.isFetching}
      onRefresh={() => { resumen.refetch(); activos.refetch(); borradores.refetch(); }}
    >
      {/* KPIs principales */}
      {r && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <KpiCard label="Productos activos"     value={String(r.activos)}    meta="Visibles en tienda"  accent="teal" />
            <KpiCard label="Productos en borrador" value={String(r.borrador)}   meta="Pendientes publicar" accent="khaki" />
            <KpiCard label="Archivados"            value={String(r.archivados)} meta="Descontinuados"      accent="steel" />
          </div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <KpiCard label="SKUs activos"      value={String(r.total_skus)}     meta="Variantes" accent="navy" />
            <KpiCard label="Unidades en stock" value={String(r.total_unidades)} meta="Total" accent="navy" />
            <KpiCard label="Sin stock"  value={String(r.sin_stock)}  meta="SKUs en cero"   accent={r.sin_stock > 0 ? "rust" : "steel"} danger={r.sin_stock > 10} />
            <KpiCard label="Stock bajo" value={String(r.stock_bajo)} meta="1-5 unidades"   accent={r.stock_bajo > 0 ? "khaki" : "steel"} />
          </div>
        </>
      )}

      {/* Tabla con tabs activos / borradores */}
      <Tabs defaultValue="activos">
        <TabsList>
          <TabsTrigger value="activos">Activos ({activos.data?.total || 0})</TabsTrigger>
          <TabsTrigger value="borradores">Borradores ({borradores.data?.total || 0})</TabsTrigger>
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
      </Tabs>

      <p className="text-[0.65rem] text-graphite/70 mt-2">
        Próximamente: productos sin venta en 90 días · reposición sugerida basada en velocidad de venta.
      </p>
    </PageShell>
  );
}
