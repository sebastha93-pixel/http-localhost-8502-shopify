"""
backend.api.melonn — Endpoints REST de logística (Melonn).
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.core.security import CurrentUser, require_role
from backend.services import melonn as svc
from backend.services import metricas as metricas_svc
from backend.services import overrides as overrides_svc


router = APIRouter(prefix="/api/melonn", tags=["melonn"])


# ── Modelos de respuesta (Pydantic — auto-doc en /docs) ──────────────────────

class PedidoListResponse(BaseModel):
    pedidos: list[dict]
    total: int
    fuente: str
    stale: bool
    fetched_at: str


class CacheInfoResponse(BaseModel):
    total: Optional[int]      = None
    age_seconds: Optional[int]= None
    fetched_at: Optional[str] = None
    stale: Optional[bool]     = None
    fuente: Optional[str]     = None
    backend: Optional[str]    = None


class StatusResponse(BaseModel):
    credenciales_ok: bool
    cache: Optional[CacheInfoResponse] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

class SyncResponse(BaseModel):
    ok: bool
    total: int = 0
    antes: int = 0
    despues: int = 0
    completados: int = 0
    error: Optional[str] = None


@router.post("/sync-completo", response_model=SyncResponse)
def sync_completo_endpoint(
    user: CurrentUser = Depends(require_role("admin", "operador")),
) -> SyncResponse:
    """
    Pasada exhaustiva de enriquecimiento Shopify sobre TODO el caché.
    Lento (~30-90s). Solo admin/operador.
    """
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import melonn_client as mc

    try:
        result = mc.sync_completo()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return SyncResponse(**result)


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    """Estado de la integración Melonn — credenciales y caché."""
    return StatusResponse(
        credenciales_ok=svc.credenciales_ok(),
        cache=svc.cache_info() and CacheInfoResponse(**svc.cache_info()),
    )


@router.get("/pedidos", response_model=PedidoListResponse)
def pedidos(
    refresh: bool = Query(default=False, description="Forzar fetch a la API"),
) -> PedidoListResponse:
    """
    Lista de pedidos activos.

    - `refresh=true` → fetch en vivo a Melonn (lento, ~2-30s)
    - `refresh=false` → caché Supabase (instantáneo)
    """
    try:
        data = svc.obtener_pedidos(forzar_refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn API error: {exc}")
    # 1) Aplicar overrides manuales (datos rellenados a mano desde la UI)
    overrides = overrides_svc.cargar_map()
    pedidos = [overrides_svc.aplicar_a_pedido(p, overrides) for p in data["pedidos"]]
    # 2) Enriquecer con nivel/zona/sla — campos críticos para tabla logística
    data["pedidos"] = [metricas_svc.clasificar(p) for p in pedidos]
    return PedidoListResponse(**data)


@router.get("/pedidos/{orden}")
def pedido_detalle(orden: str) -> dict:
    """Detalle de un pedido específico (por orden_tienda u orden_melonn)."""
    try:
        data = svc.obtener_pedidos(forzar_refresh=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn API error: {exc}")
    overrides = overrides_svc.cargar_map()
    for p in data["pedidos"]:
        if p.get("orden_tienda") == orden or p.get("orden_melonn") == orden:
            p = overrides_svc.aplicar_a_pedido(p, overrides)
            return metricas_svc.clasificar(p)
    raise HTTPException(status_code=404, detail=f"Pedido {orden} no encontrado")


class AutorizarResponse(BaseModel):
    ok: bool
    mensaje: str
    orden_melonn: str


@router.post("/pedidos/{orden_melonn}/autorizar-despacho", response_model=AutorizarResponse)
def autorizar_despacho(
    orden_melonn: str,
    user: CurrentUser = Depends(require_role("admin", "operador")),
) -> AutorizarResponse:
    """
    Libera el hold de fulfillment en Melonn y autoriza el despacho del pedido.
    Equivalente al botón "Authorize dispatch" en la UI de Melonn.
    Registra automáticamente una acción de auditoría en Supabase.
    """
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import melonn_client as mc
    import memoria

    try:
        ok, mensaje = mc.release_hold_fulfillment(orden_melonn)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn API error: {exc}")

    if not ok:
        raise HTTPException(status_code=400, detail=mensaje)

    # Audit trail: el usuario autenticado del JWT
    try:
        memoria.agregar_accion(
            orden_melonn,
            "despacho_autorizado",
            "Despacho autorizado vía dashboard MALE'DENIM OS",
            user.nombre,
        )
    except Exception:
        pass  # No bloquear la autorización si Supabase falla

    return AutorizarResponse(ok=True, mensaje=mensaje, orden_melonn=orden_melonn)
