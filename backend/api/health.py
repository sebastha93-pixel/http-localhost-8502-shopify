"""
backend.api.health — Endpoints de health-check para monitoring y debugging.
"""
from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.config import settings


router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str
    timestamp: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — usado por Railway healthcheck."""
    return HealthResponse(
        status="ok",
        env=settings.env,
        version="0.1.0",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


class ConfigCheck(BaseModel):
    """Reporta qué integraciones tienen credenciales configuradas."""
    melonn:      bool
    shopify:     bool
    mercadopago: bool
    supabase:    bool


@router.get("/health/config", response_model=ConfigCheck)
def health_config() -> ConfigCheck:
    """Verifica que las env vars críticas estén presentes (no expone valores)."""
    return ConfigCheck(
        melonn      = bool(settings.melonn_api_key),
        shopify     = bool(settings.shopify_store and settings.shopify_access_token),
        mercadopago = bool(settings.mp_access_token),
        supabase    = bool(settings.supabase_url and settings.supabase_key),
    )


@router.get("/health/scheduler")
def health_scheduler() -> dict:
    """Estado del scheduler de refresh automático."""
    from backend.core import scheduler
    return scheduler.status()
