"use client";

/**
 * Marcas de registro del sistema — la firma visual del handoff.
 *
 * Se pintan FUERA del borde, así que cualquier `overflow:hidden` en un
 * ancestro se las come. Por eso van como componente y no como utilidad
 * suelta: el sitio donde se ponen importa tanto como el estilo.
 */
export function Esquinas() {
  return (
    <>
      <i className="corner tl" aria-hidden />
      <i className="corner tr" aria-hidden />
      <i className="corner bl" aria-hidden />
      <i className="corner br" aria-hidden />
    </>
  );
}

export function Panel({
  children,
  className = "",
  ...resto
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`blueprint ${className}`} {...resto}>
      <Esquinas />
      {children}
    </div>
  );
}
