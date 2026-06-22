import * as React from "react";
import { cn } from "@/lib/utils";

export type StatusKind = "wait" | "done" | "risk" | "unassigned";

const map: Record<StatusKind, { label: string; dot: string; text: string; bg: string }> = {
  wait:       { label: "Esperando",   dot: "bg-terracotta", text: "text-terracotta",  bg: "bg-terracotta/10 border-terracotta/25" },
  done:       { label: "Atendida",    dot: "bg-sage",       text: "text-sage",        bg: "bg-sage/10       border-sage/25" },
  risk:       { label: "En riesgo",   dot: "bg-ochre",      text: "text-ochre",       bg: "bg-ochre/10      border-ochre/25" },
  unassigned: { label: "Sin asignar", dot: "bg-graphite",   text: "text-graphite",    bg: "bg-concrete/60   border-concrete" },
};

export interface StatusBadgeProps {
  status: StatusKind;
  className?: string;
  /** Override default label (defaults to Spanish copy from the map). */
  label?: string;
}

export function StatusBadge({ status, className, label }: StatusBadgeProps) {
  const s = map[status];
  return (
    <span
      role="status"
      aria-label={`Estado: ${label ?? s.label}`}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-[0.65rem] font-semibold tracking-[0.06em]",
        s.bg, s.text, className,
      )}
    >
      <span aria-hidden className={cn("inline-block h-1.5 w-1.5 rounded-full", s.dot)} />
      {label ?? s.label}
    </span>
  );
}
