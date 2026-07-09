"""
backend.services.whatsapp_cloud — Envío automático por WhatsApp Cloud API.

Requiere la WABA propia (tarea #89):
  WHATSAPP_PHONE_NUMBER_ID  — número emisor (Meta for Developers → API Setup)
  WHATSAPP_TOKEN            — token permanente de la app nueva de WhatsApp
                              (fallback: META_SYSTEM_USER_TOKEN de la app vieja)

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


def _token() -> str:
    """Token de la app de WhatsApp. La WABA nueva vive en su propia app de Meta,
    con su propio token (WHATSAPP_TOKEN); si no está, cae al token del sistema
    de la app vieja (META_SYSTEM_USER_TOKEN) por si comparten usuario."""
    return (os.environ.get("WHATSAPP_TOKEN", "").strip()
            or os.environ.get("META_SYSTEM_USER_TOKEN", "").strip())


def configurado() -> bool:
    return bool(os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip() and _token())


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
    token = _token()
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
    token = _token()
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


def estado_numero() -> dict:
    """Valida credenciales contra Meta: datos del número emisor.
    Devuelve display_phone_number, verified_name y quality_rating."""
    if not configurado():
        return {"configurado": False,
                "falta": (["WHATSAPP_PHONE_NUMBER_ID"] if not os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip() else [])
                         + (["WHATSAPP_TOKEN"] if not _token() else [])}
    phone_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"].strip()
    token = _token()
    try:
        r = httpx.get(
            f"{GRAPH}/{phone_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "display_phone_number,verified_name,quality_rating,code_verification_status"},
            timeout=20,
        )
        if r.status_code >= 400:
            return {"configurado": True, "ok": False, "error": r.text[:300]}
        return {"configurado": True, "ok": True, **r.json()}
    except Exception as e:
        return {"configurado": True, "ok": False, "error": str(e)[:300]}


def listar_plantillas() -> dict:
    """Plantillas de la WABA con su estado de aprobación (requiere WHATSAPP_WABA_ID)."""
    waba_id = os.environ.get("WHATSAPP_WABA_ID", "").strip()
    token = _token()
    if not waba_id or not token:
        return {"ok": False, "error": "falta WHATSAPP_WABA_ID o WHATSAPP_TOKEN"}
    try:
        r = httpx.get(
            f"{GRAPH}/{waba_id}/message_templates",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "name,status,language,category,components", "limit": 100},
            timeout=20,
        )
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:300]}
        data = r.json().get("data") or []
        return {"ok": True, "total": len(data), "plantillas": [
            {"nombre": t.get("name"), "estado": t.get("status"),
             "idioma": t.get("language"), "categoria": t.get("category")}
            for t in data
        ]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
