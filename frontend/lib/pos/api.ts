/**
 * Cliente del API del POS.
 *
 * Envuelve el cliente del ERP para heredar el JWT y la sesión deslizante, y
 * le agrega lo único que el POS necesita distinto: distinguir «falta
 * autorización» de «hay un error». No son lo mismo en pantalla — uno abre el
 * diálogo del PIN, el otro pinta un error rojo.
 */
import { api, ApiError } from "@/lib/api";

export interface Variante {
  variante_id: string;
  sku: string;
  referencia: string;
  talla: string;
  color: string;
  nombre: string;
  /** El precio de la ETIQUETA, con IVA. El impuesto se deriva de aquí. */
  precio_con_iva_centavos: number;
  disponible: number;
  es_escaneo: boolean;
}

export interface Cliente {
  id: string;
  tipo_documento: string;
  numero_documento: string;
  nombre: string;
  telefono?: string | null;
  correo?: string | null;
  compras: number;
}

export interface Talla {
  variante_id: string;
  sku: string;
  talla: string;
  disponible: number;
}

/** Una referencia con sus tallas — la forma que pide la rejilla del diseño. */
export interface Referencia {
  referencia: string;
  nombre: string;
  color: string;
  categoria: string;
  /** El precio de la ETIQUETA, con IVA. El impuesto se deriva de aquí. */
  precio_con_iva_centavos: number;
  tasa_iva: string;
  tallas: Talla[];
}

export interface Catalogo {
  categorias: string[];
  referencias: Referencia[];
}

export interface LineaEnvio {
  sku: string;
  cantidad: number;
  precio_unitario_centavos: number;
  tasa_iva: string;
  descripcion: string;
  descuento_porcentaje?: string;
  descuento_motivo?: string;
  autorizado_por?: string;
}

export interface Ticket {
  venta_id: string;
  numero: string;
  total_centavos: number;
  pagado_centavos: number;
  vuelto_centavos: number;
  iva_centavos: number;
  descuento_centavos: number;
  estado_fiscal: string;
  duplicada: boolean;
  /** Sólo lo pone la pantalla cuando la venta se cerró SIN RED y quedó en la
   *  cola local. El servidor nunca lo manda: allá no existe el concepto de
   *  «pendiente de llegar». */
  pendiente_de_envio?: boolean;
}

/**
 * El descuento —o el cierre— se pasa del tope del usuario que está en la caja.
 *
 * Se distingue de un error normal porque tiene una salida concreta: que entre
 * alguien con más permiso. Antes esa salida era un PIN; ahora es volver a
 * entrar con otro correo, porque el negocio decidió que sólo haya una
 * credencial.
 */
export class SobreElTope extends Error {
  constructor(public mensaje: string) {
    super(mensaje);
    this.name = "SobreElTope";
  }
}

interface DetalleError {
  error?: string;
  mensaje?: string;
  accion_sugerida?: string;
}

/**
 * Saca el detalle real del error.
 *
 * FastAPI envuelve todo en `{detail: ...}`, y el cliente del ERP guarda ese
 * SOBRE completo en `ApiError.detail` — no su contenido. Cuando el detalle es
 * un objeto (como aquí, que lleva `error` y `mensaje`) tambien termina como
 * `message`, y la pantalla mostraba «[object Object]» en vez del texto escrito
 * para la cajera. Lo vi en el diálogo del PIN.
 *
 * Se desenvuelve aquí y no en `lib/api.ts` porque ese cliente lo comparten
 * todas las pantallas del ERP y sus errores son strings.
 */
function detalleDe(e: ApiError): DetalleError | undefined {
  const bruto = e.detail as { detail?: unknown } | undefined;
  const interno = bruto && typeof bruto === "object" && "detail" in bruto
    ? bruto.detail
    : bruto;
  return interno && typeof interno === "object"
    ? (interno as DetalleError)
    : undefined;
}

function traducir(e: unknown): never {
  if (e instanceof ApiError) {
    const d = detalleDe(e);
    if (e.status === 403 &&
        (d?.error === "sobre_el_tope" || d?.error === "sin_permiso_descuadre")) {
      throw new SobreElTope(d.mensaje || "Está por encima de tu tope.");
    }
    // El mensaje del backend está escrito para la CAJERA. Se muestra tal cual.
    if (d?.mensaje) throw new Error(d.mensaje);
  }
  throw e;
}

export async function buscar(q: string, ubicacionId: string): Promise<Variante[]> {
  const p = new URLSearchParams({ q, ubicacion_id: ubicacionId });
  return api.get<Variante[]>(`/api/retail/catalogo/buscar?${p}`);
}

export async function listarCatalogo(
  ubicacionId: string,
  q = "",
  categoria = "",
): Promise<Catalogo> {
  const p = new URLSearchParams({ ubicacion_id: ubicacionId });
  if (q) p.set("q", q);
  if (categoria && categoria !== "Todo") p.set("categoria", categoria);
  return api.get<Catalogo>(`/api/retail/catalogo/referencias?${p}`);
}

export async function cerrarVenta(cuerpo: unknown): Promise<Ticket> {
  try {
    return await api.post<Ticket>("/api/retail/ventas/cerrar", cuerpo);
  } catch (e) {
    return traducir(e);
  }
}


/** Sólo por número de identificación: buscar por nombre en un mostrador
 *  devuelve seis «María González» y la cajera tiene que adivinar. */
export async function buscarClientes(documento: string): Promise<Cliente[]> {
  const p = new URLSearchParams({ documento });
  return api.get<Cliente[]>(`/api/retail/clientes/buscar?${p}`);
}

export async function crearCliente(cuerpo: {
  cliente_id: string;
  tipo_documento: string;
  numero_documento: string;
  nombre: string;
  telefono: string;
  correo: string;
}): Promise<Cliente> {
  try {
    return await api.post<Cliente>("/api/retail/clientes", cuerpo);
  } catch (e) {
    return traducir(e);
  }
}

export interface Turno {
  sesion_id: string;
  numero_turno: number;
  tienda_id: string;
  caja_id: string;
  cajera_id: string;
  cajera_nombre: string;
  tope_descuento_pct: string;
  base_inicial_centavos: number;
  reanudado: boolean;
  /** EL BLOQUE DE CONSECUTIVOS. Es lo que permite numerar sin red: el
   *  dispositivo asigna dentro de su rango sin volver a preguntar. Antes esta
   *  pantalla numeraba con `Date.now() % 100000`, que se repite cada 100
   *  segundos y choca contra el índice único (caja, prefijo, consecutivo). */
  prefijo: string;
  consecutivo_desde: number;
  consecutivo_hasta: number;
  consecutivo_siguiente: number;
}

export interface Bloque {
  prefijo: string;
  desde: number;
  hasta: number;
  siguiente: number;
}

/** Pide el bloque siguiente. Se llama al 80 % consumido, no al agotarse: si se
 *  espera al último número, la petición cae justo cuando ya no quedan, y sin
 *  red en ese momento la caja se queda sin poder vender. */
export async function arrendarBloque(
  cajaId: string,
  dispositivoId?: string,
): Promise<Bloque> {
  const p = new URLSearchParams({ caja_id: cajaId });
  if (dispositivoId) p.set("dispositivo_id", dispositivoId);
  try {
    return await api.post<Bloque>(`/api/retail/caja/consecutivos?${p}`, {});
  } catch (e) {
    return traducir(e);
  }
}

/** El turno abierto de esta caja, o null. Recargar la pantalla a media mañana
 *  no puede costar volver a entrar. */
export async function turnoActual(
  cajaId: string,
  equipo?: { id: string; nombre: string },
): Promise<Turno | null> {
  const p = new URLSearchParams({ caja_id: cajaId });
  // El equipo se identifica también al REANUDAR: es la vía por la que entra
  // una segunda tableta, y sin decir quién es se lleva el bloque de la primera.
  if (equipo) {
    p.set("dispositivo_id", equipo.id);
    p.set("dispositivo_nombre", equipo.nombre);
  }
  return api.get<Turno | null>(`/api/retail/caja/turno-actual?${p}`);
}

/** Abre turno para el usuario AUTENTICADO. No pide credenciales: ya entró con
 *  su correo y contraseña por el login del ERP. */
export async function abrirTurno(cuerpo: {
  sesion_id: string;
  tienda_id: string;
  caja_id: string;
  dispositivo_id?: string;
  dispositivo_nombre?: string;
  /** El cajón contado: `{valor_centavos: cantidad}`. Lo contado MANDA sobre la
   *  base configurada — si se abriera con la configurada, el faltante de
   *  anoche reaparecería al cierre como faltante de quien cerró hoy. */
  conteo_apertura?: Record<number, number>;
  base_justificacion?: string;
}): Promise<Turno> {
  try {
    return await api.post<Turno>("/api/retail/caja/turno", cuerpo);
  } catch (e) {
    return traducir(e);
  }
}

export interface ContextoCaja {
  tienda_id: string;
  tienda_nombre: string;
  caja_id: string;
  caja_nombre: string;
  base_caja_centavos: number;
  ubicacion_id: string | null;
  /** El encabezado de la tirilla. Viaja aquí para que el dispositivo lo tenga
   *  guardado ANTES de quedarse sin red: sin esto, una venta offline se cierra
   *  pero no se puede imprimir. */
  razon_social: string;
  nit: string;
  direccion: string;
  telefono: string;
  mensaje_tirilla: string | null;
  tiene_resolucion: boolean;
  /** Los billetes y monedas que se cuentan. Viajan con el contexto —que el
   *  equipo ya guarda— porque contar el cajón es justo lo que se hace al
   *  encender la tableta, cuando puede que todavía no haya red. */
  denominaciones: Denominacion[];
  /** Los medios que esta tienda cobra hoy. Estaban QUEMADOS en la pantalla de
   *  cobro, y uno apuntaba a un id inexistente: con tarjeta no se podía
   *  cobrar. Viajan con el contexto para que también funcionen sin red. */
  medios_pago: MedioPago[];
}

export interface MedioPago {
  id: string;
  nombre: string;
  tipo: string;
  es_efectivo: boolean;
  permite_vuelto: boolean;
  /** El único hilo que une una línea del POS con una del informe del
   *  proveedor. Sin él, cuadrar el día es comparar dos totales. */
  exige_referencia: boolean;
  /** Si la factura electrónica de este medio puede salir. Un medio sin forma
   *  de pago de Siigo se COBRA igual —la caja no se bloquea por Siigo— y su
   *  documento queda esperando. */
  factura_lista: boolean;
}

export interface Denominacion {
  valor_centavos: number;
  tipo: "billete" | "moneda";
}

/** Nombres de tienda y caja, y la base configurada. La pantalla de apertura
 *  los necesita ANTES de que exista un turno: mostrar `florida_caja1` en vez
 *  de «Caja 01» delata que nadie miró esa pantalla. */
export async function contextoCaja(cajaId: string): Promise<ContextoCaja> {
  const p = new URLSearchParams({ caja_id: cajaId });
  return api.get<ContextoCaja>(`/api/retail/caja/contexto?${p}`);
}

// ── Cierre de caja ──────────────────────────────────────────────────────────

export interface MedioResumen {
  medio_pago_id: string;
  nombre: string;
  tipo: string;
  es_efectivo: boolean;
  /** Un medio que no entra al arqueo (crédito) igual hay que declararlo, pero
   *  no hay nada físico que contar: se prellena y se bloquea. */
  entra_al_arqueo: boolean;
  total_centavos: number;
}

export interface ResumenCierre {
  sesion_id: string;
  numero_turno: number;
  cajera_nombre: string;
  abierta_en: string;
  transacciones: number;
  ventas_brutas_centavos: number;
  descuentos_centavos: number;
  anuladas: number;
  monto_anulado_centavos: number;
  medios: MedioResumen[];
  base_inicial_centavos: number;
  ventas_en_borrador: number;
  documentos_pendientes: number;
  cierre_ciego: boolean;
  umbral_descuadre_centavos: number;
  denominaciones: Denominacion[];
  /** Lo que se contó al ABRIR. Es el número contra el que se está midiendo
   *  este cierre: si el cajón amaneció corto y se explicó, quien cierra tiene
   *  derecho a verlo antes de firmar su propia diferencia. */
  base_esperada_centavos: number | null;
  base_justificacion: string | null;
  /** Retiros, gastos e ingresos. Aparte del desglose por medio de pago:
   *  mezclarlos haría que ese desglose no cuadre con lo vendido. */
  movimientos: {
    movimiento_id: string;
    tipo: string;
    monto_centavos: number;
    motivo: string;
    quien: string;
  }[];
  puede_mover_caja: boolean;
  /** Distinto de mover caja: sacar plata y deshacer una venta cobrada no
   *  son la misma operación ni las hace la misma persona. */
  puede_anular_venta: boolean;
  /** `null` en cierre ciego: el backend se NIEGA a mandarlo hasta que se
   *  declare el conteo. No es un dato que falte, es el control funcionando. */
  esperado_por_medio: Record<string, number> | null;
}

export interface Cierre {
  sesion_id: string;
  numero_turno: number;
  diferencia_centavos: number;
  cuadro: boolean;
  autorizado_por: string | null;
  autorizado_por_nombre: string | null;
}

export async function resumenCierre(sesionId: string): Promise<ResumenCierre> {
  const p = new URLSearchParams({ sesion_id: sesionId });
  return api.get<ResumenCierre>(`/api/retail/caja/cierre/resumen?${p}`);
}

export async function cerrarCaja(cuerpo: {
  sesion_id: string;
  /** Uno de los dos por medio: `piezas` para el efectivo —cantidades, y el
   *  total lo saca el servidor— y `contado_centavos` para los demás, que se
   *  leen del cierre del datáfono. Mandar ambos es un 400: dos
   *  representaciones del mismo dinero que no se obligan a coincidir son el
   *  origen exacto de un descuadre que nadie puede explicar. */
  conteos: {
    medio_pago_id: string;
    contado_centavos?: number;
    piezas?: Record<number, number>;
  }[];
  justificacion?: string;
}): Promise<Cierre> {
  try {
    return await api.post<Cierre>("/api/retail/caja/cierre", cuerpo);
  } catch (e) {
    return traducir(e);
  }
}

// ── Inventario ──────────────────────────────────────────────────────────────

export interface CeldaTalla {
  talla: string;
  disponible: number;
  /** El mínimo que rige esta celda: el de la prenda si está afinado, si no el
   *  de la tienda. Viaja para que la pantalla pueda explicar por qué avisa. */
  minimo: number;
  es_bajo: boolean;
}

export interface FilaInventario {
  referencia: string;
  nombre: string;
  color: string;
  categoria: string;
  precio_con_iva_centavos: number;
  tallas: CeldaTalla[];
  total: number;
  en_otras_ubicaciones: number;
  estado: "ok" | "bajo" | "agotado";
}

export interface Inventario {
  /** Las columnas VIENEN CON LOS DATOS. El handoff dibuja T24…T32; los SKU de
   *  MALE parsean a 4, 6, 8, 10, 12. Fijarlas aquí haría que una talla nueva
   *  no apareciera nunca. */
  columnas_talla: string[];
  filas: FilaInventario[];
  umbral_tienda: number;
  referencias: number;
  con_stock_bajo: number;
  categorias: string[];
}

export async function consultarInventario(opciones: {
  ubicacionId: string;
  tiendaId: string;
  q?: string;
  categoria?: string;
  soloBajos?: boolean;
}): Promise<Inventario> {
  const p = new URLSearchParams({
    ubicacion_id: opciones.ubicacionId,
    tienda_id: opciones.tiendaId,
  });
  if (opciones.q) p.set("q", opciones.q);
  if (opciones.categoria && opciones.categoria !== "Todo")
    p.set("categoria", opciones.categoria);
  if (opciones.soloBajos) p.set("solo_bajos", "true");
  return api.get<Inventario>(`/api/retail/inventario?${p}`);
}

// ── Panel de ventas ─────────────────────────────────────────────────────────

export interface BarraHora {
  hora: number;
  etiqueta: string;
  ventas_centavos: number;
  transacciones: number;
}

export interface MasVendido {
  posicion: number;
  referencia: string;
  nombre: string;
  color: string;
  unidades: number;
  valor_centavos: number;
}

export interface Panel {
  /** La fecha DE LA TIENDA. En UTC−5 el corte del día no es el del servidor,
   *  y un panel que no dice de qué día habla es una cifra sin contexto. */
  fecha: string;
  tienda_nombre: string;
  ventas_centavos: number;
  transacciones: number;
  ticket_promedio_centavos: number;
  unidades: number;
  anuladas: number;
  monto_anulado_centavos: number;
  descuentos_centavos: number;
  horas: BarraHora[];
  mas_vendidos: MasVendido[];
}

export async function panelDelDia(tiendaId: string): Promise<Panel> {
  const p = new URLSearchParams({ tienda_id: tiendaId });
  return api.get<Panel>(`/api/retail/panel?${p}`);
}

// ── La tirilla ──────────────────────────────────────────────────────────────

export interface LineaTirilla {
  sku: string;
  descripcion: string;
  cantidad: number;
  precio_unitario_centavos: number;
  descuento_centavos: number;
  descuento_motivo: string | null;
  total_centavos: number;
}

export interface PagoTirilla {
  nombre: string;
  monto_centavos: number;
  referencia: string | null;
}

export interface Tirilla {
  razon_social: string;
  nit: string;
  direccion: string;
  telefono: string;
  tienda_nombre: string;
  resolucion_dian: string | null;
  mensaje: string | null;
  numero: string;
  fecha: string;
  caja_nombre: string;
  cajera_nombre: string;
  cliente_nombre: string | null;
  cliente_documento: string | null;
  lineas: LineaTirilla[];
  pagos: PagoTirilla[];
  /** Presentados como en la tirilla real de Siigo: «Subtotal» es la base
   *  ANTES de IVA. Ver docs/retail-pos/tirilla-real-siigo.md */
  subtotal_centavos: number;
  total_bruto_centavos: number;
  descuento_base_centavos: number;
  impuestos: { tasa: string; base_centavos: number; impuesto_centavos: number }[];
  descuento_centavos: number;
  total_centavos: number;
  base_gravable_centavos: number;
  iva_centavos: number;
  pagado_centavos: number;
  vuelto_centavos: number;
  unidades: number;
  estado_fiscal: string;
  documento_fiscal: string | null;
  cufe: string | null;
  anulada: boolean;
  /** El QR ya dibujado en el servidor: `qr_ruta` es el atributo `d` de un
   *  <path> SVG. Viene vacío mientras no haya documento fiscal emitido — sin
   *  nada que verificar, un QR sólo haría que el papel pareciera fiscal. */
  qr_contenido: string | null;
  qr_ruta: string | null;
  qr_modulos: number;
  /** Decide el encabezado del papel. Si es `false` se imprime como
   *  COMPROBANTE y lo dice: un papel con pinta de factura que no lo es es
   *  peor que no imprimir. */
  es_documento_fiscal: boolean;
}

/** Lo que se imprime, LEÍDO DE LA BASE — no del carrito que la pantalla
 *  todavía tiene en memoria. Es el comprobante de lo que quedó registrado, y
 *  es lo que permite reimprimir tres días después. */
export async function pedirTirilla(ventaId: string): Promise<Tirilla> {
  return api.get<Tirilla>(`/api/retail/ventas/${ventaId}/tirilla`);
}

// ── Movimientos de caja ─────────────────────────────────────────────────────

export interface MovimientoCaja {
  movimiento_id: string;
  tipo: "retiro" | "ingreso" | "gasto";
  monto_centavos: number;
  motivo: string;
}

/** Plata que entra o sale del cajón sin ser una venta.
 *
 *  El monto va SIEMPRE POSITIVO: el signo lo pone el tipo. Mandar negativos
 *  dejaría convertir un retiro en un ingreso con un guion de más. */
export async function moverCaja(cuerpo: {
  movimiento_id: string;
  sesion_id: string;
  tipo: "retiro" | "ingreso" | "gasto";
  monto_centavos: number;
  motivo: string;
}): Promise<MovimientoCaja> {
  try {
    return await api.post<MovimientoCaja>("/api/retail/caja/movimientos", cuerpo);
  } catch (e) {
    return traducir(e);
  }
}

// ── Ventas del turno ────────────────────────────────────────────────────────

export interface VentaDelTurno {
  venta_id: string;
  numero: string;
  hora: string;
  total_centavos: number;
  unidades: number;
  estado: string;
  estado_fiscal: string;
  cliente_nombre: string | null;
  motivo_anulacion: string | null;
}

/** Para reimprimir o anular. Hasta ahora la tirilla sólo se podía reimprimir
 *  mientras la pantalla del ticket siguiera abierta — ocho segundos. */
export async function ventasDelTurno(sesionId: string): Promise<VentaDelTurno[]> {
  const p = new URLSearchParams({ sesion_id: sesionId });
  return api.get<VentaDelTurno[]>(`/api/retail/caja/ventas?${p}`);
}

export interface Anulacion {
  venta_id: string;
  numero: string;
  total_revertido_centavos: number;
  unidades_devueltas: number;
  /** Si la factura ya salió, anular en el POS NO la revierte ante la DIAN:
   *  hace falta una nota crédito. La pantalla tiene que decirlo. */
  exige_nota_credito: boolean;
}

export async function anularVenta(
  ventaId: string,
  motivo: string,
): Promise<Anulacion> {
  try {
    return await api.post<Anulacion>(
      `/api/retail/ventas/${ventaId}/anular`, { motivo });
  } catch (e) {
    return traducir(e);
  }
}

// ── Auditoría ───────────────────────────────────────────────────────────────

export interface EventoAuditoria {
  id: number;
  cuando: string;
  evento: string;
  severidad: "info" | "aviso" | "critico";
  quien: string;
  caja: string | null;
  /** Una línea en español, armada en el SERVIDOR. Aquí no se interpreta el
   *  payload: un `switch` por tipo de evento en la pantalla se desincroniza
   *  del backend en cuanto alguien agrega uno nuevo. */
  resumen: string;
  payload: Record<string, unknown>;
}

export interface PaginaAuditoria {
  eventos: EventoAuditoria[];
  total: number;
  /** Si la cadena de hash aguanta. Viaja JUNTO a los eventos: una lista sin
   *  decir si está íntegra invita a creérsela, y son justo los eventos que
   *  alguien querría alterar. */
  integra: boolean;
  motivo_ruptura: string | null;
  evento_roto: string | null;
  eventos_verificados: number;
}

export async function leerAuditoria(opciones: {
  tiendaId: string;
  severidad?: string;
  limite?: number;
}): Promise<PaginaAuditoria> {
  const p = new URLSearchParams({ tienda_id: opciones.tiendaId });
  if (opciones.severidad) p.set("severidad", opciones.severidad);
  if (opciones.limite) p.set("limite", String(opciones.limite));
  try {
    return await api.get<PaginaAuditoria>(`/api/retail/auditoria?${p}`);
  } catch (e) {
    return traducir(e);
  }
}

// ── Administración de permisos ──────────────────────────────────────────────

export interface PermisosUsuario {
  usuario_id: string;
  nombre: string;
  rol: string | null;
  tiendas: string[];
  tope_descuento_pct: string;
  puede_anular_venta: boolean;
  puede_cerrar_con_descuadre: boolean;
  puede_ver_esperado: boolean;
  puede_mover_caja: boolean;
  puede_ver_auditoria: boolean;
  activo: boolean;
}

export async function listarPermisos(): Promise<PermisosUsuario[]> {
  try {
    return await api.get<PermisosUsuario[]>("/api/retail/admin/permisos");
  } catch (e) {
    return traducir(e);
  }
}

/** Crea o actualiza. Queda como CRÍTICO en la auditoría con el antes y el
 *  después: conceder permisos es la operación que habilita todas las demás. */
export async function guardarPermisos(
  usuarioId: string,
  datos: Omit<PermisosUsuario, "usuario_id">,
): Promise<PermisosUsuario> {
  try {
    // PATCH, aunque el cuerpo va completo: el cliente compartido del ERP no
    // expone `put` y no vale la pena tocarlo por esto.
    return await api.patch<PermisosUsuario>(
      `/api/retail/admin/permisos/${usuarioId}`, datos);
  } catch (e) {
    return traducir(e);
  }
}
