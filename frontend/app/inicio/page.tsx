"use client";

/**
 * Inicio — launcher de módulos según permisos.
 * Página de entrada para usuarios sin acceso al Centro de Control
 * (ej. el cortador): tarjetas grandes navegables por módulo, agrupadas
 * por área, en vez de caer directo a una sola lista.
 */
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { gruposVisibles } from "@/lib/nav";
import { PageShell } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import {
  ArrowRight, Banknote, Boxes, ClipboardList, FileBarChart2, Home,
  Layers, Package, Scissors, Settings, ShoppingBag, Sparkles, Truck,
} from "lucide-react";

// Icono por ruta (fallback por grupo)
const ICONO_RUTA: Record<string, React.ComponentType<{ className?: string }>> = {
  "/produccion/corte":           Scissors,
  "/produccion/lotes":           Layers,
  "/produccion/remisiones":      ClipboardList,
  "/produccion/inventario":      Boxes,
  "/produccion/ingreso":         Package,
  "/produccion/insumos":         Package,
  "/produccion":                 Home,
  "/produccion/tablero":         FileBarChart2,
  "/logistica":                  Truck,
  "/contraentrega":              Truck,
  "/envios":                     Truck,
  "/comercial":                  ShoppingBag,
  "/inventario":                 Boxes,
  "/revenue":                    Sparkles,
  "/inteligencia":               Sparkles,
  "/finanzas":                   Banknote,
  "/usuarios":                   Settings,
};

const ICONO_GRUPO: Record<string, React.ComponentType<{ className?: string }>> = {
  Operaciones:   Truck,
  Finanzas:      Banknote,
  Comercial:     ShoppingBag,
  Inteligencia:  Sparkles,
  Producción:    Scissors,
  Configuración: Settings,
};

export default function InicioPage() {
  const { user } = useAuth();
  const grupos = gruposVisibles(user);

  return (
    <PageShell
      title={`Hola, ${user?.nombre?.split(" ")[0] || ""}`}
      subtitle="Tus módulos — entra al que necesites"
    >
      {grupos.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-graphite">
            Tu usuario no tiene módulos asignados todavía. Pídele acceso al administrador.
          </CardContent>
        </Card>
      ) : (
        grupos.map((g) => (
          <div key={g.title}>
            <p className="section-label mb-2">{g.title}</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-5">
              {g.items.map((it) => {
                const Icono = ICONO_RUTA[it.href] || ICONO_GRUPO[g.title] || Home;
                return (
                  <Link key={it.href} href={it.href}
                    className="group rounded-sm border border-border bg-card p-4 hover:border-navy-600/50 hover:bg-navy-600/[0.03] transition-colors">
                    <div className="flex items-start justify-between gap-2">
                      <div className="rounded-sm bg-navy-600/[0.08] p-2">
                        <Icono className="h-5 w-5 text-navy-600" />
                      </div>
                      <ArrowRight className="h-4 w-4 text-graphite/40 group-hover:text-navy-600 group-hover:translate-x-0.5 transition-all" />
                    </div>
                    <p className="mt-3 text-sm font-semibold text-ink-900 uppercase tracking-wider">
                      {it.label}
                    </p>
                    {it.desc && (
                      <p className="mt-0.5 text-[0.7rem] text-graphite leading-snug">{it.desc}</p>
                    )}
                  </Link>
                );
              })}
            </div>
          </div>
        ))
      )}
    </PageShell>
  );
}
