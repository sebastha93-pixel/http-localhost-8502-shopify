"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Pedido } from "@/lib/types";
import { useAuth } from "@/components/auth-provider";
import { puedeEscribir } from "@/lib/auth";
import { CheckCircle, Loader2, AlertCircle, Send } from "lucide-react";

interface AutorizarResponse {
  ok: boolean;
  mensaje: string;
  orden_melonn: string;
}

export function AutorizarDespachoButton({ pedido }: { pedido: Pedido }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [feedback, setFeedback] = useState<"idle" | "confirm" | "ok" | "error">("idle");
  const [msg, setMsg] = useState<string>("");

  // Botón oculto si el usuario es solo lectura
  if (!puedeEscribir(user)) return null;

  const mutation = useMutation({
    mutationFn: () => {
      // Melonn requiere external_order_number (orden_tienda) para release-hold.
      // Si no hay, fallback al M-id (el backend resuelve).
      const id = pedido.orden_tienda || pedido.orden_melonn;
      return api.post<AutorizarResponse>(
        `/api/melonn/pedidos/${id}/autorizar-despacho`,
      );
    },
    onSuccess: (data) => {
      setFeedback("ok");
      setMsg(data.mensaje);
      // Invalidación AGRESIVA inmediata — el backend ya refrescó el pedido
      // en caché antes de responder, así que esto es seguro.
      qc.invalidateQueries({ queryKey: ["melonn"] });
      qc.invalidateQueries({ queryKey: ["metricas"] });
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
      <div className="inline-flex flex-col items-end gap-0.5">
        <button
          onClick={() => { setFeedback("idle"); setMsg(""); }}
          className="inline-flex items-center gap-1 rounded-md bg-rust/15 px-2 py-1 text-xs font-semibold text-crimson hover:bg-rust/25"
        >
          <AlertCircle className="h-3 w-3" /> Reintentar
        </button>
        {msg && <span className="text-[0.6rem] text-graphite max-w-[200px] text-right">{msg}</span>}
      </div>
    );
  }

  // Confirmación inline (NO confirm() nativo) — iOS Safari invalida los
  // diálogos nativos cuando el user activation se gastó en un tel:/wa.me
  // previo, lo que hacía que el botón Autorizar pareciera no responder.
  if (feedback === "confirm") {
    return (
      <div className="inline-flex items-center gap-1.5">
        <button
          onClick={() => { setFeedback("idle"); mutation.mutate(); }}
          disabled={mutation.isPending}
          className="inline-flex items-center gap-1 rounded-md bg-teal px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-white hover:bg-ink disabled:opacity-50"
        >
          <CheckCircle className="h-3 w-3" /> Sí, autorizar
        </button>
        <button
          onClick={() => setFeedback("idle")}
          className="rounded-md border border-border bg-white px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-graphite hover:bg-concrete"
        >
          Cancelar
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => {
        if (!pedido.orden_melonn) return;
        setFeedback("confirm");
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
