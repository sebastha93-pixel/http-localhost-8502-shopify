"use client";

/**
 * Registra el service worker del POS.
 *
 * VA SÓLO EN EL POS, no en el ERP: el ERP no está pensado para funcionar sin
 * red y una caché a sus espaldas le mostraría datos viejos de producción sin
 * avisar. El `scope` se limita a `/pos/` por lo mismo.
 *
 * SÓLO EN PRODUCCIÓN. En desarrollo, el service worker sirve paquetes
 * guardados y hace que un cambio en el código no aparezca al recargar —se pasa
 * media hora buscando un bug que ya estaba arreglado—. Además Next reconstruye
 * los nombres con hash a cada rato y la caché se llena de basura.
 *
 * NO ES BLOQUEANTE: si el registro falla —navegador viejo, sin HTTPS— el POS
 * funciona igual, sólo pierde la capacidad de ARRANCAR sin red. Lo demás
 * (cola de ventas, catálogo local, tirilla) no depende de esto.
 */
import { useEffect } from "react";

export function RegistrarSW() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;

    // Tras `load` para no competir por ancho de banda con la primera pintada,
    // que es la que la cajera está esperando.
    const registrar = () => {
      navigator.serviceWorker
        .register("/pos-sw.js", { scope: "/pos/" })
        .catch(() => {
          // Silencio a propósito: un POS que muestra un error de service
          // worker en el mostrador asusta sin que nadie pueda hacer nada.
        });
    };

    if (document.readyState === "complete") registrar();
    else window.addEventListener("load", registrar);
    return () => window.removeEventListener("load", registrar);
  }, []);

  return null;
}
