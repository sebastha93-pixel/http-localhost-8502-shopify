"use client";

/**
 * El cajón, contado.
 *
 * POR QUÉ NO ES UN CAMPO DE TOTAL. El cierre ya era ciego —la cajera no ve lo
 * esperado hasta que declara— pero declarar era ESCRIBIR UN NÚMERO, y quien
 * lleva el día en la cabeza puede escribir una cifra plausible sin abrir el
 * cajón. El conteo ciego más débil que existe es el que se responde de
 * memoria.
 *
 * Aquí se meten CANTIDADES y el total lo saca el sistema. El total deja de ser
 * algo que se pueda escribir.
 *
 * NO HAY BOTÓN DE «CUADRA, ES LA DE SIEMPRE». Sería exactamente el paso que
 * este componente existe para quitar.
 *
 * De mayor a menor porque es como se cuenta un cajón: los billetes grandes
 * salen primero y las monedas al final.
 */
import { useMemo } from "react";
import { formatear } from "@/lib/pos/dinero";
import type { Denominacion } from "@/lib/pos/api";

export function totalDe(piezas: Record<number, number>): number {
  return Object.entries(piezas).reduce(
    (t, [valor, cantidad]) => t + Number(valor) * (cantidad || 0), 0);
}

export function ContadorDenominaciones({
  denominaciones,
  piezas,
  onCambio,
  deshabilitado,
  columnas = 2,
}: {
  denominaciones: Denominacion[];
  piezas: Record<number, number>;
  onCambio: (piezas: Record<number, number>) => void;
  deshabilitado?: boolean;
  /** El arqueo vive en un panel de ~300px, la mitad de ancho que la pantalla
   *  de apertura. A dos columnas ahí, el subtotal de los billetes se monta
   *  encima de la etiqueta de las monedas y los dos números quedan
   *  ilegibles — justo los números que hay que leer con cuidado. */
  columnas?: 1 | 2;
}) {
  const total = useMemo(() => totalDe(piezas), [piezas]);
  const billetes = denominaciones.filter((d) => d.tipo === "billete");
  const monedas = denominaciones.filter((d) => d.tipo === "moneda");

  function poner(valor: number, texto: string) {
    // Sólo dígitos: un «4a» que se cuela como NaN convertiría el total en NaN
    // y la pantalla mostraría «$NaN» justo cuando hay que confiar en ella.
    const n = texto.replace(/[^\d]/g, "");
    const siguiente = { ...piezas };
    if (n === "") delete siguiente[valor];
    else siguiente[valor] = Math.min(Number(n), 99999);
    onCambio(siguiente);
  }

  const fila = (d: Denominacion) => {
    const cantidad = piezas[d.valor_centavos];
    return (
      <div
        key={d.valor_centavos}
        className="flex items-center gap-3 border-b py-1.5 last:border-0"
        style={{ borderColor: "var(--pos-divider)" }}
      >
        <span className="tabular w-[86px] shrink-0 text-[13px] font-medium">
          {formatear(d.valor_centavos)}
        </span>
        <input
          inputMode="numeric"
          disabled={deshabilitado}
          value={cantidad ?? ""}
          onChange={(e) => poner(d.valor_centavos, e.target.value)}
          onFocus={(e) => e.target.select()}
          placeholder="0"
          aria-label={`Cuántos de ${formatear(d.valor_centavos)}`}
          className="tabular h-11 w-[68px] border px-2 text-center text-[15px] outline-none disabled:opacity-50"
          style={{ borderColor: "var(--pos-divider)", background: "#fff",
                   color: "var(--pos-text)" }}
        />
        {/* El subtotal por fila es lo que delata la fila mal digitada: «4 de
            cincuenta» son $200.000, y un cero de más se ve al instante. */}
        <span
          className="tabular flex-1 text-right text-[13px]"
          style={{ color: cantidad ? "var(--pos-700)" : "var(--pos-muted)" }}
        >
          {cantidad ? formatear(d.valor_centavos * cantidad) : "—"}
        </span>
      </div>
    );
  };

  return (
    <div>
      <div
        className={columnas === 2 ? "grid gap-x-8 sm:grid-cols-2" : "flex flex-col"}
      >
        <div>
          <p className="kicker mb-1" style={{ color: "var(--pos-600)" }}>
            Billetes
          </p>
          {billetes.map(fila)}
        </div>
        <div className={columnas === 2 ? "mt-4 sm:mt-0" : "mt-4"}>
          <p className="kicker mb-1" style={{ color: "var(--pos-600)" }}>
            Monedas
          </p>
          {monedas.map(fila)}
        </div>
      </div>

      <div
        className="mt-4 flex items-baseline justify-between border-t pt-3"
        style={{ borderColor: "var(--pos-divider)" }}
      >
        <span className="kicker" style={{ color: "var(--pos-600)" }}>
          Contado
        </span>
        <span className="tabular text-[24px] font-semibold">
          {formatear(total)}
        </span>
      </div>
    </div>
  );
}
