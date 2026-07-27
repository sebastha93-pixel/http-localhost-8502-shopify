"""
backend.services.fiscal_siigo — Implementación Siigo del EmisorFiscal.

Hace el I/O contra Siigo (buscar la factura original, emitir documentos).
El armado de payloads vive en fiscal_logic (puro). El día que otra marca use
Alegra/World Office, se crea otro emisor con la misma interfaz.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from backend.services import siigo
from backend.services import fiscal_logic as F

log = logging.getLogger("fiscal_siigo")

_MAX_PAGINAS = 20

# Cache de facturas por nº de pedido. Siigo va a ~1 req/s y paginar /invoices
# por cada caso es lentísimo cuando se procesan varios seguidos (banco de
# pruebas, lotes). La factura de un pedido no cambia, así que cachearla es
# seguro. TTL corto para no servir datos rancios en operación normal.
_cache_facturas: dict[str, tuple[float, Optional[dict]]] = {}
_TTL_FACTURA = 600.0


def limpiar_cache_facturas() -> None:
    _cache_facturas.clear()


def modo_actual() -> str:
    """'prueba' (default, no toca DIAN) | 'produccion'."""
    m = os.environ.get("SIIGO_POSTVENTA_MODO", "prueba").strip().lower()
    return "produccion" if m == "produccion" else "prueba"


class EmisorSiigo:
    """Emisor fiscal para Siigo. Implementa el protocolo EmisorFiscal."""

    nombre = "siigo"
    _ENDPOINTS = {"nota_credito": "/credit-notes", "factura": "/invoices"}

    def buscar_factura_original(self, *, numero_pedido: str,
                                desde: str = "", hasta: str = "") -> Optional[dict]:
        """Encuentra la factura de venta online cuyo `observations` contiene
        'Orden Nº: <numero_pedido>'. Devuelve None si no existe."""
        objetivo = F.normalizar_numero_pedido(numero_pedido)
        if not objetivo:
            return None

        import time
        hit = _cache_facturas.get(objetivo)
        if hit and (time.time() - hit[0]) < _TTL_FACTURA:
            return hit[1]

        params = {"page_size": 100, "document_id": F.FV_ONLINE_ID}
        if desde:
            params["date_start"] = desde
        if hasta:
            params["date_end"] = hasta

        for pagina in range(1, _MAX_PAGINAS + 1):
            params["page"] = pagina
            data = siigo.siigo_get("/invoices", params)
            resultados = data.get("results", []) if isinstance(data, dict) else []
            if not resultados:
                return None
            for inv in resultados:
                encontrado = F.extraer_numero_pedido(inv.get("observations") or "")
                # Cachear TODO lo que se pagina, no solo el objetivo: la
                # siguiente búsqueda de otro pedido de la misma página ya no
                # vuelve a llamar a Siigo.
                if encontrado:
                    _cache_facturas[encontrado] = (time.time(), inv)
                if encontrado == objetivo:
                    return inv
        _cache_facturas[objetivo] = (time.time(), None)
        return None

    def emitir(self, *, payload: dict, doc_kind: str) -> dict:
        """Crea el documento en Siigo. SOLO se llama tras confirmación humana."""
        endpoint = self._ENDPOINTS.get(doc_kind)
        if endpoint is None:
            raise ValueError("doc_kind_invalido")
        data = siigo.siigo_post(endpoint, payload)
        return {
            "siigo_document_id": data.get("id"),
            "siigo_document_number": data.get("name") or str(data.get("number") or ""),
            "crudo": data,
        }
