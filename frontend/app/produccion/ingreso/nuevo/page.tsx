"use client";

/**
 * Nuevo ingreso de tela — pantalla móvil-primero para bodega.
 *
 * Flujo:
 * 1. Cabecera: textilera, tipo de documento, número, fecha.
 * 2. Filas de rollos: se van agregando una por una. Campos grandes,
 *    teclado numérico donde aplica (metros, ancho, costo).
 * 3. Guardar → backend crea consecutivos y regresa los IDs.
 * 4. Redirige al detalle del ingreso para imprimir etiquetas masivas.
 */
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { PageShell } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Plus, Trash2, Save, Loader2, AlertCircle, ScanLine, CheckCircle } from "lucide-react";

interface RolloForm {
  numero_rollo: string;
  lote_fabrica: string;
  tono: string;
  referencia_tela: string;
  descripcion_tela: string;
  costo_metro: string;
  metros_inicial: string;
}

function rolloVacio(): RolloForm {
  return {
    numero_rollo: "", lote_fabrica: "", tono: "",
    referencia_tela: "", descripcion_tela: "",
    costo_metro: "", metros_inicial: "",
  };
}

const TIPOS_DOC = [
  { v: "remision",      l: "Remisión" },
  { v: "factura",       l: "Factura" },
  { v: "lista_empaque", l: "Lista de empaque" },
  { v: "consulta",      l: "Consulta (serial)" },
];

export default function NuevoIngresoPage() {
  const router = useRouter();
  const hoy = new Date().toISOString().slice(0, 10);

  const [textileraId, setTextileraId] = useState("");   // "" = ninguna, "otra" = nueva
  const [textilera, setTextilera] = useState("");        // nombre final
  const [textileraOtra, setTextileraOtra] = useState("");
  const [nit, setNit] = useState("");

  // Textileras del directorio de proveedores (con su NIT para el cruce Siigo)
  const textilerasQ = useQuery<{ confeccionistas: { id: string; nombre: string; documento?: string }[] }>({
    queryKey: ["produccion", "confeccionistas", "textilera"],
    queryFn: () => api.get("/api/produccion/confeccionistas?tipo=textilera&incluir_inactivos=false"),
  });
  const textileras = textilerasQ.data?.confeccionistas || [];

  function elegirTextilera(id: string) {
    setTextileraId(id);
    if (id === "otra" || id === "") {
      setTextilera(""); setNit("");
      return;
    }
    const t = textileras.find((x) => x.id === id);
    if (t) { setTextilera(t.nombre); setNit(t.documento || ""); }
  }
  const [tipoDoc, setTipoDoc] = useState("remision");
  const [numeroDoc, setNumeroDoc] = useState("");
  const [fecha, setFecha] = useState(hoy);
  const [ordenCompra, setOrdenCompra] = useState("");
  const [observaciones, setObservaciones] = useState("");
  const [rollos, setRollos] = useState<RolloForm[]>([rolloVacio()]);
  const [err, setErr] = useState("");
  const [escaneando, setEscaneando] = useState(false);
  const [msgEscaneo, setMsgEscaneo] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function escanearDocumento(f: File) {
    setErr("");
    setMsgEscaneo("");
    setEscaneando(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const token = getToken();
      const res = await fetch(`${API_BASE}/api/produccion/ingreso/parse-documento`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const text = await res.text();
      if (!res.ok) {
        throw new Error(text.slice(0, 200) || `HTTP ${res.status}`);
      }
      const json = JSON.parse(text);
      const d = json.data || {};
      // Prellenar cabecera
      const tx = (d.textilera || "").toString();
      const known = textileras.find((t) => tx.toUpperCase().includes(t.nombre.toUpperCase())
        || t.nombre.toUpperCase().includes(tx.toUpperCase()));
      if (known) { elegirTextilera(known.id); }
      else if (tx) { setTextileraId("otra"); setTextilera(tx); setTextileraOtra(tx); }
      if (d.nit_textilera && !known) setNit(String(d.nit_textilera));
      if (d.tipo_documento)    setTipoDoc(String(d.tipo_documento));
      if (d.numero_documento)  setNumeroDoc(String(d.numero_documento));
      if (d.fecha)             setFecha(String(d.fecha));
      if (d.orden_compra)      setOrdenCompra(String(d.orden_compra));
      if (d.observaciones)     setObservaciones(String(d.observaciones));
      // Prellenar rollos
      const rolls: RolloForm[] = (d.rollos || []).map((r: Record<string, unknown>) => ({
        numero_rollo:    r.numero_rollo     != null ? String(r.numero_rollo)    : "",
        lote_fabrica:    r.lote_fabrica     != null ? String(r.lote_fabrica)    : "",
        tono:            r.tono             != null ? String(r.tono)            : "",
        referencia_tela: r.referencia_tela  != null ? String(r.referencia_tela) : "",
        descripcion_tela:r.descripcion_tela != null ? String(r.descripcion_tela): "",
        costo_metro:     r.costo_metro      != null ? String(r.costo_metro)     : "",
        metros_inicial:  r.metros_inicial   != null ? String(r.metros_inicial)  : "",
      }));
      if (rolls.length > 0) setRollos(rolls);
      setMsgEscaneo(`✓ ${rolls.length} rollo(s) extraídos. Revisa y corrige antes de guardar.`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Error escaneando";
      setErr(`Escaneo falló: ${msg}`);
    } finally {
      setEscaneando(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const mut = useMutation({
    mutationFn: () => {
      const textileraFinal = textileraId === "otra" ? textileraOtra.trim() : textilera;
      if (!textileraFinal) throw new Error("Selecciona la textilera");
      const rollosValidos = rollos
        .filter((r) => r.descripcion_tela.trim() && parseFloat(r.metros_inicial || "0") > 0)
        .map((r) => ({
          numero_rollo: r.numero_rollo || null,
          lote_fabrica: r.lote_fabrica || null,
          tono: r.tono || null,
          referencia_tela: r.referencia_tela || null,
          descripcion_tela: r.descripcion_tela.trim().toUpperCase(),
          costo_metro: r.costo_metro ? parseFloat(r.costo_metro) : null,
          metros_inicial: parseFloat(r.metros_inicial),
        }));
      if (rollosValidos.length === 0) throw new Error("Agrega al menos un rollo con descripción y metros");
      return api.post<{ ok: boolean; ingreso: { id: string; numero_ingreso: string } }>(
        "/api/produccion/ingreso",
        {
          textilera: textileraFinal,
          nit_textilera: nit || null,
          numero_documento: numeroDoc,
          tipo_documento: tipoDoc,
          fecha,
          orden_compra: ordenCompra || null,
          observaciones: observaciones || null,
          rollos: rollosValidos,
        },
      );
    },
    onSuccess: (data) => {
      router.push(`/produccion/ingreso/${data.ingreso.id}`);
    },
    onError: (e: Error) => setErr(e.message),
  });

  function actualizarRollo(idx: number, campo: keyof RolloForm, valor: string) {
    setRollos((prev) => prev.map((r, i) => (i === idx ? { ...r, [campo]: valor } : r)));
  }
  function agregarRollo() {
    // Copia campos comunes del último rollo (descripción tela, ancho, costo)
    // para acelerar la digitación cuando son iguales.
    const last = rollos[rollos.length - 1];
    setRollos([
      ...rollos,
      { ...rolloVacio(),
        descripcion_tela: last?.descripcion_tela || "",
        costo_metro: last?.costo_metro || "",
        referencia_tela: last?.referencia_tela || "",
      },
    ]);
  }
  function quitarRollo(idx: number) {
    setRollos((prev) => prev.filter((_, i) => i !== idx));
  }

  const totalMetros = rollos.reduce((s, r) => s + (parseFloat(r.metros_inicial || "0") || 0), 0);
  const totalRollosVal = rollos.filter((r) => r.descripcion_tela && parseFloat(r.metros_inicial || "0") > 0).length;

  return (
    <PageShell
      title="Nuevo ingreso"
      subtitle="Recepción de tela desde textilera"
    >
      <form
        onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }}
        className="space-y-4"
      >
        {/* Escanear remisión con IA */}
        <Card>
          <CardContent className="p-5">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="h-10 w-10 shrink-0 rounded-md grid place-items-center bg-navy-600/10 text-navy-600">
                  <ScanLine className="h-5 w-5" />
                </div>
                <div>
                  <p className="font-display text-base font-medium text-ink-900">Escanear remisión</p>
                  <p className="text-xs text-graphite mt-0.5">
                    Sube el PDF o foto de la remisión de la textilera. La IA extrae cabecera + rollos.
                    Revisa antes de guardar.
                  </p>
                </div>
              </div>
              <input ref={fileRef} type="file" accept="application/pdf,image/*" className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) escanearDocumento(f); }} />
              <button type="button" onClick={() => fileRef.current?.click()} disabled={escaneando}
                className="inline-flex items-center gap-2 rounded-sm border border-navy-600 bg-navy-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700 disabled:opacity-40 shrink-0">
                {escaneando ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanLine className="h-4 w-4" />}
                {escaneando ? "Analizando…" : "Subir remisión"}
              </button>
            </div>
            {msgEscaneo && (
              <div className="mt-3 rounded-sm border border-teal/40 bg-teal/5 px-3 py-2 text-xs text-teal flex items-center gap-2">
                <CheckCircle className="h-3.5 w-3.5" /> {msgEscaneo}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Cabecera */}
        <Card>
          <CardContent className="p-5 space-y-4">
            <p className="section-label">Cabecera</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">Textilera *</label>
                <select value={textileraId} onChange={(e) => elegirTextilera(e.target.value)}
                  className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm">
                  <option value="">Selecciona una textilera…</option>
                  {textileras.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
                  <option value="otra">+ Otra (regístrala en Proveedores)</option>
                </select>
                {textileras.length === 0 && !textilerasQ.isLoading && (
                  <p className="mt-1 text-[0.6rem] text-terracotta">
                    No hay textileras. Créalas en{" "}
                    <a href="/produccion/confeccionistas" className="underline font-semibold">Proveedores</a>{" "}
                    con tipo &ldquo;Textilera&rdquo; y su NIT.
                  </p>
                )}
                {textileraId === "otra" && (
                  <input value={textileraOtra} onChange={(e) => setTextileraOtra(e.target.value)}
                    placeholder="Nombre de la textilera"
                    className="mt-2 w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
                )}
              </div>
              <div>
                <Input label="NIT (para cruce con Siigo)" value={nit} onChange={setNit} />
                {textileraId && textileraId !== "otra" && !nit && (
                  <p className="mt-1 text-[0.6rem] text-ochre">
                    Esta textilera no tiene NIT — agrégalo en Proveedores para poder cruzar la compra.
                  </p>
                )}
              </div>
              <div>
                <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">Tipo de documento</label>
                <select value={tipoDoc} onChange={(e) => setTipoDoc(e.target.value)}
                  className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm">
                  {TIPOS_DOC.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
                </select>
              </div>
              <Input label="Número del documento" value={numeroDoc} onChange={setNumeroDoc} required placeholder="Nº remisión / factura" />
              <Input label="Fecha" type="date" value={fecha} onChange={setFecha} required />
              <Input label="Orden de compra (opcional)" value={ordenCompra} onChange={setOrdenCompra} />
              <div className="md:col-span-2">
                <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">Observaciones</label>
                <textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)}
                  rows={2}
                  className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Rollos */}
        <Card>
          <CardContent className="p-5 space-y-3">
            <div className="flex items-baseline justify-between">
              <p className="section-label">Rollos ({totalRollosVal})</p>
              <p className="text-xs text-graphite tabular">
                Total: <span className="font-semibold text-ink-900">{totalMetros.toFixed(2)} m</span>
              </p>
            </div>

            <div className="space-y-3">
              {rollos.map((r, idx) => (
                <div key={idx} className="rounded-sm border border-border bg-cloud/30 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[0.62rem] uppercase tracking-[0.12em] text-graphite font-semibold">
                      Rollo #{idx + 1}
                    </span>
                    {rollos.length > 1 && (
                      <button type="button" onClick={() => quitarRollo(idx)}
                        className="text-terracotta hover:text-crimson">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
                    <Cell label="Nº rollo"  value={r.numero_rollo} onChange={(v) => actualizarRollo(idx, "numero_rollo", v)} />
                    <Cell label="Lote"      value={r.lote_fabrica} onChange={(v) => actualizarRollo(idx, "lote_fabrica", v)} />
                    <Cell label="Tono"      value={r.tono}         onChange={(v) => actualizarRollo(idx, "tono", v)} />
                    <Cell label="Ref. tela" value={r.referencia_tela} onChange={(v) => actualizarRollo(idx, "referencia_tela", v)} />
                    <Cell label="Descripción *" value={r.descripcion_tela} onChange={(v) => actualizarRollo(idx, "descripcion_tela", v)} required />
                    <Cell label="Costo/m (COP)" value={r.costo_metro}  onChange={(v) => actualizarRollo(idx, "costo_metro", v)}  inputMode="decimal" />
                    <Cell label="Metros *"      value={r.metros_inicial} onChange={(v) => actualizarRollo(idx, "metros_inicial", v)} inputMode="decimal" required />
                  </div>
                </div>
              ))}
            </div>

            <button type="button" onClick={agregarRollo}
              className="inline-flex items-center gap-2 rounded-sm border border-border bg-card px-3 py-2 text-xs font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud">
              <Plus className="h-3.5 w-3.5" /> Agregar rollo
            </button>
          </CardContent>
        </Card>

        {err && (
          <div className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5" /> {err}
          </div>
        )}

        <div className="sticky bottom-0 bg-white/95 backdrop-blur border-t border-border py-3 flex items-center justify-between gap-3">
          <div className="text-xs text-graphite">
            <span className="font-semibold text-ink-900 tabular">{totalRollosVal}</span> rollos ·
            <span className="font-semibold text-ink-900 tabular ml-1">{totalMetros.toFixed(2)}</span> metros
          </div>
          <button type="submit" disabled={mut.isPending || totalRollosVal === 0}
            className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-navy-700 disabled:opacity-40">
            {mut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Guardar ingreso
          </button>
        </div>
      </form>
    </PageShell>
  );
}

function Input({ label, value, onChange, type = "text", required = false, placeholder = "" }: {
  label: string; value: string; onChange: (v: string) => void; type?: string; required?: boolean; placeholder?: string;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-graphite">{label}</label>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)}
        required={required} placeholder={placeholder}
        className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm" />
    </div>
  );
}

function Cell({ label, value, onChange, inputMode, required = false }: {
  label: string; value: string; onChange: (v: string) => void; inputMode?: "decimal" | "numeric"; required?: boolean;
}) {
  return (
    <div>
      <label className="mb-1 block text-[0.55rem] uppercase tracking-widest text-graphite">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        inputMode={inputMode}
        required={required}
        className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-sm" />
    </div>
  );
}
