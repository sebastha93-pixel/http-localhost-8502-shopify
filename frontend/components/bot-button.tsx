"use client";

import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { esAdmin } from "@/lib/auth";
import { Bot, Loader2, CheckCircle, AlertCircle, X } from "lucide-react";

interface BotStatus {
  running: boolean;
  task_id?: string;
  total: number;
  processed: number;
  exitos: number;
  fallidos: number;
  fallos_con_novedad: number;
  error?: string | null;
  log: string[];
  started_at?: number | null;
  finished_at?: number | null;
}

interface ScrapeResponse {
  task_id: string;
  total: number;
  message: string;
}

/**
 * Botón del bot Melonn — solo visible para admin.
 * Dispara scrape de pedidos sin guía y muestra progreso.
 */
export function BotButton() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [showPanel, setShowPanel] = useState(false);

  // Solo admin
  if (!esAdmin(user)) return null;

  // Poll status mientras está corriendo o el panel está abierto
  const { data: status } = useQuery({
    queryKey: ["bot", "status"],
    queryFn: () => api.get<BotStatus>("/api/bot/status"),
    refetchInterval: (q) => {
      const s = q.state.data as BotStatus | undefined;
      return s?.running || showPanel ? 5000 : false;
    },
    enabled: true,
  });

  const startMut = useMutation({
    mutationFn: () => api.post<ScrapeResponse>("/api/bot/scrape", {
      max_pedidos: 30,
      solo_sin_guia: true,
    }),
    onSuccess: () => {
      setShowPanel(true);
      qc.invalidateQueries({ queryKey: ["bot", "status"] });
    },
  });

  // Cuando termine el run, invalidar pedidos para refrescar UI
  useEffect(() => {
    if (status && !status.running && status.finished_at) {
      qc.invalidateQueries({ queryKey: ["melonn"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    }
  }, [status?.running, status?.finished_at, qc]);

  const running = status?.running ?? false;
  const ok = status?.error == null;
  const successCount = status?.exitos ?? 0;
  const failedCount = status?.fallidos ?? 0;

  return (
    <>
      <div className="border-t border-white/5 px-4 py-2.5">
        <button
          onClick={() => {
            setShowPanel(true);
            if (!running) startMut.mutate();
          }}
          disabled={running || startMut.isPending}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-white/5 disabled:opacity-60 transition-colors"
          title="Bot Melonn: extrae carrier + guía de las órdenes pendientes"
        >
          {running ? (
            <Loader2 className="h-3.5 w-3.5 text-steel animate-spin flex-none" />
          ) : (
            <Bot className="h-3.5 w-3.5 text-steel flex-none" />
          )}
          <div className="min-w-0 flex-1">
            <p className="text-[0.68rem] font-bold uppercase tracking-[0.2em] text-steel/60">
              {running ? "Bot corriendo..." : "Bot Melonn"}
            </p>
            <p className="text-[0.65rem] text-concrete/70 truncate">
              {running
                ? `${status?.processed ?? 0}/${status?.total ?? 0} pedidos`
                : "Extraer guías automáticas"}
            </p>
          </div>
        </button>
      </div>

      {showPanel && status && (
        <BotPanel
          status={status}
          starting={startMut.isPending}
          startError={(startMut.error as Error | null)?.message}
          onClose={() => setShowPanel(false)}
        />
      )}
    </>
  );
}


function BotPanel({
  status, starting, startError, onClose,
}: {
  status: BotStatus;
  starting: boolean;
  startError?: string;
  onClose: () => void;
}) {
  const pct = status.total > 0 ? Math.round((status.processed / status.total) * 100) : 0;
  const duration = status.started_at && (status.finished_at || Date.now() / 1000)
    ? Math.round(((status.finished_at || Date.now() / 1000) - status.started_at))
    : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white shadow-xl overflow-hidden">
        <div className="flex items-center justify-between bg-ink text-white px-5 py-3">
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5" />
            <div>
              <p className="text-[0.7rem] font-bold uppercase tracking-[0.2em] text-steel/70">
                Bot Melonn
              </p>
              <p className="text-base font-bold">
                {status.running ? "Procesando..." : "Resultado"}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-white/70 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {starting && (
            <div className="text-sm text-graphite flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" /> Iniciando bot...
            </div>
          )}

          {startError && (
            <div className="rounded-md bg-crimson/10 border border-crimson/30 px-3 py-2 text-sm text-crimson flex items-start gap-2">
              <AlertCircle className="h-4 w-4 flex-none mt-0.5" />
              <div>
                <p className="font-semibold">No se pudo iniciar</p>
                <p className="text-xs mt-0.5">{startError}</p>
              </div>
            </div>
          )}

          {/* Progress bar */}
          {(status.total > 0 || status.running) && (
            <div>
              <div className="flex justify-between text-xs text-graphite mb-1.5">
                <span className="font-semibold">{status.processed} / {status.total} pedidos</span>
                <span className="tabular-nums">{pct}% · {duration}s</span>
              </div>
              <div className="h-2 rounded-full bg-concrete overflow-hidden">
                <div
                  className={`h-full ${status.running ? "bg-steel" : status.error ? "bg-crimson" : "bg-teal"} transition-all`}
                  style={{ width: `${Math.max(pct, 2)}%` }}
                />
              </div>
            </div>
          )}

          {/* Result */}
          {!status.running && status.finished_at && (
            <div className={`rounded-md p-3 ${status.error ? "bg-crimson/10 border border-crimson/30" : "bg-teal/10 border border-teal/30"}`}>
              <div className="flex items-start gap-2">
                {status.error ? (
                  <AlertCircle className="h-5 w-5 text-crimson flex-none mt-0.5" />
                ) : (
                  <CheckCircle className="h-5 w-5 text-teal flex-none mt-0.5" />
                )}
                <div className="text-sm flex-1">
                  {status.error ? (
                    <>
                      <p className="font-semibold text-crimson">Bot terminó con error</p>
                      <p className="text-xs text-crimson mt-1">{status.error}</p>
                    </>
                  ) : (
                    <>
                      <p className="font-semibold text-teal">
                        ✓ {status.exitos} pedidos enriquecidos
                      </p>
                      <p className="text-xs text-graphite mt-1">
                        Éxitos: {status.exitos} · Fallidos: {status.fallidos}
                        {status.fallos_con_novedad > 0 && (
                          <> · <span className="text-rust font-semibold">{status.fallos_con_novedad} marcados con novedad</span></>
                        )}
                      </p>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Log */}
          {status.log && status.log.length > 0 && (
            <div>
              <p className="text-[0.7rem] font-bold uppercase tracking-wider text-graphite mb-1">Log</p>
              <div className="rounded-md bg-concrete/40 border border-border p-2 max-h-32 overflow-y-auto text-xs font-mono space-y-0.5">
                {status.log.slice(-10).map((l, i) => (
                  <div key={i} className="text-graphite">{l}</div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
