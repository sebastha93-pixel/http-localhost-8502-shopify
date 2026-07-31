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
            # Estado DIAN: sin 'Accepted' no se le puede hacer nota crédito.
            "stamp": inv.get("stamp"),
            # Volcamos las llaves de nivel superior para ubicar dónde podría
            # venir el nº de pedido Shopify sin adivinar.
            "llaves_disponibles": sorted(inv.keys()),
            "campos_ref_candidatos": {k: inv.get(k) for k in _CAMPOS_REF if k in inv},
        })
    return {"total_en_muestra": len(muestras), "facturas": muestras}



def inspeccionar_notas_credito(limite: int = 2) -> dict:
    """Trae notas credito ya emitidas para copiar su estructura EXACTA (que
    campos manda Siigo, como referencia la factura original). Solo lectura."""
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    limite = max(1, min(limite, 10))
    data = _get_seguro("/credit-notes", {"page_size": limite, "page": 1})
    if isinstance(data, dict) and data.get("_error"):
        return data

    resultados = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(resultados, list):
        return {"_error": "formato_inesperado", "crudo": str(resultados)[:500]}

    notas = []
    for nc in resultados[:limite]:
        if not isinstance(nc, dict):
            continue
        notas.append({
            "id": nc.get("id"),
            "name": nc.get("name"),
            "number": nc.get("number"),
            "date": nc.get("date"),
            "document_id": (nc.get("document") or {}).get("id"),
            "customer_identification": (nc.get("customer") or {}).get("identification"),
            "invoice_ref": nc.get("invoice"),
            "items": nc.get("items"),
            "payments": nc.get("payments"),
            "llaves_disponibles": sorted(nc.keys()),
        })
    return {"total_en_muestra": len(notas), "notas": notas}


def nota_credito_por_numero(numero: int, *, max_paginas: int = 12) -> dict:
    """Una nota crédito ya emitida, tal cual la guardó Siigo.

    Sirve para responder de un tirón la pregunta que importa después de emitir:
    ¿a qué bodega entró cada prenda? Si el ítem llega sin `warehouse`, Siigo no
    sabe a qué inventario devolverla — y el stock no se mueve.

    Solo lectura. Pagina hacia atrás porque las NC recientes empujan a las
    viejas fuera de la primera página rápido.
    """
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}
    objetivo = int(numero)
    for pagina in range(1, max_paginas + 1):
        data = _get_seguro("/credit-notes", {"page_size": 25, "page": pagina})
        if isinstance(data, dict) and data.get("_error"):
            return data
        filas = data.get("results", []) if isinstance(data, dict) else []
        if not filas:
            break
        for nc in filas:
            if not isinstance(nc, dict) or int(nc.get("number") or 0) != objetivo:
                continue
            items = [i for i in (nc.get("items") or []) if isinstance(i, dict)]
            bodegas = []
            for it in items:
                wh = it.get("warehouse") or {}
                bodegas.append({"code": it.get("code"),
                                "bodega_id": wh.get("id"),
                                "bodega": wh.get("name")})
            return {
                "nombre": nc.get("name"),
                "numero": nc.get("number"),
                "fecha": nc.get("date"),
                "factura": nc.get("invoice"),
                "observaciones": nc.get("observations"),
                # Si viene `stamp` la NC fue a la DIAN y ya no se puede borrar.
                "estampada": bool(nc.get("stamp")),
                "bodegas": bodegas,
                "sin_bodega": any(b["bodega_id"] is None for b in bodegas),
                "items": items,
            }
    return {"_error": "nota_no_encontrada",
            "detalle": f"No se halló la NC {numero} en las últimas "
                       f"{max_paginas * 25} notas crédito."}


def facturas_recientes(max_paginas: int = 6, page_size: int = 25) -> list[dict]:
    """Facturas tal cual vienen de Siigo, SIN filtrar por canal.

    `facturas_aceptadas` solo devuelve las online (exige 'Orden Nº'), así que
    no sirve para probar el flujo de tienda. Aquí se devuelve todo y quien
    llama decide qué le sirve.
    """
    salida: list[dict] = []
    for pagina in range(1, max_paginas + 1):
        data = _get_seguro("/invoices", {"page_size": page_size, "page": pagina})
        if isinstance(data, dict) and data.get("_error"):
            break
        resultados = data.get("results", []) if isinstance(data, dict) else []
        if not resultados:
            break
        salida.extend(r for r in resultados if isinstance(r, dict))
    return salida


def facturas_aceptadas(minimo: int = 10, max_paginas: int = 6) -> list[dict]:
    """Facturas online que la DIAN YA aceptó, paginando hacia atrás.

    Las ventas del día están en validación y no admiten nota crédito, así que
    quedarse en la página 1 puede no devolver ninguna útil. Se avanza por
    páginas hasta juntar `minimo` aceptadas.
    """
    from backend.services import fiscal_logic as FL

    aptas: list[dict] = []
    for pagina in range(1, max_paginas + 1):
        data = _get_seguro("/invoices", {"page_size": 25, "page": pagina})
        if isinstance(data, dict) and data.get("_error"):
            break
        resultados = data.get("results", []) if isinstance(data, dict) else []
        if not resultados:
            break
        for inv in resultados:
            if not isinstance(inv, dict):
                continue
            if not FL.extraer_numero_pedido(inv.get("observations") or ""):
                continue                      # sin pedido Shopify
            if not FL.factura_aceptada_dian(inv):
                continue                      # la DIAN aún no la validó
            aptas.append({
                "id": inv.get("id"),
                "name": inv.get("name"),
                "date": inv.get("date"),
                "observations": inv.get("observations"),
                "stamp": inv.get("stamp"),
            })
            if len(aptas) >= minimo:
                return aptas
    return aptas


def tipos_documento_completos() -> dict:
    """TODOS los tipos de documento FV, paginando.

    El prefijo de una factura (FV-11-1121) corresponde al `code` del tipo
    (code 11). Se necesitan los ids de cada tienda para facturar un cambio
    desde el punto correcto: Florida FV-11/FV-12, Arrayanes FV-6.

    La consulta simple traía la lista incompleta (faltaban 6, 11 y 12), por
    eso aquí se pagina y se ordena por code.
    """
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    vistos: dict = {}
    for pagina in range(1, 6):
        data = _get_seguro("/document-types",
                           {"type": "FV", "page": pagina, "page_size": 50})
        if isinstance(data, dict) and data.get("_error"):
            break
        filas = data if isinstance(data, list) else (data.get("results") or [])
        if not filas:
            break
        for d in filas:
            if isinstance(d, dict) and d.get("id") is not None:
                vistos[d["id"]] = d
        if len(filas) < 50:
            break

    def orden(d):
        try:
            return int(d.get("code") or 0)
        except (TypeError, ValueError):
            return 999

    tipos = sorted(vistos.values(), key=orden)
    return {
        "total": len(tipos),
        "tipos": [{"id": t.get("id"), "code": t.get("code"),
                   "prefijo": f"FV-{t.get('code')}",
                   "name": t.get("name"),
                   "description": t.get("description"),
                   "activo": t.get("active"),
                   "electronico": t.get("electronic_type"),
                   "cost_center_obligatorio": t.get("cost_center_mandatory"),
                   # Campos que decidian el exito de una emision y estabamos
                   # botando al mapear. Cada uno costo (o iba a costar) un
                   # rechazo de Siigo que no dice la causa:
                   #   discount_type   -> "Percentage" o "Value": de esto
                   #                      depende COMO se manda un descuento
                   #   automatic_number-> si es false hay que mandar `number`
                   #   advance_payment -> si el comprobante admite anticipos,
                   #                      que es justo como se paga el cambio
                   "discount_type": t.get("discount_type"),
                   "numeracion_automatica": t.get("automatic_number"),
                   "admite_anticipos": t.get("advance_payment"),
                   "decimales": t.get("decimals"),
                   "consecutivo": t.get("consecutive"),
                   "cost_center_default": t.get("cost_center_default")}
                  for t in tipos],
    }


def documentos_por_prefijo(max_paginas: int = 12) -> dict:
    """Deduce el id de cada tipo de factura a partir de facturas REALES.

    La API de Siigo no expone todos los tipos: `/document-types` devuelve 9 y
    faltan justo los de las tiendas (FV-6, FV-11, FV-12). Pero cada factura sí
    trae su `document.id` y su `name` con el prefijo, así que el id se deduce
    recorriendo facturas existentes.

    Devuelve {"FV-11": {"document_id": 31433, "ejemplo": "FV-11-1121"}, ...}
    """
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    import re
    hallados: dict[str, dict] = {}
    for pagina in range(1, max_paginas + 1):
        data = _get_seguro("/invoices", {"page_size": 100, "page": pagina})
        if isinstance(data, dict) and data.get("_error"):
            break
        filas = data.get("results", []) if isinstance(data, dict) else []
        if not filas:
            break
        for inv in filas:
            if not isinstance(inv, dict):
                continue
            nombre = str(inv.get("name") or "")
            m = re.match(r"^(FV-\d+)-", nombre)
            doc_id = (inv.get("document") or {}).get("id")
            if not m or doc_id is None:
                continue
            prefijo = m.group(1)
            if prefijo not in hallados:
                hallados[prefijo] = {"document_id": doc_id, "ejemplo": nombre,
                                     "vistas": 1, "fecha": inv.get("date")}
            else:
                hallados[prefijo]["vistas"] += 1

    def clave(p):
        try:
            return int(p.split("-")[1])
        except (IndexError, ValueError):
            return 999

    return {"total_prefijos": len(hallados),
            "prefijos": {k: hallados[k] for k in sorted(hallados, key=clave)}}


def diagnostico() -> dict:
    """Corrida completa de descubrimiento: config + muestra de facturas.
    Es lo que expone el endpoint para copiar/pegar y aterrizar la Fase 1.
    """
    return {
        "configurado": siigo.siigo_configurado(),
        "config": descubrir_config(),
        "muestra_facturas": inspeccionar_facturas(3),
        "muestra_notas_credito": inspeccionar_notas_credito(2),
    }


# ── Config del tipo de documento (cacheada) ───────────────────────────
# `discount_type` NO es igual en todos: FV-1 lo quiere en "Value" y FV-5 en
# "Percentage". Mandarlo al revés produce una factura con el monto equivocado
# y SIN error. Se lee del comprobante en uso, nunca se asume.
_TIPOS_CACHE: dict = {"ts": 0.0, "data": None}
_TIPOS_TTL = 3600


def limpiar_cache_tipos() -> None:
    _TIPOS_CACHE["ts"] = 0.0
    _TIPOS_CACHE["data"] = None


def _tipos_documento() -> dict:
    """{document_id: config} de los tipos de factura. Cambian muy poco."""
    import time
    ahora = time.time()
    if _TIPOS_CACHE["data"] and (ahora - _TIPOS_CACHE["ts"]) < _TIPOS_TTL:
        return _TIPOS_CACHE["data"]
    data = _get_seguro("/document-types", {"type": "FV"})
    if isinstance(data, dict) and data.get("_error"):
        return _TIPOS_CACHE["data"] or {}
    filas = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(filas, list):
        return _TIPOS_CACHE["data"] or {}
    mapa = {int(t["id"]): t for t in filas
            if isinstance(t, dict) and t.get("id") is not None}
    _TIPOS_CACHE.update({"ts": ahora, "data": mapa})
    return mapa


def tipo_de_descuento(documento_id: int) -> Optional[str]:
    """"Value" o "Percentage" para ESE comprobante. None si no se sabe —
    y sin saberlo NO se manda descuento."""
    t = _tipos_documento().get(int(documento_id or 0)) or {}
    v = (t.get("discount_type") or "").strip()
    return v or None
