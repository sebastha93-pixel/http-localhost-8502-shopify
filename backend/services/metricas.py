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

    # NOTA: los "fulfillment on hold" (code 26 seller, 29 ext/int conditionals)
    # NO van a novedades — son holds que esperan autorización y deben quedar
    # en el tab "Pendientes despacho" (botón Autorizar). Por eso NO se listan aquí.

    # Errores genéricos
    "Error - not able to process",
    "Error - no es posible procesar",

    # Órdenes inválidas
    "Invalid order",
    "Orden inválida",
    "Orden invalida",
    "Fixed-valid - to be processed",  # a veces marca problema de validación
}

# Keywords que SIEMPRE marcan novedad, sin importar el sub_estado.
# Cubre variantes de texto de Melonn (sin stock, inválida, error, etc.)
NOVEDAD_KEYWORDS = [
    "no stock", "sin stock", "sin inventario",
    "invalid", "inválid", "invalida",
    "not able to fulfil", "no es posible procesar",
    "delivery not posible", "entrega no posible",
    "expired promise", "promesa vencida",
    "sm restriction", "restricción método",
]


def es_novedad_visible(p: dict) -> bool:
    """
    True si el pedido aparece en Novedades/Incidencias del dashboard.

    REGLA DURA primero: si el pedido ya fue entregado, NUNCA aparece en
    novedades — aunque tenga novedad_manual=True heredado de cuando
    estaba en tránsito. La entrega resuelve cualquier incidencia.

    Después, criterios para marcar como novedad:
    1. Override manual del operador
    2. Estado Melonn explícito en NOVEDADES_VISIBLES
    3. Heurístico SLA: pedido en tránsito que excede SLA crítico
    4. Heurístico VENCIDO: > 20 días sin confirmación
    """
    sub = p.get("sub_estado_logistico")
    code = int(p.get("estado_melonn_code") or 0)

    # 0) ENTREGADO → JAMÁS es novedad. Esta regla gana sobre todo lo demás.
    if sub == "entregado" or code in (6, 8):
        return False

    # 1) Override manual
    if p.get("novedad_manual"):
        return True

    estado = (p.get("estado_melonn") or "").strip()
    estado_low = estado.lower()

    # 2a) Novedad por estado Melonn (match exacto en whitelist)
    if estado in NOVEDADES_VISIBLES:
        return True

    # 2b) Novedad por keyword (sin stock, inválida, error, etc.) —
    #     independiente del sub_estado, para no perder casos
    if any(kw in estado_low for kw in NOVEDAD_KEYWORDS):
        return True

    # 2c) sub_estado novedad explícito
    if sub == "novedad" and estado in NOVEDADES_VISIBLES:
        return True

    # 3) Heurística: días reales > SLA crítico de la zona (aplica a COD + PRE)
    if sub == "en_transito":
        dias = int(p.get("dias_real") or 0)
        sla  = int(p.get("sla_critico") or 0)
        if sla > 0 and dias > sla:
            return True
        # 4) VENCIDO genérico
        if p.get("nivel") == "VENCIDO":
            return True

    return False


# ── Helpers internos ─────────────────────────────────────────────────────────

# Estados en los que el pedido AÚN NO SALIÓ de bodega. No puede llevar días en
# tránsito: contarlos ponía en RIESGO pedidos que nadie ha despachado (medido el
# 2026-07-30: el 58639 mostraba 56 días "en tránsito" sin haber salido nunca).
_SIN_DESPACHAR = ("pendiente_despacho", "pendiente", "por_despachar", "cancelado",
                  # En la bodega de Melonn (empacando / listo). No ha salido, así
                  # que no tiene días de tránsito. Ver CODIGOS_EN_PREPARACION.
                  "en_preparacion")


def _dias_estimados(p: dict) -> int:
    """Días cuando NO tenemos fecha de despacho, estimados desde la creación.

    POR QUÉ NO SE USA `dias_en_transito` DE MELONN: vale **0 siempre**. Medido el
    2026-07-31 sobre los 572 pedidos despachados sin fecha propia: los 572 traían
    0. O sea que la app mostraba "0 días" para el 53% de la flota — 56 en
    tránsito, 35 novedades y 481 entregados — y como el riesgo se calcula con ese
    número, NINGUNO de esos podía salir como VENCIDO. El sistema de alertas
    estaba ciego para más de la mitad de los pedidos.

    La creación del pedido es una cota INFERIOR del despacho (se despacha
    después de crearse), así que contar desde ahí SOBRE-estima los días de
    tránsito. Para vigilar riesgo eso es lo correcto: preferimos revisar un
    pedido de más que dejar pasar uno vencido en silencio.

    Devuelve 0 solo si de verdad no hay de dónde estimar. El llamador marca
    estos casos como estimados (ver clasificar → dias_estimados) para que la
    pantalla pueda mostrarlos con "≈" y nadie los confunda con un dato exacto.
    """
    fc = p.get("fecha_creacion")
    if not fc:
        return 0
    try:
        creado = date.fromisoformat(str(fc)[:10])
    except Exception:
        return 0
    if creado > date.today():
        return 0
    return max(0, (date.today() - creado).days)


def _dias_reales(p: dict) -> int:
    """
    Días que el pedido ha estado / estuvo en tránsito.

    - Si todavía no se despacha: 0 (no hay tránsito que medir)
    - Si está entregado y existe fecha_entrega: fecha_entrega - fecha_despacho
      (mide el tiempo REAL que tomó la entrega, no días después de entregado)
    - Si está activo: hoy - fecha_despacho
    - Sin fecha de despacho: se ESTIMA desde la creación del pedido. Ver abajo.
    """
    sub = p.get("sub_estado_logistico", "")
    if sub in _SIN_DESPACHAR:
        return 0

    # PRIMERO lo que VIMOS pasar. `fecha_despacho_observada` la anota el sync
    # cuando ve el pedido cambiar de "no despachado" a "despachado", así que es
    # un hecho presenciado y no un campo reportado. Melonn manda fechas
    # imposibles de vez en cuando; lo nuestro no.
    fd = p.get("fecha_despacho_observada") or p.get("fecha_despacho")
    if not fd:
        return _dias_estimados(p)

    try:
        fd_date = date.fromisoformat(str(fd)[:10])
    except Exception:
        return _dias_estimados(p)

    # Fecha de despacho imposible: anterior a la creación del pedido, o futura.
    # Melonn manda basura en `ship_timestamp` de vez en cuando y el valor se
    # HEREDA entre sincronizaciones, así que un dato malo se queda pegado para
    # siempre. Caso real: el 61360 se creó el 30-jul y traía despacho del
    # 12-jun → 48 días de tránsito inventados. Ante la duda, no se inventa: se
    # cae al contador de Melonn.
    try:
        fc = p.get("fecha_creacion")
        if fc and fd_date < date.fromisoformat(str(fc)[:10]):
            return int(p.get("dias_en_transito") or 0)
    except Exception:
        pass
    if fd_date > date.today():
        return int(p.get("dias_en_transito") or 0)

    # Si está entregado y hay fecha de entrega → usar tiempo real
    fe = p.get("fecha_entrega")
    if sub == "entregado" and fe:
        try:
            return max(0, (date.fromisoformat(str(fe)[:10]) - fd_date).days)
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

    # ¿Los días salen de una fecha de despacho real, o son una estimación desde
    # la creación? La pantalla debe poder distinguirlo (mostrar "≈ 5 d" en vez
    # de "5 d") para que nadie tome una estimación como un hecho.
    tiene_fecha = bool(p.get("fecha_despacho_observada") or p.get("fecha_despacho"))
    estimados = (not tiene_fecha) and sub not in _SIN_DESPACHAR and dias_real > 0

    # PROCEDENCIA DE LOS DÍAS. Un número sin procedencia no se puede auditar,
    # solo creer. Cuatro valores posibles y ninguno miente por omisión:
    #   medido        → hay fecha de despacho; los días se calcularon con ella
    #   estimado      → NO hay fecha; se contó desde la creación del pedido
    #   sin_despachar → no salió de bodega, no hay tránsito que medir
    #   sin_dato      → despachado y no hay ni fecha ni creación de dónde estimar
    if sub in _SIN_DESPACHAR:
        dias_origen = "sin_despachar"
    elif tiene_fecha:
        dias_origen = "medido"
    elif dias_real > 0:
        dias_origen = "estimado"
    else:
        dias_origen = "sin_dato"

    enriched = {
        **p,
        "nivel":               nivel,
        "score":               score,
        "tipo_recaudo":        "Contraentrega" if es_cod else "Prepago",
        "dias_real":           dias_real,
        "dias_estimados":      estimados,
        "dias_origen":         dias_origen,
        # De dónde salió la fecha de despacho, para el reporte de auditoría.
        "fecha_despacho_origen": (
            p.get("fecha_despacho_origen")
            or ("desconocido" if tiene_fecha else "")
        ),
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
