"""
backend.services.siigo — Cliente Siigo API para el cruce de costeo real.

Los confeccionistas se contabilizan como DOCUMENTO SOPORTE (DS-1-XXXX) en
Siigo Nube: producto "Servicio de Confección REF <referencia>", cantidad =
unidades del lote, valor unitario = precio pactado. Este módulo trae esos
documentos y los cruza contra la hoja de ruta del lote.

ENV requeridos (Railway Variables — mismos de atlas/Vercel):
  SIIGO_USERNAME, SIIGO_ACCESS_KEY, SIIGO_PARTNER_ID

Gotchas conocidos (ver memoria de sesiones):
  - /purchases IGNORA filtros de fecha → paginar todo y filtrar client-side.
  - Rate limit duro (429) → backoff exponencial.
  - `price` de items es SIN IVA; el `total` del doc incluye impuestos.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Optional

import httpx

log = logging.getLogger("siigo")

SIIGO_BASE = os.getenv("SIIGO_BASE_URL", "https://api.siigo.com/v1")
SIIGO_AUTH = "https://api.siigo.com/auth"

_token_cache: dict[str, Any] = {"token": None, "expira": 0.0}
_data_cache: dict[str, tuple[float, Any]] = {}


def siigo_configurado() -> bool:
    return bool(os.getenv("SIIGO_USERNAME") and os.getenv("SIIGO_ACCESS_KEY")
                and os.getenv("SIIGO_PARTNER_ID"))


def _get_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expira"] > now + 60:
        return _token_cache["token"]
    username = os.getenv("SIIGO_USERNAME")
    access_key = os.getenv("SIIGO_ACCESS_KEY")
    partner_id = os.getenv("SIIGO_PARTNER_ID")
    if not (username and access_key and partner_id):
        raise RuntimeError("siigo_env_missing")
    r = httpx.post(SIIGO_AUTH, json={"username": username, "access_key": access_key},
                   headers={"Partner-Id": partner_id}, timeout=30)
    r.raise_for_status()
    data = r.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expira"] = now + float(data.get("expires_in", 3600))
    return _token_cache["token"]


def siigo_get(path: str, params: Optional[dict] = None) -> dict:
    """GET con retry/backoff para el rate limit de Siigo (~1 req/s)."""
    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Partner-Id": os.getenv("SIIGO_PARTNER_ID", ""),
    }
    last = ""
    for intento in range(5):
        r = httpx.get(SIIGO_BASE + path, params=params or {}, headers=headers, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            espera = min(2 ** intento, 8)
            retry_after = r.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                espera = int(retry_after)
            time.sleep(espera)
            last = f"429 intento {intento + 1}"
            continue
        raise RuntimeError(f"siigo_get {path} HTTP {r.status_code}: {r.text[:200]}")
    raise RuntimeError(f"siigo_get {path} rate-limited tras reintentos ({last})")


# ═══════════════════════════════════════════════════════════════════════
# DOCUMENTOS SOPORTE (DS) — pagos a confeccionistas/terminación
# ═══════════════════════════════════════════════════════════════════════

# \bREF\b + separador OBLIGATORIO: sin él, "Referencia 505" matchearía
# y extraería "ERENCIA" en vez de la referencia real.
REF_RE = re.compile(r"\bREF(?:ERENCIA)?\b[\s.:#-]+([A-Z0-9][A-Z0-9\-]*)", re.IGNORECASE)


def _extraer_ref(texto: str) -> Optional[str]:
    m = REF_RE.search(texto or "")
    return m.group(1).upper().strip("-") if m else None


def listar_documentos_soporte(*, desde: Optional[str] = None,
                              force: bool = False) -> list[dict]:
    """Trae TODOS los documentos de /purchases cuyo consecutivo empieza por DS.
    Cache 10 min (el rate limit de Siigo no perdona).

    Devuelve por documento:
      { ds, fecha, proveedor_id, proveedor_nombre, total, balance, items: [
          { descripcion, ref, cantidad, valor_unitario, total_sin_iva } ] }
    """
    cache_key = f"ds:{desde}"
    hit = _data_cache.get(cache_key)
    if hit and not force and (time.time() - hit[0] < 600):
        return hit[1]

    def _parse_items(raw: list) -> list[dict]:
        items = []
        for it in raw or []:
            desc = it.get("description") or it.get("name") or ""
            cant = float(it.get("quantity") or 0)
            precio = float(it.get("price") or 0)
            items.append({
                "descripcion":    desc,
                "ref":            _extraer_ref(desc),
                "cantidad":       cant,
                "valor_unitario": precio,
                "total_sin_iva":  round(cant * precio, 2),
            })
        return items

    docs: list[dict] = []
    page = 1
    while page <= 50:
        data = siigo_get("/purchases", {"page": page, "page_size": 100})
        results = data.get("results") or []
        if not results:
            break
        for p in results:
            name = p.get("name") or ""
            if not name.upper().startswith("DS"):
                continue
            fecha = (p.get("date") or "")[:10]
            if desde and fecha and fecha < desde:
                continue
            sup = p.get("supplier") or {}
            docs.append({
                "id":               p.get("id"),
                "ds":               name,
                "fecha":            fecha,
                "proveedor_id":     sup.get("identification"),
                "proveedor_nombre": (sup.get("branch_office") or sup.get("name") or ""),
                "total":            float(p.get("total") or 0),
                "balance":          float(p.get("balance") or 0),
                "items":            _parse_items(p.get("items")),
            })
        # Cortar por tamaño de página, no por total_results — si Siigo omite
        # pagination.total_results, `or 0` cortaría tras la página 1 en silencio.
        if len(results) < 100:
            break
        page += 1

    # El listado de /purchases a veces NO incluye items (descripción/REF).
    # Para esos, pedir el detalle uno a uno — con pausa por el rate limit.
    pendientes = [d for d in docs if not d["items"] and d.get("id")]
    if len(pendientes) > 150:
        log.warning(f"[siigo] {len(pendientes)} DS sin items en listado; "
                    f"solo se detallan 150 — el resto no cruzará este ciclo")
    for d in pendientes[:150]:
        try:
            detalle = siigo_get(f"/purchases/{d['id']}")
            d["items"] = _parse_items(detalle.get("items"))
            time.sleep(0.4)
        except Exception as e:
            log.warning(f"[siigo] detalle DS {d['ds']} fallo: {e}")

    _data_cache[cache_key] = (time.time(), docs)
    return docs
