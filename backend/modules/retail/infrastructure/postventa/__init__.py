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
#  Lo que NO está aquí y se encola desde hoy: `emitir_factura` y
#  `emitir_nota_credito`. No es un olvido — los comprobantes de tienda (FL,
#  FV-6, FV-11, FV-12) no salen en `/document-types` de Siigo, así que
#  `POST /invoices` los rechaza. Es una gestión con Siigo, no código. Mientras
#  tanto el drenador los deja en la cola SIN gastarles intentos (ver
#  `drenar_outbox.py`), así que el día que se resuelva se emiten solos.
MANEJADORES = {
    TIPO_CASO_DEVOLUCION: abrir_caso_postventa,
}
