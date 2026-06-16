"""
backend.services.archivo — Histórico de pedidos entregados.

Snapshot inmutable cuando un pedido pasa a estado entregado. NO entra en
flujo operativo ni KPIs: solo lectura desde /historico. Sliding window 3
meses (la tabla se purga sola vía trigger Postgres).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from supabase import create_client, Client


log = logging.getLogger(__name__)

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
        log.warning(f"archivo: no conectó Supabase: {e}")
        return None


def _date_str(v) -> Optional[str]:
    """Convierte date/datetime/string a ISO YYYY-MM-DD."""
    if not v:
        return None
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    s = str(v)
    return s[:10] if len(s) >= 10 else s


def _dias_total(p: dict) -> Optional[int]:
    """Calcula días entre creación y entrega."""
    fc = p.get("fecha_creacion")
    fe = p.get("fecha_entrega")
    try:
        if isinstance(fc, str): fc = datetime.fromisoformat(fc[:10]).date()
        if isinstance(fe, str): fe = datetime.fromisoformat(fe[:10]).date()
        if isinstance(fc, datetime): fc = fc.date()
        if isinstance(fe, datetime): fe = fe.date()
        if fc and fe:
            return max(0, (fe - fc).days)
    except Exception:
        pass
    return None


def archivar_pedido(p: dict) -> dict:
    """
    Upsert de un pedido en pedidos_archivo. Idempotente: si el pedido ya
    está, lo actualiza. La PK es orden_tienda.

    Retorna {ok, accion} o {ok: False, error}.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase no configurado"}

    orden = p.get("orden_tienda") or p.get("orden_melonn") or ""
    if not orden:
        return {"ok": False, "error": "Pedido sin orden_tienda ni orden_melonn"}

    # JSON serializable (date → str, etc.)
    try:
        raw = json.loads(json.dumps(p, default=str))
    except Exception:
        raw = {"_serializa_error": True}

    data = {
        "orden":               str(orden),
        "orden_melonn":        p.get("orden_melonn") or "",
        "nombre_comprador":    (p.get("nombre_comprador") or "").strip() or None,
        "telefono_comprador":  (p.get("telefono_comprador") or "").strip() or None,
        "email_comprador":     (p.get("email_comprador") or "").strip() or None,
        "ciudad_destino":      (p.get("ciudad_destino") or "").strip() or None,
        "direccion":           (p.get("direccion") or "").strip() or None,
        "zona":                (p.get("zona") or "").strip() or None,
        "tipo_recaudo":        p.get("tipo_recaudo") or None,
        "valor_num":           p.get("valor_num"),
        "producto":            (p.get("producto") or "").strip() or None,
        "transportadora":      (p.get("transportadora") or "").strip() or None,
        "carrier_real":        (p.get("carrier_real") or "").strip() or None,
        "guia_real":           (p.get("guia_real") or "").strip() or None,
        "estado_final":        (p.get("estado_melonn") or "").strip() or None,
        "estado_melonn_code":  p.get("estado_melonn_code"),
        "tuvo_novedad":        bool(p.get("es_novedad_visible") or p.get("novedad_manual")),
        "motivo_novedad":      (p.get("motivo_novedad_manual") or "").strip() or None,
        "fecha_creacion":      _date_str(p.get("fecha_creacion")),
        "fecha_entrega":       _date_str(p.get("fecha_entrega")),
        "dias_total":          _dias_total(p),
        "archivado_en":        datetime.now(timezone.utc).isoformat(),
        "raw_pedido":          raw,
    }

    try:
        sb.table("pedidos_archivo").upsert(data, on_conflict="orden").execute()
        return {"ok": True, "orden": orden}
    except Exception as e:
        log.warning(f"archivo upsert {orden}: {e}")
        return {"ok": False, "error": str(e)[:200], "orden": orden}


def archivar_si_entregado(p: dict) -> bool:
    """
    Archiva un pedido SOLO si está en estado entregado.
    Retorna True si se archivó (o ya estaba), False si no aplica.
    """
    code = int(p.get("estado_melonn_code") or 0)
    sub  = p.get("sub_estado_logistico")
    if code in (6, 8) or sub == "entregado":
        r = archivar_pedido(p)
        return bool(r.get("ok"))
    return False


def listar(
    q: str = "",
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """
    Lista pedidos archivados, opcionalmente filtrados.
    `q`: búsqueda en nombre/teléfono/ciudad/orden
    `desde`, `hasta`: rango ISO YYYY-MM-DD sobre archivado_en
    """
    sb = _sb()
    if sb is None:
        return []
    try:
        query = sb.table("pedidos_archivo").select("*").order("archivado_en", desc=True).limit(limit)
        if desde:
            query = query.gte("archivado_en", f"{desde}T00:00:00Z")
        if hasta:
            query = query.lte("archivado_en", f"{hasta}T23:59:59Z")
        res = query.execute()
        rows = res.data or []
        if q:
            term = q.lower()
            rows = [
                r for r in rows
                if term in (r.get("nombre_comprador") or "").lower()
                or term in (r.get("telefono_comprador") or "").lower()
                or term in (r.get("ciudad_destino") or "").lower()
                or term in (str(r.get("orden") or "")).lower()
            ]
        return rows
    except Exception as e:
        log.warning(f"archivo listar: {e}")
        return []


def stats() -> dict:
    """Resumen del archivo: total registros, rango de fechas."""
    sb = _sb()
    if sb is None:
        return {"total": 0, "desde": None, "hasta": None}
    try:
        res = sb.table("pedidos_archivo").select("archivado_en, tuvo_novedad", count="exact").execute()
        rows = res.data or []
        total = res.count or len(rows)
        novedades = sum(1 for r in rows if r.get("tuvo_novedad"))
        fechas = sorted([r.get("archivado_en") for r in rows if r.get("archivado_en")])
        return {
            "total":            total,
            "con_novedad":      novedades,
            "desde":            fechas[0][:10] if fechas else None,
            "hasta":            fechas[-1][:10] if fechas else None,
        }
    except Exception as e:
        log.warning(f"archivo stats: {e}")
        return {"total": 0, "con_novedad": 0, "desde": None, "hasta": None}
