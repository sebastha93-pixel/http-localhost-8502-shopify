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


def _normalizar_tel(tel: str) -> str:
    """Limpia un teléfono colombiano: quita +57, espacios, paréntesis, guiones."""
    if not tel:
        return ""
    t = "".join(ch for ch in str(tel) if ch.isdigit())
    if t.startswith("57") and len(t) == 12:
        t = t[2:]
    return t


def _consultar_shopify(email: str = "", telefono: str = "") -> Optional[dict]:
    """
    Consulta Shopify por el cliente. Primero por email; si no hay match
    (o no hay email), intenta por teléfono. Retorna:
      {shopify_id, email, telefono, total_pedidos, entregados, cancelados,
       pendientes, ltv, ultima_compra}
    o None si no hay match.
    """
    try:
        clients = []
        # 1. Buscar por email primero (más confiable)
        if email and "@" in email:
            try:
                r = _shopify_get("/customers/search.json", {"query": f"email:{email}"})
                clients = r.get("customers", []) or []
            except Exception as e:
                log.debug(f"Shopify email search {email}: {e}")

        # 2. Si no, intentar por teléfono (Shopify acepta phone:573...)
        if not clients and telefono:
            tel_norm = _normalizar_tel(telefono)
            if tel_norm:
                # Probamos varios formatos que Shopify acepta
                for q in (f"phone:+57{tel_norm}", f"phone:57{tel_norm}", f"phone:{tel_norm}"):
                    try:
                        r = _shopify_get("/customers/search.json", {"query": q})
                        clients = r.get("customers", []) or []
                        if clients:
                            log.info(f"Cliente encontrado por teléfono ({q})")
                            break
                    except Exception:
                        continue

        if not clients:
            return None
        c = clients[0]
        sid = c.get("id")
        email_shopify = (c.get("email") or "").strip().lower()
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
            "email":         email_shopify,
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


def _leer_cache_por_tel(telefono: str) -> Optional[dict]:
    """Lee cache válido buscando por teléfono normalizado."""
    sb = _sb()
    if sb is None:
        return None
    tel_norm = _normalizar_tel(telefono)
    if not tel_norm:
        return None
    try:
        r = sb.table("clientes_clasificacion").select("*").like("telefono", f"%{tel_norm}").limit(1).execute()
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
        log.debug(f"cache leer tel {telefono}: {e}")
        return None


def clasificar(email: str = "", telefono: str = "") -> dict:
    """
    Clasifica un cliente por email Y/O teléfono. Si no hay email pero
    sí teléfono, busca en Shopify por teléfono. Usa cache 24h.
    Nunca lanza excepción.
    """
    email = (email or "").strip().lower()
    telefono = (telefono or "").strip()

    if not email and not telefono:
        return {"email": "", "tier": "desconocido", "total_pedidos": 0,
                "entregados": 0, "cancelados": 0, "ltv": 0, "from_cache": False}

    # Cache hit por email
    if email and "@" in email:
        cached = _leer_cache(email)
        if cached:
            return {**cached, "from_cache": True}
    # Cache hit por teléfono (si no hay email)
    if not (email and "@" in email) and telefono:
        cached_tel = _leer_cache_por_tel(telefono)
        if cached_tel:
            return {**cached_tel, "from_cache": True}

    # Miss → consultar Shopify
    datos = _consultar_shopify(email=email, telefono=telefono)
    if datos is None:
        # Cliente no existe en Shopify → primer_pedido
        tier = "primer_pedido"
        result = {
            "email": email, "telefono": telefono, "tier": tier, "total_pedidos": 0,
            "entregados": 0, "cancelados": 0, "pendientes": 0,
            "ltv": 0, "ultima_compra": None, "from_cache": False,
        }
        # Solo cacheamos si hay email (la PK)
        if email and "@" in email:
            _guardar_cache(email, result, tier)
        return result

    tier = _calc_tier(
        entregados=datos["entregados"],
        cancelados=datos["cancelados"],
        total=datos["total_pedidos"],
    )
    # Usar email que devuelve Shopify si lo encontramos por teléfono
    email_key = datos.get("email") or email
    if email_key and "@" in email_key:
        _guardar_cache(email_key, datos, tier)
    return {"email": email_key, "tier": tier, **datos, "from_cache": False}


def clasificar_bulk(items: list[dict]) -> dict[str, dict]:
    """
    Clasifica varios clientes. `items` es lista de dicts con keys
    `email` y/o `telefono`. Retorna mapa por email (o por "tel:X" si no
    hay email).
    """
    out: dict[str, dict] = {}
    for item in items:
        em = (item.get("email") or "").strip().lower() if isinstance(item, dict) else ""
        tel = (item.get("telefono") or "").strip() if isinstance(item, dict) else ""
        if not em and not tel:
            continue
        key = em if (em and "@" in em) else f"tel:{_normalizar_tel(tel)}"
        if key in out:
            continue
        if em in out:
            continue
        out[key] = clasificar(email=em, telefono=tel)
    return out
