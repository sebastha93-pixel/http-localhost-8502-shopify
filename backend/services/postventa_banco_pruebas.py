"""
backend.services.postventa_banco_pruebas — Suite del gate de 20 casos.

Valida el motor fiscal contra pedidos REALES de la cuenta, cubriendo los tres
escenarios que exige el criterio de salida:

  1. cambio_talla   — misma referencia, mismo precio
  2. cambio_ref     — otra referencia, con diferencia de precio
  3. reembolso      — solo nota crédito, sin factura de reemplazo

MODO POR DEFECTO: `dry_run=True` → llega hasta el PREVIEW y NO emite nada.
El preview es donde se valida lo que importa: que se encuentre la factura,
que los ítems casen por SKU, y que los montos y el payload salgan correctos.
Cero documentos basura en Siigo.

Con `dry_run=False` sí emite (en modo prueba de Siigo, sin sello DIAN).

Los casos creados quedan marcados con `source='banco_pruebas'` para poder
identificarlos y limpiarlos después.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from backend.services import postventa as pv
from backend.services import postventa_siigo as descubrir
from backend.services import postventa_fiscal as fiscal
from backend.services import fiscal_siigo
from backend.services import fiscal_logic as F

log = logging.getLogger("postventa_banco")

MARCA_PRUEBA = "banco_pruebas"

# Reparto de los 20 casos entre los tres escenarios del criterio de salida.
PLAN_DEFAULT = [
    ("cambio_talla", "talla_pequena", 8),
    ("cambio_ref",   "cambio_por_otro", 7),
    ("reembolso",    "arrepentimiento", 5),
]


def _pedidos_con_factura(cantidad: int) -> list[dict]:
    """Pedidos reales que ya tienen factura en Siigo (los únicos que sirven:
    sin factura original no hay nota crédito que emitir)."""
    data = descubrir.inspeccionar_facturas(min(cantidad * 2, 10))
    if not isinstance(data, dict) or data.get("_error"):
        return []
    pedidos = []
    for f in data.get("facturas", []):
        num = F.extraer_numero_pedido(f.get("observations") or "")
        if not num:
            continue           # facturas de tienda física: sin pedido Shopify
        pedidos.append({"numero_pedido": f"#{num}",
                        "factura": f.get("name"),
                        "factura_id": f.get("id")})
    return pedidos


def _preview_factura_simulado(case_id: str, r: dict) -> Optional[dict]:
    """Arma la factura del reemplazo SIN exigir que la NC esté emitida.

    En dry-run la NC no se emite, así que `preview_factura_reemplazo` (que
    exige NC emitida) no aplica. Se reconstruye el cálculo con el crédito que
    la NC habría dejado, para validar el reparto anticipo/excedente.
    """
    from backend.services import fiscal_logic as FL
    from backend.services import fiscal_shopify as FS

    items = pv.items_caso(case_id)
    if not items:
        return None
    it = items[0]
    credito = r.get("totales", {}).get("total")
    if not credito:
        return None

    requested = (it.get("requested_sku") or "").strip()
    if requested:
        base = FS.precio_base_variante(requested)
        if base is None:
            return None
        item_reemplazo = {"code": requested, "description": requested,
                          "price_base": base}
    else:
        item_reemplazo = {"code": it.get("original_sku"),
                          "description": it.get("original_variant") or "",
                          "price_base": float(it.get("original_price") or 0)}

    payload = FL.construir_payload_factura_reemplazo(
        factura_original={"id": "sim", "name": "sim", "customer": {},
                          "seller": FL.VENDEDOR_ONLINE_ID},
        item_reemplazo=item_reemplazo, credito_con_iva=float(credito),
        modo="prueba", fecha="2026-01-01")
    return {"resumen": payload["_resumen"]}


def _correr_uno(pedido: dict, tipo: str, motivo: str, *, dry_run: bool,
                actor: str) -> dict:
    """Un caso completo: crear → aprobar → ítem → preview [→ emitir]."""
    r: dict[str, Any] = {"pedido": pedido["numero_pedido"], "tipo": tipo,
                         "pasos": [], "ok": False}

    def paso(nombre: str, ok: bool, detalle: str = ""):
        r["pasos"].append({"paso": nombre, "ok": ok, "detalle": detalle[:300]})
        return ok

    try:
        caso = pv.crear_caso(tipo=tipo, reason=motivo,
                             customer_name="Prueba banco",
                             shopify_order_name=pedido["numero_pedido"],
                             source=MARCA_PRUEBA)
        r["case_id"] = caso["id"]
        r["case_number"] = caso["case_number"]
        paso("crear_caso", True, caso["case_number"])
    except Exception as e:  # noqa: BLE001
        paso("crear_caso", False, str(e))
        return r

    cid = r["case_id"]
    try:
        pv.cambiar_estado(cid, "pendiente_validacion", actor=actor)
        pv.cambiar_estado(cid, "aprobado", actor=actor)
        paso("aprobar", True)
    except Exception as e:  # noqa: BLE001
        return r if not paso("aprobar", False, str(e)) else r

    # Ítem tomado de la factura real: garantiza que el SKU exista en Siigo.
    try:
        info = fiscal.items_factura_del_caso(cid)
        items = info.get("items") or []
        if not items:
            return r if not paso("items_factura", False, "factura sin items") else r
        it = items[0]
        # Para cambio_ref se pide otra referencia: se usa el segundo ítem si
        # la factura lo tiene; si no, se marca y el caso corre como cambio simple.
        requested = ""
        if tipo == "cambio_ref":
            # Buscar en Shopify una prenda MÁS CARA: así el caso ejercita el
            # excedente (la clienta paga la diferencia), que es el camino que
            # importa validar y que la factura del pedido no siempre permite.
            from backend.services import fiscal_shopify as FS
            cara = FS.variante_mas_cara_que(it.get("price") or 0,
                                            excluir_sku=it["code"])
            if cara:
                requested = cara["sku"]
                r["reemplazo_mas_caro"] = cara
                paso("buscar_reemplazo_mas_caro", True,
                     f"{cara['sku']} · {cara['precio_con_iva']}")
            else:
                requested = (items[1]["code"] if len(items) > 1 else "")
                paso("buscar_reemplazo_mas_caro", False,
                     "no se halló una variante más cara en Shopify")
        pv.agregar_item(cid, original_sku=it["code"],
                        original_variant=it.get("description") or "",
                        original_price=it.get("price") or 0,
                        requested_sku=requested)
        paso("agregar_item", True, f"{it['code']} · {it.get('price')}")
    except Exception as e:  # noqa: BLE001
        return r if not paso("agregar_item", False, str(e)) else r

    # PREVIEW: aquí se valida lo que de verdad importa.
    try:
        prev = fiscal.preview_nota_credito(cid)
        tot = prev.get("totales", {})
        # El total debe ser subtotal + 19%: si esto cuadra, el payload sirve.
        esperado = F.total_con_iva(tot.get("subtotal", 0))
        cuadra = abs(esperado - tot.get("total", 0)) < 1.0
        r["totales"] = tot
        r["factura_original"] = (prev.get("factura_original") or {}).get("name")
        paso("preview_nota_credito", cuadra,
             f"subtotal {tot.get('subtotal')} + IVA {tot.get('iva')} = "
             f"{tot.get('total')} (esperado {esperado})")
        if not cuadra:
            return r
    except Exception as e:  # noqa: BLE001
        return r if not paso("preview_nota_credito", False, str(e)) else r

    # Preview de la FACTURA del reemplazo: aquí se valida el reparto
    # anticipo / excedente, que es lo que el gate anterior no cubría.
    if tipo not in fiscal.TIPOS_SIN_FACTURA:
        try:
            prevf = _preview_factura_simulado(cid, r)
            if prevf is not None:
                res = prevf["resumen"]
                suma_ok = abs((res["anticipo"] + res["excedente"]) - res["total"]) < 1.0
                r["resumen_factura"] = res
                paso("preview_factura_reemplazo", suma_ok,
                     f"total {res['total']} = anticipo {res['anticipo']} + "
                     f"excedente {res['excedente']}")
                if not suma_ok:
                    return r
        except Exception as e:  # noqa: BLE001
            paso("preview_factura_reemplazo", False, str(e))
            return r

    if dry_run:
        r["ok"] = True
        r["emitido"] = False
        return r

    # Emisión real (en modo prueba de Siigo: sin sello DIAN).
    try:
        res = fiscal.emitir_nota_credito(cid, actor=actor)
        r["nota_credito"] = res.get("siigo_document_number")
        paso("emitir_nota_credito", True, str(res.get("siigo_document_number")))
    except Exception as e:  # noqa: BLE001
        return r if not paso("emitir_nota_credito", False, str(e)) else r

    if tipo in fiscal.TIPOS_SIN_FACTURA:
        paso("sin_factura_por_tipo", True, f"{tipo} no lleva factura")
        r["ok"] = True
        r["emitido"] = True
        return r

    try:
        prevf = fiscal.preview_factura_reemplazo(cid)
        r["resumen_factura"] = prevf.get("resumen")
        resf = fiscal.emitir_factura_reemplazo(cid, actor=actor)
        r["factura_reemplazo"] = resf.get("siigo_document_number")
        paso("emitir_factura", True, str(resf.get("siigo_document_number")))
    except Exception as e:  # noqa: BLE001
        return r if not paso("emitir_factura", False, str(e)) else r

    r["ok"] = True
    r["emitido"] = True
    return r


def correr(*, total: int = 20, dry_run: bool = True,
           actor: str = "banco_pruebas") -> dict:
    """Corre el gate de N casos. Por defecto NO emite (dry_run)."""
    if fiscal_siigo.modo_actual() == "produccion" and not dry_run:
        return {"_error": "modo_produccion",
                "detalle": "El banco no emite en modo producción: serían "
                           "documentos electrónicos reales ante la DIAN. "
                           "Ponga SIIGO_POSTVENTA_MODO=prueba."}

    pedidos = _pedidos_con_factura(total)
    if not pedidos:
        return {"_error": "sin_pedidos_facturados",
                "detalle": "No se encontraron facturas de venta online con "
                           "'Orden Nº' en observations."}

    plan = []
    for tipo, motivo, n in PLAN_DEFAULT:
        plan.extend([(tipo, motivo)] * n)
    plan = plan[:total]

    resultados = []
    for i, (tipo, motivo) in enumerate(plan):
        pedido = pedidos[i % len(pedidos)]     # rota los pedidos disponibles
        resultados.append(_correr_uno(pedido, tipo, motivo,
                                      dry_run=dry_run, actor=actor))

    ok = [r for r in resultados if r.get("ok")]
    fallidos = [r for r in resultados if not r.get("ok")]
    por_tipo: dict[str, dict] = {}
    for r in resultados:
        d = por_tipo.setdefault(r["tipo"], {"total": 0, "ok": 0})
        d["total"] += 1
        d["ok"] += 1 if r.get("ok") else 0

    return {
        "modo": fiscal_siigo.modo_actual(),
        "dry_run": dry_run,
        "pedidos_usados": len(pedidos),
        "total": len(resultados),
        "exitosos": len(ok),
        "fallidos": len(fallidos),
        "por_tipo": por_tipo,
        "gate_verde": len(fallidos) == 0 and len(ok) >= total,
        "detalle_fallidos": fallidos,
        "resultados": resultados,
    }


def limpiar(*, confirmar: bool = False) -> dict:
    """Borra los casos creados por el banco (source='banco_pruebas').

    Las tablas hijas caen por ON DELETE CASCADE. Exige confirmar=True.
    OJO: no borra los documentos que hayan quedado en Siigo — esos se
    eliminan desde Siigo (son Proforma/no estampados, se pueden borrar).
    """
    if not confirmar:
        return {"_error": "requiere_confirmacion",
                "detalle": "Llamar con confirmar=true para borrar."}
    sb = pv._sb()
    if sb is None:
        return {"_error": "supabase_no_configurado"}
    r = (sb.table("postventa_cases").select("id")
           .eq("brand_id", pv._brand_id()).eq("source", MARCA_PRUEBA).execute())
    ids = [f["id"] for f in (r.data or [])]
    for cid in ids:
        sb.table("postventa_cases").delete().eq("id", cid).execute()
    return {"borrados": len(ids)}
