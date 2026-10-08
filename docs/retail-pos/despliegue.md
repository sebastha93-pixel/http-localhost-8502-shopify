# Poner el POS en línea

Estado a **2026-10-08: las dos tiendas pueden vender. Lo que no existe es
la factura electrónica.**

| | |
|---|---|
| Servicio | `Postgres` en el proyecto `vivacious-perception` |
| Versión | PostgreSQL 18.6 (`ghcr.io/railwayapp-templates/postgres-ssl:18`) |
| Volumen | `86b1e1a6-63ad-4434-91e7-f2b7baa70a5b` en `/var/lib/postgresql/data` |
| Migraciones | `0001` → `0021` |
| Variable | `RETAIL_DATABASE_URL = ${{Postgres.DATABASE_URL}}` en `backend` |
| Respaldos | PITR continuo + programación diaria y mensual |
| Enlace | `https://app.maledenim.com/pos` — uno solo; la tienda sale de quien entra |
| Arrayanes | 680 SKU · 1.828 unidades · prefijo de piloto `ARRPOS` |
| Florida | 615 SKU · 2.209 unidades · prefijo de piloto `FLPOS` |

## Qué se probó y qué no (2026-10-08)

Un turno completo recorrido a mano en cada tienda, contra una base local con
el catálogo real: abrir con el cajón corto, vender con descuento y pago mixto
con vuelto, cobrar con QR y su número de aprobación, crear clienta, devolver
en una tienda lo vendido en la otra, anular, contar a ciegas y cerrar. **Cerró
con diferencia $0.** También vender sin servidor y que la venta suba sola.

Ese recorrido encontró, y quedó corregido: el vuelto contado como faltante de
la cajera (el más grave), el conteo ciego que mostraba lo esperado, las ventas
netas que restaban lo anulado dos veces, la tirilla que prometía una factura
por correo, y el caso de Postventa que llegaba sin ticket ni clienta.

**LO QUE NO SE PUEDE PROBAR PORQUE NO EXISTE:**

* **La factura electrónica.** No es que esté sin probar: no hay emisor. Al
  cerrar una venta se encola `emitir_documento_fiscal`, que no tiene
  manejador, y aunque lo tuviera Siigo rechazaría el documento: `FL`, `TARR`
  y `FV-6` no salen en `/document-types` (verificado ese mismo día). La
  tirilla es un comprobante interno y lo dice.
* **La nota crédito automática.** Una devolución abre un caso en Postventa
  —ahora con ticket, prendas, valor y clienta— que nace esperando a que una
  persona lo apruebe. Y como la venta del POS no tiene factura propia en
  Siigo, no hay qué acreditar: la nota crédito se hace contra la factura que
  emitió Siigo POS.

Por eso el piloto va **en paralelo**: Siigo POS sigue emitiendo el documento
legal y el POS lleva la venta, la caja y el inventario.

### El emisor de facturas (2026-10-08) — construido y APAGADO

**Cambio de plan el mismo día:** NO se crean resoluciones nuevas. Se usa la
de cada tienda (`FL`, `TARR`) y Siigo la reconfigura por dentro para que
acepte documentos por API. Al cierre del día todavía no aparecen en
`/document-types`. Consecuencia: el día que una tienda emita desde el POS,
Siigo POS deja de facturar en ella — misma numeración, un solo emisor. Y la
resolución `TARR` vence el 2026-11-20.

El emisor ya existe
(`infrastructure/siigo/emisor_factura.py`) y atiende
`emitir_documento_fiscal`; lo gobierna `RETAIL_FISCAL_MODO`:

| Modo | Qué hace |
|---|---|
| `apagado` (por defecto) | No emite. Los trabajos esperan sin gastar intentos. |
| `prueba` | Crea el documento en Siigo **sin estamparlo**: no va a la DIAN, queda revisable y se puede borrar. |
| `produccion` | Estampa. Irreversible. |

**Una venta, una factura.** Siigo no tiene llave de idempotencia: si el envío
se corta sin respuesta, no se sabe si la factura se creó. Por eso antes de
enviar se confirma en la base un «voy a enviar», se envía UNA vez, y al
reintentar primero se busca la factura en Siigo por su marca
(`observations: POS <número> · <venta>`). Un 4xx no se reintenta.

Para encender una tienda hacen falta, y mientras falten el trabajo ESPERA:

* `cajas.siigo_documento_id` — el id del comprobante nuevo (el número visible
  NO es el id; sale de `/document-types`).
* `tiendas.siigo_vendedor_id` — un usuario de Siigo a cuyo nombre queda la
  venta.
* `tiendas.autorizacion_prefijo` (migración 0025) — el prefijo que ampara la
  resolución. La tirilla sólo imprime la resolución si la factura trae ESE
  prefijo.

Las ventas sin clienta van a consumidor final (222222222222). La clienta que
Siigo no conoce **se crea** (`tercero_siigo.py`, con las reglas que el Portal
Mayoristas midió contra la cuenta); si su ficha tiene un solo nombre, la venta
espera con el motivo a la vista y sale sola cuando se complete. Un cliente
que ya existe en Siigo nunca se actualiza.

**Cuándo es una factura.** Creada en Siigo no basta: es factura cuando la
DIAN la valida y hay CUFE. El documento pasa por `verificando` y se le
pregunta a Siigo —cuatro veces ahí mismo, luego cada minuto desde la cola—
hasta que el sello diga `Accepted`. Rechazada → `rechazado`; más de 6 h sin
validar → `discrepante`; las dos quedan `fallido` en la cola para que alguien
mire, y ninguna reenvía.

**El número.** El legal es `prefix`-`number` de Siigo (`TARR-11451`), NO
`name` (`FV-6-11451`, código interno; medido contra la cuenta). El número del
POS (`ARRPOS-…`) es referencia interna y **no se cambia al prefijo real**.

**El papel.** Con CUFE la tirilla es «FACTURA ELECTRÓNICA DE VENTA»: número de
Siigo, fechas de generación y expedición, adquiriente (consumidor final si no
hay clienta), forma de pago, QR, CUFE, calidad tributaria, la autorización de
numeración y el proveedor tecnológico (Siigo). Sin CUFE es un comprobante
interno y lo dice — incluido el modo `prueba`, que deja el documento
`emitido` pero sin CUFE.

**En el mostrador.** Al cerrar la venta se lanza una pasada de la cola en el
mismo worker (`planificador_outbox.empujar`), y la pantalla espera la factura
hasta 20 s antes de imprimir (sólo en `produccion`). Si no llega, sale el
comprobante diciendo que la factura está en trámite; hay botón «IMPRIMIR YA».

Lo que NO se ha probado, porque sólo lo prueba Siigo: que acepte el documento.
En particular el redondeo —Siigo redondea la base de cada línea, y dos prendas
de $149.900 le dan $299.800,01; los pagos se cuadran contra ESE total— está
deducido, no verificado. La primera emisión va en `prueba`.

Sigue sin manejador: `emitir_nota_credito`.

**Falta probar con las manos**, en la tienda: la impresora térmica (la tirilla
sale por `window.print()` a 80 mm; sin impresión directa configurada, el
navegador abre su diálogo en cada venta) y el lector de códigos.

## Lo que hace que este despliegue sea seguro

`backend/main.py` monta el módulo retail **sólo si existe `RETAIL_DATABASE_URL`**,
y dentro de un `try/except`:

```python
if _retail_dep.configurado():          # ← lee RETAIL_DATABASE_URL
    app.include_router(_retail)
```

Consecuencia práctica: **fusionar la rama a `main` no cambia nada en
producción.** El código aterriza apagado y se enciende poniendo una variable.
Si el módulo tuviera un fallo al importar, el `except` impide que tumbe el ERP.

Por eso el orden es base → variable → migraciones → fusionar, y no al revés.

## Decisión de arquitectura: instancia PROPIA, en Railway

El POS no comparte base con el ERP. El motivo no es la limpieza: es que **la
tienda tiene que poder cobrar aunque el ERP esté caído.** Compartir instancia
acopla vender a la salud de otro sistema — y si el ERP y el CRM agotan las
conexiones un martes, la caja deja de cobrar sin que nadie entienda por qué.

El esquema `retail` ya está aislado por nombre, así que compartir *funcionaría*.
Lo que se pierde es la independencia, que es justo lo que hace falta.

**Por qué Railway y no Supabase.** Va en el MISMO proyecto que el backend, así
que la consulta no sale a internet. Es más barato (~5 USD/mes contra 10). Y es
un proveedor menos: el intento de crearlo en Supabase se topó con
`PaymentRequiredException — overdue invoices`, y depender de dos facturaciones
distintas para que la tienda cobre es una dependencia que no hace falta tener.

**Por qué NO un servidor propio administrado por nosotros.** El día malo de un
servicio gestionado es una factura vencida: molesto, se arregla pagando, la
tienda no se entera. El día malo de un servidor propio es un sábado a las 8pm
con la tienda llena y el disco lleno. Además el ahorro no existe a esta escala:
dos tiendas generan decenas de miles de filas al mes, una base que cabe en la
máquina más pequeña de cualquier proveedor. Si algún día se quiere servidor
propio, el POS es el PEOR primer candidato — es lo más nuevo, lo menos probado,
y lo único que para la caja.

## Los pasos

### 1. Crear la base — HECHO (2026-08-29)

~~Se hace desde el panel y no por API: la API no permite adjuntar volumen.~~
**Eso ya no es cierto** y conviene corregirlo, porque era la razón por la que
este paso llevaba once días parado. La API sí adjunta volúmenes
(`create-volume`), y el agente de Railway despliega la plantilla oficial de
Postgres, que lo trae correcto de fábrica.

Lo que NO cambia es el porqué de la advertencia: **un Postgres sin volumen
borra todas las ventas en cada redespliegue, en silencio.** Sea quien sea que
lo cree, hay que verificarlo después — no dar por bueno que lo diga quien lo
creó:

```bash
railway postgres pitr status --service Postgres   # y mirar el volumen en el panel
```

### 2. Migrar

Desde cualquier máquina con el repo y el `.venv`:

```bash
python -m backend.modules.retail.migraciones.runner \
  "$DATABASE_URL_DEL_SERVICIO_POSTGRES"
```

Imprime a dónde va a migrar **sin la contraseña** antes de tocar nada. Migrar
la base equivocada no se deshace, y la única defensa barata es verlo escrito.

Son 20 migraciones, de `0001_esquema_inicial` a `0020_devoluciones`.

### 3. Sembrar la tienda

⚠️ **La migración `0016` NO crea la tienda: la ACTUALIZA.** Este documento
decía que «ya deja los datos reales de Florida», y es falso — su SQL es un
`UPDATE retail.tiendas`, que sobre una base nueva no toca ninguna fila porque
no hay ninguna. La fila venía del sembrador de DESARROLLO (`semilla.py`), que
no corre en producción.

Comprobado el 2026-08-29 sobre la base recién migrada: **0 tiendas, 0 cajas,
0 ubicaciones**, y de medios de pago sólo `addi`, `sumas` y `wompi_qr` (los
que sí inserta la `0015`). Falta hasta el efectivo.

~~O sea que después de migrar hay que sembrar a mano.~~ Ya no: **`sembrar_tiendas`**
crea Florida (dos cajas, prefijo `FL`) y Arrayanes (una caja, `FV-6`), sus
ubicaciones y los medios de pago. Corre en ENSAYO por defecto, no pisa nada que
ya exista, y se puede repetir:

```bash
python -m backend.modules.retail.sembrar_tiendas            # ensayo
python -m backend.modules.retail.sembrar_tiendas --aplicar
```

El **efectivo y el datáfono son de cada tienda** (`efectivo_florida` → Siigo
12243, `efectivo_arrayanes` → 8282…): en Siigo son cuentas distintas, y un
efectivo compartido mandaría la plata de una tienda a la cuenta de la otra.

**Arrayanes quedó completo el 2026-10-01**, con una tirilla real
(`TARR-11389`, 30/09/2026): dirección `CR 50A 36 90 LC 231, Itagüí`, teléfono,
y su resolución. **Su prefijo NO era `FV-6`** —ese es el tipo de documento
viejo de Siigo— **sino `TARR`**, autorización 18764083761292 del 1 al
1.000.000. Pedir la tirilla fue lo que lo descubrió; `FV-6` habría salido
impreso en cada papel.

⚠️ **Esa resolución vence el 2026-11-20** (aprobada el 2024-11-20, vigencia 24
meses). Hay que pedir la nueva a la DIAN; no es algo del POS.

**Las dos tiendas numeran con un prefijo de piloto —`ARRPOS` y `FLPOS`—, no
con el de su resolución** (`TARR` y `FL`). Mientras Siigo POS siga facturando
en la tienda, los dos imprimirían papeles distintos con el mismo número y
nadie sabría cuál buscar cuando la clienta vuelva a cambiar. El día que el POS
emita de verdad: cambiar el prefijo al real y subir `consecutivo_externo` al
número que vaya Siigo. Mientras tanto, **no hay que tocar el consecutivo
antes de cada jornada**.

Después, el **catálogo** — con `python -m backend.modules.retail.cargar_catalogo`,
una vez por tienda (`RETAIL_UBICACION=tienda:arrayanes`). Lee un CSV, corre en
ENSAYO por defecto y no borra nada. No confundir con `semilla.py`, que hace
`TRUNCATE` y sólo corre en local.

**El CSV sale de Siigo**, que es donde vive el inventario de la tienda física:
una fila por SKU con existencia en su bodega (Florida 48, Arrayanes 37), con
el precio de la lista —que viene CON IVA cuando el producto está marcado
`tax_included`, y hay que multiplicar cuando no—. Arrayanes se cargó así el
2026-10-01: **681 SKU, 174 referencias, 1.830 unidades, $288.806.100** a
precio de etiqueta.

Lo que queda FUERA y hay que mirar a mano: productos sin precio en Siigo (la
referencia 94609-1 completa) y los que están marcados sin IVA cuando todos sus
hermanos lo traen incluido (`H31503-1`, que daba $190.281 — el único precio
que no terminaba en 900). El cargador no adivina precios.

⚠️ El ENSAYO no toca la base: valida el CSV y calcula el valor, nada más. Dos
fallos que sólo aparecen al aplicar —la URL de Railway sin normalizar y una
columna `color` vacía contra un `NOT NULL`— se arreglaron el 2026-10-01.

### 3b. El enlace, y de dónde sale la tienda

**Un solo enlace para todas las tiendas: `https://app.maledenim.com/pos`.**

LA TIENDA SALE DE QUIEN ENTRA, no del enlace. Un enlace por caja se reenvía
por WhatsApp y acaba abierto en la tableta de la otra tienda, vendiendo contra
un inventario ajeno — y eso no se descubre hasta el conteo. Una persona no se
reenvía: la asesora entra con su correo y el POS lee sus tiendas de
`permisos_pos.tiendas`, que se asignan en **Permisos del POS**.

Lo que sí decide el EQUIPO es cuál de las cajas de esa tienda es: Florida
tiene dos mostradores y eso es propiedad de la tableta, no de la persona. Se
pregunta una vez y se recuerda. Donde hay una sola caja no se pregunta nada.

| Quién entra | Qué pasa |
|---|---|
| Asignada a una tienda de una caja | entra directo a vender |
| Asignada a Florida (dos cajas) | elige el mostrador una vez, por tableta |
| Sin tienda asignada | «Todavía no tienes caja», con qué pedir |
| Administrador | ve todas: es quien configura |

**La puerta está en el TURNO**: abrir turno en una tienda que no es tuya se
rechaza, también al reanudar uno ya abierto. Va ahí y no en cada venta porque
abrir turno siempre ocurre con red y antes de cobrar; comprobarlo en la venta
rechazaría una cobrada sin conexión si reasignaron a esa persona mientras
tanto, y esa venta ya pasó.

Los enlaces por caja siguen existiendo
(`/pos/venta?caja=florida_caja2`) y sirven para **asignar una tableta** a un
mostrador concreto sin preguntar. Lo que ya no hacen es decidir la tienda: si
la caja del enlace no es de las tuyas, el servidor no te deja abrir turno.

La tienda y la ubicación salen de la caja en el servidor, y el servidor
rechaza una venta o un turno cuya caja, tienda e inventario no sean de la misma
tienda. Una devolución se hace en la caja DONDE ocurre: la plata sale de ese
cajón y la prenda entra a esa tienda, aunque la venta haya sido en la otra.

Y además lo que depende de la operación:

* Las **cajas** y sus prefijos, si va a haber más de una.
* Los **permisos** de cada cajera — se hacen desde `/pos/permisos`, que existe
  justamente para no depender de `psql`.
* Los **medios de pago**: `wompi_qr`, `addi` y `sumas` nacen SIN id de Siigo a
  propósito. Se cobran igual; su factura queda pendiente hasta que se
  configuren. Ver `tirilla-real-siigo.md`.
* **`tiendas.consecutivo_externo`** — el último número que Siigo POS ya usó.
  La 0018 lo deja en 1536 para Florida, que es lo que decía la tirilla de la
  foto. **Mientras Siigo POS siga facturando en paralelo durante el piloto,
  hay que subirlo antes de cada jornada**, o los dos sistemas emitirán el
  mismo número bajo la misma resolución. El día que el POS sea el único que
  emite, deja de moverse.

### 4. Encender

Railway → proyecto `vivacious-perception` → servicio `backend` → variable:

```
RETAIL_DATABASE_URL = ${{Postgres.DATABASE_URL}}
```

Se usa la REFERENCIA de Railway (`${{Postgres.DATABASE_URL}}`) y no la cadena
copiada a mano: si la contraseña rota, la referencia sigue apuntando bien y una
copia pegada deja de funcionar sin decir por qué.

~~Ojo con el prefijo: Railway entrega `postgresql://…` y SQLAlchemy necesita
`postgresql+psycopg://…`.~~ **Ya no hay que vigilarlo**: `crear_motor`
normaliza la URL. Era una advertencia que sólo protegía a quien la hubiera
leído, y el fallo que evita es invisible — el `try/except` se come el error y
el POS sencillamente no aparece.

Al redesplegar, el arranque imprime `🛒 Modulo retail (POS) montado en /api/retail`.
Si no aparece esa línea, el módulo NO está montado — el `except` se lo tragó y
el mensaje dice por qué.

### 5. Fusionar la rama

`feat/retail-dominio` → `main`. El frontend es la misma app Next, así que las
pantallas `/pos/*` viajan con ella.

## Lo primero que hay que hacer una vez arriba

En este orden, porque cada uno desbloquea al siguiente:

1. **`GET /api/retail/admin/clientes/muestra-siigo`** — devuelve un veredicto de
   cobertura. Confirma el mapeo de clientas contra la cuenta real antes de
   importar nada. Ver `veredicto` y `problemas` en la respuesta.
2. **`POST /api/retail/admin/clientes/importar?dry_run=true`** — ensayo. Luego
   `dry_run=false`.
3. **`GET /api/postventa/siigo/discovery`** — trae las formas de pago y el
   `automatic_number` de los tipos de documento. Sin eso no se puede escribir
   el emisor fiscal.

## Lo que sigue sin resolverse con desplegar

* **No se puede facturar.** ~~No existe el consumidor del outbox.~~ El
  consumidor SÍ existe y corre cada dos minutos; lo que falta es el manejador
  de `emitir_documento_fiscal`, y eso está bloqueado en SIIGO, no aquí: los comprobantes
  de tienda (FL, FV-6, FV-11, FV-12) no salen en `/document-types`, así que
  `POST /invoices` los rechaza. Mientras tanto la cola guarda esos trabajos
  **sin gastarles intentos**, así que el día que se destrabe se emiten solos.
  La tirilla sale como «COMPROBANTE DE VENTA · Documento interno · no válido
  como factura», que es lo correcto mientras no haya documento emitido.
* **El stock no llega a Shopify.** `publicar_stock_shopify` se encola y nadie lo
  consume.
* **El piloto en paralelo exige mover `consecutivo_externo` a mano.** El POS ya
  respeta el piso (arranca en 1537) y el techo de la resolución (avisa al
  agotarse), pero no sabe cuánto facturó Siigo POS ayer. Eso se sincroniza solo
  el día que exista el emisor.
* **Nunca ha corrido en una tableta ni con impresora térmica real.** La
  tirilla sale por `window.print()` con `@page 80mm`, así que depende de que
  la impresora esté instalada en la tableta. Es lo primero que hay que probar
  en el local, antes de que haya una clienta esperando.

Por eso el primer día en tienda va **en paralelo** con lo que se usa hoy, no
reemplazándolo.

## Respaldos (2026-08-29)

**PITR — recuperación a un punto en el tiempo, activa.** No son fotos diarias:
es continuo, así que se puede volver a un instante concreto. Para una caja la
diferencia es real — con sólo una foto de las 2 a. m., un problema a las 3 p. m.
cuesta toda la mañana de ventas.

Además hay programación **diaria** (retención 6 días) y **mensual** (89 días).
No se puso semanal: el plan tope 10 respaldos y las tres juntas se pasan.

```bash
railway postgres pitr status   --service Postgres
railway postgres pitr backup list --service Postgres
railway postgres pitr restore  --service Postgres --at 2026-08-29T14:00:00Z
```

El primer respaldo se creó a mano el 2026-08-29 (`88a1f967…`) para comprobar el
mecanismo entero, no sólo la configuración.

**Lo que esto NO cubre**, y conviene saberlo antes de necesitarlo:

* «Vaciar un volumen borra todos sus respaldos» (documentación de Railway).
* Sólo se restaura **en el mismo proyecto y entorno**. Si se pierde la cuenta
  de Railway, no hay copia fuera.

Para lo segundo existe el bucket `respaldos-pos` (ya creado) y la plantilla
`postgres-s3-backups`, que vuelca copias ahí. No está montada: PITR cubre el
riesgo que de verdad ocurre —un borrado, una migración mala, una corrupción—
y el volcado externo es para el escenario de perder el proveedor entero.
