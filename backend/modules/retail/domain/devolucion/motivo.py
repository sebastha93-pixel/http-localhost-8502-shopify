"""Por qué vuelve la prenda.

CERRADO Y NO TEXTO LIBRE, a propósito. Un campo abierto aquí se llena de
«cambio», «devolución» y «la señora no quiso», que describen el trámite y no
la causa. Los cuatro valores del handoff sí separan cosas que se arreglan en
sitios distintos:

  · `talla`          → problema de HORMA. Si una referencia acumula esto, el
                       patrón está mal escalado y eso se corrige en Diseño.
  · `defecto`        → problema de TALLER. Se le reclama al satélite que la
                       confeccionó, y por eso tiene que poder contarse aparte.
  · `no_le_gusto`    → no hay nada que arreglar. Es el ruido normal del
                       retail y mezclarlo con los otros tres los diluye.
  · `cambio_modelo`  → la clienta se lleva otra cosa. La prenda vuelve al
                       stock intacta, que no es lo mismo que un defecto.

La diferencia entre `talla` y `defecto` es la que después decide a quién se le
reclama. Si los dos entran como «devolución», esa pregunta ya no se puede
responder con los datos guardados.
"""
from __future__ import annotations

from enum import Enum

__all__ = ["MotivoDevolucion"]


class MotivoDevolucion(Enum):
    TALLA = "talla"
    DEFECTO = "defecto"
    NO_LE_GUSTO = "no_le_gusto"
    CAMBIO_MODELO = "cambio_modelo"
