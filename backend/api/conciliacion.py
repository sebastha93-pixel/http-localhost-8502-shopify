"""
backend.api.conciliacion — Conciliación de pedidos COD entregados vs
liquidaciones recibidas de Melonn.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.security import CurrentUser, get_current_user, require_role, require_permission
from backend.services import melonn as melonn_svc
from backend.services import metricas as metricas_svc
from backend.services import conciliacion as cnc_svc


router = APIRouter(prefix="/api/conciliacion", tags=["conciliacion"])


# ── Modelos ──────────────────────────────────────────────────────────

class PedidoConciliacion(BaseModel):
    orden_tienda: str
    orden_melonn: str
    nombre_comprador: str
    ciudad_destino: str
    zona: str
    transportadora: str
    fecha_entrega: Optional[str] = None
    fecha_despacho: Optional[str] = None
    valor_cod: float
    dias_desde_entrega: int
    # Estado de liquidación
    liquidado: bool
    monto_liquidado: Optional[float] = None
    fecha_liquidacion: Optional[str] = None
    referencia: Optional[str] = None
    diferencia: Optional[float] = None    # monto_liquidado - valor_cod (puede ser 0 o negativo)
    autor_liquidacion: Optional[str] = None


class ResumenConciliacion(BaseModel):
    total_entregado: float
    total_liquidado: float
    total_pendiente: float
    n_total: int
    n_liquidados: int
    n_pendientes: int
    n_con_diferencia: int


class CodResponse(BaseModel):
    resumen: ResumenConciliacion
    pedidos: list[PedidoConciliacion]


class LiquidarBody(BaseModel):
    monto: float = Field(gt=0)
    fecha: str = Field(description="YYYY-MM-DD")
    referencia: str = ""
    nota: str = ""


# ── Helpers ──────────────────────────────────────────────────────────

def _construir_pedido(p: dict, liq: dict | None) -> PedidoConciliacion:
    valor = float(p.get("valor_num") or 0)
    fecha_entrega = p.get("fecha_entrega") or ""
    dias = 0
    if fecha_entrega:
        try:
            dias = max(0, (date.today() - date.fromisoformat(str(fecha_entrega))).days)
        except Exception:
            pass

    liquidado = bool(liq)
    monto_liq = float(liq.get("monto_liquidado") or 0) if liq else None
    diferencia = (monto_liq - valor) if (liq and monto_liq is not None) else None

    return PedidoConciliacion(
        orden_tienda=str(p.get("orden_tienda") or ""),
        orden_melonn=str(p.get("orden_melonn") or ""),
        nombre_comprador=str(p.get("nombre_comprador") or ""),
        ciudad_destino=str(p.get("ciudad_destino") or ""),
        zona=str(p.get("zona") or ""),
        transportadora=str(p.get("transportadora") or ""),
        fecha_entrega=fecha_entrega or None,
        fecha_despacho=str(p.get("fecha_despacho") or "") or None,
        valor_cod=valor,
        dias_desde_entrega=dias,
        liquidado=liquidado,
        monto_liquidado=monto_liq,
        fecha_liquidacion=(liq.get("fecha_liquidacion") if liq else None),
        referencia=(liq.get("referencia") if liq else None),
        diferencia=diferencia,
        autor_liquidacion=(liq.get("autor") if liq else None),
    )


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/cod", response_model=CodResponse)
def listar_cod(_: CurrentUser = Depends(get_current_user)) -> CodResponse:
    """
    Lista pedidos COD entregados con su estado de liquidación.
    """
    try:
        data = melonn_svc.obtener_pedidos(forzar_refresh=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn error: {exc}")

    pedidos = [metricas_svc.clasificar(p) for p in data["pedidos"]]
    # COD entregados (codes 6 o 8)
    entregados = [
        p for p in pedidos
        if p.get("tipo_recaudo") == "Contraentrega"
        and int(p.get("estado_melonn_code") or 0) in (6, 8)
    ]

    liquidaciones = cnc_svc.cargar_map()

    items: list[PedidoConciliacion] = []
    for p in entregados:
        key = p.get("orden_melonn") or p.get("orden_tienda") or ""
        # liquidaciones puede tener key tanto orden_tienda como orden_melonn
        liq = liquidaciones.get(p.get("orden_tienda", "")) or liquidaciones.get(key)
        items.append(_construir_pedido(p, liq))

    # Ordenar por dias_desde_entrega desc (los más atrasados arriba)
    items.sort(key=lambda x: (x.liquidado, -x.dias_desde_entrega))

    total_entregado = sum(i.valor_cod for i in items)
    liq_items = [i for i in items if i.liquidado]
    total_liquidado = sum((i.monto_liquidado or 0) for i in liq_items)
    pend_items = [i for i in items if not i.liquidado]
    total_pendiente = sum(i.valor_cod for i in pend_items)
    n_con_diff = sum(1 for i in liq_items if i.diferencia and abs(i.diferencia) > 1)

    resumen = ResumenConciliacion(
        total_entregado=total_entregado,
        total_liquidado=total_liquidado,
        total_pendiente=total_pendiente,
        n_total=len(items),
        n_liquidados=len(liq_items),
        n_pendientes=len(pend_items),
        n_con_diferencia=n_con_diff,
    )
    return CodResponse(resumen=resumen, pedidos=items)


@router.post("/{orden}/liquidar")
def liquidar(
    orden: str,
    body: LiquidarBody,
    user: CurrentUser = Depends(require_permission("finanzas", "modificar")),
) -> dict:
    """Marcar un pedido como liquidado por Melonn."""
    try:
        # Validar fecha
        datetime.fromisoformat(body.fecha)
    except Exception:
        raise HTTPException(400, "Formato de fecha inválido. Usa YYYY-MM-DD.")

    try:
        r = cnc_svc.upsert(
            orden,
            monto=body.monto,
            fecha=body.fecha,
            referencia=body.referencia,
            nota=body.nota,
            autor=user.nombre,
        )
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "liquidacion": r}


@router.delete("/{orden}/liquidar")
def desliquidar(
    orden: str,
    _: CurrentUser = Depends(require_permission("finanzas", "borrar")),
) -> dict:
    """Eliminar la liquidación de un pedido (marcar como no liquidado)."""
    ok = cnc_svc.eliminar(orden)
    if not ok:
        raise HTTPException(500, "No se pudo eliminar")
    return {"ok": True}
