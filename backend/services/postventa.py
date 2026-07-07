"""
backend.services.postventa — Orquestación del módulo Postventa.

Acceso Supabase + reglas de negocio que combinan postventa_logic con I/O.
Sigue el patrón _sb() de los otros servicios (revenue_db, clientes).
"""
from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

from backend.services import postventa_logic as L
from backend.services import whatsapp_cloud
from backend.services import clientes

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


def _brand_id() -> str:
    """Marca (tenant) del despliegue actual. Base para multi-tenant.

    Cada despliegue sirve a UNA marca; se controla con la env var BRAND_ID.
    El día que se comercialice a otra marca, su despliegue usa otro valor y
    los datos quedan aislados por esta columna. Default 'male'.
    """
    return os.environ.get("BRAND_ID", "male").strip() or "male"


def _siguiente_consecutivo(anio: int) -> int:
    """Cuenta cuántos casos existen del año PARA ESTA MARCA y devuelve el
    siguiente número. El consecutivo es por marca (cada tenant su propia serie).

    Simple y suficiente para el volumen de MALE Denim. Si en el futuro hay
    concurrencia alta, se migra a una secuencia postgres.
    """
    sb = _sb()
    if sb is None:
        return 1
    inicio = f"{anio}-01-01T00:00:00+00:00"
    r = (sb.table("postventa_cases")
           .select("id", count="exact")
           .eq("brand_id", _brand_id())
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
        "brand_id": _brand_id(),
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
    r = (sb.table("postventa_cases").select("*")
           .eq("id", case_id).eq("brand_id", _brand_id()).limit(1).execute())
    filas = r.data or []
    return filas[0] if filas else None


def listar_casos(status: Optional[str] = None) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    q = sb.table("postventa_cases").select("*").eq("brand_id", _brand_id())
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
        "brand_id": _brand_id(),
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


PLANTILLAS_WA: dict[str, str] = {
    "aprobado": "¡Hola! 💛 Tu solicitud {case_number} en MALE Denim fue APROBADA. "
                "Pronto te contamos los siguientes pasos.",
    "nota_credito_emitida": "Generamos tu nota crédito para la solicitud {case_number}. "
                            "Ya quedó en el sistema ✅.",
    "factura_emitida": "¡Listo! Tu cambio de la solicitud {case_number} va en camino. "
                       "Gracias por confiar en MALE Denim 💛.",
    "rechazado": "Sobre tu solicitud {case_number}: no fue posible aprobarla. "
                 "Escríbenos y con gusto te explicamos.",
}


def _notificar_estado(caso: dict, estado: str) -> None:
    """Envía WhatsApp en los momentos clave. Nunca bloquea el flujo del caso."""
    plantilla = PLANTILLAS_WA.get(estado)
    telefono = (caso.get("customer_phone") or "").strip()
    if not plantilla or not telefono:
        return None
    mensaje = plantilla.format(case_number=caso.get("case_number", ""))
    try:
        res = whatsapp_cloud.enviar_texto(telefono, mensaje)
        ok = bool(res.get("enviado")) if isinstance(res, dict) else False
        registrar_evento(
            caso["id"], "notificacion_wa",
            f"WhatsApp '{estado}' {'enviado' if ok else 'no entregado'}",
            created_by="sistema",
        )
    except Exception as e:  # notificación es secundaria: no romper el caso
        log.warning(f"[postventa] fallo notificacion wa: {e}")
        # Spec §7.2: dejar rastro en timeline de la notificación no entregada.
        # El registro tampoco debe romper el caso, por eso va en su propio try.
        try:
            registrar_evento(
                caso["id"], "notificacion_wa",
                f"WhatsApp '{estado}' no entregado (error: {str(e)[:120]})",
                created_by="sistema",
            )
        except Exception:
            pass
    return None


def agregar_item(case_id: str, *, original_sku: str = "", original_variant: str = "",
                 original_price: float = 0, requested_sku: str = "",
                 requested_variant: str = "",
                 requested_price: Optional[float] = None) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    diferencia = L.calcular_diferencia(original_price, requested_price)
    data = {
        "brand_id": _brand_id(),
        "case_id": case_id,
        "original_sku": original_sku or None,
        "original_variant": original_variant or None,
        "original_price": original_price,
        "requested_sku": requested_sku or None,
        "requested_variant": requested_variant or None,
        "requested_price": requested_price,
        "price_difference": diferencia,
        "item_status": "pendiente",
    }
    r = sb.table("postventa_items").insert(data).execute()
    return (r.data or [data])[0]


def agregar_evidencia(case_id: str, file_url: str, file_type: str = "",
                      uploaded_by: Optional[str] = None) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    data = {
        "brand_id": _brand_id(),
        "case_id": case_id,
        "file_url": file_url,
        "file_type": file_type or None,
        "uploaded_by": uploaded_by,
    }
    r = sb.table("postventa_evidence").insert(data).execute()
    return (r.data or [data])[0]


def pedido_shopify(email: str = "", telefono: str = "") -> dict:
    """Trae historial Shopify del cliente reutilizando el servicio existente."""
    return clientes.clasificar(email=email, telefono=telefono)


def contadores_dashboard() -> dict:
    """Contadores para el dashboard básico. Los KPIs profundos son Fase 6."""
    casos = listar_casos()
    por_estado = Counter(c.get("status", "?") for c in casos)
    motivos = Counter(c.get("reason", "?") for c in casos)
    cerrados = por_estado.get("cerrado", 0) + por_estado.get("rechazado", 0)
    abiertos = len(casos) - cerrados
    top = [{"motivo": m, "total": n} for m, n in motivos.most_common(5)]
    return {
        "por_estado": dict(por_estado),
        "abiertos": abiertos,
        "cerrados": cerrados,
        "top_motivos": top,
        "total": len(casos),
    }
