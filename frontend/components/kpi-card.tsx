import * as React from "react";
import { cn } from "@/lib/utils";
import { ArrowDown, ArrowUp } from "lucide-react";

export interface KpiCardProps {
  label: string;
  value: string | number;
  meta?: string;
  delta?: { value: string; direction: "up" | "down" };
  /** Selvedge variants — `highlight` and `danger` carry the stitch rail. */
  variant?: "default" | "highlight" | "danger" | "success";
  /** @deprecated kept for non-Revenue pages */
  accent?: "steel" | "navy" | "teal" | "rust" | "crimson" | "khaki";
  /** @deprecated use `variant="danger"` */
  danger?: boolean;
}

const legacyAccent: Record<NonNullable<KpiCardProps["accent"]>, string> = {
  steel:   "bg-steel-400",
  navy:    "bg-navy-600",
  teal:    "bg-teal",
  rust:    "bg-terracotta",
  crimson: "bg-terracotta",
  khaki:   "bg-ochre",
};

export function KpiCard({
  label, value, meta, delta, variant, accent = "steel", danger,
}: KpiCardProps) {
  const v: NonNullable<KpiCardProps["variant"]> = variant ?? (danger ? "danger" : "default");
  const stitched = v === "highlight" || v === "danger";

  return (
    <div
      className={cn(
        "relative border bg-card p-5 transition-shadow duration-200",
        "rounded-md hover:shadow-sm",
        v === "danger"    && "border-terracotta/30 bg-terracotta/[0.03]",
        v === "highlight" && "border-navy-600/30 bg-navy-600/[0.03]",
        v === "success"   && "border-sage/30 bg-sage/[0.03]",
        v === "default"   && "border-border",
        stitched && "stitch-rail pl-6",
      )}
    >
      {!stitched && (
        <span className={cn("absolute left-0 top-0 h-full w-[2px] rounded-l-md", legacyAccent[accent])} />
      )}
      <p className="section-label">{label}</p>
      <p
        className={cn(
          "mt-2 font-display tabular text-[1.65rem] font-medium leading-none tracking-tight",
          v === "danger"  ? "text-terracotta" :
          v === "success" ? "text-sage"       :
                            "text-ink-900 dark:text-foreground",
        )}
      >
        {value}
      </p>
      {(meta || delta) && (
        <p className="mt-2 flex items-center gap-1 text-xs font-medium text-graphite">
          {delta && (
            <span className={cn(
              "inline-flex items-center gap-0.5 font-semibold",
              delta.direction === "up" ? "text-sage" : "text-terracotta",
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

/**
 * Slim horizontal KPI strip — for /revenue. Renders a row of label/value pairs
 * with hairline dividers. Designed to be dense and quiet, not loud cards.
 */
export interface KpiStripItem {
  label: string;
  value: string | number;
  tone?: "default" | "danger" | "success";
}

export function KpiStrip({ items }: { items: KpiStripItem[] }) {
  return (
    <div className="grid grid-cols-2 divide-x divide-border rounded-md border border-border bg-card md:grid-cols-3 lg:grid-cols-6">
      {items.map((it, i) => (
        <div key={i} className="px-5 py-4">
          <p className="text-[0.65rem] font-semibold uppercase tracking-[0.14em] text-graphite">
            {it.label}
          </p>
          <p
            className={cn(
              "mt-1.5 font-display tabular text-lg font-medium leading-none tracking-tight",
              it.tone === "danger"  ? "text-terracotta" :
              it.tone === "success" ? "text-sage"       :
                                      "text-ink-900 dark:text-foreground",
            )}
          >
            {it.value}
          </p>
        </div>
      ))}
    </div>
  );
}
