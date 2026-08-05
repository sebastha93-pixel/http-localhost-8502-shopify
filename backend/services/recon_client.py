"""recon_client.py — el OS le pregunta al módulo de conciliación bancaria.

QUÉ CONECTA (2026-08-05). La conciliación bancaria vive en su propio servicio
(`male-denim-reconciliation` en Railway) con su propia API y su propio schema
`recon` en la MISMA Supabase. El OS no puede leer ese schema: PostgREST solo
expone `public` y `graphql_public`. Así que la costura es HTTP.

POR QUÉ HTTP Y NO LEER LA BASE DIRECTO. Es la misma decisión que Sebastián tomó
para n8n: quien tiene la lógica es el servicio, no el que consulta. Si el OS
leyera `recon` por su cuenta tendría que reimplementar qué significa "liquidado",
"en excepción" o "pendiente" — y el día que el motor cambie una regla, el OS
mostraría otra cosa sin que nadie lo note. Con HTTP hay una sola definición.

REGLA DE ORO: si el servicio de conciliación no responde, el módulo financiero
del OS NO se cae. Devuelve `disponible: False` y la pantalla lo dice. Un tablero
de plata que muestra un error es malo; uno que muestra ceros sin avisar es peor,
porque se lee como "no hay nada pendiente".
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

# El servicio responde en ~0,5 s; 12 s es holgado y evita que una pantalla del OS
# quede colgada esperando a otro servicio.
_TIMEOUT = 12.0
# El resumen son agregados de miles de filas: no cambia de un segundo a otro y la
# pantalla financiera se abre varias veces al día.
_TTL_RESUMEN = 90
_cache: dict[str, tuple[float, Any]] = {}


def configurado() -> bool:
    return bool(os.getenv("RECON_API_URL") and os.getenv("RECON_API_KEY"))


def _base() -> str:
    return (os.getenv("RECON_API_URL") or "").rstrip("/")


def _get(path: str, *, params: Optional[dict] = None) -> tuple[bool, Any]:
    """(ok, datos). Nunca levanta: el llamador decide qué mostrar."""
    if not configurado():
        return False, "falta RECON_API_URL o RECON_API_KEY"
    try:
        r = httpx.get(
            f"{_base()}{path}",
            params=params or {},
            headers={"X-API-Key": os.getenv("RECON_API_KEY", "")},
            timeout=_TIMEOUT,
        )
        if r.status_code == 401:
            return False, "la API key del módulo de conciliación fue rechazada"
        if r.status_code == 404:
            return False, f"el servicio no tiene la ruta {path}"
        r.raise_for_status()
        return True, r.json()
    except httpx.TimeoutException:
        return False, f"el módulo de conciliación no respondió en {_TIMEOUT:.0f}s"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:140]}"


def salud() -> dict:
    """¿Está vivo el servicio de conciliación?"""
    if not configurado():
        return {"disponible": False, "motivo": "no configurado"}
    ok, d = _get("/health")
    if ok and isinstance(d, dict) and d.get("status") == "ok":
        return {"disponible": True, "servicio": d.get("service")}
    return {"disponible": False, "motivo": str(d)[:200]}


def resumen(*, forzar: bool = False) -> dict:
    """Los números gruesos: pendiente por plataforma, cruces, excepciones.

    `by_gateway` es lo que responde "cuánto esperar de cada plataforma" — el dato
    que el OS no podía calcular porque el eslabón de la consignación vivía fuera.
    """
    clave = "resumen"
    ahora = time.time()
    if not forzar and clave in _cache:
        ts, val = _cache[clave]
        if (ahora - ts) < _TTL_RESUMEN:
            return {**val, "cacheado_hace_s": int(ahora - ts)}

    ok, d = _get("/api/summary")
    if not ok:
        log.warning(f"[recon] resumen no disponible: {d}")
        # Se devuelve el último bueno si existe, marcado como viejo. Es mejor un
        # número de hace un rato —dicho— que una pantalla en blanco.
        if clave in _cache:
            ts, val = _cache[clave]
            return {**val, "disponible": True, "obsoleto": True,
                    "edad_s": int(ahora - ts), "motivo": str(d)[:200]}
        return {"disponible": False, "motivo": str(d)[:200]}

    plataformas = []
    for g in (d.get("by_gateway") or []):
        plataformas.append({
            "plataforma": g.get("gateway"),
            "pedidos": int(g.get("count") or 0),
            "valor": float(g.get("value") or 0),
        })
    plataformas.sort(key=lambda x: -x["valor"])
    out = {
        "disponible": True,
        "obsoleto": False,
        "pendiente_total": float(d.get("pending_orders_value") or 0),
        "excepciones_abiertas": int(d.get("exceptions_open") or 0),
        "pedidos": d.get("orders") or {},
        "banco": d.get("bank") or {},
        "cruces": int((d.get("matches") or {}).get("total") or 0),
        "por_plataforma": plataformas,
    }
    _cache[clave] = (ahora, out)
    return out


def liquidaciones(*, limite: int = 50) -> dict:
    """Los lotes de liquidación: cada consignación agrupada por pasarela.

    OJO al leer `gross_total`: viene en 0 cuando el lote todavía no se descompuso
    en los pedidos que lo componen (medido el 2026-08-05: la consignación de
    Melonn del 10-jul tenía sus 84 pedidos y cuadraba al peso; la del 3-jul tenía
    0 identificados). Por eso se expone `descompuesto` — sin esa marca, un lote
    sin detalle se ve igual que uno cuadrado.
    """
    ok, d = _get("/api/settlements", params={"limit": limite})
    if not ok:
        return {"disponible": False, "motivo": str(d)[:200], "items": []}
    items = []
    for s in (d.get("items") if isinstance(d, dict) else d) or []:
        bruto = float(s.get("gross_total") or 0)
        items.append({
            "id": s.get("id"),
            "plataforma": s.get("gateway"),
            "fecha": s.get("settlement_date"),
            "bruto": bruto,
            "comision": float(s.get("fee_total") or 0),
            "retencion": float(s.get("retention_total") or 0),
            "neto": float(s.get("net_total") or 0),
            "estado": s.get("status"),
            "descompuesto": bruto > 0,
        })
    return {"disponible": True, "items": items,
            "sin_descomponer": sum(1 for x in items if not x["descompuesto"])}


def excepciones(*, limite: int = 100) -> dict:
    """Lo que el motor no pudo cuadrar. Es la lista de trabajo real."""
    ok, d = _get("/api/exceptions", params={"limit": limite})
    if not ok:
        return {"disponible": False, "motivo": str(d)[:200], "items": []}
    items = []
    for e in (d.get("items") if isinstance(d, dict) else d) or []:
        det = e.get("details") or {}
        items.append({
            "id": e.get("id"),
            "tipo": e.get("type"),
            "severidad": e.get("severity"),
            "estado": e.get("status"),
            "creada": e.get("created_at"),
            "plataforma": det.get("gateway"),
            "valor": float(det.get("valor") or 0) if det.get("valor") else None,
            "fecha": det.get("fecha"),
            "referencia": det.get("external_id"),
        })
    por_tipo: dict[str, int] = {}
    for x in items:
        por_tipo[x["tipo"] or "?"] = por_tipo.get(x["tipo"] or "?", 0) + 1
    return {"disponible": True, "items": items, "por_tipo": por_tipo}
