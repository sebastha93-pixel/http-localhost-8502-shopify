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
from backend.services import postventa_shopify as shopify_svc
from backend.services import postventa_fiscal as fiscal_svc

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


@router.post("/casos/{case_id}/fiscal/preview")
def fiscal_preview(case_id: str,
                   _: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Arma la nota credito y la muestra. NO emite nada en Siigo."""
    try:
        return fiscal_svc.preview_nota_credito(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/fiscal/emitir")
def fiscal_emitir(case_id: str,
                  user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Emite en Siigo la NC previsualizada. Requiere confirmacion del equipo."""
    try:
        return fiscal_svc.emitir_nota_credito(case_id, actor=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"siigo: {str(e)[:300]}")


@router.post("/casos/{case_id}/fiscal/factura/preview")
def fiscal_factura_preview(case_id: str,
                           _: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Arma la factura del reemplazo (consume el anticipo). NO emite."""
    try:
        return fiscal_svc.preview_factura_reemplazo(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/fiscal/factura/emitir")
def fiscal_factura_emitir(case_id: str,
                          user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Emite en Siigo la factura del reemplazo. Requiere confirmacion."""
    try:
        return fiscal_svc.emitir_factura_reemplazo(case_id, actor=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"siigo: {str(e)[:300]}")


@router.get("/casos/{case_id}/fiscal/items-factura")
def fiscal_items_factura(case_id: str,
                         _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Items de la factura original del pedido, para elegir cual se devuelve."""
    try:
        return fiscal_svc.items_factura_del_caso(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"siigo: {str(e)[:300]}")


@router.get("/casos/{case_id}/timeline")
def timeline(case_id: str,
             _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Historial del caso: estados, notificaciones, documentos fiscales."""
    return svc.timeline_caso(case_id)


@router.get("/casos/{case_id}/items")
def items(case_id: str,
          _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Items del caso (lo que se devuelve y su reemplazo)."""
    return svc.items_caso(case_id)


@router.get("/shopify/discovery")
def shopify_discovery(
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Que permisos tiene el token de Shopify: si puede descontar ventas,
    registrar retornos o reservar inventario. Solo lectura."""
    return shopify_svc.diagnostico()


class GuiaIn(BaseModel):
    guia: str
    transportadora: str = ""


class RecepcionIn(BaseModel):
    notas: str = ""


@router.get("/casos/{case_id}/logistica")
def logistica(case_id: str,
              _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Guias, fechas y costos del caso."""
    return svc.obtener_logistica(case_id) or {}


@router.post("/casos/{case_id}/logistica/guia-retorno")
def guia_retorno(case_id: str, body: GuiaIn,
                 user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Asigna la guia de la devolucion y pone el caso en transito."""
    try:
        return svc.registrar_guia_retorno(case_id, guia=body.guia,
                                          transportadora=body.transportadora,
                                          actor=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/logistica/recibir")
def recibir(case_id: str, body: RecepcionIn,
            user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Confirma que la prenda llego a bodega. Desbloquea el despacho."""
    return svc.confirmar_recepcion(case_id, actor=user.id, notas=body.notas)


@router.post("/casos/{case_id}/logistica/despachar")
def despachar(case_id: str, body: GuiaIn,
              user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Registra el despacho del reemplazo. Exige que el retorno ya llego."""
    try:
        return svc.registrar_despacho(case_id, guia=body.guia,
                                      transportadora=body.transportadora,
                                      actor=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/impacto-ventas")
def impacto_ventas(desde: str = "", hasta: str = "",
                   _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Lo que la postventa le resta a las ventas del periodo (venta neta real)."""
    return svc.impacto_ventas(desde=desde, hasta=hasta)
