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
from backend.services import siigo as siigo_svc

log = logging.getLogger("postventa_banco")

MARCA_PRUEBA = "banco_pruebas"

# Reparto de los 20 casos entre los tres escenarios del criterio de salida.
PLAN_DEFAULT = [
    ("cambio_talla", "talla_pequena", 8),
    ("cambio_ref",   "cambio_por_otro", 7),
    ("reembolso",    "arrepentimiento", 5),
]


# Reparto de los casos de TIENDA. Se ejercitan los tres puntos a propósito:
# Florida y Arrayanes tienen bodegas distintas, y probar uno solo no revelaría
# un mapeo cruzado entre punto de venta y bodega.
PLAN_TIENDA_DEFAULT = [
    ("florida_caja1", "cambio_talla", "talla_pequena"),
    ("arrayanes",     "cambio_ref",   "cambio_por_otro"),
    ("florida_caja2", "cambio_talla", "talla_grande"),
    ("arrayanes",     "reembolso",    "arrepentimiento"),
    ("florida_caja1", "cambio_ref",   "cambio_por_otro"),
]


def _tienda_por_documento() -> dict[int, str]:
    """document_id de Siigo → clave del punto de venta."""
    from backend.services import tiendas
    salida = {}
    for p in tiendas.listar():
        t = tiendas.obtener(p["clave"]) or {}
        doc = t.get("documento_factura_id")
        if doc:
            salida[int(doc)] = p["clave"]
    return salida


def facturas_de_tienda(facturas: list[dict]) -> list[dict]:
    """De un lote de facturas, las hechas EN TIENDA que la DIAN ya aceptó.

    Se enlazan por **id**, no por nº de pedido: una compra presencial no tiene
    pedido Shopify. Esa era justamente la razón por la que el banco las saltaba
    y el flujo presencial se quedó sin probar.
    """
    mapa = _tienda_por_documento()
    salida = []
    for f in facturas:
        if not isinstance(f, dict):
            continue
        clave = mapa.get(int((f.get("document") or {}).get("id") or 0))
        if not clave:
            continue                      # online u otro prefijo
        if not F.factura_aceptada_dian(f):
            continue                      # sin aceptación DIAN no hay NC
        salida.append({"factura": f.get("name"), "factura_id": f.get("id"),
                       "tienda": clave, "numero_pedido": ""})
    return salida


def verificar_bodega_nc(payload: dict, clave_tienda: str) -> tuple[bool, str]:
    """La prenda devuelta debe entrar a la bodega de ESE punto.

    Si entra a la bodega online, el inventario de la tienda queda corto y el de
    MELONN inflado — y nadie se entera hasta el conteo físico.
    """
    from backend.services import tiendas
    esperada = int((tiendas.obtener(clave_tienda) or {}).get("bodega_id") or 0)
    items = payload.get("items") or []
    if not items:
        # Un payload vacío no prueba nada. Darlo por bueno es cómo un gate
        # llega a "verde" sin haber mirado lo que decía verificar.
        return False, "la NC llegó sin items: no hay bodega que verificar"
    malas = []
    for it in items:
        real = int((it.get("warehouse") or {}).get("id") or 0)
        if real != esperada:
            malas.append(f"{it.get('code')}→bodega {real}")
    if malas:
        return False, (f"la NC debía entrar a la bodega {esperada} "
                       f"({clave_tienda}) y entró a: {', '.join(malas)}")
    return True, f"bodega {esperada}"


def verificar_documento_factura(payload: dict, clave_tienda: str) -> tuple[bool, str]:
    """La factura del reemplazo sale con el comprobante que SI se puede usar
    por API.

    Ojo: NO es el prefijo de la caja. Siigo no deja emitir con FV-6/11/12
    (rangos DIAN del punto de venta), asi que hoy sale por FV-1 y el arqueo
    se cruza por los medios de pago. Ver tiendas.documento_para_facturar."""
    from backend.services import tiendas
    esperado = int(tiendas.documento_para_facturar(clave_tienda))
    real = int((payload.get("document") or {}).get("id") or 0)
    if real != esperado:
        return False, (f"la factura debía salir con el documento {esperado} "
                       f"({clave_tienda}) y salió con {real}")
    return True, f"documento {esperado}"


def verificar_pago_excedente(payload: dict, clave_tienda: str) -> tuple[bool, str]:
    """El excedente se cobra en la caja de ESE punto.

    En tienda la clienta está presente y paga ahí mismo; dejarlo como cuenta
    por cobrar es plata que nadie va a cobrar nunca.
    """
    from backend.services import tiendas
    # El ANTICIPO es el crédito que dejó la nota crédito, no plata que entre
    # por la caja: siempre está y es legítimo. Solo se juzga lo que la clienta
    # paga de más.
    pagos = [p for p in (payload.get("payments") or [])
             if p.get("id") and int(p["id"]) != F.ANTICIPO_CLIENTES_ID]
    if not pagos:
        return True, "sin excedente"
    malos = [str(p["id"]) for p in pagos
             if not tiendas.forma_pago_valida(clave_tienda, int(p["id"]))]
    if malos:
        return False, (f"formas de pago que no son de {clave_tienda}: "
                       f"{', '.join(malos)}")
    return True, f"{len(pagos)} pago(s) del punto"


def _pedidos_con_factura(cantidad: int) -> list[dict]:
    """Pedidos reales que ya tienen factura en Siigo (los únicos que sirven:
    sin factura original no hay nota crédito que emitir)."""
    # Paginar hasta juntar facturas que la DIAN ya aceptó: las del día no
    # admiten nota crédito y quedarse en la página 1 devolvía cero.
    aptas = descubrir.facturas_aceptadas(minimo=max(cantidad, 5))
    pedidos = []
    descartadas = 0
    for f in aptas:
        num = F.extraer_numero_pedido(f.get("observations") or "")
        if not num:
            continue           # facturas de tienda física: sin pedido Shopify
        # Solo facturas que la DIAN ya aceptó: a las de hoy no se les puede
        # hacer nota crédito todavía.
        if not F.factura_aceptada_dian(f):
            descartadas += 1
            continue
        pedidos.append({"numero_pedido": f"#{num}",
                        "factura": f.get("name"),
                        "factura_id": f.get("id")})
    if descartadas:
        log.info(f"[banco] {descartadas} facturas descartadas: DIAN no las aceptó aún")
    return pedidos


def _pago_del_punto(clave_tienda: str) -> Optional[int]:
    """Forma de pago de esa caja para cobrar el excedente. En tienda la clienta
    está presente y paga ahí mismo — no queda como cuenta por cobrar."""
    if not clave_tienda:
        return None
    from backend.services import tiendas
    formas = (tiendas.obtener(clave_tienda) or {}).get("formas_pago") or []
    return int(formas[0]["id"]) if formas else None


def _preview_factura_simulado(case_id: str, r: dict,
                              clave_tienda: str = "") -> Optional[dict]:
    """Arma la factura del reemplazo SIN exigir que la NC esté emitida.

    En dry-run la NC no se emite, así que `preview_factura_reemplazo` (que
    exige NC emitida) no aplica. Se reconstruye el cálculo con el crédito que
    la NC habría dejado, para validar el reparto anticipo/excedente.
    """
    from backend.services import fiscal_logic as FL
    from backend.services import fiscal_shopify as FS

    items = pv.items_caso(case_id)
    if not items:
        return {"_motivo": "el caso no tiene items en la DB"}
    it = items[0]
    credito = r.get("totales", {}).get("total")
    if not credito:
        return {"_motivo": "no hay total de la nota credito para usar de credito"}

    requested = (it.get("requested_sku") or "").strip()
    if requested:
        base = FS.precio_base_variante(requested)
        if base is None:
            return {"_motivo": f"Shopify no dio precio para el SKU {requested}"}
        item_reemplazo = {"code": requested, "description": requested,
                          "price_base": base}
    else:
        item_reemplazo = {"code": it.get("original_sku"),
                          "description": it.get("original_variant") or "",
                          "price_base": float(it.get("original_price") or 0)}

    # En tienda la factura sale del punto de venta: su prefijo, su bodega y su
    # caja. Simularla como venta online no probaría nada de eso.
    extra: dict = {}
    if clave_tienda:
        from backend.services import tiendas
        t = tiendas.validar_para_facturar(clave_tienda)
        extra = {"documento_id": tiendas.documento_para_facturar(clave_tienda),
                 "bodega_id": t["bodega_id"],
                 "pago_excedente_id": _pago_del_punto(clave_tienda)}

    payload = FL.construir_payload_factura_reemplazo(
        factura_original={"id": "sim", "name": "sim", "customer": {},
                          "seller": FL.VENDEDOR_ONLINE_ID},
        item_reemplazo=item_reemplazo, credito_con_iva=float(credito),
        modo="prueba", fecha="2026-01-01", **extra)
    return {"resumen": payload["_resumen"], "payload": payload}


def _correr_uno(pedido: dict, tipo: str, motivo: str, *, dry_run: bool,
                actor: str) -> dict:
    """Un caso completo: crear → aprobar → ítem → preview [→ emitir]."""
    tienda = pedido.get("tienda") or ""
    r: dict[str, Any] = {"pedido": pedido.get("numero_pedido") or pedido.get("factura"),
                         "canal": tienda or "online",
                         "tipo": tipo, "pasos": [], "ok": False}

    def paso(nombre: str, ok: bool, detalle: str = ""):
        r["pasos"].append({"paso": nombre, "ok": ok, "detalle": detalle[:300]})
        return ok

    try:
        caso = pv.crear_caso(tipo=tipo, reason=motivo,
                             customer_name="Prueba banco",
                             shopify_order_name=pedido.get("numero_pedido") or "",
                             # Una compra de tienda solo se puede enlazar por
                             # id de factura: no tiene nº de pedido.
                             siigo_invoice_id=pedido.get("factura_id") or "",
                             tienda=tienda,
                             pago_excedente_id=_pago_del_punto(tienda),
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

        # Cambio presencial: la prenda devuelta tiene que entrar al inventario
        # de ESA tienda. Si entra a la bodega online, la tienda queda corta y
        # MELONN inflada — y no se nota hasta el conteo físico.
        if tienda:
            ok_bod, det_bod = verificar_bodega_nc(prev.get("payload") or {}, tienda)
            if not paso("nc_entra_a_la_bodega_del_punto", ok_bod, det_bod):
                return r
    except Exception as e:  # noqa: BLE001
        return r if not paso("preview_nota_credito", False, str(e)) else r

    # Preview de la FACTURA del reemplazo: aquí se valida el reparto
    # anticipo / excedente, que es lo que el gate anterior no cubría.
    if tipo not in fiscal.TIPOS_SIN_FACTURA:
        try:
            prevf = _preview_factura_simulado(cid, r, clave_tienda=tienda)
            if prevf is None or prevf.get("_motivo"):
                # No pasa callado: si no se pudo validar la factura, el caso
                # FALLA y dice por qué.
                paso("preview_factura_reemplazo", False,
                     (prevf or {}).get("_motivo", "no se pudo simular"))
                return r
            res = prevf["resumen"]
            suma_ok = abs((res["anticipo"] + res["excedente"]) - res["total"]) < 1.0
            r["resumen_factura"] = res
            paso("preview_factura_reemplazo", suma_ok,
                 f"total {res['total']} = anticipo {res['anticipo']} + "
                 f"excedente {res['excedente']}")
            if not suma_ok:
                return r

            # La factura del cambio presencial sale del punto de venta: su
            # prefijo (FV-6/11/12) y su caja. Con FV-1 se descuadra la venta
            # de la tienda; con la caja de otra tienda, el arqueo.
            if tienda:
                pl = prevf.get("payload") or {}
                ok_doc, det_doc = verificar_documento_factura(pl, tienda)
                if not paso("factura_sale_del_punto", ok_doc, det_doc):
                    return r
                ok_pago, det_pago = verificar_pago_excedente(pl, tienda)
                if not paso("excedente_se_cobra_en_esa_caja", ok_pago, det_pago):
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

    # Las bodegas configuradas deben existir y estar activas en Siigo. Se
    # verifica ANTES de emitir: una bodega inventada no produce un error
    # visible hasta que Siigo rechaza el documento, y mientras el campo iba
    # mal formado ni siquiera eso — el stock simplemente no se movía.
    from backend.services import tiendas
    malas = tiendas.bodegas_invalidas(siigo_svc.listar_bodegas())
    if malas is None:
        return {"_error": "bodegas_no_verificables",
                "detalle": "No se pudieron leer las bodegas de Siigo "
                           "(GET /warehouses). Sin eso no se puede afirmar que "
                           "la configuración de las tiendas sirva."}
    if malas:
        return {"_error": "bodegas_mal_configuradas", "detalle": malas,
                "como_arreglar": "Los ids reales salen de GET /warehouses "
                                 "(endpoint /api/inventario/siigo/descubrir). "
                                 "El número que se ve en la pantalla de Siigo "
                                 "NO es el id de la API."}

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

    # ── Cambios EN TIENDA ──────────────────────────────────────────────
    # Antes se saltaban a propósito ("sin pedido Shopify") y por eso el gate
    # daba verde con el flujo presencial sin probar. Ahora se enlazan por id
    # de factura, que es la vía correcta.
    facturas_t = facturas_de_tienda(descubrir.facturas_recientes(max_paginas=8))
    aviso_tienda = ""
    if not facturas_t:
        # No pasa callado: un gate que no probó tienda no puede decir "verde".
        aviso_tienda = ("No se hallaron facturas de tienda (FV-6/11/12) "
                        "aceptadas por la DIAN. El flujo presencial NO se probó.")
        log.warning("[banco] %s", aviso_tienda)
    else:
        for i, (clave, tipo, motivo) in enumerate(PLAN_TIENDA_DEFAULT):
            # Solo se usan facturas del punto que toca: la bodega y el prefijo
            # se validan contra ESE punto.
            del_punto = [f for f in facturas_t if f["tienda"] == clave]
            if not del_punto:
                log.info("[banco] sin facturas de %s, se omite", clave)
                continue
            resultados.append(_correr_uno(del_punto[i % len(del_punto)],
                                          tipo, motivo,
                                          dry_run=dry_run, actor=actor))

    ok = [r for r in resultados if r.get("ok")]
    fallidos = [r for r in resultados if not r.get("ok")]
    por_tipo: dict[str, dict] = {}
    for r in resultados:
        d = por_tipo.setdefault(r["tipo"], {"total": 0, "ok": 0})
        d["total"] += 1
        d["ok"] += 1 if r.get("ok") else 0

    por_canal: dict[str, dict] = {}
    for r in resultados:
        d = por_canal.setdefault(r.get("canal", "online"), {"total": 0, "ok": 0})
        d["total"] += 1
        d["ok"] += 1 if r.get("ok") else 0

    # El gate NO puede decir "verde" si dejó un canal sin probar. Esa fue
    # exactamente la falla del gate anterior: 20/20 en verde con el flujo de
    # tienda nunca ejercitado, y se rompió en producción.
    de_tienda = [r for r in resultados if r.get("canal") != "online"]
    cubre_tienda = bool(de_tienda)
    faltas = []
    if not cubre_tienda:
        faltas.append(aviso_tienda or "no se probó ningún cambio en tienda")
    if len(ok) < total:
        faltas.append(f"solo {len(ok)} casos exitosos de {total} pedidos")

    return {
        "modo": fiscal_siigo.modo_actual(),
        "dry_run": dry_run,
        "pedidos_usados": len(pedidos),
        "total": len(resultados),
        "exitosos": len(ok),
        "fallidos": len(fallidos),
        "por_tipo": por_tipo,
        "por_canal": por_canal,
        "cobertura": {
            "online": len(resultados) - len(de_tienda),
            "tienda": len(de_tienda),
            "puntos_probados": sorted({r["canal"] for r in de_tienda}),
        },
        "gate_verde": len(fallidos) == 0 and len(ok) >= total and cubre_tienda,
        "por_que_no_verde": faltas,
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
