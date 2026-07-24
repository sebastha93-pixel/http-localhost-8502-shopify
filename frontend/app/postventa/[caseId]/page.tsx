"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatMoney } from "@/lib/utils";
import {
  obtenerCaso, cambiarEstado, previewFiscal, emitirFiscal,
  previewFactura, emitirFactura, type PreviewFactura,
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

export default function CasoDetallePage() {
  const params = useParams();
  const caseId = params?.caseId as string;
  const qc = useQueryClient();
  const caso = useQuery({ queryKey: ["postventa-caso", caseId],
                          queryFn: () => obtenerCaso(caseId) });

  const mut = useMutation({
    mutationFn: (estado: string) => cambiarEstado(caseId, estado),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["postventa-caso", caseId] });
      qc.invalidateQueries({ queryKey: ["postventa-casos"] });
    },
  });

  if (caso.isLoading) return <PageShell title="Caso"><LoadingState /></PageShell>;
  if (caso.isError || !caso.data)
    return <PageShell title="Caso"><ErrorState error={caso.error} onRetry={() => caso.refetch()} /></PageShell>;

  const c = caso.data;
  const acciones = ACCIONES[c.status] ?? [];

  return (
    <PageShell title={c.case_number} subtitle={`${c.type} · ${c.reason}`}>
      <Card className="mb-4"><CardContent className="py-4 space-y-1">
        <div className="flex items-center gap-2">
          <Badge>{ESTADOS_LABEL[c.status] ?? c.status}</Badge>
          <span className="text-sm text-muted-foreground">
            Prioridad: {c.priority}
          </span>
        </div>
        <div className="text-sm">Cliente: {c.customer_name || c.customer_email || "—"}</div>
        <div className="text-sm">Teléfono: {c.customer_phone || "—"}</div>
        <div className="text-sm">Pedido Shopify: {c.shopify_order_name || "—"}</div>
      </CardContent></Card>

      {/* Panel fiscal: nota crédito */}
      <PanelFiscal caseId={caseId} status={c.status} onEmitido={() =>
        qc.invalidateQueries({ queryKey: ["postventa-caso", caseId] })} />

      {/* Panel fiscal: factura del reemplazo (tras la nota crédito) */}
      <PanelFactura caseId={caseId} status={c.status} tipo={c.type} onEmitido={() =>
        qc.invalidateQueries({ queryKey: ["postventa-caso", caseId] })} />

      <div className="flex gap-2 flex-wrap mt-4">
        {acciones.map((a) => (
          <button key={a} disabled={mut.isPending}
                  onClick={() => mut.mutate(a)}
                  className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-medium text-graphite transition-colors hover:bg-cloud disabled:opacity-50">
            {ESTADOS_LABEL[a] ?? a}
          </button>
        ))}
        {acciones.length === 0 && (
          <p className="text-sm text-muted-foreground">Caso en estado final.</p>
        )}
      </div>
      {mut.isError && (
        <p className="text-sm text-destructive mt-2">
          No se pudo cambiar el estado (transición inválida).
        </p>
      )}
    </PageShell>
  );
}

function PanelFiscal({ caseId, status, onEmitido }:
  { caseId: string; status: string; onEmitido: () => void }) {
  const [preview, setPreview] = useState<PreviewFiscal | null>(null);

  const prevMut = useMutation({
    mutationFn: () => previewFiscal(caseId),
    onSuccess: setPreview,
  });
  const emitMut = useMutation({
    mutationFn: () => emitirFiscal(caseId),
    onSuccess: () => { setPreview(null); onEmitido(); },
  });

  // Solo tiene sentido desde 'aprobado' (antes de emitir la NC).
  if (status !== "aprobado") return null;

  return (
    <Card className="mb-4 border-navy-600/30">
      <CardContent className="py-4 space-y-3">
        <div className="font-medium text-sm">Nota crédito (Siigo)</div>

        {!preview && (
          <button disabled={prevMut.isPending} onClick={() => prevMut.mutate()}
            className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-700 disabled:opacity-50">
            {prevMut.isPending ? "Calculando…" : "Previsualizar nota crédito"}
          </button>
        )}
        {prevMut.isError && (
          <p className="text-sm text-destructive">
            No se pudo armar la nota crédito (¿se encontró la factura del pedido en Siigo?).
          </p>
        )}

        {preview && (
          <div className="space-y-2">
            <div className="text-sm">Factura original: <b>{preview.factura_original.name}</b></div>
            <div className="rounded-sm border border-border bg-cloud/30 p-3 text-sm space-y-1">
              <Fila k="Subtotal" v={formatMoney(preview.totales.subtotal)} />
              <Fila k="IVA 19%" v={formatMoney(preview.totales.iva)} />
              <Fila k="Total" v={formatMoney(preview.totales.total)} bold />
            </div>
            {preview.modo !== "produccion" ? (
              <p className="text-xs text-amber-600">
                Modo prueba — se emite una nota crédito Proforma que <b>NO</b> llega a la DIAN.
              </p>
            ) : (
              <p className="text-xs text-destructive">
                Modo producción — esta nota crédito es <b>electrónica y va a la DIAN</b>.
              </p>
            )}
            <div className="flex gap-2">
              <button disabled={emitMut.isPending} onClick={() => emitMut.mutate()}
                className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-700 disabled:opacity-50">
                {emitMut.isPending ? "Emitiendo…" : "Emitir nota crédito"}
              </button>
              <button onClick={() => setPreview(null)}
                className="rounded-sm border border-border bg-card px-4 py-2 text-sm font-medium text-graphite hover:bg-cloud">
                Cancelar
              </button>
            </div>
            {emitMut.isError && (
              <p className="text-sm text-destructive">
                Siigo rechazó la emisión. El caso quedó registrado con el error; revisa e intenta de nuevo.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PanelFactura({ caseId, status, tipo, onEmitido }:
  { caseId: string; status: string; tipo: string; onEmitido: () => void }) {
  const [preview, setPreview] = useState<PreviewFactura | null>(null);
  const prevMut = useMutation({
    mutationFn: () => previewFactura(caseId), onSuccess: setPreview });
  const emitMut = useMutation({
    mutationFn: () => emitirFactura(caseId),
    onSuccess: () => { setPreview(null); onEmitido(); } });

  // Solo tras emitir la NC, y solo para cambios (reembolso/bono no llevan factura).
  if (status !== "nota_credito_emitida") return null;
  if (tipo === "reembolso" || tipo === "bono") return null;

  return (
    <Card className="mb-4 border-navy-600/30">
      <CardContent className="py-4 space-y-3">
        <div className="font-medium text-sm">Factura del reemplazo (Siigo)</div>
        {!preview && (
          <button disabled={prevMut.isPending} onClick={() => prevMut.mutate()}
            className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-700 disabled:opacity-50">
            {prevMut.isPending ? "Calculando…" : "Previsualizar factura del reemplazo"}
          </button>
        )}
        {prevMut.isError && (
          <p className="text-sm text-destructive">
            No se pudo armar la factura (¿el precio de la referencia nueva está en Shopify?).
          </p>
        )}
        {preview && (
          <div className="space-y-2">
            <div className="rounded-sm border border-border bg-cloud/30 p-3 text-sm space-y-1">
              <Fila k="Total factura" v={formatMoney(preview.resumen.total)} />
              <Fila k="Cubierto por anticipo (NC)" v={formatMoney(preview.resumen.anticipo)} />
              <Fila k="Paga la clienta (excedente)"
                    v={formatMoney(preview.resumen.excedente)} bold />
            </div>
            {preview.resumen.excedente > 0 && (
              <p className="text-xs text-amber-600">
                La prenda nueva vale más: la clienta debe pagar el excedente.
              </p>
            )}
            <div className="flex gap-2">
              <button disabled={emitMut.isPending} onClick={() => emitMut.mutate()}
                className="rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-700 disabled:opacity-50">
                {emitMut.isPending ? "Emitiendo…" : "Emitir factura"}
              </button>
              <button onClick={() => setPreview(null)}
                className="rounded-sm border border-border bg-card px-4 py-2 text-sm font-medium text-graphite hover:bg-cloud">
                Cancelar
              </button>
            </div>
            {emitMut.isError && (
              <p className="text-sm text-destructive">
                Siigo rechazó la factura. El caso quedó con el error; revisa e intenta de nuevo.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Fila({ k, v, bold }: { k: string; v: string; bold?: boolean }) {
  return (
    <div className={`flex justify-between ${bold ? "font-semibold" : ""}`}>
      <span>{k}</span><span>{v}</span>
    </div>
  );
}
