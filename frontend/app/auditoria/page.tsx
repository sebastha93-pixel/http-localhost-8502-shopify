"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { esAdmin } from "@/lib/auth";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtDateTime } from "@/lib/utils";
import { Shield, Search } from "lucide-react";

interface Evento {
  kind: "accion" | "nota";
  orden: string;
  tipo: string;
  descripcion: string;
  autor: string;
  creada_en?: string;
}

interface AuditoriaResponse {
  eventos: Evento[];
  total: number;
  autores: string[];
  tipos: string[];
}

const TIPO_LABEL: Record<string, string> = {
  despacho_autorizado:    "Despacho autorizado",
  llamada:                "Llamada",
  whatsapp:               "WhatsApp",
  acuerdo_cliente:        "Acuerdo cliente",
  gestion_transportadora: "Gestión transportadora",
  escalado:               "Escalado",
  visita:                 "Visita",
  resuelto:               "Resuelto",
  devolucion:             "Devolución",
  nota:                   "Nota",
  otro:                   "Otro",
};

function tipoTone(tipo: string): "critico" | "riesgo" | "normal" | "info" | "neutral" | "pendiente" {
  switch (tipo) {
    case "despacho_autorizado": return "info";
    case "escalado":            return "riesgo";
    case "devolucion":          return "critico";
    case "resuelto":            return "normal";
    case "nota":                return "neutral";
    default:                    return "pendiente";
  }
}

export default function AuditoriaPage() {
  const { user } = useAuth();
  const [autor, setAutor] = useState("");
  const [tipo, setTipo] = useState("");
  const [orden, setOrden] = useState("");

  const params = new URLSearchParams();
  if (autor) params.set("autor", autor);
  if (tipo) params.set("tipo", tipo);
  if (orden) params.set("orden", orden);
  const qs = params.toString();

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["auditoria", autor, tipo, orden],
    queryFn: () => api.get<AuditoriaResponse>(`/api/auditoria${qs ? `?${qs}` : ""}`),
    enabled: esAdmin(user),
  });

  if (!esAdmin(user)) {
    return (
      <PageShell title="Auditoría">
        <Card className="border-terracotta/25 bg-terracotta/[0.03]">
          <CardContent className="p-10 text-center">
            <Shield className="mx-auto mb-3 h-10 w-10 text-terracotta" />
            <p className="font-display text-base font-medium text-ink-900">Acceso restringido</p>
            <p className="mt-1 text-sm text-graphite">Solo administradores pueden ver el log de auditoría.</p>
          </CardContent>
        </Card>
      </PageShell>
    );
  }

  if (isLoading) return <LoadingState label="Cargando auditoría…" />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <PageShell
      title="Auditoría"
      subtitle={`${data.total} eventos · acciones y notas de todo el equipo`}
      isFetching={isFetching}
      onRefresh={() => refetch()}
    >
      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
          <input
            value={orden}
            onChange={(e) => setOrden(e.target.value)}
            placeholder="Filtrar por orden"
            className="w-full rounded-sm border border-border bg-card pl-9 pr-3 py-2 text-sm text-ink-900 placeholder:text-graphite/60 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
          />
        </div>

        <label className="flex items-center gap-2 text-xs text-graphite">
          <span className="text-[0.7rem] font-semibold uppercase tracking-[0.12em]">Usuario</span>
          <select
            value={autor}
            onChange={(e) => setAutor(e.target.value)}
            className="rounded-sm border border-border bg-card px-3 py-2 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
          >
            <option value="">Todos</option>
            {data.autores.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>

        <label className="flex items-center gap-2 text-xs text-graphite">
          <span className="text-[0.7rem] font-semibold uppercase tracking-[0.12em]">Tipo</span>
          <select
            value={tipo}
            onChange={(e) => setTipo(e.target.value)}
            className="rounded-sm border border-border bg-card px-3 py-2 text-sm text-ink-900 focus:outline-none focus:ring-2 focus:ring-navy-600/30"
          >
            <option value="">Todos</option>
            {data.tipos.map((t) => (
              <option key={t} value={t}>{TIPO_LABEL[t] || t}</option>
            ))}
          </select>
        </label>
      </div>

      {/* Timeline */}
      <Card>
        <CardContent className="p-0">
          {data.eventos.length === 0 ? (
            <p className="py-12 text-center text-sm text-graphite">
              Sin eventos con estos filtros. Limpia los filtros o cambia el período.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-cloud/60 border-b border-border">
                <tr>
                  {["Fecha · hora", "Usuario", "Tipo", "Orden", "Detalle"].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.eventos.map((e, i) => (
                  <tr key={i} className="border-b border-border transition-colors hover:bg-cloud/50">
                    <td className="px-4 py-2.5 text-xs tabular-nums text-graphite whitespace-nowrap">
                      {fmtDateTime(e.creada_en)}
                    </td>
                    <td className="px-4 py-2.5 font-medium text-ink-900 whitespace-nowrap">{e.autor || "—"}</td>
                    <td className="px-4 py-2.5">
                      <Badge tone={tipoTone(e.tipo)}>{TIPO_LABEL[e.tipo] || e.tipo}</Badge>
                    </td>
                    <td className="px-4 py-2.5 tabular-nums font-medium text-ink-900 whitespace-nowrap">{e.orden}</td>
                    <td className="px-4 py-2.5 text-graphite max-w-[320px] truncate" title={e.descripcion}>
                      {e.descripcion || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
