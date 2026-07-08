"""
backend.services.postventa_siigo — Motor fiscal de Postventa (Siigo).

FASE 0 (este archivo por ahora): DESCUBRIMIENTO de solo lectura.

Antes de emitir NADA ante la DIAN necesitamos los IDs reales de la cuenta
Siigo de la marca (tipos de documento NC/FV, impuestos, formas de pago,
vendedores) y entender por qué campo se enlaza una factura de venta con el
pedido de Shopify. Este módulo SOLO LEE (usa siigo.siigo_get); no crea ni
modifica documentos. La emisión (POST) llega en una fase posterior, con
previsualización + confirmación humana + modo prueba.

Reusa la autenticación y el backoff de rate-limit de backend.services.siigo.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from backend.services import siigo

log = logging.getLogger("postventa_siigo")


def _get_seguro(path: str, params: Optional[dict] = None) -> Any:
    """siigo_get envuelto: si un endpoint falla, devolvemos el error como dato
    en vez de romper todo el descubrimiento (así una llamada mala no tumba las
    demás en la primera corrida contra la cuenta real)."""
    try:
        return siigo.siigo_get(path, params)
    except Exception as e:  # noqa: BLE001 - queremos el detalle del fallo
        return {"_error": str(e)[:300]}


def descubrir_config() -> dict:
    """Trae los IDs de configuración de la cuenta Siigo necesarios para emitir
    notas crédito y facturas. TODO de solo lectura.

    Devuelve un dict con una sección por recurso; cada sección puede traer
    `_error` si ese endpoint falló, sin afectar a las demás.
    """
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado",
                "detalle": "Faltan SIIGO_USERNAME / SIIGO_ACCESS_KEY / SIIGO_PARTNER_ID"}

    return {
        "tipos_documento_factura": _get_seguro("/document-types", {"type": "FV"}),
        "tipos_documento_nota_credito": _get_seguro("/document-types", {"type": "NC"}),
        "impuestos": _get_seguro("/taxes"),
        "formas_pago": _get_seguro("/payment-types", {"document_type": "FV"}),
        "vendedores": _get_seguro("/users"),
    }


# Campos donde suele guardarse una referencia externa (nº de pedido Shopify).
_CAMPOS_REF = ("name", "number", "observations", "seller", "additional_fields",
               "customer", "globals", "retentions", "metadata")


def inspeccionar_facturas(limite: int = 3) -> dict:
    """Trae unas pocas facturas de venta reales para ver su estructura y
    detectar POR QUÉ CAMPO se enlazan con el pedido de Shopify (Riesgo #1 del
    spec). Solo lectura.
    """
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    limite = max(1, min(limite, 10))
    data = _get_seguro("/invoices", {"page_size": limite, "page": 1})
    if isinstance(data, dict) and data.get("_error"):
        return data

    resultados = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(resultados, list):
        return {"_error": "formato_inesperado", "crudo": str(resultados)[:500]}

    muestras = []
    for inv in resultados[:limite]:
        if not isinstance(inv, dict):
            continue
        muestras.append({
            "id": inv.get("id"),
            "name": inv.get("name"),
            "number": inv.get("number"),
            "date": inv.get("date"),
            "document_id": (inv.get("document") or {}).get("id"),
            "customer_identification": (inv.get("customer") or {}).get("identification"),
            "observations": inv.get("observations"),
            # Volcamos las llaves de nivel superior para ubicar dónde podría
            # venir el nº de pedido Shopify sin adivinar.
            "llaves_disponibles": sorted(inv.keys()),
            "campos_ref_candidatos": {k: inv.get(k) for k in _CAMPOS_REF if k in inv},
        })
    return {"total_en_muestra": len(muestras), "facturas": muestras}


def diagnostico() -> dict:
    """Corrida completa de descubrimiento: config + muestra de facturas.
    Es lo que expone el endpoint para copiar/pegar y aterrizar la Fase 1.
    """
    return {
        "configurado": siigo.siigo_configurado(),
        "config": descubrir_config(),
        "muestra_facturas": inspeccionar_facturas(3),
    }
