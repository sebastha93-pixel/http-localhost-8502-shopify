"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Pedido } from "@/lib/types";
import { useAuth } from "@/components/auth-provider";
import { puedeEscribir } from "@/lib/auth";
import { CheckCircle, Loader2, AlertCircle, Send, Lock } from "lucide-react";

interface AutorizarResponse {
  ok: boolean;
  mensaje: string;
  orden_melonn: string;
}

interface AccionFlow {
  ok?: boolean;
  existe?: boolean;
  contacto_at?: string | null;
  contacto_via?: "llamada" | "mensaje" | null;
  respuesta?: "aprobacion" | "no_contesta" | "rechazo" | null;
}

export function AutorizarDespachoButton({ pedido }: { pedido: Pedido }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [feedback, setFeedback] = useState<"idle" | "confirm" | "ok" | "error">("idle");
  const [msg, setMsg] = useState<string>("");

  // Botón oculto si el usuario es solo lectura
  if (!puedeEscribir(user)) return null;

  const orden = pedido.orden_melonn;

  // Estado del workflow (contacto + respuesta).
  // Solo autorizar se permite si respuesta === "aprobacion".
  const flowQ = useQuery<AccionFlow>({
    queryKey: ["cod-accion", orden],
    queryFn: () => api.get(`/api/cod-acciones/${orden}`),
    enabled: !!orden,
    staleTime: 5_000,
  });

  const flow = flowQ.data;
  const contactado = !!flow?.contacto_at;
  const respuesta = flow?.respuesta;
  const aprobado = respuesta === "aprobacion";

  const mutation = useMutation({
    mutationFn: () => {
      const id = pedido.orden_tienda || pedido.orden_melonn;
      return api.post<AutorizarResponse>(
        `/api/melonn/pedidos/${id}/autorizar-despacho`,
      );
    },
    onSuccess: (data) => {
      setFeedback("ok");
      setMsg(data.mensaje);
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
        {msg && <span className="text-[0.7rem] text-graphite max-w-[200px] text-right">{msg}</span>}
      </div>
    );
  }

  // ── GATE: bloquear si no hay contacto previo o respuesta no aprobada ──
  // El cliente debe haber sido contactado Y haber dado acuerdo antes de
  // autorizar el despacho. Esto evita despachar pedidos sin confirmar
  // (causa #1 de devoluciones y contraentregas rechazadas).
  if (!contactado) {
    return (
      <div className="inline-flex flex-col items-end gap-0.5">
        <button
          disabled
          title="Toca el pedido para abrir el detalle y contactar al cliente primero"
          className="inline-flex items-center gap-1.5 rounded-md bg-concrete border border-border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-graphite cursor-not-allowed"
        >
          <Lock className="h-3 w-3" /> Contactar primero
        </button>
        <span className="text-[0.7rem] text-graphite">Llama o escribe por WhatsApp</span>
      </div>
    );
  }
  if (respuesta === "no_contesta") {
    return (
      <div className="inline-flex flex-col items-end gap-0.5">
        <button
          disabled
          title="El cliente no contestó. Vuelve a intentar contactarlo."
          className="inline-flex items-center gap-1.5 rounded-md bg-concrete border border-border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-graphite cursor-not-allowed"
        >
          <Lock className="h-3 w-3" /> Sin respuesta
        </button>
        <span className="text-[0.7rem] text-graphite">Vuelve a contactar</span>
      </div>
    );
  }
  if (respuesta === "rechazo") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-rust">
        <AlertCircle className="h-3.5 w-3.5" /> Cliente rechazó
      </span>
    );
  }
  if (!aprobado) {
    return (
      <div className="inline-flex flex-col items-end gap-0.5">
        <button
          disabled
          title="Marca la respuesta del cliente en el panel"
          className="inline-flex items-center gap-1.5 rounded-md bg-concrete border border-border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-graphite cursor-not-allowed"
        >
          <Lock className="h-3 w-3" /> Falta respuesta
        </button>
        <span className="text-[0.7rem] text-graphite">Acuerdo / No contesta / Rechazó</span>
      </div>
    );
  }

  // Confirmación inline
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

  // Cliente aprobó → botón habilitado
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
