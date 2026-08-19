# Lo que respondió la cuenta de Siigo

Consultado el 2026-08-18 con `railway run --service backend`, o sea con las
credenciales cargadas en el proceso y sin que salieran de la infraestructura.
Sólo lectura: `GET /v1/document-types?type=FV` y `GET /v1/payment-types`.

No es documentación ni suposición. Es lo que la cuenta contestó.

## 1. Los comprobantes de tienda NO se pueden usar por API — confirmado

`/document-types?type=FV` devuelve **9 comprobantes**, y el campo `code` es el
NÚMERO, no el prefijo (`"1"`, no `"FV-1"`):

| code | id | consecutive | automatic_number | activo | nombre |
|---|---|---|---|---|---|
| 1 | 11810 | 65317 | **true** | sí | Factura Electrónica de Venta |
| 2 | 26954 | 4512 | true | sí | Proforma |
| 3 | 27152 | 2485 | true | sí | Factura electrónica de venta |
| 4 | 27153 | 1477 | true | sí | Factura electrónica de venta |
| 5 | 27154 | 648 | true | **sí** | Factura electrónica de venta |
| 7 | 29193 | 14 | true | sí | Documento de ingreso |
| 8 | 31431 | 1 | true | sí | Documento de ingreso |
| 9 | 31432 | 1 | true | sí | Documento de ingreso |
| 10 | 29077 | 10001 | false | **no** | Factura electrónica de venta |

**No aparecen FV-6 (29192), FV-11 (31433), FV-12 (31434) ni FL.** Los tres
primeros son los que `codigo/backend/services/tiendas.py` tiene anotados como
los prefijos de Arrayanes y de las dos cajas de Florida. FL es el de la tirilla
de la foto.

Eso confirma empíricamente lo que ese archivo ya había medido: los comprobantes
atados al punto de venta de Siigo **no salen** en `/document-types`, y por eso
`POST /invoices` los rechaza con *«The id cannot be used, you must verify the
document settings»*. No hay bandera que consultar — la señal es la ausencia.

**Consecuencia: el POS no puede quedarse con las resoluciones de tienda sin
antes reconfigurarlas en Siigo.** Es una gestión con Siigo, no código.

## 2. `automatic_number = true` en todos los emitibles

El número lo pone **Siigo**, no nosotros. Eso responde la pregunta que llevaba
varias sesiones abierta, y tiene una consecuencia concreta:

> El número que la tableta imprime en la tirilla **no es** el número de la
> factura.

Hoy el POS numera con su bloque de consecutivos (`FL-1537`…) y lo imprime. Si
Siigo asigna el suyo al emitir, hay dos números por venta. Las opciones son
imprimir la tirilla sin número fiscal y dejar que llegue después, o reimprimir.
No es un detalle de implementación: cambia lo que la clienta se lleva en la mano.

## 3. Dato aparte: FV-5 «Cambios» ya está ACTIVO

`codigo/backend/services/tiendas.py` dice *«FV-5 (id 27154, hoy inactivo)»* y
que el día que esté listo basta poner `SIIGO_DOC_FACTURA_CAMBIO=27154` en
Railway. **La cuenta lo devuelve como `active: true`.** Se activó en algún
momento y nadie movió la variable — o sea que el motor fiscal de postventa
sigue facturando los cambios con FV-1 pudiendo usar el comprobante correcto.

Es de otro módulo, pero vale la pena mirarlo.

## 4. Las formas de pago, con sus ids

25 activas de 36. Las que importan para el POS:

| Medio | id | Nombre en Siigo |
|---|---|---|
| Efectivo | **12243** | Caja general Florida |
| Datáfono | **12244** | Datafono Florida |
| **Addi** | **12245** | ADDI FLORIDA |
| **Sumas Pay** | **12218** | SUMAS PAY TIENDA |

Los tres primeros son **consecutivos** (12243, 12244, 12245): se dieron de alta
juntos, para el mismo punto de venta. Eso los hace inequívocos.

`SUMAS PAY TIENDA` (12218) y no `SUMAS PAY CREDITO 30 DIAS` (12217): el nombre
distingue el cobro en mostrador del crédito, que es otra cosa.

**Sin resolver, y a propósito:**

* **Wompi** — hay `8353 WOMPI` y `8844 WOMPI CREDITO UN DIA`. Ninguno dice
  «Florida» ni «tienda». Elegir mal imputa la venta a la cuenta contable
  equivocada, y ese error no revienta: sale en el balance.
* **Transferencia** — el candidato sería `2719 BANCOLOMBIA CUENTA DE AHORROS`,
  pero eso es la cuenta bancaria, no un medio de cobro en mostrador.

Otros que existen y pueden servir después: `12240 Devoluciones POS`,
`8298 ADDI CREDITO 30 DIAS` (el de la web, distinto del de tienda),
`8276 MERCADO PAGO`, `8274 EPAYCO`, `8275 PAY U`, `8353 WOMPI`.
Inactivos: `8277 NEQUI`, `10385 SISTECREDITO 60 DIAS`.

## Lo que hay que decidir ahora

1. **¿Siigo puede reconfigurar FL / FV-11 / FV-12 / FV-6 para que acepten
   documentos por API?** Si sí, el plan de quedarse con las resoluciones
   funciona. Si no, hay que pedir una resolución nueva o emitir con FV-1 y
   mezclar el canal.
2. **¿Qué se imprime en la tirilla mientras Siigo asigna el número?** Con
   `automatic_number = true` el número de la caja y el de la factura son
   distintos.
3. **¿Cuál Wompi?** `8353` o `8844`.
