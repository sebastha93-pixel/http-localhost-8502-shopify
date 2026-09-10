/**
 * QUÉ CAJA ES ESTE EQUIPO.
 *
 * Salía de `NEXT_PUBLIC_POS_CAJA`, una variable que se hornea al publicar:
 * UNA caja para toda la app, así que Florida y Arrayanes no podían usar el
 * mismo sitio. Ahora cada tableta lo aprende de su enlace
 * —`/pos/venta?caja=arrayanes_caja1`— y lo recuerda. Sin enlace, lo elige una
 * vez de la lista.
 *
 * La TIENDA y el INVENTARIO no se guardan aquí: salen de la caja, en el
 * servidor (`/caja/contexto`). Eran tres variables sueltas que podían
 * contradecirse; ahora es un dato y dos consecuencias.
 *
 * Vive en `localStorage` y no en IndexedDB porque se lee al pintar la primera
 * pantalla, sin red y antes que nada. Se borran juntos con «borrar datos del
 * sitio», igual que la cola: un equipo sin ellos es, a efectos prácticos, un
 * equipo nuevo.
 */
import { useCallback, useEffect, useState } from "react";
import { contextoCaja, type ContextoCaja } from "@/lib/pos/api";
import {
  guardarContexto,
  leerContexto,
  olvidarDatosDeCaja,
} from "@/lib/pos/almacen";

const CLAVE = "pos.caja";
// El mismo formato que los ids de `retail.cajas`. Un enlace roto o manipulado
// no puede dejar al equipo apuntando a basura.
const FORMATO = /^[a-z0-9_]{1,60}$/;

function guardada(): string {
  try {
    return localStorage.getItem(CLAVE) || "";
  } catch {
    return "";
  }
}

/** La del equipo. SIN respaldo en `NEXT_PUBLIC_POS_CAJA`: con él, un equipo
 *  en desarrollo se comportaba distinto que uno en producción —nunca pedía el
 *  enlace— y lo que se probaba en local no era lo que corría en la tienda. */
function actual(): string {
  return guardada();
}

function delEnlace(): string {
  const v = new URLSearchParams(window.location.search).get("caja") || "";
  return FORMATO.test(v) ? v : "";
}

/** Quita `?caja=` de la barra: ya se leyó, y dejarlo haría volver a
 *  preguntar en cada recarga a quien eligió seguir con la suya. */
function limpiarEnlace(): void {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("caja")) return;
  url.searchParams.delete("caja");
  window.history.replaceState(null, "", url.pathname + url.search + url.hash);
}

export type EstadoCaja =
  | { fase: "cargando" }
  | { fase: "sin_caja" }
  | { fase: "cambiar"; actual: string; nueva: string }
  | { fase: "lista"; caja: string };

export interface CajaDelEquipo {
  estado: EstadoCaja;
  /** Deja este equipo como `id` y olvida lo guardado de la caja anterior. */
  elegir: (id: string) => Promise<void>;
  /** Se queda con la que tenía e ignora el enlace. */
  conservar: () => void;
  /** Deja el equipo sin caja, para volver a elegir. */
  olvidar: () => void;
}

export function useCajaDelEquipo(): CajaDelEquipo {
  const [estado, setEstado] = useState<EstadoCaja>({ fase: "cargando" });

  const elegir = useCallback(async (id: string) => {
    setEstado({ fase: "cargando" });
    try {
      localStorage.setItem(CLAVE, id);
    } catch {
      // Sin almacenamiento el equipo no recuerda, pero puede vender esta vez.
    }
    // Sin IndexedDB no hay nada que olvidar; no es motivo para no vender.
    await olvidarDatosDeCaja().catch(() => {});
    limpiarEnlace();
    setEstado({ fase: "lista", caja: id });
  }, []);

  const conservar = useCallback(() => {
    limpiarEnlace();
    const c = actual();
    setEstado(c ? { fase: "lista", caja: c } : { fase: "sin_caja" });
  }, []);

  const olvidar = useCallback(() => {
    try {
      localStorage.removeItem(CLAVE);
    } catch {
      // nada que borrar
    }
    setEstado({ fase: "sin_caja" });
  }, []);

  // En un efecto y no al inicializar el estado: el servidor no tiene
  // `localStorage`, y leerlo antes de hidratar pintaría dos cosas distintas.
  useEffect(() => {
    const enlace = delEnlace();
    const c = actual();
    if (enlace && enlace !== c) {
      // Un equipo que YA es una caja no cambia de tienda por abrir un enlace
      // equivocado: se pregunta. Uno nuevo se configura con el enlace.
      if (c) setEstado({ fase: "cambiar", actual: c, nueva: enlace });
      else void elegir(enlace);
      return;
    }
    limpiarEnlace();
    setEstado(c ? { fase: "lista", caja: c } : { fase: "sin_caja" });
  }, [elegir]);

  return { estado, elegir, conservar, olvidar };
}

/**
 * La tienda y el inventario de la caja, con la copia local si no hay red.
 *
 * La copia sólo vale si es DE ESTA CAJA: la de otra traería los medios de
 * pago y el inventario de otra tienda.
 */
export function useContextoDeCaja(caja: string): {
  contexto: ContextoCaja | null;
  error: string | null;
} {
  const [contexto, setContexto] = useState<ContextoCaja | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const ctx = await contextoCaja(caja);
        if (!vivo) return;
        setContexto(ctx);
        void guardarContexto(ctx).catch(() => {});
      } catch (e) {
        const guardado = await leerContexto<ContextoCaja>().catch(() => undefined);
        if (!vivo) return;
        if (guardado && guardado.caja_id === caja) setContexto(guardado);
        else setError(e instanceof Error ? e.message : "No se pudo leer la caja.");
      }
    })();
    return () => {
      vivo = false;
    };
  }, [caja]);

  return { contexto, error };
}
