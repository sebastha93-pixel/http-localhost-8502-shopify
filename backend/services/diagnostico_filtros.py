"""diagnostico_filtros.py — ¿qué pedidos descarta el tablero, y por qué regla?

POR QUÉ EXISTE (2026-08-01): Sebastián contó 21 contraentregas pendientes en
Melonn y el tablero mostraba 17. Faltaban 4 y no había forma de saber dónde se
caían: entre la respuesta cruda de Melonn y la tabla hay seis filtros distintos
(códigos excluidos, proceso interno, B2B, ventana de 90 días, whitelist de
sub_estado, y el filtro de la pestaña) y ninguno deja rastro de lo que descarta.

Este módulo pide el listado CRUDO a Melonn y clasifica cada pedido por la regla
que lo saca, con su número de orden. Es la única forma de responder "¿por qué no
está el pedido X?" sin leer código.

No arregla nada: dice la verdad sobre lo que se está perdiendo.
"""
from __future__ import annotations

import logging
from collections import Counter

log = logging.getLogger(__name__)


def _es_cod(item: dict) -> bool:
    """Contraentrega, con la MISMA regla que _normalizar en melonn_client.

    Estaba mal (2026-08-01): usaba `bool(item["payment_on_delivery_type"])`, y
    ese campo es un OBJETO que viene en TODOS los pedidos — así que daba True
    siempre. Efecto: `?solo_contraentrega=true` no filtraba nada y el reporte
    marcaba todos los pedidos como contraentrega. La regla real es el monto o el
    código del tipo de recaudo.
    """
    monto_raw = item.get("payment_on_delivery_amount")
    try:
        monto = float(str(monto_raw).replace(",", ".")) if monto_raw else 0.0
    except Exception:
        monto = 0.0
    tipo_obj = item.get("payment_on_delivery_type") or {}
    tipo = int(tipo_obj.get("code", 0) or 0) if isinstance(tipo_obj, dict) else 0
    return monto > 0 or tipo > 0


def _clasificar_descarte(item: dict) -> tuple[str, str]:
    """(regla, detalle) por la que este pedido crudo NO llega al tablero.
    ('', '') si pasa todos los filtros."""
    import melonn_client as mc

    est = item.get("sell_order_state") or {}
    code = int(est.get("code") or 0)
    nombre = str(est.get("name") or "")
    nombre_limpio = mc._limpiar_nombre_estado(nombre)

    # El orden reproduce el de _fetch_api_filtrado. Si acá se evalúa distinto,
    # el reporte miente sobre por qué se cayó el pedido.
    es_activo = (code in mc.CODIGOS_ACTIVOS
                 or nombre_limpio in mc.ESTADOS_NOVEDAD_EXTERNA)
    # Igual que en _fetch_api_filtrado: la ventana solo se salta para los que
    # siguen ABIERTOS. Entregado está cerrado y sí se corta por viejo.
    sigue_abierto = (code in mc.CODIGOS_ACTIVOS_OPERATIVO
                     or nombre_limpio in mc.ESTADOS_NOVEDAD_EXTERNA)

    fc = mc._parsear_fecha(item.get("creation_date"))
    corte = mc._fecha_corte()
    if fc and fc < corte and not sigue_abierto:
        return ("fuera_de_ventana",
                f"creado {fc}, antes del corte {corte}, y ya está cerrado")

    # El filtro real es una WHITELIST por código, no una lista negra. Se separa
    # el motivo para poder distinguir "cancelado" (correcto) de "código que no
    # conocemos" (bug: el pedido existe y nadie lo ve).
    if not es_activo:
        if code in mc.CODIGOS_EXCLUIR:
            return ("cancelado", f"code {code} {nombre_limpio} (cancelado/devolución)")
        if code in mc.CODIGOS_PROCESO_INTERNO:
            return ("proceso_interno", f"code {code} {nombre_limpio}")
        return ("codigo_no_clasificado",
                f"code {code} {nombre_limpio} — NO está en ningún CODIGOS_*, "
                f"el pedido es invisible en el tablero")

    if nombre_limpio in mc.ESTADOS_EXCLUIR:
        return ("nombre_excluido", nombre_limpio)
    if nombre_limpio in mc.ESTADOS_PROCESO_INTERNO:
        return ("nombre_proceso_interno", nombre_limpio)

    if item.get("is_b2b"):
        return ("b2b", "marcado is_b2b — el tablero es solo D2C")

    sub = mc._sub_estado_logistico(nombre_limpio, code, _es_cod(item))
    if sub not in ("pendiente_despacho", "en_preparacion", "en_transito",
                   "novedad", "entregado"):
        return ("sub_estado_no_listado",
                f"code {code} {nombre_limpio} → sub_estado '{sub}', "
                f"que no está en la lista de inclusión")
    return ("", "")


def reporte(*, solo_contraentrega: bool = False, max_ejemplos: int = 40) -> dict:
    """Compara el listado crudo de Melonn contra lo que llega al tablero."""
    import melonn_client as mc

    crudos = mc._fetch_api_raw() if hasattr(mc, "_fetch_api_raw") else None
    if crudos is None:
        return {"error": "no pude obtener el listado crudo; falta _fetch_api_raw"}

    if solo_contraentrega:
        crudos = [c for c in crudos if _es_cod(c)]

    descartados: dict[str, list[dict]] = {}
    pasan = []
    for item in crudos:
        regla, detalle = _clasificar_descarte(item)
        fila = {
            "orden": item.get("external_order_number"),
            "melonn": item.get("internal_order_number"),
            "estado": ((item.get("sell_order_state") or {}).get("name")),
            "code": ((item.get("sell_order_state") or {}).get("code")),
            "creado": item.get("creation_date"),
            "cod": _es_cod(item),
            "detalle": detalle,
        }
        if regla:
            descartados.setdefault(regla, []).append(fila)
        else:
            pasan.append(fila)

    # Los que Melonn considera SIN DESPACHAR: no están entregados ni en la calle.
    # Es lo que el panel de Melonn cuenta como "pendientes".
    def _sin_despachar(f) -> bool:
        return int(f.get("code") or 0) not in (6, 7, 8)

    # ── FANTASMAS: el tablero dice una cosa y Melonn dice otra ───────────────
    # Esto es lo que faltaba y lo que destapó el bug del 2026-08-01: no bastaba
    # con revisar qué se descarta, porque los pedidos que sobraban estaban en el
    # caché con un estado que Melonn ya había cambiado (o cancelado).
    # Se cruza por ID de Melonn, no por número de tienda: un mismo #61436 puede
    # tener tres órdenes Melonn (envío, cancelación, reposición) y compararlas
    # entre sí da falsos positivos.
    fantasmas: list[dict] = []
    try:
        estado_real = {}
        for c in crudos:
            mid = str(c.get("internal_order_number") or "")
            if mid:
                est_c = c.get("sell_order_state") or {}
                estado_real[mid] = (int(est_c.get("code") or 0),
                                    str(est_c.get("name") or ""))
        en_tablero, _, _ = mc.obtener_pedidos_activos()
        for p in en_tablero:
            mid = str(p.get("orden_melonn") or "")
            if not mid or mid not in estado_real:
                continue
            code_real, nombre_real = estado_real[mid]
            code_app = int(p.get("estado_melonn_code") or 0)
            if code_real == code_app:
                continue
            if solo_contraentrega and not p.get("es_contraentrega"):
                continue
            fantasmas.append({
                "orden": p.get("orden_tienda"),
                "melonn": mid,
                "app_dice": f"code {code_app} {p.get('estado_melonn','')}",
                "melonn_dice": f"code {code_real} {nombre_real}",
                "cod": bool(p.get("es_contraentrega")),
                "cancelado_en_melonn": code_real in mc.CODIGOS_EXCLUIR,
            })
    except Exception as e:
        log.warning(f"[diagnostico] no pude cruzar fantasmas: {e}")
        fantasmas = [{"error": str(e)[:200]}]

    return {
        "crudos_de_melonn": len(crudos),
        "llegan_al_tablero": len(pasan),
        "descartados": sum(len(v) for v in descartados.values()),
        "por_regla": {k: len(v) for k, v in sorted(
            descartados.items(), key=lambda x: -len(x[1]))},
        # Pedidos cuyo estado en la app NO es el que Melonn tiene hoy. Si esta
        # lista no está vacía, el tablero no es auditable: da igual el conteo.
        "fantasmas_total": len(fantasmas),
        "fantasmas_cancelados": sum(
            1 for f in fantasmas if f.get("cancelado_en_melonn")),
        "fantasmas": fantasmas[:max_ejemplos],
        # Los descartados que NO están despachados: estos son los que hacen que
        # el conteo del tablero no cuadre con el de Melonn.
        "descartados_sin_despachar": {
            k: [f for f in v if _sin_despachar(f)][:max_ejemplos]
            for k, v in descartados.items()
            if any(_sin_despachar(f) for f in v)
        },
        "codigos_crudos": dict(Counter(
            (c.get("sell_order_state") or {}).get("code") for c in crudos)),
    }
