"use client";

/**
 * La tarjeta del sistema.
 *
 * ── LAS MARCAS DE REGISTRO SE FUERON CON LA v1 (handoff v2, 2026-08-25) ─────
 * `Esquinas` pintaba cuatro marcas de plano por fuera del borde: era la firma
 * visual del handoff «Industry». La v2 las elimina de forma explícita — «los
 * `<i class="corner">` están ocultos con display:none — no implementarlos».
 *
 * El componente NO se borra, y no es por nostalgia: lo llaman varias pantallas
 * y `pos.css` ya apaga `.corner`, así que borrarlo aquí obligaría a tocar
 * todos esos archivos en el mismo commit que cambia la paleta — y mezclar
 * «quitar las esquinas» con «reescribir los colores» en un diff hace imposible
 * revisar ninguna de las dos cosas. Devuelve `null`, el rediseño se ve solo, y
 * cuando ya no lo nombre nadie se va.
 */
export function Esquinas() {
  return null;
}

export function Panel({
  children,
  className = "",
  ...resto
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`blueprint ${className}`} {...resto}>
      {children}
    </div>
  );
}
