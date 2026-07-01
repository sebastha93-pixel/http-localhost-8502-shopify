"""
backend.api.produccion — Router del módulo Producción.

Prefijo: /api/produccion
Auth: reutiliza core.security (require_role / require_permission).

FASE 1 · Bloque 1 (Cimientos):
    - GET /health → estado Supabase + presencia de tablas
    - GET /consecutivo/{prefijo} → siguiente consecutivo (debug)

Los endpoints funcionales (ingreso, precosteo, corte, remisiones, insumos)
se añaden en bloques siguientes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.core.security import CurrentUser, require_role, require_permission
from backend.services import produccion as svc

router = APIRouter(prefix="/api/produccion", tags=["produccion"])


# ═══════════════════════════════════════════════════════════════════════
# Health & debug
# ═══════════════════════════════════════════════════════════════════════

@router.get("/health")
def health(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Reporta estado del módulo Producción: conexión Supabase + tablas creadas.
    Útil después de correr SUPABASE_PRODUCCION.sql para verificar que todo quedó.
    """
    return svc.health_check()


@router.get("/consecutivo/{prefijo}")
def consecutivo(
    prefijo: str,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Devuelve el próximo consecutivo del prefijo (ING, ROLLO, OC, REM, RI).
    ADVERTENCIA: cada llamada consume un número (no idempotente). Usar solo
    para debug/diagnóstico; en producción los consecutivos se piden dentro
    del transaction del create endpoint correspondiente.
    """
    prefijo = prefijo.upper().strip()
    if prefijo not in ("ING", "ROLLO", "OC", "REM", "RI", "PC"):
        raise HTTPException(400, "prefijo_invalido")
    try:
        return {"ok": True, "consecutivo": svc.next_consecutivo(prefijo)}
    except Exception as e:
        raise HTTPException(500, f"consecutivo: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════════════════
# Placeholders para bloques siguientes (marcados TODO para no perder scope)
# ═══════════════════════════════════════════════════════════════════════

# Bloque 2 — Ingreso + Inventario
# - POST /ingreso           crear cabecera + rollos
# - GET  /ingreso/{id}
# - GET  /rollos            filtros: tela, estado, tono
# - GET  /inventario/resumen unificado por descripcion_tela
# - POST /rollos/{id}/etiqueta
# - POST /movimientos/ajuste

# Bloque 3 — Precosteo
# - GET/POST /precosteo
# - POST /precosteo/{id}/firmar (requiere puede_autorizar_precosteo)
# - GET  /precosteo/historico

# Bloque 4 — Orden de Corte
# - POST /corte             crea borrador
# - POST /corte/{id}/autorizar (requiere puede_autorizar_corte)
# - POST /corte/{id}/cierre  captura consumo real → descuenta inventario

# Bloque 5 — Informe
# - GET /informe/corte      teórico vs real

# Bloque 6 — Remisiones + Insumos
# - POST /remisiones
# - GET/POST /insumos
# - POST /remisiones-insumos
