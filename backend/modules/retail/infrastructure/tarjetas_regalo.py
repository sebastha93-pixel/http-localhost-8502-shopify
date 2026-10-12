"""Verificar una tarjeta regalo de la tienda en línea antes de cobrar con ella.

Las tarjetas se venden y viven en Shopify. De cada una Shopify sólo deja ver
los ÚLTIMOS CUATRO caracteres del código —el resto no lo guarda legible—, así
que se busca por ellos y se devuelven las que casan, con su saldo.

Si la app no tiene el permiso `read_gift_cards`, o Shopify no responde, se
dice ASÍ: «no se pudo verificar». Lo que no se hace es dar por buena una
tarjeta que nadie comprobó.

ESTO SÓLO LEE. Cobrar con la tarjeta en la caja NO le descuenta el saldo en
Shopify todavía: hay que descontarlo a mano hasta que la app tenga permiso de
escritura y eso se pruebe con una tarjeta de verdad.
"""
from __future__ import annotations

import re
from typing import List, Optional

__all__ = ["consultar", "limpiar"]

_CONSULTA = """
query($q: String!) {
  giftCards(first: 5, query: $q) {
    nodes {
      lastCharacters enabled expiresOn createdAt
      balance { amount }
      initialValue { amount }
    }
  }
}
"""


def limpiar(codigo: str) -> str:
    """El código como lo guarda Shopify: sin espacios ni guiones, en mayúscula."""
    return re.sub(r"[^A-Za-z0-9]", "", codigo or "").upper()


def consultar(codigo: str) -> dict:
    """`{"verificada": bool, "motivo": str|None, "tarjetas": [...]}`.

    `verificada` es False cuando NO SE PUDO preguntar; con True y la lista
    vacía, Shopify respondió que no hay tarjeta con esos últimos caracteres.
    """
    limpio = limpiar(codigo)
    if len(limpio) < 4:
        return {"verificada": False, "tarjetas": [],
                "motivo": "El código tiene al menos 4 caracteres."}
    from backend.services.clientes import _shopify_graphql

    r = _shopify_graphql(_CONSULTA, {"q": f"last_characters:{limpio[-4:]}"}) or {}
    if r.get("errors"):
        msg = " ".join(str(e.get("message", "")) for e in r["errors"])
        if "read_gift_cards" in msg or "ACCESS_DENIED" in str(r["errors"]):
            return {"verificada": False, "tarjetas": [],
                    "motivo": "La app de Shopify no tiene permiso para ver "
                              "tarjetas regalo."}
        return {"verificada": False, "tarjetas": [],
                "motivo": "Shopify no respondió."}
    nodos = (((r.get("data") or {}).get("giftCards") or {}).get("nodes")) or []
    return {"verificada": True, "motivo": None, "tarjetas": [_fila(n) for n in nodos
            if str(n.get("lastCharacters") or "").upper() == limpio[-4:]]}


def _fila(n: dict) -> dict:
    return {
        "ultimos": str(n.get("lastCharacters") or "").upper(),
        "activa": bool(n.get("enabled")),
        "vence": n.get("expiresOn"),
        "saldo": float((n.get("balance") or {}).get("amount") or 0),
        "inicial": float((n.get("initialValue") or {}).get("amount") or 0),
        "creada": (n.get("createdAt") or "")[:10],
    }
