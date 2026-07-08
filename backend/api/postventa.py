"""
backend.api.postventa — Router del módulo MALE POSTVENTA IA (panel interno).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.security import CurrentUser, require_permission
from backend.services import postventa as svc
from backend.services import postventa_siigo as siigo_svc

router = APIRouter(prefix="/api/postventa", tags=["postventa"])


# ── Modelos ──────────────────────────────────────────────────────────
class CrearCasoIn(BaseModel):
    tipo: str
    reason: str
    customer_email: str = ""
    customer_phone: str = ""
    customer_name: str = ""
    shopify_order_id: str = ""
    shopify_order_name: str = ""
    subreason: str = ""
    priority: str = "media"
    source: str = "interno"
    assigned_to: Optional[str] = None


class ItemIn(BaseModel):
    original_sku: str = ""
    original_variant: str = ""
    original_price: float = 0
    requested_sku: str = ""
    requested_variant: str = ""
    requested_price: Optional[float] = None


class EvidenciaIn(BaseModel):
    file_url: str
    file_type: str = ""


class CambioEstadoIn(BaseModel):
    nuevo_estado: str
    motivo: str = ""


# ── Endpoints ────────────────────────────────────────────────────────
@router.get("/casos")
def listar(status: Optional[str] = None,
           _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    return svc.listar_casos(status=status)


@router.post("/casos")
def crear(body: CrearCasoIn,
          user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    try:
        caso = svc.crear_caso(**body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    svc.registrar_evento(caso["id"], "creado", f"Caso creado por {user.email}",
                         created_by=user.id)
    return caso


@router.get("/casos/{case_id}")
def detalle(case_id: str,
            _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    caso = svc.obtener_caso(case_id)
    if caso is None:
        raise HTTPException(404, "caso_no_encontrado")
    return caso


@router.patch("/casos/{case_id}/estado")
def cambiar_estado(case_id: str, body: CambioEstadoIn,
                   user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    try:
        return svc.cambiar_estado(case_id, body.nuevo_estado, actor=user.id,
                                  motivo=body.motivo)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/items")
def agregar_item(case_id: str, body: ItemIn,
                 _: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    return svc.agregar_item(case_id, **body.model_dump())


@router.post("/casos/{case_id}/evidencia")
def agregar_evidencia(case_id: str, body: EvidenciaIn,
                      user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    return svc.agregar_evidencia(case_id, body.file_url, body.file_type,
                                 uploaded_by=user.id)


@router.get("/shopify")
def buscar_shopify(email: str = "", telefono: str = "",
                   _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    return svc.pedido_shopify(email=email, telefono=telefono)


@router.get("/dashboard")
def dashboard(_: CurrentUser = Depends(require_permission("postventa", "ver"))):
    return svc.contadores_dashboard()


@router.get("/siigo/discovery")
def siigo_discovery(
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """FASE 0 del motor fiscal: descubrimiento SOLO LECTURA de la config Siigo
    (tipos de doc NC/FV, impuestos, formas de pago, vendedores) + muestra de
    facturas para ubicar el enlace con el pedido Shopify. No emite nada."""
    return siigo_svc.diagnostico()
