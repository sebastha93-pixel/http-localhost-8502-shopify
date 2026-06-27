"""
backend.api.finanzas — Dashboard financiero + integración MercadoPago.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.core.security import CurrentUser, get_current_user, require_role, require_permission
from backend.services import melonn as melonn_svc
from backend.services import metricas as metricas_svc
from backend.services import addi as addi_svc

_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


router = APIRouter(prefix="/api/finanzas", tags=["finanzas"])


# ── Modelos ──────────────────────────────────────────────────────────

class PagoMP(BaseModel):
    mp_id: str
    valor_bruto: float
    comision: float
    valor_neto: float
    email: str
    nombre_pagador: str
    fecha_aprobado: str
    estado: str
    descripcion: str
    external_reference: str


class PagosMPResponse(BaseModel):
    pagos: list[PagoMP]
    total: int
    valor_bruto_total: float
    valor_neto_total: float
    comision_total: float
    desde: str
    hasta: str


class ResumenFinanzas(BaseModel):
    # COD
    cod_total:          float
    cod_pendientes:     float    # esperan despacho
    cod_transito:       float    # en ruta
    cod_novedades:      float    # con incidencia
    cod_entregados:     float    # COBRADOS (deben estar en liquidación Melonn)
    n_cod_total:        int
    n_cod_pendientes:   int
    n_cod_transito:     int
    n_cod_novedades:    int
    n_cod_entregados:   int
    # MercadoPago (últimos 30 días)
    mp_total:           float
    mp_neto:            float
    mp_comisiones:      float
    n_mp:               int
    # Meta
    fuente:             str
    fetched_at:         str


# ── Endpoint resumen ─────────────────────────────────────────────────

@router.get("/resumen", response_model=ResumenFinanzas)
def resumen(_: CurrentUser = Depends(get_current_user)) -> ResumenFinanzas:
    """Resumen financiero consolidado: COD activo, entregado, MP último mes."""
    # Cargar pedidos enriquecidos
    try:
        data = melonn_svc.obtener_pedidos(forzar_refresh=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn error: {exc}")

    pedidos = [metricas_svc.clasificar(p) for p in data["pedidos"]]
    cods = [p for p in pedidos if p.get("tipo_recaudo") == "Contraentrega"]

    def _val(arr, pred):
        return sum(p.get("valor_num", 0) for p in arr if pred(p))

    def _code(p): return int(p.get("estado_melonn_code") or 0)

    cod_pend     = [p for p in cods if _code(p) in (26, 29)]
    cod_tran     = [p for p in cods if _code(p) in (5, 7, 24, 28)]
    cod_nov      = [p for p in cods if p.get("es_novedad_visible")]
    cod_entreg   = [p for p in cods if _code(p) in (6, 8)]

    # MercadoPago — últimos 30 días
    mp_total = mp_neto = mp_com = 0.0
    n_mp = 0
    try:
        import mp_client as mp
        desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        pagos = mp.obtener_pagos(fecha_desde=desde, limit_total=1000)
        n_mp = len(pagos)
        mp_total = sum(p.get("valor_bruto", 0) for p in pagos)
        mp_neto  = sum(p.get("valor_neto", 0)  for p in pagos)
        mp_com   = sum(p.get("comision", 0)    for p in pagos)
    except Exception as e:
        print(f"[finanzas] MP error: {e}")

    return ResumenFinanzas(
        cod_total=sum(p.get("valor_num", 0) for p in cods),
        cod_pendientes=sum(p.get("valor_num", 0) for p in cod_pend),
        cod_transito=sum(p.get("valor_num", 0) for p in cod_tran),
        cod_novedades=sum(p.get("valor_num", 0) for p in cod_nov),
        cod_entregados=sum(p.get("valor_num", 0) for p in cod_entreg),
        n_cod_total=len(cods),
        n_cod_pendientes=len(cod_pend),
        n_cod_transito=len(cod_tran),
        n_cod_novedades=len(cod_nov),
        n_cod_entregados=len(cod_entreg),
        mp_total=mp_total,
        mp_neto=mp_neto,
        mp_comisiones=mp_com,
        n_mp=n_mp,
        fuente=data["fuente"],
        fetched_at=data["fetched_at"],
    )


# ── Endpoint MercadoPago ─────────────────────────────────────────────

@router.get("/mercadopago", response_model=PagosMPResponse)
def listar_pagos_mp(
    desde: Optional[str] = Query(default=None, description="YYYY-MM-DD, default últimos 30d"),
    hasta: Optional[str] = Query(default=None, description="YYYY-MM-DD, default hoy"),
    limit: int = Query(default=500, le=2000),
    _: CurrentUser = Depends(get_current_user),
) -> PagosMPResponse:
    """Pagos aprobados de MercadoPago en el rango dado (default últimos 30d)."""
    import mp_client as mp

    if not desde:
        desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not hasta:
        hasta = datetime.now().strftime("%Y-%m-%d")

    try:
        pagos_raw = mp.obtener_pagos(fecha_desde=desde, fecha_hasta=hasta, limit_total=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MercadoPago error: {exc}")

    pagos = [PagoMP(**p) for p in pagos_raw]
    return PagosMPResponse(
        pagos=pagos,
        total=len(pagos),
        valor_bruto_total=sum(p.valor_bruto for p in pagos),
        valor_neto_total=sum(p.valor_neto for p in pagos),
        comision_total=sum(p.comision for p in pagos),
        desde=desde,
        hasta=hasta,
    )


# ── Addi ────────────────────────────────────────────────────────────

class AddiStatusResponse(BaseModel):
    ok: bool
    error: Optional[str] = None
    base_url: Optional[str] = None
    token_path: Optional[str] = None


class TransaccionAddi(BaseModel):
    addi_id: str
    valor_bruto: float
    estado: str
    fecha: str
    email_cliente: str
    nombre_cliente: str
    external_ref: str


class TransaccionesAddiResponse(BaseModel):
    transacciones: list[TransaccionAddi]
    total: int
    valor_total: float
    desde: str
    hasta: str


@router.get("/addi/status", response_model=AddiStatusResponse)
def addi_status(_: CurrentUser = Depends(get_current_user)) -> AddiStatusResponse:
    """Verifica conectividad y credenciales Addi (intenta obtener access_token)."""
    r = addi_svc.status()
    return AddiStatusResponse(**r)


@router.get("/addi", response_model=TransaccionesAddiResponse)
def listar_addi(
    desde: Optional[str] = Query(default=None),
    hasta: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=2000),
    _: CurrentUser = Depends(get_current_user),
) -> TransaccionesAddiResponse:
    """Transacciones Addi en el rango dado (default últimos 30d)."""
    if not desde:
        desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not hasta:
        hasta = datetime.now().strftime("%Y-%m-%d")

    try:
        raw = addi_svc.obtener_transacciones(fecha_desde=desde, fecha_hasta=hasta, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Addi error: {exc}")

    transacciones = []
    for r in raw:
        r.pop("_raw", None)  # No exponemos el payload crudo al frontend
        transacciones.append(TransaccionAddi(**r))

    return TransaccionesAddiResponse(
        transacciones=transacciones,
        total=len(transacciones),
        valor_total=sum(t.valor_bruto for t in transacciones),
        desde=desde,
        hasta=hasta,
    )
