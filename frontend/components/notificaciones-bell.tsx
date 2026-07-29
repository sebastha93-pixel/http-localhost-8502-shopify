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
 * interactúa con la página. El contexto se crea al montar y se despierta con
 * cualquier gesto (click, tecla, scroll, rueda, foco). Si la página se carga y
 * NADIE la toca, no hay forma de hacerlo sonar — es política del navegador, no
 * un bug. Para esos casos está el botón "Probar" del panel, y sobre todo la
 * notificación del sistema, cuyo permiso SÍ persiste entre recargas.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { Bell, Check, Scissors, PackageCheck, Truck, Volume2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
//
// Cuentas actuales: los `parciales` de abajo suman 1.60 y el "clac" 0.13 =
// 1.73; por 0.62 del maestro da un pico de ~1.07, que el compresor
// (−3 dB, ratio 3) deja en ~0.81 de salida.
//
// DOS TRAMPAS, las dos ya pisadas acá:
//  1. Subir VOLUMEN sin bajar las amplitudes NO lo hace más fuerte. Le mete
//     más señal al compresor, que aplasta el golpe y suena MÁS FLOJO. Si
//     quieres más nivel, sube el threshold del compresor, no el maestro.
//  2. Subir los agudos tampoco. El oído es más sensible entre 2 y 4 kHz, así
//     que ahí lo que se gana es aspereza, no volumen. Para más cuerpo se sube
//     110/220 Hz y se alargan las colas.
const VOLUMEN = 0.62;
const GOLPES = 2;        // repeticiones del golpe
const SEPARACION = 0.26; // segundos entre golpes

/**
 * Golpe de campana con cuerpo: fundamental grave + armónicos + un "clac" de
 * ataque. Antes eran dos senoidales limpias y sonaban a notificación de
 * celular; esto se parece más a un timbre de taller, que es donde se usa.
 */
function tocarTimbre(ctx: AudioContext) {
  try {
    // El contexto llega YA creado y desbloqueado por un gesto del usuario.
    // Si está suspendido (el navegador lo duerme en pestañas de fondo), se
    // reanuda: eso SÍ está permitido, porque el contexto nació de un gesto.
    if (ctx.state === "suspended") void ctx.resume();

    // Compresor: deja subir el volumen sin que sature ni distorsione.
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -3;
    comp.ratio.value = 3;
    comp.connect(ctx.destination);

    const maestro = ctx.createGain();
    maestro.gain.value = VOLUMEN;
    maestro.connect(comp);

    // Acorde consonante sobre La: 110 (sub) · 220 (fundamental) · 330 (quinta)
    // · 440 (octava) · 660 (quinta alta, suave). Todos armónicos enteros de
    // 110, así que no hay batimientos: suena a acorde, no a alarma.
    //
    // POR QUÉ NO HAY NADA ARRIBA DE 660: el oído es más sensible entre 2 y 4
    // kHz, que es exactamente donde vive lo "estridente". La versión anterior
    // tenía un parcial en 1320 y el "clac" filtrado en 2400: eso picaba. Para
    // que suene MÁS FUERTE sin lastimar, la energía va en graves y medios, que
    // dan peso y volumen percibido. Colas más largas también leen como "más
    // lleno" sin subir un solo decibel de pico.
    const parciales = [
      { f: 110, a: 0.34, dur: 1.5, tipo: "sine" as OscillatorType },
      { f: 220, a: 0.58, dur: 1.4, tipo: "triangle" as OscillatorType },
      { f: 330, a: 0.30, dur: 1.1, tipo: "sine" as OscillatorType },
      { f: 440, a: 0.26, dur: 1.0, tipo: "sine" as OscillatorType },
      { f: 660, a: 0.12, dur: 0.7, tipo: "sine" as OscillatorType },
    ];

    for (let g = 0; g < GOLPES; g++) {
      const t0 = ctx.currentTime + g * SEPARACION;
      // Segundo golpe una CUARTA JUSTA abajo (0.75 = 3/4): el "din-don"
      // clasico. El semitono anterior (0.94) chocaba con el primero.
      const detune = g === 0 ? 1 : 0.75;

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
      bp.frequency.value = 1100;
      bp.Q.value = 0.8;
      const gClac = ctx.createGain();
      gClac.gain.value = 0.13;
      src.connect(bp);
      bp.connect(gClac);
      gClac.connect(maestro);
      src.start(t0);
    }

    // NO se cierra el contexto: es compartido y se reutiliza en cada aviso.
    // Cerrarlo obligaría a crear uno nuevo, y uno creado fuera de un gesto
    // del usuario nace suspendido y no suena — que era justo el bug.
  } catch {
    /* sin audio disponible — el badge visual sigue funcionando */
  }
}

/**
 * Crea UN AudioContext en el primer gesto del usuario y lo reutiliza siempre.
 *
 * EL BUG QUE ESTO ARREGLA: antes se creaba un contexto nuevo en el momento de
 * cada aviso. Si la pestaña estaba en segundo plano (el caso normal: tienes la
 * app abierta y trabajas en otra cosa), ese contexto nacía suspendido y el
 * aviso llegaba MUDO. El badge subía, el sonido no salía.
 *
 * Un contexto creado DURANTE un gesto queda autorizado para toda la vida de la
 * página y puede sonar después, incluso desde una pestaña de fondo.
 */
function useAudioCompartido() {
  const ref = useRef<AudioContext | null>(null);
  useEffect(() => {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctx) return;

    // Se crea DE ENTRADA, no al primer click. Nace suspendido (política de
    // autoplay) pero existir desde el arranque significa que cualquier gesto
    // posterior lo puede despertar. Antes se creaba solo al hacer click, así
    // que si el usuario recargaba y se iba a otra ventana sin tocar nada —su
    // flujo real— no había contexto y el aviso llegaba mudo.
    try {
      ref.current = new Ctx();
    } catch {
      return;
    }

    // Cualquiera de estos gestos sirve para despertarlo. Se escucha una lista
    // amplia a propósito: mientras más caminos, más probable que quede listo
    // antes del primer aviso. `pointerdown` y `touchstart` cubren tablet.
    const EVENTOS = [
      "pointerdown", "mousedown", "click", "keydown",
      "touchstart", "wheel", "scroll", "focus",
    ] as const;

    const despertar = () => {
      const ctx = ref.current;
      if (!ctx) return;
      if (ctx.state === "running") return;
      ctx.resume()
        .then(() => {
          // Tick inaudible: algunos navegadores solo dan el contexto por
          // "usado" —y por tanto autorizado a sonar luego— si algo se
          // reprodujo dentro del gesto.
          try {
            const g = ctx.createGain();
            g.gain.value = 0;
            g.connect(ctx.destination);
            const o = ctx.createOscillator();
            o.connect(g);
            o.start();
            o.stop(ctx.currentTime + 0.01);
          } catch {
            /* da igual, lo importante era el resume */
          }
        })
        .catch(() => {});
    };

    EVENTOS.forEach((e) =>
      window.addEventListener(e, despertar, { passive: true }),
    );
    return () => {
      EVENTOS.forEach((e) => window.removeEventListener(e, despertar));
    };
  }, []);
  return ref;
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
  const router = useRouter();
  const [abierto, setAbierto] = useState(false);
  const audioCtx = useAudioCompartido();
  // null = primera carga. Sin esto suena al entrar por los avisos viejos.
  const previas = useRef<number | null>(null);

  // Permiso para notificaciones del sistema (macOS/Windows). Se pide en el
  // primer gesto, no al cargar: pedirlo de entrada es intrusivo y los
  // navegadores penalizan los prompts sin contexto.
  //
  // A DIFERENCIA DEL AUDIO, este permiso PERSISTE entre recargas. Es por eso
  // el canal fiable para quien deja la app abierta y trabaja en otra ventana:
  // se concede una vez y macOS pone el banner (con su propio sonido) para
  // siempre, sin depender de la política de autoplay que tumba el audio en
  // cada recarga.
  useEffect(() => {
    if (typeof Notification === "undefined") return;
    if (Notification.permission !== "default") return;
    const EVENTOS = ["pointerdown", "click", "keydown", "touchstart"] as const;
    const pedir = () => {
      EVENTOS.forEach((e) => window.removeEventListener(e, pedir));
      Notification.requestPermission().catch(() => {});
    };
    EVENTOS.forEach((e) =>
      window.addEventListener(e, pedir, { passive: true }),
    );
    return () => EVENTOS.forEach((e) => window.removeEventListener(e, pedir));
  }, []);

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

  // Prueba manual del timbre. El click en sí ya despierta el AudioContext
  // (useAudioCompartido escucha `click`), así que si antes no sonaba, después
  // de tocar este botón una vez empieza a sonar en esta pestaña.
  const probarSonido = useCallback(() => {
    const ctx = audioCtx.current;
    if (!ctx) return;
    if (ctx.state === "suspended") {
      ctx.resume().then(() => tocarTimbre(ctx)).catch(() => {});
    } else {
      tocarTimbre(ctx);
    }
  }, [audioCtx]);

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

  useEffect(() => {
    if (!q.data) return;
    const antes = previas.current;
    previas.current = noLeidas;
    if (antes === null || noLeidas <= antes) return;

    if (audioCtx.current) tocarTimbre(audioCtx.current);

    // Notificación del sistema: es lo único que se ve cuando el navegador
    // está detrás de otra ventana. `tag` fijo para que no se apilen 10.
    try {
      if (typeof Notification !== "undefined" &&
          Notification.permission === "granted") {
        const nueva = q.data?.notificaciones?.find((x) => !x.leida);
        const banner = new Notification("MALE'DENIM · Producción", {
          body: nueva?.titulo ?? `${noLeidas} avisos sin leer`,
          tag: "maledenim-avisos",
        });
        // Tocar el banner lleva al movimiento que lo genero. Sin esto el
        // banner era decorativo: se podia hacer click y no pasaba nada.
        banner.onclick = () => {
          try {
            window.focus();          // traer el navegador al frente
            banner.close();
            if (nueva) {
              if (!nueva.leida) marcarUna(nueva.id);
              if (nueva.enlace) router.push(nueva.enlace);
            }
          } catch {
            /* si no se puede navegar, al menos se enfocó la ventana */
          }
        };
      }
    } catch {
      /* sin soporte de notificaciones — el sonido y el badge siguen */
    }
  }, [noLeidas, q.data, audioCtx, router, marcarUna]);



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
              <div className="flex items-center gap-3">
                {/* Probar el timbre a voluntad. Doble propósito: además de
                    dejarte oírlo, el click DESBLOQUEA el audio del navegador
                    — que es la parte frágil de todo esto. */}
                <button
                  onClick={probarSonido}
                  title="Escuchar el timbre (y habilitar el audio de esta pestaña)"
                  className="inline-flex items-center gap-1 text-[0.68rem] font-semibold text-graphite hover:text-ink-900 dark:hover:text-foreground"
                >
                  <Volume2 className="h-3 w-3" /> Probar
                </button>
                {noLeidas > 0 && (
                  <button
                    onClick={marcarTodas}
                    className="inline-flex items-center gap-1 text-[0.68rem] font-semibold text-teal hover:underline"
                  >
                    <Check className="h-3 w-3" /> Marcar todas
                  </button>
                )}
              </div>
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
