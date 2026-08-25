"use client";

import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";

/**
 * Buscador de listas, uno para todo el módulo de producción.
 *
 * POR QUÉ EXISTE (2026-08-12, pedido de Sebastián: "ese mismo filtro ponlo en
 * cada submódulo de producción"). Se escribió primero suelto en la lista de
 * precosteo; copiarlo a diez pantallas habría garantizado que con el tiempo
 * cada una filtre distinto —una con acentos, otra sin, una con AND, otra con
 * OR—. Acá vive una sola vez y todas se comportan igual.
 *
 * TRES DECISIONES QUE CAMBIAN EL USO REAL:
 *
 * 1. Filtra en el NAVEGADOR sobre la lista ya cargada. Buscar contra el backend
 *    sería una llamada por tecla para filtrar algo que ya está en memoria.
 * 2. Sin acentos ni mayúsculas: "boxer" encuentra "BÓXER". Nadie pone la tilde
 *    cuando busca.
 * 3. Varias palabras se ACUMULAN: "flare verbena" no trae los flare de otra
 *    tela. Escribir más tiene que reducir, no ensanchar.
 */

/** Sin acentos y en minúsculas. */
export function normalizar(s: unknown): string {
  return String(s ?? "")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().trim();
}

/**
 * Filtra `items` con el texto `q`, mirando los campos que devuelva `campos`.
 *
 * `campos` recibe el item y devuelve lo buscable. Se pasa como función y no
 * como lista de llaves para que cada pantalla pueda incluir datos anidados
 * (`r.referencia?.nombre`) o compuestos sin pelear con los tipos.
 */
export function filtrar<T>(items: T[], q: string, campos: (x: T) => unknown[]): T[] {
  const t = normalizar(q);
  if (!t) return items;
  const palabras = t.split(/\s+/).filter(Boolean);
  return items.filter((x) => {
    const heno = normalizar(campos(x).filter((v) => v != null && v !== "").join(" "));
    return palabras.every((w) => heno.includes(w));
  });
}

/** Estado + lista filtrada, listo para usar en una pantalla. */
export function useBusqueda<T>(items: T[], campos: (x: T) => unknown[]) {
  const [q, setQ] = useState("");
  const filtrados = useMemo(() => filtrar(items, q, campos),
    // `campos` se redefine en cada render (es una lambda), así que NO va en las
    // dependencias: metería un recálculo por render. Los datos y el texto son
    // lo que de verdad cambia el resultado.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items, q]);
  return { q, setQ, filtrados, buscando: q.trim().length > 0 };
}

interface Props {
  valor: string;
  onChange: (v: string) => void;
  placeholder?: string;
  /** Cuántos se ven / cuántos hay. Se muestra solo mientras hay búsqueda. */
  visibles?: number;
  total?: number;
}

export function CasillaBusqueda({
  valor, onChange, placeholder = "Buscar…", visibles, total,
}: Props) {
  return (
    <div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-graphite" aria-hidden />
        <input
          value={valor}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          className="w-full rounded-sm border border-border bg-card py-2.5 pl-10 pr-10 text-sm outline-none focus:border-navy-600"
        />
        {valor && (
          <button
            type="button"
            onClick={() => onChange("")}
            title="Limpiar"
            aria-label="Limpiar búsqueda"
            className="absolute right-3 top-1/2 -translate-y-1/2 text-graphite hover:text-ink-900"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      {/* Decir "N de M" evita el susto de creer que se perdieron registros. */}
      {valor && visibles != null && total != null && (
        <p className="mt-1 text-[0.68rem] text-graphite">
          {visibles} de {total} · «{valor}»
        </p>
      )}
    </div>
  );
}

interface VacioProps {
  buscando: boolean;
  onLimpiar: () => void;
  total?: number;
  /** Qué decir cuando la lista está vacía de verdad, no por la búsqueda. */
  mensajeVacio: string;
}

/**
 * Los dos vacíos, que NO son el mismo.
 *
 * "No hay nada registrado" y "tu búsqueda no encontró nada" se resuelven al
 * contrario: uno creando un registro, el otro borrando lo que escribiste. Un
 * solo mensaje para ambos manda a la persona al lado equivocado.
 */
export function ListaVacia({ buscando, onLimpiar, total, mensajeVacio }: VacioProps) {
  if (!buscando) {
    return <p className="p-8 text-center text-sm text-graphite">{mensajeVacio}</p>;
  }
  return (
    <div className="p-8 text-center">
      <p className="text-sm text-graphite">Nada coincide con lo que buscaste.</p>
      <button
        type="button"
        onClick={onLimpiar}
        className="mt-2 text-xs font-semibold uppercase tracking-wider text-navy-600 hover:underline"
      >
        {total != null ? `Ver los ${total}` : "Limpiar búsqueda"}
      </button>
    </div>
  );
}
