"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Scissors, X } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Buscar y elegir al cortador responsable de una orden de corte.
 *
 * POR QUÉ EXISTE (2026-08-06): "Cortador responsable" era un campo de texto
 * libre, justo al lado del campo de correos. Alguien escribió el correo donde va
 * el nombre y la orden 2608-0001 quedó INVISIBLE para su cortador: el permiso
 * compara ese texto contra el nombre del usuario, y 'johnj2397@hotmail.com' no
 * se parece a 'JHON JAIRO BARRETO'. Hubo que borrar la orden y volverla a crear.
 *
 * Las otras 15 órdenes funcionaban por casualidad: escribían 'BARRETO', que sí
 * es un pedazo del nombre completo. Con un cortador la coincidencia por texto
 * parece funcionar; con dos empieza a fallar callada.
 *
 * La lista sale de los PERMISOS del portal, no de nada escrito a mano: cuando
 * entre un cortador nuevo, se le da acceso a la plataforma y aparece aquí solo.
 *
 * Al elegir se devuelve el CORREO además del nombre, y quien llama lo usa para
 * llenar los destinatarios. Un dato que el sistema ya conoce no se vuelve a
 * teclear.
 */

export interface Cortador {
  nombre: string;
  email: string;
  /** true = cortador puro (solo ve sus órdenes). false = también diseño/admin. */
  solo_corte: boolean;
}

interface Props {
  /** Correo del cortador elegido ("" si no hay). Es la identidad. */
  email: string;
  /** Nombre mostrado; sirve para las órdenes viejas que solo tienen texto. */
  nombre: string;
  onSelect: (c: Cortador | null) => void;
  label?: string;
  disabled?: boolean;
}

export function SelectorCortador({
  email, nombre, onSelect, label = "Cortador responsable", disabled = false,
}: Props) {
  const [abierto, setAbierto] = useState(false);
  const [busqueda, setBusqueda] = useState("");
  const cajaRef = useRef<HTMLDivElement>(null);

  const q = useQuery<{ cortadores: Cortador[] }>({
    queryKey: ["produccion", "cortadores"],
    queryFn: () => api.get("/api/produccion/cortadores"),
    staleTime: 5 * 60_000,
  });

  const cortadores = q.data?.cortadores ?? [];
  const filtrados = useMemo(() => {
    const t = busqueda.trim().toLowerCase();
    if (!t) return cortadores;
    return cortadores.filter(
      (c) => c.nombre.toLowerCase().includes(t) || c.email.toLowerCase().includes(t));
  }, [cortadores, busqueda]);

  const elegido = cortadores.find(
    (c) => c.email.toLowerCase() === email.trim().toLowerCase());

  // Qué se ve en el botón. Si la orden es vieja y solo trae un nombre escrito a
  // mano, se muestra ese nombre — pero marcado, porque no es una identidad.
  const textoBoton = elegido?.nombre || nombre || "Elegir cortador…";

  function elegir(c: Cortador) {
    onSelect(c);
    setAbierto(false);
    setBusqueda("");
  }

  return (
    <div ref={cajaRef} className="relative">
      <label className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
        {label}
      </label>

      <button
        type="button"
        disabled={disabled}
        onClick={() => setAbierto((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-sm border border-border bg-card px-3 py-2 text-left text-sm disabled:opacity-50"
      >
        <span className={`flex min-w-0 items-center gap-2 ${elegido || nombre ? "" : "text-graphite"}`}>
          <Scissors className="h-3.5 w-3.5 shrink-0 text-graphite" aria-hidden />
          <span className="truncate">{textoBoton}</span>
          {!elegido && nombre && (
            <span
              className="shrink-0 rounded-sm bg-amber-500/15 px-1.5 py-0.5 text-[0.6rem] font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-400"
              title="Este nombre está escrito a mano, no está ligado a un usuario del portal. Elige el cortador de la lista para ligarlo."
            >
              sin ligar
            </span>
          )}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-graphite" aria-hidden />
      </button>

      {elegido && (
        <p className="mt-1 flex items-center gap-1.5 text-[0.68rem] text-graphite">
          <span className="truncate">{elegido.email}</span>
          {!elegido.solo_corte && (
            <span className="shrink-0 text-[0.62rem] uppercase tracking-wider">
              · también diseño
            </span>
          )}
          {!disabled && (
            <button
              type="button"
              onClick={() => onSelect(null)}
              className="ml-auto inline-flex items-center gap-0.5 text-graphite hover:text-terracotta"
              title="Quitar el cortador"
            >
              <X className="h-3 w-3" /> quitar
            </button>
          )}
        </p>
      )}

      {abierto && !disabled && (
        <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-sm border border-border bg-card shadow-lg">
          <input
            autoFocus
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar por nombre o correo…"
            className="w-full border-b border-border bg-transparent px-3 py-2 text-sm outline-none"
          />
          <ul className="max-h-56 overflow-y-auto">
            {q.isLoading && (
              <li className="px-3 py-2 text-xs text-graphite">Cargando cortadores…</li>
            )}
            {q.isError && (
              <li className="px-3 py-2 text-xs text-terracotta">
                No se pudo cargar la lista de cortadores.
              </li>
            )}
            {!q.isLoading && !q.isError && cortadores.length === 0 && (
              <li className="px-3 py-2 text-xs text-graphite">
                Ningún usuario tiene acceso de cortador. Dáselo en Usuarios y
                aparecerá aquí.
              </li>
            )}
            {!q.isLoading && cortadores.length > 0 && filtrados.length === 0 && (
              <li className="px-3 py-2 text-xs text-graphite">Nadie coincide con «{busqueda}».</li>
            )}
            {filtrados.map((c) => {
              const activo = c.email.toLowerCase() === email.trim().toLowerCase();
              return (
                <li key={c.email}>
                  <button
                    type="button"
                    onClick={() => elegir(c)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-cloud dark:hover:bg-ink-800"
                  >
                    <Check
                      className={`h-3.5 w-3.5 shrink-0 ${activo ? "text-navy-600" : "opacity-0"}`}
                      aria-hidden
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-ink-900 dark:text-foreground">
                        {c.nombre}
                        {!c.solo_corte && (
                          <span className="ml-1.5 text-[0.62rem] uppercase tracking-wider text-graphite">
                            · también diseño
                          </span>
                        )}
                      </span>
                      <span className="block truncate text-[0.68rem] text-graphite">{c.email}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
