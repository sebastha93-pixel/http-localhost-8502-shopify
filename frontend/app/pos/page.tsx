"use client";

/**
 * La puerta del POS: `app.maledenim.com/pos`. Un solo enlace para todas las
 * tiendas.
 *
 * LA TIENDA SALE DE QUIEN ENTRA, no del enlace. Un enlace por caja se reenvía
 * por WhatsApp y acaba abierto en la tableta de la otra tienda, vendiendo
 * contra un inventario ajeno — y eso no se descubre hasta el conteo. Una
 * persona no se reenvía: la asesora entra con su correo y el POS sabe dónde
 * trabaja (`permisos_pos.tiendas`).
 *
 * LO QUE SÍ DECIDE EL EQUIPO es CUÁL de las cajas de esa tienda es. Florida
 * tiene dos mostradores y eso es una propiedad de la tableta, no de la
 * persona: se pregunta una vez y se recuerda. Donde sólo hay una caja no se
 * pregunta nada.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Panel } from "@/components/pos/marco";
import { ElegirCaja } from "@/components/pos/elegir-caja";
import { useCajaDelEquipo } from "@/lib/pos/caja-del-equipo";
import { listarCajas, type CajaDelPos } from "@/lib/pos/api";

export default function PuertaDelPos() {
  const router = useRouter();
  const caja = useCajaDelEquipo();
  const [cajas, setCajas] = useState<CajaDelPos[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Para no repetir la decisión en cada repintado: `elegir` y `olvidar`
  // cambian el estado, y sin esto el efecto volvería a entrar.
  const decidido = useRef(false);

  useEffect(() => {
    let vivo = true;
    listarCajas()
      .then((c) => { if (vivo) setCajas(c); })
      .catch((e) => {
        if (vivo) {
          setError(e instanceof Error ? e.message
                   : "No se pudo saber en qué tienda trabajas.");
        }
      });
    return () => { vivo = false; };
  }, []);

  const entrar = useCallback(() => router.replace("/pos/venta"), [router]);

  useEffect(() => {
    if (!cajas || decidido.current) return;
    if (caja.estado.fase === "cargando" || caja.estado.fase === "cambiar") return;

    const guardada = caja.estado.fase === "lista" ? caja.estado.caja : "";
    if (guardada && cajas.some((c) => c.caja_id === guardada)) {
      decidido.current = true;
      entrar();
      return;
    }
    if (guardada) {
      // El equipo recuerda una caja que ya no es de esta persona —la
      // reasignaron, o es la tableta de la otra tienda—. Se olvida y se
      // vuelve a preguntar entre las suyas.
      decidido.current = true;
      caja.olvidar();
      decidido.current = false;
      return;
    }
    if (cajas.length === 1) {
      decidido.current = true;
      void caja.elegir(cajas[0].caja_id).then(entrar);
    }
    // Con varias, se pinta el selector de abajo.
  }, [cajas, caja, entrar]);

  if (error) {
    return (
      <Centro>
        <p className="titular text-[18px]">No se pudo abrir el punto de venta</p>
        <p className="mt-3 text-[14px]" style={{ color: "var(--pos-700)" }}>
          {error}
        </p>
      </Centro>
    );
  }

  if (!cajas) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-[13px]" style={{ color: "var(--pos-600)" }}>
          Preparando la caja…
        </p>
      </div>
    );
  }

  if (cajas.length === 0) {
    return (
      <Centro>
        <p className="titular text-[18px]">Todavía no tienes caja</p>
        <p className="mt-3 text-[14px] leading-relaxed" style={{ color: "var(--pos-700)" }}>
          Tu usuario no está asignado a ninguna tienda, así que el POS no sabe
          desde qué inventario venderías. Pídele a un administrador que te
          asigne tu tienda en <b>Permisos del POS</b>.
        </p>
      </Centro>
    );
  }

  return <ElegirCaja caja={caja} alElegir={entrar} />;
}

function Centro({ children }: { children: React.ReactNode }) {
  return (
    <div className="pos-raiz flex min-h-screen items-center justify-center p-8">
      <Panel className="w-full max-w-md p-6" style={{ background: "var(--pos-surface)" }}>
        {children}
      </Panel>
    </div>
  );
}
