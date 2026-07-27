"""
backend.services.shopify_auth — Token de Admin API de Shopify (modelo 2026).

Desde el 1-ene-2026 Shopify ya no emite tokens permanentes `shpat_` para apps
nuevas. Las apps del dev dashboard entregan Client ID + Secret que se cambian
por un token de ~24h vía el grant `client_credentials`.

Este módulo centraliza esa obtención con dos garantías:

1. **Cache con refresh anticipado** — el token se pide una vez y se reusa hasta
   5 minutos antes de expirar. Una petición no dispara un intercambio nuevo.
2. **Fallback al token legacy** — si no hay CLIENT_ID/SECRET, o el intercambio
   falla, se usa SHOPIFY_ACCESS_TOKEN. La migración no puede tumbar el OS:
   comercial, inventario, clientes y postventa dependen de esto.

ENV:
  SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET  → modelo nuevo (24h, con escritura)
  SHOPIFY_ACCESS_TOKEN                       → legacy shpat_ (solo lectura)
  SHOPIFY_STORE                              → male-denim-5524.myshopify.com
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

import httpx

log = logging.getLogger("shopify_auth")

# Margen para refrescar antes de que expire de verdad.
_MARGEN_SEG = 300
_lock = threading.Lock()
_cache: dict = {"token": None, "expira": 0.0, "fuente": None}


def _store() -> str:
    return os.environ.get("SHOPIFY_STORE", "").strip()


def _credenciales_app() -> tuple[str, str]:
    return (os.environ.get("SHOPIFY_CLIENT_ID", "").strip(),
            os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip())


def _token_legacy() -> str:
    return os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()


def _intercambiar() -> Optional[dict]:
    """Cambia Client ID + Secret por un token de ~24h. None si no se puede."""
    client_id, client_secret = _credenciales_app()
    store = _store()
    if not (client_id and client_secret and store):
        return None
    try:
        r = httpx.post(
            f"https://{store}/admin/oauth/access_token",
            json={"client_id": client_id, "client_secret": client_secret,
                  "grant_type": "client_credentials"},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if r.status_code != 200:
            log.warning(f"[shopify_auth] intercambio fallo {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        token = data.get("access_token")
        if not token:
            log.warning("[shopify_auth] respuesta sin access_token")
            return None
        return {"token": token,
                "expira": time.time() + float(data.get("expires_in", 86000)),
                "scope": data.get("scope", "")}
    except Exception as e:  # noqa: BLE001
        log.warning(f"[shopify_auth] excepcion en intercambio: {e}")
        return None


def token() -> str:
    """Token vigente para la Admin API.

    Prefiere el modelo nuevo (client_credentials). Si no está configurado o
    falla, cae al legacy — así la migración nunca deja el OS sin Shopify.
    """
    with _lock:
        ahora = time.time()
        if _cache["token"] and _cache["expira"] > ahora + _MARGEN_SEG:
            return _cache["token"]

        nuevo = _intercambiar()
        if nuevo:
            _cache.update({"token": nuevo["token"], "expira": nuevo["expira"],
                           "fuente": "client_credentials"})
            return nuevo["token"]

        legacy = _token_legacy()
        if legacy:
            # El legacy no expira; se cachea largo para no reintentar el
            # intercambio en cada request cuando no hay credenciales de app.
            _cache.update({"token": legacy, "expira": ahora + 3600,
                           "fuente": "legacy"})
            return legacy

        raise RuntimeError("shopify_sin_credenciales")


def fuente_actual() -> Optional[str]:
    """'client_credentials' | 'legacy' | None. Para diagnóstico."""
    return _cache.get("fuente")


def invalidar() -> None:
    """Fuerza pedir un token nuevo en la próxima llamada."""
    with _lock:
        _cache.update({"token": None, "expira": 0.0, "fuente": None})


def diagnostico() -> dict:
    """Estado de la autenticación, sin exponer secretos."""
    client_id, client_secret = _credenciales_app()
    tiene_app = bool(client_id and client_secret)
    try:
        t = token()
        ok = bool(t)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "modelo_nuevo_configurado": tiene_app,
                "legacy_configurado": bool(_token_legacy())}
    return {
        "ok": ok,
        "fuente": fuente_actual(),
        "modelo_nuevo_configurado": tiene_app,
        "legacy_configurado": bool(_token_legacy()),
        "expira_en_min": round(max(0.0, _cache["expira"] - time.time()) / 60, 1),
    }
