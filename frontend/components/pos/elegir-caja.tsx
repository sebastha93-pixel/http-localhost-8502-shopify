"use client";

/**
 * Qué caja es este equipo — la pantalla que sale cuando no se sabe.
 *
 * Dos casos. Un equipo NUEVO sin enlace elige de la lista, una sola vez. Y un
 * equipo que YA es una caja y abre el enlace de otra: no se cambia solo,
 * porque cambiar de caja es cambiar de tienda y de inventario, y un enlace
 * reenviado por error no puede mandar a vender contra el stock ajeno.
 */
import { useEffect, useState } from "react";
import { Panel } from "@/components/pos/marco";
import { listarCajas, type CajaDelPos, type ContextoCaja } from "@/lib/pos/api";
import {
  useCajaDelEquipo,
  useContextoDeCaja,
  type CajaDelEquipo,
} from "@/lib/pos/caja-del-equipo";

/**
 * Para las pantallas que necesitan la TIENDA de la caja —el panel, el
 * inventario—: resuelve la caja del equipo y su contexto, y sólo entonces
 * pinta. Así ninguna pantalla vuelve a leer la tienda de una variable.
 */
export function ConLaCaja({ children }: {
  children: (contexto: ContextoCaja) => React.ReactNode;
}) {
  const caja = useCajaDelEquipo();
  if (caja.estado.fase !== "lista") return <ElegirCaja caja={caja} />;
  return (
    <ConContexto key={caja.estado.caja} caja={caja.estado.caja}
                 onOtraCaja={caja.olvidar}>
      {children}
    </ConContexto>
  );
}

function ConContexto({ caja, onOtraCaja, children }: {
  caja: string;
  onOtraCaja: () => void;
  children: (contexto: ContextoCaja) => React.ReactNode;
}) {
  const { contexto, error } = useContextoDeCaja(caja);
  if (error) {
    return (
      <Centro>
        <p className="titular text-[18px]">No se pudo leer la caja «{caja}»</p>
        <p className="mt-3 text-[14px]" style={{ color: "var(--pos-700)" }}>
          {error}
        </p>
        <button
          type="button"
          onClick={onOtraCaja}
          className="pos-btn pos-btn-sec mt-5 h-12 px-4 text-[15px]"
        >
          Elegir otra caja
        </button>
      </Centro>
    );
  }
  if (!contexto) return <Preparando />;
  return <>{children(contexto)}</>;
}

function Preparando() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-[13px]" style={{ color: "var(--pos-600)" }}>
        Preparando la caja…
      </p>
    </div>
  );
}

export function ElegirCaja({ caja }: { caja: CajaDelEquipo }) {
  const { estado, elegir, conservar } = caja;
  const [cajas, setCajas] = useState<CajaDelPos[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pregunta = estado.fase === "sin_caja" || estado.fase === "cambiar";

  useEffect(() => {
    if (!pregunta) return;
    let vivo = true;
    listarCajas()
      .then((c) => {
        if (vivo) setCajas(c);
      })
      .catch((e) => {
        if (vivo) {
          setError(e instanceof Error ? e.message
                   : "No se pudo traer la lista de cajas.");
        }
      });
    return () => {
      vivo = false;
    };
  }, [pregunta]);

  if (!pregunta) return <Preparando />;

  const nombre = (id: string) => {
    const c = cajas?.find((x) => x.caja_id === id);
    return c ? `${c.tienda_nombre} · ${c.caja_nombre}` : id;
  };

  if (estado.fase === "cambiar") {
    return (
      <Centro>
        <p className="titular text-[18px]">¿Cambiar la caja de este equipo?</p>
        <p className="mt-3 text-[14px]" style={{ color: "var(--pos-700)" }}>
          Este equipo es <b>{nombre(estado.actual)}</b>. El enlace que abriste
          es de <b>{nombre(estado.nueva)}</b>. Si lo cambias, vende desde el
          inventario de esa tienda. Las ventas que falten por enviar no se
          pierden.
        </p>
        <div className="mt-5 flex flex-col gap-2">
          <button
            type="button"
            onClick={() => void elegir(estado.nueva)}
            className="pos-btn pos-btn-primario h-12 px-4 text-[15px]"
          >
            Sí, este equipo es {nombre(estado.nueva)}
          </button>
          <button
            type="button"
            onClick={conservar}
            className="pos-btn pos-btn-sec h-12 px-4 text-[15px]"
          >
            No, sigue siendo {nombre(estado.actual)}
          </button>
        </div>
      </Centro>
    );
  }

  const tiendas = agrupar(cajas ?? []);

  return (
    <Centro>
      <p className="titular text-[18px]">¿Qué caja es este equipo?</p>
      <p className="mt-3 text-[14px]" style={{ color: "var(--pos-700)" }}>
        Se elige una sola vez: el equipo lo recuerda. Con el enlace de la caja
        no hace falta elegir.
      </p>

      {error && (
        <p role="alert" className="mt-4 text-[13px]" style={{ color: "var(--pos-900)" }}>
          {error}
        </p>
      )}
      {!cajas && !error && (
        <p className="mt-4 text-[13px]" style={{ color: "var(--pos-600)" }}>
          Cargando cajas…
        </p>
      )}
      {cajas && cajas.length === 0 && (
        <p className="mt-4 text-[13px]" style={{ color: "var(--pos-700)" }}>
          Todavía no hay ninguna caja creada.
        </p>
      )}

      {tiendas.map(([tienda, suyas]) => (
        <div key={tienda} className="mt-5">
          <p className="kicker">{tienda}</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {suyas.map((c) => (
              <button
                key={c.caja_id}
                type="button"
                onClick={() => void elegir(c.caja_id)}
                className="pos-btn pos-btn-sec h-12 px-4 text-[15px]"
              >
                {c.caja_nombre}
              </button>
            ))}
          </div>
        </div>
      ))}
    </Centro>
  );
}

function agrupar(cajas: CajaDelPos[]): [string, CajaDelPos[]][] {
  const m = new Map<string, CajaDelPos[]>();
  for (const c of cajas) m.set(c.tienda_nombre, [...(m.get(c.tienda_nombre) ?? []), c]);
  return Array.from(m.entries());
}

function Centro({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <Panel className="w-full max-w-md p-6" style={{ background: "var(--pos-surface)" }}>
        {children}
      </Panel>
    </div>
  );
}
