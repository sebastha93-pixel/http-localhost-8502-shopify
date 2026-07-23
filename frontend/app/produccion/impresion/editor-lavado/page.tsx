"use client";

/**
 * Editor VISUAL de la etiqueta de lavado — arrastra los elementos y edita su
 * texto sobre un lienzo a escala. Usa las MISMAS fuentes de marca que el
 * render del backend (se cargan por FontFace), así lo que ves ≈ lo que se
 * imprime. El layout se guarda en `plantillas_etiqueta` y el backend lo
 * rasteriza a BITMAP para la SAT. "Ver como imprime" trae el PNG exacto.
 */
import { useEffect, useRef, useState } from "react";
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { ArrowLeft, Save, RotateCcw, Eye, Loader2, Type as TypeIcon } from "lucide-react";
import Link from "next/link";

const ANCHO = 224, ALTO = 1040;   // dots (27.5 × 130 mm @ 203dpi)
const ESCALA = 1.5;               // px pantalla por dot
const PT = 203 / 72;              // punto tipográfico → dots

interface Elemento {
  id: string;
  tipo: "texto" | "logo" | "simbolos";
  x: number; y: number;
  texto?: string;
  fuente?: "TimesNewRoman" | "Arial" | "ArialBold";
  tam?: number;
  align?: "left" | "center" | "right";
  max_w?: number;
  por_material?: boolean;
  alto?: number;
  items?: string[];
}
interface Layout { ancho: number; alto: number; elementos: Elemento[]; }

const FAM: Record<string, string> = {
  TimesNewRoman: "MDTimes", Arial: "MDArial", ArialBold: "MDArialBold",
};

export default function EditorLavadoPage() {
  const [layout, setLayout] = useState<Layout | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [fontsReady, setFontsReady] = useState(false);
  const [cargaErr, setCargaErr] = useState("");
  const [msg, setMsg] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [prevRef, setPrevRef] = useState("96613-1");
  const [prevComp, setPrevComp] = useState("98% ALGODON 2% ELASTANO");
  const [pngUrl, setPngUrl] = useState("");
  const lienzoRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const resize = useRef<{ id: string; startY: number; base: number } | null>(null);

  // Cargar plantilla
  useEffect(() => {
    api.get<{ layout: Layout }>("/api/produccion/impresion/lavado/plantilla")
      .then((r) => setLayout(r.layout))
      .catch((e) => setCargaErr(e instanceof Error ? e.message : "Error"));
  }, []);

  // Cargar las fuentes reales (fetch autenticado → FontFace)
  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const token = getToken();
        for (const [arch, fam] of [["TimesNewRoman.ttf", "MDTimes"], ["Arial.ttf", "MDArial"], ["ArialBold.ttf", "MDArialBold"]]) {
          const res = await fetch(`${API_BASE}/api/produccion/impresion/fonts/${arch}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          });
          const buf = await res.arrayBuffer();
          const ff = new FontFace(fam, buf);
          await ff.load();
          (document as unknown as { fonts: FontFaceSet }).fonts.add(ff);
        }
        if (vivo) setFontsReady(true);
      } catch { if (vivo) setFontsReady(true); }  // seguir aunque falle
    })();
    return () => { vivo = false; };
  }, []);

  // Logo y símbolos: se descargan AUTENTICADOS (el endpoint exige token en
  // cabecera; un <img src> con ?t= daría 401). Se guardan como object URLs.
  const [assets, setAssets] = useState<Record<string, string>>({});
  useEffect(() => {
    let vivo = true;
    const urls: string[] = [];
    (async () => {
      const map: Record<string, string> = {};
      const pares: [string, string][] = [
        ["logo", "/api/produccion/impresion/lavado/asset?kind=logo"],
      ];
      for (const n of ["lavadora.png", "no_bleach.png", "secadora.png", "plancha.png", "no_secadora.png"])
        pares.push([`sym:${n}`, `/api/produccion/impresion/lavado/asset?kind=symbol&name=${encodeURIComponent(n)}`]);
      for (const [k, path] of pares) {
        try { const u = await api.blobUrl(path); map[k] = u; urls.push(u); } catch { /* ignore */ }
      }
      if (vivo) setAssets(map); else urls.forEach((u) => URL.revokeObjectURL(u));
    })();
    return () => { vivo = false; urls.forEach((u) => URL.revokeObjectURL(u)); };
  }, []);

  // ── Arrastre (mover) y redimensión (tamaño) ──
  useEffect(() => {
    function move(e: PointerEvent) {
      if (resize.current) {
        const dy = (e.clientY - resize.current.startY) / ESCALA;
        setLayout((L) => L && ({ ...L, elementos: L.elementos.map((el) => {
          if (el.id !== resize.current!.id) return el;
          if (el.tipo === "texto") {
            return { ...el, tam: Math.max(8, Math.round(resize.current!.base + dy)) };
          }
          return { ...el, alto: Math.max(10, Math.round(resize.current!.base + dy)) };
        }) }));
        return;
      }
      if (!drag.current || !lienzoRef.current) return;
      const r = lienzoRef.current.getBoundingClientRect();
      const x = Math.round((e.clientX - r.left) / ESCALA - drag.current.dx);
      const y = Math.round((e.clientY - r.top) / ESCALA - drag.current.dy);
      setLayout((L) => L && ({ ...L, elementos: L.elementos.map((el) =>
        el.id === drag.current!.id
          ? { ...el, x: Math.max(0, Math.min(ANCHO, x)), y: Math.max(0, Math.min(ALTO - 4, y)) }
          : el) }));
    }
    function up() { drag.current = null; resize.current = null; }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, []);

  function onDown(e: React.PointerEvent, el: Elemento) {
    e.stopPropagation();
    setSel(el.id);
    const r = lienzoRef.current!.getBoundingClientRect();
    drag.current = {
      id: el.id,
      dx: (e.clientX - r.left) / ESCALA - el.x,
      dy: (e.clientY - r.top) / ESCALA - el.y,
    };
  }

  function onResizeDown(e: React.PointerEvent, el: Elemento) {
    e.stopPropagation();
    setSel(el.id);
    resize.current = { id: el.id, startY: e.clientY, base: el.tipo === "texto" ? (el.tam || 17) : (el.alto || 40) };
  }

  function actualizar(id: string, campos: Partial<Elemento>) {
    setLayout((L) => L && ({ ...L, elementos: L.elementos.map((el) => el.id === id ? { ...el, ...campos } : el) }));
  }

  const guardar = async () => {
    if (!layout) return;
    setGuardando(true); setMsg("");
    try {
      await api.patch("/api/produccion/impresion/lavado/plantilla", { layout });
      setMsg("Diseño guardado — así saldrán todas las etiquetas de lavado.");
      setTimeout(() => setMsg(""), 5000);
    } catch (e) { setMsg(e instanceof Error ? e.message : "Error al guardar"); }
    finally { setGuardando(false); }
  };

  const restaurar = async () => {
    if (!window.confirm("¿Restaurar el diseño por defecto? Se pierde lo que ajustaste (aún sin guardar).")) return;
    // Recargar el default: pedirlo sin plantilla guardada no es trivial; se
    // reconstruye pidiendo la plantilla tras borrar — más simple: recargar.
    const r = await api.get<{ layout: Layout }>("/api/produccion/impresion/lavado/plantilla");
    setLayout(r.layout);
  };

  const verImpreso = async () => {
    if (!layout) return;
    setPngUrl("cargando");
    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/api/produccion/impresion/lavado/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ codigo: prevRef, composicion: prevComp, layout }),
      });
      setPngUrl(URL.createObjectURL(await res.blob()));
    } catch { setPngUrl(""); }
  };

  if (cargaErr) return <ErrorState error={new Error(cargaErr)} onRetry={() => location.reload()} />;
  if (!layout) return <LoadingState label="Cargando editor…" />;

  const elSel = layout.elementos.find((e) => e.id === sel) || null;
  const muestra = (el: Elemento) => {
    let t = (el.texto || "").replace("{{REF}}", prevRef).replace("{{COMPOSICION}}", prevComp);
    if (el.por_material || el.id === "composicion") {
      const partes = t.match(/\d+\s*%\s*[^%\d]+/g);
      if (partes && partes.length) t = partes.map((p) => p.trim().replace(/[,;·-]+$/, "").trim()).join("\n");
    }
    return t;
  };

  return (
    <PageShell title="Editor · etiqueta de lavado" subtitle="Arrastra los elementos y edita su texto — lo que ves es lo que se imprime">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link href="/produccion/impresion" className="inline-flex items-center gap-1.5 text-xs text-navy-600 hover:underline">
          <ArrowLeft className="h-3.5 w-3.5" /> Volver a Impresión
        </Link>
        <div className="flex-1" />
        <button onClick={verImpreso} className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-graphite hover:bg-cloud">
          <Eye className="h-3 w-3" /> Ver como imprime
        </button>
        <button onClick={restaurar} className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-graphite hover:bg-cloud">
          <RotateCcw className="h-3 w-3" /> Descartar cambios
        </button>
        <button onClick={guardar} disabled={guardando} className="inline-flex items-center gap-1.5 rounded-sm bg-teal px-4 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:bg-ink-900 disabled:opacity-40">
          {guardando ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Guardar diseño
        </button>
      </div>

      {msg && <div className="mb-3 rounded-sm border border-teal/30 bg-teal-soft px-3 py-2 text-xs text-teal">{msg}</div>}

      <div className="grid gap-5 lg:grid-cols-[auto_1fr]">
        {/* ── Lienzo editable ── */}
        <div className="flex flex-col items-center gap-2">
          <div className="grid grid-cols-2 gap-2 w-full">
            <input value={prevRef} onChange={(e) => setPrevRef(e.target.value)}
              placeholder="Referencia de prueba"
              className="rounded-sm border border-border bg-white px-2 py-1 text-xs" />
            <input value={prevComp} onChange={(e) => setPrevComp(e.target.value)}
              placeholder="Composición de prueba"
              className="rounded-sm border border-border bg-white px-2 py-1 text-xs" />
          </div>
          <div ref={lienzoRef} onPointerDown={() => setSel(null)}
            className="relative border border-border bg-white shadow-sm touch-none select-none"
            style={{ width: ANCHO * ESCALA, height: ALTO * ESCALA }}>
            {!fontsReady && <div className="absolute inset-0 grid place-items-center text-[0.65rem] text-graphite">Cargando fuentes…</div>}
            {layout.elementos.map((el) => {
              const seleccionado = el.id === sel;
              const wrap: React.CSSProperties = {
                position: "absolute",
                left: el.x * ESCALA,
                top: el.y * ESCALA,
                transform: el.tipo !== "texto" || el.align === "center" ? "translateX(-50%)"
                  : el.align === "right" ? "translateX(-100%)" : "none",
                cursor: "move",
                outline: seleccionado ? "1.5px solid #2f6f6a" : "none",
                outlineOffset: 0,
                display: "inline-block",
                lineHeight: 0,   // ciñe el recuadro a la imagen (sin hueco de línea)
                fontSize: 0,
              };
              let contenido: React.ReactNode = null;
              if (el.tipo === "texto") {
                contenido = (
                  <span style={{
                    fontFamily: FAM[el.fuente || "Arial"] + ", sans-serif",
                    fontSize: (el.tam || 17) * ESCALA,
                    lineHeight: 1.25, textAlign: el.align || "center",
                    whiteSpace: "pre", color: "#000", display: "inline-block",
                  }}>{muestra(el)}</span>
                );
              } else if (el.tipo === "logo") {
                contenido = assets["logo"]
                  ? <img src={assets["logo"]} alt="logo" draggable={false}
                      style={{ height: (el.alto || 82) * ESCALA, width: "auto", maxWidth: "none", display: "block" }} />
                  : <span className="text-[0.6rem] text-graphite">logo…</span>;
              } else {
                contenido = (
                  <div style={{ display: "flex", gap: 8 * ESCALA }}>
                    {(el.items || []).map((n, i) => (
                      assets[`sym:${n}`]
                        ? <img key={i} src={assets[`sym:${n}`]} alt={n} draggable={false}
                            style={{ height: (el.alto || 40) * ESCALA, width: "auto", maxWidth: "none", display: "block" }} />
                        : <span key={i} style={{ width: (el.alto || 40) * ESCALA, height: (el.alto || 40) * ESCALA }}
                            className="border border-dashed border-border" />
                    ))}
                  </div>
                );
              }
              return (
                <div key={el.id} style={wrap} onPointerDown={(e) => onDown(e, el)}>
                  {contenido}
                  {seleccionado && (
                    <span
                      onPointerDown={(e) => onResizeDown(e, el)}
                      title="Arrastra para cambiar el tamaño"
                      style={{
                        position: "absolute", right: -6, bottom: -6,
                        width: 14, height: 14, borderRadius: 3,
                        background: "#2f6f6a", border: "2px solid #fff",
                        cursor: "nwse-resize", touchAction: "none",
                      }} />
                  )}
                </div>
              );
            })}
          </div>
          <span className="text-[0.6rem] text-graphite">27.5 × 130 mm · arrastra cada elemento</span>
        </div>

        {/* ── Panel de propiedades ── */}
        <div className="space-y-4">
          <Card><CardContent className="p-4">
            {!elSel ? (
              <p className="text-xs text-graphite">Toca un elemento de la etiqueta para editarlo, o arrástralo para moverlo.</p>
            ) : (
              <div className="space-y-3">
                <p className="section-label flex items-center gap-2"><TypeIcon className="h-3.5 w-3.5" /> {elSel.id}</p>
                {elSel.tipo === "texto" && (
                  <>
                    <label className="block">
                      <span className="mb-1 block text-[0.65rem] uppercase tracking-widest text-graphite">Texto (usa {"{{REF}}"} y {"{{COMPOSICION}}"})</span>
                      <textarea value={elSel.texto || ""} rows={4}
                        onChange={(e) => actualizar(elSel.id, { texto: e.target.value })}
                        className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs font-mono" />
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      <label className="block">
                        <span className="mb-1 block text-[0.65rem] uppercase tracking-widest text-graphite">Fuente</span>
                        <select value={elSel.fuente || "Arial"} onChange={(e) => actualizar(elSel.id, { fuente: e.target.value as Elemento["fuente"] })}
                          className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs">
                          <option value="TimesNewRoman">Times New Roman</option>
                          <option value="Arial">Arial</option>
                          <option value="ArialBold">Arial Bold</option>
                        </select>
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-[0.65rem] uppercase tracking-widest text-graphite">Tamaño (pt)</span>
                        <input type="number" step="0.5" value={Math.round((elSel.tam || 17) / PT * 10) / 10}
                          onChange={(e) => actualizar(elSel.id, { tam: Math.round((parseFloat(e.target.value) || 6) * PT) })}
                          className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs tabular" />
                      </label>
                    </div>
                    <div>
                      <span className="mb-1 block text-[0.65rem] uppercase tracking-widest text-graphite">Alineación</span>
                      <div className="flex gap-1">
                        {(["left", "center", "right"] as const).map((a) => (
                          <button key={a} onClick={() => actualizar(elSel.id, { align: a })}
                            className={`flex-1 rounded-sm border px-2 py-1 text-[0.62rem] uppercase ${elSel.align === a ? "border-navy-600 bg-navy-600 text-white" : "border-border bg-card text-graphite"}`}>
                            {a === "left" ? "Izq" : a === "center" ? "Centro" : "Der"}
                          </button>
                        ))}
                      </div>
                    </div>
                  </>
                )}
                {(elSel.tipo === "logo" || elSel.tipo === "simbolos") && (
                  <div>
                    <span className="mb-1 block text-[0.65rem] uppercase tracking-widest text-graphite">Tamaño (alto)</span>
                    <div className="flex items-center gap-2">
                      <button onClick={() => actualizar(elSel.id, { alto: Math.max(10, (elSel.alto || 40) - 4) })}
                        className="h-8 w-8 rounded-sm border border-border bg-card text-lg leading-none text-ink-900 hover:bg-cloud">−</button>
                      <input type="number" step="0.5" value={Math.round((elSel.alto || 40) / 8 * 10) / 10}
                        onChange={(e) => actualizar(elSel.id, { alto: Math.round((parseFloat(e.target.value) || 5) * 8) })}
                        className="w-20 rounded-sm border border-border bg-white px-2 py-1.5 text-center text-xs tabular" />
                      <span className="text-[0.65rem] text-graphite">mm</span>
                      <button onClick={() => actualizar(elSel.id, { alto: (elSel.alto || 40) + 4 })}
                        className="h-8 w-8 rounded-sm border border-border bg-card text-lg leading-none text-ink-900 hover:bg-cloud">+</button>
                    </div>
                    <p className="mt-1 text-[0.62rem] text-graphite">También puedes arrastrar el punto verde de la esquina.</p>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2">
                  <label className="block">
                    <span className="mb-1 block text-[0.65rem] uppercase tracking-widest text-graphite">X (centro)</span>
                    <input type="number" value={elSel.x} onChange={(e) => actualizar(elSel.id, { x: parseInt(e.target.value) || 0 })}
                      className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs tabular" />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-[0.65rem] uppercase tracking-widest text-graphite">Y (arriba)</span>
                    <input type="number" value={elSel.y} onChange={(e) => actualizar(elSel.id, { y: parseInt(e.target.value) || 0 })}
                      className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs tabular" />
                  </label>
                </div>
              </div>
            )}
          </CardContent></Card>

          {pngUrl && (
            <Card><CardContent className="p-4">
              <p className="section-label mb-2">Como imprime (render exacto)</p>
              {pngUrl === "cargando"
                ? <div className="h-40 grid place-items-center text-xs text-graphite"><Loader2 className="h-4 w-4 animate-spin" /></div>
                : <img src={pngUrl} alt="Render exacto" className="mx-auto border border-border" style={{ width: 160, imageRendering: "pixelated" }} />}
            </CardContent></Card>
          )}
        </div>
      </div>
    </PageShell>
  );
}
