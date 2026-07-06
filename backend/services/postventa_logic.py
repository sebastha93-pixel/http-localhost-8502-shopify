"""
backend.services.postventa_logic — Lógica pura del módulo Postventa.

Sin I/O, sin dependencias externas: constantes del dominio, máquina de
estados, validaciones y cálculos. 100% testeable con pytest.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

# ── Estados ──────────────────────────────────────────────────────────
ESTADOS: set[str] = {
    "creado",
    "pendiente_validacion",
    "aprobado",
    "rechazado",
    "nota_credito_emitida",
    "factura_emitida",
    "cerrado",
    "escalado",
}

ESTADOS_TERMINALES: set[str] = {"rechazado", "cerrado"}

# Transiciones válidas (además de "cualquiera -> cerrado", ver transicion_valida)
TRANSICIONES: dict[str, set[str]] = {
    "creado":                {"pendiente_validacion"},
    "pendiente_validacion":  {"aprobado", "rechazado", "escalado"},
    "aprobado":              {"nota_credito_emitida"},
    "nota_credito_emitida":  {"factura_emitida"},
    "factura_emitida":       set(),
    "escalado":              {"aprobado", "rechazado"},
    "rechazado":             set(),
    "cerrado":               set(),
}


def transicion_valida(actual: str, nuevo: str) -> bool:
    """True si se puede pasar de `actual` a `nuevo`.

    Reglas:
      - No se sale de un estado terminal (rechazado, cerrado).
      - Cualquier estado NO terminal puede ir a 'cerrado' (cierre manual).
      - El resto según el grafo TRANSICIONES.
    """
    if actual not in ESTADOS or nuevo not in ESTADOS:
        return False
    if actual in ESTADOS_TERMINALES:
        return False
    if nuevo == "cerrado":
        return True
    return nuevo in TRANSICIONES.get(actual, set())


# ── Catálogos ────────────────────────────────────────────────────────
TIPOS: set[str] = {
    "cambio_talla", "cambio_ref", "reembolso", "bono", "garantia",
}

MOTIVOS: list[str] = [
    "talla_pequena", "talla_grande", "no_le_gusto_como_quedo",
    "color_diferente", "producto_defectuoso", "producto_equivocado",
    "pedido_incompleto", "demora_entrega", "arrepentimiento",
    "calidad_percibida", "error_asesoria", "error_logistico",
    "cambio_por_otro", "garantia", "otro",
]

PRIORIDADES: set[str] = {"baja", "media", "alta"}


def validar_tipo(t: str) -> bool:
    return t in TIPOS


def validar_motivo(m: str) -> bool:
    return m in MOTIVOS


def validar_prioridad(p: str) -> bool:
    return p in PRIORIDADES
