# Poner el POS en línea

Estado a 2026-08-18: **bloqueado por facturas vencidas en Supabase.** Todo lo
demás está listo y verificado. Cuando se salde el pago, esto son minutos.

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

## Decisión de arquitectura: instancia PROPIA

El POS no comparte base con el ERP. El motivo no es la limpieza: es que **la
tienda tiene que poder cobrar aunque el ERP esté caído.** Compartir instancia
acopla vender a la salud de otro sistema — y si el ERP y el CRM agotan las
conexiones un martes, la caja deja de cobrar sin que nadie entienda por qué.

El esquema `retail` ya está aislado por nombre, así que compartir *funcionaría*.
Lo que se pierde es la independencia, que es justo lo que hace falta.

Costo: 10 USD/mes (proyecto Supabase). Frente a perder un día de ventas, es
barato — y los backups diarios vienen incluidos, que para la base que guarda
las ventas y es el registro legal hasta que se emitan facturas no es opcional.

## Los pasos

### 1. Crear la base

Supabase → organización `yyixgpntdgschcbvkuoy` → nuevo proyecto
`male-denim-pos`, región `us-east-2` (la misma que `male-crm`).

> Bloqueado hoy: `PaymentRequiredException — There are overdue invoices`.
> Los seis proyectos existentes siguen `ACTIVE_HEALTHY`, pero una organización
> con facturas vencidas puede terminar con proyectos pausados. Eso es más
> urgente que este despliegue.

### 2. Migrar

Desde cualquier máquina con el repo y el `.venv`:

```bash
python -m backend.modules.retail.migraciones.runner \
  "postgresql+psycopg://postgres:CLAVE@db.REF.supabase.co:5432/postgres"
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

### 4. Encender

Railway → proyecto `vivacious-perception` → servicio `backend` → variable:

```
RETAIL_DATABASE_URL = postgresql+psycopg://postgres:CLAVE@db.REF.supabase.co:5432/postgres
```

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
* **La numeración empieza en 1** y la resolución `FL` va por 1536. Al emitir hay
  que continuar donde va Siigo.
* **Nunca ha corrido en una tableta ni con impresora térmica real.**

Por eso el primer día en tienda va **en paralelo** con lo que se usa hoy, no
reemplazándolo.
