# Pedido con envío desde la caja — plan de construcción

Diseño: `docs/superpowers/specs/2026-11-13-pedido-con-envio-design.md` (aprobado
el 2026-11-17). Rama: `feat/pos-pedido-con-envio`.

Regla de todo el plan: **cada etapa se puede publicar sola y ninguna cambia una
venta de mostrador.** Todo lo nuevo cuelga de `canal = 'envio'`, que nadie puede
elegir hasta la etapa 5.

Rutas: `R` = `backend/modules/retail/`, `F` = `frontend/`.

## Etapa 0 — Lo que sólo se sabe probando en Melonn — HECHA, 2026-11-17

Pedido `PRUEBA-POS-1` (Melonn `M1794944965087455`): 1 unidad de 25626-1T16,
creado a las 14:49:25 y cancelado a las 14:50:28. No despachó ni facturó.
Script: `~/Proyectos/MALE-DENIM-OS/auditoria-railway-oct2026/prueba_melonn_pos.py`.

- [x] **Shopify SÍ baja su existencia sola.** Antes: Melonn 10, Shopify 10. A
      los 28 s de crearlo Melonn decía 9; a los 45 s Shopify decía 9 (en la
      ubicación «Melonn Sabaneta»). Al cancelar, los dos volvieron a 10 en
      menos de 40 s. **El POS no tiene que tocar el inventario de Shopify.**
- [x] **`external_order_id` es obligatorio** (400 «body must have required
      property 'external_order_id'»). Se manda numérico y que no sea un pedido
      de Shopify (ver la nota de `shopify_enricher` en la etapa 3).
- [x] Crear responde `201` con `sell_order.internal_order_number` (el M-id),
      `external_order_number` y `external_order_id`.
- [x] El `GET sell-orders/{número}` de un pedido creado por API SÍ trae el
      detalle: `line_items`, `shipping_info` (Melonn normaliza la dirección),
      `buyer`, `melonn_tracking_link`, paquetes con promesas (despacho ese
      mismo día 11 p. m., entrega a los 2 días) y `payment_on_delivery_amount`
      nulo (prepagado).
- [x] **Las etiquetas no vuelven** (`tags: []` aunque se mandaron `POS` y
      `PRUEBA`): no sirven para reconocer un pedido del POS. Se reconoce por
      el número.
- [x] **«Retenido» no se nota en el estado:** quedó en `2 · All items reserved
      - ready for fulfillment` a los 40 s, igual que uno normal. No contar con
      la retención para ganar tiempo: un pedido creado puede empezar a
      alistarse ya.
- [x] Cancelar (`request-cancellation`) → `200` y estado `15 · Canceled` en
      menos de 35 s.
- [ ] Si Melonn le avisa algo a la clienta (SMS/correo): no se pudo ver desde
      aquí. Se mira en el pedido real de la etapa 5.

## Etapa 1 — Cimientos en el servidor (sin cambio visible) — HECHA en la rama, 2026-11-17

770 pruebas del POS pasan (10 nuevas en `test_venta_con_envio.py`). **PUBLICADA el 2026-11-17 a las 11:28 p. m.** (migración 0042 aplicada con las
tiendas cerradas, PR #141 fusionado, despliegue correcto). Primera venta con el código nuevo:
FERPOS-2538 → TPFE-1519, emitida en 5 s al primer intento. Las 1.462 ventas son `mostrador` y
ninguna tienda tiene `vende_con_envio`.

Migración aditiva (aplicarla en producción antes de fusionar):

- [x] `retail.ventas.canal text NOT NULL DEFAULT 'mostrador' CHECK (canal IN
      ('mostrador','envio'))`. NO se reutiliza `origen`: ya significa en línea /
      fuera de línea y tiene su CHECK (`0030`). Actualizar `tablas.py`.
- [x] `retail.tiendas.vende_con_envio boolean NOT NULL DEFAULT false`.
- [x] Ubicación `bodega:en_linea` (`tipo='bodega'`, `siigo_bodega_id=32`, sin
      tienda). La sincronización horaria sólo toca `tipo='tienda'`.
- [x] Tabla `retail.despachos`: `venta_id` (PK, FK), `estado` (`pendiente`,
      `en_melonn`, `despachado`, `entregado`, `no_creado`, `cancelado`),
      destinatario, teléfono, dirección, complemento, ciudad, departamento,
      `melonn_numero`, `melonn_estado`, `seguimiento_url`, `ultimo_error`,
      `resuelto_por`, `resolucion` (texto: cómo se le devolvió la plata),
      marcas de tiempo. Sin datos de más: lo justo para despachar.

Código:

- [x] `VentaEntrada` acepta `canal` y `entrega`; `_armar` exige que la tienda
      tenga `vende_con_envio` y que venga la entrega completa cuando
      `canal='envio'`; rechaza `canal='envio'` con `origen='fuera_de_linea'`.
- [x] `CerrarVenta`: con `canal='envio'` la salida de inventario va a
      `bodega:en_linea` (queda el asiento, así anular/devolver saben de dónde
      salió) y se guarda la fila de `despachos` en la misma transacción.
- [x] `emisor_factura._emitir/_armar`: la bodega de la factura es la de la
      ubicación de donde salió la venta (32 para envío), no siempre la de la
      tienda. Comprobante, vendedor, centro de costos y pagos: los de la tienda.
      La observación conserva la marca `POS {numero} · {id}` y añade «Entrega a
      domicilio».
- [x] Nota crédito de la ANULACIÓN (`emisor_nota_credito.py`): usa la bodega
      de donde salió la prenda (32 si era con envío). La del CAMBIO
      (`emisor_nota_credito_cambio.py`) se deja como está a propósito: ahí la
      clienta trae la prenda a una tienda y entra al inventario de ESA tienda.
- [x] `sincronizar_inventario.py:164-171`: las ventas `canal='envio'` sin
      facturar NO se le restan al inventario de la tienda.
- [x] `/caja/contexto` y `ContextoCaja` devuelven `vende_con_envio`.

Pruebas (base local, `SiigoFalso`):

- [x] Una venta de mostrador produce exactamente la misma factura que hoy
      (misma bodega, mismo cuerpo) — la prueba que protege lo que ya funciona.
- [x] Una venta con envío: factura con bodega 32 en todas las líneas, centro de
      costos y comprobante de la tienda; el inventario de la tienda no se
      mueve; queda la fila de despacho.
- [x] Tienda sin `vende_con_envio` → 400. Sin dirección → 400. Fuera de línea →
      400.
- [x] Anular una venta con envío en el mismo turno: nota crédito con bodega 32.
- [x] La sincronización no descuenta de la tienda una venta con envío pendiente.

## Etapa 2 — Catálogo y precio de la web — HECHA en la rama `feat/pos-pedido-con-envio-2`, 2026-11-17

785 pruebas del POS pasan (15 nuevas de esta etapa, más 6 del lector de Shopify). Probado contra la
tienda real con la llave del servidor: consultar 1,3 s, buscar 0,4 s. Notas de lo que quedó:
la existencia es la de la sucursal de Shopify que refleja a Melonn (`gid://shopify/Location/99023749440`,
«Melonn Sabaneta»), no la suma de sucursales; un precio enviado POR ENCIMA del de la web se rechaza
(«el precio cambió»); la prenda nueva entra `activa=false` con el precio de lista.

- [x] `infrastructure/tienda_en_linea.py`: buscar en Shopify por texto o SKU →
      variantes con `sku`, título, talla, `price` (lo que cobra la web HOY),
      `compareAtPrice`, `inventoryQuantity`. Reutiliza
      `backend.services.clientes._shopify_graphql`. Nunca revienta: sin Shopify
      devuelve vacío y la pantalla lo dice.
- [x] `GET /catalogo/en-linea?q=`: sólo para tiendas con `vende_con_envio`.
- [x] En `_armar`, con `canal='envio'`: el precio de referencia es el de la web
      en ese momento (se vuelve a consultar al cobrar, junto con la
      existencia), no `variantes.precio_con_iva`; no cuenta contra el tope de
      la cajera; un descuento adicional de ella sí. Las promociones de tienda
      (`retail.promociones`) no se aplican.
- [x] Si la prenda no está en `retail.variantes`, se crea al venderla (SKU,
      referencia, talla, nombre, precio) como hace `sincronizar_inventario`.
- [x] Sin existencia en Shopify al cobrar → 400 con mensaje para la vendedora.

Pruebas: precio de promoción de la web aceptado sin gastar tope; descuento
encima sí lo gasta; promoción de tienda ignorada; prenda nueva se crea; sin
existencia se rechaza; Shopify caído → mensaje claro, no un 500.

## Etapa 3 — El despacho en Melonn — HECHA en la rama `feat/pos-pedido-con-envio-3`, 2026-11-18

(La etapa 2 se publicó el 2026-11-18, PR #142.)

- [x] `melonn/despacho.py` · `MelonnIO`: `leer_pedido` (404 → `None`; lo demás
      lanza), `crear_pedido` de UN intento y `pedir_cancelacion`. Lectura
      probada contra el Melonn real (PRUEBA-POS-1 cancelado y un número que no
      existe).
- [x] Trabajo `crear_despacho_melonn`, encolado al cerrar la venta en la misma
      transacción. Pregunta antes de crear; un envío sin respuesta espera 45
      min sólo preguntando (la lección de Siigo del 18-nov); rechazo →
      `no_creado` con el motivo; sin cuota → espera sin gastar intentos.
- [x] Prepagado y D2C; `external_order_id` = `999` + 10 dígitos del número.
- [x] `melonn_client._normalizar`: `origen="pos"` y `external_order_id` vacío;
      el detalle del POS se pide sin «#»; `cartera_cod._numeros_orden` ignora
      los números de caja.
- [x] Cancelar. Desde la caja (turno abierto) y desde la oficina
      (`POST /despachos/{venta}/cancelar`, administrador, turno cerrado o no,
      sin tocar el arqueo, con `resolucion`). ANTES de anular se le pide a
      Melonn que no despache: si ya salió, no contesta o no deja, la venta NO
      se anula. Después, `cancelar_despacho_melonn` verifica en la cola que
      quedó cancelado (y cancela el que Melonn haya creado tarde).
- [x] `GET /despachos`: la lista de la oficina, lo que hay que resolver primero.

Decisiones tomadas al construir (distintas de lo escrito arriba):

- **El estado no sale del tablero de logística del OS** sino de preguntarle a
  Melonn pedido por pedido cada 30 min (`refrescar_despachos`, tras cada
  pasada de la cola). El tablero deja por fuera entregados y cancelados, que
  son justo los finales que importan. Cuesta unas pocas peticiones al día.
- **La caja también puede anular** una venta con envío de su turno (no sólo
  la oficina), con la misma comprobación en Melonn.
- **Si Melonn cancela por su cuenta**, el despacho vuelve a `no_creado` con
  el aviso: la clienta pagó y no le va a llegar.
- No hay «reintentar despacho» tras un `no_creado` (p. ej. dirección mal
  escrita): hoy la salida es cancelar y volver a vender. Verlo en la etapa 4.

Pruebas: `tests/retail/integracion/test_despacho_melonn.py` (36) y
`tests/test_melonn_pedidos_del_pos.py` (5). `tests/retail`: 831 pasan.

Pendiente de la etapa 5 (pedido real): confirmar contra Melonn el `POST` sin
retención y la cancelación, que aquí sólo corrieron contra el falso.

## Etapa 4 — Pantallas — HECHA en la rama `feat/pos-pedido-con-envio-4`, 2026-11-19

(La etapa 3 se publicó el 2026-11-18, PR #145.)

- [x] Venta: «En la tienda / Con envío a domicilio» (sólo si la tienda tiene
      `vende_con_envio`); bloqueado con prendas en el carrito. Con envío el
      buscador consulta la tienda en línea (`catalogoEnLinea`), la talla
      agotada no se puede tocar y no se agrega más de lo disponible; sin
      promociones de tienda.
- [x] Cobro: bloque de entrega arriba (`bloque-entrega.tsx`); sin entrega
      completa no se confirma. Con envío no hay cola fuera de línea: sin red
      se avisa y se reintenta con el mismo `venta_id` (no duplica).
- [x] Tirilla: «ENTREGA A DOMICILIO · sin costo de envío», quién recibe y la
      dirección (sin el celular). Probada imprimiendo a PDF con Chrome.
- [x] Panel, cierre y ventas del turno: etiqueta «Shopify · <estado del
      despacho>»; lo que ya salió no se ofrece para anular.
- [x] Tablero: «N con envío ($…)» por tienda y aviso arriba de pedidos por
      resolver. Pantalla nueva `/pos/despachos` («Envíos» en el menú, sólo
      admin) con cancelar (motivo + cómo se devolvió la plata) y reintentar.
- [x] Probado en una demo local a 1024×768 (iPad apaisado), con Shopify y
      Melonn simulados: buscar, agregar, tope de existencia, entrega, cobro,
      tirilla, la cola creando el pedido, la lista de la oficina y cancelar.

Encontrado en la demo y corregido: la tasa de IVA de lo de la tienda en
línea iba como `0.19` y la caja decía «IVA incluido $303» en una prenda de
$159.900; el precio tachado partía la referencia en la tarjeta angosta.

## Etapa 5 — Pedido real y encendido

- [ ] Con todo publicado y la Feria AÚN apagada: prender `vende_con_envio` en
      una tienda de prueba o sólo para el administrador, y hacer un pedido real
      de punta a punta (prenda barata, dirección de la oficina) con Sebastián.
      Verificar: factura TPFE con bodega MELONN, pedido en Melonn, estado en el
      POS, tirilla, tablero.
- [ ] Prender la Feria. Escribirles el paso a paso a las vendedoras.
- [ ] Barrer al día siguiente: ventas con envío sin despacho, facturas sin
      emitir.

## Notas

- Comprobado (ver el diseño): Siigo factura contra la bodega 32 sin saldo; el
  método de envío es `MEL-15`; el SKU de Melonn es el de MALE; bodega `MED-2`.
- Revisión de «quién más lee los pedidos de Melonn en el OS» (2026-11-17):
  nada se rompe con un pedido del POS mientras sea prepagado. Tablero de
  logística, finanzas y conciliación sólo suman plata de contra entrega; el
  webhook, el archivo y el histórico cruzan por el número como texto. Ningún
  mensaje a la clienta sale por cambios de estado de Melonn. Los pedidos del
  POS aparecerán en logística como un despacho más (sin tienda); decidir en la
  etapa 4 si se muestran como canal propio.
- Mapa del flujo de venta del POS (2026-11-17), lo que más pesa: `origen` ya
  está ocupado (en línea / fuera de línea); la bodega va por factura completa,
  no por línea; las notas crédito pisan la bodega con la de la tienda;
  `sincronizar_inventario.py:164-171` resta de la tienda las ventas sin
  facturar; `permite_stock_negativo` no lo lee nadie (el stock siempre puede
  quedar negativo); el buscador sólo muestra lo que tiene fila de stock en la
  tienda; `outbox.encolar` fija 8 intentos y sólo drena el líder.
