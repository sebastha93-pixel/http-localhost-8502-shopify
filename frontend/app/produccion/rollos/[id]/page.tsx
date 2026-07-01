"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, API_BASE } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Printer } from "lucide-react";

interface Rollo {
  id: string;
  codigo_interno: string;
  barcode: string;
  descripcion_tela: string;
  tono?: string;
  ancho?: number;
  costo_metro?: number;
  metros_inicial: number;
  metros_disponible: number;
  lote_fabrica?: string;
  referencia_tela?: string;
  numero_rollo?: string;
  serial?: string;
  fecha_ingreso?: string;
  fecha_ultimo_corte?: string;
  estado: string;
  orden_ingreso_id: string;
}

export default function RolloDetallePage() {
  const params = useParams();
  const id = params?.id as string;

  const q = useQuery<Rollo>({
    queryKey: ["produccion", "rollo", id],
    queryFn: () => api.get(`/api/produccion/rollos/${id}`),
    enabled: !!id,
  });

  if (q.isLoading) return <LoadingState label="Cargando rollo…" />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const r = q.data;
  const consumido = r.metros_inicial - r.metros_disponible;

  function imprimirEtiqueta() {
    const token = getToken();
    fetch(`${API_BASE}/api/produccion/rollos/${r.id}/etiqueta`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => res.blob())
      .then((blob) => window.open(URL.createObjectURL(blob), "_blank"));
  }

  return (
    <PageShell title={r.codigo_interno} subtitle={r.descripcion_tela}>
      <div className="flex items-center justify-between">
        <Link href="/produccion/inventario" className="inline-flex items-center gap-1 text-xs text-graphite hover:text-ink-900">
          <ArrowLeft className="h-3.5 w-3.5" /> Volver a inventario
        </Link>
        <button
          onClick={imprimirEtiqueta}
          className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-sm font-semibold uppercase tracking-widest text-white hover:bg-navy-700"
        >
          <Printer className="h-4 w-4" /> Imprimir etiqueta
        </button>
      </div>

      <Card>
        <CardContent className="p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
          <Kpi label="Metros disponibles" value={r.metros_disponible.toLocaleString("es-CO")} />
          <Kpi label="Metros inicial"     value={r.metros_inicial.toLocaleString("es-CO")} />
          <Kpi label="Consumido"          value={consumido.toLocaleString("es-CO")} />
          <Kpi label="Estado"             value={r.estado} />
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <Row label="Descripción"          value={r.descripcion_tela} />
          <Row label="Tono"                 value={r.tono} />
          <Row label="Referencia textilera" value={r.referencia_tela} />
          <Row label="Nº rollo textilera"   value={r.numero_rollo} />
          <Row label="Serial"               value={r.serial} />
          <Row label="Lote de fábrica"      value={r.lote_fabrica} />
          <Row label="Ancho (cm)"           value={r.ancho} />
          <Row label="Costo por metro"      value={r.costo_metro ? `$${Number(r.costo_metro).toLocaleString("es-CO")}` : undefined} />
          <Row label="Fecha ingreso"        value={r.fecha_ingreso} />
          <Row label="Último corte"         value={r.fecha_ultimo_corte} />
          <Row label="Barcode"              value={r.barcode} />
        </CardContent>
      </Card>
    </PageShell>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.6rem] uppercase tracking-widest text-graphite">{label}</p>
      <p className="mt-1 font-display text-xl text-ink-900 tabular">{value}</p>
    </div>
  );
}
function Row({ label, value }: { label: string; value: any }) {
  return (
    <div className="flex items-baseline gap-3 border-b border-border/40 pb-2">
      <span className="text-[0.62rem] uppercase tracking-widest text-graphite min-w-[140px]">{label}</span>
      <span className="text-ink-900">{value ?? "—"}</span>
    </div>
  );
}
