"use client";

/**
 * Reasignar el confeccionista de un lote ya remitido.
 *
 * Para dos casos reales: se eligió mal al cerrar el informe de corte, o el
 * confeccionista avisa después que no puede recibir el lote. Antes había que
 * borrar la remisión y volver a empezar.
 *
 * Solo aparece mientras el lote NO se haya recogido. Después el cambio es
 * físico, no de datos, y el backend lo rechaza a propósito.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { puedeAccionModulo } from "@/lib/auth";
import { UserCog, Loader2, X, Check, MessageCircle } from "lucide-react";

interface Confeccionista {
  id: string;
  nombre: string;
}

interface Resultado {
  anterior?: { nombre?: string };
  nuevo?: { nombre?: string };
  rutas_actualizadas?: number;
  reencolada_para_imprimir?: boolean;
  aviso_nuevo?: { enviado?: boolean; wa_url?: string }[];
  aviso_anterior?: { nombre?: string; wa_url?: string };
}

/** Mensajes en español de los casos que el backend rechaza a propósito. */
const MOTIVO_RECHAZO: Record<string, string> = {
  lote_ya_recogido:
    "El confeccionista ya recogió el lote. Reasignarlo solo cambiaría el papel, no dónde está la mercancía.",
  solo_remisiones_de_confeccion:
    "Esta remisión es de terminación, no de confección. Se cambia desde la hoja de ruta.",
  mismo_confeccionista: "Es el mismo confeccionista que ya tenía.",
  proveedor_inactivo: "Ese confeccionista está inactivo.",
  proveedor_no_es_confeccion: "Ese proveedor no es de confección.",
  proveedor_no_encontrado: "No se encontró ese confeccionista.",
  remision_no_encontrada: "No se encontró la remisión.",
};

export function ReasignarConfeccionista({
  remisionId, actual, confeccionistas, onHecho,
}: {
  remisionId: string;
  actual?: string;
  confeccionistas: Confeccionista[];
  onHecho?: () => void;
}) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [abierto, setAbierto] = useState(false);
  const [nuevoId, setNuevoId] = useState("");
  const [motivo, setMotivo] = useState("");
  const [error, setError] = useState("");
  const [hecho, setHecho] = useState<Resultado | null>(null);

  // Mismo permiso que exige el endpoint.
  const puede = puedeAccionModulo(user, "produccion_remisiones", "modificar") ||
                puedeAccionModulo(user, "produccion_corte", "modificar");
  if (!puede) return null;

  const mut = useMutation({
    mutationFn: () => api.post<Resultado>(
      `/api/produccion/remisiones/${remisionId}/reasignar-confeccionista`,
      { confeccionista_id: nuevoId, motivo }),
    onSuccess: (d) => {
      setHecho(d);
      setError("");
      setAbierto(false);
      setNuevoId("");
      setMotivo("");
      // Todo lo que muestra el confeccionista del lote queda viejo.
      qc.invalidateQueries({ queryKey: ["produccion"] });
      qc.invalidateQueries({ queryKey: ["ruta-corte"] });
      onHecho?.();
    },
    onError: (e: Error) => {
      setError(MOTIVO_RECHAZO[e.message] || e.message || "No se pudo reasignar");
    },
  });

  if (hecho) {
    const avisado = (hecho.aviso_nuevo || []).some((a) => a.enviado);
    return (
      <div className="rounded-sm border border-teal/40 bg-teal/5 p-3 text-xs space-y-2">
        <p className="flex items-center gap-1.5 font-semibold text-teal">
          <Check className="h-3.5 w-3.5" />
          Reasignado a {hecho.nuevo?.nombre}
        </p>
        <ul className="space-y-0.5 text-graphite">
          <li>· Hoja de ruta actualizada ({hecho.rutas_actualizadas} lote(s)) y aceptación anterior anulada.</li>
          <li>
            {avisado
              ? "· Ya se le avisó por WhatsApp que tiene un lote por recoger."
              : "· ⚠ No se pudo avisar por WhatsApp al nuevo — avísale manual."}
          </li>
          {hecho.reencolada_para_imprimir && (
            <li>· La remisión ya estaba impresa: volvió a la cola de la RICOH. <strong>Bota el papel viejo</strong>, tiene el nombre equivocado.</li>
          )}
        </ul>
        {hecho.aviso_anterior?.wa_url && (
          <div className="pt-1">
            <p className="text-[0.65rem] text-graphite mb-1">
              A {hecho.aviso_anterior.nombre} no se le avisó nada. Si ya sabía del lote, dile que no lo recoja:
            </p>
            <a href={hecho.aviso_anterior.wa_url} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-white px-2.5 py-1 text-[0.65rem] font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud">
              <MessageCircle className="h-3 w-3" />
              Avisar al anterior
            </a>
          </div>
        )}
      </div>
    );
  }

  if (!abierto) {
    return (
      <button type="button" onClick={() => setAbierto(true)}
        className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-white px-2.5 py-1 text-[0.62rem] font-semibold uppercase tracking-widest text-ink-900 hover:bg-cloud"
        title="Cambiar el confeccionista de este lote (antes de que lo recoja)">
        <UserCog className="h-3 w-3" />
        Reasignar
      </button>
    );
  }

  const otros = confeccionistas.filter((c) => c.nombre !== actual);

  return (
    <div className="rounded-sm border border-steel/40 bg-steel/5 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[0.7rem] font-bold uppercase tracking-widest text-graphite">
          Reasignar confeccionista
        </p>
        <button onClick={() => { setAbierto(false); setError(""); }} className="text-graphite hover:text-ink-900">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <p className="text-[0.65rem] text-graphite">
        Actual: <strong className="text-ink-900">{actual || "—"}</strong>
      </p>

      <select value={nuevoId} onChange={(e) => setNuevoId(e.target.value)}
        className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs text-ink-900">
        <option value="">— Elegir el nuevo confeccionista —</option>
        {otros.map((c) => (
          <option key={c.id} value={c.id}>{c.nombre}</option>
        ))}
      </select>

      <input value={motivo} onChange={(e) => setMotivo(e.target.value)}
        placeholder="Motivo (queda en la hoja de ruta): no puede recibir, error al cerrar…"
        className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs text-ink-900" />

      {error && <p className="text-[0.65rem] text-terracotta">{error}</p>}

      <div className="flex justify-end gap-2">
        <button onClick={() => { setAbierto(false); setError(""); }}
          className="rounded-sm border border-border bg-white px-2.5 py-1 text-[0.62rem] font-semibold uppercase tracking-widest text-graphite hover:bg-cloud">
          Cancelar
        </button>
        <button onClick={() => mut.mutate()} disabled={!nuevoId || mut.isPending}
          className="inline-flex items-center gap-1.5 rounded-sm bg-ink px-2.5 py-1 text-[0.62rem] font-semibold uppercase tracking-widest text-white hover:bg-black disabled:opacity-40">
          {mut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <UserCog className="h-3 w-3" />}
          Reasignar
        </button>
      </div>
    </div>
  );
}
