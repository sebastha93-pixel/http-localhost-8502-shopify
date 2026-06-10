"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { puedeEscribir } from "@/lib/auth";
import { RefreshCw, Loader2, CheckCircle, AlertCircle } from "lucide-react";

interface SyncResponse {
  ok: boolean;
  total: number;
  antes: number;
  despues: number;
  completados: number;
  error?: string;
}

/**
 * Botón en el sidebar para forzar sincronización exhaustiva con Shopify.
 * Solo visible para admin/operador. Tarda ~30-90s.
 */
export function SyncButton() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string>("");

  const mut = useMutation({
    mutationFn: () => api.post<SyncResponse>("/api/melonn/sync-completo"),
    onSuccess: (data) => {
      if (data.completados > 0) {
        setMsg(`✓ ${data.completados} pedidos completados (${data.despues}/${data.total})`);
        qc.invalidateQueries({ queryKey: ["melonn"] });
        qc.invalidateQueries({ queryKey: ["metricas"] });
      } else {
        setMsg(`✓ Ya sincronizado (${data.despues}/${data.total})`);
      }
      setTimeout(() => setMsg(""), 6000);
    },
    onError: (err: Error) => {
      setMsg(`✗ ${err.message}`);
      setTimeout(() => setMsg(""), 6000);
    },
  });

  if (!puedeEscribir(user)) return null;

  return (
    <div className="border-t border-white/5 px-4 py-2.5">
      <button
        onClick={() => mut.mutate()}
        disabled={mut.isPending}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-white/5 disabled:opacity-60 transition-colors"
        title="Buscar datos faltantes en Shopify (puede tardar ~30s)"
      >
        {mut.isPending ? (
          <Loader2 className="h-3.5 w-3.5 text-steel animate-spin flex-none" />
        ) : msg.startsWith("✓") ? (
          <CheckCircle className="h-3.5 w-3.5 text-teal flex-none" />
        ) : msg.startsWith("✗") ? (
          <AlertCircle className="h-3.5 w-3.5 text-crimson flex-none" />
        ) : (
          <RefreshCw className="h-3.5 w-3.5 text-steel flex-none" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-[0.55rem] font-bold uppercase tracking-[0.2em] text-steel/60">
            {mut.isPending ? "Sincronizando..." : "Sincronizar datos"}
          </p>
          <p className="text-[0.65rem] text-concrete/70 truncate">
            {msg || (mut.isPending ? "Buscando en Shopify..." : "Completar clientes faltantes")}
          </p>
        </div>
      </button>
    </div>
  );
}
