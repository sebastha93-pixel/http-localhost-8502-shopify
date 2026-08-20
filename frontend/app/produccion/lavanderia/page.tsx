"use client";

/**
 * Trazabilidad de lavandería — lo que el OS lee del grupo y lo que persigue.
 *
 * POR QUÉ EXISTE (2026-08-19). El motor llevaba un día funcionando —leyendo el
 * grupo, abriendo pendientes, adjuntando remisiones— y no había una sola pantalla
 * donde verlo. Todo se comprobaba con consultas a la base. Una automatización que
 * solo se puede auditar por SQL es una automatización en la que nadie confía, y
 * con razón: cuando algo sale raro, la única salida es llamar a quien la escribió.
 *
 * Tres bloques, en orden de urgencia para quien abre la página:
 *   1. ¿está vivo y está enviando?  — el estado del oyente y del envío
 *   2. ¿qué está esperando?         — los pendientes, con días y recordatorios
 *   3. ¿qué se dijo en el grupo?    — el espejo, con las fotos visibles
 */
import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Clock, MessageSquare, AlertTriangle } from "lucide-react";

interface Pendiente {
  id: string;
  hoja_ruta_id: string;
  consecutivo?: string;
  codigo_referencia?: string | null;
  referencia_nombre?: string | null;
  reloj: string;
  estado: string;
  abierto_at: string;
  dias_abierto?: number;
  avisos: number;
  ultimo_aviso_at?: string | null;
  detectado_texto?: string | null;
  origen?: string;
  confeccionista?: { nombre?: string; telefono?: string } | null;
  lavanderia?: { nombre?: string; telefono?: string } | null;
}

interface RespPendientes {
  pendientes: Pendiente[];
  resumen: Record<string, number>;
  reloj: { running?: boolean; intervalo_min?: number; last_run_at?: string | null };
  envio_activo: boolean;
  cadencia: Record<string, number>;
}

interface Descuadre {
  hoja_ruta_id: string;
  consecutivo?: string;
  programadas?: number | null;
  cortadas?: number | null;
  en_remision?: number | null;
  recibidas_lavanderia?: number | null;
  entregadas_lavanderia?: number | null;
  recibidas_terminacion?: number | null;
  dif_corte_vs_remision?: number | null;
  dif_remision_vs_recibidas?: number | null;
  faltan?: number;
}

interface MensajeGrupo {
  id: string;
  wa_message_id: string;
  autor_nombre?: string;
  tipo: string;
  texto?: string | null;
  media_url?: string | null;
  enviado_en: string;
}

function esImagen(url?: string | null): boolean {
  if (!url) return false;
  return /\.(jpg|jpeg|png|webp|gif)$/.test(url.split("?")[0].toLowerCase());
}

function hora(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("es-CO", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

const RELOJ_LABEL: Record<string, string> = {
  recogida: "Esperando recogida + remisión",
  remision: "Esperando la remisión",
};

export default function LavanderiaPage() {
  const qc = useQueryClient();
  const [estadoFiltro, setEstadoFiltro] = useState("abierto");
  const [err, setErr] = useState("");

  const pendQ = useQuery<RespPendientes>({
    queryKey: ["lavanderia-pendientes", estadoFiltro],
    queryFn: () => api.get(`/api/produccion/lavanderia/pendientes?estado=${estadoFiltro}`),
    refetchInterval: 60_000,
  });

  const grupoQ = useQuery<{ mensajes: MensajeGrupo[] }>({
    queryKey: ["grupo-mensajes"],
    queryFn: () => api.get("/api/produccion/grupo/mensajes?limite=40"),
    refetchInterval: 30_000,
  });

  const cuadreQ = useQuery<{ descuadres: Descuadre[]; total_faltantes: number }>({
    queryKey: ["lavanderia-descuadres"],
    queryFn: () => api.get("/api/produccion/lavanderia/descuadres"),
    refetchInterval: 120_000,
  });

  const anular = useMutation({
    mutationFn: (id: string) =>
      api.post(`/api/produccion/lavanderia/pendientes/${id}/anular`,
               { motivo: "la detección se equivocó" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lavanderia-pendientes"] }),
    onError: (e: unknown) =>
      setErr(`No se pudo anular: ${e instanceof Error ? e.message : "error"}`),
  });

  const barrer = useMutation({
    mutationFn: () => api.post("/api/produccion/lavanderia/barrido", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lavanderia-pendientes"] }),
    onError: (e: unknown) =>
      setErr(`No se pudo correr el barrido: ${e instanceof Error ? e.message : "error"}`),
  });

  if (pendQ.isLoading) return <LoadingState />;
  if (pendQ.error) return <ErrorState error={pendQ.error} />;

  const d = pendQ.data;
  const pendientes = d?.pendientes || [];
  const resumen = d?.resumen || {};

  return (
    <PageShell
      title="Trazabilidad de lavandería"
      subtitle="Lo que el OS leyó del grupo y las remisiones que está esperando"
      isFetching={pendQ.isFetching}
      onRefresh={() => qc.invalidateQueries({ queryKey: ["lavanderia-pendientes"] })}
      dataUpdatedAt={pendQ.dataUpdatedAt}
    >
      {err && (
        <div className="mb-4 rounded-sm border border-terracotta/40 bg-terracotta/10 px-3 py-2 text-xs text-terracotta">
          {err}
        </div>
      )}

      {/* ── 1. ¿ESTÁ VIVO Y ESTÁ ENVIANDO? ────────────────────────────
          Va primero porque es lo que cambia el significado de todo lo de
          abajo: los mismos pendientes quieren decir cosas distintas si el
          motor está enviando o si está callado. */}
      <Card className="mb-5">
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-3 p-4 text-xs">
          <span className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${d?.reloj?.running ? "bg-teal" : "bg-terracotta"}`} />
            <span className="uppercase tracking-widest text-graphite">Reloj</span>
            <span className="font-semibold">
              {d?.reloj?.running
                ? `activo · cada ${d.reloj.intervalo_min} min`
                : "detenido"}
            </span>
          </span>

          <span className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${d?.envio_activo ? "bg-teal" : "bg-graphite/50"}`} />
            <span className="uppercase tracking-widest text-graphite">WhatsApp</span>
            <span className="font-semibold">
              {d?.envio_activo ? "enviando" : "en observación (no escribe a nadie)"}
            </span>
          </span>

          <span className="text-graphite">
            Último barrido: <span className="font-semibold">{hora(d?.reloj?.last_run_at)}</span>
          </span>

          <div className="flex-1" />
          <button
            onClick={() => { setErr(""); barrer.mutate(); }}
            disabled={barrer.isPending}
            className="rounded-sm border border-border bg-cloud px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest hover:bg-cloud/70 disabled:opacity-40"
          >
            {barrer.isPending ? "Corriendo…" : "Correr el reloj ahora"}
          </button>
        </CardContent>
      </Card>

      {/* Contadores */}
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { k: "abiertos_recogida", label: "Esperando recogida" },
          { k: "abiertos_remision", label: "Esperando remisión" },
          { k: "escalados", label: "Escalados" },
          { k: "cerrados", label: "Cumplidos" },
        ].map((c) => (
          <Card key={c.k}>
            <CardContent className="p-4">
              <p className="font-display text-2xl font-semibold tabular">{resumen[c.k] ?? 0}</p>
              <p className="text-[0.68rem] uppercase tracking-widest text-graphite">{c.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── PRENDAS QUE NO CUADRAN ────────────────────────────────────
          Va antes de los pendientes: un documento que va tarde se persigue,
          pero prendas perdidas hay que ir a buscarlas, y el rastro se enfría.
          Solo aparece si hay algo — una tarjeta vacía enseña a ignorarla. */}
      {(cuadreQ.data?.descuadres?.length || 0) > 0 && (
        <>
          <div className="mb-2 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-terracotta" />
            <h2 className="text-sm font-semibold uppercase tracking-widest text-terracotta">
              Prendas que no cuadran
            </h2>
            <span className="text-xs text-graphite">
              {cuadreQ.data?.total_faltantes} sin ubicar
            </span>
          </div>
          <Card className="mb-6 border-terracotta/40">
            <CardContent className="p-0">
              <table className="w-full text-xs">
                <thead className="border-b border-border bg-terracotta/5">
                  <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                    <th className="px-4 py-2">Lote</th>
                    <th className="px-4 py-2 text-right">Cortadas</th>
                    <th className="px-4 py-2 text-right">En la remisión</th>
                    <th className="px-4 py-2 text-right">Llegó a terminación</th>
                    <th className="px-4 py-2 text-right">Sin ubicar</th>
                  </tr>
                </thead>
                <tbody>
                  {(cuadreQ.data?.descuadres || []).map((c) => (
                    <tr key={c.hoja_ruta_id} className="border-b border-border/40">
                      <td className="px-4 py-2 font-semibold tabular">{c.consecutivo || "—"}</td>
                      <td className="px-4 py-2 text-right tabular">{c.cortadas ?? "—"}</td>
                      <td className="px-4 py-2 text-right tabular">{c.en_remision ?? "—"}</td>
                      <td className="px-4 py-2 text-right tabular">{c.recibidas_terminacion ?? "—"}</td>
                      <td className="px-4 py-2 text-right tabular font-bold text-terracotta">
                        {c.faltan ? c.faltan : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </>
      )}

      {/* ── 2. ¿QUÉ ESTÁ ESPERANDO? ──────────────────────────────────── */}
      <div className="mb-2 flex items-center gap-2">
        <Clock className="h-4 w-4 text-graphite" />
        <h2 className="text-sm font-semibold uppercase tracking-widest text-graphite">Pendientes</h2>
        <div className="flex-1" />
        {["abierto", "escalado", "cerrado", "anulado", "todos"].map((e) => (
          <button key={e} onClick={() => setEstadoFiltro(e)}
            className={`rounded-sm px-2 py-1 text-[0.62rem] font-semibold uppercase tracking-widest ${
              estadoFiltro === e ? "bg-navy-600 text-white" : "bg-cloud text-graphite hover:bg-cloud/70"}`}>
            {e}
          </button>
        ))}
      </div>

      <Card className="mb-6">
        <CardContent className="p-0">
          {pendientes.length === 0 ? (
            <p className="p-6 text-center text-xs text-graphite">
              Nada pendiente con ese filtro.
            </p>
          ) : (
            <table className="w-full text-xs">
              <thead className="border-b border-border bg-cloud/60">
                <tr className="text-left text-[0.7rem] uppercase tracking-widest text-graphite">
                  <th className="px-4 py-2">Referencia</th>
                  <th className="px-4 py-2">Consecutivo</th>
                  <th className="px-4 py-2">Esperando</th>
                  <th className="px-4 py-2 text-right">Días</th>
                  <th className="px-4 py-2 text-right">Recordatorios</th>
                  <th className="px-4 py-2">A quién se le pide</th>
                  <th className="px-4 py-2">Leído del grupo</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {pendientes.map((p) => (
                  <tr key={p.id} className="border-b border-border/40 hover:bg-cloud/30">
                    <td className="px-4 py-2 font-semibold text-navy-600">
                      <Link href={`/produccion/corte/${p.hoja_ruta_id}`} className="hover:underline">
                        {p.codigo_referencia || p.consecutivo || "—"}
                      </Link>
                      <div className="text-[0.7rem] font-normal text-graphite">
                        {p.referencia_nombre || ""}
                      </div>
                    </td>
                    <td className="px-4 py-2 tabular text-graphite">{p.consecutivo || "—"}</td>
                    <td className="px-4 py-2">{RELOJ_LABEL[p.reloj] || p.reloj}</td>
                    {/* Los días en rojo desde el 3º: es el plazo tras el cual
                        escala, así que el color avisa antes de que suene. */}
                    <td className={`px-4 py-2 text-right tabular font-semibold ${
                      (p.dias_abierto || 0) >= 3 ? "text-terracotta" : ""}`}>
                      {p.dias_abierto ?? 0}
                    </td>
                    <td className="px-4 py-2 text-right tabular">{p.avisos}</td>
                    <td className="px-4 py-2 text-graphite">
                      {p.confeccionista?.nombre || "—"}
                      {!p.confeccionista?.telefono && (
                        <span className="ml-1 text-terracotta" title="sin teléfono: el recordatorio no puede salir">
                          <AlertTriangle className="inline h-3 w-3" />
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 max-w-[16rem] truncate text-[0.7rem] text-graphite"
                        title={p.detectado_texto || ""}>
                      {p.detectado_texto || <span className="italic">abierto a mano</span>}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {p.estado === "abierto" && (
                        <button
                          onClick={() => { setErr(""); anular.mutate(p.id); }}
                          disabled={anular.isPending}
                          className="rounded-sm border border-border px-2 py-1 text-[0.6rem] font-semibold uppercase tracking-widest text-graphite hover:bg-cloud disabled:opacity-40"
                          title="La detección se equivocó: este lote no va a lavandería">
                          Anular
                        </button>
                      )}
                      {p.estado !== "abierto" && (
                        <Badge tone={p.estado === "escalado" ? "riesgo" : "neutral"}>
                          {p.estado}
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* ── 3. ¿QUÉ SE DIJO EN EL GRUPO? ──────────────────────────────
          El original al lado de lo que el OS entendió. Sin esto, cuando la
          detección se equivoca no hay forma de ver POR QUÉ. */}
      <div className="mb-2 flex items-center gap-2">
        <MessageSquare className="h-4 w-4 text-graphite" />
        <h2 className="text-sm font-semibold uppercase tracking-widest text-graphite">
          Espejo del grupo
        </h2>
      </div>
      <Card>
        <CardContent className="divide-y divide-border/40 p-0">
          {(grupoQ.data?.mensajes || []).length === 0 ? (
            <p className="p-6 text-center text-xs text-graphite">
              Todavía no ha entrado nada del grupo.
            </p>
          ) : (
            (grupoQ.data?.mensajes || []).map((m) => (
              <div key={m.id} className="flex gap-3 px-4 py-3">
                <div className="w-28 shrink-0 text-[0.68rem] text-graphite">
                  <div className="font-semibold text-ink-900">{m.autor_nombre || "—"}</div>
                  <div className="tabular">{hora(m.enviado_en)}</div>
                </div>
                <div className="min-w-0 flex-1">
                  {m.texto
                    ? <p className="whitespace-pre-wrap text-xs text-ink-900">{m.texto}</p>
                    : <p className="text-xs italic text-graphite">({m.tipo} sin texto)</p>}
                  {esImagen(m.media_url) && (
                    <a href={m.media_url!} target="_blank" rel="noopener noreferrer"
                      className="mt-2 inline-block rounded-sm border border-border p-1 hover:border-navy-600">
                      <img src={m.media_url!} alt="Adjunto del grupo"
                        className="max-h-32 w-auto rounded-sm object-contain" />
                    </a>
                  )}
                  {m.media_url && !esImagen(m.media_url) && (
                    <a href={m.media_url} target="_blank" rel="noopener noreferrer"
                      className="text-[0.68rem] text-navy-600 hover:underline">Abrir adjunto</a>
                  )}
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
