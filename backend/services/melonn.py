"""
backend.services.melonn — Lógica de Melonn (envuelve src/melonn_client.py).

Mantiene la misma fuente única de verdad (src/melonn_client) y solo añade
una capa fina async-friendly para FastAPI. Cuando eventualmente borremos
el dashboard Streamlit, podremos consolidar todo aquí.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# src/ del repo — donde está la lógica de negocio
_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC  = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def obtener_pedidos(forzar_refresh: bool = False) -> dict[str, Any]:
    """
    Wrapper de melonn_client.obtener_pedidos_activos para uso desde FastAPI.

    Retorna:
        {
          "pedidos": [...],          # lista de dicts (normalizada)
          "total":   int,
          "fuente":  str,            # api_live | supabase | stale
          "fetched_at": str ISO,
          "stale":   bool,
        }
    """
    import melonn_client as mc

    resultado = mc.obtener_pedidos_activos(forzar_refresh=forzar_refresh)
    if len(resultado) == 3:
        pedidos, _omitidos, meta = resultado
    else:
        pedidos, _omitidos = resultado
        meta = {}

    fa = meta.get("fetched_at")
    return {
        "pedidos":    pedidos or [],
        "total":      len(pedidos or []),
        "fuente":     meta.get("fuente", "unknown"),
        "stale":      bool(meta.get("stale", False)),
        "fetched_at": fa.isoformat() if hasattr(fa, "isoformat") else (fa or ""),
    }


def cache_info() -> dict[str, Any] | None:
    """Estado del caché de Melonn en Supabase."""
    import melonn_client as mc
    info = mc.cache_info()
    if not info:
        return None
    fa = info.get("fetched_at")
    return {
        "total":      info.get("total"),
        "age_seconds":int(info.get("age_s", 0)),
        "fetched_at": fa.isoformat() if hasattr(fa, "isoformat") else (fa or ""),
        "stale":      bool(info.get("stale", False)),
        "fuente":     info.get("fuente"),
        "backend":    info.get("backend"),
    }


def credenciales_ok() -> bool:
    import melonn_client as mc
    return mc.credenciales_ok()
