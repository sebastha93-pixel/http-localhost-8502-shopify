"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { formatMoney, fmtDateTime } from "@/lib/utils";
import {
  obtenerCaso, cambiarEstado, previewFiscal, emitirFiscal,
  previewFactura, emitirFactura, type PreviewFactura,
  itemsFacturaCaso, agregarItem, type ItemFactura,
  timelineCaso, itemsCaso, listarTiendas, ESTADO_KIND, CICLO,
  obtenerLogistica, registrarGuiaRetorno, confirmarRecepcion, registrarDespacho,
  ESTADOS_LABEL, type EstadoPostventa, type PreviewFiscal,
} from "@/lib/postventa";

// Transiciones ofrecidas en UI (espejo del backend postventa_logic.TRANSICIONES).
const ACCIONES: Record<string, EstadoPostventa[]> = {
  creado: ["pendiente_validacion"],
  pendiente_validacion: ["aprobado", "rechazado", "escalado"],
  aprobado: ["nota_credito_emitida", "cerrado"],
  escalado: ["aprobado", "rechazado"],
  nota_credito_emitida: ["factura_emitida", "cerrado"],
  factura_emitida: ["cerrado"],
};

const TIPO_LABEL: Record<string, string> = {
  cambio_talla: "Cambio de talla", cambio_ref: "Cambio de referencia",
  reembolso: "Reembolso", bono: "Bono", garantia: "Garantía",
};

export default function CasoDetallePage() {
  const params = useParams();
  const caseId = params?.caseId as string;
  const qc = useQueryClient();
  const caso = useQuery({ queryKey: ["postventa-caso", caseId],
                          queryFn: () => obtenerCaso(caseId) });
  const refrescar = () => {
    qc.invalidateQueries({ queryKey: ["postventa-caso", caseId] });
    qc.invalidateQueries({ queryKey: ["postventa-timeline", caseId] });
    qc.invalidateQueries({ queryKey: ["postventa-items", caseId] });
  };

  const mut = useMutation({
    mutationFn: (estado: string) => cambiarEstado(caseId, estado),
    onSuccess: () => { refrescar(); qc.invalidateQueries({ queryKey: ["postventa-casos"] }); },
  });

  if (caso.isLoading) return <PageShell title="Caso"><LoadingState /></PageShell>;
  if (caso.isError || !caso.data)
    return <PageShell title="Caso"><ErrorState error={caso.error} onRetry={() => caso.refetch()} /></PageShell>;

  const c = caso.data;
  const acciones = ACCIONES[c.status] ?? [];

  return (
    <PageShell title={c.case_number}
               subtitle={`${TIPO_LABEL[c.type] ?? c.type} · ${c.reason.replace(/_/g, " ")}`}>
      {/* Riel de progreso: dónde está el caso y qué sigue */}
      <RielCiclo actual={c.status} />
      <CanalDelCaso tienda={c.tienda} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Columna de trabajo */}
        <div className="lg:col-span-2 space-y-4">
          <PanelItems caseId={caseId} status={c.status} onAgregado={refrescar} />
          <PanelLogistica caseId={caseId} status={c.status} onCambio={refrescar} />
          <PanelFiscal caseId={caseId} status={c.status} onEmitido={refrescar} />
          <PanelFactura caseId={caseId} status={c.status} tipo={c.type} onEmitido={refrescar} />

          {acciones.length > 0 && (
            <section>
              <p className="section-label mb-2">Avanzar el caso</p>
              <div className="flex gap-2 flex-wrap">
                {acciones.map((a) => (
                  <button key={a} disabled={mut.isPending} onClick={() => mut.mutate(a)}
                    className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-medium
                               text-ink-900 transition-colors hover:bg-cloud disabled:opacity-50">
                    {ESTADOS_LABEL[a] ?? a}
                  </button>
                ))}
              </div>
              {mut.isError && (
                <p className="text-sm text-terracotta mt-2">
                  No se pudo cambiar el estado (transición inválida).
                </p>
              )}
            </section>
          )}
        </div>

        {/* Columna de contexto */}
        <div className="space-y-4">
          <FichaCliente caso={c} />
          <PanelTimeline caseId={caseId} />
        </div>
      </div>
    </PageShell>
  );
}

/* ── Riel del ciclo de vida ─────────────────────────────────────────── */
function RielCiclo({ actual }: { actual: EstadoPostventa }) {
  const idx = CICLO.indexOf(actual);
  const fuera = idx === -1;   // rechazado / escalado
  return (
    <div className="mb-4 flex items-center gap-2 overflow-x-auto pb-1">
      <StatusBadge status={ESTADO_KIND[actual] ?? "wait"}
                   label={ESTADOS_LABEL[actual] ?? actual} />
      {!fuera && (
        <div className="flex items-center gap-1.5">
          {CICLO.map((e, i) => (
            <span key={e} title={ESTADOS_LABEL[e]}
              className={`h-1 rounded-full transition-colors ${
                i < idx ? "w-6 bg-sage"
                : i === idx ? "w-10 bg-navy-600"
                : "w-6 bg-concrete"}`} />
          ))}
          <span className="ml-1 text-[0.68rem] text-graphite whitespace-nowrap">
            paso {idx + 1} de {CICLO.length}
          </span>
        </div>
      )}
    </div>
  );
}

/* ── Canal: online o tienda física ──────────────────────────────────── */
function CanalDelCaso({ tienda }: { tienda?: string | null }) {
  const puntos = useQuery({ queryKey: ["postventa-tiendas"],
                            queryFn: listarTiendas, enabled: !!tienda });
  if (!tienda) return null;
  const p = (puntos.data ?? []).find((x) => x.clave === tienda);
  return (
    <div className="mb-4 rounded-sm border border-navy-600/25 bg-cloud/40 px-3 py-2">
      <p className="text-sm text-ink-900">
        Cambio presencial en{" "}
        <b>{p?.nombre ?? tienda}</b>
        {p && (
          <span className="text-graphite">
            {" · "}la prenda entra al inventario de {p.tienda}
            {" · "}factura{" "}
            <span className="font-display tabular-nums">{p.prefijo_factura}</span>
          </span>
        )}
      </p>
    </div>
  );
}

/* ── Ficha del cliente y pedido ─────────────────────────────────────── */
function FichaCliente({ caso }: { caso: { customer_name?: string | null;
  customer_email?: string | null; customer_phone?: string | null;
  shopify_order_name?: string | null; priority: string; created_at: string } }) {
  return (
    <Card><CardContent className="py-4">
      <p className="section-label mb-3">Cliente y pedido</p>
      <dl className="space-y-2.5 text-sm">
        <Dato k="Nombre" v={caso.customer_name} />
        <Dato k="Email" v={caso.customer_email} />
        <Dato k="Teléfono" v={caso.customer_phone} />
        <Dato k="Pedido" v={caso.shopify_order_name} mono />
        <Dato k="Prioridad" v={caso.priority} />
        <Dato k="Creado" v={fmtDateTime(caso.created_at)} />
      </dl>
    </CardContent></Card>
  );
}

function Dato({ k, v, mono }: { k: string; v?: string | null; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-graphite shrink-0">{k}</dt>
      <dd className={`text-ink-900 text-right break-words ${mono ? "font-display tabular-nums" : ""}`}>
        {v || "—"}
      </dd>
    </div>
  );
}

/* ── Timeline del caso ──────────────────────────────────────────────── */
const EVENTO_TONO: Record<string, string> = {
  fiscal_error: "bg-terracotta",
  nota_credito_emitida: "bg-sage",
  factura_emitida: "bg-sage",
  cambio_estado: "bg-navy-600",
  notificacion_wa: "bg-steel-400",
  creado: "bg-graphite",
};

function PanelTimeline({ caseId }: { caseId: string }) {
  const q = useQuery({ queryKey: ["postventa-timeline", caseId],
                       queryFn: () => timelineCaso(caseId) });
  return (
    <Card><CardContent className="py-4">
      <p className="section-label mb-3">Historial</p>
      {q.isLoading && <p className="text-sm text-graphite">Cargando…</p>}
      {q.data && q.data.length === 0 && (
        <p className="text-sm text-graphite">Sin eventos todavía.</p>
      )}
      {q.data && q.data.length > 0 && (
        <ol className="relative space-y-3 border-l border-concrete pl-4">
          {q.data.map((e) => (
            <li key={e.id} className="relative">
              <span className={`absolute -left-[1.32rem] top-1.5 h-1.5 w-1.5 rounded-full
                                ${EVENTO_TONO[e.event_type] ?? "bg-concrete"}`} />
              <p className="text-sm text-ink-900 leading-snug">{e.description}</p>
              <p className="text-[0.68rem] text-graphite tabular-nums">
                {fmtDateTime(e.created_at)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </CardContent></Card>
  );
}

/* ── Ítems del caso + selector desde la factura ─────────────────────── */
function PanelItems({ caseId, status, onAgregado }:
  { caseId: string; status: string; onAgregado: () => void }) {
  const [nuevoSku, setNuevoSku] = useState("");
  const yaEnCaso = useQuery({ queryKey: ["postventa-items", caseId],
                              queryFn: () => itemsCaso(caseId) });
  const deFactura = useQuery({
    queryKey: ["postventa-items-factura", caseId],
    queryFn: () => itemsFacturaCaso(caseId),
    enabled: status === "aprobado" && (yaEnCaso.data?.length ?? 0) === 0,
    retry: false,
  });
  const addMut = useMutation({
    mutationFn: (it: ItemFactura) => agregarItem(caseId, {
      original_sku: it.code, original_variant: it.description,
      original_price: it.price, requested_sku: nuevoSku.trim(),
    }),
    onSuccess: onAgregado,
  });

  const items = yaEnCaso.data ?? [];

  return (
    <Card><CardContent className="py-4 space-y-3">
      <p className="section-label">Prenda del caso</p>

      {items.length > 0 && items.map((it) => (
        <div key={it.id} className="rounded-sm border border-border bg-cloud/40 p-3">
          <div className="flex justify-between gap-3">
            <div>
              <p className="text-sm text-ink-900">{it.original_variant || it.original_sku}</p>
              <p className="text-[0.68rem] text-graphite font-display tabular-nums">
                {it.original_sku}
              </p>
            </div>
            <p className="font-display tabular-nums text-sm text-ink-900">
              {formatMoney(it.original_price ?? 0)}
            </p>
          </div>
          {it.requested_sku && (
            <p className="mt-2 border-t border-concrete pt-2 text-xs text-graphite">
              Cambia por <span className="font-display tabular-nums text-ink-900">{it.requested_sku}</span>
            </p>
          )}
        </div>
      ))}

      {items.length === 0 && status !== "aprobado" && (
        <p className="text-sm text-graphite">
          Aprueba el caso para elegir la prenda desde la factura.
        </p>
      )}

      {items.length === 0 && status === "aprobado" && (
        <>
          {deFactura.isLoading && <p className="text-sm text-graphite">Buscando la factura en Siigo…</p>}
          {deFactura.isError && (
            <p className="text-sm text-terracotta">
              No se encontró la factura del pedido en Siigo. Revisa el nº de pedido.
            </p>
          )}
          {deFactura.data && (
            <>
              <p className="text-[0.68rem] text-graphite">
                Factura <span className="font-display tabular-nums">{deFactura.data.factura.name}</span>
              </p>
              <label className="block space-y-1">
                <span className="block text-xs text-graphite">
                  SKU de la referencia nueva (vacío si es cambio de talla)
                </span>
                <input value={nuevoSku} onChange={(e) => setNuevoSku(e.target.value)}
                  placeholder="94625-1T12"
                  className="w-full rounded-sm border border-border bg-card px-3 py-2 text-sm
                             text-ink-900 font-display tabular-nums
                             focus:outline-none focus:ring-2 focus:ring-navy-600/30" />
              </label>
              {deFactura.data.items.map((it) => (
                <div key={it.code}
                  className="flex items-center justify-between gap-3 rounded-sm border border-border p-2.5">
                  <div className="min-w-0">
                    <p className="text-sm text-ink-900 truncate">{it.description}</p>
                    <p className="text-[0.68rem] text-graphite font-display tabular-nums">
                      {it.code} · {formatMoney(it.price)}
                    </p>
                  </div>
                  <button disabled={addMut.isPending} onClick={() => addMut.mutate(it)}
                    className="shrink-0 rounded-sm border border-border bg-card px-3 py-1 text-xs
                               font-medium text-ink-900 hover:bg-cloud disabled:opacity-50">
                    Agregar
                  </button>
                </div>
              ))}
            </>
          )}
        </>
      )}
    </CardContent></Card>
  );
}


/* ── Logística inversa: guía, recepción y despacho ──────────────────── */
const ESTADOS_CON_LOGISTICA = new Set([
  "aprobado", "esperando_envio_cliente", "en_transito_bodega",
  "recibido_bodega", "nota_credito_emitida", "factura_emitida", "cambio_enviado",
]);

function PanelLogistica({ caseId, status, onCambio }:
  { caseId: string; status: string; onCambio: () => void }) {
  const [guiaRet, setGuiaRet] = useState("");
  const [transRet, setTransRet] = useState("");
  const [guiaDesp, setGuiaDesp] = useState("");
  const [transDesp, setTransDesp] = useState("");

  const log = useQuery({ queryKey: ["postventa-logistica", caseId],
                         queryFn: () => obtenerLogistica(caseId) });
  const refrescar = () => { onCambio(); log.refetch(); };

  const guiaMut = useMutation({
    mutationFn: () => registrarGuiaRetorno(caseId, guiaRet, transRet),
    onSuccess: () => { setGuiaRet(""); setTransRet(""); refrescar(); } });
  const recibirMut = useMutation({
    mutationFn: () => confirmarRecepcion(caseId), onSuccess: refrescar });
  const despMut = useMutation({
    mutationFn: () => registrarDespacho(caseId, guiaDesp, transDesp),
    onSuccess: () => { setGuiaDesp(""); setTransDesp(""); refrescar(); } });

  if (!ESTADOS_CON_LOGISTICA.has(status)) return null;

  const l = log.data ?? {};
  const enTransito = status === "en_transito_bodega";
  const yaRecibido = !!l.fecha_recibido_bodega;
  const puedeDespachar = status === "factura_emitida" && !l.guia_despacho;

  return (
    <Card><CardContent className="py-4 space-y-3">
      <p className="section-label">Logística de la devolución</p>

      {/* Estado del retorno */}
      {l.guia_retorno ? (
        <div className="rounded-sm border border-border bg-cloud/40 p-3 space-y-1">
          <div className="flex justify-between gap-3 text-sm">
            <span className="text-graphite">Guía de retorno</span>
            <span className="font-display tabular-nums text-ink-900">{l.guia_retorno}</span>
          </div>
          {l.transportadora_retorno && (
            <div className="flex justify-between gap-3 text-sm">
              <span className="text-graphite">Transportadora</span>
              <span className="text-ink-900">{l.transportadora_retorno}</span>
            </div>
          )}
          <div className="flex justify-between gap-3 text-sm">
            <span className="text-graphite">Estado</span>
            <span className={yaRecibido ? "text-sage" : "text-ochre"}>
              {yaRecibido ? "Recibido en bodega" : "En tránsito"}
            </span>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-graphite">
            Registra la guía con la que la clienta devuelve la prenda.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input value={guiaRet} onChange={(e) => setGuiaRet(e.target.value)}
              placeholder="Nº de guía"
              className="rounded-sm border border-border bg-card px-3 py-2 text-sm
                         text-ink-900 font-display tabular-nums
                         focus:outline-none focus:ring-2 focus:ring-navy-600/30" />
            <input value={transRet} onChange={(e) => setTransRet(e.target.value)}
              placeholder="Transportadora"
              className="rounded-sm border border-border bg-card px-3 py-2 text-sm
                         text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30" />
          </div>
          <button disabled={!guiaRet.trim() || guiaMut.isPending}
            onClick={() => guiaMut.mutate()}
            className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white
                       transition-colors hover:bg-navy-700 disabled:opacity-50">
            {guiaMut.isPending ? "Guardando…" : "Registrar guía de devolución"}
          </button>
        </div>
      )}

      {/* Confirmar recepción: el gate */}
      {enTransito && !yaRecibido && (
        <button disabled={recibirMut.isPending} onClick={() => recibirMut.mutate()}
          className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white
                     transition-colors hover:bg-navy-700 disabled:opacity-50">
          {recibirMut.isPending ? "Confirmando…" : "Confirmar recepción en bodega"}
        </button>
      )}

      {/* Despacho del reemplazo */}
      {l.guia_despacho ? (
        <div className="rounded-sm border border-sage/25 bg-sage/5 p-3 flex justify-between gap-3 text-sm">
          <span className="text-graphite">Reemplazo despachado</span>
          <span className="font-display tabular-nums text-ink-900">{l.guia_despacho}</span>
        </div>
      ) : puedeDespachar ? (
        <div className="space-y-2 border-t border-concrete pt-3">
          <p className="text-xs text-graphite">Despacho del reemplazo</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input value={guiaDesp} onChange={(e) => setGuiaDesp(e.target.value)}
              placeholder="Nº de guía"
              className="rounded-sm border border-border bg-card px-3 py-2 text-sm
                         text-ink-900 font-display tabular-nums
                         focus:outline-none focus:ring-2 focus:ring-navy-600/30" />
            <input value={transDesp} onChange={(e) => setTransDesp(e.target.value)}
              placeholder="Transportadora"
              className="rounded-sm border border-border bg-card px-3 py-2 text-sm
                         text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30" />
          </div>
          <button disabled={!guiaDesp.trim() || despMut.isPending}
            onClick={() => despMut.mutate()}
            className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white
                       transition-colors hover:bg-navy-700 disabled:opacity-50">
            {despMut.isPending ? "Registrando…" : "Registrar despacho"}
          </button>
          {despMut.isError && (
            <p className="text-sm text-terracotta">
              No se pudo despachar. La prenda devuelta debe estar recibida en bodega.
            </p>
          )}
        </div>
      ) : null}
    </CardContent></Card>
  );
}

/* ── Nota crédito ───────────────────────────────────────────────────── */
function PanelFiscal({ caseId, status, onEmitido }:
  { caseId: string; status: string; onEmitido: () => void }) {
  const [preview, setPreview] = useState<PreviewFiscal | null>(null);
  const prevMut = useMutation({ mutationFn: () => previewFiscal(caseId), onSuccess: setPreview });
  const emitMut = useMutation({
    mutationFn: () => emitirFiscal(caseId),
    onSuccess: () => { setPreview(null); onEmitido(); } });

  if (status !== "aprobado") return null;

  return (
    <Card className="stitch-rail border-navy-600/25">
      <CardContent className="py-4 space-y-3">
        <p className="section-label">Nota crédito · Siigo</p>
        {!preview && (
          <button disabled={prevMut.isPending} onClick={() => prevMut.mutate()}
            className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white
                       transition-colors hover:bg-navy-700 disabled:opacity-50">
            {prevMut.isPending ? "Calculando…" : "Previsualizar nota crédito"}
          </button>
        )}
        {prevMut.isError && (
          <p className="text-sm text-terracotta">
            No se pudo armar la nota crédito. Revisa que la prenda esté agregada.
          </p>
        )}
        {preview && (
          <div className="space-y-3">
            <p className="text-xs text-graphite">
              Factura original{" "}
              <span className="font-display tabular-nums text-ink-900">
                {preview.factura_original.name}
              </span>
            </p>
            <Totales subtotal={preview.totales.subtotal} iva={preview.totales.iva}
                     total={preview.totales.total} />
            <AvisoModo modo={preview.modo} />
            <div className="flex gap-2">
              <button disabled={emitMut.isPending} onClick={() => emitMut.mutate()}
                className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white
                           transition-colors hover:bg-navy-700 disabled:opacity-50">
                {emitMut.isPending ? "Emitiendo…" : "Emitir nota crédito"}
              </button>
              <button onClick={() => setPreview(null)}
                className="rounded-sm border border-border bg-card px-4 py-2 text-sm
                           font-medium text-graphite hover:bg-cloud">
                Cancelar
              </button>
            </div>
            {emitMut.isError && (
              <p className="text-sm text-terracotta">
                Siigo rechazó la emisión. El motivo quedó en el historial.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ── Factura del reemplazo ──────────────────────────────────────────── */
function PanelFactura({ caseId, status, tipo, onEmitido }:
  { caseId: string; status: string; tipo: string; onEmitido: () => void }) {
  const [preview, setPreview] = useState<PreviewFactura | null>(null);
  const prevMut = useMutation({ mutationFn: () => previewFactura(caseId), onSuccess: setPreview });
  const emitMut = useMutation({
    mutationFn: () => emitirFactura(caseId),
    onSuccess: () => { setPreview(null); onEmitido(); } });

  if (status !== "nota_credito_emitida") return null;
  if (tipo === "reembolso" || tipo === "bono") return null;

  return (
    <Card className="stitch-rail border-navy-600/25">
      <CardContent className="py-4 space-y-3">
        <p className="section-label">Factura del reemplazo · Siigo</p>
        {!preview && (
          <button disabled={prevMut.isPending} onClick={() => prevMut.mutate()}
            className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white
                       transition-colors hover:bg-navy-700 disabled:opacity-50">
            {prevMut.isPending ? "Calculando…" : "Previsualizar factura"}
          </button>
        )}
        {prevMut.isError && (
          <p className="text-sm text-terracotta">
            No se pudo armar la factura. ¿El precio de la referencia nueva está en Shopify?
          </p>
        )}
        {preview && (
          <div className="space-y-3">
            <dl className="rounded-sm border border-border bg-cloud/40 p-3 text-sm space-y-1.5">
              <Fila k="Total factura" v={formatMoney(preview.resumen.total)} />
              <Fila k="Cubierto por anticipo" v={formatMoney(preview.resumen.anticipo)} />
              <Fila k="Paga la clienta" v={formatMoney(preview.resumen.excedente)} destacado />
            </dl>
            {preview.resumen.excedente > 0 && (
              <p className="text-xs text-ochre">
                La prenda nueva vale más: la clienta paga el excedente.
              </p>
            )}
            <AvisoModo modo={preview.modo} />
            <div className="flex gap-2">
              <button disabled={emitMut.isPending} onClick={() => emitMut.mutate()}
                className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white
                           transition-colors hover:bg-navy-700 disabled:opacity-50">
                {emitMut.isPending ? "Emitiendo…" : "Emitir factura"}
              </button>
              <button onClick={() => setPreview(null)}
                className="rounded-sm border border-border bg-card px-4 py-2 text-sm
                           font-medium text-graphite hover:bg-cloud">
                Cancelar
              </button>
            </div>
            {emitMut.isError && (
              <p className="text-sm text-terracotta">
                Siigo rechazó la factura. El motivo quedó en el historial.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ── Piezas compartidas ─────────────────────────────────────────────── */
function Totales({ subtotal, iva, total }:
  { subtotal: number; iva: number; total: number }) {
  return (
    <dl className="rounded-sm border border-border bg-cloud/40 p-3 text-sm space-y-1.5">
      <Fila k="Subtotal" v={formatMoney(subtotal)} />
      <Fila k="IVA 19%" v={formatMoney(iva)} />
      <Fila k="Total" v={formatMoney(total)} destacado />
    </dl>
  );
}

function Fila({ k, v, destacado }: { k: string; v: string; destacado?: boolean }) {
  return (
    <div className={`flex justify-between ${destacado ? "border-t border-concrete pt-1.5" : ""}`}>
      <dt className="text-graphite">{k}</dt>
      <dd className={`font-display tabular-nums text-ink-900 ${destacado ? "font-medium" : ""}`}>
        {v}
      </dd>
    </div>
  );
}

function AvisoModo({ modo }: { modo: string }) {
  return modo !== "produccion" ? (
    <p className="text-xs text-ochre">
      Modo prueba — se crea en Siigo pero <b>no</b> se envía a la DIAN. Revisable y borrable.
    </p>
  ) : (
    <p className="text-xs text-terracotta">
      Modo producción — el documento es <b>electrónico y va a la DIAN</b>.
    </p>
  );
}
