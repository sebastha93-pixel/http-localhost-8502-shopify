"use client";

/**
 * Detalle de remisión a confeccionista.
 */
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { fmtFecha } from "@/lib/utils";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TablaInsumosSeparar } from "@/components/tabla-insumos-separar";
import { ArrowLeft, Truck, Loader2, MessageCircle, Copy, Printer } from "lucide-react";

interface Item {
  id: string;
  orden_corte_id: string;
  orden_corte?: {
    consecutivo: string;
    referencia_lote?: string;
    cantidad_programada?: number;
    unidades_cortadas?: Record<string, number>;
    fecha_entrega?: string;
    referencia?: { codigo_referencia: string; nombre: string; tela?: string };
  };
}

interface Remision {
  id: string;
  consecutivo: string;
  fecha_recogida: string;
  estado: string;
  tipo?: string; // 'confeccion' | 'terminacion'
  created_at: string;
  confeccionista?: { nombre: string; telefono?: string; direccion?: string };
  items: Item[];
}

export default function RemisionDetallePage() {
  const params = useParams();
  const id = params?.id as string;
  const qc = useQueryClient();

  const q = useQuery<Remision>({
    queryKey: ["produccion", "remision", id],
    queryFn: () => api.get(`/api/produccion/remisiones/${id}`),
    enabled: !!id,
  });

  const [errAccion, setErrAccion] = useState("");
  const [imprimiendo, setImprimiendo] = useState(false);

  async function imprimirPDF() {
    setImprimiendo(true);
    try {
      const r = await fetch(`${API_BASE}/api/produccion/remisiones/${id}/pdf`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      window.open(URL.createObjectURL(blob), "_blank");
    } catch (e) {
      setErrAccion(`No se pudo generar el PDF: ${e instanceof Error ? e.message : "error"}`);
    } finally {
      setImprimiendo(false);
    }
  }
  const [waEnviado, setWaEnviado] = useState<"auto" | "manual" | "">("");
  const recogida = useMutation({
    mutationFn: () => api.post<{ ok: boolean; remision: { whatsapp?: { enviado: boolean; wa_url: string }[] } }>(
      `/api/produccion/remisiones/${id}/recogida`),
    onSuccess: (data) => {
      setErrAccion("");
      qc.invalidateQueries({ queryKey: ["produccion", "remision", id] });
      // Notificación al proveedor: si la API de WhatsApp está activa ya se
      // envió sola; si no, abrimos WhatsApp con el mensaje listo (un solo tap).
      const wa = data.remision?.whatsapp || [];
      if (wa.length === 0) return;
      if (wa.every((w) => w.enviado)) {
        setWaEnviado("auto");
      } else {
        setWaEnviado("manual");
        const pendiente = wa.find((w) => !w.enviado);
        if (pendiente?.wa_url) window.open(pendiente.wa_url, "_blank");
      }
    },
    onError: (e: Error) => setErrAccion(`No se pudo marcar la remisión: ${e.message}`),
  });

  if (q.isLoading) return <LoadingState label="Cargando remisión…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const rem = q.data;
  const yaRecogida = rem.estado === "recogida";
  // Confección: el confeccionista RECOGE. Terminación: MALE'DENIM DESPACHA.
  const esTerm = rem.tipo === "terminacion";
  const labelEstado = yaRecogida
    ? (esTerm ? "Despachada" : "Recogida")
    : (esTerm ? "Por despachar" : "Por recoger");

  const totalUnidades = (rem.items || []).reduce((s, it) => {
    const u = it.orden_corte?.unidades_cortadas || {};
    return s + Object.values(u).reduce((x, y) => x + (Number(y) || 0), 0);
  }, 0);

  return (
    <PageShell title={rem.consecutivo} subtitle={rem.confeccionista?.nombre || "—"}>
      <div className="flex items-center justify-between">
        <Link href="/produccion/remisiones" className="inline-flex items-center gap-1 text-xs text-graphite hover:text-ink-900">
          <ArrowLeft className="h-3.5 w-3.5" /> Volver a remisiones
        </Link>
        <div className="flex items-center gap-3">
          <button onClick={imprimirPDF} disabled={imprimiendo}
            className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-white px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud disabled:opacity-40">
            {imprimiendo ? <Loader2 className="h-3 w-3 animate-spin" /> : <Printer className="h-3 w-3" />}
            Imprimir
          </button>
          <Badge tone={yaRecogida ? "normal" : "pendiente"}>{labelEstado}</Badge>
        </div>
      </div>

      {/* Info general */}
      <Card>
        <CardContent className="p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
          <Info label={esTerm ? "Proveedor terminación" : "Confeccionista"} value={rem.confeccionista?.nombre || "—"} />
          <Info label="Teléfono"         value={rem.confeccionista?.telefono || "—"} />
          <Info label="Dirección"        value={rem.confeccionista?.direccion || "—"} />
          <Info label={esTerm ? "Fecha despacho" : "Fecha recogida"} value={fmtFecha(rem.fecha_recogida)} />
          <Info label="Órdenes"          value={String(rem.items?.length || 0)} />
          <Info label="Total unidades"   value={String(totalUnidades)} />
        </CardContent>
      </Card>

      {/* Items */}
      <Card>
        <CardContent className="p-0">
          <div className="px-4 py-3 border-b border-border">
            <p className="section-label">Órdenes de corte entregadas</p>
          </div>
          {(rem.items || []).length === 0 ? (
            <div className="p-8 text-center text-xs text-graphite">Sin órdenes.</div>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-cloud/60 border-b border-border">
                <tr className="text-left text-[0.6rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Consecutivo</th>
                  <th className="px-4 py-2">Referencia</th>
                  <th className="px-4 py-2">Lote</th>
                  <th className="px-4 py-2 text-right">Cantidad</th>
                  <th className="px-4 py-2">Entrega corte</th>
                </tr>
              </thead>
              <tbody>
                {(rem.items || []).map((it) => {
                  const totalOC = Object.values(it.orden_corte?.unidades_cortadas || {})
                    .reduce((x, y) => x + (Number(y) || 0), 0);
                  return (
                    <tr key={it.id} className="border-b border-border/40 hover:bg-cloud/40">
                      <td className="px-4 py-2 font-semibold tabular text-navy-600">
                        <Link href={`/produccion/corte/${it.orden_corte_id}`} className="hover:underline">
                          {it.orden_corte?.consecutivo || "—"}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-ink-900">
                        {it.orden_corte?.referencia?.codigo_referencia || "—"}
                        <div className="text-[0.6rem] text-graphite">
                          {it.orden_corte?.referencia?.nombre}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-graphite">{it.orden_corte?.referencia_lote || "—"}</td>
                      <td className="px-4 py-2 text-right tabular">
                        {totalOC || it.orden_corte?.cantidad_programada || "—"}
                      </td>
                      <td className="px-4 py-2 text-graphite text-[0.65rem] tabular">
                        {fmtFecha(it.orden_corte?.fecha_entrega)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          )}
        </CardContent>
      </Card>

      {errAccion && (
        <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
          {errAccion}
        </div>
      )}

      {waEnviado === "auto" && (
        <div role="status" className="rounded-sm border border-teal/40 bg-teal/[0.06] px-3 py-2 text-xs text-teal">
          ✓ Remisión marcada y WhatsApp enviado automáticamente al proveedor.
        </div>
      )}
      {waEnviado === "manual" && (
        <div role="status" className="rounded-sm border border-navy-600/40 bg-navy-600/[0.05] px-3 py-2 text-xs text-ink-900">
          Remisión marcada — se abrió WhatsApp con el mensaje al proveedor: solo dale enviar.
        </div>
      )}

      {!yaRecogida && (
        <div className="flex justify-end">
          <button onClick={() => recogida.mutate()} disabled={recogida.isPending}
            className="inline-flex items-center gap-2 rounded-sm bg-teal px-6 py-2.5 text-sm font-semibold uppercase tracking-[0.14em] text-white hover:bg-ink-900 disabled:opacity-40">
            {recogida.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Truck className="h-4 w-4" />}
            {esTerm ? "Marcar como despachada" : "Marcar como recogida"}
          </button>
        </div>
      )}

      {/* Envío por WhatsApp por cada lote */}
      <Card>
        <CardContent className="p-5 space-y-3">
          <p className="section-label">
            {rem.tipo === "terminacion" ? "Ficha para terminación" : "Ficha para el confeccionista"}
          </p>
          <p className="text-xs text-graphite">
            Para cada lote hay un link público con la ficha técnica, precio, cantidad e insumos.
            Configura el precio + fecha entrega y envía el link por WhatsApp.
          </p>
          <div className="space-y-3">
            {(rem.items || []).map((it) => (
              <RutaCard key={it.id} ordenCorteId={it.orden_corte_id}
                consecutivo={it.orden_corte?.consecutivo || ""}
                referencia={it.orden_corte?.referencia?.codigo_referencia || ""}
                tipo={rem.tipo === "terminacion" ? "terminacion" : "confeccion"}
                telefono={rem.confeccionista?.telefono}
                confeccionistaNombre={rem.confeccionista?.nombre}
                remisionId={rem.id} />
            ))}
          </div>
        </CardContent>
      </Card>
    </PageShell>
  );
}

interface Ruta {
  id: string;
  token_publico: string;
  separacion_insumos?: Record<string, {
    items?: Record<string, boolean>;
    ok?: boolean;
    responsable?: string | null;
    completado_at?: string | null;
  }>;
  token_publico_terminacion?: string;
  precio_confeccion?: number;
  precio_terminacion?: number;
  fecha_entrega_confeccion?: string;
  terminacion_id?: string;
  terminacion?: { nombre?: string; telefono?: string };
  etapa: string;
  aceptado_at?: string;
}

function RutaCard({ ordenCorteId, consecutivo, referencia, tipo, telefono, confeccionistaNombre, remisionId }: {
  ordenCorteId: string;
  consecutivo: string;
  referencia?: string;
  tipo: "confeccion" | "terminacion";
  telefono?: string;
  confeccionistaNombre?: string;
  remisionId?: string;
}) {
  const esTerminacion = tipo === "terminacion";
  const qc = useQueryClient();
  const [fecha, setFecha] = useState("");
  const [copiado, setCopiado] = useState<"ok" | "error" | "">("");
  const [errCard, setErrCard] = useState("");

  const q = useQuery<Ruta>({
    queryKey: ["ruta", ordenCorteId],
    queryFn: () => api.get(`/api/produccion/rutas/por-corte/${ordenCorteId}`),
    enabled: !!ordenCorteId,
    retry: false,
  });

  // El input date ignora placeholder: al cargar la ruta, mostrar la fecha guardada.
  useEffect(() => {
    if (q.data?.fecha_entrega_confeccion) setFecha(q.data.fecha_entrega_confeccion);
  }, [q.data?.fecha_entrega_confeccion]);

  // La tabla de insumos vive en el componente compartido <TablaInsumosSeparar />.

  const guardar = useMutation({
    mutationFn: () => {
      if (!q.data) return Promise.reject(new Error("ruta no cargada"));
      // El precio viene del precosteo (bloqueado) — solo se edita la fecha.
      return api.patch(`/api/produccion/rutas/${q.data.id}`, {
        fecha_entrega_confeccion: fecha || null,
      });
    },
    onSuccess: () => { setErrCard(""); qc.invalidateQueries({ queryKey: ["ruta", ordenCorteId] }); },
    onError: (e: Error) => setErrCard(`No se pudo guardar la fecha: ${e.message}`),
  });

  if (q.isLoading) {
    return <div className="rounded-sm border border-border bg-cloud/20 p-3 text-xs text-graphite">Cargando ficha…</div>;
  }
  if (q.isError) {
    return (
      <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/5 p-3 text-xs text-terracotta">
        No se pudo cargar la ficha de este lote (error de red o del servidor).{" "}
        <button onClick={() => q.refetch()} className="underline font-semibold">Reintentar</button>
      </div>
    );
  }
  if (!q.data) {
    return (
      <div className="rounded-sm border border-terracotta/40 bg-terracotta/5 p-3 text-xs text-terracotta">
        Este lote no tiene ficha creada aún. Corre la migración de hoja_ruta_lote en Supabase y refresca.
      </div>
    );
  }

  const r = q.data;
  const publicoBase = typeof window !== "undefined" ? window.location.origin : "";
  const linkPublico = esTerminacion
    ? `${publicoBase}/terminacion/${r.token_publico_terminacion || ""}`
    : `${publicoBase}/lote/${r.token_publico || ""}`;
  const linkOk = esTerminacion ? !!r.token_publico_terminacion : !!r.token_publico;

  // Al proveedor se le habla por la REFERENCIA de la prenda, no por el código interno.
  const refMsg = referencia || consecutivo;
  const mensajeWA = `Hola${confeccionistaNombre ? " " + confeccionistaNombre : ""}, te comparto la ficha del lote referencia *${refMsg}* de MALE'DENIM. Ahí ves referencia, cantidad, insumos y valor acordado. Cuando abras confirma con "Aceptar lote":\n\n${linkPublico}`;
  const telClean = (telefono || "").replace(/\D/g, "");
  const telFinal = telClean.startsWith("57") ? telClean : telClean ? `57${telClean}` : "";
  const waUrl = telFinal
    ? `https://wa.me/${telFinal}?text=${encodeURIComponent(mensajeWA)}`
    : `https://wa.me/?text=${encodeURIComponent(mensajeWA)}`;

  async function copiarLink() {
    try {
      await navigator.clipboard.writeText(linkPublico);
      setCopiado("ok");
    } catch {
      setCopiado("error");
    }
    setTimeout(() => setCopiado(""), 2500);
  }

  return (
    <div className="rounded-sm border border-border bg-white p-3 space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-semibold text-ink-900 tabular text-sm">{consecutivo}</p>
        <Badge tone={r.etapa === "asignado" ? "pendiente" : "normal"}>
          {({ asignado: "Asignado", aceptado: "Aceptado", en_confeccion: "En confección",
              lavanderia: "En lavandería", terminacion_recibida: "En terminación",
              terminacion_terminada: "Terminación lista", despachado: "En bodega",
            }[r.etapa] || r.etapa)}
        </Badge>
      </div>

      {errCard && (
        <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">
          {errCard}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <div>
          <label className="mb-1 block text-[0.6rem] uppercase tracking-widest text-graphite">
            {esTerminacion ? "Precio terminación (del precosteo)" : "Precio confección (del precosteo)"}
          </label>
          <div className="w-full rounded-sm border border-border bg-cloud/40 px-2 py-1.5 text-xs text-right tabular font-semibold text-ink-900">
            {(() => {
              const p = esTerminacion ? r.precio_terminacion : r.precio_confeccion;
              return p != null
                ? `$${Number(p).toLocaleString("es-CO", { maximumFractionDigits: 0 })}`
                : "— sin precio en el precosteo";
            })()}
          </div>
        </div>
        {!esTerminacion && (
          <div>
            <label className="mb-1 block text-[0.6rem] uppercase tracking-widest text-graphite">Fecha entrega</label>
            <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)}
              placeholder={r.fecha_entrega_confeccion || ""}
              className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs" />
          </div>
        )}
      </div>

      {/* Insumos que hay que SEPARAR físicamente antes de enviar */}
      <TablaInsumosSeparar ordenCorteId={ordenCorteId} tipo={tipo}
        rutaId={r.id} remisionId={remisionId}
        separacionInicial={(r.separacion_insumos || {})[tipo] || null} />

      <div className="flex flex-wrap items-center gap-2">
        {!esTerminacion && (
          <button onClick={() => guardar.mutate()} disabled={guardar.isPending || !fecha}
            className="inline-flex items-center gap-1 rounded-sm border border-border bg-cloud px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud/80 disabled:opacity-40">
            {guardar.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            Guardar fecha
          </button>
        )}
        {!linkOk ? (
          <p className="text-[0.65rem] text-terracotta">
            Este lote aún no tiene link {esTerminacion ? "de terminación" : "público"}. Corre la migración correspondiente en Supabase y refresca.
          </p>
        ) : (
          <>
            <a href={waUrl} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-sm bg-[#25D366] px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:opacity-90">
              <MessageCircle className="h-3 w-3" /> Enviar por WhatsApp
            </a>
            <button type="button" onClick={copiarLink}
              className="inline-flex items-center gap-1 rounded-sm border border-border bg-white px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-graphite hover:bg-cloud">
              <Copy className="h-3 w-3" /> {copiado === "ok" ? "Copiado ✓" : copiado === "error" ? "No se pudo copiar" : "Copiar link"}
            </button>
            <a href={linkPublico} target="_blank" rel="noopener noreferrer"
              className="text-[0.65rem] text-navy-600 hover:underline">Ver ficha</a>
          </>
        )}
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.6rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className="mt-1 text-sm text-ink-900">{value}</p>
    </div>
  );
}
