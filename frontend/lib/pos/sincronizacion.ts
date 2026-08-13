/**
 * La cola que vacía las ventas pendientes cuando vuelve la red.
 *
 * LO QUE SE REINTENTA Y LO QUE NO. Un fallo de red se reintenta: la venta es
 * válida y sólo falta que llegue. Un rechazo del servidor —número repetido,
 * regla de negocio— NO: insistir no lo arregla y la cola se quedaría girando
 * para siempre sobre la misma venta, tapando a las que sí podrían pasar.
 * Distinguirlos es la mitad del trabajo de este archivo.
 *
 * `navigator.onLine` NO ES LA SEÑAL. Dice si hay una interfaz de red levantada,
 * no si el servidor responde: el wifi de un centro comercial con el portal
 * caído da `true` y no llega nada. La verdad la da el intento; `onLine` sólo
 * sirve para despertar la cola antes.
 *
 * REINTENTO CON ESPERA CRECIENTE. Sin ella, una caída de diez minutos son
 * miles de peticiones fallidas que calientan la batería de la tablet y no
 * consiguen nada. Con tope, porque una espera que crece sin límite acaba
 * ignorando que la red ya volvió.
 */
import { cerrarVenta, SobreElTope } from "@/lib/pos/api";
import {
  anotarIntento,
  confirmada,
  encolar,
  pendientes,
  type VentaPendiente,
} from "@/lib/pos/almacen";

const ESPERA_BASE_MS = 2_000;
const ESPERA_TOPE_MS = 60_000;

export interface EstadoCola {
  enCola: number;
  rechazadas: number;
  sincronizando: boolean;
  ultimoIntento: number | null;
}

type Oyente = (e: EstadoCola) => void;

/** Cuántas veces se renumera una venta antes de darla por perdida. Tres, y no
 *  «hasta que entre»: si el bloque del equipo está mal, insistir consume la
 *  numeración entera del turno buscando un hueco que no existe. */
const RENUMERADOS_MAX = 3;

/** La pone la pantalla, que es la que tiene el bloque. La cola no puede pedir
 *  números por su cuenta: sin red no hay a quién pedírselos. */
let tomarNumero: (() => string) | null = null;

export function usarNumerador(fn: () => string): void {
  tomarNumero = fn;
}

let corriendo = false;
let temporizador: ReturnType<typeof setTimeout> | null = null;
let fallosSeguidos = 0;
const oyentes = new Set<Oyente>();

export function alCambiar(fn: Oyente): () => void {
  oyentes.add(fn);
  void avisar();
  return () => oyentes.delete(fn);
}

async function avisar(sincronizando = false): Promise<void> {
  const lista = await pendientes();
  const estado: EstadoCola = {
    enCola: lista.filter((v) => v.estado !== "rechazada").length,
    rechazadas: lista.filter((v) => v.estado === "rechazada").length,
    sincronizando,
    ultimoIntento: null,
  };
  oyentes.forEach((fn) => fn(estado));
}

/**
 * ¿Este error significa «vuelve a intentar» o «esto no va a pasar nunca»?
 *
 * Se falla del lado de REINTENTAR ante la duda. Marcar como rechazada una
 * venta que sí habría entrado es perderla; reintentar una que no va a entrar
 * sólo cuesta peticiones, y de todas formas queda visible en la pantalla.
 */
function esNumeroRepetido(e: unknown): boolean {
  return e instanceof Error && /ya está usado/i.test(e.message);
}

function esDefinitivo(e: unknown): boolean {
  if (e instanceof SobreElTope) return true;
  const mensaje = e instanceof Error ? e.message : "";
  // El cliente del ERP convierte los 4xx en Error con el mensaje del backend.
  // Un fallo de red, en cambio, llega como TypeError («Failed to fetch»).
  if (e instanceof TypeError) return false;
  return /ya está usado|no sale de ningún bloque|no está|no existe/i.test(mensaje);
}

async function enviarUna(v: VentaPendiente): Promise<boolean> {
  try {
    await cerrarVenta(v.cuerpo);
    await confirmada(v.venta_id);
    return true;
  } catch (e) {
    // NÚMERO REPETIDO: la venta es buena, sólo su número está tomado. Se
    // renumera y se reintenta en vez de darla por perdida — es plata que sí
    // entró a la caja, y dejarla «rechazada» la borra del sistema aunque la
    // clienta se haya llevado su prenda y su papel.
    //
    // El número impreso se CONSERVA para que la cajera pueda encontrar la
    // venta con el papel que la clienta trae de vuelta.
    if (esNumeroRepetido(e) && tomarNumero && (v.renumerados ?? 0) < RENUMERADOS_MAX) {
      try {
        const nuevo = tomarNumero();
        await encolar({
          ...v,
          numero: nuevo,
          numero_impreso: v.numero_impreso ?? v.numero,
          cuerpo: { ...(v.cuerpo as object), numero: nuevo },
          renumerados: (v.renumerados ?? 0) + 1,
          intentos: v.intentos + 1,
          estado: "en_cola",
        });
        return true;   // sigue la cola: la próxima vuelta lo reintenta
      } catch {
        // Sin numeración disponible: cae al camino normal y queda visible.
      }
    }

    const definitivo = esDefinitivo(e);
    await anotarIntento(v.venta_id, {
      estado: definitivo ? "rechazada" : "en_cola",
      error: definitivo
        ? e instanceof Error
          ? e.message
          : "El servidor la rechazó."
        : undefined,
    });
    // Un rechazo definitivo NO frena la cola: las que vienen detrás pueden
    // estar bien, y dejarlas atascadas por una mala sería perderlas también.
    return definitivo;
  }
}

/** Intenta vaciar la cola. Devuelve cuántas quedaron sin pasar. */
export async function sincronizar(): Promise<number> {
  if (corriendo) return -1;
  corriendo = true;
  await avisar(true);
  try {
    let atascadas = 0;
    for (const v of await pendientes()) {
      if (v.estado === "rechazada") continue;
      const ok = await enviarUna(v);
      if (!ok) {
        atascadas += 1;
        // Si la red está caída, la siguiente va a fallar igual. Se corta y se
        // reintenta el lote entero más tarde, en vez de gastar una petición
        // por venta para descubrir lo mismo.
        break;
      }
    }
    fallosSeguidos = atascadas ? fallosSeguidos + 1 : 0;
    return atascadas;
  } finally {
    corriendo = false;
    await avisar(false);
  }
}

function esperaActual(): number {
  return Math.min(ESPERA_BASE_MS * 2 ** Math.min(fallosSeguidos, 5),
                  ESPERA_TOPE_MS);
}

function programar(): void {
  if (temporizador) clearTimeout(temporizador);
  temporizador = setTimeout(async () => {
    const quedan = await sincronizar();
    if (quedan !== 0) programar();
  }, esperaActual());
}

/** Arranca la cola. Se llama una vez al montar el POS. */
export function arrancarCola(): () => void {
  const despertar = () => {
    fallosSeguidos = 0;     // la red volvió: no arrastrar la espera anterior
    void sincronizar().then((q) => {
      if (q !== 0) programar();
    });
  };

  window.addEventListener("online", despertar);
  // También al volver a la pestaña: el POS pasa ratos en segundo plano y los
  // temporizadores se ralentizan ahí.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) despertar();
  });

  despertar();
  return () => {
    window.removeEventListener("online", despertar);
    if (temporizador) clearTimeout(temporizador);
  };
}
