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
      { label: "Postventa",     href: "/postventa",     permiso: "postventa",     desc: "Cambios, devoluciones y garantías con IA" },
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
    // Ordenado según el FLUJO del proceso productivo:
    // vista general → precosteo → tela entra → corte → despacho →
    // remisiones → seguimiento del lote → costeo real → directorio.
    title: "Producción",
    items: [
      { label: "Producción",    href: "/produccion",                 permiso: "produccion",         desc: "Vista general del módulo" },
      { label: "Tablero",       href: "/produccion/tablero",         permiso: "produccion",         desc: "Alertas y estado global" },
      { label: "Precosteo",     href: "/produccion/precosteo",                                      desc: "1 · Costeo por referencia" },
      { label: "Ingreso",       href: "/produccion/ingreso",         permiso: "produccion_ingreso", desc: "2 · Entradas de tela" },
      { label: "Inventario",    href: "/produccion/inventario",      permiso: "produccion_ingreso|produccion_cortador", desc: "3 · Telas y rollos disponibles" },
      { label: "Insumos",       href: "/produccion/insumos",         permiso: "produccion_ingreso", desc: "4 · Stock de insumos" },
      { label: "Orden corte",   href: "/produccion/corte",           permiso: "produccion_corte|produccion_cortador", desc: "5 · Cortes asignados e informe" },
      { label: "Mis despachos", href: "/produccion/mis-despachos",   permiso: "produccion_cortador", desc: "6 · Unidades despachadas por corte" },
      { label: "Remisiones",    href: "/produccion/remisiones",      permiso: "produccion_remisiones", desc: "6 · Entregas e insumos por lote" },
      { label: "Lotes",         href: "/produccion/lotes",           permiso: "produccion|produccion_remisiones", desc: "7 · Seguimiento del lote en proceso" },
      { label: "Costeo real",   href: "/produccion/costeo",                                         desc: "8 · Cierre con Siigo" },
      { label: "Proveedores",   href: "/produccion/confeccionistas", permiso: "produccion_proveedores", desc: "Directorio: confección, lavandería, terminación" },
    ],
  },
  {
    // Módulo Personal. "Mi tiempo" va primero y SIN permiso: es el
    // autoservicio, lo ve todo empleado con login. Si alguien no tiene
    // ningún permiso del módulo, este es el único item que verá.
    title: "Personal",
    items: [
      { label: "Mi tiempo",      href: "/personal/mi-tiempo",                                    desc: "Tu jornada, permisos y saldo" },
      { label: "Dashboard",      href: "/personal",              permiso: "personal",            desc: "Asistencia del día y tendencias" },
      { label: "Empleados",      href: "/personal/empleados",    permiso: "personal",            desc: "Fichas, áreas y jerarquía" },
      { label: "Asistencia",     href: "/personal/asistencia",   permiso: "personal_asistencia", desc: "Jornadas calculadas por día" },
      { label: "Permisos",       href: "/personal/permisos",     permiso: "personal_permisos",   desc: "Solicitudes y aprobaciones" },
      { label: "Compensaciones", href: "/personal/compensaciones", permiso: "personal_permisos", desc: "Tiempo por reponer" },
      { label: "Horas extras",   href: "/personal/extras",       permiso: "personal_permisos",   desc: "Autorización y seguimiento" },
      { label: "Incidencias",    href: "/personal/incidencias",  permiso: "personal_asistencia", desc: "Marcaciones incompletas" },
      { label: "Horarios",       href: "/personal/horarios",     permiso: "personal_config",     desc: "Jornadas y turnos" },
      { label: "Calendario",     href: "/personal/calendario",   permiso: "personal|personal_permisos", desc: "Vista mensual del equipo" },
      { label: "Novedades",      href: "/personal/nomina",       permiso: "personal_nomina",     desc: "Para nómina, con revisión" },
      { label: "Dispositivos",   href: "/personal/dispositivos", permiso: "personal_dispositivos", desc: "Dahua y estado del conector" },
      { label: "Reportes",       href: "/personal/reportes",     permiso: "personal",            desc: "Puntualidad, ausentismo, permisos" },
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

/**
 * Grupos detrás de feature flag.
 *
 * El flag del backend (TIME_MANAGEMENT_ENABLED) decide si el API existe, pero
 * NO alcanza al menú: el frontend es otro despliegue. Sin este gate, "Mi
 * tiempo" —que a propósito no exige permiso, porque es el autoservicio— le
 * saldría a TODO el mundo apuntando a una página que aún no existe.
 *
 * Poner NEXT_PUBLIC_TIME_MANAGEMENT_ENABLED=true en Vercel cuando las páginas
 * estén desplegadas (Fase 5). Debe activarse junto con el flag del backend.
 */
const GRUPOS_CON_FLAG: Record<string, boolean> = {
  Personal: process.env.NEXT_PUBLIC_TIME_MANAGEMENT_ENABLED === "true",
};

export function grupoHabilitado(titulo: string): boolean {
  return GRUPOS_CON_FLAG[titulo] ?? true;
}

export function itemVisible(user: UserLike, it: NavItem): boolean {
  if (ADMIN_ONLY.includes(it.href)) return esAdmin(user as User);
  if (COSTOS_ONLY.includes(it.href)) return puedeVerCostosProduccion(user);
  if (it.permiso) return it.permiso.split("|").some((m) => puedeVerModulo(user, m));
  return true;
}

/** Grupos con solo los links que el usuario puede ver (vacíos se eliminan). */
export function gruposVisibles(user: UserLike): NavGroup[] {
  return NAV_GROUPS
    .filter((g) => grupoHabilitado(g.title))
    .map((g) => ({ ...g, items: g.items.filter((it) => itemVisible(user, it)) }))
    .filter((g) => g.items.length > 0);
}

/** Página de entrada según permisos: Centro de Control si puede verlo,
 * si no el Inicio tipo módulos (ej. cortador). */
export function homePath(user: UserLike): string {
  if (!user) return "/centro-control";
  return puedeVerModulo(user, "centro_control") ? "/centro-control" : "/inicio";
}
