import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-[0.6rem] font-bold uppercase tracking-[0.12em] transition-colors",
  {
    variants: {
      tone: {
        critico:   "bg-crimson/10 text-crimson border border-crimson/20",
        riesgo:    "bg-rust/10 text-rust border border-rust/20",
        normal:    "bg-teal/10 text-teal border border-teal/20",
        pendiente: "bg-khaki/10 text-khaki border border-khaki/20",
        info:      "bg-navy/10 text-navy border border-navy/20",
        neutral:   "bg-concrete/40 text-graphite border border-concrete",
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
