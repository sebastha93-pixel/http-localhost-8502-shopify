"use client";

/**
 * Nuevo precosteo — plantilla estática.
 * 24 líneas fijas por categoría + botón "+ Otro" para renglones especiales.
 * Se llenan solo valor unitario, cantidad y (opcional) IVA.
 */
import { Fragment, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Plus, Trash2, Save, Loader2, AlertCircle, CheckCircle } from "lucide-react";

interface LineaForm {
  categoria: string;
  item: string;
  valor_unitario: string;
  cantidad: string;
  aplica_iva: boolean;   // si true, IVA se calcula automático con iva_pct global
  fija?: boolean;        // true = renglón de plantilla (no se borra, categoría fija)
  item_editable?: boolean; // true = puedes editar el nombre del item (renglón "Otro")
  placeholder?: string;    // placeholder del input cuando item_editable
}

/**
 * Plantilla estándar MALE'DENIM — orden de aparición en el form.
 * Si quieres editar/reordenar items, solo cambia este array.
 */
const PLANTILLA: { categoria: string; items: string[] }[] = [
  { categoria: "MATERIA PRIMA", items: [
    "Tela principal", "Forro de bolsillo",
  ]},
  { categoria: "PROCESO EN MATERIA PRIMA", items: [
    "Corte", "Confección", "Lavandería", "Teñido especial",
    "Terminación", "Bordado/estampado",
  ]},
  { categoria: "INSUMO CONFECCION", items: [
    "Cierre", "Marquilla talla",
  ]},
  { categoria: "INSUMO TERMINACION", items: [
    "Código de barras", "Instrucción de lavado", "Bolsa",
    "Botón 27 L", "Remache", "Garra", "Pretinera", "Apliques",
  ]},
];

function lineasIniciales(): LineaForm[] {
  const out: LineaForm[] = [];
  for (const g of PLANTILLA) {
    for (const it of g.items) {
      out.push({
        categoria: g.categoria, item: it,
        valor_unitario: "", cantidad: "1", aplica_iva: false,
        fija: true,
      });
    }
    // Fila "Otro" editable al final de cada categoría
    out.push({
      categoria: g.categoria, item: "",
      valor_unitario: "", cantidad: "1", aplica_iva: false,
      fija: true, item_editable: true, placeholder: "Otro (opcional)",
    });
  }
  return out;
}

function ivaDeLinea(l: LineaForm, ivaPct: number): number {
  if (!l.aplica_iva) return 0;
  const v = parseFloat(l.valor_unitario || "0") || 0;
  const q = parseFloat(l.cantidad || "0") || 0;
  return Math.round(v * q * (ivaPct / 100));
}

export default function NuevoPrecosteoPage() {
  const router = useRouter();
  const CATEGORIAS = PLANTILLA.map((p) => p.categoria);

  const [codigo, setCodigo] = useState("");
  const [nombre, setNombre] = useState("");
  const [tela, setTela] = useState("");
  const [color, setColor] = useState("");
  const [iva, setIva] = useState("19");
  const [precioVenta, setPrecioVenta] = useState("");
  const [lineas, setLineas] = useState<LineaForm[]>(lineasIniciales());
  const [err, setErr] = useState("");
  const [confirmar, setConfirmar] = useState(false);

  // Tela final normalizada a mayúsculas — se cruza con inventario al momento del corte
  const telaFinal = tela.trim().toUpperCase();

  const ivaPct = parseFloat(iva) || 0;
  const precioVentaNum = parseFloat(precioVenta || "0") || 0;

  const mut = useMutation({
    mutationFn: () => {
      // Solo mandamos líneas con valor > 0 o cantidad > 0 (evita renglones vacíos de plantilla)
      const items = lineas
        .filter((l) => l.item.trim() && (parseFloat(l.valor_unitario || "0") > 0 || parseFloat(l.cantidad || "0") > 0))
        .map((l) => ({
          categoria: l.categoria,
          item: l.item.trim(),
          valor_unitario: parseFloat(l.valor_unitario || "0") || 0,
          cantidad: parseFloat(l.cantidad || "0") || 0,
          iva: ivaDeLinea(l, ivaPct),
        }));
      if (items.length === 0) throw new Error("Llena al menos un renglón con valor unitario.");
      // El precio de venta que el usuario teclea YA INCLUYE IVA.
      // Para calcular la utilidad real: sacar el IVA de la venta y compararlo
      // contra el costo SIN IVA (el IVA de compras es crédito recuperable).
      const costoSin = items.reduce((s, it) => s + it.valor_unitario * it.cantidad, 0);
      const precioNeto = precioVentaNum > 0 ? precioVentaNum / (1 + (ivaPct || 0) / 100) : 0;
      const margen = precioNeto > 0 && costoSin > 0
        ? ((precioNeto - costoSin) / costoSin) * 100
        : 0;
      return api.post<{ id: string }>("/api/produccion/precosteo", {
        codigo_referencia: codigo.trim(),
        nombre: nombre.trim(),
        tela: telaFinal || null,
        color: color.trim() || null,
        iva_pct: ivaPct || 19,
        margen,
        items,
      });
    },
    onSuccess: (data) => router.push(`/produccion/precosteo/${data.id}`),
    onError: (e: Error) => setErr(e.message),
  });

  function actualizar(idx: number, campo: keyof LineaForm, valor: string | boolean) {
    setLineas((prev) => prev.map((l, i) => (i === idx ? { ...l, [campo]: valor } : l)));
  }
  function agregarOtro() {
    setLineas((prev) => [...prev, {
      categoria: CATEGORIAS[0], item: "",
      valor_unitario: "", cantidad: "1", aplica_iva: false,
      fija: false,
    }]);
  }
  function quitar(idx: number) {
    setLineas((prev) => prev.filter((_, i) => i !== idx));
  }

  const totalSin = lineas.reduce((s, l) => s + (parseFloat(l.valor_unitario || "0") || 0) * (parseFloat(l.cantidad || "0") || 0), 0);
  const totalIva = lineas.reduce((s, l) => s + ivaDeLinea(l, ivaPct), 0);
  const totalCon = totalSin + totalIva;
  // Precio de venta que teclea el usuario YA INCLUYE IVA.
  // Sacamos el neto para calcular utilidad real (vs costo sin IVA).
  const precioNetoVenta = precioVentaNum > 0 ? precioVentaNum / (1 + ivaPct / 100) : 0;
  const utilidad = precioNetoVenta > 0 && totalSin > 0 ? precioNetoVenta - totalSin : 0;
  const utilidadPct = precioNetoVenta > 0 && totalSin > 0 ? (utilidad / totalSin) * 100 : 0;

  // Agrupamos por categoría para dibujar sub-encabezados en la tabla
  const gruposUI: { categoria: string; indices: number[] }[] = [];
  lineas.forEach((l, i) => {
    const last = gruposUI[gruposUI.length - 1];
    if (last && last.categoria === l.categoria) last.indices.push(i);
    else gruposUI.push({ categoria: l.categoria, indices: [i] });
  });

  return (
    <PageShell title="Nuevo precosteo" subtitle="Plantilla estándar · llena valor y cantidad">
      <form
        onSubmit={(e) => { e.preventDefault(); setErr(""); setConfirmar(true); }}
        className="space-y-4"
      >
        <Card>
          <CardContent className="p-5 space-y-4">
            <p className="section-label">Cabecera</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Input label="Código referencia *" value={codigo} onChange={setCodigo} required placeholder="14500-1" />
              <Input label="Nombre *"             value={nombre} onChange={setNombre} required placeholder="SKINNY OSCURO" />
              <Input label="Tela *" value={tela} onChange={(v) => setTela(v.toUpperCase())} required placeholder="SANDDENIM 12OZ" />
              <Input label="Color"                value={color} onChange={setColor} placeholder="Índigo" />
              <Input label="IVA %"                value={iva} onChange={setIva} inputMode="decimal" />
              <Input label="Precio de venta (con IVA)" value={precioVenta} onChange={setPrecioVenta} inputMode="decimal" placeholder="120000" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5 space-y-3">
            <div className="flex items-baseline justify-between">
              <p className="section-label">Líneas ({lineas.length})</p>
              <button type="button" onClick={agregarOtro}
                className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-3 py-1.5 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud">
                <Plus className="h-3.5 w-3.5" /> Otro
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite border-b border-border">
                    <th className="px-2 py-2">Item</th>
                    <th className="px-2 py-2 w-[130px]">Valor unit.</th>
                    <th className="px-2 py-2 w-[90px]">Cantidad</th>
                    <th className="px-2 py-2 w-[60px] text-center">IVA</th>
                    <th className="px-2 py-2 w-[100px] text-right">IVA $</th>
                    <th className="px-2 py-2 w-[120px] text-right">Total c/IVA</th>
                    <th className="px-2 py-2 w-[30px]" />
                  </tr>
                </thead>
                <tbody>
                  {gruposUI.map((g) => (
                    <Fragment key={g.categoria}>
                      <tr className="bg-cloud/60 border-b border-border">
                        <td colSpan={7} className="px-2 py-1.5 text-[0.6rem] font-bold uppercase tracking-[0.16em] text-ink-900">
                          {g.categoria}
                        </td>
                      </tr>
                      {g.indices.map((idx) => {
                        const l = lineas[idx];
                        const ts = (parseFloat(l.valor_unitario || "0") || 0) * (parseFloat(l.cantidad || "0") || 0);
                        const ivaMonto = ivaDeLinea(l, ivaPct);
                        const tc = ts + ivaMonto;
                        return (
                          <tr key={idx} className="border-b border-border/40">
                            <td className="px-2 py-1.5">
                              {l.fija && !l.item_editable ? (
                                <span className="text-ink-900">{l.item}</span>
                              ) : l.fija && l.item_editable ? (
                                <input value={l.item} onChange={(e) => actualizar(idx, "item", e.target.value)}
                                  placeholder={l.placeholder || "Otro"}
                                  className="w-full rounded-sm border border-border bg-white px-2 py-1 text-xs italic text-graphite placeholder:text-graphite/50" />
                              ) : (
                                <div className="flex items-center gap-1">
                                  <select value={l.categoria} onChange={(e) => actualizar(idx, "categoria", e.target.value)}
                                    className="rounded-sm border border-border bg-white px-1.5 py-1 text-[0.65rem] w-[130px]">
                                    {CATEGORIAS.map((c) => <option key={c} value={c}>{c}</option>)}
                                  </select>
                                  <input value={l.item} onChange={(e) => actualizar(idx, "item", e.target.value)}
                                    placeholder="Item"
                                    className="flex-1 rounded-sm border border-border bg-white px-2 py-1 text-xs" />
                                </div>
                              )}
                            </td>
                            <td className="px-2 py-1.5">
                              <input value={l.valor_unitario} onChange={(e) => actualizar(idx, "valor_unitario", e.target.value)}
                                inputMode="decimal" placeholder="0"
                                className="w-full rounded-sm border border-border bg-white px-2 py-1 text-xs text-right tabular" />
                            </td>
                            <td className="px-2 py-1.5">
                              <input value={l.cantidad} onChange={(e) => actualizar(idx, "cantidad", e.target.value)}
                                inputMode="decimal"
                                className="w-full rounded-sm border border-border bg-white px-2 py-1 text-xs text-right tabular" />
                            </td>
                            <td className="px-2 py-1.5 text-center">
                              <input type="checkbox" checked={l.aplica_iva}
                                onChange={(e) => actualizar(idx, "aplica_iva", e.target.checked)} />
                            </td>
                            <td className="px-2 py-1.5 text-right tabular text-graphite">
                              {ivaMonto > 0 ? `$${ivaMonto.toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular text-ink-900 font-medium">
                              ${tc.toLocaleString("es-CO", { maximumFractionDigits: 0 })}
                            </td>
                            <td className="px-2 py-1.5 text-center">
                              {!l.fija && (
                                <button type="button" onClick={() => quitar(idx)} className="text-terracotta hover:text-crimson">
                                  <Trash2 className="h-3 w-3" />
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </Fragment>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-border">
                    <td colSpan={4} className="px-2 py-2 text-right text-[0.65rem] uppercase tracking-widest text-graphite">Total sin IVA</td>
                    <td colSpan={2} className="px-2 py-2 text-right tabular font-semibold">${totalSin.toLocaleString("es-CO", { maximumFractionDigits: 0 })}</td>
                    <td />
                  </tr>
                  <tr>
                    <td colSpan={4} className="px-2 py-1 text-right text-[0.65rem] uppercase tracking-widest text-graphite">Total con IVA</td>
                    <td colSpan={2} className="px-2 py-1 text-right tabular font-semibold text-ink-900">${totalCon.toLocaleString("es-CO", { maximumFractionDigits: 0 })}</td>
                    <td />
                  </tr>
                  <tr>
                    <td colSpan={4} className="px-2 py-1 text-right text-[0.65rem] uppercase tracking-widest text-graphite">Precio venta (con IVA)</td>
                    <td colSpan={2} className="px-2 py-1 text-right tabular font-semibold text-ink-900">
                      {precioVentaNum > 0 ? `$${precioVentaNum.toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}
                    </td>
                    <td />
                  </tr>
                  <tr>
                    <td colSpan={4} className="px-2 py-1 text-right text-[0.65rem] uppercase tracking-widest text-graphite">Precio venta (neto sin IVA)</td>
                    <td colSpan={2} className="px-2 py-1 text-right tabular text-graphite">
                      {precioNetoVenta > 0 ? `$${precioNetoVenta.toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}
                    </td>
                    <td />
                  </tr>
                  <tr>
                    <td colSpan={4} className="px-2 py-1 text-right text-[0.65rem] uppercase tracking-widest text-graphite">
                      Utilidad {precioVentaNum > 0 ? `(${utilidadPct.toFixed(1)}%)` : ""}
                    </td>
                    <td colSpan={2} className={`px-2 py-1 text-right tabular font-bold text-sm ${utilidad >= 0 ? "text-teal" : "text-terracotta"}`}>
                      {precioVentaNum > 0 ? `$${utilidad.toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          </CardContent>
        </Card>

        {err && (
          <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5" /> {err}
          </div>
        )}

        <div className="sticky bottom-0 bg-white/95 backdrop-blur border-t border-border py-3 flex items-center justify-between gap-3">
          <p className="text-xs text-graphite">Se guardará como <span className="font-semibold text-ink-900">Borrador</span>. Puedes firmar después.</p>
          <button type="submit" disabled={mut.isPending}
            className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700 disabled:opacity-40">
            {mut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Guardar borrador
          </button>
        </div>
      </form>

      {/* Modal de confirmación — mitiga errores mostrando qué tela se seleccionó */}
      {confirmar && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/60 p-4">
          <div className="w-full max-w-md rounded-sm bg-white border border-border shadow-2xl">
            <div className="px-5 py-4 border-b border-border">
              <p className="section-label">Confirmar guardado</p>
            </div>
            <div className="p-5 space-y-3">
              <p className="text-sm text-ink-900">
                Vas a crear el precosteo <span className="font-semibold">{codigo || "(sin código)"}</span>.
              </p>
              <div className="rounded-sm border border-navy-600/30 bg-navy-600/5 p-3 space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-graphite">Nombre</span>
                  <span className="font-semibold text-ink-900">{nombre || "—"}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-graphite">Tela</span>
                  <span className="font-bold text-navy-600 uppercase">{telaFinal || "SIN TELA"}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-graphite">Color</span>
                  <span className="text-ink-900">{color || "—"}</span>
                </div>
                <div className="flex justify-between text-xs pt-2 border-t border-border/40">
                  <span className="text-graphite">Costo total con IVA</span>
                  <span className="tabular font-semibold text-ink-900">
                    ${totalCon.toLocaleString("es-CO", { maximumFractionDigits: 0 })}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-graphite">Precio venta (con IVA)</span>
                  <span className="tabular font-semibold text-ink-900">
                    {precioVentaNum > 0 ? `$${precioVentaNum.toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-graphite">Precio venta (neto sin IVA)</span>
                  <span className="tabular text-graphite">
                    {precioNetoVenta > 0 ? `$${precioNetoVenta.toLocaleString("es-CO", { maximumFractionDigits: 0 })}` : "—"}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-graphite">Utilidad (neto vs costo sin IVA)</span>
                  <span className={`tabular font-semibold ${utilidad >= 0 ? "text-teal" : "text-terracotta"}`}>
                    {precioVentaNum > 0 ? `$${utilidad.toLocaleString("es-CO", { maximumFractionDigits: 0 })} (${utilidadPct.toFixed(1)}%)` : "—"}
                  </span>
                </div>
              </div>
              <p className="text-[0.7rem] text-graphite">
                Se guardará como <span className="font-semibold text-ink-900">borrador</span>.
                Podrás editarlo hasta que lo firmes.
              </p>
            </div>
            <div className="px-5 py-4 border-t border-border flex justify-end gap-2">
              <button type="button" onClick={() => setConfirmar(false)}
                className="rounded-sm border border-border bg-card px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-ink-900 hover:bg-cloud">
                Volver a editar
              </button>
              <button type="button" onClick={() => { setConfirmar(false); mut.mutate(); }}
                disabled={mut.isPending}
                className="inline-flex items-center gap-2 rounded-sm bg-teal px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
                {mut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle className="h-4 w-4" />}
                Confirmar y guardar
              </button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}

function Input({ label, value, onChange, required = false, placeholder = "", inputMode }: {
  label: string; value: string; onChange: (v: string) => void; required?: boolean; placeholder?: string; inputMode?: "decimal" | "numeric";
}) {
  return (
    <div>
      <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        required={required} placeholder={placeholder} inputMode={inputMode}
        className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
    </div>
  );
}
