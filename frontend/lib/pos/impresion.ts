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
 * No viaja al servidor a propósito: si el equipo se cambia, la impresora
 * también, y heredar el ajuste de la anterior sería empezar mal.
 */
import { useCallback, useEffect, useState } from "react";

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
  letraPct: { min: 70, max: 160, paso: 5 },
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

/** El ajuste vigente. Se entera si cambia en esta pestaña o en otra. */
export function useConfigImpresion(): [
  ConfigImpresion,
  (c: Partial<ConfigImpresion>) => void,
] {
  const [cfg, setCfg] = useState<ConfigImpresion>(IMPRESION_POR_DEFECTO);
  useEffect(() => {
    const releer = () => setCfg(leerImpresion());
    releer();
    window.addEventListener(AVISO, releer);
    window.addEventListener("storage", releer);
    return () => {
      window.removeEventListener(AVISO, releer);
      window.removeEventListener("storage", releer);
    };
  }, []);
  const guardar = useCallback((c: Partial<ConfigImpresion>) => {
    setCfg(guardarImpresion(c));
  }, []);
  return [cfg, guardar];
}
