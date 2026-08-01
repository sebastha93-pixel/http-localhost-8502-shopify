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


def _clasificar_descarte(item: dict) -> tuple[str, str]:
    """(regla, detalle) por la que este pedido crudo NO llega al tablero.
    ('', '') si pasa todos los filtros."""
    import melonn_client as mc

    est = item.get("sell_order_state") or {}
    code = int(est.get("code") or 0)
    nombre = str(est.get("name") or "")
    nombre_limpio = mc._limpiar_nombre_estado(nombre)

    if item.get("is_b2b"):
        return ("b2b", "marcado is_b2b — el tablero es solo D2C")
    if code in mc.CODIGOS_EXCLUIR:
        return ("codigo_excluido", f"code {code} {nombre_limpio} (cancelado/devolución)")
    if code in mc.CODIGOS_PROCESO_INTERNO:
        # ESTE es el sospechoso: Melonn cuenta estos como pendientes porque no
        # han salido de bodega, y el tablero los borra por "no puedes actuar".
        return ("proceso_interno", f"code {code} {nombre_limpio}")
    if nombre_limpio in mc.ESTADOS_EXCLUIR:
        return ("nombre_excluido", nombre_limpio)
    if nombre_limpio in mc.ESTADOS_PROCESO_INTERNO:
        return ("nombre_proceso_interno", nombre_limpio)

    sub = mc._sub_estado_logistico(nombre_limpio, code,
                                   bool(item.get("payment_on_delivery_type")))
    if sub == "otro":
        return ("sin_clasificar",
                f"code {code} {nombre_limpio} — no cae en ninguna categoría")
    if sub not in ("pendiente_despacho", "en_preparacion", "en_transito",
                   "novedad", "entregado"):
        return ("sub_estado_no_listado", f"{sub}")

    fc = mc._parsear_fecha(item.get("creation_date"))
    corte = mc._fecha_corte()
    es_activo = (code in mc.CODIGOS_ACTIVOS
                 or nombre_limpio in mc.ESTADOS_NOVEDAD_EXTERNA)
    if fc and fc < corte and not es_activo:
        return ("fuera_de_ventana", f"creado {fc} y no está activo")
    return ("", "")


def reporte(*, solo_contraentrega: bool = False, max_ejemplos: int = 40) -> dict:
    """Compara el listado crudo de Melonn contra lo que llega al tablero."""
    import melonn_client as mc

    crudos = mc._fetch_api_raw() if hasattr(mc, "_fetch_api_raw") else None
    if crudos is None:
        return {"error": "no pude obtener el listado crudo; falta _fetch_api_raw"}

    if solo_contraentrega:
        crudos = [c for c in crudos if c.get("payment_on_delivery_type")]

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
            "cod": bool(item.get("payment_on_delivery_type")),
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

    return {
        "crudos_de_melonn": len(crudos),
        "llegan_al_tablero": len(pasan),
        "descartados": sum(len(v) for v in descartados.values()),
        "por_regla": {k: len(v) for k, v in sorted(
            descartados.items(), key=lambda x: -len(x[1]))},
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
