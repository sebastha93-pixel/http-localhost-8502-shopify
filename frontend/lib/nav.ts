"use client";

/**
 * Navegación central de la app — una sola fuente para el sidebar y la
 * pantalla de Inicio (launcher de módulos).
 *
 * Reglas de visibilidad:
 *  - `permiso`: módulo(s) requeridos para VER el link. Varios separados
 *    por "|" — con cualquiera se muestra (ej. corte para el cortador).
 *  - ADMIN_ONLY / COSTOS_ONLY: reglas especiales por ruta.
 */
import { esAdmin, puedeVerCostosProduccion, puedeVerModulo, type User } from "@/lib/auth";

export interface NavItem {
  label: string;
  href: string;
  permiso?: string;
  desc?: string;   // descripción corta para la tarjeta de Inicio
}

export interface NavGroup {
  title: string;
  items: NavItem[];
  defaultOpen?: boolean;
}

export const ADMIN_ONLY = ["/usuarios", "/auditoria", "/diagnostico-revenue"];
export const COSTOS_ONLY = ["/produccion/precosteo", "/produccion/costeo"];

export const NAV_HOME: NavItem = { label: "Centro de Control", href: "/centro-control" };

export const NAV_GROUPS: NavGroup[] = [
  {
    title: "Operaciones",
    defaultOpen: true,
    items: [
      { label: "Logística",     href: "/logistica",     permiso: "logistica",     desc: "Pedidos y despachos del día" },
      { label: "Contraentrega", href: "/contraentrega", permiso: "contraentrega", desc: "Pedidos COD y novedades" },
      { label: "Envíos",        href: "/envios",        permiso: "envios",        desc: "Guías y transportadoras" },
      { label: "B2B",           href: "/b2b",           permiso: "b2b",           desc: "Pedidos mayoristas" },
      { label: "Devoluciones",  href: "/devoluciones",  permiso: "devoluciones",  desc: "Retornos y cambios" },
      { label: "Incidencias",   href: "/incidencias",   permiso: "incidencias",   desc: "Casos abiertos" },
      { label: "Histórico",     href: "/historico",     permiso: "historico",     desc: "Movimientos pasados" },
    ],
  },
  {
    title: "Finanzas",
    items: [
      { label: "Finanzas",     href: "/finanzas",     permiso: "finanzas", desc: "Panorama financiero" },
      { label: "Conciliación", href: "/conciliacion", permiso: "finanzas", desc: "Cruce de pagos" },
      { label: "Facturación",  href: "/facturacion",  permiso: "finanzas", desc: "Facturas emitidas" },
      { label: "MercadoPago",  href: "/mercadopago",  permiso: "finanzas", desc: "Pagos MercadoPago" },
      { label: "Addi",         href: "/addi",         permiso: "finanzas", desc: "Pagos Addi" },
    ],
  },
  {
    title: "Comercial",
    items: [
      { label: "Comercial",  href: "/comercial",  permiso: "comercial",  desc: "Ventas y asesoras" },
      { label: "Inventario", href: "/inventario", permiso: "inventario", desc: "Stock de producto" },
      { label: "Revenue IA", href: "/revenue",    permiso: "revenue",    desc: "Conversaciones y fugas" },
    ],
  },
  {
    title: "Inteligencia",
    items: [
      { label: "Inteligencia", href: "/inteligencia", permiso: "inteligencia", desc: "Análisis con IA" },
      { label: "Reportes",     href: "/reportes",     permiso: "inteligencia", desc: "Informes ejecutivos" },
    ],
  },
  {
    title: "Producción",
    items: [
      { label: "Producción",  href: "/produccion",                 permiso: "produccion",         desc: "Vista general del módulo" },
      { label: "Tablero",     href: "/produccion/tablero",         permiso: "produccion",         desc: "Alertas y estado global" },
      { label: "Costeo real", href: "/produccion/costeo",                                         desc: "Cruce con Siigo" },
      { label: "Ingreso",     href: "/produccion/ingreso",         permiso: "produccion_ingreso", desc: "Entradas de tela" },
      { label: "Inventario",  href: "/produccion/inventario",      permiso: "produccion_ingreso|produccion_cortador", desc: "Telas y rollos disponibles" },
      { label: "Insumos",     href: "/produccion/insumos",         permiso: "produccion_ingreso", desc: "Stock de insumos" },
      { label: "Precosteo",   href: "/produccion/precosteo",                                      desc: "Costeo por referencia" },
      { label: "Lotes",       href: "/produccion/lotes",           permiso: "produccion_corte|produccion_cortador", desc: "Lotes en proceso" },
      { label: "Orden corte", href: "/produccion/corte",           permiso: "produccion_corte|produccion_cortador", desc: "Cortes asignados e informe" },
      { label: "Remisiones",  href: "/produccion/remisiones",      permiso: "produccion_remisiones", desc: "Entregas e insumos por lote" },
      { label: "Mis despachos", href: "/produccion/mis-despachos",   permiso: "produccion_cortador",   desc: "Unidades despachadas por corte" },
      { label: "Proveedores", href: "/produccion/confeccionistas", permiso: "produccion_proveedores", desc: "Confección, lavandería, terminación" },
    ],
  },
  {
    title: "Configuración",
    items: [
      { label: "Usuarios",            href: "/usuarios",            desc: "Cuentas y permisos" },
      { label: "Auditoría",           href: "/auditoria",           desc: "Registro de acciones" },
      { label: "Diagnóstico Revenue", href: "/diagnostico-revenue", desc: "Calidad de datos" },
    ],
  },
];

type UserLike = Pick<User, "rol" | "permisos"> | null | undefined;

export function itemVisible(user: UserLike, it: NavItem): boolean {
  if (ADMIN_ONLY.includes(it.href)) return esAdmin(user as User);
  if (COSTOS_ONLY.includes(it.href)) return puedeVerCostosProduccion(user);
  if (it.permiso) return it.permiso.split("|").some((m) => puedeVerModulo(user, m));
  return true;
}

/** Grupos con solo los links que el usuario puede ver (vacíos se eliminan). */
export function gruposVisibles(user: UserLike): NavGroup[] {
  return NAV_GROUPS
    .map((g) => ({ ...g, items: g.items.filter((it) => itemVisible(user, it)) }))
    .filter((g) => g.items.length > 0);
}

/** Página de entrada según permisos: Centro de Control si puede verlo,
 * si no el Inicio tipo módulos (ej. cortador). */
export function homePath(user: UserLike): string {
  if (!user) return "/centro-control";
  return puedeVerModulo(user, "centro_control") ? "/centro-control" : "/inicio";
}
