"""
backend.services.postventa — Orquestación del módulo Postventa.

Acceso Supabase + reglas de negocio que combinan postventa_logic con I/O.
Sigue el patrón _sb() de los otros servicios (revenue_db, clientes).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

from backend.services import postventa_logic as L

log = logging.getLogger("postventa")
_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    _client = create_client(url, key)
    return _client


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _siguiente_consecutivo(anio: int) -> int:
    """Cuenta cuántos casos existen del año y devuelve el siguiente número.

    Simple y suficiente para el volumen de MALE Denim. Si en el futuro hay
    concurrencia alta, se migra a una secuencia postgres.
    """
    sb = _sb()
    if sb is None:
        return 1
    inicio = f"{anio}-01-01T00:00:00+00:00"
    r = (sb.table("postventa_cases")
           .select("id", count="exact")
           .gte("created_at", inicio)
           .execute())
    return (getattr(r, "count", None) or 0) + 1


def crear_caso(*, tipo: str, reason: str, customer_email: str = "",
               customer_phone: str = "", customer_name: str = "",
               shopify_order_id: str = "", shopify_order_name: str = "",
               subreason: str = "", priority: str = "media",
               source: str = "interno",
               assigned_to: Optional[str] = None) -> dict:
    """Crea un caso de postventa. Agnóstico a la puerta de entrada (source)."""
    if not L.validar_tipo(tipo):
        raise ValueError("tipo_invalido")
    if not L.validar_motivo(reason):
        raise ValueError("motivo_invalido")
    if not L.validar_prioridad(priority):
        raise ValueError("prioridad_invalida")

    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")

    anio = datetime.now(timezone.utc).year
    case_number = L.formato_case_number(anio, _siguiente_consecutivo(anio))

    data = {
        "case_number": case_number,
        "shopify_order_id": shopify_order_id or None,
        "shopify_order_name": shopify_order_name or None,
        "customer_email": customer_email or None,
        "customer_phone": customer_phone or None,
        "customer_name": customer_name or None,
        "status": "creado",
        "type": tipo,
        "reason": reason,
        "subreason": subreason or None,
        "priority": priority,
        "source": source,
        "assigned_to": assigned_to,
    }
    r = sb.table("postventa_cases").insert(data).execute()
    caso = (r.data or [data])[0]
    return caso


def obtener_caso(case_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    r = sb.table("postventa_cases").select("*").eq("id", case_id).limit(1).execute()
    filas = r.data or []
    return filas[0] if filas else None


def listar_casos(status: Optional[str] = None) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    q = sb.table("postventa_cases").select("*")
    if status:
        q = q.eq("status", status)
    r = q.order("created_at", desc=True).execute()
    return r.data or []


def registrar_evento(case_id: str, event_type: str, description: str = "",
                     created_by: str = "sistema") -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    data = {
        "case_id": case_id,
        "event_type": event_type,
        "description": description,
        "created_by": created_by,
    }
    r = sb.table("postventa_timeline").insert(data).execute()
    return (r.data or [data])[0]


def cambiar_estado(case_id: str, nuevo_estado: str, *, actor: str = "sistema",
                   motivo: str = "") -> dict:
    """Cambia el estado validando la transición y registra timeline + notifica."""
    caso = obtener_caso(case_id)
    if caso is None:
        raise ValueError("caso_no_encontrado")
    actual = caso.get("status", "")
    if not L.transicion_valida(actual, nuevo_estado):
        raise ValueError("transicion_invalida")

    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")

    campos = {"status": nuevo_estado, "updated_at": _ahora()}
    if nuevo_estado in L.ESTADOS_TERMINALES:
        campos["closed_at"] = _ahora()
    r = sb.table("postventa_cases").update(campos).eq("id", case_id).execute()

    desc = f"{actual} → {nuevo_estado}" + (f" · {motivo}" if motivo else "")
    registrar_evento(case_id, "cambio_estado", desc, created_by=actor)

    caso_actualizado = {**caso, **campos}
    _notificar_estado(caso_actualizado, nuevo_estado)
    return caso_actualizado


def _notificar_estado(caso: dict, estado: str) -> None:
    """Placeholder — se implementa en la tarea de notificaciones (Task 7)."""
    return None
