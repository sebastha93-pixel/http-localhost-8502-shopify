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
    # ── Logística inversa: la prenda viaja de vuelta ──
    "esperando_envio_cliente",
    "en_transito_bodega",
    "recibido_bodega",
    # ── Cierre fiscal y despacho del reemplazo ──
    "nota_credito_emitida",
    "factura_emitida",
    "cambio_enviado",
    "cerrado",
    "escalado",
}

ESTADOS_TERMINALES: set[str] = {"rechazado", "cerrado"}

# Transiciones válidas (además de "cualquiera -> cerrado", ver transicion_valida)
TRANSICIONES: dict[str, set[str]] = {
    "creado":                {"pendiente_validacion"},
    "pendiente_validacion":  {"aprobado", "rechazado", "escalado"},
    # Tras aprobar: o se pide la devolución física, o se salta directo a la NC
    # (cuando la prenda ya está en bodega o el caso no requiere retorno).
    "aprobado":              {"esperando_envio_cliente", "nota_credito_emitida"},
    "esperando_envio_cliente": {"en_transito_bodega"},
    "en_transito_bodega":    {"recibido_bodega"},
    "recibido_bodega":       {"nota_credito_emitida"},
    "nota_credito_emitida":  {"factura_emitida"},
    "factura_emitida":       {"cambio_enviado"},
    "cambio_enviado":        set(),
    "escalado":              {"aprobado", "rechazado"},
    "rechazado":             set(),
    "cerrado":               set(),
}


# El reemplazo NO se despacha hasta que la prenda devuelta llegó a bodega.
# Si el caso pasó por logística inversa, debe haber tocado 'recibido_bodega'.
ESTADOS_LOGISTICA_INVERSA: set[str] = {
    "esperando_envio_cliente", "en_transito_bodega",
}


def requiere_recepcion(estado_actual: str) -> bool:
    """True si el caso está esperando que la prenda llegue a bodega."""
    return estado_actual in ESTADOS_LOGISTICA_INVERSA


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


# ── Cálculos ─────────────────────────────────────────────────────────
def calcular_diferencia(original: float, requested: Optional[float]) -> float:
    """Diferencia de precio del item. Convención: + cobra, - devuelve.

    - requested None (reembolso/bono) -> se devuelve todo el original.
    - requested con valor -> requested - original.
    Se usa Decimal para no arrastrar error de punto flotante y se
    devuelve float con 2 decimales (COP).
    """
    o = Decimal(str(original))
    if requested is None:
        return float(-o)
    r = Decimal(str(requested))
    return float(r - o)


def formato_case_number(anio: int, consecutivo: int) -> str:
    """Consecutivo legible: PV-2026-0001 (mínimo 4 dígitos, crece si hace falta)."""
    return f"PV-{anio}-{consecutivo:04d}"
