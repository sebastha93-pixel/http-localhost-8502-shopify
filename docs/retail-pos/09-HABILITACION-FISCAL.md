# 09 · Habilitación fiscal en Siigo — runbook

> **Estado de D1: resuelta.** Se crean comprobantes nuevos, uno por tienda, emitibles por API.
> Este documento es el procedimiento y —más importante— **cómo verificar que quedó bien
> antes de construir nada encima**.

---

## 1. La trampa que hay que evitar

Crear el comprobante en Siigo **no basta**. FV-6, FV-11 y FV-12 existen, están activos y
facturan todos los días en las tiendas — y aun así la API los rechaza:

```
POST /invoices → document_settings
"The id cannot be used, you must verify the document settings"
Params: ["document.id"]
```

La señal que lo delataba estaba en otro lado, y el código ya la había identificado
([`tiendas.py:64-66`](../../backend/services/tiendas.py)):

> *"Y `/document-types` nunca los devuelve — esa ausencia era la señal, no un descuido."*

**De ahí sale la prueba decisiva de todo este procedimiento:**

> ### Un comprobante sirve para el POS si —y sólo si— aparece en `GET /document-types`.

Es una consulta de un segundo y responde la pregunta antes de gastar un peso en desarrollo.
Si el prefijo nuevo no aparece ahí, algo quedó mal configurado del lado de Siigo, y ninguna
cantidad de código lo arregla.

---

## 2. Cuántos comprobantes: uno por tienda

Tu mensaje dice "para reconocer cada tienda", y esa es la decisión correcta. Hoy hay tres
prefijos para tres cajas (Florida tiene FV-11 y FV-12); con el POS nuevo bastan **dos**:

| Tienda | Cajas | Comprobante nuevo | Bodega Siigo | Centro de costo |
|---|---|---|---|---|
| Florida | Caja 1 y Caja 2 | uno solo | `48` | `774` |
| Arrayanes | Arrayanes | uno solo | `37` | `677` |

### Por qué no hace falta uno por caja

Las tres razones por las que un POS tradicional necesita un prefijo por caja **no aplican en
este diseño**:

| Razón clásica | Por qué no aplica |
|---|---|
| "Cada caja necesita su propia numeración para no chocar" | El consecutivo DIAN lo asigna **Siigo** al emitir, de forma centralizada y serializada. Nuestra numeración de ticket ya es por caja, con bloques arrendados (doc 04). Son dos numeraciones distintas y sólo una es fiscal. |
| "El arqueo se cuadra por prefijo" | El arqueo se cuadra contra **nuestros** datos: `sesion_id` → pagos. No necesita el número de factura para nada. |
| "Sin prefijo por caja no se sabe qué caja vendió" | Cada venta guarda `caja_id`, `dispositivo_id` y `cajera_id`. Se sabe con más precisión que con un prefijo. |

Menos prefijos = menos resoluciones DIAN que renovar y vigilar. Cada rango que se vence
estando desatendido es una tienda que no puede facturar.

**Cuándo sí querrías uno por caja:** si tu contador prefiere atar la numeración a un punto
físico, o si en algún momento dos sistemas distintos van a facturar en la misma tienda. Si
es el caso, el diseño lo soporta sin cambios — `retail.cajas.siigo_documento_id` ya es por
caja, no por tienda. Sólo cargarías un id distinto en cada fila.

### Nomenclatura

Sugiero continuar la convención que ya lee tu contador (`FV-N`) en vez de inventar un
esquema nuevo: por ejemplo `FV-20` Florida y `FV-21` Arrayanes. Lo importante es que **no se
confundan con FV-1** (venta online) ni con FV-6/11/12 (las cajas actuales), porque durante
el piloto van a convivir en los mismos informes.

---

## 3. El procedimiento

### Paso 1 · DIAN — rango de numeración (lo hace el contador)

Solicitar autorización de numeración de facturación electrónica para cada prefijo nuevo.
**Este paso es del contador y del representante legal, no mío** — no te voy a dar
instrucciones fiscales que no me corresponden.

Lo que necesito que salga de ahí, para poder configurar el sistema:

- Número de resolución
- Prefijo autorizado
- Rango: desde – hasta
- Fecha de vigencia (inicio y **vencimiento**)

⚠️ Pide un rango **holgado**. Si Florida hace ~60 facturas al día, un rango de 5.000 se agota
en 3 meses, y un rango agotado un sábado deja la tienda sin facturar. Con 50.000 no vuelves
a pensar en el tema en años.

### Paso 2 · Siigo — crear el comprobante

En Siigo Nube, crear el tipo de comprobante de venta con:

- El prefijo autorizado por la DIAN
- La resolución cargada (número, rango, vigencia)
- Marcado como **factura electrónica**
- **Habilitado para uso por API / integración** ← esto es lo que le falta a FV-11/12/6
- Bodega por defecto: la de la tienda (48 Florida / 37 Arrayanes)
- Centro de costo: si el comprobante lo marca obligatorio, el de la tienda (774 / 677)

Si la interfaz de Siigo no ofrece una casilla explícita para habilitarlo por API, es el
momento de escribirle a soporte con esta pregunta concreta:

> *"Creamos el tipo de documento de venta con prefijo `FV-20`. No aparece en la respuesta de
> `GET /v1/document-types`. ¿Qué configuración le falta para poder emitir con él desde la
> API con `POST /v1/invoices`?"*

### Paso 3 · Verificación por API ⭐ (esta es la que manda)

Ya tienes el endpoint en producción:

```
GET /api/postventa/siigo/tipos-documento
```

→ [`backend/api/postventa.py:499`](../../backend/api/postventa.py)

**Qué tiene que pasar:** el prefijo nuevo aparece en la lista.

**Anota el `id` que devuelve la API.** No el número que ves en la pantalla de Siigo — ya nos
pasó dos veces: la bodega "5" tiene id `48`, y FV-11 se ve como "11" y su id es `31433`. El
número de pantalla no sirve para nada.

Si el prefijo **no** aparece: vuelve al paso 2. No sigas. Ese es exactamente el estado en el
que están hoy FV-6/11/12, y significa que la API no lo va a aceptar.

> **Por qué la ausencia sí es concluyente.** La historia del repo lo confirma: primero se
> construyó `tipos_documento_completos()` **paginando** `/document-types` justamente
> sospechando que la lista llegaba incompleta (commit `77bb93a`). No apareció nada nuevo. Sólo
> entonces se construyó el rodeo de deducir los ids recorriendo facturas reales (`9c76415`).
> Es decir: se descartó que fuera un problema de paginación **antes** de aceptar que la
> ausencia era real.

### Paso 3b · Los siete campos que deciden si la emisión funciona

La respuesta de `/document-types` trae, por cada comprobante, campos que **deciden el éxito de
una emisión** y que conviene mirar el mismo día que lo creas — no en el primer rechazo con la
clienta enfrente. El repo ya los expone
([`postventa_siigo.py:271-294`](../../backend/services/postventa_siigo.py)):

| Campo | Qué decide | Qué queremos ver |
|---|---|---|
| `electronic_type` | Si es factura electrónica de verdad | Que sea electrónico |
| `active` | Si está habilitado | `true` |
| `automatic_number` | **Si Siigo asigna el consecutivo DIAN, o lo tenemos que mandar nosotros** | Preferimos `true` — ver abajo |
| `cost_center_mandatory` | Si exige centro de costo | Si es `true`, cargar 774 / 677 |
| `discount_type` | Si los descuentos se mandan como `Percentage` o como `Value` | Determina cómo mapea el POS los descuentos |
| `decimals` | Cuántos decimales admite | Afecta el redondeo del IVA |
| `consecutive` | En qué número va el rango | Para vigilar el agotamiento |

**El que más pesa es `automatic_number`.**

- Si es `true`, Siigo asigna el consecutivo DIAN al emitir. Es lo más simple y lo que asume
  el diseño por defecto.
- Si es `false`, **el consecutivo DIAN lo tenemos que asignar nosotros** y mandarlo en el
  campo `number`. Eso no rompe el diseño, pero agrega una regla que hay que implementar bien:
  el número se reserva **en el momento de emitir** (en el worker, que es de una sola réplica y
  toma lock), nunca en el momento de la venta. Y hay que registrar los huecos: si el `POST`
  falla después de haber reservado un número, ese número queda quemado y debe quedar
  documentado, no reutilizado.

Esto refuerza, por cierto, la decisión de **un prefijo por tienda y no por caja**: como el
número fiscal se asigna al emitir —en el servidor, serializado— las dos cajas de Florida
pueden compartir prefijo sin competir por el consecutivo. Si el número se asignara en la caja,
compartir prefijo sí sería un problema.

Los otros dos que ya costaron caro en postventa: `discount_type` decide **cómo** se manda un
descuento (mandar un porcentaje donde espera un valor es un rechazo que no dice la causa), y
`advance_payment` decide si el comprobante admite anticipos.

### Paso 4 · Factura de prueba y relectura

Con `SIIGO_POSTVENTA_MODO=prueba` (el valor por defecto — no toca DIAN):

1. `POST /invoices` con el `document.id` nuevo, la bodega de la tienda, el centro de costo y
   un pago de la caja de esa tienda.
2. `GET /invoices/{id}` — **releer la factura emitida**.
3. Comparar: prefijo, total, pagos, bodega y centro de costo.

El paso 3 no es opcional y no es paranoia. `tiendas.py:211-221` documenta que Siigo
**descartaba `warehouse` en silencio**: la factura salía con 200 OK, el inventario no se
movía, y no había error en ninguna parte.

### Paso 5 · Cargar la configuración

Con los ids verificados, van a `retail.cajas`:

| Caja | `prefijo_factura` | `siigo_documento_id` |
|---|---|---|
| `florida_caja1` | FV-20 | *(el id real de la API)* |
| `florida_caja2` | FV-20 | *(el mismo)* |
| `arrayanes` | FV-21 | *(el id real de la API)* |

Mientras `siigo_documento_id` sea NULL, **el sistema se niega a facturar** desde esa caja. Es
deliberado y ya es el criterio que aplica el código de hoy: un id adivinado sale con el
prefijo de otro punto y descuadra la numeración DIAN.

---

## 4. Lo que esto desbloquea, además del POS

### El piloto deja de ser riesgoso

Los prefijos nuevos son **aditivos**: no tocan FV-6/11/12, que siguen facturando en Siigo POS
exactamente igual. Consecuencia directa sobre la decisión D2:

> Durante la Fase 6 el POS nuevo puede facturar en paralelo, en la misma tienda, con su
> propia numeración, **sin poner en riesgo la operación actual**. Si el piloto sale mal, se
> apaga y no hay nada que revertir en la contabilidad.

Eso convierte D2 de una decisión de fondo ("¿reemplazo o convivencia?") en una decisión de
calendario: se convive durante el piloto y se reemplaza cuando las métricas lo justifiquen.
**Es la mejor noticia de todo esto.**

### Un arreglo gratis para postventa, hoy

Mientras estés en Siigo con este tema, vale la pena resolver otro pendiente del mismo tipo.
Existe **FV-5 «Factura de venta Cambios»** (id `27154`), hoy **inactivo**. Por eso los cambios
en tienda se facturan con FV-1, el prefijo de la venta online
([`tiendas.py:69-73`](../../backend/services/tiendas.py)).

Si activas su resolución en la misma gestión, el arreglo del lado del código es **una variable
de entorno en Railway**:

```
SIIGO_DOC_FACTURA_CAMBIO=27154
```

Sin deploy, sin código nuevo. Los cambios pasan a facturarse con su propio comprobante en vez
de ensuciar la numeración de la venta web. Ojo con un detalle que el código ya contempla:
FV-5 tiene `cost_center_obligatorio: true`, así que las dos tiendas necesitan su centro de
costo cargado — 774 y 677, que ya están.

---

## 5. Criterio de salida de la Fase 0

La Fase 3 (fiscal) no arranca hasta que esto esté en verde:

- [ ] Rango DIAN autorizado para cada tienda, con vigencia y rango holgado
- [ ] Comprobante creado en Siigo por tienda
- [ ] **El prefijo aparece en `GET /document-types`** ← la prueba decisiva
- [ ] `id` real de la API anotado (no el de pantalla)
- [ ] Anotados los siete campos del paso 3b, en especial **`automatic_number`** y `discount_type`
- [ ] Factura de prueba emitida por API con ese prefijo
- [ ] Factura **releída** y verificada: prefijo, total, pagos, bodega, centro de costo
- [ ] Ids cargados en `retail.cajas`
- [ ] *(opcional, alto valor)* FV-5 activo y `SIIGO_DOC_FACTURA_CAMBIO` puesto

### Qué de esto cambia el código

| Resultado | Impacto |
|---|---|
| `automatic_number: true` | Ninguno. El diseño ya lo asume. |
| `automatic_number: false` | El worker fiscal asigna y reserva el consecutivo DIAN al emitir, con registro de huecos. ~2 días en Fase 3. |
| `discount_type` distinto en cada tienda | El mapeador convierte por comprobante. Ya está previsto: es un campo del adaptador, no del dominio. |
| `cost_center_mandatory: true` | Ninguno. 774 y 677 ya están cargados. |

Cuando esto esté, el riesgo R1 —el único bloqueante del proyecto— queda cerrado.

---

## 6. Qué documento se emite: **factura electrónica** (decidido)

Esta pregunta estaba abierta sin que nadie la hubiera nombrado. El esquema deja elegir por
tienda —`tiendas.tipo_documento_fiscal IN ('factura_electronica','pos_electronico')`— y todo
el runbook de arriba asumía factura electrónica sin decirlo. **Se confirma: factura
electrónica.**

No es un detalle de configuración; cambia qué se imprime en el mostrador.

| | Factura electrónica ✅ | Documento POS electrónico |
|---|---|---|
| Datos de la clienta | Obligatorios (NIT/cédula) | No los pide |
| Ritmo del mostrador | Frena: hay que pedirlos | Pensado para la caja |
| El papel que se entrega | Comprobante; la factura va aparte | **ES el documento fiscal** |
| Dependencia de Siigo al vender | Ninguna (ADR-002) | El CUFE tiene que estar YA |

**La consecuencia que importa.** Con documento POS, el papel del momento de la venta tiene
que llevar CUFE y QR — o sea, la venta tendría que esperar a que Siigo responda, que es
exactamente lo que ADR-002 evita y lo que hace que el POS siga vendiendo sin señal. Con
factura electrónica ese conflicto no existe: la tirilla sale en el mostrador como
comprobante y la factura llega después.

### Cómo se comporta la tirilla con esta decisión

El encabezado del papel **cambia solo**, y sólo cuando hay algo real que amparar:

- Sin resolución DIAN o sin documento emitido → `COMPROBANTE DE VENTA · Documento interno ·
  no válido como factura`. Sin QR: un código en un papel que todavía no ampara nada lo haría
  parecer fiscal a simple vista.
- Con resolución **y** documento emitido → `FACTURA ELECTRÓNICA DE VENTA`, con su número, su
  CUFE y el QR de verificación.

Hacen falta las dos condiciones. Con resolución pero sin emitir, el papel todavía no ampara
nada.

### Lo que falta para cerrar el círculo (Fase 3)

1. **La cadena del QR.** La construye Siigo, no nosotros. Se guarda tal cual en
   `documentos_fiscales.qr_datos` (migración 0009). Mientras esté vacía, la tirilla arma la
   URL estándar del catálogo con el CUFE — es un respaldo razonable, pero si Siigo usa otro
   formato y no lo guardamos, el QR se sigue imprimiendo, sigue pareciendo correcto y no
   lleva a ninguna parte.
2. **La entrega de la factura.** `documentos_fiscales.pdf_url` existe desde el diseño y nadie
   la llena. Con factura electrónica, la clienta que dio sus datos tiene que recibirla — por
   correo desde Siigo o desde aquí, y eso hay que decidirlo.
3. **Qué pasa con quien NO da sus datos.** Es la mayoría en un mostrador. Hay que confirmar
   con el contador cómo se resuelve: consumidor final con un NIT genérico, o factura sólo a
   quien la pida. Esto no lo resuelve el software.
