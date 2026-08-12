"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Rail de navegación — 92px, cinco secciones.
 *
 * Es lo que mi diseño no tenía: sin él, cada pantalla del POS era un callejón
 * sin salida. Viene del handoff.
 *
 * Sólo lleva a lo que existe. Devoluciones queda fuera de esta fase por
 * decisión de alcance, y un enlace que no lleva a nada enseña a la cajera a
 * desconfiar de la navegación.
 */
const SECCIONES = [
  { href: "/pos/venta", label: "Venta", icono: BolsaIcono, listo: true },
  { href: "/pos/inventario", label: "Stock", icono: CajaIcono, listo: true },
  { href: "/pos/cierre", label: "Cierre", icono: CandadoIcono, listo: true },
  { href: "/pos/panel", label: "Panel", icono: BarrasIcono, listo: false },
];

export function Rail({ cajera }: { cajera: string }) {
  const ruta = usePathname();

  return (
    <nav
      className="flex w-[92px] shrink-0 flex-col items-center border-r py-4"
      style={{ borderColor: "var(--pos-divider)" }}
      aria-label="Secciones del punto de venta"
    >
      <span className="titular mb-6 text-[15px] tracking-tight">M&apos;D</span>

      <ul className="flex w-full flex-col items-center gap-1">
        {SECCIONES.map((s) => {
          const activo = ruta.startsWith(s.href);
          const Icono = s.icono;
          const contenido = (
            <>
              <Icono />
              <span className="kicker mt-1.5">{s.label}</span>
            </>
          );
          const clases = `flex w-[76px] flex-col items-center rounded-[var(--pos-r-md)] py-2.5 transition-colors ${
            activo ? "bg-[var(--pos-100)] text-[var(--pos-800)]" : "text-[var(--pos-600)]"
          }`;

          return (
            <li key={s.href} className="w-full text-center">
              {s.listo ? (
                <Link href={s.href} className={`${clases} hover:bg-[var(--pos-100)]`}>
                  {contenido}
                </Link>
              ) : (
                <span
                  className={`${clases} cursor-not-allowed opacity-40`}
                  title="Todavía no está construida"
                  aria-disabled="true"
                >
                  {contenido}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      <div className="mt-auto flex flex-col items-center gap-2">
        <span
          className="flex h-11 w-11 items-center justify-center rounded-[var(--pos-r-md)] text-[15px] font-medium"
          style={{ background: "var(--pos-100)", color: "var(--pos-800)" }}
          title={cajera}
        >
          {cajera.charAt(0).toUpperCase()}
        </span>
      </div>
    </nav>
  );
}

/* Lucide, stroke 1.5 — como pide el handoff. Inline para no sumar un paquete
   por cuatro iconos. */
const props = {
  width: 22, height: 22, viewBox: "0 0 24 24", fill: "none",
  stroke: "currentColor", strokeWidth: 1.5,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
};
function BolsaIcono() {
  return (
    <svg {...props} aria-hidden>
      <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
      <path d="M3 6h18M16 10a4 4 0 0 1-8 0" />
    </svg>
  );
}
function CajaIcono() {
  return (
    <svg {...props} aria-hidden>
      <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <path d="m3.3 7 8.7 5 8.7-5M12 22V12" />
    </svg>
  );
}
function CandadoIcono() {
  return (
    <svg {...props} aria-hidden>
      <rect width="18" height="11" x="3" y="11" rx="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}
function BarrasIcono() {
  return (
    <svg {...props} aria-hidden>
      <path d="M3 3v18h18M7 16v-5M12 16V8M17 16v-3" />
    </svg>
  );
}
