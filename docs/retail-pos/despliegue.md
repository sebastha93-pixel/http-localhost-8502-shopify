# Poner el POS en línea

Estado a 2026-08-18: **falta crear la base.** Todo lo demás está listo y
verificado; en cuanto exista la `DATABASE_URL`, esto son minutos.

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

### 1. Crear la base

Railway → proyecto `vivacious-perception` → **New → Database → Add PostgreSQL**.

Se hace desde el panel y no por API a propósito: la API no permite adjuntar
volumen, y **un Postgres sin volumen borra todas las ventas en cada
redespliegue, en silencio.** La plantilla del panel lo trae correcto.

Luego, la `DATABASE_URL` del servicio nuevo es la que va en el paso 4.

### 2. Migrar

Desde cualquier máquina con el repo y el `.venv`:

```bash
python -m backend.modules.retail.migraciones.runner \
  "$DATABASE_URL_DEL_SERVICIO_POSTGRES"
```

Imprime a dónde va a migrar **sin la contraseña** antes de tocar nada. Migrar
la base equivocada no se deshace, y la única defensa barata es verlo escrito.

Son 16 migraciones, de `0001_esquema_inicial` a `0016_datos_reales_tienda`.

### 3. Sembrar la tienda

La migración `0016` ya deja los datos reales de Florida (NIT 901680460-1,
dirección, prefijo `FL`). Falta lo que depende de la operación:

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

Ojo con el prefijo: Railway entrega `postgresql://…` y SQLAlchemy necesita
`postgresql+psycopg://…`. Si el arranque no monta el módulo, es lo primero a
mirar.

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

* **No se puede facturar.** No existe el consumidor del outbox. La tirilla sale
  como «COMPROBANTE DE VENTA · Documento interno · no válido como factura», que
  es lo correcto mientras no haya documento emitido.
* **El stock no llega a Shopify.** `publicar_stock_shopify` se encola y nadie lo
  consume.
* **El piloto en paralelo exige mover `consecutivo_externo` a mano.** El POS ya
  respeta el piso (arranca en 1537) y el techo de la resolución (avisa al
  agotarse), pero no sabe cuánto facturó Siigo POS ayer. Eso se sincroniza solo
  el día que exista el emisor.
* **Nunca ha corrido en una tableta ni con impresora térmica real.**

Por eso el primer día en tienda va **en paralelo** con lo que se usa hoy, no
reemplazándolo.
