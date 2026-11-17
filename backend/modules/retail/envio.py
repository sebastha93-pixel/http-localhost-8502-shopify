"""Venta con envío a domicilio: lo que comparten quienes la tocan.

La prenda de una venta con envío no sale del estante de la tienda: sale de la
bodega de la tienda en línea. Por eso su factura —y la nota crédito si se
anula antes de despacharse— llevan la bodega de ESA ubicación y no la de la
tienda que cobró. Ver la migración 0042 y
`docs/superpowers/specs/2026-11-13-pedido-con-envio-design.md`.
"""
from __future__ import annotations

__all__ = ["CANAL_MOSTRADOR", "CANAL_ENVIO", "UBICACION_EN_LINEA",
           "SQL_BODEGA_DE_LA_VENTA"]

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
