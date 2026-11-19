"""Venta con envío a domicilio: lo que comparten quienes la tocan.

La prenda de una venta con envío no sale del estante de la tienda: sale de la
bodega de la tienda en línea. Por eso su factura —y la nota crédito si se
anula antes de despacharse— llevan la bodega de ESA ubicación y no la de la
tienda que cobró. Ver la migración 0042 y
`docs/superpowers/specs/2026-11-13-pedido-con-envio-design.md`.
"""
from __future__ import annotations

__all__ = ["CANAL_MOSTRADOR", "CANAL_ENVIO", "UBICACION_EN_LINEA",
           "SQL_BODEGA_DE_LA_VENTA", "SQL_DESPACHO_REQUIERE_ATENCION",
           "MINUTOS_PENDIENTE_SIN_SALIR"]

CANAL_MOSTRADOR = "mostrador"
CANAL_ENVIO = "envio"

#  De dónde sale lo que se vende con envío (migración 0042).
UBICACION_EN_LINEA = "bodega:en_linea"

#  La bodega de Siigo que le corresponde a una venta, para usar dentro de un
#  SELECT que tenga `retail.ventas v` y `retail.tiendas ti`. Una venta de
#  mostrador da EXACTAMENTE lo de siempre: la bodega de su tienda.
SQL_BODEGA_DE_LA_VENTA = f"""
    CASE WHEN v.canal = '{CANAL_ENVIO}'
         THEN (SELECT u.siigo_bodega_id FROM retail.ubicaciones u
                WHERE u.id = '{UBICACION_EN_LINEA}')
         ELSE ti.siigo_bodega_id END
"""

#  Cuánto puede quedarse un despacho «pendiente» antes de que se muestre como
#  problema. El trabajo de la cola lo pide a los segundos de cobrar; veinte
#  minutos sin salir ya no es normal.
MINUTOS_PENDIENTE_SIN_SALIR = 20

#  Un despacho que necesita que ALGUIEN haga algo, para usar con
#  `retail.despachos d`. Es la red de seguridad de la oficina: lo diga el
#  despacho (`no_creado`, un error anotado), lo diga la cola (el trabajo se
#  rindió) o lo diga el reloj (lleva demasiado rato sin pedirse). La lista de
#  la oficina y el aviso del tablero cuentan con esto mismo.
SQL_DESPACHO_REQUIERE_ATENCION = f"""
    (d.estado = 'no_creado'
     OR d.ultimo_error IS NOT NULL
     OR (d.estado = 'pendiente'
         AND d.creado_en < now() - interval '{MINUTOS_PENDIENTE_SIN_SALIR} minutes')
     OR EXISTS (SELECT 1 FROM retail.outbox o
                 WHERE o.agregado_id = d.venta_id AND o.estado = 'fallido'
                   AND o.tipo IN ('crear_despacho_melonn',
                                  'cancelar_despacho_melonn')))
"""
