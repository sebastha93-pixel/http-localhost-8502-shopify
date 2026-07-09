import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-sm px-2 py-0.5 text-[0.7rem] font-semibold uppercase tracking-[0.12em] transition-colors",
  {
    variants: {
      tone: {
        critico:   "bg-terracotta/10 text-terracotta border border-terracotta/25",
        riesgo:    "bg-ochre/10    text-ochre      border border-ochre/25",
        normal:    "bg-sage/10     text-sage       border border-sage/25",
        pendiente: "bg-ochre/10    text-ochre      border border-ochre/25",
        info:      "bg-navy-600/10 text-navy-600   border border-navy-600/25",
        neutral:   "bg-concrete/50 text-graphite   border border-concrete",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ tone }), className)} {...props} />;
}
