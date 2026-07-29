"use client";

/**
 * Campanita de avisos internos.
 *
 * Suena cuando llega algo nuevo. El sonido se GENERA con Web Audio en vez de
 * cargar un mp3: no hay archivo que servir, no depende del CSP ni de que el
 * asset exista en el build.
 *
 * OJO con el autoplay: los navegadores bloquean el audio hasta que el usuario
 * interactúa con la página al menos una vez. Por eso se "desbloquea" con el
 * primer click/tecla de la sesión (ver `useDesbloqueoAudio`). En la práctica:
 * el primer aviso del día puede llegar mudo si nadie ha tocado nada todavía;
 * a partir del primer click suena siempre.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { Bell, Check, Scissors, PackageCheck, Truck } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface Notificacion {
  id: string;
  tipo: string;
  titulo: string;
  mensaje?: string;
  enlace?: string;
  leida: boolean;
  creado_en: string;
}

interface Respuesta {
  ok: boolean;
  no_leidas: number;
  notificaciones: Notificacion[];
}

const ICONO: Record<string, typeof Bell> = {
  corte_creado: Scissors,
  corte_cerrado: PackageCheck,
  lote_etapa: Truck,
};

/** Dos notas cortas, como un timbre discreto. Sin archivos externos. */
function tocarTimbre() {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const notas = [
      { f: 880, t: 0 },
      { f: 1174, t: 0.11 },
    ];
    notas.forEach(({ f, t }) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = f;
      // Ataque y caída suaves: un tono cuadrado sin envolvente suena a "click".
      gain.gain.setValueAtTime(0, ctx.currentTime + t);
      gain.gain.linearRampToValueAtTime(0.18, ctx.currentTime + t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.28);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + t);
      osc.stop(ctx.currentTime + t + 0.3);
    });
    // Cerrar el contexto para no acumular uno por aviso.
    setTimeout(() => ctx.close().catch(() => {}), 800);
  } catch {
    /* sin audio disponible — el badge visual sigue funcionando */
  }
}

/** El navegador exige un gesto del usuario antes de permitir audio. */
function useDesbloqueoAudio() {
  const listo = useRef(false);
  useEffect(() => {
    const desbloquear = () => {
      listo.current = true;
      window.removeEventListener("click", desbloquear);
      window.removeEventListener("keydown", desbloquear);
    };
    window.addEventListener("click", desbloquear);
    window.addEventListener("keydown", desbloquear);
    return () => {
      window.removeEventListener("click", desbloquear);
      window.removeEventListener("keydown", desbloquear);
    };
  }, []);
  return listo;
}

function hace(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.floor(ms / 60000);
  if (min < 1) return "ahora";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} h`;
  return `${Math.floor(h / 24)} d`;
}

export function NotificacionesBell() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [abierto, setAbierto] = useState(false);
  const audioListo = useDesbloqueoAudio();
  // null = primera carga. Sin esto, al entrar suena por los avisos viejos.
  const previas = useRef<number | null>(null);

  const q = useQuery<Respuesta>({
    queryKey: ["notificaciones"],
    queryFn: () => api.get("/api/notificaciones"),
    enabled: !!user,
    refetchInterval: 20_000,
    refetchOnWindowFocus: true,
  });

  const noLeidas = q.data?.no_leidas ?? 0;

  useEffect(() => {
    if (!q.data) return;
    const antes = previas.current;
    previas.current = noLeidas;
    // Solo suena si SUBIÓ, y nunca en la primera carga.
    if (antes !== null && noLeidas > antes && audioListo.current) {
      tocarTimbre();
    }
  }, [noLeidas, q.data, audioListo]);

  const marcarTodas = useCallback(async () => {
    try {
      await api.post("/api/notificaciones/leer-todas");
      qc.invalidateQueries({ queryKey: ["notificaciones"] });
    } catch {
      /* si falla, el poll lo corrige */
    }
  }, [qc]);

  const marcarUna = useCallback(
    async (id: string) => {
      try {
        await api.post(`/api/notificaciones/${id}/leida`);
        qc.invalidateQueries({ queryKey: ["notificaciones"] });
      } catch {
        /* idem */
      }
    },
    [qc],
  );

  if (!user) return null;
  const items = q.data?.notificaciones ?? [];

  return (
    <div className="relative">
      <button
        onClick={() => setAbierto((v) => !v)}
        title={noLeidas ? `${noLeidas} sin leer` : "Avisos"}
        aria-label={noLeidas ? `Avisos: ${noLeidas} sin leer` : "Avisos"}
        className="relative text-steel/70 hover:text-white p-1 rounded hover:bg-white/5"
      >
        <Bell className="h-3.5 w-3.5" />
        {noLeidas > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[1rem] h-4 px-1 flex items-center justify-center rounded-full bg-terracotta text-[0.6rem] font-bold text-white tabular-nums">
            {noLeidas > 99 ? "99+" : noLeidas}
          </span>
        )}
      </button>

      {abierto && (
        <>
          {/* Capa para cerrar al hacer click afuera */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setAbierto(false)}
            aria-hidden
          />
          <div className="absolute bottom-full right-0 mb-2 z-50 w-80 max-h-96 overflow-y-auto rounded-sm border border-border bg-white shadow-lg">
            <div className="sticky top-0 flex items-center justify-between border-b border-border bg-white px-3 py-2">
              <span className="text-[0.68rem] font-semibold uppercase tracking-[0.15em] text-graphite">
                Avisos
              </span>
              {noLeidas > 0 && (
                <button
                  onClick={marcarTodas}
                  className="inline-flex items-center gap-1 text-[0.68rem] font-semibold text-teal hover:underline"
                >
                  <Check className="h-3 w-3" /> Marcar todas
                </button>
              )}
            </div>

            {items.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-graphite">
                Nada nuevo por acá.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {items.map((n) => {
                  const Icono = ICONO[n.tipo] ?? Bell;
                  const Cuerpo = (
                    <div className="flex gap-2.5">
                      <Icono
                        className={cn(
                          "h-3.5 w-3.5 flex-none mt-0.5",
                          n.leida ? "text-graphite/50" : "text-terracotta",
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <p
                          className={cn(
                            "text-xs leading-snug",
                            n.leida
                              ? "text-graphite"
                              : "font-semibold text-ink",
                          )}
                        >
                          {n.titulo}
                        </p>
                        {n.mensaje && (
                          <p className="mt-0.5 text-[0.7rem] leading-snug text-graphite">
                            {n.mensaje}
                          </p>
                        )}
                        <p className="mt-1 text-[0.65rem] uppercase tracking-wider text-graphite/60">
                          {hace(n.creado_en)}
                        </p>
                      </div>
                    </div>
                  );
                  return (
                    <li
                      key={n.id}
                      className={cn(
                        "px-3 py-2.5 hover:bg-concrete/50",
                        !n.leida && "bg-terracotta/[0.04]",
                      )}
                    >
                      {n.enlace ? (
                        <Link
                          href={n.enlace}
                          onClick={() => {
                            if (!n.leida) marcarUna(n.id);
                            setAbierto(false);
                          }}
                        >
                          {Cuerpo}
                        </Link>
                      ) : (
                        <button
                          className="w-full text-left"
                          onClick={() => !n.leida && marcarUna(n.id)}
                        >
                          {Cuerpo}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
