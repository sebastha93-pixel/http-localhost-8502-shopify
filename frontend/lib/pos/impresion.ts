"use client";

/**
 * Cómo imprime ESTE equipo.
 *
 * POR QUÉ ES DEL EQUIPO Y NO DE LA TIENDA. La misma tirilla salió bien en
 * Arrayanes y en Florida salió más pequeña y cortada por la derecha
 * (2026-10-10): otra impresora, otro controlador, otra área imprimible. Eso no
 * lo sabe el servidor ni lo puede adivinar el navegador — lo sabe quien está
 * frente a la impresora con el papel en la mano. Por eso se ajusta ahí, con
 * una tirilla de prueba, y se guarda en el equipo.
 *
 * SE GUARDA EN LA CAJA, EN EL SERVIDOR (2026-10-10). Vivía sólo en el
 * navegador, y eso falló de dos maneras: quien lo ajustaba desde su propio
 * computador veía cambiar la vista previa mientras la caja de la tienda seguía
 * imprimiendo igual —eran dos navegadores—, y un navegador que borra sus datos
 * lo perdía. Ahora la caja lo lee del servidor cada vez que abre una pantalla
 * que imprime; el navegador sólo guarda una copia para cuando no hay red.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cajaDeEsteEquipo } from "@/lib/pos/caja-del-equipo";

export interface ConfigImpresion {
  /** Ancho de la hoja que se le declara a la impresora, en mm (el rollo). */
  hojaMm: number;
  /** Ancho que ocupa el texto, en mm. Menor que la hoja: el cabezal no llega
   *  a los bordes, y lo que se pase sale cortado. */
  anchoMm: number;
  /** Tamaño de la letra, en porcentaje del normal. */
  letraPct: number;
  /** Corrimiento hacia la derecha, en mm, si la impresora empieza muy pegada
   *  al borde izquierdo. */
  margenMm: number;
}

export const IMPRESION_POR_DEFECTO: ConfigImpresion = {
  hojaMm: 80, anchoMm: 72, letraPct: 100, margenMm: 0,
};

export const LIMITES = {
  hojaMm: { min: 48, max: 90, paso: 1 },
  anchoMm: { min: 40, max: 80, paso: 1 },
  // Hasta 250: hay controladores que encogen la hoja entera, y con 160 no
  // alcanzaba a compensarse.
  letraPct: { min: 70, max: 250, paso: 5 },
  margenMm: { min: 0, max: 12, paso: 0.5 },
} as const;

const CLAVE = "pos.impresion";
const AVISO = "pos:impresion";

function acotar(c: Partial<ConfigImpresion>): ConfigImpresion {
  const dentro = (v: unknown, k: keyof ConfigImpresion) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return IMPRESION_POR_DEFECTO[k];
    return Math.min(Math.max(n, LIMITES[k].min), LIMITES[k].max);
  };
  const cfg = {
    hojaMm: dentro(c.hojaMm, "hojaMm"),
    anchoMm: dentro(c.anchoMm, "anchoMm"),
    letraPct: dentro(c.letraPct, "letraPct"),
    margenMm: dentro(c.margenMm, "margenMm"),
  };
  // El texto no puede ser más ancho que la hoja menos el corrimiento.
  cfg.anchoMm = Math.min(cfg.anchoMm, cfg.hojaMm - cfg.margenMm);
  return cfg;
}

export function leerImpresion(): ConfigImpresion {
  if (typeof window === "undefined") return IMPRESION_POR_DEFECTO;
  try {
    const crudo = window.localStorage.getItem(CLAVE);
    return crudo ? acotar(JSON.parse(crudo)) : IMPRESION_POR_DEFECTO;
  } catch {
    // Un ajuste corrupto no puede dejar a la caja sin imprimir.
    return IMPRESION_POR_DEFECTO;
  }
}

export function guardarImpresion(c: Partial<ConfigImpresion>): ConfigImpresion {
  const limpio = acotar(c);
  try {
    window.localStorage.setItem(CLAVE, JSON.stringify(limpio));
  } catch {
    /* sin almacenamiento, vale para esta sesión */
  }
  window.dispatchEvent(new CustomEvent(AVISO));
  return limpio;
}

// ── El servidor ─────────────────────────────────────────────────────────────

/** Una consulta por carga de página y por caja: varias pantallas montan la
 *  tirilla y no hace falta preguntar lo mismo cada vez. */
const pedidas = new Map<string, Promise<ConfigImpresion | null>>();

export function impresionDeLaCaja(caja: string): Promise<ConfigImpresion | null> {
  if (!caja) return Promise.resolve(null);
  let p = pedidas.get(caja);
  if (!p) {
    p = api
      .get<{ impresion: Partial<ConfigImpresion> | null }>(
        `/api/retail/caja/impresion?${new URLSearchParams({ caja_id: caja })}`)
      .then((r) => (r.impresion ? acotar(r.impresion) : null))
      .catch(() => {
        pedidas.delete(caja);      // sin red: que se vuelva a intentar luego
        return null;
      });
    pedidas.set(caja, p);
  }
  return p;
}

/** Deja el ajuste puesto EN LA CAJA. Lanza si el servidor no lo recibió:
 *  decir «guardado» sin haberlo guardado es justo lo que se está arreglando. */
export async function guardarImpresionEnLaCaja(
  caja: string, c: Partial<ConfigImpresion>,
): Promise<ConfigImpresion> {
  const limpio = acotar(c);
  const r = await api.post<{ impresion: ConfigImpresion }>(
    "/api/retail/caja/impresion", { caja_id: caja, ...limpio });
  const guardado = acotar(r.impresion);
  pedidas.set(caja, Promise.resolve(guardado));
  guardarImpresion(guardado);
  return guardado;
}

/** El ajuste vigente. Se entera si cambia en esta pestaña o en otra. */
export function useConfigImpresion(): [
  ConfigImpresion,
  (c: Partial<ConfigImpresion>) => void,
] {
  const [cfg, setCfg] = useState<ConfigImpresion>(IMPRESION_POR_DEFECTO);
  useEffect(() => {
    const releer = () => setCfg(leerImpresion());
    releer();
    // LO QUE DIGA LA CAJA MANDA sobre la copia de este navegador.
    let vivo = true;
    impresionDeLaCaja(cajaDeEsteEquipo()).then((delServidor) => {
      if (vivo && delServidor) guardarImpresion(delServidor);
    });
    window.addEventListener(AVISO, releer);
    window.addEventListener("storage", releer);
    return () => {
      vivo = false;
      window.removeEventListener(AVISO, releer);
      window.removeEventListener("storage", releer);
    };
  }, []);
  const guardar = useCallback((c: Partial<ConfigImpresion>) => {
    setCfg(guardarImpresion(c));
  }, []);
  return [cfg, guardar];
}
