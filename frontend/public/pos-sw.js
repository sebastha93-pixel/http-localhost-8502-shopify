/**
 * Service worker del POS — para que la caja ABRA sin internet.
 *
 * Sin esto, todo lo offline que ya existe sólo sirve si la pestaña quedó
 * abierta: la venta sobrevive a una caída a mitad de jornada, pero si el equipo
 * se reinicia —o la tienda abre con el router caído— el navegador no puede ni
 * cargar la aplicación. Esto guarda el armazón para que arranque igual.
 *
 * ══ LO QUE NO SE GUARDA: EL API ══
 *
 * Ninguna respuesta de `/api/` entra en caché, y es la decisión más importante
 * de este archivo. Una respuesta guardada del catálogo o de las ventas del día
 * se vería EXACTAMENTE igual que una fresca: mismos números, sin marca, sin
 * fecha. La cajera leería stock de ayer creyendo que es de ahora.
 *
 * El catálogo ya tiene su copia local explícita, en IndexedDB, que la pantalla
 * muestra diciendo de cuándo es («Stock de hace 12 min»). Una caché HTTP por
 * debajo se saltaría esa honestidad. Es mejor que una consulta falle —y la
 * pantalla lo diga— a que devuelva algo viejo callando.
 *
 * ══ ESTRATEGIAS ══
 *
 * · Navegación → RED PRIMERO, caché de respaldo. Al revés, un despliegue
 *   tardaría días en llegar a las tiendas.
 * · Estáticos de Next (`/_next/static/…`) → CACHÉ PRIMERO. Llevan hash en el
 *   nombre: si el nombre coincide, el contenido es idéntico. Pedirlos por red
 *   es gastar tiempo para recibir lo mismo.
 * · Todo lo demás → red, sin guardar nada.
 *
 * ══ POR QUÉ NO HAY `skipWaiting` ══
 *
 * Activar la versión nueva de inmediato cambia la aplicación DEBAJO de una
 * venta en curso. En un POS eso es peor que actualizar un rato más tarde: la
 * versión nueva entra al siguiente arranque, cuando no hay una clienta
 * enfrente.
 */

const VERSION = "pos-v1";
const ARMAZON = `armazon-${VERSION}`;
const ESTATICOS = `estaticos-${VERSION}`;

self.addEventListener("install", (evento) => {
  // No se precarga una lista de rutas: los nombres de los paquetes de Next
  // llevan hash y cambian en cada despliegue, así que una lista escrita a mano
  // queda obsoleta el primer viernes. Se guarda lo que se vaya usando.
  evento.waitUntil(caches.open(ARMAZON));
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    (async () => {
      // Fuera las cachés de versiones anteriores: si no, el disco del equipo
      // crece con cada despliegue hasta que el navegador empieza a desalojar
      // cosas por su cuenta — incluida, eventualmente, la cola de ventas.
      const nombres = await caches.keys();
      await Promise.all(
        nombres
          .filter((n) => !n.endsWith(VERSION))
          .map((n) => caches.delete(n)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (evento) => {
  const peticion = evento.request;
  if (peticion.method !== "GET") return;

  const url = new URL(peticion.url);

  // EL API NUNCA. Ver arriba: una respuesta vieja que se ve igual que una
  // fresca es peor que un error.
  if (url.pathname.startsWith("/api/")) return;

  // Otro origen (el backend en otro puerto o dominio): tampoco.
  if (url.origin !== self.location.origin) return;

  if (peticion.mode === "navigate") {
    evento.respondWith(redPrimero(peticion));
    return;
  }

  if (url.pathname.startsWith("/_next/static/")) {
    evento.respondWith(cachePrimero(peticion));
  }
});

async function redPrimero(peticion) {
  const cache = await caches.open(ARMAZON);
  try {
    const respuesta = await fetch(peticion);
    if (respuesta.ok) cache.put(peticion, respuesta.clone());
    return respuesta;
  } catch {
    const guardada = await cache.match(peticion);
    if (guardada) return guardada;
    // Cualquier pantalla del POS sirve de armazón: la aplicación se rearma
    // sola desde el JavaScript. Sin esto, entrar a /pos/cierre sin red daría
    // el dinosaurio aunque /pos/venta esté guardada.
    const cualquiera = await cache.match("/pos/venta");
    if (cualquiera) return cualquiera;
    throw new Error("sin conexión y sin copia local");
  }
}

async function cachePrimero(peticion) {
  const cache = await caches.open(ESTATICOS);
  const guardada = await cache.match(peticion);
  if (guardada) return guardada;
  const respuesta = await fetch(peticion);
  if (respuesta.ok) cache.put(peticion, respuesta.clone());
  return respuesta;
}
