# Barrido de Melonn por tramos con cursor

**Fecha:** 2026-08-06
**Módulos:** `src/melonn_client.py`, `backend/services/salud_logistica.py`
**Base:** `origin/main` @ `a49e0f2`

---

## 1. El problema

El backend barre `GET /sell-orders` de Melonn paginando desde la página 0 hasta
que se sale de la ventana de 90 días. Hoy son ~44 páginas y ~4.200 pedidos en
ventana: **~88 segundos de peticiones seguidas**, porque el limitador deja 2 s
entre GETs (`_MAX_RPS = 0.5`).

> **Las 44 páginas son una estimación, no una medida.** Lo medido el 2026-08-01
> fue `en_ventana = 4200` con `paginas = 43`, *antes* del corte por fecha de
> `4ca695d`. Nadie ha medido cuántas páginas barre desde ese arreglo. No cambia
> el diseño: `N` se autocalibra contra el barrido anterior real (§3.3), así que
> el número correcto lo aprende solo en el primer ciclo. Sí conviene confirmarlo
> en `/api/melonn/salud` antes de fijar expectativas de cuota.

Si **cualquiera** de esas ~44 peticiones falla, el barrido entero se pierde.
`_fetch_api_filtrado` marca `completo = False`, descarta lo traído y devuelve
`[]`, y `obtener_pedidos_activos` conserva el caché anterior.

Ese descarte **es correcto y se conserva**. Antes guardaba la lista cortada como
si fuera completa, y así se llegó a comparar el tablero contra media lista. El
problema no es lo que hace cuando falla; es que **depende de que ~44 peticiones
seguidas salgan bien**, y eso no se puede garantizar.

### Qué pasó realmente el 2026-08-01

El brief original atribuyó la caída a `fallo_get_pagina_42`. Ese fallo ocurrió,
pero **no fue la causa de que el tablero se quedara pegado**. La causa fue:

```
fetch: tope_paginas · paginas=61 · completo=False   (3 chequeos seguidos en rojo)
```

Melonn no ofrece filtro por fecha en el listado, así que la ventana de 90 días se
aplica de este lado, después de bajar los datos. Al quitar el corte anticipado, el
barrido pasó a descargar la historia completa de la empresa (>6.100 pedidos),
topó `_MAX_PAGES = 60` y quedó marcado incompleto **para siempre**.

Eso ya está arreglado en `4ca695d`: el corte ahora es **por fecha** (dos páginas
llenas seguidas sin un solo pedido en ventana → `motivo_fin = "fuera_de_ventana"`,
que cuenta como completo).

**Consecuencia para este spec:** el cursor ya no es urgente. Es robustez, no un
incendio. Lo que sigue arreglando:

1. Un `fallo_get_pagina_N` todavía cuesta el barrido completo.
2. No hay forma de responder *"¿el tablero de ahora es auditable?"* — hay un solo
   reloj y no distingue "le hablé a Melonn hace poco" de "la lista que muestro
   está completa".

### Hallazgo aparte: el TTL de 2 h no frena el barrido del scheduler

Hay dos caminos de refresh y solo uno respeta `_CACHE_TTL`:

| Camino | Disparo | ¿Respeta `_CACHE_TTL = 7200`? |
|---|---|---|
| `_refresh_background()` | Abrir la página con caché vencido | Sí |
| `obtener_pedidos_activos(forzar_refresh=True)` | Scheduler, cada tick | **No** |

En la rama de `forzar_refresh` el único guard es `api_age_s < _MIN_REFRESH_SECS`
(**60 s**). Con `REFRESH_LIGHT_SECONDS = 3600`, `api_age ≈ 3600 > 60` → barre
igual, **cada hora**. Son ~24 barridos/día × 44 ≈ **1.056 peticiones/día**, no las
~516 que registra el mensaje de `e1d6ebf`.

Sigue holgado contra la cuota de 10.000/día, pero el número medido está a la
mitad. **Este spec lo corrige de raíz**: con cursor, la cadencia la fija el
cursor, no el tick.

---

## 2. Decisiones tomadas

| Decisión | Elegido | Por qué |
|---|---|---|
| Alcance | **Solo tramos.** El caché de 6,5 MB se parte aparte | Cambio desplegable y verificable solo. El módulo lleva muchos despliegues; no conviene meter dos cambios grandes juntos |
| Cadencia | **Barrido completo cada 2 h** | Encaja con los umbrales del centinela ya desplegados (ámbar 180 min, rojo 360 min): no hay que recalibrar nada. Y baja el gasto a la mitad de lo que consume hoy de verdad |
| Fusión | **Incremental sobre el caché vivo**, bajas al cerrar el barrido | No añade un segundo blob de 6,5 MB en Supabase, coherente con no tocar el caché todavía |

Alternativas descartadas:

- **Staging con publicación atómica.** El caché vivo seguiría siendo siempre un
  snapshot coherente — más limpio — pero exige un segundo blob de 6,5 MB en
  Supabase, justo lo que la otra tarea quiere eliminar.
- **Híbrido** (staging para bajas, fusión directa para altas). Mejor en frescura
  y coherencia, pero son dos caminos de escritura y una regla más donde puede
  esconderse el próximo bug silencioso.

---

## 3. Diseño

### 3.1 Dónde vive el estado del barrido

Fila `id = 3` en la tabla `melonn_cache` de Supabase (`_SB_FILA_BARRIDO`). No hace
falta migración: la tabla ya acepta `id = 2` para la marca del fetch.

En SQLite va en su **propia tabla** `melonn_barrido`, no en una fila de
`melonn_pedidos_cache`: esa tabla tiene `CHECK (id = 1)` y el insert fallaría en
silencio. Es el mismo patrón que ya usó `melonn_fetch_marca`.

El estado se serializa en la columna `pedidos_json` existente:

```json
{
  "v": 1,
  "generacion": 137,
  "pagina": 22,
  "tam_pagina": 100,
  "paginas_fuera_ventana": 0,
  "iniciado_en": "2026-08-06T14:00:00",
  "vistas": ["M12345", "M12346", "..."],
  "ausencias": {"M9001": 1},
  "paginas_barrido_previo": 44,
  "motivo_ultimo_tramo": "tramo_ok",
  "ultimo_tramo_en": "2026-08-06T15:00:00",
  "ultimo_completo_en": "2026-08-06T13:58:00",
  "lease_worker": "a3f1…",
  "lease_hasta": "2026-08-06T15:01:30"
}
```

Tres campos merecen justificación:

- **`vistas`** son ~4.200 claves ≈ 40 KB, escritas una vez por tick. Va aparte y
  **no** como campo dentro de cada pedido, para no engordar el blob de 6,5 MB que
  la otra tarea quiere partir.
- **`paginas_fuera_ventana`** tiene que persistir. Es el contador del corte por
  fecha de `4ca695d`, que exige **dos páginas llenas seguidas** sin pedidos en
  ventana. Hoy es una variable local al loop; si un tramo termina justo entre esas
  dos páginas y el contador se reinicia, **el barrido no corta nunca** y vuelve el
  `tope_paginas` que rompió el tablero el 1 de agosto.
- **`lease`** existe porque `_BG_LOCK_PATH = /tmp/…` es por contenedor. Si Railway
  levanta réplicas, dos avanzarían el cursor a la vez: doble gasto de cuota y un
  cursor incoherente. Compare-and-set sobre `lease_hasta`.

### 3.2 El ciclo de un tick

```
_barrido_tick():
  1. tomar lease · si otro worker lo tiene y no venció → salir
  2. si no hay barrido en curso:
       ultimo_completo_en hace < 2 h  → salir (la cadencia la fija el cursor)
       si no                          → generación nueva: pagina=0, vistas=[],
                                        paginas_fuera_ventana=0
     si hay uno en curso y iniciado_en hace > 6 h → abandonarlo y empezar de cero
  3. traer hasta N páginas desde `pagina`
       página OK    → normalizar + filtrar, acumular claves en `vistas`,
                      actualizar paginas_fuera_ventana, avanzar cursor
       página FALLA → NO avanzar el cursor. Guardar estado y salir del tick.
                      El tick siguiente reintenta ESA página.
  4. fusionar lo traído sobre el caché vivo (§3.4)
  5. ¿terminó el barrido? (ultima_pagina | sin_mas_datos | fuera_de_ventana)
       sí → reconciliar bajas (§3.5)
            _marcar_fetch_api()          ← el reloj de "barrido COMPLETO"
            paginas_barrido_previo = pagina + 1
            generacion += 1 · pagina = 0 · vistas = [] · ausencias conservadas
       no → sellar solo `ultimo_tramo_en`
  6. soltar lease
```

**Por qué se abandona una generación de más de 6 h** (paso 2): un barrido que no
cierra en 6 h significa que lleva varios tramos fallando. Seguir acumulando
`vistas` de hace horas hace que la reconciliación mida contra una foto vieja.
6 h coincide con `FETCH_ROJO_MIN`, así que para entonces el centinela ya está en
rojo. Se registra en el log y en `motivo_ultimo_tramo`.

**`_MAX_PAGES = 60` se sigue aplicando a la generación completa**, no por tramo:
el cursor lleva números de página absolutos. Si `pagina >= _MAX_PAGES`, el barrido
se cierra con `motivo_fin = "tope_paginas"`, **no** se sella el reloj de completo,
y el centinela lo marca en rojo — igual que hoy.

### 3.3 Tamaño del tramo y traslape

**N se autocalibra:** `N = max(4, min(30, ceil(paginas_barrido_previo / 2)))`.

Hoy son ~44 páginas → tramos de 22 → el barrido cierra en 2 ticks = 2 h. Si el
listado crece, N crece solo y la cadencia se mantiene. Cuando la otra tarea
recorte la ventana, N baja solo. Sin `paginas_barrido_previo` (primer arranque) se
usa 22.

**Traslape de una página:** salvo el primer tramo de la generación, cada tramo
arranca en `pagina - 1` y re-lee esa página.

Es la defensa contra el corrimiento del listado. Paginar por offset sobre una
lista que se mueve entre tick y tick puede **saltarse un pedido**: si se borran
ítems por encima, todo sube de índice y un pedido puede pasar del rango no barrido
al ya barrido, y desaparecer sin dejar rastro. Una página (100 pedidos) cubre
cualquier corrimiento realista en una hora.

Eso importa más de lo que parece por `_marcar_despacho_observado` — ver §3.4.

La página de traslape es **solo para fusión**: no toca `paginas_fuera_ventana`
(ya se contó) ni se cuenta dos veces en `paginas_barrido_previo`.

Costo: +1 petición por tramo salvo el primero. Con 44 páginas y 2 tramos son 45
peticiones por barrido en vez de 44.

### 3.4 Fusión

`_fusionar_tramo(vivos, frescos)` reusa `_clave_pedido` y aplica **exactamente la
misma regla** que `_heredar_enriquecidos`:

- El fresco manda en estado y logística.
- Los `_CAMPOS_ENRIQUECIDOS` solo se pisan si el fresco trae valor — un vacío
  nunca borra un dato heredado (cliente, ciudad, guía, fechas de despacho).
- Clave nueva → se agrega. **Nunca se quita nada aquí.**

Y llama a `_marcar_despacho_observado(p, prev)` igual que hoy.

**Esto es lo más delicado del cambio.** `_marcar_despacho_observado` no copia
campos: **detecta una transición** comparando el `sub_estado_logistico` fresco
contra el del caché. Si un pedido se salta un tramo justo cuando pasa de
`pendiente_despacho` a `en_transito`, esa fecha **se pierde para siempre** — el
barrido siguiente ve `en_transito` en los dos lados y ya no hay transición que
observar. No se puede recalcular. Por eso el traslape de §3.3 no es opcional.

Un pedido que aparece en dos tramos se compara dos veces, pero la función ya es
idempotente: `if p.get("fecha_despacho_observada"): return False`.

### 3.5 Bajas — regla de dos barridos

Al cerrar un barrido, las claves del caché que no están en `vistas` suman una
ausencia. **Se dan de baja a la segunda ausencia consecutiva.** Si reaparecen, el
contador se limpia.

Por qué no a la primera: paginar por offset sobre una lista que se mueve puede
saltarse un pedido (§3.3), y ese es justo el error que no se ve. Una ausencia
puede ser un corrimiento; dos seguidas es que de verdad no está.

Costo: un cancelado tarda hasta 4 h en salir del tablero. De eso normalmente se
encarga el webhook, no el barrido.

Efecto secundario bueno: un pedido que creó un webhook durante el barrido en curso
no estaba en `vistas`, suma 1 ausencia y **no** se cae.

**`vistas` guarda las claves de los pedidos que pasaron el filtro**, no las de
todos los ítems crudos. Así un pedido que Melonn devuelve pero que el tablero
descarta (cancelado, B2B, estado fuera de la whitelist, fuera de los 90 días y ya
cerrado) cuenta como ausente y termina saliendo — que es exactamente lo que hace
hoy el reemplazo completo del caché.

### 3.6 Los candados que ya existen

**Anti-vaciado (`_cache_guardar`, 40 % / 50 pedidos).** Se conserva y **no** se
usa `forzar`:

- Durante los tramos la lista solo crece o se queda igual → nunca se dispara.
- En la reconciliación sí puede encoger. Ahí el candado se queda encendido: una
  caída bajo el 40 % al reconciliar es un accidente que hay que bloquear. Con la
  regla de dos barridos una baja legítima es de unidades.

**Fetch incompleto no reemplaza el caché.** Se conserva, pero cambia de granularidad:
ya no aplica al barrido entero sino a la **página**. Una página que falla no se
fusiona y no avanza el cursor. Las anteriores sí se fusionan, porque están
completas y son correctas.

### 3.7 Los dos relojes

- **`_edad_fetch_api()` conserva su significado exacto**: se sella solo al cerrar
  un barrido completo. Así `_caduco_vs_melonn` y los umbrales del centinela
  (`FETCH_AMARILLO_MIN = 180`, `FETCH_ROJO_MIN = 360`) siguen calibrados sin
  tocarlos.
- **`_edad_tramo()`** es nuevo: segundos desde el último tramo, completo o no.
- **`ultimo_fetch()`** deja de leer el `_ULTIMO_FETCH` de proceso y lee la fila
  del cursor. Así sobrevive reinicios y es igual en todas las réplicas. Tiene un
  solo consumidor (`salud_logistica._revisar_fetch`), así que el cambio de forma
  es contenido.

Forma nueva de `ultimo_fetch()`:

```json
{"generacion": 137, "pagina": 22, "paginas_estimadas": 44,
 "en_curso": true, "motivo_fin": "tramo_ok",
 "ultimo_completo_en": "…", "ultimo_tramo_en": "…"}
```

### 3.8 Cambios en `salud_logistica.py`

**Obligatorio, o el centinela queda rojo permanente.** Hoy `_revisar_fetch` marca
rojo ante cualquier `completo = False`. Con tramos, estar a mitad de barrido es lo
**normal**.

| Situación | Hoy | Con tramos |
|---|---|---|
| Barrido en curso | rojo `fetch_incompleto` | informativo: `generación 137, página 22 de ~44` |
| Sin cerrar barrido en > `FETCH_ROJO_MIN` | rojo | rojo (sin cambio, vía `_edad_fetch_api`) |
| > 3 ticks sin un tramo | *no se detecta* | **rojo `barrido_atascado`** (nuevo) |
| `tope_paginas` | rojo | rojo (sin cambio) |
| Guardado bloqueado | rojo | rojo (sin cambio) |

El hallazgo nuevo `barrido_atascado` cubre el caso que hoy no tiene alarma: el
último barrido completo es reciente, así que el reloj principal está verde, pero
el barrido en curso lleva horas sin avanzar ni una página.

Los umbrales `FETCH_AMARILLO_MIN` / `FETCH_ROJO_MIN` **no se tocan**.

### 3.9 Qué NO cambia

- El botón "Sincronizar datos" y el camino del hard-TTL de 24 h siguen usando
  `_fetch_api()` bloqueante y completo. Hay una persona esperando; que gaste ~90 s
  está bien. Se distingue del camino del scheduler con un parámetro `modo`
  (`"tramo"` para el scheduler, `"completo"` para lo manual).
- El corte por fecha de `4ca695d` se conserva tal cual. Solo se persiste su
  contador.
- `_merge_webhook`, `_CAMPOS_ENRIQUECIDOS`, `refrescar_un_pedido`: sin cambios.
- El filtro de estados, la whitelist y la ventana de 90 días: sin cambios.

---

## 4. Riesgos

| Riesgo | Mitigación |
|---|---|
| El listado se corre entre tramos y un pedido se salta | Traslape de una página (§3.3) + regla de dos barridos (§3.5) |
| Se pierde una `fecha_despacho_observada` en un salto | Mismo traslape. Es el dato que **no se puede recalcular** |
| El contador del corte por fecha se reinicia en un borde de tramo → vuelve `tope_paginas` | Se persiste en el cursor (§3.1) |
| Dos réplicas avanzan el cursor a la vez | Lease con compare-and-set (§3.1) |
| Un barrido no cierra nunca y el reloj de completo envejece | Se abandona a las 6 h y empieza de cero; el centinela ya está en rojo para entonces |
| La reconciliación borra de más | Candado anti-vaciado encendido (§3.6) |
| El centinela queda rojo permanente por estar a mitad de barrido | §3.8, obligatorio |

**El riesgo aceptado, explícito:** entre cierres, el caché es una mezcla de
generaciones. La página 2 es de hace 5 minutos y la 40 de hace 2 horas. Es el
precio de no añadir un segundo blob de 6,5 MB, y es tolerable porque los webhooks
son los que dan la frescura en tiempo real — el barrido es la red de seguridad.
El reloj de "barrido COMPLETO" es el que dice si el tablero es auditable, y ese
sigue siendo honesto.

---

## 5. Pruebas

Con las respuestas de Melonn simuladas, como en `4ca695d`.

| Caso | Qué prueba |
|---|---|
| Falla la página 30 de un tramo | El cursor no pasa de 30; las páginas 22-29 quedan fusionadas; el tick siguiente arranca en 30 |
| Dos tramos hasta el final | `_marcar_fetch_api` sellado una sola vez, generación +1, cursor en 0 |
| Tramo que termina entre las dos páginas fuera de ventana | El contador sobrevive y el barrido corta con `fuera_de_ventana` |
| Pedido ausente 1 barrido / 2 barridos | No se da de baja / se da de baja |
| Pedido creado por webhook durante el barrido | No se da de baja |
| Fusión de tramo | `nombre_comprador`, `guia_real`, `fecha_despacho_confiable` sobreviven |
| Transición de despacho dentro del traslape | `fecha_despacho_observada` se marca una sola vez |
| Reconciliación que borraría el 70 % | Bloqueada por el candado |
| `pagina` llega a `_MAX_PAGES` | `tope_paginas`, reloj de completo NO sellado, centinela rojo |
| Generación de más de 6 h | Se abandona y arranca una nueva |
| Dos workers en el mismo tick | Solo uno avanza el cursor |
| Centinela a mitad de barrido | No es rojo |
| Centinela con 3 ticks sin tramo | Rojo `barrido_atascado` |

---

## 6. Verificación en producción

La API de Melonn solo responde desde la IP de Railway (desde fuera da 403
`explicit deny in an identity-based policy`), así que hay que medir por el backend
desplegado:

1. `/api/melonn/status` — confirmar `SCHEDULER_LIGHT_SEC` y el gasto real.
2. `/api/melonn/salud` — el semáforo tiene que quedar **verde**, con
   `ultimo_fetch` mostrando la generación y la página.
3. Observar **dos barridos completos seguidos** (≈4 h) y confirmar que
   `minutos_desde_fetch` se resetea al cerrar cada uno, no en cada tramo.
4. `/api/melonn/diagnostico-filtros` — el total del tablero no debe moverse más de
   lo normal al pasar de barrido completo a barrido por tramos.
5. Histórico en la tabla `logistica_salud`: ningún rojo nuevo.
6. Cuota: el gasto diario debe **bajar** de ~1.056 a ~540 peticiones
   (12 barridos × 45).

---

## 7. Fuera de alcance

- **Partir el caché de 6,5 MB** (4.380 pedidos en un solo JSON que el webhook
  reescribe completo). Tarea aparte, decidida como tal. Este diseño evita a
  propósito añadir un segundo blob para no empeorarla.
- El `http_400` de `stock?warehouse_code=MED-2&per_page=250` que dejó registrado
  el centinela. Afecta inventario, no logística.
- El 89 % de fechas de despacho estimadas sobre el histórico (medido en
  `f49b84a`). Es un problema de backfill, no del barrido.
