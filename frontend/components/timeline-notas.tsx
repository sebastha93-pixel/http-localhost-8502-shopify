"use client";

/**
 * Timeline de notas de una hoja de ruta.
 * Muestra el histórico de mensajes del confeccionista, del proveedor de
 * terminación y del admin. Permite al admin agregar notas nuevas.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Loader2, MessageSquare } from "lucide-react";

interface Nota {
  id: string;
  actor: "confeccionista" | "terminacion" | "admin";
  autor?: string;
  mensaje: string;
  created_at: string;
}

const ACTOR_LABEL: Record<string, string> = {
  confeccionista: "Confeccionista",
  terminacion:    "Terminación",
  admin:          "Admin",
};
const ACTOR_TONE: Record<string, string> = {
  confeccionista: "bg-navy-600/10 text-navy-600",
  terminacion:    "bg-teal/10 text-teal",
  admin:          "bg-graphite/10 text-graphite",
};

export function TimelineNotas({ rutaId, permiteAgregar = true }: {
  rutaId?: string;
  permiteAgregar?: boolean;
}) {
  const qc = useQueryClient();
  const [msg, setMsg] = useState("");
  const [errNota, setErrNota] = useState("");

  const q = useQuery<{ notas: Nota[] }>({
    queryKey: ["notas-ruta", rutaId],
    queryFn: () => api.get(`/api/produccion/rutas/${rutaId}/notas`),
    enabled: !!rutaId,
  });

  const agregar = useMutation({
    mutationFn: () => api.post(`/api/produccion/rutas/${rutaId}/notas`, {
      mensaje: msg.trim(),
    }),
    onError: (e: Error) => setErrNota(`No se pudo guardar la nota: ${e.message}`),
    onSuccess: () => {
      setErrNota("");
      setMsg("");
      qc.invalidateQueries({ queryKey: ["notas-ruta", rutaId] });
    },
  });

  if (!rutaId) return null;
  const notas = q.data?.notas || [];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <MessageSquare className="h-3.5 w-3.5 text-navy-600" />
        <p className="section-label">Notas del lote ({notas.length})</p>
      </div>

      {q.isLoading ? (
        <p className="text-xs text-graphite">Cargando…</p>
      ) : notas.length === 0 ? (
        <p className="text-xs text-graphite">Sin notas todavía.</p>
      ) : (
        <ol className="space-y-2">
          {notas.map((n) => (
            <li key={n.id} className="rounded-sm border border-border bg-cloud/20 p-3">
              <div className="flex items-baseline justify-between gap-2 mb-1">
                <span className={`rounded-sm px-1.5 py-0.5 text-[0.68rem] font-bold uppercase tracking-widest ${ACTOR_TONE[n.actor] || "bg-graphite/10 text-graphite"}`}>
                  {ACTOR_LABEL[n.actor] || n.actor}
                </span>
                <span className="text-[0.7rem] text-graphite tabular">
                  {new Date(n.created_at).toLocaleString("es-CO", {
                    dateStyle: "short",
                    timeStyle: "short",
                  })}
                </span>
              </div>
              {n.autor && (
                <p className="text-[0.7rem] text-graphite/70 mb-1">{n.autor}</p>
              )}
              <p className="text-xs text-ink-900 whitespace-pre-wrap">{n.mensaje}</p>
            </li>
          ))}
        </ol>
      )}

      {permiteAgregar && (
        <div className="rounded-sm border border-border bg-white p-2 space-y-2">
          <textarea value={msg} onChange={(e) => setMsg(e.target.value)}
            rows={2} maxLength={5000} placeholder="Agregar nota…"
            className="w-full rounded-sm border border-border bg-white px-2 py-1.5 text-xs" />
          {errNota && (
            <p role="alert" className="text-[0.65rem] text-terracotta">{errNota}</p>
          )}
          <div className="flex justify-end">
            <button onClick={() => agregar.mutate()}
              disabled={agregar.isPending || !msg.trim()}
              className="inline-flex items-center gap-1 rounded-sm bg-navy-600 px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:bg-navy-700 disabled:opacity-40">
              {agregar.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              Agregar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
