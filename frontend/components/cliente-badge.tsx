"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Crown, Repeat, Sparkles, AlertCircle, Star, HelpCircle, Send, CheckCircle, PhoneCall, Eye } from "lucide-react";
import { calcularPrioridad } from "@/lib/prioridad-cod";

interface Clasificacion {
  email: string;
  tier: "vip" | "recurrente" | "nuevo" | "primer_pedido" | "riesgo" | "desconocido";
  total_pedidos: number;
  entregados: number;
  cancelados: number;
  pendientes?: number;       // creados pero sin fulfilled ni cancelled
  otros?: number;            // gap entre total_pedidos y los clasificados
  ltv?: number;              // total_spent del customer en Shopify
  ultima_compra?: string | null;
}

const TIERS = {
  vip: {
    label: "VIP",
    tone: "info" as const,
    icon: Crown,
    descripcion: "5+ entregados sin cancelaciones",
  },
  recurrente: {
    label: "Recurrente",
    tone: "normal" as const,
    icon: Repeat,
    descripcion: "2-4 pedidos entregados",
  },
  nuevo: {
    label: "Nuevo",
    tone: "pendiente" as const,
    icon: Sparkles,
    descripcion: "1 pedido entregado previamente",
  },
  primer_pedido: {
    label: "1er pedido",
    tone: "neutral" as const,
    icon: Star,
    descripcion: "Primera vez que compra",
  },
  riesgo: {
    label: "Riesgo",
    tone: "critico" as const,
    icon: AlertCircle,
    descripcion: "Cancelaciones ≥ entregas — verificar antes de autorizar",
  },
  desconocido: {
    label: "—",
    tone: "neutral" as const,
    icon: HelpCircle,
    descripcion: "Sin email para clasificar",
  },
};

export function ClienteBadge({ email, telefono, compact = false }: { email?: string; telefono?: string; compact?: boolean }) {
  const e = (email || "").trim().toLowerCase();
  const t = (telefono || "").trim();
  const key = e || `tel:${t}`;
  const tieneInput = (e && e.includes("@")) || !!t;

  const { data, isLoading } = useQuery<Clasificacion>({
    queryKey: ["cliente-clasif", key],
    queryFn: () => api.get<Clasificacion>(
      `/api/clientes/clasificacion?email=${encodeURIComponent(e)}&telefono=${encodeURIComponent(t)}`,
    ),
    enabled: tieneInput,
    staleTime: 60 * 60_000,        // 1h client-side (server tiene 24h en Supabase)
    refetchOnWindowFocus: false,
    retry: 1,
  });

  if (!tieneInput) {
    return compact ? <Badge tone="neutral">—</Badge> : null;
  }

  if (isLoading) {
    return <Badge tone="neutral">···</Badge>;
  }

  const tier = data?.tier || "desconocido";
  const def = TIERS[tier];
  const Icon = def.icon;
  const title = `${def.descripcion} · ${data?.total_pedidos ?? 0} pedidos (${data?.entregados ?? 0} entregados, ${data?.cancelados ?? 0} cancelados)`;

  return (
    <span title={title} className="inline-flex">
      <Badge tone={def.tone}>
        <Icon className="h-3 w-3 mr-1 inline" />
        {def.label}
      </Badge>
    </span>
  );
}

/** Versión expandida para el panel detalle del pedido. */
export function ClienteHistorial({ email, telefono }: { email?: string; telefono?: string }) {
  const e = (email || "").trim().toLowerCase();
  const t = (telefono || "").trim();
  const key = e || `tel:${t}`;
  const tieneInput = (e && e.includes("@")) || !!t;

  const { data, isLoading } = useQuery<Clasificacion>({
    queryKey: ["cliente-clasif", key],
    queryFn: () => api.get<Clasificacion>(
      `/api/clientes/clasificacion?email=${encodeURIComponent(e)}&telefono=${encodeURIComponent(t)}`,
    ),
    enabled: tieneInput,
    staleTime: 60 * 60_000,
    refetchOnWindowFocus: false,
  });

  if (!tieneInput) {
    return (
      <div className="rounded-md bg-concrete/40 border border-border px-3 py-2 text-xs text-graphite">
        Sin email ni teléfono del cliente — no se puede clasificar.
      </div>
    );
  }
  if (isLoading || !data) {
    return (
      <div className="rounded-md bg-concrete/40 border border-border px-3 py-2 text-xs text-graphite">
        Consultando historial del cliente...
      </div>
    );
  }

  const def = TIERS[data.tier];
  const Icon = def.icon;
  const prioridad = calcularPrioridad(data.tier);
  const PrioIcon =
    prioridad.nivel === "autorizar_ya" ? CheckCircle
    : prioridad.nivel === "ok"         ? Send
    : prioridad.nivel === "llamar_antes" ? PhoneCall
    : Eye;

  return (
    <div className="rounded-md bg-concrete/40 border border-border px-3 py-2 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[0.6rem] uppercase tracking-wider text-graphite">Historial del cliente</p>
        <Badge tone={def.tone}>
          <Icon className="h-3 w-3 mr-1 inline" />
          {def.label}
        </Badge>
      </div>
      <p className="text-xs text-graphite">{def.descripcion}</p>
      {(() => {
        const otros = data.otros ?? 0;
        return (
          <div className={`grid ${otros > 0 ? "grid-cols-6" : "grid-cols-5"} gap-2 text-center pt-1`}>
            <Stat label="Pedidos" value={data.total_pedidos} hint="Total de pedidos creados en Shopify" />
            <Stat label="Entregados" value={data.entregados} tone="teal" hint="Pedidos con fulfillment 'fulfilled' en Shopify" />
            <Stat label="En curso" value={data.pendientes ?? 0} tone="ink" hint="Sin estado fulfilled ni cancelled — pueden estar en tránsito" />
            <Stat label="Cancelados" value={data.cancelados} tone={data.cancelados > 0 ? "rust" : "graphite"} hint="Pedidos cancelados en Shopify" />
            {otros > 0 && (
              <Stat
                label="Otros"
                value={otros}
                tone="graphite"
                hint="Pedidos archivados en Shopify o que no aparecen en el endpoint de orders — se cuentan en Pedidos pero no en los demás buckets"
              />
            )}
            <Stat label="LTV" value={data.ltv ? `$${Math.round((data.ltv) / 1000)}K` : "—"} hint="Lifetime Value · revenue total que el cliente ha generado" />
          </div>
        );
      })()}
      {data.ultima_compra && (
        <p className="text-[0.65rem] text-graphite text-right">
          Última compra: <span className="font-medium text-ink">{data.ultima_compra}</span>
        </p>
      )}

      {/* Recomendación de acción — qué hacer con este pedido */}
      <div className="flex items-center justify-between pt-2 mt-2 border-t border-border">
        <p className="text-[0.6rem] uppercase tracking-wider text-graphite">Recomendación</p>
        <span title={prioridad.motivo} className="inline-flex">
          <Badge tone={prioridad.tone}>
            <PrioIcon className="h-3 w-3 mr-1 inline" />
            {prioridad.label}
          </Badge>
        </span>
      </div>
      <p className="text-[0.65rem] text-graphite italic">{prioridad.motivo}</p>
    </div>
  );
}

/**
 * Badge de prioridad COD para la tabla de Pendientes.
 * Reutiliza la misma query de clasificación (mismo queryKey + caché).
 * Devuelve también el `orden` para sort.
 */
export function PrioridadCodBadge({ email, telefono }: { email?: string; telefono?: string }) {
  const e = (email || "").trim().toLowerCase();
  const t = (telefono || "").trim();
  const key = e || `tel:${t}`;
  const tieneInput = (e && e.includes("@")) || !!t;

  const { data, isLoading } = useQuery<Clasificacion>({
    queryKey: ["cliente-clasif", key],
    queryFn: () => api.get<Clasificacion>(
      `/api/clientes/clasificacion?email=${encodeURIComponent(e)}&telefono=${encodeURIComponent(t)}`,
    ),
    enabled: tieneInput,
    staleTime: 60 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  if (!tieneInput) return <Badge tone="pendiente"><Eye className="h-3 w-3 mr-1 inline" />Verificar</Badge>;
  if (isLoading) return <Badge tone="neutral">···</Badge>;

  const prioridad = calcularPrioridad(data?.tier);
  const Icon =
    prioridad.nivel === "autorizar_ya" ? CheckCircle
    : prioridad.nivel === "ok"         ? Send
    : prioridad.nivel === "llamar_antes" ? PhoneCall
    : Eye;

  return (
    <span title={prioridad.motivo} className="inline-flex">
      <Badge tone={prioridad.tone}>
        <Icon className="h-3 w-3 mr-1 inline" />
        {prioridad.short}
      </Badge>
    </span>
  );
}

/** Helper para ordenar pedidos por prioridad COD (mayor → autorizar_ya primero). */
export function ordenPrioridadCod(tier?: string): number {
  return calcularPrioridad(tier).orden;
}

function Stat({
  label,
  value,
  tone = "ink",
  hint,
}: {
  label: string;
  value: number | string;
  tone?: "ink" | "teal" | "rust" | "graphite";
  hint?: string;
}) {
  const colorClass =
    tone === "teal" ? "text-teal"
    : tone === "rust" ? "text-rust"
    : tone === "graphite" ? "text-graphite"
    : "text-ink";
  return (
    <div title={hint} className={hint ? "cursor-help" : undefined}>
      <p className="text-[0.6rem] uppercase tracking-wider text-graphite">{label}</p>
      <p className={`text-sm font-bold tabular-nums ${colorClass}`}>{value}</p>
    </div>
  );
}
