"use client";

import { forwardRef, useEffect, useRef } from "react";

/**
 * El buscador SIEMPRE tiene el foco.
 *
 * El lector de códigos de barras es un teclado: escribe aquí sin que nadie
 * toque nada. Si el foco se pierde —porque alguien tocó otra cosa— el escaneo
 * se va al vacío y la cajera lo descubre cuando ya pasó la prenda. Por eso se
 * recupera solo.
 */
interface Props {
  valor: string;
  onCambio: (v: string) => void;
  buscando?: boolean;
}

export const Buscador = forwardRef<HTMLInputElement, Props>(function Buscador(
  { valor, onCambio, buscando },
  ref,
) {
  const interno = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const el = interno.current;
    el?.focus();
    // Recuperar el foco si se pierde por un clic en cualquier otra parte.
    const recuperar = () => {
      if (document.activeElement?.tagName !== "INPUT") el?.focus();
    };
    const t = setInterval(recuperar, 800);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <div className="flex items-center gap-3 border border-[#C8412B] bg-[#1A242A] px-3 py-2.5">
        <span aria-hidden className="text-[#6F92A6]">🔍</span>
        <input
          ref={(el) => {
            interno.current = el;
            if (typeof ref === "function") ref(el);
            else if (ref) ref.current = el;
          }}
          value={valor}
          onChange={(e) => onCambio(e.target.value)}
          placeholder="Escanea o escribe referencia, talla, color…"
          className="w-full bg-transparent font-mono text-[15px] text-[#F4F3F0] outline-none placeholder:text-[#4A5C66]"
          autoComplete="off"
          spellCheck={false}
          aria-label="Buscar producto"
        />
        {buscando && <span className="font-mono text-[10px] text-[#6F92A6]">…</span>}
      </div>
      <p className="mt-2 font-mono text-[10.5px] text-[#4A5C66]">
        El foco vive aquí. Un código de barras entra solo, sin un clic.
      </p>
    </div>
  );
});
