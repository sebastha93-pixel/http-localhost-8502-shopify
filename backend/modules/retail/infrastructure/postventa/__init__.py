"""Adaptadores hacia el módulo de POSTVENTA.

Está en `infrastructure` y no en `application` porque Postventa es un sistema
de afuera desde el punto de vista de este módulo: tiene su propia base
(Supabase), su propio vocabulario y su propio ciclo de aprobación. Lo que vive
aquí es la traducción, y traducir es justo donde se inventan datos si nadie
mira.
"""
from backend.modules.retail.infrastructure.postventa.caso_devolucion import (
    TIPO as TIPO_CASO_DEVOLUCION,
    abrir_caso_postventa,
)

__all__ = ["TIPO_CASO_DEVOLUCION", "abrir_caso_postventa", "MANEJADORES"]

#  EL REGISTRO. Una sola tabla `tipo → manejador`, para que «qué sabe hacer el
#  drenador» se responda leyendo cinco líneas y no rastreando llamadas.
#
#  `emitir_documento_fiscal` ya tiene quien lo atienda (`emisor_factura`).
#  Con `RETAIL_FISCAL_MODO` apagado —el valor por defecto— no emite nada: el
#  manejador APLAZA el trabajo sin gastarle intentos, así que encenderlo es
#  cambiar una variable y lo que estaba en cola sale solo.
#
#  Lo que sigue SIN manejador: `emitir_nota_credito`. El drenador lo guarda
#  igual, sin gastarle intentos.
from backend.modules.retail.infrastructure.siigo.emisor_factura import (  # noqa: E402
    TIPO as TIPO_FACTURA,
    emitir_factura,
)

MANEJADORES = {
    TIPO_CASO_DEVOLUCION: abrir_caso_postventa,
    TIPO_FACTURA: emitir_factura,
}
