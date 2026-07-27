"""
backend.services.postventa_shopify — Descubrimiento de capacidades Shopify.

FASE 0 de la integración de reserva/devolución: saber QUÉ permisos tiene el
token antes de intentar escribir. Solo lectura; no muta nada.

Contexto: hoy toda la integración Shopify del OS es de lectura. Para descontar
una venta (refund) o apartar inventario hace falta escritura, y eso depende de
los scopes con los que se emitió el token.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.services import clientes

log = logging.getLogger("postventa_shopify")

# Scopes que necesita cada capacidad que queremos construir.
CAPACIDADES = {
    "descontar_venta_reembolso": ["write_orders"],
    "registrar_retorno":         ["write_returns", "write_orders"],
    "reservar_inventario":       ["write_inventory"],
    "leer_inventario":           ["read_inventory"],
    "leer_pedidos":              ["read_orders"],
}

_Q_SCOPES = """
query { currentAppInstallation { accessScopes { handle } } }
"""

_Q_LOCATIONS = """
query { locations(first: 10) { edges { node { id name isActive } } } }
"""


def _q(query: str) -> Any:
    try:
        return clientes._shopify_graphql(query)
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)[:300]}


def scopes_actuales() -> list[str]:
    """Permisos con los que se emitió el token. Vacío si no se pudo leer."""
    data = _q(_Q_SCOPES)
    if not isinstance(data, dict) or data.get("errors") or data.get("_error"):
        return []
    nodos = (((data.get("data") or {}).get("currentAppInstallation") or {})
             .get("accessScopes") or [])
    return sorted(n.get("handle", "") for n in nodos if n.get("handle"))


def diagnostico() -> dict:
    """Qué puede y qué NO puede hacer el token hoy, por capacidad.

    Con esto se decide si la reserva/devolución en Shopify es viable o si hay
    que pedir un token con más permisos antes de construir nada.
    """
    scopes = scopes_actuales()
    if not scopes:
        return {"_error": "no_se_pudieron_leer_scopes",
                "detalle": "El token no respondió a currentAppInstallation. "
                           "Puede ser un token sin permisos de app o mal configurado.",
                "crudo": _q(_Q_SCOPES)}

    puede = {}
    for capacidad, requeridos in CAPACIDADES.items():
        faltantes = [s for s in requeridos if s not in scopes]
        puede[capacidad] = {"disponible": not faltantes,
                            "requiere": requeridos,
                            "faltan": faltantes}

    # Las bodegas importan para saber DÓNDE se reservaría el inventario.
    loc = _q(_Q_LOCATIONS)
    bodegas = []
    if isinstance(loc, dict) and not loc.get("errors"):
        for e in (((loc.get("data") or {}).get("locations") or {}).get("edges") or []):
            n = e.get("node") or {}
            bodegas.append({"id": n.get("id"), "name": n.get("name"),
                            "activa": n.get("isActive")})

    return {"scopes": scopes, "capacidades": puede, "bodegas": bodegas}
