"use client";

/**
 * PendientesCodFlow — workflow obligatorio antes de autorizar despacho COD.
 *
 * Flujo de 2 pasos:
 *   1. Contactar al cliente (Llamar o WhatsApp) → auto-trackeado
 *   2. Marcar respuesta (Aprobación cliente / Cliente no contesta)
 *
 * Solo cuando respuesta = 'aprobacion' se habilita "Autorizar despacho".
 *
 * Reemplaza al simple <AutorizarDespachoButton> en la pestaña Pendientes
 * de /contraentrega.
 */
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Phone, MessageCircle, CheckCircle, XCircle, Send, Loader2, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Pedido } from "@/lib/types";
import { useAuth } from "@/components/auth-provider";
import { puedeEscribir } from "@/lib/auth";

interface AccionState {
  ok: boolean;
  existe?: boolean;
  contacto_via?: "llamada" | "mensaje" | null;
  contacto_at?: string | null;
  respuesta?: "aprobacion" | "no_contesta" | null;
  respuesta_at?: string | null;
  error?: string;
}

export function PendientesCodFlow({ pedido }: { pedido: Pedido }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const tel = (pedido.telefono_comprador || "").replace(/\D/g, "");
  const orden = pedido.orden_melonn;
  const [autorizando, setAutorizando] = useState(false);
  const [autorizado, setAutorizado] = useState(false);
  const [autorizError, setAutorizError] = useState<string>("");
  const [confirmando, setConfirmando] = useState(false);

  // Estado actual del workflow
  const accionQ = useQuery<AccionState>({
    queryKey: ["cod-accion", orden],
    queryFn: () => api.get(`/api/cod-acciones/${orden}`),
    enabled: !!orden && !autorizado,
    staleTime: 10_000,
  });

  // Registrar contacto (al hacer click en Llamar o WhatsApp)
  const contactoMut = useMutation({
    mutationFn: (via: "llamada" | "mensaje") =>
      api.post(`/api/cod-acciones/${orden}/contacto`, { via }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cod-accion", orden] }),
  });

  // Registrar respuesta del cliente
  const respuestaMut = useMutation({
    mutationFn: (valor: "aprobacion" | "no_contesta") =>
      api.post(`/api/cod-acciones/${orden}/respuesta`, { valor }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cod-accion", orden] }),
  });

  if (!puedeEscribir(user)) return null;
  if (!orden) return null;

  const data = accionQ.data;
  const contactado = !!data?.contacto_at;
  const respuesta = data?.respuesta;
  const aprobado = respuesta === "aprobacion";
  const noContesta = respuesta === "no_contesta";

  // ── Autorizar despacho (solo si aprobado) ──────────────────────────
  async function ejecutarAutorizar() {
    setAutorizando(true);
    setAutorizError("");
    try {
      const id = pedido.orden_tienda || pedido.orden_melonn;
      await api.post(`/api/melonn/pedidos/${id}/autorizar-despacho`);
      setAutorizado(true);
      qc.invalidateQueries({ queryKey: ["melonn"] });
      qc.invalidateQueries({ queryKey: ["metricas"] });
    } catch (e: any) {
      setAutorizError(e.message || "Error");
    } finally {
      setAutorizando(false);
      setConfirmando(false);
    }
  }

  if (autorizado) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-teal">
        <CheckCircle className="h-3.5 w-3.5" /> Autorizado
      </span>
    );
  }

  // ── UI compacto en una columna de tabla ──────────────────────────
  return (
    <div className="flex flex-col gap-1.5 min-w-[200px]">
      {/* Paso 1: Botones de contacto */}
      <div className="flex items-center gap-1.5">
        <a
          href={tel ? `tel:+57${tel}` : "#"}
          onClick={(e) => {
            if (!tel) { e.preventDefault(); return; }
            contactoMut.mutate("llamada");
          }}
          className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[0.65rem] font-medium uppercase tracking-wider transition-colors ${
            data?.contacto_via === "llamada"
              ? "border-teal bg-teal/10 text-teal"
              : "border-border bg-white text-ink-900 hover:bg-cloud"
          }`}
          title={`Llamar al ${pedido.telefono_comprador || "—"}`}
        >
          <Phone className="h-3 w-3" /> Llamar
        </a>
        <a
          href={tel ? `https://wa.me/57${tel}` : "#"}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => {
            if (!tel) { e.preventDefault(); return; }
            contactoMut.mutate("mensaje");
          }}
          className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[0.65rem] font-medium uppercase tracking-wider transition-colors ${
            data?.contacto_via === "mensaje"
              ? "border-sage bg-sage/10 text-sage"
              : "border-border bg-white text-ink-900 hover:bg-cloud"
          }`}
          title="Mensaje por WhatsApp"
        >
          <MessageCircle className="h-3 w-3" /> WhatsApp
        </a>
      </div>

      {/* Paso 2: Respuesta del cliente (visible solo si ya hay contacto) */}
      {contactado && !aprobado && (
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => respuestaMut.mutate("aprobacion")}
            disabled={respuestaMut.isPending}
            className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[0.65rem] font-medium uppercase tracking-wider transition-colors ${
              aprobado
                ? "border-teal bg-teal/15 text-teal"
                : "border-teal/40 bg-white text-teal hover:bg-teal/10"
            } disabled:opacity-50`}
          >
            <CheckCircle className="h-3 w-3" /> Aprobación
          </button>
          <button
            onClick={() => respuestaMut.mutate("no_contesta")}
            disabled={respuestaMut.isPending}
            className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[0.65rem] font-medium uppercase tracking-wider transition-colors ${
              noContesta
                ? "border-rust bg-rust/15 text-rust"
                : "border-border bg-white text-graphite hover:bg-cloud"
            } disabled:opacity-50`}
          >
            <XCircle className="h-3 w-3" /> No contesta
          </button>
        </div>
      )}

      {/* Estado: no contestó */}
      {noContesta && (
        <span className="text-[0.6rem] text-rust">
          Cliente no contestó · vuelve a intentar
        </span>
      )}

      {/* Paso 3: Autorizar (solo si aprobado) */}
      {aprobado && !confirmando && (
        <button
          onClick={() => setConfirmando(true)}
          disabled={autorizando}
          className="inline-flex items-center justify-center gap-1.5 rounded-md bg-ink px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50 transition-colors"
        >
          <Send className="h-3 w-3" /> Autorizar despacho
        </button>
      )}

      {aprobado && confirmando && (
        <div className="flex items-center gap-1.5">
          <button
            onClick={ejecutarAutorizar}
            disabled={autorizando}
            className="inline-flex items-center gap-1 rounded-md bg-teal px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-white hover:bg-ink disabled:opacity-50"
          >
            {autorizando ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle className="h-3 w-3" />}
            Sí, autorizar
          </button>
          <button
            onClick={() => setConfirmando(false)}
            className="rounded-md border border-border bg-white px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-graphite hover:bg-concrete"
          >
            Cancelar
          </button>
        </div>
      )}

      {autorizError && (
        <div className="inline-flex items-center gap-1 text-[0.6rem] text-crimson">
          <AlertCircle className="h-3 w-3" /> {autorizError.slice(0, 80)}
        </div>
      )}

      {/* Hint cuando no se ha contactado */}
      {!contactado && (
        <p className="text-[0.6rem] text-graphite italic">
          Contacta al cliente antes de autorizar
        </p>
      )}

      {/* Error de tabla no existe (primer setup) */}
      {data?.error === "tabla_no_existe" && (
        <p className="text-[0.6rem] text-rust">
          Falta crear tabla cod_acciones en Supabase
        </p>
      )}
    </div>
  );
}
