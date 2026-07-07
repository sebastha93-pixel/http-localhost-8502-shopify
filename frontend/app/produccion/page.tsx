"use client";

/**
 * Home de Producción — guía visual del FLUJO del proceso.
 * En vez de una rejilla plana, muestra el proceso en fases numeradas (1→8)
 * en el orden real de trabajo, con conteos en vivo y "qué sigue".
 * Cada paso se muestra solo si el usuario tiene permiso de verlo.
 */
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { esAdmin, puedeVerModulo } from "@/lib/auth";
import { itemVisible, type NavItem } from "@/lib/nav";
import { PageShell } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import {
  Package, Boxes, Ruler, Scissors, FileText, Users, BarChart3, Layers,
  Truck, PackageSearch, Coins, Trash2, Loader2, ArrowRight, AlertTriangle,
} from "lucide-react";

type IconType = React.ComponentType<{ className?: string }>;

interface Paso extends NavItem {
  n?: number;            // número de paso en el flujo (los de apoyo no llevan)
  icon: IconType;
  contador?: "en_proceso" | "estancados" | "telas_bajas"; // KPI en vivo del tablero
}

interface Fase {
  titulo: string;
  nota: string;
  pasos: Paso[];
}

// Flujo real del proceso, agrupado por fase.
const FLUJO: Fase[] = [
  {
    titulo: "1 · Preparación",
    nota: "Antes de cortar: costea, recibe tela e insumos.",
    pasos: [
      { n: 1, label: "Precosteo",  href: "/produccion/precosteo",  icon: Ruler,        desc: "Costea la referencia y fírmala" },
      { n: 2, label: "Ingreso de tela", href: "/produccion/ingreso", icon: Package,     desc: "Recibe rollos de la textilera", permiso: "produccion_ingreso" },
      { n: 3, label: "Inventario", href: "/produccion/inventario", icon: Boxes,         desc: "Telas y metros disponibles", permiso: "produccion_ingreso|produccion_cortador", contador: "telas_bajas" },
      { n: 4, label: "Insumos",    href: "/produccion/insumos",    icon: PackageSearch, desc: "Stock de botones, cierres, marquillas", permiso: "produccion_ingreso" },
    ],
  },
  {
    titulo: "2 · Corte",
    nota: "El cortador pistolea rollos y sube el informe.",
    pasos: [
      { n: 5, label: "Orden de corte", href: "/produccion/corte", icon: Scissors, desc: "Trazo, curva y consumo real", permiso: "produccion_corte|produccion_cortador" },
      { label: "Mis despachos", href: "/produccion/mis-despachos", icon: Truck, desc: "Unidades despachadas por corte", permiso: "produccion_cortador" },
    ],
  },
  {
    titulo: "3 · Entrega y confección",
    nota: "Separa insumos, entrega al taller y sigue el lote.",
    pasos: [
      { n: 6, label: "Remisiones", href: "/produccion/remisiones", icon: FileText, desc: "Entrega insumos al confeccionista", permiso: "produccion_remisiones" },
      { n: 7, label: "Lotes",      href: "/produccion/lotes",      icon: Layers,   desc: "Seguimiento confección → bodega", permiso: "produccion_corte|produccion_cortador", contador: "en_proceso" },
    ],
  },
  {
    titulo: "4 · Cierre y control",
    nota: "Cruza costos con Siigo y revisa el tablero.",
    pasos: [
      { n: 8, label: "Costeo real", href: "/produccion/costeo",  icon: Coins,     desc: "Cruce con facturas de Siigo" },
      { label: "Tablero",          href: "/produccion/tablero",  icon: BarChart3, desc: "Alertas, stock y eficiencia", permiso: "produccion" },
    ],
  },
];

// Directorio de apoyo — no es un paso del flujo.
const APOYO: Paso = {
  label: "Proveedores", href: "/produccion/confeccionistas", icon: Users,
  desc: "Confección · terminación · lavandería · otros", permiso: "produccion_proveedores",
};

interface Tablero {
  ruta?: { en_proceso?: number; estancados?: { consecutivo: string }[] };
  inventario?: { telas_bajas?: unknown[] };
}

export default function ProduccionHome() {
  const { user } = useAuth();
  const puedeTablero = puedeVerModulo(user, "produccion");

  const tabQ = useQuery<Tablero>({
    queryKey: ["produccion", "tablero", "home"],
    queryFn: () => api.get("/api/produccion/tablero"),
    enabled: puedeTablero,
    staleTime: 60_000,
  });

  const enProceso = tabQ.data?.ruta?.en_proceso ?? 0;
  const estancados = tabQ.data?.ruta?.estancados?.length ?? 0;
  const telasBajas = tabQ.data?.inventario?.telas_bajas?.length ?? 0;
  const contadores = { en_proceso: enProceso, estancados, telas_bajas: telasBajas };

  const fasesVisibles = FLUJO
    .map((f) => ({ ...f, pasos: f.pasos.filter((p) => itemVisible(user, p)) }))
    .filter((f) => f.pasos.length > 0);
  const verApoyo = itemVisible(user, APOYO);

  return (
    <PageShell title="Producción" subtitle="El proceso paso a paso — de la tela a bodega">
      {/* Franja de atención: solo lo que requiere acción hoy */}
      {puedeTablero && (estancados > 0 || telasBajas > 0 || enProceso > 0) && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <AlertaTile
            label="Lotes en proceso" valor={enProceso} href="/produccion/lotes"
            tono="info" icon={Layers} sub="En confección o terminación" />
          <AlertaTile
            label="Lotes estancados" valor={estancados} href="/produccion/tablero"
            tono={estancados > 0 ? "alerta" : "ok"} icon={AlertTriangle} sub="Más de 7 días sin bodega" />
          <AlertaTile
            label="Telas bajo mínimo" valor={telasBajas} href="/produccion/inventario"
            tono={telasBajas > 0 ? "alerta" : "ok"} icon={Boxes} sub="Reponer pronto" />
        </div>
      )}

      {/* Flujo por fases */}
      {fasesVisibles.map((fase) => (
        <section key={fase.titulo} className="space-y-2">
          <div className="flex items-baseline gap-3">
            <h2 className="section-label">{fase.titulo}</h2>
            <p className="text-[0.7rem] text-graphite">{fase.nota}</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {fase.pasos.map((p) => (
              <PasoCard key={p.href} paso={p}
                contador={p.contador ? contadores[p.contador] : undefined} />
            ))}
          </div>
        </section>
      ))}

      {/* Apoyo */}
      {verApoyo && (
        <section className="space-y-2">
          <h2 className="section-label">Apoyo</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <PasoCard paso={APOYO} />
          </div>
        </section>
      )}

      {esAdmin(user) && <ResetProduccionCard />}
    </PageShell>
  );
}

function PasoCard({ paso, contador }: { paso: Paso; contador?: number }) {
  const Icon = paso.icon;
  const mostrarBadge = typeof contador === "number" && contador > 0;
  return (
    <Link href={paso.href} className="group block">
      <Card className="h-full transition-colors hover:border-navy-600/50 hover:bg-navy-600/[0.02]">
        <CardContent className="p-4 flex items-start gap-3">
          <div className="relative flex-none">
            <div className="h-10 w-10 rounded-md grid place-items-center bg-navy-600/10 text-navy-600">
              <Icon className="h-5 w-5" />
            </div>
            {paso.n != null && (
              <span className="absolute -top-1.5 -left-1.5 h-5 w-5 grid place-items-center rounded-full bg-navy-600 text-[0.6rem] font-bold text-white tabular">
                {paso.n}
              </span>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="font-display text-base font-medium text-ink-900">{paso.label}</p>
              {mostrarBadge && (
                <span className="rounded-full bg-navy-600/10 px-2 py-0.5 text-[0.6rem] font-bold tabular text-navy-600">
                  {contador}
                </span>
              )}
            </div>
            <p className="text-xs text-graphite mt-0.5">{paso.desc}</p>
          </div>
          <ArrowRight className="h-4 w-4 flex-none text-graphite/30 group-hover:text-navy-600 group-hover:translate-x-0.5 transition-all" />
        </CardContent>
      </Card>
    </Link>
  );
}

function AlertaTile({ label, valor, sub, href, tono, icon: Icon }: {
  label: string; valor: number; sub: string; href: string;
  tono: "info" | "alerta" | "ok"; icon: IconType;
}) {
  const estilos = {
    info:   "border-navy-600/30 bg-navy-600/[0.04] text-navy-600",
    alerta: "border-terracotta/40 bg-terracotta/[0.06] text-terracotta",
    ok:     "border-teal/30 bg-teal/[0.05] text-teal",
  }[tono];
  return (
    <Link href={href} className={`group rounded-sm border ${estilos} px-4 py-3 flex items-center gap-3 transition-colors hover:brightness-95`}>
      <Icon className="h-5 w-5 flex-none" />
      <div className="flex-1 min-w-0">
        <p className="text-[0.6rem] uppercase tracking-widest opacity-80">{label}</p>
        <p className="font-display text-2xl leading-none tabular mt-0.5">{valor}</p>
        <p className="text-[0.62rem] opacity-70 mt-0.5">{sub}</p>
      </div>
      <ArrowRight className="h-4 w-4 flex-none opacity-40 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
    </Link>
  );
}

/** Zona de peligro (solo admin): borra TODOS los datos del módulo para
 * arrancar de cero. Corre en el backend con la service key — no depende
 * del SQL Editor de Supabase. */
function ResetProduccionCard() {
  const qc = useQueryClient();
  const [confirmando, setConfirmando] = useState(false);
  const [texto, setTexto] = useState("");
  const [resultado, setResultado] = useState("");
  const [err, setErr] = useState("");

  const reset = useMutation({
    mutationFn: () => api.post<{ ok: boolean; borradas: Record<string, number>; errores: Record<string, string> }>(
      "/api/produccion/admin/reset-datos", { confirmacion: "RESET" }),
    onSuccess: (d) => {
      setErr("");
      setConfirmando(false);
      setTexto("");
      const total = Object.values(d.borradas || {}).reduce((s, n) => s + n, 0);
      const errores = Object.keys(d.errores || {});
      setResultado(errores.length
        ? `Se borraron ${total} registros, pero fallaron: ${errores.join(", ")}`
        : `Módulo en cero: ${total} registros borrados. Consecutivos reiniciados.`);
      qc.clear();
    },
    onError: (e: Error) => setErr(`No se pudo resetear: ${e.message}`),
  });

  return (
    <Card className="border-terracotta/40 mt-4">
      <CardContent className="p-5 space-y-3">
        <p className="text-[0.6rem] uppercase tracking-widest text-terracotta font-bold">Zona de peligro (solo admin)</p>
        <p className="text-xs text-graphite">
          Borra <strong>todos</strong> los datos del módulo: telas, cortes, remisiones, precosteos,
          insumos, proveedores y consecutivos. Conserva usuarios y permisos. <strong>Irreversible.</strong>
        </p>
        {resultado && (
          <div className="rounded-sm border border-teal/40 bg-teal/[0.06] px-3 py-2 text-xs text-teal">✓ {resultado}</div>
        )}
        {err && (
          <div role="alert" className="rounded-sm border border-terracotta/40 bg-terracotta/[0.06] px-3 py-2 text-xs text-terracotta">{err}</div>
        )}
        {!confirmando ? (
          <button onClick={() => { setConfirmando(true); setResultado(""); }}
            className="inline-flex items-center gap-1.5 rounded-sm border border-terracotta/50 bg-white px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-terracotta hover:bg-terracotta/10">
            <Trash2 className="h-3.5 w-3.5" /> Resetear módulo producción
          </button>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <input value={texto} onChange={(e) => setTexto(e.target.value)}
              placeholder={'Escribe RESET para confirmar'}
              className="rounded-sm border border-terracotta/50 bg-white px-2 py-1.5 text-xs w-[220px]" />
            <button onClick={() => reset.mutate()}
              disabled={texto !== "RESET" || reset.isPending}
              className="inline-flex items-center gap-1.5 rounded-sm bg-terracotta px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-widest text-white hover:bg-ink-900 disabled:opacity-40">
              {reset.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              Borrar todo
            </button>
            <button onClick={() => { setConfirmando(false); setTexto(""); }}
              className="text-[0.65rem] uppercase tracking-widest text-graphite hover:text-ink-900">
              Cancelar
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
