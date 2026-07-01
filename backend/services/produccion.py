"""
backend.services.produccion — Lógica de negocio del módulo Producción.

Patrón: espeja backend/services/clientes.py y revenue_db.
Toda persistencia va contra Supabase. Los endpoints de backend/api/produccion.py
delegan aquí la lógica; los tests unitarios usan mocks de _sb().

TABLAS (definidas en SUPABASE_PRODUCCION.sql):
    ordenes_ingreso, rollos_tela, movimientos_inventario
    referencias_precosteo, precosteo_items
    ordenes_corte, orden_corte_rollos
    confeccionistas, remisiones, remision_items
    insumos, remisiones_insumos, remision_insumo_items
    produccion_consecutivos (función next_consecutivo)
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

from supabase import Client, create_client

log = logging.getLogger(__name__)

_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    """Cliente Supabase singleton por proceso."""
    global _client
    if _client is not None:
        return _client
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not url or not key:
        return None
    try:
        _client = create_client(url, key)
        return _client
    except Exception as e:
        log.warning(f"[produccion] Supabase client failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# Consecutivos (ING-2026-0001, ROLLO-..., OC-..., REM-..., RI-...)
# ═══════════════════════════════════════════════════════════════════════

def next_consecutivo(prefijo: str, anio: Optional[int] = None, width: int = 4) -> str:
    """Devuelve el próximo consecutivo global del prefijo dado.

    Implementación en Python: SELECT actual + UPSERT +1. Hay una pequeña
    ventana de race entre workers (con 25 usuarios operando en producción
    simultánea es raro colisionar). Si necesitamos garantía atómica dura,
    después movemos esto a una función SQL con lock.

    Formato: 'ING-2026-0001'
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    anio = anio or datetime.now(tz=timezone.utc).year

    # Leer último
    try:
        r = (sb.table("produccion_consecutivos")
               .select("ultimo")
               .eq("prefijo", prefijo)
               .eq("anio", anio)
               .limit(1)
               .execute())
        ultimo = ((r.data or [None])[0] or {}).get("ultimo") or 0
    except Exception as e:
        raise RuntimeError(f"lectura consecutivo {prefijo}/{anio}: {e}")

    nuevo = ultimo + 1

    # Upsert nuevo valor
    try:
        sb.table("produccion_consecutivos").upsert(
            {
                "prefijo": prefijo,
                "anio": anio,
                "ultimo": nuevo,
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            },
            on_conflict="prefijo,anio",
        ).execute()
    except Exception as e:
        raise RuntimeError(f"upsert consecutivo {prefijo}/{anio}: {e}")

    return f"{prefijo}-{anio}-{str(nuevo).zfill(width)}"


# ═══════════════════════════════════════════════════════════════════════
# Health check — verificar conexión + presencia de tablas
# ═══════════════════════════════════════════════════════════════════════

TABLAS_ESPERADAS = [
    "ordenes_ingreso", "rollos_tela", "movimientos_inventario",
    "referencias_precosteo", "precosteo_items",
    "ordenes_corte", "orden_corte_rollos",
    "confeccionistas", "remisiones", "remision_items",
    "insumos", "remisiones_insumos", "remision_insumo_items",
]


def health_check() -> dict:
    """Reporta estado de conexión Supabase + presencia de tablas del módulo."""
    sb = _sb()
    if sb is None:
        return {
            "ok": False,
            "error": "supabase_no_configurado",
            "hint": "Verifica SUPABASE_URL y SUPABASE_KEY en Railway env.",
        }
    tablas_ok: list[str] = []
    tablas_faltantes: list[str] = []
    for t in TABLAS_ESPERADAS:
        try:
            # SELECT limit 0 solo verifica que la tabla exista + schema cache
            sb.table(t).select("id").limit(0).execute()
            tablas_ok.append(t)
        except Exception as e:
            err = str(e)
            if "does not exist" in err or "42P01" in err:
                tablas_faltantes.append(t)
            else:
                tablas_faltantes.append(f"{t} (error: {err[:80]})")

    return {
        "ok": len(tablas_faltantes) == 0,
        "tablas_encontradas": len(tablas_ok),
        "tablas_esperadas": len(TABLAS_ESPERADAS),
        "tablas_faltantes": tablas_faltantes,
        "hint": (
            "Corre SUPABASE_PRODUCCION.sql en Supabase SQL Editor."
            if tablas_faltantes else None
        ),
    }
