# Pedido con envío desde la caja — diseño

Fecha: 2026-11-13 · Pedido por: Sebastián · Estado: **aprobado por Sebastián el 2026-11-17**

## Para qué

En la feria (Caja Feria, iPad, hasta enero) las vendedoras pierden ventas cuando
la clienta quiere una prenda o una talla que no está en el stand pero sí en la
tienda en línea. Se quiere que la vendedora pueda **vender ahí mismo lo que está
disponible en Shopify y que le llegue a la clienta a su casa**.

Lo que Sebastián definió, en sus palabras:

- La clienta **paga en el datáfono de la feria**.
- La factura **es la misma de Wein** (TPFE), no la de la tienda en línea.
- La venta **debe quedar registrada en el POS, marcada como Shopify**.
- **El envío es gratis.**
- La feria va **hasta enero**.

## Metas

1. Desde la caja, vender una prenda disponible en la tienda en línea con entrega
   a domicilio, cobrando como cualquier venta de la caja.
2. Que la factura salga por el comprobante de la tienda que vende (en la feria,
   TPFE: pago Wompi, centro de costos PLAZA DE WEIN) y descuente la prenda de la
   bodega **MELONN** de Siigo, que es donde está físicamente.
3. Que Melonn reciba el pedido y lo despache, sin que nadie lo vuelva a digitar.
4. Que la venta se vea en el POS y en el tablero como venta de esa tienda,
   **distinguible** como «Shopify / con envío», con el estado de su despacho.

## Lo que NO es

- No es un carrito mezclado: una venta es **toda** de mostrador o **toda** con
  envío. Si la clienta se lleva algo del stand y pide otra cosa a domicilio, son
  dos ventas. (Decisión mía para la primera versión; se puede abrir después.)
- No cobra envío ni lo factura: es gratis.
- No reemplaza el flujo de la tienda en línea ni toca MarketHub.
- No maneja contra entrega: siempre está pagado antes de crear el despacho.

## Lo que haría de esto un fracaso aunque «funcione»

- **Dos facturas por la misma venta.** Pasa si el pedido se crea en Shopify:
  MarketHub (el conector que factura la web) factura todo pedido de Shopify como
  FV-1. Verificado el 13-nov con pedidos borrador reales (#65279 → FV-1-68427,
  pago «BANCOLOMBIA CUENTA DE AHORROS»). **Por eso el pedido NO se crea en
  Shopify: va directo a Melonn.**
- **Cobrar y que no se despache**, sin que nadie se entere. Un despacho que
  Melonn no aceptó tiene que quedar a la vista, con su motivo, hasta resolverse.
- **Vender lo que no hay.** La disponibilidad sale de Shopify, no de la bodega
  MELONN de Siigo: el 13-nov, para 25626-1T6, Siigo decía 3 y Shopify y Melonn
  decían 0.
- **Descontar del stand** una prenda que nunca estuvo ahí.

## Restricciones

- Toca la emisión de facturas, que está en producción en tres tiendas. Nada de
  lo que hoy factura puede cambiar de comportamiento: todo lo nuevo va detrás de
  «esta venta es con envío».
- API de Melonn: 1 petición por segundo y cuota diaria compartida con el resto
  del OS (`src/melonn_client.py`). Un 429 «Limit Exceeded» no se arregla
  reintentando.
- La caja de la feria es un iPad; la pantalla tiene que servir ahí.
- Sin datos de la clienta en el tablero (se mantiene la regla).
- Migraciones aditivas, aplicadas en producción antes de fusionar.

## Caminos considerados

| | Cómo | Por qué sí / por qué no |
|---|---|---|
| **A. El POS factura y crea el pedido directo en Melonn** (elegido) | Venta en el POS marcada «con envío»; factura TPFE con bodega MELONN; el POS llama `POST /sell-orders` de Melonn. | Una sola factura, la de Wein. Queda en el POS. Verificado que la API lo permite. Más desarrollo. |
| B. Pedido borrador en Shopify marcado como pagado | Sin desarrollo; Melonn lo despacha como pedido web. | MarketHub lo factura como FV-1 con pago «Bancolombia»: no es la factura de Wein, no queda en el POS. Descartado por lo que pidió Sebastián. |
| C. El POS factura y el pedido se crea en Shopify | Reutiliza el flujo web hacia Melonn. | Doble factura (TPFE + FV-1). Sólo serviría si MarketHub pudiera saltarse pedidos, y no lo administramos. Descartado. |

Sebastián no eligió entre A y C en esos términos; pidió el resultado (factura de
Wein, registrado en el POS, marcado Shopify) y A es el único que lo da sin doble
factura. Es mi decisión técnica.

## Diseño

### Lo que ve la vendedora

1. En **Venta**, un interruptor **«Con envío a domicilio»** (sólo en las tiendas
   que lo tengan habilitado; arranca con la Feria).
2. Con el interruptor puesto, el buscador busca en la **tienda en línea**:
   muestra prenda, tallas, precio de la web y cuántas hay disponibles. Lo que no
   tiene existencia en Shopify no se puede agregar.
3. Al cobrar pide, además de la clienta (nombre, cédula, celular, correo, como
   hoy), la **entrega**: quién recibe, celular, dirección, complemento, ciudad y
   departamento. Todo obligatorio salvo el complemento.
4. Cobra con los medios de la caja (datáfono de la feria, efectivo, Addi…),
   igual que hoy. Descuentos y topes, igual que hoy.
5. La tirilla dice **«Entrega a domicilio»**, la dirección y «sin costo de
   envío».
6. En el Panel y en la lista de ventas la venta lleva la marca **Shopify** y el
   estado del despacho: *por enviar a Melonn → en Melonn → despachado →
   entregado*, o *no se pudo crear* con el motivo.

### Lo que pasa por debajo

- **La venta** se guarda con un canal nuevo (`mostrador` por defecto, `envio`
  para éstas) y sus datos de entrega aparte.
- **Inventario del POS:** no descuenta de la ubicación de la tienda. La prenda
  sale de una ubicación propia de la bodega en línea (no bloquea por saldo: la
  verdad de esa existencia es Shopify).
- **Catálogo:** la prenda puede no existir todavía en `retail.variantes` (el POS
  sólo carga lo que tiene existencia en tiendas). Se crea al venderla, con el
  SKU, nombre y precio de la web.
- **Factura:** el emisor de siempre, con la bodega de las líneas = MELONN (32)
  en vez de la de la tienda. Comprobante, vendedor, centro de costos y formas de
  pago: los de la tienda que vende. La observación añade «Entrega a domicilio».
- **Despacho:** un trabajo en la cola que ya existe (la misma mecánica de la
  factura: se intenta, se reintenta, queda a la vista si falla) llama a Melonn:
  `POST /sell-orders` con `external_order_number` = número de la venta del POS
  (`FERPOS-12`), `line_items` por SKU, `shipping_info`, `buyer`, etiquetas
  `POS` y la tienda. El número del POS es la llave de idempotencia: antes de
  reenviar se pregunta a Melonn si ya existe.
- **Estado del despacho:** se actualiza con lo que el OS ya recibe de Melonn
  (webhooks y barrido), cruzando por `external_order_number`.
- **Anular:** mientras Melonn no lo haya despachado, anular la venta pide la
  cancelación en Melonn (`request-cancellation`) y sigue el camino normal de
  anulación (nota crédito). Ya despachado, no se anula: se maneja como un cambio
  o una devolución.
- **Tablero:** por tienda, cuántas ventas y cuánta plata fueron «con envío»; y
  un aviso si hay despachos que no se pudieron crear.

### Orden: primero se cobra, después se pide el despacho

La venta se cierra y se factura aunque Melonn esté caído; el despacho queda en
cola. Lo contrario (pedir a Melonn antes de cobrar) dejaría despachos sin pago
si la clienta se arrepiente en el datáfono. El riesgo que queda —Melonn rechaza
por falta de existencia después de cobrar— se reduce verificando la existencia
en Shopify al agregar y otra vez al cobrar, y queda visible como «no se pudo
crear» para que alguien llame a la clienta.

## Hechos verificados (13-nov-2026)

- `POST /sell-orders` «Create D2C order», `request-cancellation` y `GET /stock`
  existen en la API de Melonn (colección pública «Melonn sellers API»).
- El SKU de Melonn es el de MALE (`25626-1T6`). Bodega `MED-2`. Métodos de envío
  vistos en pedidos reales: `FP-5`, `MEL-15`.
- El OS ya tiene llave de Melonn y cliente con control de cuota
  (`src/melonn_client.py`); hoy sólo lee y libera despachos, nunca ha creado uno.
- El POS ya consulta precios en Shopify
  (`infrastructure/precios_tienda_en_linea.py`).
- Facturar desde el POS con una bodega distinta a la de la tienda es un
  parámetro que el armado de la factura ya recibe (`bodega_id`).

## Lo que falta por comprobar (antes o durante la construcción)

1. **Qué método de envío usar** (`shipping_method_code`) para un pedido pagado a
   domicilio, y si depende de la ciudad. Se mira en los pedidos web recientes.
2. **Que Shopify baje su existencia** cuando Melonn recibe un pedido que no vino
   de Shopify. Si no baja sola, el POS tiene que ajustarla, o la web vendería la
   misma prenda.
3. **Qué le avisa Melonn a la clienta** (guía, seguimiento) en un pedido creado
   por API, y si hace falta que el POS le mande el enlace.
4. **Que Siigo acepte facturar contra la bodega MELONN (32) cuando su saldo
   ahí está en cero o mal** (Siigo va desfasado: 3 contra 0 real). Se prueba
   con una factura sin timbrar (`RETAIL_FISCAL_MODO=prueba`). Si Siigo bloquea
   por saldo, hace falta un plan B antes de construir lo demás.
5. **Que un pedido `FERPOS-n` en Melonn no rompa lo que el OS ya hace con los
   pedidos de Melonn** (barrido, webhook, conciliación, cartera COD, archivo):
   hoy todos asumen que un pedido de Melonn viene de Shopify. Se revisa leyendo
   el código; donde haga falta, se filtra por la etiqueta `POS`.
6. **Un pedido real de punta a punta** antes de soltarlo a las vendedoras: una
   prenda barata, a una dirección de la oficina, con Sebastián enterado. Crea un
   despacho de verdad y una factura de verdad. Los puntos 2 y 3 sólo se
   responden con este pedido, así que va TEMPRANO, no al final.

## Comprobado el 2026-11-17 (sólo lectura)

- **Siigo sí factura contra la bodega MELONN sin saldo:** 94 productos tienen
  hoy saldo NEGATIVO ahí (p. ej. 95614-1T8 en −21). El punto 4 de arriba queda
  resuelto: no hace falta plan B.
- **Método de envío:** `MEL-15` «Estándar (Local y Nacional)» es el de casi
  todos los pedidos web pagados (54 de 69 en los 200 más recientes). Es el que
  usa el POS. Los otros vistos: `FP-5` siguiente día hábil local, `FP-4` mismo
  día hábil local, `MEL-49` B2B.
- La API de Melonn devolvió un HTTP 500 pasajero en una de tres lecturas: el
  trabajo de despacho tiene que tratar el 5xx como «no sé si se creó» y
  preguntar antes de reenviar.

## Lo que ya responde el código (revisión del 13-nov)

- Preguntarle a Melonn si un pedido ya existe: `GET sell-orders/{número}`
  funciona (`refrescar_un_pedido` en `src/melonn_client.py`).
- El `_post` de ese cliente reintenta solo ante un timeout: crear el pedido
  necesita su propia llamada de UN intento, o puede duplicarlo.
- `construir_factura` recibe `bodega_id`, pero `emisor_factura._armar` siempre
  le pasa la de la tienda: ahí va el cambio.
- `sincronizar_inventario.py` sólo toca ubicaciones `tipo = 'tienda'`: una
  ubicación de la bodega en línea queda a salvo de la sincronización horaria.
- La anulación normal se niega si el turno ya cerró (`anular_venta.py`, INV-V11)
  y su nota crédito usa la bodega de la tienda (`emisor_nota_credito.py`), igual
  que la del cambio (`emisor_nota_credito_cambio.py`). Ninguna sirve tal cual
  para una prenda que nunca salió de Melonn.

## Lo que Sebastián decidió el 2026-11-17 (aceptó las dos propuestas)

1. **Si ya se cobró y Melonn no puede despachar:**
   - Lo resuelve la **oficina**, no la vendedora, desde una lista de «pedidos
     que no se pudieron despachar».
   - Primero se le ofrece a la clienta **otra talla u otra prenda**; si no
     quiere, se le **devuelve la plata** por transferencia o reversando el
     cobro en Wompi (eso se hace por fuera del POS; el POS registra que se
     devolvió y por dónde).
   - El POS emite la **nota crédito contra la bodega MELONN**, sin mover el
     inventario de la tienda. Tiene que poder hacerse con el turno ya cerrado:
     es un flujo propio («cancelar pedido con envío»), no la anulación normal.
2. **Precio y descuentos:** el pedido con envío lleva **el mismo precio que
   vería la clienta comprando en la web ese día** (el de promoción si la web
   está en promoción), **sin sumarle las promociones de las tiendas** (segunda
   prenda, pañoleta). Ese precio no cuenta como descuento de la cajera contra
   su tope; un descuento adicional que ella ponga encima, sí.

## Lo que queda a criterio de quien construye

- Nombres de tablas y columnas, y cómo partir las migraciones.
- La forma exacta del buscador en línea (cuántos resultados, caché).
- Cómo se pinta el estado del despacho en cada pantalla.
- El orden de los cortes, siempre que el primero que llegue a producción no
  cambie nada de las ventas de mostrador.

## Decisiones mías que Sebastián puede cambiar

- Una venta es toda de mostrador o toda con envío.
- Arranca habilitado sólo en la Feria; Florida y Arrayanes se prenden con un
  ajuste, sin desarrollo.
- Primero se cobra, después se pide el despacho.
- Ya despachado no se anula: va por cambios/devoluciones.
