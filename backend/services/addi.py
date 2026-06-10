"""
backend.services.addi — Cliente Addi (financiación).

OAuth2 client_credentials flow. Token cacheado en memoria hasta su expiración.

Variables de entorno necesarias:
  ADDI_CLIENT_ID
  ADDI_CLIENT_SECRET
  ADDI_BASE_URL          (default: https://api.addi.com)
  ADDI_TOKEN_PATH        (default: /v1/oauth/token; ajustar según docs)
  ADDI_TRANSACTIONS_PATH (default: /v1/transactions; ajustar según docs)

Cuando llegue la documentación oficial, ajustar los paths arriba y los
parsers de response en _parse_transaction().
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _base_url() -> str:
    return _env("ADDI_BASE_URL", "https://api.addi.com").rstrip("/")


def _token_path() -> str:
    p = _env("ADDI_TOKEN_PATH", "/v1/oauth/token")
    if not p.startswith("/"):
        p = "/" + p
    return p


def _transactions_path() -> str:
    p = _env("ADDI_TRANSACTIONS_PATH", "/v1/transactions")
    if not p.startswith("/"):
        p = "/" + p
    return p


def credenciales_ok() -> bool:
    return bool(_env("ADDI_CLIENT_ID")) and bool(_env("ADDI_CLIENT_SECRET"))


# ── OAuth2 token cache ───────────────────────────────────────────────

_token_cache: dict = {"access_token": "", "expires_at": 0.0}


def get_token(forzar_refresh: bool = False) -> Optional[str]:
    """
    Obtiene access_token via client_credentials. Cacheado hasta expiración.
    """
    if not credenciales_ok():
        return None

    now = time.time()
    if not forzar_refresh and _token_cache["access_token"] and now < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]

    url = _base_url() + _token_path()
    payload = {
        "grant_type": "client_credentials",
        "client_id": _env("ADDI_CLIENT_ID"),
        "client_secret": _env("ADDI_CLIENT_SECRET"),
    }

    # Intentar formato JSON primero, luego form-encoded (algunos APIs varían)
    for content_type, data_arg in [
        ("json", {"json": payload}),
        ("form", {"data": payload}),
    ]:
        try:
            r = requests.post(
                url,
                timeout=15,
                headers={"Accept": "application/json"},
                **data_arg,
            )
            if r.status_code >= 400:
                continue
            data = r.json()
            token = data.get("access_token") or data.get("token") or data.get("data", {}).get("access_token")
            if not token:
                continue
            expires_in = int(data.get("expires_in") or data.get("expiresIn") or 3600)
            _token_cache["access_token"] = token
            _token_cache["expires_at"]  = now + expires_in
            return token
        except Exception as e:
            print(f"[addi] Token error ({content_type}): {e}")
            continue

    return None


def _auth_headers() -> dict:
    token = get_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


# ── Endpoints de negocio (placeholders hasta confirmar con docs) ─────

def status() -> dict:
    """Verifica conexión: intenta obtener token sin hacer request adicional."""
    if not credenciales_ok():
        return {"ok": False, "error": "Credenciales no configuradas en Railway"}
    tok = get_token(forzar_refresh=True)
    if not tok:
        return {
            "ok": False,
            "error": f"No se pudo obtener token. Verifica ADDI_TOKEN_PATH (actual: {_token_path()})",
            "base_url": _base_url(),
            "token_path": _token_path(),
        }
    return {
        "ok": True,
        "base_url": _base_url(),
        "token_path": _token_path(),
        "expires_at": _token_cache["expires_at"],
    }


def obtener_transacciones(
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """
    Lista transacciones/créditos aprobados.

    NOTA: el path exacto y parámetros dependen de la doc de Addi.
    Implementación tentativa basada en patrones REST estándar.
    Cuando tengamos la doc, ajustar paths/params/parser aquí.
    """
    if not credenciales_ok():
        return []

    params = {"limit": limit}
    if fecha_desde:
        params["from"] = fecha_desde
    if fecha_hasta:
        params["to"] = fecha_hasta

    url = _base_url() + _transactions_path()
    try:
        r = requests.get(url, headers=_auth_headers(), params=params, timeout=30)
        if r.status_code == 401:
            # Token expirado → refresh y reintentar una vez
            r = requests.get(url, headers=_auth_headers(), params=params, timeout=30)
        if r.status_code >= 400:
            print(f"[addi] GET {url} → {r.status_code}: {r.text[:200]}")
            return []
        data = r.json()
        # Algunos APIs envuelven en {data: [...]}, otros devuelven array directo
        items = data if isinstance(data, list) else (data.get("data") or data.get("transactions") or data.get("results") or [])
        return [_parse_transaction(item) for item in items if item]
    except Exception as e:
        print(f"[addi] Error transacciones: {e}")
        return []


def _parse_transaction(item: dict) -> dict:
    """
    Normaliza una transacción Addi a campos consistentes con nuestro modelo.
    Ajustar nombres de keys cuando confirmemos contra docs reales.
    """
    return {
        "addi_id":       str(item.get("id") or item.get("transaction_id") or item.get("loanId") or ""),
        "valor_bruto":   float(item.get("amount") or item.get("total") or item.get("totalAmount") or 0),
        "estado":        str(item.get("status") or item.get("state") or ""),
        "fecha":         str(item.get("created_at") or item.get("date") or item.get("approved_at") or "")[:10],
        "email_cliente": str(item.get("customer_email") or item.get("email") or ""),
        "nombre_cliente":str(item.get("customer_name") or item.get("name") or ""),
        "external_ref":  str(item.get("external_reference") or item.get("order_id") or item.get("reference") or ""),
        # Raw payload por si necesitamos campos no normalizados
        "_raw": item,
    }
