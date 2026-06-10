"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Pedido } from "@/lib/types";
import { CheckCircle, Loader2, AlertCircle, Send } from "lucide-react";

interface AutorizarResponse {
  ok: boolean;
  mensaje: string;
  orden_melonn: string;
}

export function AutorizarDespachoButton({ pedido }: { pedido: Pedido }) {
  const qc = useQueryClient();
  const [feedback, setFeedback] = useState<"idle" | "ok" | "error">("idle");
  const [msg, setMsg] = useState<string>("");

  const mutation = useMutation({
    mutationFn: () =>
      api.post<AutorizarResponse>(`/api/melonn/pedidos/${pedido.orden_melonn}/autorizar-despacho`),
    onSuccess: (data) => {
      setFeedback("ok");
      setMsg(data.mensaje);
      // Refresca pedidos en background — el pedido saldrá de "Pendientes"
      setTimeout(() => qc.invalidateQueries({ queryKey: ["melonn", "pedidos", "all"] }), 1500);
      setTimeout(() => qc.invalidateQueries({ queryKey: ["metricas"] }), 1500);
    },
    onError: (err: Error) => {
      setFeedback("error");
      setMsg(err.message);
    },
  });

  if (feedback === "ok") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-teal">
        <CheckCircle className="h-3.5 w-3.5" /> Autorizado
      </span>
    );
  }

  if (feedback === "error") {
    return (
      <button
        onClick={() => { setFeedback("idle"); setMsg(""); }}
        className="inline-flex items-center gap-1 text-xs font-semibold text-crimson"
        title={msg}
      >
        <AlertCircle className="h-3.5 w-3.5" /> Reintentar
      </button>
    );
  }

  return (
    <button
      onClick={() => {
        if (!pedido.orden_melonn) return;
        if (confirm(`¿Autorizar despacho del pedido ${pedido.orden_tienda || pedido.orden_melonn}?`)) {
          mutation.mutate();
        }
      }}
      disabled={mutation.isPending || !pedido.orden_melonn}
      className="inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
    >
      {mutation.isPending ? (
        <>
          <Loader2 className="h-3 w-3 animate-spin" />
          Autorizando
        </>
      ) : (
        <>
          <Send className="h-3 w-3" />
          Autorizar
        </>
      )}
    </button>
  );
}
