"""
backend.services.metricas — Clasificación de riesgo + métricas globales.

Replica la lógica de dashboard/shared.py:_procesar_df y metricas_globales,
pero sin dependencias de Streamlit. Usa src/riesgo.py directamente.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from riesgo import calcular_riesgo  # noqa: E402

MAX_DIAS_ACTIVO = 20

# ── Estados de Melonn que se consideran "novedad/incidencia" operativa ───────
# Son los que requieren gestión humana (llamar cliente, autorizar, escalar).
# Excluimos estados internos de proceso que no son accionables (picking, etc.)
NOVEDADES_VISIBLES = {
    # COD — transportadora no pudo entregar
    "Delivery not posible",
    "Entrega no posible",

    # Sin stock / expired promises / SM restriction → "on stand by - not able to fulfil - X"
    "on stand by - not able to fulfil - no stock",
    "En espera - sin stock",
    "on stand by - not able to fulfil - expired promises",
    "En espera - promesas vencidas",
    "on stand by - not able to fulfil - SM restriction",
    "Restricción método de envío",

    # Hold por condiciones externas/internas — NO incluye seller (esos están en
    # "Pendientes despacho" donde se autorizan con el botón Autorizar)
    "All items reserved - fulfillment on hold - ext. conditionals",
    "All items reserved - fulfillment on hold - int. conditionals",

    # Errores genéricos
    "Error - not able to process",
    "Error - no es posible procesar",
}


def es_novedad_visible(p: dict) -> bool:
    """True si el pedido aparece en Novedades/Incidencias del dashboard."""
    if p.get("sub_estado_logistico") != "novedad":
        return False
    estado = (p.get("estado_melonn") or "").strip()
    return estado in NOVEDADES_VISIBLES


# ── Helpers internos ─────────────────────────────────────────────────────────

def _dias_reales(p: dict) -> int:
    """
    Días que el pedido ha estado / estuvo en tránsito.

    - Si está entregado y existe fecha_entrega: fecha_entrega - fecha_despacho
      (mide el tiempo REAL que tomó la entrega, no días después de entregado)
    - Si está activo: hoy - fecha_despacho
    - Fallback: campo dias_en_transito del pedido
    """
    fd = p.get("fecha_despacho")
    if not fd:
        return int(p.get("dias_en_transito") or 0)

    try:
        fd_date = date.fromisoformat(str(fd))
    except Exception:
        return int(p.get("dias_en_transito") or 0)

    # Si está entregado y hay fecha de entrega → usar tiempo real
    sub = p.get("sub_estado_logistico", "")
    fe = p.get("fecha_entrega")
    if sub == "entregado" and fe:
        try:
            return max(0, (date.fromisoformat(str(fe)) - fd_date).days)
        except Exception:
            pass

    return max(0, (date.today() - fd_date).days)


def _parse_cod(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except Exception:
        pass
    s = str(v).replace("$", "").replace(",", "").replace(".", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0


# ── Clasificación por pedido ──────────────────────────────────────────────────

def clasificar(p: dict) -> dict:
    """Añade Nivel, Sub_Estado, Tipo_Recaudo, Valor_num al dict del pedido."""
    dias_real = _dias_reales(p)
    sub       = p.get("sub_estado_logistico", "en_transito")
    es_cod    = bool(p.get("es_contraentrega"))

    r = calcular_riesgo(
        ciudad=p.get("ciudad_destino", ""),
        dias_en_transito=dias_real,
        incidencia_raw=p.get("incidencia", "NINGUNO"),
        es_contraentrega=es_cod,
    )

    es_entregado = (sub == "entregado")
    es_resuelto  = (sub == "resuelto")
    es_vencido   = (
        not es_resuelto and not es_entregado
        and dias_real > MAX_DIAS_ACTIVO
        and sub in ("en_transito", "novedad")
    )

    if es_entregado:
        nivel, score, motivo = "NORMAL", 100, "Pedido entregado · COD cobrado"
    elif es_resuelto:
        nivel, score, motivo = "RESUELTO", 100, "Novedad solucionada"
    elif es_vencido:
        nivel, score, motivo = "VENCIDO", 0, f"Sin confirmación · {dias_real}d en tránsito"
    else:
        nivel  = r.nivel
        score  = r.score
        motivo = r.motivos[0] if r.motivos else "—"

    enriched = {
        **p,
        "nivel":               nivel,
        "score":               score,
        "tipo_recaudo":        "Contraentrega" if es_cod else "Prepago",
        "dias_real":           dias_real,
        "sla_critico":         r.zona_info.sla_critico,
        "zona":                r.zona_info.zona,
        "motivo_riesgo":       motivo,
        "categoria_incidencia": r.incidencia_info.categoria,
        "requiere_contacto":   bool(getattr(r.incidencia_info, "requiere_contacto", False)),
        "valor_num":           _parse_cod(p.get("valor_cod_raw", "")),
    }
    enriched["es_novedad_visible"] = es_novedad_visible(enriched)
    return enriched


# ── Métricas globales ─────────────────────────────────────────────────────────

def calcular_metricas(pedidos: list[dict]) -> dict:
    """
    Recibe pedidos crudos (de svc.melonn.obtener_pedidos), retorna el dict
    de métricas globales + lista enriquecida con nivel.
    """
    if not pedidos:
        return {
            "n_total": 0, "n_pend": 0, "n_tran_cod": 0, "n_nov_cod": 0, "n_ent_cod": 0,
            "n_nov_pre": 0, "n_tran_pre": 0, "n_ent_pre": 0,
            "n_critico": 0, "n_riesgo": 0, "n_normal": 0,
            "val_cod": 0.0, "val_riesgo": 0.0, "val_ent": 0.0, "val_nov_cod": 0.0,
            "pedidos": [],
        }

    enriched = [clasificar(p) for p in pedidos]
    cods = [p for p in enriched if p["tipo_recaudo"] == "Contraentrega"]
    pres = [p for p in enriched if p["tipo_recaudo"] == "Prepago"]

    def _code(p): return int(p.get("estado_melonn_code") or 0)

    n_critico = sum(1 for p in enriched if p["nivel"] == "CRITICO")
    n_riesgo  = sum(1 for p in enriched if p["nivel"] == "RIESGO")

    return {
        "n_total":     len(enriched),
        "n_pend":      sum(1 for p in cods if _code(p) in (26, 29)),
        "n_tran_cod":  sum(1 for p in cods if _code(p) in (5, 7, 24, 28)),
        "n_nov_cod":   sum(1 for p in cods if p.get("es_novedad_visible")),
        "n_ent_cod":   sum(1 for p in cods if _code(p) in (6, 8)),
        "n_nov_pre":   sum(1 for p in pres if p.get("es_novedad_visible")),
        "n_tran_pre":  sum(1 for p in pres if p.get("sub_estado_logistico") == "en_transito"),
        "n_ent_pre":   sum(1 for p in pres if p.get("sub_estado_logistico") == "entregado"),
        "n_critico":   n_critico,
        "n_riesgo":    n_riesgo,
        "n_normal":    max(0, len(enriched) - n_critico - n_riesgo),
        "val_cod":     sum(p["valor_num"] for p in cods),
        "val_riesgo":  sum(p["valor_num"] for p in cods if p["nivel"] in ("CRITICO", "RIESGO")),
        "val_ent":     sum(p["valor_num"] for p in cods if _code(p) in (6, 8)),
        "val_nov_cod": sum(p["valor_num"] for p in cods if p.get("es_novedad_visible")),
        "pedidos":     enriched,
    }
