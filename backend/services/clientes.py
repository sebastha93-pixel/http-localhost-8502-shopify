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

        # Trae TODOS los orders del cliente. Antes traíamos solo los
        # primeros 50 y faltaban pedidos archivados — la suma no cuadraba
        # con orders_count del customer. Ahora paginamos completo y
        # además consideramos un filtro más amplio.
        orders = []
        if sid:
            seen_ids: set = set()
            base_params = {
                "customer_id": sid,
                "limit": 250,
                "fields": "id,fulfillment_status,cancelled_at,created_at,total_price,financial_status,closed_at",
                # created_at_min muy antiguo fuerza a Shopify a NO aplicar
                # el filtro default de últimos 60 días → trae histórico completo
                "created_at_min": "2018-01-01T00:00:00-05:00",
            }
            # Pasada 1: status=any (abiertos + cerrados + cancelados, no archivados)
            try:
                ro = _shopify_get("/orders.json", {**base_params, "status": "any"})
                for o in (ro.get("orders") or []):
                    if o.get("id") not in seen_ids:
                        orders.append(o)
                        seen_ids.add(o.get("id"))
            except Exception as e:
                log.debug(f"orders any del cliente {sid}: {e}")
            # Pasada 2: status=closed (incluye archivados manualmente cerrados en Shopify)
            try:
                ro = _shopify_get("/orders.json", {**base_params, "status": "closed"})
                for o in (ro.get("orders") or []):
                    if o.get("id") not in seen_ids:
                        orders.append(o)
                        seen_ids.add(o.get("id"))
            except Exception as e:
                log.debug(f"orders closed del cliente {sid}: {e}")

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

        # Pasada extra: draft_orders (cotizaciones, abandoned carts convertidos a draft)
        # No se cuentan en orders_count pero a veces el cliente sí tiene varios.
        cotizaciones = 0
        if sid:
            try:
                rd = _shopify_get("/draft_orders.json", {
                    "customer_id": sid,
                    "limit": 250,
                    "fields": "id,name,status,created_at",
                })
                cotizaciones = len((rd.get("draft_orders") or []))
            except Exception as e:
                log.debug(f"draft_orders {sid}: {e}")

        total = max(orders_count, len(orders))
        # `otros` = gap entre lo que Shopify dice que tiene el cliente
        # (orders_count) y lo que pudimos clasificar (entregados + en curso + cancelados).
        # Cotizaciones son una categoría APARTE (no se restan de otros).
        clasificados = entregados + pendientes + cancelados
        otros = max(0, total - clasificados)
        return {
            "shopify_id":    sid,
            "email":         email_shopify,
            "telefono":      telefono,
            "total_pedidos": total,
            "entregados":    entregados,
            "cancelados":    cancelados,
            "pendientes":    pendientes,
            "cotizaciones":  cotizaciones,
            "otros":         otros,
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


def _con_otros(d: dict) -> dict:
    """Asegura que el payload tenga el campo `otros` (gap clasificación)."""
    total = int(d.get("total_pedidos") or 0)
    e     = int(d.get("entregados")    or 0)
    p     = int(d.get("pendientes")    or 0)
    c     = int(d.get("cancelados")    or 0)
    d["otros"] = max(0, total - e - p - c)
    return d


def clasificar(email: str = "", telefono: str = "") -> dict:
    """
    Clasifica un cliente por email Y/O teléfono. Si no hay email pero
    sí teléfono, busca en Shopify por teléfono. Usa cache 24h.
    Nunca lanza excepción.
    """
    email = (email or "").strip().lower()
    telefono = (telefono or "").strip()

    if not email and not telefono:
        return _con_otros({"email": "", "tier": "desconocido", "total_pedidos": 0,
                "entregados": 0, "cancelados": 0, "pendientes": 0, "ltv": 0, "from_cache": False})

    # Cache hit por email
    if email and "@" in email:
        cached = _leer_cache(email)
        if cached:
            return _con_otros({**cached, "from_cache": True})
    # Cache hit por teléfono (si no hay email)
    if not (email and "@" in email) and telefono:
        cached_tel = _leer_cache_por_tel(telefono)
        if cached_tel:
            return _con_otros({**cached_tel, "from_cache": True})

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
        return _con_otros(result)

    tier = _calc_tier(
        entregados=datos["entregados"],
        cancelados=datos["cancelados"],
        total=datos["total_pedidos"],
    )
    # Usar email que devuelve Shopify si lo encontramos por teléfono
    email_key = datos.get("email") or email
    if email_key and "@" in email_key:
        _guardar_cache(email_key, datos, tier)
    return _con_otros({"email": email_key, "tier": tier, **datos, "from_cache": False})


def purgar_cache() -> dict:
    """
    Borra TODOS los registros de clientes_clasificacion. Útil cuando
    cambia la lógica de cálculo (ej. añadimos `otros`) y queremos
    forzar refetch desde Shopify en la próxima consulta.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase no configurado"}
    try:
        # Necesitamos un filtro: borrar todo donde email != '' (truco)
        r = sb.table("clientes_clasificacion").delete().neq("email", "__never__").execute()
        n = len(r.data) if r.data else 0
        return {"ok": True, "borrados": n}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


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


def debug_pedidos_crudos(email: str = "", telefono: str = "") -> dict:
    """Devuelve los pedidos crudos de Shopify para un cliente.
    Útil para diagnosticar 'otros' — muestra exactamente qué Shopify devuelve.
    AHORA: busca TODOS los customers que matchean (por email y por tel) y
    consulta orders de todos ellos."""
    em = (email or "").strip().lower()
    tel = (telefono or "").strip()
    if not em and not tel:
        return {"ok": False, "error": "falta email o telefono"}

    # Buscar TODOS los customer records que matcheen
    try:
        clients: list = []
        seen_cids: set = set()
        if em and "@" in em:
            try:
                r = _shopify_get("/customers/search.json", {"query": f"email:{em}"})
                for cc in (r.get("customers") or []):
                    if cc.get("id") not in seen_cids:
                        clients.append(cc); seen_cids.add(cc.get("id"))
            except Exception:
                pass
        if tel:
            tel_norm = _normalizar_tel(tel)
            for q in (f"phone:+57{tel_norm}", f"phone:57{tel_norm}", f"phone:{tel_norm}"):
                try:
                    r = _shopify_get("/customers/search.json", {"query": q})
                    for cc in (r.get("customers") or []):
                        if cc.get("id") not in seen_cids:
                            clients.append(cc); seen_cids.add(cc.get("id"))
                except Exception:
                    continue
        if not clients:
            return {"ok": False, "error": "cliente no encontrado en Shopify"}

        # Sumar orders_count de TODOS los customers
        customers_info = [{
            "id": cc.get("id"),
            "email": cc.get("email"),
            "phone": cc.get("phone"),
            "orders_count": int(cc.get("orders_count") or 0),
            "total_spent": cc.get("total_spent"),
            "created_at": cc.get("created_at"),
        } for cc in clients]
        orders_count = sum(int(cc.get("orders_count") or 0) for cc in clients)

        # Para retrocompat: c y sid del primero (el debug singular)
        c = clients[0]
        sid = c.get("id")

        # Traer pedidos de TODOS los customer_ids encontrados, varios filtros y endpoints
        orders: list = []
        seen: set = set()
        intentos: list = []

        for cust in clients:
            cust_id = cust.get("id")
            if not cust_id:
                continue
            base = {
                "customer_id": cust_id,
                "limit": 250,
                "created_at_min": "2015-01-01T00:00:00-05:00",  # más antiguo
                "fields": "id,name,fulfillment_status,cancelled_at,closed_at,financial_status,created_at,total_price,tags,source_name,test,customer",
            }
            # 3 pasadas por status para cada customer
            for status in ("any", "closed", "open"):
                try:
                    ro = _shopify_get("/orders.json", {**base, "status": status})
                    found = ro.get("orders") or []
                    intentos.append({"customer_id": cust_id, "status": status, "endpoint": "/orders.json", "count": len(found)})
                    for o in found:
                        if o.get("id") not in seen:
                            orders.append(o); seen.add(o.get("id"))
                except Exception as e:
                    intentos.append({"customer_id": cust_id, "status": status, "endpoint": "/orders.json", "error": str(e)[:100]})
            # Endpoint alternativo: /customers/{id}/orders.json
            try:
                ro = _shopify_get(f"/customers/{cust_id}/orders.json", {"limit": 250, "status": "any"})
                found = ro.get("orders") or []
                intentos.append({"customer_id": cust_id, "endpoint": f"/customers/{cust_id}/orders.json", "count": len(found)})
                for o in found:
                    if o.get("id") not in seen:
                        orders.append(o); seen.add(o.get("id"))
            except Exception as e:
                intentos.append({"customer_id": cust_id, "endpoint": f"/customers/{cust_id}/orders.json", "error": str(e)[:100]})

        # Clasificar
        rows = []
        bucket_counts = {"entregado": 0, "cancelado": 0, "pendiente": 0}
        for o in orders:
            if o.get("cancelled_at"):
                bucket = "cancelado"
            elif (o.get("fulfillment_status") or "") == "fulfilled":
                bucket = "entregado"
            else:
                bucket = "pendiente"
            bucket_counts[bucket] += 1
            rows.append({
                "id":                o.get("id"),
                "name":               o.get("name"),
                "created_at":         (o.get("created_at") or "")[:10],
                "fulfillment_status": o.get("fulfillment_status"),
                "financial_status":   o.get("financial_status"),
                "cancelled_at":       o.get("cancelled_at"),
                "closed_at":          o.get("closed_at"),
                "total_price":        o.get("total_price"),
                "tags":               o.get("tags"),
                "source_name":        o.get("source_name"),
                "test":               o.get("test"),
                "_bucket":            bucket,
            })

        otros = max(0, orders_count - len(orders))
        return {
            "ok":              True,
            "customers_encontrados": customers_info,
            "orders_count_total": orders_count,
            "orders_devueltos_por_endpoint": len(orders),
            "diferencia_otros": otros,
            "clasificacion": bucket_counts,
            "intentos":         intentos,
            "pedidos":         sorted(rows, key=lambda r: r["created_at"], reverse=True),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
