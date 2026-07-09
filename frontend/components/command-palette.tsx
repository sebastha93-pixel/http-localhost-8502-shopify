"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, CornerDownLeft } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { NAV_HOME, gruposVisibles, homePath } from "@/lib/nav";

/**
 * Command palette (⌘K / Ctrl+K): salto rápido a cualquier módulo que el
 * usuario tenga permitido ver. Filtro insensible a mayúsculas y tildes,
 * navegación con flechas + Enter, Esc para cerrar.
 */

interface Entrada {
  label: string;
  href: string;
  grupo: string;
  desc?: string;
}

function norm(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function CommandPalette() {
  const { user } = useAuth();
  const router = useRouter();
  const [abierto, setAbierto] = useState(false);
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const entradas = useMemo<Entrada[]>(() => {
    if (!user) return [];
    const out: Entrada[] = [
      { label: NAV_HOME.label, href: homePath(user), grupo: "Inicio" },
    ];
    for (const g of gruposVisibles(user)) {
      for (const it of g.items) {
        out.push({ label: it.label, href: it.href, grupo: g.title, desc: it.desc });
      }
    }
    return out;
  }, [user]);

  const filtradas = useMemo(() => {
    const term = norm(q.trim());
    if (!term) return entradas;
    return entradas.filter((e) =>
      norm(e.label).includes(term) || norm(e.grupo).includes(term) || (e.desc && norm(e.desc).includes(term)),
    );
  }, [entradas, q]);

  // Atajo global ⌘K / Ctrl+K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setAbierto((a) => !a);
      } else if (e.key === "Escape") {
        setAbierto(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Reset al abrir + foco
  useEffect(() => {
    if (abierto) {
      setQ("");
      setIdx(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [abierto]);

  useEffect(() => setIdx(0), [q]);

  if (!abierto || !user) return null;

  const ir = (href: string) => {
    setAbierto(false);
    router.push(href);
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-ink-900/30 px-4 pt-[12vh]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) setAbierto(false); }}
    >
      <div className="w-full max-w-lg overflow-hidden rounded-md border border-border bg-card shadow-xl">
        <div className="flex items-center gap-2 border-b border-border px-3.5 py-3">
          <Search className="h-4 w-4 shrink-0 text-graphite" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, filtradas.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
              else if (e.key === "Enter" && filtradas[idx]) { e.preventDefault(); ir(filtradas[idx].href); }
            }}
            placeholder="Ir a un módulo… (logística, fit, revenue, corte…)"
            className="w-full bg-transparent text-sm text-ink-900 outline-none placeholder:text-graphite/60"
          />
          <kbd className="shrink-0 rounded-sm border border-border bg-cloud px-1.5 py-0.5 text-[0.68rem] text-graphite">esc</kbd>
        </div>
        <div className="max-h-[50vh] overflow-y-auto py-1.5">
          {filtradas.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-graphite">Sin resultados para “{q}”.</p>
          ) : (
            filtradas.map((e, i) => (
              <button
                key={e.href + e.label}
                onClick={() => ir(e.href)}
                onMouseEnter={() => setIdx(i)}
                className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                  i === idx ? "bg-cloud" : ""
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-ink-900">{e.label}</span>
                  {e.desc && <span className="block truncate text-[0.7rem] text-graphite">{e.desc}</span>}
                </span>
                <span className="shrink-0 text-[0.68rem] uppercase tracking-[0.1em] text-graphite/70">{e.grupo}</span>
                {i === idx && <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-graphite" />}
              </button>
            ))
          )}
        </div>
        <div className="border-t border-border px-4 py-2 text-[0.68rem] text-graphite">
          ↑↓ navegar · Enter abrir · ⌘K abrir/cerrar
        </div>
      </div>
    </div>
  );
}
