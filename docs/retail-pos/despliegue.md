# Poner el POS en línea

Estado a **2026-08-29: la base ya existe, migrada y asociada.**

| | |
|---|---|
| Servicio | `Postgres` en el proyecto `vivacious-perception` |
| Versión | PostgreSQL 18.6 (`ghcr.io/railwayapp-templates/postgres-ssl:18`) |
| Volumen | `86b1e1a6-63ad-4434-91e7-f2b7baa70a5b` en `/var/lib/postgresql/data` |
| Migraciones | `0001` → `0020`, 28 tablas |
| Variable | `RETAIL_DATABASE_URL = ${{Postgres.DATABASE_URL}}` en `backend` |
| Respaldos | PITR continuo + programación diaria y mensual |

**Lo que falta para vender: los datos operativos.** Ver «Sembrar la tienda»
más abajo — la base está migrada pero no tiene tienda, ni caja, ni ubicación,
ni los medios de pago básicos.

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

O sea que después de migrar hay que sembrar a mano:

* La **tienda**, la **caja** con su prefijo y la **ubicación** de inventario.
* Los **medios de pago** básicos: efectivo, datáfono, transferencia.
* El **catálogo** — con `python -m backend.modules.retail.cargar_catalogo`,
  que lee un CSV, corre en ENSAYO por defecto y no borra nada. No confundir
  con `semilla.py`, que hace `TRUNCATE` y sólo corre en local.

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
  de `emitir_factura`, y eso está bloqueado en SIIGO, no aquí: los comprobantes
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
* **Nunca ha corrido en una tableta ni con impresora térmica real.**

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
