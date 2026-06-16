"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Crown, Repeat, Sparkles, AlertCircle, Star, HelpCircle } from "lucide-react";

interface Clasificacion {
  email: string;
  tier: "vip" | "recurrente" | "nuevo" | "primer_pedido" | "riesgo" | "desconocido";
  total_pedidos: number;
  entregados: number;
  cancelados: number;
  pendientes?: number;
  ltv?: number;
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

export function ClienteBadge({ email, compact = false }: { email?: string; compact?: boolean }) {
  const e = (email || "").trim().toLowerCase();

  const { data, isLoading } = useQuery<Clasificacion>({
    queryKey: ["cliente-clasif", e],
    queryFn: () => api.get<Clasificacion>(`/api/clientes/clasificacion?email=${encodeURIComponent(e)}`),
    enabled: !!e && e.includes("@"),
    staleTime: 60 * 60_000,        // 1h client-side (server tiene 24h en Supabase)
    refetchOnWindowFocus: false,
    retry: 1,
  });

  if (!e || !e.includes("@")) {
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
export function ClienteHistorial({ email }: { email?: string }) {
  const e = (email || "").trim().toLowerCase();

  const { data, isLoading } = useQuery<Clasificacion>({
    queryKey: ["cliente-clasif", e],
    queryFn: () => api.get<Clasificacion>(`/api/clientes/clasificacion?email=${encodeURIComponent(e)}`),
    enabled: !!e && e.includes("@"),
    staleTime: 60 * 60_000,
    refetchOnWindowFocus: false,
  });

  if (!e || !e.includes("@")) {
    return (
      <div className="rounded-md bg-concrete/40 border border-border px-3 py-2 text-xs text-graphite">
        Sin email del cliente — no se puede clasificar.
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
      <div className="grid grid-cols-4 gap-2 text-center pt-1">
        <Stat label="Pedidos" value={data.total_pedidos} />
        <Stat label="Entregados" value={data.entregados} tone="teal" />
        <Stat label="Cancelados" value={data.cancelados} tone={data.cancelados > 0 ? "rust" : "graphite"} />
        <Stat label="LTV" value={data.ltv ? `$${Math.round((data.ltv) / 1000)}K` : "—"} />
      </div>
      {data.ultima_compra && (
        <p className="text-[0.65rem] text-graphite text-right">
          Última compra: <span className="font-medium text-ink">{data.ultima_compra}</span>
        </p>
      )}
    </div>
  );
}

function Stat({ label, value, tone = "ink" }: { label: string; value: number | string; tone?: "ink" | "teal" | "rust" | "graphite" }) {
  const colorClass =
    tone === "teal" ? "text-teal"
    : tone === "rust" ? "text-rust"
    : tone === "graphite" ? "text-graphite"
    : "text-ink";
  return (
    <div>
      <p className="text-[0.6rem] uppercase tracking-wider text-graphite">{label}</p>
      <p className={`text-sm font-bold tabular-nums ${colorClass}`}>{value}</p>
    </div>
  );
}
