"use client";

import Link from "next/link";
import { PageShell } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Package, Boxes, Ruler, Scissors, FileText, Users, BarChart3 } from "lucide-react";

const MODULOS = [
  { href: "/produccion/ingreso",       label: "Ingreso de tela", desc: "Recepción de textilera → rollos + etiquetas", icon: Package, activo: true },
  { href: "/produccion/inventario",    label: "Inventario",      desc: "Rollos por tela · metros disponibles",         icon: Boxes,   activo: true },
  { href: "/produccion/precosteo",     label: "Precosteo",       desc: "Costeo por referencia + firma",                icon: Ruler,   activo: true },
  { href: "/produccion/corte",         label: "Orden de corte",  desc: "Trazo, curva y consumo real (pistolea rollos)",  icon: Scissors, activo: true },
  { href: "/produccion/remisiones",    label: "Remisiones",      desc: "Entregas a confeccionista",                    icon: FileText, activo: true },
  { href: "/produccion/confeccionistas", label: "Confeccionistas", desc: "Directorio de talleres",                       icon: Users,   activo: true },
  { href: "/produccion/tablero",       label: "Tablero",         desc: "Eficiencia · stock mínimo · valor",             icon: BarChart3, activo: true },
];

export default function ProduccionHome() {
  return (
    <PageShell title="Producción" subtitle="Inventario de tela · precosteo · corte · confección">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {MODULOS.map((m) => {
          const Icon = m.icon;
          const inner = (
            <CardContent className="p-5 flex items-start gap-3">
              <div className={`h-10 w-10 rounded-md grid place-items-center ${m.activo ? "bg-navy-600/10 text-navy-600" : "bg-cloud text-graphite"}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <p className={`font-display text-base font-medium ${m.activo ? "text-ink-900" : "text-graphite"}`}>
                  {m.label}
                  {!m.activo && <span className="ml-2 text-[0.6rem] uppercase tracking-widest text-graphite">Próximamente</span>}
                </p>
                <p className="text-xs text-graphite mt-0.5">{m.desc}</p>
              </div>
            </CardContent>
          );
          return m.activo ? (
            <Link key={m.href} href={m.href} className="block">
              <Card className="hover:border-navy-600/40 transition-colors">{inner}</Card>
            </Link>
          ) : (
            <Card key={m.href} className="opacity-60">{inner}</Card>
          );
        })}
      </div>
    </PageShell>
  );
}
