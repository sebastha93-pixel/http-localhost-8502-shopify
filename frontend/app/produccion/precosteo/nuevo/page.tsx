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
import { Plus, Trash2, Save, Loader2, AlertCircle } from "lucide-react";

interface LineaForm {
  categoria: string;
  item: string;
  valor_unitario: string;
  cantidad: string;
  iva: string;
  fija?: boolean;   // true = renglón de plantilla (no se borra, item read-only)
}

/**
 * Plantilla estándar MALE'DENIM — orden de aparición en el form.
 * Si quieres editar/reordenar items, solo cambia este array.
 */
const PLANTILLA: { categoria: string; items: string[] }[] = [
  { categoria: "MP", items: [
    "Tela principal", "Forro bolsillo", "Etiqueta cuero",
    "Marquilla talla", "Marquilla composición",
  ]},
  { categoria: "PROCESO EN MP", items: [
    "Lavandería", "Tintura especial",
  ]},
  { categoria: "PROCESO", items: [
    "Corte", "Confección", "Terminación", "Bordado/estampado",
  ]},
  { categoria: "INSUMO CONFECCION", items: [
    "Hilo", "Cierre", "Botón", "Remaches", "Elástico",
  ]},
  { categoria: "INSUMO EMPAQUE", items: [
    "Bolsa", "Sticker", "Caja", "Cinta",
  ]},
  { categoria: "INSUMO TERMINACION", items: [
    "Etiqueta colgante", "Hilo colgante", "Precinto seguridad",
  ]},
];

function lineasIniciales(): LineaForm[] {
  const out: LineaForm[] = [];
  for (const g of PLANTILLA) {
    for (const it of g.items) {
      out.push({
        categoria: g.categoria, item: it,
        valor_unitario: "", cantidad: "1", iva: "0",
        fija: true,
      });
    }
  }
  return out;
}

export default function NuevoPrecosteoPage() {
  const router = useRouter();
  const CATEGORIAS = PLANTILLA.map((p) => p.categoria);

  const [codigo, setCodigo] = useState("");
  const [nombre, setNombre] = useState("");
  const [tela, setTela] = useState("");
  const [color, setColor] = useState("");
  const [iva, setIva] = useState("19");
  const [margen, setMargen] = useState("60");
  const [lineas, setLineas] = useState<LineaForm[]>(lineasIniciales());
  const [err, setErr] = useState("");

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
          iva: parseFloat(l.iva || "0") || 0,
        }));
      if (items.length === 0) throw new Error("Llena al menos un renglón con valor unitario.");
      return api.post<{ id: string }>("/api/produccion/precosteo", {
        codigo_referencia: codigo.trim(),
        nombre: nombre.trim(),
        tela: tela.trim() || null,
        color: color.trim() || null,
        iva_pct: parseFloat(iva) || 19,
        margen: parseFloat(margen) || 0,
        items,
      });
    },
    onSuccess: (data) => router.push(`/produccion/precosteo/${data.id}`),
    onError: (e: Error) => setErr(e.message),
  });

  function actualizar(idx: number, campo: keyof LineaForm, valor: string) {
    setLineas((prev) => prev.map((l, i) => (i === idx ? { ...l, [campo]: valor } : l)));
  }
  function agregarOtro() {
    setLineas((prev) => [...prev, {
      categoria: CATEGORIAS[0], item: "",
      valor_unitario: "", cantidad: "1", iva: "0",
      fija: false,
    }]);
  }
  function quitar(idx: number) {
    setLineas((prev) => prev.filter((_, i) => i !== idx));
  }

  const totalSin = lineas.reduce((s, l) => s + (parseFloat(l.valor_unitario || "0") || 0) * (parseFloat(l.cantidad || "0") || 0), 0);
  const totalIva = lineas.reduce((s, l) => s + (parseFloat(l.iva || "0") || 0), 0);
  const totalCon = totalSin + totalIva;
  const precioSugerido = totalCon * (1 + (parseFloat(margen || "0") || 0) / 100);

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
        onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }}
        className="space-y-4"
      >
        <Card>
          <CardContent className="p-5 space-y-4">
            <p className="section-label">Cabecera</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Input label="Código referencia *" value={codigo} onChange={setCodigo} required placeholder="14500-1" />
              <Input label="Nombre *"             value={nombre} onChange={setNombre} required placeholder="SKINNY OSCURO" />
              <Input label="Tela"                 value={tela} onChange={setTela} placeholder="SANDDENIM" />
              <Input label="Color"                value={color} onChange={setColor} placeholder="Índigo" />
              <Input label="IVA %"                value={iva} onChange={setIva} inputMode="decimal" />
              <Input label="Margen %"             value={margen} onChange={setMargen} inputMode="decimal" placeholder="60" />
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
                    <th className="px-2 py-2 w-[110px]">IVA $</th>
                    <th className="px-2 py-2 w-[120px] text-right">Total c/IVA</th>
                    <th className="px-2 py-2 w-[30px]" />
                  </tr>
                </thead>
                <tbody>
                  {gruposUI.map((g) => (
                    <Fragment key={g.categoria}>
                      <tr className="bg-cloud/60 border-b border-border">
                        <td colSpan={6} className="px-2 py-1.5 text-[0.6rem] font-bold uppercase tracking-[0.16em] text-ink-900">
                          {g.categoria}
                        </td>
                      </tr>
                      {g.indices.map((idx) => {
                        const l = lineas[idx];
                        const ts = (parseFloat(l.valor_unitario || "0") || 0) * (parseFloat(l.cantidad || "0") || 0);
                        const tc = ts + (parseFloat(l.iva || "0") || 0);
                        return (
                          <tr key={idx} className="border-b border-border/40">
                            <td className="px-2 py-1.5">
                              {l.fija ? (
                                <span className="text-ink-900">{l.item}</span>
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
                            <td className="px-2 py-1.5">
                              <input value={l.iva} onChange={(e) => actualizar(idx, "iva", e.target.value)}
                                inputMode="decimal"
                                className="w-full rounded-sm border border-border bg-white px-2 py-1 text-xs text-right tabular" />
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
                    <td colSpan={3} className="px-2 py-2 text-right text-[0.65rem] uppercase tracking-widest text-graphite">Total sin IVA</td>
                    <td colSpan={2} className="px-2 py-2 text-right tabular font-semibold">${totalSin.toLocaleString("es-CO", { maximumFractionDigits: 0 })}</td>
                    <td />
                  </tr>
                  <tr>
                    <td colSpan={3} className="px-2 py-1 text-right text-[0.65rem] uppercase tracking-widest text-graphite">Total con IVA</td>
                    <td colSpan={2} className="px-2 py-1 text-right tabular font-semibold text-ink-900">${totalCon.toLocaleString("es-CO", { maximumFractionDigits: 0 })}</td>
                    <td />
                  </tr>
                  <tr>
                    <td colSpan={3} className="px-2 py-1 text-right text-[0.65rem] uppercase tracking-widest text-graphite">
                      Precio sugerido ({margen || 0}%)
                    </td>
                    <td colSpan={2} className="px-2 py-1 text-right tabular font-bold text-navy-600 text-sm">
                      ${precioSugerido.toLocaleString("es-CO", { maximumFractionDigits: 0 })}
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
