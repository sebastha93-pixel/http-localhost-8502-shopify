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
        numero_pedido=caso.get("shopify_order_name") or "",
        factura_id=caso.get("siigo_invoice_id") or "")
    if factura is None:
        raise ValueError("factura_original_no_encontrada")

    skus = _skus_del_caso(items)
    modo = fiscal_siigo.modo_actual()
    # Si la DIAN no ha aceptado la factura, decirlo con claridad en vez de
    # dejar que Siigo responda un 'invalid_document' que no explica nada.
    if not F.factura_aceptada_dian(factura):
        raise ValueError(F.motivo_factura_no_apta(factura))
    # Cambio en tienda: la prenda entra a la bodega de esa tienda, no a la
    # bodega de donde salió la venta online (evita el traslado manual).
    bodega_destino = None
    if caso.get("tienda"):
        from backend.services import tiendas
        bodega_destino = tiendas.validar_para_facturar(caso["tienda"])["bodega_id"]
    payload = F.construir_payload_nota_credito(
        factura=factura, skus_a_acreditar=skus, modo=modo, fecha=_hoy(),
        bodega_destino=bodega_destino)

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


# ── Factura del reemplazo ────────────────────────────────────────────
from backend.services import fiscal_shopify  # noqa: E402

TIPOS_SIN_FACTURA = {"reembolso", "bono"}


def _item_reemplazo(caso: dict, item: dict, factura: dict) -> dict:
    """Determina el ítem a facturar y su precio base.

    Misma ref (o sin requested_sku) → precio del ítem original (exacto de la
    factura). Otra ref → precio desde Shopify (convertido a base).
    """
    requested = (item.get("requested_sku") or "").strip()
    original_sku = item.get("original_sku")
    if not requested or requested == original_sku:
        origs = F.items_factura_por_sku(factura, [original_sku])
        if not origs:
            raise ValueError("item_original_no_encontrado")
        o = origs[0]
        return {"code": requested or original_sku,
                "description": o.get("description"),
                "price_base": o.get("price"),
                "seller": o.get("seller"),
                "warehouse": o.get("warehouse")}
    base = fiscal_shopify.precio_base_variante(requested)
    if base is None:
        raise ValueError("precio_shopify_no_encontrado")
    return {"code": requested,
            "description": item.get("requested_variant") or requested,
            "price_base": base}


def preview_factura_reemplazo(case_id: str, *,
                              pagos_excedente: Optional[list] = None) -> dict:
    """Arma la factura del reemplazo (consume el anticipo de la NC). NO emite."""
    if _fiscal_existente(case_id, "factura"):
        raise ValueError("factura_ya_emitida")
    nc = _fiscal_existente(case_id, "nota_credito")
    if nc is None:
        raise ValueError("nota_credito_no_emitida")

    caso = _caso(case_id)
    if caso is None:
        raise ValueError("caso_no_encontrado")
    if caso.get("type") in TIPOS_SIN_FACTURA:
        raise ValueError("tipo_sin_factura")

    items = _items_caso(case_id)
    if not items:
        raise ValueError("caso_sin_items")

    emisor = obtener_emisor()
    factura = emisor.buscar_factura_original(
        numero_pedido=caso.get("shopify_order_name") or "",
        factura_id=caso.get("siigo_invoice_id") or "")
    if factura is None:
        raise ValueError("factura_original_no_encontrada")

    item_reemplazo = _item_reemplazo(caso, items[0], factura)
    modo = fiscal_siigo.modo_actual()
    # En tienda: la prenda sale de la BODEGA del punto y el excedente se cobra
    # ahí mismo. El PREFIJO, en cambio, no puede ser el de la caja: Siigo no
    # deja emitir por API con FV-6/11/12 (rangos DIAN del punto de venta).
    # Ver tiendas.documento_para_facturar.
    doc_id = bodega = pago_exc = None
    if caso.get("tienda"):
        from backend.services import tiendas
        t = tiendas.validar_para_facturar(caso["tienda"])
        doc_id = tiendas.documento_para_facturar(caso["tienda"])
        bodega = t["bodega_id"]
        pago_exc = caso.get("pago_excedente_id")
        # Los medios con que se cobró el excedente tienen que ser de ESA caja:
        # cobrar en el datáfono de la otra tienda descuadra las dos.
        ajenos = tiendas.pagos_ajenos(caso["tienda"], pagos_excedente or [])
        if ajenos:
            raise ValueError(
                f"forma_pago_no_es_de_esa_tienda: {ajenos}")
        if pago_exc and not tiendas.forma_pago_valida(caso["tienda"], pago_exc):
            raise ValueError("forma_pago_no_es_de_esa_tienda")
    payload = F.construir_payload_factura_reemplazo(
        factura_original=factura, item_reemplazo=item_reemplazo,
        credito_con_iva=float(nc.get("amount") or 0), modo=modo, fecha=_hoy(),
        documento_id=doc_id, bodega_id=bodega, pago_excedente_id=pago_exc,
        pagos_excedente=pagos_excedente)
    resumen = payload.pop("_resumen")

    _guardar_fiscal(case_id=case_id, doc_kind="factura",
                    siigo_invoice_ref=factura.get("id"),
                    amount=resumen["total"], status="pendiente",
                    payload_snapshot=payload)

    return {"payload": payload, "resumen": resumen, "modo": modo, "emitido": False}


def emitir_factura_reemplazo(case_id: str, *, actor: str = "sistema") -> dict:
    """Emite en Siigo la factura del reemplazo previamente previsualizada."""
    if _fiscal_existente(case_id, "factura"):
        raise ValueError("factura_ya_emitida")
    fila = _pendiente(case_id, "factura")
    if fila is None:
        raise ValueError("sin_preview")

    emisor = obtener_emisor()
    try:
        res = emisor.emitir(payload=fila["payload_snapshot"], doc_kind="factura")
    except Exception as e:
        _marcar_error(fiscal_id=fila["id"], detalle=str(e))
        pv.registrar_evento(case_id, "fiscal_error",
                            f"Factura de reemplazo rechazada: {str(e)[:200]}",
                            created_by=actor)
        raise

    _marcar_emitido(fiscal_id=fila["id"],
                    siigo_document_id=res["siigo_document_id"],
                    siigo_document_number=res["siigo_document_number"])
    pv.registrar_evento(case_id, "factura_emitida",
                        f"Factura {res['siigo_document_number']} emitida "
                        f"(modo {fiscal_siigo.modo_actual()})",
                        created_by=actor)
    pv.cambiar_estado(case_id, "factura_emitida", actor=actor)
    return res


def items_factura_del_caso(case_id: str) -> dict:
    """Trae los ítems de la factura original del pedido del caso, para que el
    equipo elija cuál se devuelve (garantiza que el SKU coincida con Siigo).
    Solo lectura. También sirve para verificar que la búsqueda de la factura
    funciona."""
    caso = _caso(case_id)
    if caso is None:
        raise ValueError("caso_no_encontrado")
    emisor = obtener_emisor()
    factura = emisor.buscar_factura_original(
        numero_pedido=caso.get("shopify_order_name") or "",
        factura_id=caso.get("siigo_invoice_id") or "")
    if factura is None:
        raise ValueError("factura_original_no_encontrada")
    return {
        "factura": {"id": factura.get("id"), "name": factura.get("name")},
        "items": [{
            "code": it.get("code"),
            "description": it.get("description"),
            "price": it.get("price"),
            "variant": it.get("description"),
        } for it in (factura.get("items") or [])],
    }
