import * as React from "react";
import { cn } from "@/lib/utils";
import { ArrowDown, ArrowUp } from "lucide-react";

export interface KpiCardProps {
  label: string;
  value: string | number;
  meta?: string;
  delta?: { value: string; direction: "up" | "down" };
  accent?: "steel" | "navy" | "teal" | "rust" | "crimson" | "khaki";
  danger?: boolean;
}

const accentClass: Record<NonNullable<KpiCardProps["accent"]>, string> = {
  steel:   "bg-steel",
  navy:    "bg-navy",
  teal:    "bg-teal",
  rust:    "bg-rust",
  crimson: "bg-crimson",
  khaki:   "bg-khaki",
};

export function KpiCard({ label, value, meta, delta, accent = "steel", danger }: KpiCardProps) {
  return (
    <div className="relative rounded-2xl border border-border bg-card p-5 shadow-sm transition hover:shadow-md">
      <span className={cn("absolute left-0 top-0 h-full w-[3px] rounded-l-2xl", accentClass[accent])} />
      <p className="section-label">{label}</p>
      <p
        className={cn(
          "mt-2 text-[1.7rem] font-bold leading-none tracking-tight",
          danger ? "text-crimson" : "text-ink",
        )}
      >
        {value}
      </p>
      {(meta || delta) && (
        <p className="mt-2 flex items-center gap-1 text-xs font-medium text-graphite">
          {delta && (
            <span className={cn(
              "inline-flex items-center gap-0.5 font-semibold",
              delta.direction === "up" ? "text-teal" : "text-crimson",
            )}>
              {delta.direction === "up" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
              {delta.value}
            </span>
          )}
          {meta && <span>{meta}</span>}
        </p>
      )}
    </div>
  );
}
