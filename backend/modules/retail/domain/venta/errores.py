"""Errores del dominio de venta.

Todos llevan un mensaje escrito PARA LA CAJERA, no para el log. Un POS no
puede mostrarle un rastro de excepción a alguien que tiene una clienta
enfrente: el mensaje tiene que decir qué pasó y qué hacer.
"""
from __future__ import annotations

__all__ = ["ReglaDeNegocio", "RequiereAutorizacion", "VentaNoModificable"]


class ReglaDeNegocio(Exception):
    """Una regla del dominio impide la operación."""


class RequiereAutorizacion(ReglaDeNegocio):
    """La operación es posible, pero necesita el PIN de alguien con permiso.

    Se distingue de las demás porque el frontend reacciona distinto: abre el
    diálogo de autorización en vez de mostrar un error.
    """


class VentaNoModificable(ReglaDeNegocio):
    """Se intentó tocar una venta que ya no está en borrador (INV-V1)."""
