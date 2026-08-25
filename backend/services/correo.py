"""
backend.services.correo — envío de correos transaccionales por Resend.

POR QUÉ ESTE MÓDULO EXISTE APARTE. `backend.services.produccion` ya sabe mandar
correos (`_enviar_por_resend`), pero es un módulo de más de 3.000 líneas que
arrastra Supabase, Siigo, Shopify y el generador de PDF. Importarlo desde
`auth` para mandar un correo de recuperación significaría que el login no puede
arrancar si algo de producción falla al importarse — un acoplamiento absurdo
para dos peticiones HTTP.

Acá vive lo mínimo, con las MISMAS variables de entorno (RESEND_API_KEY,
RESEND_FROM). Sí, es una segunda implementación del mismo envío; unificarlas
implica tocar el módulo de producción, y eso es una refactorización que merece
su propio cambio, no un efecto colateral de arreglar un login.
"""
from __future__ import annotations

import os

import httpx


TIMEOUT_S = 15.0


def disponible() -> bool:
    """Si hay con qué mandar. Se consulta antes de prometerle algo al usuario."""
    return bool(os.environ.get("RESEND_API_KEY", "").strip())


def enviar(*, para: str, asunto: str, html: str, texto: str = "") -> dict:
    """Manda un correo. Devuelve {"ok": bool, "id": str|None, "error": str}.

    No levanta excepción a propósito: quien llama decide qué hacer. En el flujo
    de recuperación, por ejemplo, la respuesta al usuario es la misma haya
    salido el correo o no —para no revelar qué correos existen—, pero el error
    sí queda en los logs del servidor.
    """
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "id": None, "error": "sin_RESEND_API_KEY"}
    if not para:
        return {"ok": False, "id": None, "error": "sin_destinatario"}

    remitente = os.environ.get("RESEND_FROM", "orden-corte@maledenim.com").strip()
    cuerpo: dict = {
        "from": remitente,
        "to": [para],
        "subject": asunto,
        "html": html,
    }
    if texto:
        cuerpo["text"] = texto

    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=cuerpo,
            timeout=TIMEOUT_S,
        )
        if r.status_code >= 300:
            return {"ok": False, "id": None,
                    "error": f"resend {r.status_code}: {r.text[:300]}"}
        return {"ok": True, "id": ((r.json() or {}).get("id")), "error": ""}
    except Exception as e:
        return {"ok": False, "id": None, "error": f"{type(e).__name__}: {e}"[:300]}
