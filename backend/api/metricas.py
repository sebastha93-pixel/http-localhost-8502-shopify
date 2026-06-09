"""
backend.api.metricas — Endpoints de métricas globales (Centro de Control).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.services import melonn as melonn_svc
from backend.services import metricas as metricas_svc


router = APIRouter(prefix="/api/metricas", tags=["metricas"])


class MetricasGlobales(BaseModel):
    n_total: int
    n_pend: int
    n_tran_cod: int
    n_nov_cod: int
    n_ent_cod: int
    n_nov_pre: int
    n_tran_pre: int
    n_ent_pre: int
    n_critico: int
    n_riesgo: int
    n_normal: int
    val_cod: float
    val_riesgo: float
    val_ent: float
    val_nov_cod: float


class MetricasResponse(BaseModel):
    metricas: MetricasGlobales
    fuente: str
    stale: bool
    fetched_at: str


@router.get("", response_model=MetricasResponse)
def obtener_metricas(
    refresh: bool = Query(default=False, description="Forzar fetch a la API"),
) -> MetricasResponse:
    """Métricas globales pre-calculadas para el Centro de Control."""
    try:
        data = melonn_svc.obtener_pedidos(forzar_refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn API error: {exc}")

    m = metricas_svc.calcular_metricas(data["pedidos"])
    # Excluir 'pedidos' del payload (es payload pesado, no es métrica)
    m.pop("pedidos", None)

    return MetricasResponse(
        metricas=MetricasGlobales(**m),
        fuente=data["fuente"],
        stale=data["stale"],
        fetched_at=data["fetched_at"],
    )
