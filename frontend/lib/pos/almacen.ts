/**
 * Lo que sobrevive a que se caiga la red, el navegador o la luz.
 *
 * ESCRITURA ANTICIPADA. La venta se guarda AQUÍ antes de intentar mandarla. Lo
 * natural sería al revés —intentar, y encolar si falla— pero eso pierde la
 * venta en la única ventana que importa: el instante entre que la clienta paga
 * y el servidor responde. Si en ese instante se va la luz, con el orden
 * natural no queda rastro de nada; con este, la venta está en disco y sale
 * sola al volver.
 *
 * INDEXEDDB Y NO `localStorage`. `localStorage` es síncrono: escribir bloquea
 * el hilo que pinta, y en el POS eso son milisegundos de los treinta segundos.
 * Además tiene ~5 MB y guarda sólo texto, así que un día de ventas sin red
 * cabría raspando.
 *
 * NO ES UNA COPIA DEL SERVIDOR. Aquí sólo vive lo que todavía no llegó allá.
 * Una réplica local del catálogo o de las ventas del día sería otra cosa —y
 * otra fuente de verdad que mantener sincronizada—. Lo que está confirmado se
 * borra de aquí.
 */

const BASE = "pos-male";
const VERSION = 3;

const PENDIENTES = "ventas_pendientes";
const CARRITO = "carrito";
const CATALOGO = "catalogo";
const CONTEXTO = "contexto";

export type EstadoPendiente = "en_cola" | "enviando" | "rechazada";

export interface VentaPendiente {
  /** El ULID de la venta. Es la llave de idempotencia: reintentar con el mismo
   *  id no duplica nada del lado del servidor (ADR-005). */
  venta_id: string;
  numero: string;
  cuerpo: unknown;
  creada_en: number;
  intentos: number;
  estado: EstadoPendiente;
  /** Cuántas veces se le cambió el número porque el suyo ya estaba tomado. */
  renumerados?: number;
  /** El número que se IMPRIMIÓ en el papel de la clienta. Si la venta se
   *  renumeró al sincronizar, el sistema quedó con otro — y este es el único
   *  hilo para encontrarla cuando la clienta vuelve con su tirilla. */
  numero_impreso?: string;
  /** Por qué la rechazó el servidor. Sólo se llena cuando NO tiene sentido
   *  reintentar: un número repetido o una regla de negocio no mejoran por
   *  insistir, y hay que enseñárselo a la cajera. */
  error?: string;
}

let conexion: Promise<IDBDatabase> | null = null;

function abrir(): Promise<IDBDatabase> {
  if (conexion) return conexion;
  conexion = new Promise((resolver, rechazar) => {
    const peticion = indexedDB.open(BASE, VERSION);
    peticion.onupgradeneeded = () => {
      const db = peticion.result;
      if (!db.objectStoreNames.contains(PENDIENTES)) {
        db.createObjectStore(PENDIENTES, { keyPath: "venta_id" });
      }
      if (!db.objectStoreNames.contains(CARRITO)) {
        db.createObjectStore(CARRITO);
      }
      if (!db.objectStoreNames.contains(CATALOGO)) {
        db.createObjectStore(CATALOGO);
      }
      if (!db.objectStoreNames.contains(CONTEXTO)) {
        db.createObjectStore(CONTEXTO);
      }
    };
    peticion.onsuccess = () => resolver(peticion.result);
    peticion.onerror = () => rechazar(peticion.error);
  });
  return conexion;
}

async function conStore<T>(
  nombre: string,
  modo: IDBTransactionMode,
  fn: (s: IDBObjectStore) => IDBRequest,
): Promise<T> {
  const db = await abrir();
  return new Promise<T>((resolver, rechazar) => {
    const tx = db.transaction(nombre, modo);
    const peticion = fn(tx.objectStore(nombre));
    peticion.onsuccess = () => resolver(peticion.result as T);
    peticion.onerror = () => rechazar(peticion.error);
  });
}

/** ¿Se puede guardar en disco? En modo incógnito de algunos navegadores, no.
 *  Hay que saberlo ANTES de prometerle a la cajera que no se pierde nada. */
export async function almacenDisponible(): Promise<boolean> {
  try {
    if (typeof indexedDB === "undefined") return false;
    await abrir();
    return true;
  } catch {
    return false;
  }
}

// ── Ventas pendientes ───────────────────────────────────────────────────────

export async function encolar(v: VentaPendiente): Promise<void> {
  await conStore(PENDIENTES, "readwrite", (s) => s.put(v));
}

export async function pendientes(): Promise<VentaPendiente[]> {
  const todas = await conStore<VentaPendiente[]>(
    PENDIENTES, "readonly", (s) => s.getAll());
  // Por orden de creación: la numeración es correlativa y mandarlas
  // desordenadas dejaría huecos temporales en los informes del día.
  return todas.sort((a, b) => a.creada_en - b.creada_en);
}

export async function confirmada(ventaId: string): Promise<void> {
  await conStore(PENDIENTES, "readwrite", (s) => s.delete(ventaId));
}

export async function anotarIntento(
  ventaId: string,
  cambios: Partial<VentaPendiente>,
): Promise<void> {
  const actual = await conStore<VentaPendiente | undefined>(
    PENDIENTES, "readonly", (s) => s.get(ventaId));
  if (!actual) return;
  await encolar({ ...actual, ...cambios, intentos: actual.intentos + 1 });
}

// ── El carrito ──────────────────────────────────────────────────────────────
//
// Se guarda en cada cambio. Un corte de luz a mitad de una venta de doce
// prendas obliga a escanearlas otra vez con la clienta esperando (R11).

export async function guardarCarrito(datos: unknown): Promise<void> {
  await conStore(CARRITO, "readwrite", (s) => s.put(datos, "actual"));
}

export async function leerCarrito<T>(): Promise<T | undefined> {
  return conStore<T | undefined>(CARRITO, "readonly", (s) => s.get("actual"));
}

export async function limpiarCarrito(): Promise<void> {
  await conStore(CARRITO, "readwrite", (s) => s.delete("actual"));
}


// ── La identidad del equipo ─────────────────────────────────────────────────
//
// No autentica nada: de eso se encarga el login del ERP. Sirve para que dos
// tabletas en la misma caja no compartan bloque de numeración y saquen
// tiquetes con el mismo número.
//
// Vive en la MISMA base que la cola de ventas: si se borran los datos del
// navegador se pierden las dos a la vez, que es lo coherente — un equipo sin
// su cola pendiente es, a efectos prácticos, un equipo nuevo.

const EQUIPO = "equipo";

export async function idDelEquipo(nuevoId: () => string): Promise<string> {
  const guardado = await conStore<string | undefined>(
    CARRITO, "readonly", (s) => s.get(EQUIPO));
  if (guardado) return guardado;
  const id = nuevoId();
  await conStore(CARRITO, "readwrite", (s) => s.put(id, EQUIPO));
  return id;
}


// ── El catálogo ─────────────────────────────────────────────────────────────
//
// Se guarda una COPIA COMPLETA, sin filtro de búsqueda ni de categoría: sin
// red no se puede volver a preguntar, así que hay que tener todo y filtrar
// aquí. Guardar sólo lo último consultado dejaría a la cajera viendo tres
// referencias porque justo antes de la caída había buscado «falda».
//
// EL STOCK QUE SE GUARDA ES UNA FOTO, y envejece. Por eso viaja `guardado_en`:
// la pantalla tiene que poder decir de cuándo es. Ofrecer como disponible algo
// que se vendió hace tres horas en la otra caja produce la peor conversación
// posible en el mostrador.

export interface CatalogoGuardado<R> {
  referencias: R[];
  categorias: string[];
  guardado_en: number;
}

export async function guardarCatalogo<R>(
  datos: { referencias: R[]; categorias: string[] },
): Promise<void> {
  await conStore(CATALOGO, "readwrite", (s) =>
    s.put({ ...datos, guardado_en: Date.now() }, "completo"));
}

export async function leerCatalogo<R>(): Promise<CatalogoGuardado<R> | undefined> {
  return conStore<CatalogoGuardado<R> | undefined>(
    CATALOGO, "readonly", (s) => s.get("completo"));
}


/**
 * EL CONTEXTO DE LA CAJA, guardado.
 *
 * Sin esto, una tableta que enciende sin red no puede VENDER — ni siquiera
 * abrir el turno. En el contexto viajan las DENOMINACIONES (sin ellas no hay
 * nada que contar y el botón dice «Cuenta el cajón» para siempre) y los MEDIOS
 * DE PAGO (sin ellos no hay con qué cobrar). También el encabezado de la
 * tirilla: razón social, NIT y dirección.
 *
 * Lo encontré apagando el servidor de verdad: la pantalla de apertura salía
 * con cero filas de billetes. Yo mismo había escrito en el router que estos
 * datos «viajan con el contexto, que el equipo ya guarda» — y el equipo no lo
 * guardaba. El comentario afirmaba algo que no era cierto.
 */
export async function guardarContexto(datos: unknown): Promise<void> {
  await conStore(CONTEXTO, "readwrite", (s) =>
    s.put({ datos, guardado_en: Date.now() }, "caja"));
}

export async function leerContexto<T>(): Promise<T | undefined> {
  const g = await conStore<{ datos: T } | undefined>(
    CONTEXTO, "readonly", (s) => s.get("caja"));
  return g?.datos;
}


// ── Cuánto lleva esta caja sin hablar con el servidor ───────────────────────
//
// No es lo mismo que «hay red». La caja puede estar cobrando sin conexión
// perfectamente durante una hora; lo que no puede es seguir haciéndolo tres
// días. Cuanto más tiempo pasa, más cosas se han movido a sus espaldas: precios
// que cambiaron, stock que se vendió en la otra caja, un turno que alguien
// cerró desde el panel.
//
// Se guarda el ÚLTIMO CONTACTO EXITOSO, no el último intento: un equipo que
// lleva tres días intentando cada dos minutos sigue llevando tres días sin
// saber nada.

const CONTACTO = "ultimo_contacto";

export async function marcarContacto(): Promise<void> {
  await conStore(CARRITO, "readwrite", (s) => s.put(Date.now(), CONTACTO));
}

export async function ultimoContacto(): Promise<number | null> {
  const v = await conStore<number | undefined>(
    CARRITO, "readonly", (s) => s.get(CONTACTO));
  return typeof v === "number" ? v : null;
}
