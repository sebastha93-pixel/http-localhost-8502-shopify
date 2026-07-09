"""
backend.api.whatsapp — Administración de la WhatsApp Cloud API propia (task #89).

Endpoints admin para validar la configuración y probar envíos ANTES de
conectar los flujos automáticos (agente logístico COD, notificaciones).

Variables en Railway:
  WHATSAPP_PHONE_NUMBER_ID  — id del número emisor (Meta → WhatsApp → API Setup)
  WHATSAPP_WABA_ID          — id de la cuenta de WhatsApp Business
  META_SYSTEM_USER_TOKEN    — token permanente del usuario del sistema (ya existe
                              para el webhook; debe tener acceso a la nueva WABA)

El webhook de recepción ya existe en /api/meta/webhook (backend/api/meta.py) y
procesa cualquier número de la app — el nuevo queda etiquetado por su
phone_number_id automáticamente.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.security import CurrentUser, require_role
from backend.services import whatsapp_cloud as wa

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


@router.get("/estado")
def estado(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Chequeo de credenciales contra Meta: número, nombre verificado y calidad."""
    return wa.estado_numero()


@router.get("/plantillas")
def plantillas(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Plantillas de la WABA y su estado de aprobación."""
    return wa.listar_plantillas()


class PruebaBody(BaseModel):
    telefono: str = Field(..., description="Celular destino (10 dígitos o con 57)")
    mensaje: str | None = Field(None, description="Texto libre (solo ventana 24h)")
    plantilla: str | None = Field(None, description="Nombre de plantilla aprobada")
    variables: list[str] | None = Field(None, description="Variables del body de la plantilla")
    idioma: str = Field("es", description="Código de idioma de la plantilla")


@router.post("/enviar-prueba")
def enviar_prueba(
    body: PruebaBody,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Envío de prueba. Con `plantilla` usa template (inicia conversación);
    con `mensaje` usa texto libre (requiere que el destino haya escrito
    en las últimas 24h)."""
    if not wa.configurado():
        raise HTTPException(503, "WhatsApp Cloud API no configurada: faltan variables en Railway")
    if body.plantilla:
        return wa.enviar_plantilla(body.telefono, body.plantilla,
                                   variables=body.variables, idioma=body.idioma)
    if body.mensaje:
        return wa.enviar_texto(body.telefono, body.mensaje)
    raise HTTPException(400, "Envía 'mensaje' o 'plantilla'")
