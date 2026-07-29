"use client";

/**
 * Campanita de avisos internos — fija arriba a la derecha.
 *
 * Va en AuthShell y no en PageShell: así aparece en TODAS las páginas
 * privadas, incluidas las que no usan PageShell.
 *
 * El sonido se GENERA con Web Audio en vez de cargar un mp3: no hay archivo
 * que servir, no depende del CSP ni de que el asset exista en el build.
 *
 * OJO con el autoplay: los navegadores bloquean el audio hasta que el usuario
 * interactúa con la página al menos una vez. Se desbloquea con el primer
 * click/tecla de la sesión. En la práctica: el primer aviso del día puede
 * llegar mudo; de ahí en adelante suena siempre.
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

// ── Sonido ────────────────────────────────────────────────────────────────
// Agrupado acá arriba para que ajustarlo sea trivial: sube VOLUMEN si en el
// taller no se oye, o baja GOLPES a 1 si resulta insistente.
// Las amplitudes de abajo suman ~1.3 en el instante del golpe, así que el
// maestro se queda en 0.62 para que el pico caiga cerca de 0.8 — fuerte pero
// sin pegarle al techo. OJO: no subas VOLUMEN por encima de 0.75 sin bajar las
// amplitudes de `parciales`; el compresor está puesto suave (−6 dB, ratio 4)
// para que solo dome los picos, y si le entra mucha señal aplasta el golpe y
// suena MÁS FLOJO, no más fuerte. Ese error ya lo cometí una vez acá.
const VOLUMEN = 0.62;
const GOLPES = 2;        // repeticiones del golpe
const SEPARACION = 0.19; // segundos entre golpes

/**
 * Golpe de campana con cuerpo: fundamental grave + armónicos + un "clac" de
 * ataque. Antes eran dos senoidales limpias y sonaban a notificación de
 * celular; esto se parece más a un timbre de taller, que es donde se usa.
 */
function tocarTimbre() {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();

    // Compresor: deja subir el volumen sin que sature ni distorsione.
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -6;
    comp.ratio.value = 4;
    comp.connect(ctx.destination);

    const maestro = ctx.createGain();
    maestro.gain.value = VOLUMEN;
    maestro.connect(comp);

    // Parciales de una campana: la fundamental da el peso, las de arriba el
    // brillo que atraviesa el ruido ambiente. Amplitud decreciente y colas
    // más cortas en los agudos = suena a metal, no a pitido.
    const parciales = [
      { f: 220, a: 0.52, dur: 1.1, tipo: "triangle" as OscillatorType },
      { f: 440, a: 0.32, dur: 0.9, tipo: "sine" as OscillatorType },
      { f: 660, a: 0.19, dur: 0.6, tipo: "sine" as OscillatorType },
      { f: 1320, a: 0.10, dur: 0.35, tipo: "sine" as OscillatorType },
    ];

    for (let g = 0; g < GOLPES; g++) {
      const t0 = ctx.currentTime + g * SEPARACION;
      // Segundo golpe un semitono abajo: da el "din-don" en vez de repetir.
      const detune = g === 0 ? 1 : 0.94;

      parciales.forEach(({ f, a, dur, tipo }) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = tipo;
        osc.frequency.value = f * detune;
        // Ataque casi instantáneo (3ms) = percusión. Caída exponencial = campana.
        gain.gain.setValueAtTime(0, t0);
        gain.gain.linearRampToValueAtTime(a, t0 + 0.003);
        gain.gain.exponentialRampToValueAtTime(0.0008, t0 + dur);
        osc.connect(gain);
        gain.connect(maestro);
        osc.start(t0);
        osc.stop(t0 + dur + 0.05);
      });

      // "Clac" del badajo: ruido cortísimo pasado por filtro. Es lo que hace
      // que el golpe se sienta contundente y no solo fuerte.
      const dur = 0.05;
      const buf = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * dur), ctx.sampleRate);
      const datos = buf.getChannelData(0);
      for (let i = 0; i < datos.length; i++) {
        // Decae rápido para que sea un golpe, no un siseo.
        datos[i] = (Math.random() * 2 - 1) * (1 - i / datos.length) ** 3;
      }
      const src = ctx.createBufferSource();
      src.buffer = buf;
      const bp = ctx.createBiquadFilter();
      bp.type = "bandpass";
      bp.frequency.value = 2400;
      bp.Q.value = 1.2;
      const gClac = ctx.createGain();
      gClac.gain.value = 0.26;
      src.connect(bp);
      bp.connect(gClac);
      gClac.connect(maestro);
      src.start(t0);
    }

    // Cerrar el contexto: si no, se acumula uno por aviso y el navegador
    // acaba negando los nuevos (hay un tope de contextos vivos).
    const total = GOLPES * SEPARACION + 1.4;
    setTimeout(() => ctx.close().catch(() => {}), total * 1000);
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
  // null = primera carga. Sin esto suena al entrar por los avisos viejos.
  const previas = useRef<number | null>(null);

  const q = useQuery<Respuesta>({
    queryKey: ["notificaciones"],
    queryFn: () => api.get("/api/notificaciones"),
    enabled: !!user,
    refetchInterval: 20_000,
    // CRÍTICO para este caso de uso: sin esto, React Query PAUSA el intervalo
    // cuando la pestaña pierde el foco (es su default). El diseñador tendría
    // la app abierta en otra pestaña, el cortador cerraría el corte, y no se
    // enteraría hasta volver a la pestaña — justo cuando el aviso ya no sirve.
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
  });

  const noLeidas = q.data?.no_leidas ?? 0;

  useEffect(() => {
    if (!q.data) return;
    const antes = previas.current;
    previas.current = noLeidas;
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
    <div className="fixed top-6 right-6 z-40">
      <button
        onClick={() => setAbierto((v) => !v)}
        title={noLeidas ? `${noLeidas} sin leer` : "Avisos"}
        aria-label={noLeidas ? `Avisos: ${noLeidas} sin leer` : "Avisos"}
        className={cn(
          "relative flex h-9 w-9 items-center justify-center rounded-sm border bg-card shadow-sm transition-colors",
          noLeidas > 0
            ? "border-terracotta/40 text-terracotta hover:bg-terracotta/5"
            : "border-border text-graphite hover:bg-cloud dark:hover:bg-ink-800",
        )}
      >
        <Bell className="h-4 w-4" />
        {noLeidas > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[1.15rem] h-[1.15rem] px-1 flex items-center justify-center rounded-full bg-terracotta text-[0.62rem] font-bold text-white tabular-nums shadow">
            {noLeidas > 99 ? "99+" : noLeidas}
          </span>
        )}
      </button>

      {abierto && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setAbierto(false)}
            aria-hidden
          />
          <div className="absolute top-full right-0 mt-2 z-50 w-80 max-h-[70vh] overflow-y-auto rounded-sm border border-border bg-card shadow-lg">
            <div className="sticky top-0 flex items-center justify-between border-b border-border bg-card px-3 py-2">
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
                              : "font-semibold text-ink-900 dark:text-foreground",
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
                        "px-3 py-2.5 hover:bg-cloud/60 dark:hover:bg-ink-800/60",
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
