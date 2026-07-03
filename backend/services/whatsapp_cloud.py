"""
backend.services.whatsapp_cloud — Envío automático por WhatsApp Cloud API.

Requiere la WABA propia (tarea #89):
  WHATSAPP_PHONE_NUMBER_ID  — número emisor (Meta for Developers → API Setup)
  META_SYSTEM_USER_TOKEN    — ya existe en Railway (mismo del webhook)

Mientras la WABA no esté configurada, `configurado()` devuelve False y los
flujos caen al modo manual (el frontend abre wa.me con el mensaje armado).
Cuando Sebastián complete la tarea #89, esto se activa solo.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("whatsapp")

GRAPH = "https://graph.facebook.com/v23.0"


def configurado() -> bool:
    return bool(os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
                and os.environ.get("META_SYSTEM_USER_TOKEN", "").strip())


def _normalizar(telefono: str) -> str:
    clean = "".join(c for c in (telefono or "") if c.isdigit())
    if not clean:
        return ""
    return clean if clean.startswith("57") else f"57{clean}"


def enviar_texto(telefono: str, mensaje: str) -> dict:
    """Mensaje de texto libre (solo válido dentro de ventana de 24h de sesión).
    Para iniciar conversación se necesita plantilla — ver enviar_plantilla."""
    if not configurado():
        return {"enviado": False, "motivo": "whatsapp_no_configurado"}
    tel = _normalizar(telefono)
    if not tel:
        return {"enviado": False, "motivo": "sin_telefono"}
    phone_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"].strip()
    token = os.environ["META_SYSTEM_USER_TOKEN"].strip()
    try:
        r = httpx.post(
            f"{GRAPH}/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"messaging_product": "whatsapp", "to": tel,
                  "type": "text", "text": {"body": mensaje[:4000]}},
            timeout=20,
        )
        ok = r.status_code < 400
        if not ok:
            log.warning(f"[wa] envio fallo {r.status_code}: {r.text[:200]}")
        return {"enviado": ok, "detalle": None if ok else r.text[:200]}
    except Exception as e:
        log.warning(f"[wa] envio excepcion: {e}")
        return {"enviado": False, "motivo": str(e)[:200]}


def enviar_plantilla(telefono: str, plantilla: str,
                     variables: Optional[list] = None,
                     idioma: str = "es") -> dict:
    """Plantilla aprobada por Meta (inicia conversación). Ej: lote_asignado."""
    if not configurado():
        return {"enviado": False, "motivo": "whatsapp_no_configurado"}
    tel = _normalizar(telefono)
    if not tel:
        return {"enviado": False, "motivo": "sin_telefono"}
    phone_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"].strip()
    token = os.environ["META_SYSTEM_USER_TOKEN"].strip()
    componentes = []
    if variables:
        componentes = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)[:500]} for v in variables],
        }]
    try:
        r = httpx.post(
            f"{GRAPH}/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"messaging_product": "whatsapp", "to": tel, "type": "template",
                  "template": {"name": plantilla,
                               "language": {"code": idioma},
                               "components": componentes}},
            timeout=20,
        )
        ok = r.status_code < 400
        if not ok:
            log.warning(f"[wa] plantilla fallo {r.status_code}: {r.text[:200]}")
        return {"enviado": ok, "detalle": None if ok else r.text[:200]}
    except Exception as e:
        log.warning(f"[wa] plantilla excepcion: {e}")
        return {"enviado": False, "motivo": str(e)[:200]}
