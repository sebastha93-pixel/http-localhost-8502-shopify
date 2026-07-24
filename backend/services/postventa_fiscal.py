"""
backend.services.postventa_fiscal — Orquestación del motor fiscal.

preview (arma y guarda, NO emite) → confirmar → emitir → persistir.
Idempotente: nunca dos notas crédito para el mismo caso. Un documento fiscal
NUNCA se reintenta automáticamente.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from backend.services import postventa as pv
from backend.services import fiscal_logic as F
from backend.services import fiscal_siigo

log = logging.getLogger("postventa_fiscal")


def obtener_emisor():
    """Emisor fiscal de la marca. Hoy Siigo; el protocolo permite otros."""
    return fiscal_siigo.EmisorSiigo()


def _hoy() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _caso(case_id: str) -> Optional[dict]:
    return pv.obtener_caso(case_id)


def _items_caso(case_id: str) -> list[dict]:
    sb = pv._sb()
    if sb is None:
        return []
    r = sb.table("postventa_items").select("*").eq("case_id", case_id).execute()
    return r.data or []


def _fiscal_existente(case_id: str, doc_kind: str) -> Optional[dict]:
    """Fila de postventa_fiscal ya EMITIDA para ese caso y tipo de doc."""
    sb = pv._sb()
    if sb is None:
        return None
    r = (sb.table("postventa_fiscal").select("*")
           .eq("case_id", case_id).eq("doc_kind", doc_kind)
           .eq("status", "emitido").limit(1).execute())
    filas = r.data or []
    return filas[0] if filas else None


def _pendiente(case_id: str, doc_kind: str) -> Optional[dict]:
    """El preview guardado más reciente, listo para emitir."""
    sb = pv._sb()
    if sb is None:
        return None
    r = (sb.table("postventa_fiscal").select("*")
           .eq("case_id", case_id).eq("doc_kind", doc_kind)
           .eq("status", "pendiente")
           .order("created_at", desc=True).limit(1).execute())
    filas = r.data or []
    return filas[0] if filas else None


def _guardar_fiscal(**campos) -> dict:
    sb = pv._sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    campos["brand_id"] = pv._brand_id()
    r = sb.table("postventa_fiscal").insert(campos).execute()
    return (r.data or [campos])[0]


def _marcar_emitido(*, fiscal_id: str, siigo_document_id: str,
                    siigo_document_number: str) -> dict:
    sb = pv._sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    campos = {"status": "emitido", "siigo_document_id": siigo_document_id,
              "siigo_document_number": siigo_document_number}
    sb.table("postventa_fiscal").update(campos).eq("id", fiscal_id).execute()
    return campos


def _marcar_error(*, fiscal_id: str, detalle: str) -> None:
    sb = pv._sb()
    if sb is None:
        return
    sb.table("postventa_fiscal").update(
        {"status": "error", "error_detail": detalle[:500]}
    ).eq("id", fiscal_id).execute()


def _skus_del_caso(items: list[dict]) -> list[str]:
    return [it.get("original_sku") for it in items if it.get("original_sku")]


def preview_nota_credito(case_id: str) -> dict:
    """Arma la nota crédito y la guarda como 'pendiente'. NO emite nada.

    Los montos se toman de la factura original (no del panel), casando por SKU.
    """
    if _fiscal_existente(case_id, "nota_credito"):
        raise ValueError("nota_credito_ya_emitida")

    caso = _caso(case_id)
    if caso is None:
        raise ValueError("caso_no_encontrado")

    items = _items_caso(case_id)
    if not items:
        raise ValueError("caso_sin_items")

    emisor = obtener_emisor()
    factura = emisor.buscar_factura_original(
        numero_pedido=caso.get("shopify_order_name") or "")
    if factura is None:
        raise ValueError("factura_original_no_encontrada")

    skus = _skus_del_caso(items)
    modo = fiscal_siigo.modo_actual()
    payload = F.construir_payload_nota_credito(
        factura=factura, skus_a_acreditar=skus, modo=modo, fecha=_hoy())

    total = payload["payments"][0]["value"]
    subtotal = round(sum(
        (l.get("price") or 0) * (l.get("quantity") or 1) for l in payload["items"]), 2)
    totales = {"subtotal": subtotal, "iva": round(total - subtotal, 2), "total": total}

    _guardar_fiscal(case_id=case_id, doc_kind="nota_credito",
                    siigo_invoice_ref=factura.get("id"),
                    amount=total, status="pendiente",
                    payload_snapshot=payload)

    return {"factura_original": factura, "payload": payload,
            "totales": totales, "modo": modo, "emitido": False}


def emitir_nota_credito(case_id: str, *, actor: str = "sistema") -> dict:
    """Emite en Siigo la NC previamente previsualizada. Irreversible en modo
    producción — por eso exige un preview guardado y confirmación explícita."""
    if _fiscal_existente(case_id, "nota_credito"):
        raise ValueError("nota_credito_ya_emitida")

    fila = _pendiente(case_id, "nota_credito")
    if fila is None:
        raise ValueError("sin_preview")

    emisor = obtener_emisor()
    try:
        res = emisor.emitir(payload=fila["payload_snapshot"],
                            doc_kind="nota_credito")
    except Exception as e:
        _marcar_error(fiscal_id=fila["id"], detalle=str(e))
        pv.registrar_evento(case_id, "fiscal_error",
                            f"Nota crédito rechazada: {str(e)[:200]}",
                            created_by=actor)
        raise

    _marcar_emitido(fiscal_id=fila["id"],
                    siigo_document_id=res["siigo_document_id"],
                    siigo_document_number=res["siigo_document_number"])
    pv.registrar_evento(case_id, "nota_credito_emitida",
                        f"NC {res['siigo_document_number']} emitida "
                        f"(modo {fiscal_siigo.modo_actual()})",
                        created_by=actor)
    pv.cambiar_estado(case_id, "nota_credito_emitida", actor=actor)
    return res
