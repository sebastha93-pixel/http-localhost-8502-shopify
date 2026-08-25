# La tirilla que MALE imprime HOY

Extraído de una tirilla física de Siigo Nube, tienda Florida, 14/08/2026.
**Es la fuente de verdad del formato fiscal**: lo que la DIAN ya aceptó, lo que
la clienta ya reconoce y lo que la contadora ya sabe leer. Cualquier diferencia
de nuestra tirilla contra ésta es una decisión que hay que poder defender.

## Lo que dice, tal cual

```
                    [logo MALE DENIM]
                   DIRTY JEANS S.A.S.
                   NIT: 901680460-1
      Dir.: CALLE 71 65 150 SEGUNDA ETAPA LC 221
              Medellín - tel.3122851520

              Factura electrónica de venta
                     No. FL-1536
 Fecha generación:              14/08/2026, 15:4x
 Fecha expedición:              14/08/2026, 15:4x

 Cliente:      ELI GONZALEZ
 C.C / NIT:    1037368561-6
 Dirección:    CL 50 A  86- 450 APTO 513 URB CALAZANS
               AZUL BR CALAZANS
 Teléfono:     3117910110
 Vendedor:     ASESOR FLORIDA

 t.  Cant.   Vr. Unit        Valor        ID
 1   1 UNI   149.900,00      149.900,00   A
 16520-1T10JEAN SKINNY GRIS, STRETCH, UN BOTÓN,
 CINTURA AJUSTADA, BÁSICO CON DESGASTE / 16520-1T10
 2   1 UNI   1.000,00        1.000,00     A
 BOLSA MALE PEQUEÑA / 5353

                     Impuestos
 D    %          Base            Impuesto
 A    19,00      126.806,73      24.093,2x
                A=IVA 19%

                              Total Ítems: 2
 Total bruto:                     126.806,7x
 Descuentos:                            0,0x
 Subtotal:                        126.806,7x
 IVA 19%:                          24.093,2x

 Total a pagar:                   150.900,00

 Formas de pago:
 Contado
 Métodos de pago:
 Tarjetas:                        150.900,00

                        CUFE
 db8e55e25ed3610232b02390697c4515ec50b6204e93023c61…
 …d7b7e3979bebb2af75af4cb752a0a4890d3851393c1f
                      [QR]

 Responsable de IVA - Actividad económica 4782.
 A esta factura de venta aplican las normas relativas a la letra de
 cambio (artículo 5 Ley 1231 de 2008). Con esta el Comprador declara
 haber recibido real y materialmente las mercancías o prestación de
 servicios descritos en este título - Valor.

 Número Autorización 18764108303738 aprobado en 20260410
 prefijo FL desde el número 1 al 10000  Vigencia: 24 meses

 Fabricante de software y proveedor tecnológico:
 Siigo S.A.S. - Nit: 830.048.145-8.
 Nombre del software: Siigo Nube
 Factura electrónica: relacionado en el XML
```

## LO QUE CAMBIA RESPECTO A LO QUE TENÍAMOS

### 1. «Subtotal» es ANTES de IVA — y nosotros lo usábamos al revés

Nuestra tirilla imprimía:

```
Subtotal        $169.900     ← el total CON IVA
Base gravable   $142.773,11
IVA incluido     $27.126,89
TOTAL           $169.900
```

La real:

```
Total bruto     126.806,73   ← base, SIN IVA
Descuentos            0,00   ← el descuento, SIN IVA
Subtotal        126.806,73   ← base después de descuento, SIN IVA
IVA 19%          24.093,27
Total a pagar   150.900,00
```

No es un nombre distinto: es **la misma palabra significando dos cosas** en
papeles de la misma tienda. Una clienta que compare dos tirillas, o la
contadora que cuadre el día, leen «Subtotal» y encuentran números que no
casan. Se adopta el de Siigo.

El cálculo NO cambia —el precio de vitrina sigue mandando y el IVA se sigue
derivando por línea (INV-V12)—; cambia cómo se presenta.

### 2. EL PREFIJO REAL ES `FL`, NO `FV`

La factura es `FL-1536` y la autorización dice **«prefijo FL desde el número 1
al 10000»**. Nuestras cajas están sembradas con `FV-20`. Emitir con un prefijo
que la resolución no ampara es un documento rechazado por la DIAN.

Ojo además con el rango: **1 al 10000**, y ya van por 1536.

### 3. Datos de resolución que hacen falta para emitir

| Dato | Valor |
|---|---|
| Número de autorización | 18764108303738 |
| Aprobada en | 2026-04-10 |
| Prefijo | FL |
| Rango | 1 – 10000 |
| Vigencia | 24 meses |
| Actividad económica | 4782 |
| Régimen | Responsable de IVA |

### 4. Datos reales de la tienda (los nuestros eran de relleno)

| Campo | Teníamos | Real |
|---|---|---|
| Razón social | Dirty Jeans S.A.S. | ✔ correcto |
| NIT | 900000000-0 | **901680460-1** |
| Dirección | Cra 43A #1-50, Medellín | **CALLE 71 65 150 SEGUNDA ETAPA LC 221** |
| Teléfono | (604) 000 0000 | **3122851520** |

### 5. Lo que la factura pide del cliente y nosotros NO capturamos

* **Dirección.** La imprime («CL 50 A 86-450 APTO 513 URB CALAZANS») y nuestro
  alta de clienta no la pide. Sin ella la factura electrónica sale incompleta.
* **Dígito de verificación**: `1037368561-6`, no `1037368561`.

### 6. «Vendedor» no es la cajera

Imprime `Vendedor: ASESOR FLORIDA`. Es el asesor comercial al que se le abona
la venta, y puede no ser quien opera la caja. Nosotros sólo tenemos «Atendió».

### 7. Siigo distingue FORMA de pago y MÉTODO de pago

```
Formas de pago:   Contado          ← contado / crédito
Métodos de pago:  Tarjetas         ← efectivo / tarjetas / transferencia…
```

Nuestro `medios_pago.siigo_forma_pago_id` mezcla los dos conceptos. Hay que
confirmar contra el discovery cuál de los dos es ese id — porque si es el de
«forma», los ids por tienda que tenemos no son lo que creemos.

### 8. Se cobran líneas que no son prendas

`BOLSA MALE PEQUEÑA / 5353` a $1.000. La bolsa es un artículo con código, no un
recargo. El POS tiene que poder añadirla — hoy sólo lista prendas del catálogo.

### 9. Detalles de formato

* Dos fechas: **generación** y **expedición**.
* `Total Ítems: 2` — se imprime el conteo.
* La línea lleva el código **antes** de la descripción y otra vez al final:
  `16520-1T10JEAN SKINNY GRIS… / 16520-1T10`.
* Columna `ID` con la letra del impuesto (`A`) y su leyenda (`A=IVA 19%`), más
  un bloque «Impuestos» con base e impuesto por tarifa. Con una sola tarifa
  parece redundante; con dos, es la única forma de cuadrarlo.
* Importes con **centavos** y coma decimal: `126.806,73`.
* El bloque del fabricante de software dice **Siigo S.A.S.** Mientras emitamos
  A TRAVÉS de Siigo ese texto sigue siendo correcto — es un argumento a favor
  de no emitir directo a la DIAN.
