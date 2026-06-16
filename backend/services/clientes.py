"""
backend.services.clientes — Clasificación de clientes desde historial Shopify.

Tier basado en pedidos:
  vip            → 5+ entregados, 0 cancelados
  recurrente     → 2-4 entregados
  nuevo          → 1 entregado
  primer_pedido  → sin historial (este es el primero)
  riesgo         → cancelados >= entregados (cliente problemático)

Cache 24h por email en Supabase (tabla clientes_clasificacion).
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from supabase import create_client, Client


log = logging.getLogger(__name__)

_TTL_HORAS = 24
_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        _client = create_client(url, key)
        return _client
    except Exception as e:
        log.warning(f"clientes: no conectó Supabase: {e}")
        return None


def _shopify_get(endpoint: str, params: Optional[dict] = None) -> dict:
    """Wrapper sobre shopify_client._get desde src/."""
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    from shopify_client import _get
    return _get(endpoint, params)


def _calc_tier(entregados: int, cancelados: int, total: int) -> str:
    """Decide el tier del cliente según sus números."""
    if total == 0:
        return "primer_pedido"
    if cancelados >= max(entregados, 1) and total >= 2:
        return "riesgo"
    if entregados >= 5 and cancelados == 0:
        return "vip"
    if entregados >= 2:
        return "recurrente"
    if entregados == 1:
        return "nuevo"
    return "desconocido"


def _consultar_shopify(email: str) -> Optional[dict]:
    """
    Consulta Shopify por el cliente y suma sus órdenes. Retorna:
      {shopify_id, telefono, total_pedidos, entregados, cancelados,
       pendientes, ltv, ultima_compra}
    o None si no hay match en Shopify.
    """
    try:
        # 1. Buscar el customer por email
        r = _shopify_get("/customers/search.json", {"query": f"email:{email}"})
        clients = r.get("customers", [])
        if not clients:
            return None
        c = clients[0]
        sid = c.get("id")
        telefono = (c.get("phone") or "").strip()

        # 2. Traer sus orders (Shopify ya tiene orders_count + total_spent)
        orders_count = int(c.get("orders_count") or 0)
        total_spent  = float(c.get("total_spent") or 0)
        last_order   = c.get("last_order_name")

        # Para entregados vs cancelados necesitamos los orders detalle
        # (status any, fulfillment_status all). Limit 50 — cubre la
        # inmensa mayoría de casos.
        orders = []
        if sid:
            try:
                ro = _shopify_get("/orders.json", {
                    "customer_id": sid,
                    "status": "any",
                    "limit": 50,
                    "fields": "id,fulfillment_status,cancelled_at,created_at,total_price",
                })
                orders = ro.get("orders", []) or []
            except Exception as e:
                log.debug(f"orders del cliente {sid}: {e}")

        entregados = 0
        cancelados = 0
        pendientes = 0
        ultima = None
        for o in orders:
            if o.get("cancelled_at"):
                cancelados += 1
            elif (o.get("fulfillment_status") or "") == "fulfilled":
                entregados += 1
            else:
                pendientes += 1
            ca = (o.get("created_at") or "")[:10]
            if ca and (ultima is None or ca > ultima):
                ultima = ca

        total = max(orders_count, len(orders))
        return {
            "shopify_id":    sid,
            "telefono":      telefono,
            "total_pedidos": total,
            "entregados":    entregados,
            "cancelados":    cancelados,
            "pendientes":    pendientes,
            "ltv":           total_spent,
            "ultima_compra": ultima,
        }
    except Exception as e:
        log.warning(f"clientes: Shopify error para {email}: {e}")
        return None


def _leer_cache(email: str) -> Optional[dict]:
    """Lee cache válido (< 24h). Retorna None si expiró o no existe."""
    sb = _sb()
    if sb is None:
        return None
    try:
        r = sb.table("clientes_clasificacion").select("*").eq("email", email).limit(1).execute()
        rows = r.data or []
        if not rows:
            return None
        row = rows[0]
        ts_str = row.get("actualizado_en") or ""
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            return None
        if datetime.now(timezone.utc) - ts > timedelta(hours=_TTL_HORAS):
            return None
        return row
    except Exception as e:
        log.debug(f"cache leer {email}: {e}")
        return None


def _guardar_cache(email: str, datos: dict, tier: str) -> None:
    sb = _sb()
    if sb is None:
        return
    try:
        sb.table("clientes_clasificacion").upsert({
            "email":         email,
            "telefono":      datos.get("telefono") or None,
            "shopify_id":    datos.get("shopify_id"),
            "tier":          tier,
            "total_pedidos": datos.get("total_pedidos", 0),
            "entregados":    datos.get("entregados", 0),
            "cancelados":    datos.get("cancelados", 0),
            "pendientes":    datos.get("pendientes", 0),
            "ltv":           datos.get("ltv", 0),
            "ultima_compra": datos.get("ultima_compra"),
            "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="email").execute()
    except Exception as e:
        log.warning(f"cache guardar {email}: {e}")


def clasificar(email: str) -> dict:
    """
    Clasifica un cliente por email. Usa cache 24h.
    Retorna dict con tier + métricas. Nunca lanza excepción.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"email": email, "tier": "desconocido", "total_pedidos": 0, "entregados": 0, "cancelados": 0, "ltv": 0, "from_cache": False}

    # Cache hit?
    cached = _leer_cache(email)
    if cached:
        return {**cached, "from_cache": True}

    # Miss → consultar Shopify
    datos = _consultar_shopify(email)
    if datos is None:
        # Cliente no existe en Shopify → primer_pedido
        tier = "primer_pedido"
        result = {
            "email": email, "tier": tier, "total_pedidos": 0,
            "entregados": 0, "cancelados": 0, "pendientes": 0,
            "ltv": 0, "ultima_compra": None, "from_cache": False,
        }
        _guardar_cache(email, result, tier)
        return result

    tier = _calc_tier(
        entregados=datos["entregados"],
        cancelados=datos["cancelados"],
        total=datos["total_pedidos"],
    )
    _guardar_cache(email, datos, tier)
    return {"email": email, "tier": tier, **datos, "from_cache": False}


def clasificar_bulk(emails: list[str]) -> dict[str, dict]:
    """Clasifica varios emails. Returna {email: clasificacion}."""
    out: dict[str, dict] = {}
    for em in emails:
        em = (em or "").strip().lower()
        if not em:
            continue
        if em in out:
            continue
        out[em] = clasificar(em)
    return out
