"""
backend.api.melonn — Endpoints REST de logística (Melonn).
"""
from __future__ import annotations

import os
import logging
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.core.security import CurrentUser, require_role, require_permission
from backend.services import melonn as svc
from backend.services import metricas as metricas_svc
from backend.services import overrides as overrides_svc


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/melonn", tags=["melonn"])


# Contador in-memory de webhooks (para verificar que están llegando)
_webhook_stats: dict = {
    "total_recibidos": 0,
    "exitosos": 0,
    "fallidos_auth": 0,
    "sin_identificador": 0,
    "errores_proc": 0,
    "ultimos_eventos": [],   # lista circular, últimos 20
    "primero_recibido_en": None,
    "ultimo_recibido_en": None,
}


def _registrar_webhook(estado: str, evento: str, identificador: str, detalle: str = ""):
    """Registra el evento del webhook en stats in-memory."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    _webhook_stats["total_recibidos"] += 1
    _webhook_stats[estado] = _webhook_stats.get(estado, 0) + 1
    if _webhook_stats["primero_recibido_en"] is None:
        _webhook_stats["primero_recibido_en"] = now
    _webhook_stats["ultimo_recibido_en"] = now
    _webhook_stats["ultimos_eventos"].insert(0, {
        "ts": now, "estado": estado, "evento": evento,
        "id": identificador, "detalle": detalle[:100],
    })
    _webhook_stats["ultimos_eventos"] = _webhook_stats["ultimos_eventos"][:20]


@router.get("/webhook-stats")
def webhook_stats(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Estadísticas del receptor de webhooks. Solo admin."""
    return dict(_webhook_stats)


# ── Webhook receiver (público, validado por secret) ──────────────────────────
@router.post("/webhook")
async def webhook_receiver(request: Request, secret: Optional[str] = Query(None)) -> dict:
    """
    Receptor de webhooks de Melonn.

    Configurar en admin.melonn.com → Integraciones → Webhooks:
        URL:    https://<backend>.up.railway.app/api/melonn/webhook
        Header: X-Webhook-Secret = <MELONN_WEBHOOK_SECRET>
        (alternativa menos segura: pasar ?secret=X en la URL)

    Cuando llega un evento, refrescamos SOLO ese pedido en el caché
    (sin descargar toda la lista). Ahorra >90% de llamadas al list endpoint.

    El secret se valida contra la env var MELONN_WEBHOOK_SECRET. Si no
    está configurada, el endpoint responde 503 (fail-closed).
    """
    expected = os.environ.get("MELONN_WEBHOOK_SECRET", "").strip()
    if not expected:
        raise HTTPException(503, "MELONN_WEBHOOK_SECRET no configurado en Railway")

    # Aceptar el secret en HEADER (recomendado) o en query param (fallback).
    header_secret = (
        request.headers.get("x-webhook-secret")
        or request.headers.get("X-Webhook-Secret")
        or request.headers.get("x-melonn-secret")
        or ""
    ).strip()
    provisto = header_secret or (secret or "").strip()
    if provisto != expected:
        _registrar_webhook("fallidos_auth", "?", "?", "secret inválido")
        log.warning(f"Webhook con secret inválido (header={'sí' if header_secret else 'no'}, query={'sí' if secret else 'no'})")
        raise HTTPException(401, "Secret inválido")

    try:
        payload = await request.json()
    except Exception:
        # Algunos webhooks vienen como form-data; tomamos lo que se pueda
        payload = {}

    # Extraer identificadores del payload. Melonn usa shape:
    #   { eventDate, eventClassifier, eventData: {...} }
    # y dentro de eventData están los IDs. Probamos múltiples paths y nombres.
    def _buscar(d: Any, keys: list[str]) -> Optional[str]:
        if not isinstance(d, dict):
            return None
        # Match exacto (case-sensitive) primero, luego case-insensitive
        for k in keys:
            if k in d and d[k]:
                return str(d[k])
        # Case-insensitive: comparar contra todas las claves del dict
        d_lower = {str(kk).lower(): vv for kk, vv in d.items()}
        for k in keys:
            v = d_lower.get(k.lower())
            if v:
                return str(v)
        # Buscar en sub-objetos comunes (Melonn usa eventData)
        for sub_key in ("eventData", "event_data", "order", "sell_order", "sellOrder",
                         "data", "payload"):
            sub = d.get(sub_key)
            if isinstance(sub, dict):
                r = _buscar(sub, keys)
                if r:
                    return r
        return None

    external = _buscar(payload, [
        "external_order_number", "externalOrderNumber",
        "external_id", "externalId", "order_number", "orderNumber",
    ])
    internal = _buscar(payload, [
        "internal_order_number", "internalOrderNumber",
        "internal_id", "internalId", "sell_order_id", "sellOrderId", "id",
    ])
    # eventClassifier puede venir como string o como dict {category, type, tags}.
    # Si es dict, preferimos su .type (ej. "SELL_ORDER/DELIVERED_TO_BUYER").
    raw_evento = payload.get("eventClassifier") if isinstance(payload, dict) else None
    if isinstance(raw_evento, dict):
        evento = str(raw_evento.get("type") or raw_evento.get("category") or "?")
    elif isinstance(raw_evento, str):
        evento = raw_evento
    else:
        evento = _buscar(payload, ["event", "event_type", "eventType", "type"]) or "?"

    identificador = external or internal
    if not identificador:
        # Loguear keys del payload Y de eventData para diagnóstico
        top_keys = list(payload.keys()) if isinstance(payload, dict) else []
        event_data = payload.get("eventData") if isinstance(payload, dict) else None
        ed_keys = list(event_data.keys()) if isinstance(event_data, dict) else []
        # Una muestra de valores (recortados) para entender la estructura
        ed_muestra = ""
        if isinstance(event_data, dict):
            ed_muestra = " | values: " + ", ".join(
                f"{k}={str(v)[:50]}" for k, v in list(event_data.items())[:5]
            )
        detalle = f"evento={evento} top={top_keys} eventData={ed_keys}{ed_muestra}"
        _registrar_webhook("sin_identificador", evento, "?", detalle)
        log.warning(f"Webhook sin id. {detalle}")
        return {"ok": False, "error": "Sin identificador de pedido en el payload",
                "payload_keys": top_keys, "eventData_keys": ed_keys}

    # Refrescar solo ese pedido
    try:
        import sys
        from pathlib import Path
        _SRC = Path(__file__).resolve().parent.parent.parent / "src"
        if str(_SRC) not in sys.path:
            sys.path.insert(0, str(_SRC))
        import melonn_client as mc

        resultado = mc.refrescar_un_pedido(identificador)
        _registrar_webhook("exitosos", evento, identificador, str(resultado.get("accion", "")))
        log.info(f"Webhook {evento}: {identificador} → {resultado.get('accion')}")

        # Si el evento es de entrega, archivar el pedido en /historico.
        # Eventos Melonn relevantes: DELIVERED_TO_BUYER, COLLECTED_BY_BUYER.
        ev_str = str(evento).upper()
        if "DELIVER" in ev_str or "COLLECT" in ev_str or "ENTREG" in ev_str:
            try:
                from backend.services import archivo as archivo_svc
                from backend.services import melonn as melonn_svc
                # Buscar el pedido recién refrescado en el caché para tener
                # todos los campos enriquecidos.
                cache = melonn_svc.obtener_pedidos(forzar_refresh=False)
                for p in cache.get("pedidos", []):
                    if (p.get("orden_tienda") == identificador
                            or p.get("orden_melonn") == identificador
                            or str(p.get("orden_melonn") or "").lstrip("Mm") == str(identificador).lstrip("Mm")):
                        archivo_svc.archivar_si_entregado(p)
                        break
            except Exception as e:
                log.warning(f"Webhook {evento}: no se pudo archivar {identificador}: {e}")

        return {"ok": True, "evento": evento, "identificador": identificador, **resultado}
    except Exception as e:
        _registrar_webhook("errores_proc", evento, identificador, str(e)[:100])
        log.exception(f"Error procesando webhook")
        # Retornamos 200 igual para que Melonn no reintente — el error queda en logs
        return {"ok": False, "error": str(e)[:200], "evento": evento}


# ── Modelos de respuesta (Pydantic — auto-doc en /docs) ──────────────────────

class PedidoListResponse(BaseModel):
    pedidos: list[dict]
    total: int
    fuente: str
    stale: bool
    fetched_at: str


class CacheInfoResponse(BaseModel):
    total: Optional[int]      = None
    age_seconds: Optional[int]= None
    fetched_at: Optional[str] = None
    stale: Optional[bool]     = None
    fuente: Optional[str]     = None
    backend: Optional[str]    = None


class StatusResponse(BaseModel):
    credenciales_ok: bool
    cache: Optional[CacheInfoResponse] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

class SyncResponse(BaseModel):
    ok: bool
    total: int = 0
    antes: int = 0
    despues: int = 0
    completados: int = 0
    error: Optional[str] = None


@router.get("/debug/detalle/{orden_melonn}")
def debug_detalle(
    orden_melonn: str,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Debug: respuesta RAW del detail endpoint de Melonn para una orden."""
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import melonn_client as mc

    try:
        detail = mc._get(f"sell-orders/{orden_melonn}")
        if not detail:
            raise HTTPException(404, "Melonn devolvió respuesta vacía")
        return {"orden_melonn": orden_melonn, "detail": detail, "keys": list(detail.keys())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Error: {e}")


@router.post("/sync-completo", response_model=SyncResponse)
def sync_completo_endpoint(
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> SyncResponse:
    """
    Pasada exhaustiva de enriquecimiento Shopify sobre TODO el caché.
    Lento (~30-90s). Solo admin/operador.
    """
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import melonn_client as mc

    try:
        result = mc.sync_completo()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return SyncResponse(**result)


@router.post("/enriquecer-faltantes")
def enriquecer_faltantes_endpoint(
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    """
    Corre sync_completo en loop hasta que no queden faltantes o el conteo
    deje de bajar. Para los pedidos manuales (sin external_order_id) que
    aún no tienen datos del cliente.
    """
    import sys, time as _t
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import melonn_client as mc

    total_completados = 0
    faltantes_inicial = None
    faltantes_final = None
    iteraciones = 0
    for _ in range(5):  # máx 5 iteraciones de sync_completo
        iteraciones += 1
        # Contar faltantes ANTES
        data = svc.obtener_pedidos(forzar_refresh=False)
        faltantes_antes = sum(
            1 for p in data.get("pedidos", [])
            if not p.get("nombre_comprador") and not p.get("telefono_comprador")
        )
        if faltantes_inicial is None:
            faltantes_inicial = faltantes_antes
        if faltantes_antes == 0:
            faltantes_final = 0
            break

        # Ejecutar pasada
        try:
            mc.sync_completo()
        except Exception as e:
            return {"ok": False, "error": str(e)[:200], "iteraciones": iteraciones,
                    "completados": total_completados}

        # Recontar Y persistir los recién enriquecidos en pedido_overrides
        # para que SOBREVIVAN cambios de estado y refreshes del caché.
        data = svc.obtener_pedidos(forzar_refresh=False)
        for p in data.get("pedidos", []):
            nombre = (p.get("nombre_comprador") or "").strip()
            tel    = (p.get("telefono_comprador") or "").strip()
            ciu    = (p.get("ciudad_destino") or "").strip()
            if not (nombre or tel or ciu):
                continue
            orden = p.get("orden_tienda") or p.get("orden_melonn") or ""
            if not orden:
                continue
            try:
                overrides_svc.upsert(
                    orden, nombre=nombre, telefono=tel, ciudad=ciu,
                    autor="auto-enrich",
                )
            except Exception:
                pass  # no bloquear si Supabase falla

        faltantes_final = sum(
            1 for p in data.get("pedidos", [])
            if not p.get("nombre_comprador") and not p.get("telefono_comprador")
        )
        completados = faltantes_antes - faltantes_final
        total_completados += completados
        if completados == 0:
            break  # no avanza más
        _t.sleep(1)

    return {
        "ok": True,
        "iteraciones": iteraciones,
        "faltantes_inicial": faltantes_inicial or 0,
        "faltantes_restantes": faltantes_final if faltantes_final is not None else 0,
        "completados": total_completados,
    }


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    """Estado de la integración Melonn — credenciales y caché."""
    return StatusResponse(
        credenciales_ok=svc.credenciales_ok(),
        cache=svc.cache_info() and CacheInfoResponse(**svc.cache_info()),
    )


@router.get("/pedidos", response_model=PedidoListResponse)
def pedidos(
    refresh: bool = Query(default=False, description="Forzar fetch a la API"),
) -> PedidoListResponse:
    """
    Lista de pedidos activos.

    - `refresh=true` → fetch en vivo a Melonn (lento, ~2-30s)
    - `refresh=false` → caché Supabase (instantáneo)
    """
    try:
        data = svc.obtener_pedidos(forzar_refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn API error: {exc}")
    # 1) Aplicar overrides manuales (datos rellenados a mano desde la UI)
    overrides = overrides_svc.cargar_map()
    pedidos = [overrides_svc.aplicar_a_pedido(p, overrides) for p in data["pedidos"]]
    # 2) Enriquecer con nivel/zona/sla — campos críticos para tabla logística
    data["pedidos"] = [metricas_svc.clasificar(p) for p in pedidos]
    return PedidoListResponse(**data)


@router.get("/pedidos/{orden}")
def pedido_detalle(orden: str) -> dict:
    """Detalle de un pedido específico (por orden_tienda u orden_melonn)."""
    try:
        data = svc.obtener_pedidos(forzar_refresh=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn API error: {exc}")
    overrides = overrides_svc.cargar_map()
    for p in data["pedidos"]:
        if p.get("orden_tienda") == orden or p.get("orden_melonn") == orden:
            p = overrides_svc.aplicar_a_pedido(p, overrides)
            return metricas_svc.clasificar(p)
    raise HTTPException(status_code=404, detail=f"Pedido {orden} no encontrado")


class AutorizarResponse(BaseModel):
    ok: bool
    mensaje: str
    orden_melonn: str


@router.get("/pedidos/{orden_melonn}/documentos-entrega")
def documentos_entrega(
    orden_melonn: str,
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    """Trae guía de envío + evidencia de entrega (POD) de una orden.

    Útil para:
      - Mostrar/descargar la guía sin entrar a Melonn
      - Adjuntar foto/firma de entregado cuando un cliente reclama
      - Auditoría de entregas en /devoluciones e /incidencias
    """
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import melonn_client as mc

    try:
        data = mc.obtener_documentos_entrega(orden_melonn)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn API error: {exc}")

    if data is None:
        return {"ok": False, "error": "documentos_no_disponibles", "orden": orden_melonn}
    return {"ok": True, "orden": orden_melonn, "data": data}


@router.post("/pedidos/{orden_melonn}/autorizar-despacho", response_model=AutorizarResponse)
def autorizar_despacho(
    orden_melonn: str,
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> AutorizarResponse:
    """
    Libera el hold de fulfillment en Melonn y autoriza el despacho del pedido.
    Equivalente al botón "Authorize dispatch" en la UI de Melonn.

    GATE de workflow: requiere que ANTES exista en cod_acciones:
      - contacto_at NO NULL (asesor contactó al cliente)
      - respuesta = 'aprobacion' (cliente aprobó el envío)

    Esto evita despachar pedidos sin confirmación previa del cliente,
    causa #1 de devoluciones y contraentregas rechazadas.
    """
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import melonn_client as mc
    import memoria

    # ── Verificar workflow obligatorio ──────────────────────────────────
    # Buscamos la fila en cod_acciones para esta orden. Si no existe o
    # respuesta no es 'aprobacion', rechazamos con 409.
    from backend.services import revenue_db as _rdb
    sb = _rdb._sb()
    if sb is not None:
        try:
            r = (sb.table("cod_acciones")
                   .select("contacto_at,respuesta,contacto_via")
                   .eq("orden_melonn", orden_melonn)
                   .limit(1)
                   .execute())
            row = (r.data or [None])[0]
            contacto_at = (row or {}).get("contacto_at")
            respuesta   = (row or {}).get("respuesta")
            if not contacto_at:
                raise HTTPException(
                    status_code=409,
                    detail="Contacta al cliente (Llamar o WhatsApp) antes de autorizar el despacho.",
                )
            if respuesta == "no_contesta":
                raise HTTPException(
                    status_code=409,
                    detail="Cliente no contestó. Vuelve a contactarlo antes de autorizar.",
                )
            if respuesta == "rechazo":
                raise HTTPException(
                    status_code=409,
                    detail="El cliente rechazó el pedido. No se puede autorizar el despacho.",
                )
            if respuesta != "aprobacion":
                raise HTTPException(
                    status_code=409,
                    detail="Marca la respuesta del cliente (Acuerdo / No contesta / Rechazo) antes de autorizar.",
                )
        except HTTPException:
            raise
        except Exception as e:
            # Si la tabla no existe aún (DDL pendiente), no bloqueamos —
            # log warning y continuamos. Pero esto NO debería pasar en prod.
            err = str(e)
            if "does not exist" in err or "42P01" in err:
                log.warning(f"cod_acciones tabla ausente — skip gate ({orden_melonn})")
            else:
                log.warning(f"Error chequeando workflow cod_acciones: {err[:200]}")

    try:
        ok, mensaje = mc.release_hold_fulfillment(orden_melonn)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn API error: {exc}")

    if not ok:
        raise HTTPException(status_code=400, detail=mensaje)

    # Refrescar ESE pedido en el caché. Esperamos un instante porque Melonn
    # puede tardar ~1s en propagar el cambio de estado entre su POST y su
    # GET — si llamamos el detail inmediatamente, devuelve el estado viejo
    # (hold) y el pedido sigue apareciendo en Pendientes.
    import time as _t
    _t.sleep(1.5)
    try:
        r = mc.refrescar_un_pedido(orden_melonn)
        log.info(f"Autorizar {orden_melonn}: refresh → {r.get('accion', 'sin cambio')}")
    except Exception as e:
        log.warning(f"No se pudo refrescar pedido tras autorizar {orden_melonn}: {e}")

    # Audit trail: el usuario autenticado del JWT
    try:
        memoria.agregar_accion(
            orden_melonn,
            "despacho_autorizado",
            "Despacho autorizado vía dashboard MALE'DENIM OS",
            user.nombre,
        )
    except Exception:
        pass  # No bloquear la autorización si Supabase falla

    return AutorizarResponse(ok=True, mensaje=mensaje, orden_melonn=orden_melonn)
