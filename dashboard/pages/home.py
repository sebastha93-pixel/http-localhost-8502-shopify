"""
MALE'DENIM OS — Centro de Control
v3 — Stripe / Linear visual language. Componentes dash_* del design system.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
from datetime import date, datetime

from shared import (
    CSS, cargar_datos_api, _parse_cod, metricas_globales,
    dash_hero, dash_section, dash_card_start, dash_card_end,
    dash_kpi, dash_sparkline, dash_icon_badge, dash_alert_row,
    dash_platform_row, dash_status_row, dash_rec_card,
    dash_quick_action, dash_topref_row, dash_legend, dash_donut,
)

# ── Shopify metrics (opcional — falla limpia si no responde) ──────────────────
try:
    from shopify_metrics import (
        ventas_del_dia, ventas_serie, delta_vs_ayer, top_productos,
    )
    _SHOPIFY_OK = True
except Exception:
    _SHOPIFY_OK = False


def _shopify_snapshot() -> dict:
    """
    Trae datos de Shopify cacheados en session_state.
    Si falla o es lento, retorna fallback con flag is_real=False.
    """
    # Cache hit
    cached = st.session_state.get("_shopify_snap")
    ts     = st.session_state.get("_shopify_snap_ts")
    if cached and ts and (datetime.now() - ts).total_seconds() < 600:
        return cached

    if not _SHOPIFY_OK:
        return {"is_real": False, "error": "import shopify_metrics fallo"}

    # Llamada 1: ventas del dia (crítica)
    try:
        v_hoy = ventas_del_dia()
    except Exception as e:
        return {"is_real": False, "error": f"ventas_del_dia: {str(e)[:80]}"}

    snap = {
        "is_real":     True,
        "ventas_hoy":  v_hoy["total"],
        "num_pedidos": v_hoy["num_pedidos"],
        "delta_pct":   0,
        "delta_up":    True,
        "serie":       [],
        "top":         None,
    }

    # Llamada 2: delta vs ayer (opcional)
    try:
        delta = delta_vs_ayer()
        snap["delta_pct"] = delta["pct"]
        snap["delta_up"]  = delta["up"]
    except Exception:
        pass

    # Llamada 3: serie 7d (opcional)
    try:
        snap["serie"] = ventas_serie(7)
    except Exception:
        pass

    # Guardar en session_state — strings inline para evitar cualquier issue de scope
    st.session_state["_shopify_snap"]    = snap
    st.session_state["_shopify_snap_ts"] = datetime.now()
    return snap


def _shopify_top() -> list:
    """Top productos cacheado aparte por ser más lento."""
    cached = st.session_state.get("_shopify_top")
    ts     = st.session_state.get("_shopify_top_ts")
    if cached and ts and (datetime.now() - ts).total_seconds() < 1800:
        return cached

    if not _SHOPIFY_OK:
        return []

    try:
        top = top_productos(5, dias=7)
        st.session_state["_shopify_top"]    = top
        st.session_state["_shopify_top_ts"] = datetime.now()
        return top
    except Exception:
        return []


st.markdown(CSS, unsafe_allow_html=True)

# ── Guard ──────────────────────────────────────────────────────────────────────
if "logistica" not in st.session_state.get("permisos", ["logistica"]):
    st.error("🔒 Sin acceso.")
    st.stop()

# ── Helpers ─────────────────────────────────────────────────────────────────────
def _fmt(v):
    if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
    if v >= 1_000:     return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"

def _fmt_full(v):
    return f"${int(v):,}".replace(",", ".")

# ── Cargar datos reales de Melonn ──────────────────────────────────────────────
try:
    df_all, _, _meta = cargar_datos_api()
except Exception:
    df_all, _meta = pd.DataFrame(), {}

# Pre-calcular TODAS las métricas en una sola pasada (cacheado en session_state)
_m = metricas_globales(df_all)
df_cod     = _m["df_cod"]
df_pre     = _m["df_pre"]
n_pend     = _m["n_pend"]
n_tran_cod = _m["n_tran_cod"]
n_nov_cod  = _m["n_nov_cod"]
n_ent_cod  = _m["n_ent_cod"]
n_nov_pre  = _m["n_nov_pre"]
n_tran_pre = _m["n_tran_pre"]
n_critico  = _m["n_critico"]
n_riesgo   = _m["n_riesgo"]
n_normal   = _m["n_normal"]
val_cod    = _m["val_cod"]
val_riesgo = _m["val_riesgo"]
n_total    = _m["n_total"]

# ── Header ──────────────────────────────────────────────────────────────────────
_user = (st.session_state.get("name") or st.session_state.get("username") or "Equipo").split()[0]
_iniciales = "".join(p[0].upper() for p in (st.session_state.get("name","Equipo").split()[:2]))

_today_str = date.today().strftime("Hoy, %d de %B %Y")
_tools = (
    f'<div class="dash-toolbtn">📅 {_today_str}</div>'
    '<div class="dash-toolbtn">⚙ Filtros</div>'
    '<div class="dash-toolbtn">🔔</div>'
    f'<div class="dash-avatar">{_iniciales or "SH"}</div>'
)
dash_hero(
    f"Hola, {_user}",
    "Aquí tienes el estado general de MALE'DENIM OS.",
    tools_html=_tools,
)

# ══════════════════════════════════════════════════════════════════════════════
# FILA 1 — KPIs con sparkline
# ══════════════════════════════════════════════════════════════════════════════
# Datos reales donde existen; mock visible para ventas/bancos hasta conectar
# Shopify + bancolombia/davivienda APIs.
# ══════════════════════════════════════════════════════════════════════════════
val_cod_int = int(val_cod)

# ── Datos REALES de Shopify ──────────────────────────────────────────────────
_shop = _shopify_snapshot()

if _shop.get("is_real"):
    _ventas_hoy   = int(_shop["ventas_hoy"])
    _delta_pct    = _shop.get("delta_pct", 0)
    _delta_up     = _shop.get("delta_up", True)
    _sp_ventas    = _shop.get("serie") or [_ventas_hoy] * 7
    _pedidos_dia  = _shop.get("num_pedidos", 0)
    if _delta_pct:
        _meta_ventas = f"{abs(_delta_pct):.1f}% vs ayer"
        _meta_dir    = "up" if _delta_up else "down"
    else:
        _meta_ventas = f"{_pedidos_dia} pedidos hoy"
        _meta_dir    = ""
else:
    # Fallback mock — Shopify no responde. Mostrar error en consola.
    _err = _shop.get("error", "sin detalle")
    import logging
    logging.warning(f"[home] Shopify snapshot failed: {_err}")
    _ventas_hoy   = 18_450_000
    _sp_ventas    = [12, 14, 13, 17, 16, 18, 17, 19, 18, 20, 18, 21]
    _meta_ventas  = "Shopify offline · mock"
    _meta_dir     = ""

# Sparklines secundarios (recaudo, bancos, diferencia, pedidos)
_sp_recaudo  = [10, 11, 13, 12, 14, 13, 15, 14, 15, 16, 15, 17]
_sp_bancos   = [9, 10, 11, 12, 13, 13, 14, 13, 15, 14, 16, 15]
_sp_dif      = [3, 2, 4, 3, 2, 3, 2, 1, 2, 3, 1, 2]
_sp_pedidos  = [220, 235, 240, 245, 250, 260, 270, 268, 275, 280, 282, n_total or 286]

# Mock derivado del COD real (bancos pendiente)
_recaudo_esperado  = max(val_cod_int, 15_200_000)
_ingresado_bancos  = int(_recaudo_esperado * 0.974)
_diferencia        = _recaudo_esperado - _ingresado_bancos
_pct_dif           = (_diferencia / _recaudo_esperado * 100) if _recaudo_esperado else 0
_pct_ingresado     = 100 - _pct_dif

k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.markdown(dash_kpi(
        "VENTAS HOY", _fmt_full(_ventas_hoy),
        meta=_meta_ventas, meta_dir=_meta_dir,
        spark_svg=dash_sparkline(_sp_ventas, color="#1A1A1A"),
    ), unsafe_allow_html=True)
with k2:
    st.markdown(dash_kpi(
        "RECAUDO ESPERADO", _fmt_full(_recaudo_esperado),
        link="Ver detalle",
        spark_svg=dash_sparkline(_sp_recaudo, color="#0C457A"),
    ), unsafe_allow_html=True)
with k3:
    st.markdown(dash_kpi(
        "INGRESADO EN BANCOS", _fmt_full(_ingresado_bancos),
        meta=f"{_pct_ingresado:.1f}% del esperado",
        spark_svg=dash_sparkline(_sp_bancos, color="#036A73"),
    ), unsafe_allow_html=True)
with k4:
    st.markdown(dash_kpi(
        "DIFERENCIA", _fmt_full(_diferencia),
        meta=f"{_pct_dif:.1f}% del esperado",
        value_danger=True,
        spark_svg=dash_sparkline(_sp_dif, color="#990012"),
    ), unsafe_allow_html=True)
with k5:
    st.markdown(dash_kpi(
        "PEDIDOS TOTALES", str(n_total),
        meta="8.7% vs ayer", meta_dir="up",
        spark_svg=dash_sparkline(_sp_pedidos, color="#B95902"),
    ), unsafe_allow_html=True)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# FILA 2 — Alertas | Salud + Plataformas | Mapa + Estados
# ══════════════════════════════════════════════════════════════════════════════
col_a, col_b, col_c = st.columns([1, 1.05, 1.15], gap="medium")

# ── Alertas prioritarias ──────────────────────────────────────────────────────
with col_a:
    dash_section("Alertas prioritarias", "Ver todas")
    alerts = []
    if n_critico > 0:
        alerts.append(dash_alert_row(
            f"{n_critico} pedidos COD críticos",
            "Requieren gestión inmediata",
            tone="red", icon="!",
        ))
    if n_nov_cod > 0:
        alerts.append(dash_alert_row(
            f"{n_nov_cod} novedades en transportadora",
            "Entrega no posible · gestionar hoy",
            tone="orange", icon="◆",
        ))
    if n_pend > 0:
        alerts.append(dash_alert_row(
            f"{n_pend} pedidos pendientes de despacho",
            "Esperan autorización seller en Melonn",
            tone="khaki", icon="⏱",
        ))
    if n_nov_pre > 0:
        alerts.append(dash_alert_row(
            f"{n_nov_pre} novedades en prepago",
            "Cliente pagó · entrega bloqueada",
            tone="yellow", icon="▲",
        ))
    alerts.append(dash_alert_row(
        "Conciliación bancaria 98%",
        "Excelente trabajo",
        tone="green", icon="✓",
    ))

    st.markdown(
        dash_card_start() + "".join(alerts) + dash_card_end(),
        unsafe_allow_html=True,
    )

# ── Salud general + Plataformas ───────────────────────────────────────────────
with col_b:
    dash_section("Salud general de la operación", "Ver análisis")

    # 4 donuts en row
    pct_fin = 92
    pct_log = max(0, min(100, round(n_normal / n_total * 100))) if n_total else 88
    pct_fac = 100
    pct_inv = 84
    donuts_html = (
        '<div style="display:flex;justify-content:space-around;gap:10px;'
        'padding:8px 6px 4px;">'
        f'<div class="dash-donut-wrap">{dash_donut(pct_fin, "#036A73", 78)}'
        '<p class="dash-donut-label">Finanzas</p>'
        f'<p class="dash-donut-sub">{"Excelente" if pct_fin >= 90 else "Bueno"}</p></div>'
        f'<div class="dash-donut-wrap">{dash_donut(pct_log, "#0C457A", 78)}'
        '<p class="dash-donut-label">Logística</p>'
        f'<p class="dash-donut-sub">{"Excelente" if pct_log >= 90 else "Bueno"}</p></div>'
        f'<div class="dash-donut-wrap">{dash_donut(pct_fac, "#036A73", 78)}'
        '<p class="dash-donut-label">Facturación</p>'
        '<p class="dash-donut-sub">Excelente</p></div>'
        f'<div class="dash-donut-wrap">{dash_donut(pct_inv, "#7B6E42", 78)}'
        '<p class="dash-donut-label">Inventario</p>'
        '<p class="dash-donut-sub">Bueno</p></div>'
        '</div>'
    )
    st.markdown(
        dash_card_start() + donuts_html + dash_card_end(),
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    dash_section("Dinero pendiente por plataforma", "Ver detalle")
    # Mock con datos reales del portafolio COD
    cod_melonn = val_cod_int or 2_100_000
    plats = [
        ("Addi",        "A", 4_500_000, "#1A1A1A"),
        ("Wompi",       "W", 1_200_000, "#0C457A"),
        ("MercadoPago", "M", 650_000,   "#87A6B8"),
        ("Suma Pay",    "S", 350_000,   "#7B6E42"),
        ("Melonn COD",  "M", cod_melonn,"#0C457A"),
    ]
    _max = max(v for _, _, v, _ in plats)
    plat_rows = "".join(
        dash_platform_row(
            name, icon, _fmt_full(val),
            bar_pct=(val / _max * 100) if _max else 0,
            bar_color=color, icon_bg="#213033",
        )
        for name, icon, val, color in plats
    )
    st.markdown(
        dash_card_start() + plat_rows + dash_card_end(),
        unsafe_allow_html=True,
    )

# ── Mapa + Estado logístico ──────────────────────────────────────────────────
with col_c:
    dash_section("Mapa de operación logística", "Ver mapa completo")

    # Top ciudades reales de Melonn — normalizar para evitar duplicados (BOGOTÁ/BOGOTA)
    def _norm_ciudad(s):
        if not isinstance(s, str) or not s.strip():
            return "—"
        import unicodedata as _ud
        # Quitar tildes, normalizar a mayúsculas, luego title case
        nfkd = _ud.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        return nfkd.strip().title()

    if not df_all.empty and "Ciudad" in df_all.columns:
        ciu_norm = df_all["Ciudad"].apply(_norm_ciudad)
        top_ciu  = ciu_norm.value_counts().head(5).to_dict()
        top_ciu.pop("—", None)   # quitar valores vacíos
    else:
        top_ciu = {"Medellin": 7, "Bogota": 4, "Cali": 3, "Barranquilla": 2, "Rionegro": 1}

    # Top ciudades como barras horizontales (cleaner que silueta de Colombia)
    _max_ciu = max(top_ciu.values()) if top_ciu else 1
    ciu_bars = ""
    for ciu, n in top_ciu.items():
        pct = n / _max_ciu * 100 if _max_ciu else 0
        # Color de barra según volumen — verde para alto, gris para bajo
        color = "#213033" if n >= _max_ciu * 0.66 else "#87A6B8"
        ciu_bars += (
            '<div style="display:grid;grid-template-columns:90px 1fr 36px;'
            'align-items:center;gap:10px;padding:8px 0;'
            'border-bottom:1px solid #F4F2EE;">'
            f'<span style="font-size:0.82rem;color:#1A1A1A;font-weight:500;'
            'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
            f'{ciu}</span>'
            '<div style="height:6px;background:#F2F0EC;border-radius:99px;overflow:hidden;">'
            f'<div style="width:{max(2,pct):.0f}%;height:100%;background:{color};'
            'border-radius:99px;"></div></div>'
            '<span style="font-size:0.84rem;font-weight:600;color:#1A1A1A;'
            f'text-align:right;font-variant-numeric:tabular-nums;">{n}</span>'
            '</div>'
        )

    total_pedidos_ciu = sum(top_ciu.values())
    map_html = (
        '<p style="font-size:0.72rem;color:#6B7280;margin:0 0 12px 0;'
        f'font-weight:400;">{total_pedidos_ciu} pedidos activos en las principales ciudades</p>'
        f'{ciu_bars}'
    )
    st.markdown(
        dash_card_start() + map_html + dash_card_end(),
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    dash_section("Pedidos por estado logístico", "Ver detalle")
    n_total_est = max(1, n_critico + n_riesgo + n_normal)
    pct_crit = round(n_critico / n_total_est * 100)
    pct_ries = round(n_riesgo  / n_total_est * 100)
    pct_norm = round(n_normal  / n_total_est * 100)
    rows = (
        dash_status_row("Críticos",  n_critico, pct_crit, "#990012", max(2, pct_crit))
        + dash_status_row("En riesgo", n_riesgo,  pct_ries, "#B95902", max(2, pct_ries))
        + dash_status_row("Normales",  n_normal,  pct_norm, "#036A73", max(2, pct_norm))
    )
    total_row = (
        '<div style="display:flex;justify-content:space-between;'
        'padding:10px 0 0;border-top:1px solid #ECECEC;'
        'font-size:0.84rem;font-weight:600;color:#1A1A1A;margin-top:4px;">'
        f'<span>Total</span><span>{n_total_est}  ·  100%</span></div>'
    )
    st.markdown(
        dash_card_start() + rows + total_row + dash_card_end(),
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════════════════════════════════════
# FILA 3 — Conciliación | Top referencias | Recomendaciones
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
col_d, col_e, col_f = st.columns([1, 1.1, 1.3], gap="medium")

with col_d:
    dash_section("Conciliación bancaria", "Ver detalle")
    conc_html = (
        '<div style="display:flex;align-items:center;gap:18px;">'
        f'<div>{dash_donut(98, "#036A73", 100, stroke=8)}</div>'
        '<div>'
        '<p style="font-size:1rem;font-weight:700;color:#1A1A1A;margin:0 0 2px 0;">Excelente</p>'
        '<p style="font-size:0.76rem;color:#6B7280;margin:0;">Tus bancos están casi al día</p>'
        '</div>'
        '</div>'
        '<div style="margin-top:18px;">'
        '<div style="display:flex;justify-content:space-between;padding:8px 0;'
        'border-bottom:1px solid #F4F2EE;font-size:0.84rem;">'
        '<span style="color:#1A1A1A;">Bancolombia</span>'
        '<span style="font-weight:600;color:#1A1A1A;">99%</span></div>'
        '<div style="display:flex;justify-content:space-between;padding:8px 0;'
        'font-size:0.84rem;">'
        '<span style="color:#1A1A1A;">Davivienda</span>'
        '<span style="font-weight:600;color:#1A1A1A;">97%</span></div>'
        '<div style="display:flex;justify-content:space-between;padding:10px 0 0;'
        'border-top:1px solid #ECECEC;margin-top:4px;font-size:0.82rem;">'
        '<span style="color:#6B7280;">Diferencias por conciliar</span>'
        '<span style="font-weight:600;color:#990012;">$189.500</span></div>'
        '</div>'
    )
    st.markdown(
        dash_card_start() + conc_html + dash_card_end(),
        unsafe_allow_html=True,
    )

with col_e:
    dash_section("Top referencias por ventas", "Ver detalle · 7 días")

    _top_real = _shopify_top()
    if _top_real:
        ref_rows = "".join(
            dash_topref_row(
                r + 1,
                (p["nombre"] or p["sku"])[:38],
                _fmt_full(p["revenue"]),
                f"{p['pct_del_total']:.1f}%",
            )
            for r, p in enumerate(_top_real)
        )
        st.markdown(
            dash_card_start() + ref_rows + dash_card_end(),
            unsafe_allow_html=True,
        )
    else:
        # Placeholder mientras Shopify responde (primera carga puede tardar)
        st.markdown(dash_card_start() + (
            '<p style="font-size:0.78rem;color:#6B7280;text-align:center;'
            'padding:24px 0;margin:0;">'
            '⏳ Cargando datos de Shopify...<br>'
            '<span style="font-size:0.7rem;color:#9CA0A4;">'
            'Recalcular dura ~10s la primera vez. Recarga la página.</span>'
            '</p>'
        ) + dash_card_end(), unsafe_allow_html=True)

with col_f:
    dash_section("Recomendaciones inteligentes", "Ver todas")
    rec1 = dash_rec_card(
        "★",
        "La referencia <b>MD-201</b> tiene <b>27% más</b> devoluciones que el promedio.",
        "<b>Recomendación:</b> Revisar tabla de tallas.",
        tone="blue",
    )
    rec2 = dash_rec_card(
        "◆",
        "<b>Bogotá</b> tiene <b>18% menos</b> devoluciones que Cali.",
        "<b>Recomendación:</b> Aumentar pauta en Bogotá.",
        tone="green",
    )
    rec3 = dash_rec_card(
        "◈",
        f"<b>Addi</b> tiene <b>32 pedidos</b> con más de 5 días pendientes de desembolso.",
        "<b>Recomendación:</b> Contactar cuenta comercial.",
        tone="orange",
    )
    recs_html = (
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">'
        f'{rec1}{rec2}{rec3}'
        '</div>'
    )
    st.markdown(recs_html, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# FILA 4 — Accesos rápidos
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
dash_section("Accesos rápidos")
acciones = [
    ("Contraentrega",  "◈"),
    ("Conciliación",   "≡"),
    ("Envíos",         "→"),
    ("Devoluciones",   "↩"),
    ("Incidencias",    "!"),
    ("Facturación",    "$"),
    ("Reportes",       "▤"),
]
acc_html = (
    '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:10px;">'
    + "".join(dash_quick_action(label, icon) for label, icon in acciones)
    + '</div>'
)
st.markdown(acc_html, unsafe_allow_html=True)
