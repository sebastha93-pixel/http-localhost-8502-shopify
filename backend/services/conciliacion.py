"""
backend.services.conciliacion — Liquidaciones COD por pedido.

Tabla Supabase: liquidaciones_cod (orden, monto_liquidado, fecha_liquidacion,
                                   referencia, nota, autor, creado_en)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client


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
        print(f"[conciliacion] Error creando cliente Supabase: {e}")
        return None


def cargar_map() -> dict[str, dict]:
    """Retorna {orden: {monto_liquidado, fecha_liquidacion, ...}}."""
    sb = _sb()
    if sb is None:
        return {}
    try:
        res = sb.table("liquidaciones_cod").select("*").execute()
        return {r["orden"]: r for r in (res.data or [])}
    except Exception as e:
        print(f"[conciliacion] Error cargar_map: {e}")
        return {}


def upsert(
    orden: str,
    *,
    monto: float,
    fecha: str,
    referencia: str = "",
    nota: str = "",
    autor: str,
) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    data = {
        "orden":             orden,
        "monto_liquidado":   float(monto),
        "fecha_liquidacion": fecha,
        "referencia":        referencia.strip() or None,
        "nota":              nota.strip() or None,
        "autor":             autor,
    }
    res = sb.table("liquidaciones_cod").upsert(data, on_conflict="orden").execute()
    return res.data[0] if res.data else data


def eliminar(orden: str) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        sb.table("liquidaciones_cod").delete().eq("orden", orden).execute()
        return True
    except Exception as e:
        print(f"[conciliacion] Error eliminar: {e}")
        return False
