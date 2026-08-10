"""Motivos de un asiento de inventario.

Es un enum EXTENSIBLE a propósito: los traslados entre tiendas y las
devoluciones (Fase 2) son dos motivos más, no un modelo nuevo. Esa es la
diferencia entre "no lo construimos todavía" y "va a tocar rehacer todo".
"""
from __future__ import annotations

from enum import Enum

__all__ = ["Motivo"]


class Motivo(Enum):
    VENTA = "venta"
    ANULACION = "anulacion"
    INGRESO_COMPRA = "ingreso_compra"
    AJUSTE_CONTEO = "ajuste_conteo"
    MERMA = "merma"
    SINCRONIZACION_INICIAL = "sincronizacion_inicial"
    # Fase 2 — el modelo ya los admite.
    TRASLADO_SALIDA = "traslado_salida"
    TRASLADO_ENTRADA = "traslado_entrada"
    DEVOLUCION = "devolucion"
