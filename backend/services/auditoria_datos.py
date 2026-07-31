"""auditoria_datos.py — ¿de qué se puede fiar el módulo logístico y de qué no?

POR QUÉ EXISTE (2026-07-31): el requisito es que la información sea fiel y
auditable. Hoy no lo es del todo, y lo peligroso no es que falten datos: es que
faltaban EN SILENCIO. Ejemplos reales encontrados esta semana, todos invisibles
desde la pantalla:

  · `dias_en_transito` de Melonn valía 0 en los 572 pedidos que dependían de él,
    así que el 53% de la flota mostraba "0 días" y NINGUNO podía salir vencido.
  · `cargar_map()` leía 1.000 de 2.875 overrides: el 65% de guías, nombres y
    teléfonos se descartaba sin un error.
  · El M-id interno de Melonn se mostraba como si fuera número de guía.

Este módulo no arregla nada: MIDE. Dice, campo por campo, qué porcentaje está
medido, qué está estimado y qué no se sabe, y entrega la lista de pedidos que no
se pueden auditar para poder actuar sobre ellos. Un número sin procedencia no se
audita, se cree — y creer es justo lo que hay que dejar de hacer.

No consulta Melonn ni Shopify: trabaja sobre lo que la app YA devuelve, que es
exactamente lo que ve el usuario. Medir la fuente en vez de la pantalla fue el
error que dejó pasar el bug de las guías.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

# Qué tan confiable es cada procedencia de la fecha de despacho.
#   observado  = LO VIMOS pasar (transición de estado). Máxima confianza.
#   melonn     = ship_timestamp de la API. Bueno, pero manda basura a veces.
#   shopify    = fecha del REGISTRO del fulfillment, no del despacho físico.
CONFIANZA_FECHA = {
    "transicion_observada":   "alta",
    "melonn_ship_timestamp":  "media",
    "shopify_fulfillment":    "baja",
    "desconocido":            "baja",
    "":                       "sin_dato",
}

# Campos que el módulo logístico muestra y de los que alguien depende para operar.
CAMPOS_OPERATIVOS = (
    "nombre_comprador", "telefono_comprador", "ciudad_destino",
    "carrier_real", "guia_real", "fecha_despacho", "fecha_entrega",
)

ESTADOS_DESPACHADOS = ("en_transito", "novedad", "entregado")


def _vacio(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _pct(parte: int, total: int) -> float:
    return round(100.0 * parte / total, 1) if total else 0.0


def reporte(pedidos: list[dict], *, max_ejemplos: int = 50) -> dict:
    """Radiografía de confiabilidad de la lista que devuelve el módulo."""
    total = len(pedidos)
    if not total:
        return {"total": 0, "advertencias": ["la lista vino vacía"]}

    # ── Los días: lo que más se usa para decidir ─────────────────────────
    por_origen = Counter(p.get("dias_origen") or "sin_marcar" for p in pedidos)
    despachados = [p for p in pedidos
                   if (p.get("sub_estado_logistico") or "") in ESTADOS_DESPACHADOS]
    medidos = [p for p in despachados if p.get("dias_origen") == "medido"]
    estimados = [p for p in despachados if p.get("dias_origen") == "estimado"]
    sin_dato = [p for p in despachados if p.get("dias_origen") == "sin_dato"]

    dias = {
        "pedidos_despachados": len(despachados),
        "medidos": len(medidos),
        "medidos_pct": _pct(len(medidos), len(despachados)),
        "estimados": len(estimados),
        "estimados_pct": _pct(len(estimados), len(despachados)),
        "sin_dato": len(sin_dato),
        "desglose_por_origen": dict(por_origen),
        # LA CIFRA HONESTA: qué porcentaje del SLA se puede auditar de verdad.
        "auditable_pct": _pct(len(medidos), len(despachados)),
    }

    # ── Procedencia de la fecha de despacho ──────────────────────────────
    conf = Counter()
    for p in despachados:
        origen = p.get("fecha_despacho_origen") or ""
        conf[CONFIANZA_FECHA.get(origen, "baja")] += 1
    fecha_despacho = {
        "por_confianza": dict(conf),
        "alta_pct": _pct(conf.get("alta", 0), len(despachados)),
    }

    # ── Cobertura de los campos operativos ──────────────────────────────
    campos = {}
    for c in CAMPOS_OPERATIVOS:
        con = sum(1 for p in pedidos if not _vacio(p.get(c)))
        campos[c] = {"con_dato": con, "pct": _pct(con, total)}

    # ── Incoherencias que hacen desconfiar del tablero ──────────────────
    problemas: list[dict] = []

    def _anota(clave: str, desc: str, lista: list[dict]) -> None:
        if lista:
            problemas.append({
                "clave": clave, "descripcion": desc, "n": len(lista),
                "ordenes": [str(p.get("orden_tienda") or p.get("orden_melonn"))
                            for p in lista[:max_ejemplos]],
            })

    _anota("dias_sin_procedencia",
           "muestran días pero no dicen de dónde salieron (no auditable)",
           [p for p in pedidos if (p.get("dias_real") or 0) > 0
            and not p.get("dias_origen")])
    _anota("despachado_sin_fecha",
           "despachados sin fecha de despacho: su SLA es una estimación",
           [p for p in despachados if _vacio(p.get("fecha_despacho"))
            and _vacio(p.get("fecha_despacho_observada"))])
    _anota("sin_despachar_con_dias",
           "no han salido de bodega pero muestran días de tránsito",
           [p for p in pedidos
            if (p.get("sub_estado_logistico") or "") not in ESTADOS_DESPACHADOS
            and (p.get("dias_real") or 0) > 0])
    _anota("entregado_sin_fecha_entrega",
           "entregados sin fecha de entrega: no se puede medir cuánto tardaron",
           [p for p in pedidos if p.get("sub_estado_logistico") == "entregado"
            and _vacio(p.get("fecha_entrega"))])
    _anota("guia_sin_transportadora",
           "tienen número de guía pero no dicen de qué transportadora",
           [p for p in pedidos if not _vacio(p.get("guia_real"))
            and _vacio(p.get("carrier_real"))])
    _anota("contraentrega_sin_telefono",
           "contraentrega sin teléfono: no se puede confirmar con el cliente",
           [p for p in pedidos if p.get("es_contraentrega")
            and _vacio(p.get("telefono_comprador"))])

    # ── Veredicto, sin adornos ──────────────────────────────────────────
    auditable = dias["auditable_pct"]
    if auditable >= 95:
        veredicto = "AUDITABLE"
        resumen = f"El {auditable}% del SLA sale de una fecha de despacho real."
    elif auditable >= 60:
        veredicto = "PARCIAL"
        resumen = (f"Solo el {auditable}% del SLA es medido; el resto se estima "
                   f"desde la creación del pedido y NO sirve para auditar.")
    else:
        veredicto = "NO AUDITABLE"
        resumen = (f"Apenas el {auditable}% del SLA sale de una fecha real. "
                   f"{len(estimados)} pedidos muestran días estimados: sirven "
                   f"para vigilar riesgo, no para medir cumplimiento.")

    return {
        "total": total,
        "veredicto": veredicto,
        "resumen": resumen,
        "dias": dias,
        "fecha_despacho": fecha_despacho,
        "campos": campos,
        "problemas": problemas,
    }
