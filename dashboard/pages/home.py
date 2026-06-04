"""
MALE'DENIM OS — Centro de Control
Vista gerencial: qué necesita atención hoy.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
from datetime import date

from design_system import CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, BORDER_DEFAULT, SURFACE_CARD
from design_system import COLOR_CRITICO, COLOR_RIESGO, COLOR_NORMAL, COLOR_PENDIENTE, COLOR_INFO
from design_system import BG_CRITICO, BG_RIESGO, BG_NORMAL, BG_PENDIENTE, BG_INFO
from components.ui import (
    page_header, section_header, kpi_card, alert_card, badge,
    card, empty_state, divider_label, progress_bar, sidebar_logo, sidebar_footer,
    table_header, table_row_html, table_wrap,
)

st.markdown(CSS, unsafe_allow_html=True)

# ── Guard de permisos ──────────────────────────────────────────────────────────
if "logistica" not in st.session_state.get("permisos", ["logistica"]):
    st.error("🔒 Sin acceso.")
    st.stop()

# ── Sidebar ────────────────────────────────────────────────────────────────────
from shared import render_sidebar
sidebar_logo()
render_sidebar("Centro de Control")

# ── Intentar cargar datos de logística ────────────────────────────────────────
_df_all = pd.DataFrame()
_meta   = {}
try:
    from shared import cargar_datos_api
    _df_all, _, _meta = cargar_datos_api()
except Exception:
    pass

_fuente = _meta.get("fuente", "")
_fa     = _meta.get("fetched_at")
_fa_txt = _fa.strftime("%d/%m %H:%M") if _fa else "—"

# Derivar métricas desde datos disponibles
if not _df_all.empty:
    from shared import _parse_cod
    df_cod = _df_all[_df_all["Tipo_Recaudo"] == "Contraentrega"]
    df_pre = _df_all[_df_all["Tipo_Recaudo"] == "Prepago"]

    n_pend    = len(df_cod[df_cod["Estado_Code"].isin([26, 29])])
    n_tran    = len(df_cod[df_cod["Estado_Code"].isin([5, 7, 24, 28])])
    n_nov_cod = len(df_cod[df_cod["Sub_Estado"] == "novedad"])
    n_nov_pre = len(df_pre[df_pre["Sub_Estado"] == "novedad"])
    n_critico = len(_df_all[_df_all["Nivel"] == "CRITICO"])
    n_riesgo  = len(_df_all[_df_all["Nivel"] == "RIESGO"])

    val_cod_total = df_cod["Valor COD"].apply(_parse_cod).sum()
    val_riesgo    = (df_cod[df_cod["Nivel"].isin(["CRITICO","RIESGO"])]["Valor COD"]
                    .apply(_parse_cod).sum())

    def _fmt(v):
        if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
        if v >= 1_000:     return f"${v/1_000:.0f}K"
        return f"${v:,.0f}"
else:
    n_pend = n_tran = n_nov_cod = n_nov_pre = n_critico = n_riesgo = 0
    val_cod_total = val_riesgo = 0
    def _fmt(v): return f"${v:,.0f}"

# ── Header ─────────────────────────────────────────────────────────────────────
_username = st.session_state.get("name") or st.session_state.get("username") or "Equipo"
page_header(
    f"Hola, {_username.split()[0]}",
    f"Estado general de MALE'DENIM OS · {date.today().strftime('%A %d de %B, %Y').capitalize()}",
)

# ── KPIs superiores ────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)

with k1:
    kpi_card(
        str(n_pend + n_tran + n_nov_cod),
        "Pedidos activos",
        "COD en operación",
        accent_color=STEEL_BLUE,
    )
with k2:
    kpi_card(
        str(n_critico),
        "Críticos",
        "Acción inmediata",
        accent_color=COLOR_CRITICO if n_critico > 0 else STEEL_BLUE,
    )
with k3:
    kpi_card(
        str(n_riesgo),
        "En riesgo",
        "Monitorear hoy",
        accent_color=COLOR_RIESGO if n_riesgo > 0 else STEEL_BLUE,
    )
with k4:
    kpi_card(
        _fmt(val_cod_total),
        "Portafolio COD",
        "Total activo",
        accent_color=COLOR_INFO,
    )
with k5:
    kpi_card(
        _fmt(val_riesgo),
        "COD en riesgo",
        "Recaudo comprometido",
        accent_color=COLOR_RIESGO if val_riesgo > 0 else STEEL_BLUE,
    )

st.markdown("<br>", unsafe_allow_html=True)

# ── Dos columnas: Alertas + Salud operativa ────────────────────────────────────
col_left, col_right = st.columns([1.1, 1], gap="large")

with col_left:
    section_header("Alertas prioritarias", "Lo que necesita atención ahora")

    if n_critico > 0:
        alert_card(
            f"{n_critico} pedido{'s' if n_critico>1 else ''} en estado CRÍTICO",
            f"Superaron el SLA. Valor en riesgo: {_fmt(val_riesgo)}",
            level="CRITICO",
            action_label="Ver en Logística",
        )
    if n_nov_cod > 0:
        alert_card(
            f"{n_nov_cod} novedad{'es' if n_nov_cod>1 else ''} activa{'s' if n_nov_cod>1 else ''}",
            "Transportadora no pudo entregar. Requieren gestión.",
            level="RIESGO",
            action_label="Gestionar",
        )
    if n_pend > 0:
        alert_card(
            f"{n_pend} pedido{'s' if n_pend>1 else ''} pendiente{'s' if n_pend>1 else ''} de despacho",
            "Esperan autorización del seller en Melonn.",
            level="PENDIENTE",
            action_label="Autorizar",
        )
    if n_nov_pre > 0:
        alert_card(
            f"{n_nov_pre} novedad en pedidos pagados",
            "Clientes que pagaron y no han recibido. Riesgo de chargeback.",
            level="INFO",
        )

    if n_critico == 0 and n_nov_cod == 0 and n_pend == 0 and n_nov_pre == 0:
        empty_state("✓", "Sin alertas activas", "Todo está operando con normalidad.")

with col_right:
    section_header("Salud de la operación", f"Actualizado: {_fa_txt}")

    # Semáforo por módulo
    items_salud = [
        ("Contraentrega pendiente",  str(n_pend),    "pendiente" if n_pend > 0 else "ok"),
        ("En tránsito COD",          str(n_tran),    "ok"),
        ("Novedades COD",            str(n_nov_cod), "critico" if n_nov_cod > 0 else "ok"),
        ("Pedidos pagos activos",    str(n_nov_pre + len(df_pre[df_pre["Sub_Estado"] == "en_transito"]) if not _df_all.empty else 0), "ok"),
    ]

    rows = ""
    for label, val, estado in items_salud:
        _c, _bg = {
            "ok":       (COLOR_NORMAL,    BG_NORMAL),
            "pendiente":(COLOR_PENDIENTE, BG_PENDIENTE),
            "critico":  (COLOR_CRITICO,   BG_CRITICO),
            "riesgo":   (COLOR_RIESGO,    BG_RIESGO),
        }.get(estado, (GRAPHITE_GREY, "#F4F4F2"))

        rows += f"""
        <div style="
            display:flex;justify-content:space-between;align-items:center;
            padding:11px 0;border-bottom:1px solid #F2F0ED;
        ">
            <span style="font-size:0.8rem;color:{DEEP_INK};font-weight:500;">{label}</span>
            <span style="
                background:{_bg};color:{_c};
                font-size:0.65rem;font-weight:700;letter-spacing:1px;
                padding:4px 10px;border-radius:20px;
            ">{val}</span>
        </div>"""

    st.markdown(f"""
    <div style="
        background:white;border:1px solid {BORDER_DEFAULT};
        border-radius:14px;padding:20px 22px;
    ">{rows}</div>
    """, unsafe_allow_html=True)


# ── Fila inferior ──────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)

col_a, col_b, col_c = st.columns(3, gap="large")

with col_a:
    section_header("Módulos del sistema")
    modulos = [
        ("📦", "Logística",      "Pedidos activos y novedades",   "/logistica"),
        ("💰", "Conciliación",   "Pendiente de implementar",       None),
        ("📊", "Comercial",      "Pendiente de implementar",       None),
        ("💳", "MercadoPago",    "Pendiente de implementar",       None),
    ]
    for icon, nombre, desc, link in modulos:
        _opacity = "1" if link else "0.5"
        st.markdown(f"""
        <div style="
            display:flex;align-items:center;gap:12px;
            padding:11px 14px;
            background:white;border:1px solid {BORDER_DEFAULT};border-radius:10px;
            margin-bottom:6px;opacity:{_opacity};
            cursor:{'pointer' if link else 'default'};
        ">
            <span style="font-size:1.1rem;">{icon}</span>
            <div style="flex:1;">
                <p style="font-size:0.78rem;font-weight:700;color:{DEEP_INK};margin:0;">{nombre}</p>
                <p style="font-size:0.68rem;color:{GRAPHITE_GREY};margin:0;">{desc}</p>
            </div>
            {'<span style="font-size:0.65rem;color:' + STEEL_BLUE + ';">→</span>' if link else ''}
        </div>
        """, unsafe_allow_html=True)

with col_b:
    section_header("Integraciones activas")
    integraciones = [
        ("Melonn API",    _fuente == "api_live", _fa_txt),
        ("Supabase",      True,                  "Conectado"),
        ("Shopify",       False,                 "Pendiente config"),
        ("MercadoPago",   False,                 "Pendiente config"),
        ("Wompi",         False,                 "Pendiente config"),
    ]
    for nombre, activo, estado_txt in integraciones:
        _dot_color = COLOR_NORMAL if activo else GRAPHITE_GREY
        st.markdown(f"""
        <div style="
            display:flex;align-items:center;justify-content:space-between;
            padding:10px 14px;background:white;
            border:1px solid {BORDER_DEFAULT};border-radius:10px;margin-bottom:6px;
        ">
            <div style="display:flex;align-items:center;gap:10px;">
                <div style="width:7px;height:7px;border-radius:50%;background:{_dot_color};
                            flex-shrink:0;margin-top:1px;"></div>
                <span style="font-size:0.78rem;font-weight:600;color:{DEEP_INK};">{nombre}</span>
            </div>
            <span style="font-size:0.65rem;color:{GRAPHITE_GREY};">{estado_txt}</span>
        </div>
        """, unsafe_allow_html=True)

with col_c:
    section_header("Distribución de pedidos COD")
    if not _df_all.empty and len(df_cod) > 0:
        _items = [
            ("Pendientes",  n_pend,    COLOR_PENDIENTE, val_cod_total),
            ("En tránsito", n_tran,    COLOR_INFO,      val_cod_total),
            ("Novedades",   n_nov_cod, COLOR_RIESGO,    val_cod_total),
        ]
        st.markdown(f"""
        <div style="background:white;border:1px solid {BORDER_DEFAULT};
                    border-radius:14px;padding:20px 22px;">
        """, unsafe_allow_html=True)
        for label, n, color, total in _items:
            pct = round(n / total * 100, 1) if total > 0 else 0
            pct_num = round(n / len(df_cod) * 100) if len(df_cod) > 0 else 0
            st.markdown(f"""
            <div style="margin-bottom:14px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
                    <span style="font-size:0.75rem;font-weight:600;color:{DEEP_INK};">{label}</span>
                    <span style="font-size:0.72rem;color:{GRAPHITE_GREY};">{n} · {pct_num}%</span>
                </div>
            """, unsafe_allow_html=True)
            progress_bar(n, len(df_cod), color=color, height=5)
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        empty_state("📦", "Sin datos de logística", "Presiona ↻ Actualizar datos")

# ── Recomendaciones inteligentes (placeholder) ─────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
section_header("Inteligencia operativa", "Conclusiones automáticas del sistema")

rec_cols = st.columns(3, gap="large")
recomendaciones = [
    (
        COLOR_RIESGO,
        "Novedades con transportadora",
        f"Hay {n_nov_cod} pedido{'s' if n_nov_cod!=1 else ''} con 'Delivery not posible'. "
        "La transportadora no pudo entregar. Contactar cliente para verificar dirección.",
        "Gestionar novedades →",
    ),
    (
        COLOR_INFO,
        "Pedidos pendientes de despacho",
        f"{n_pend} pedido{'s' if n_pend!=1 else ''} esperan autorización. "
        "Revisar y autorizar despacho en Melonn para no perder ventana de entrega.",
        "Autorizar en Melonn →",
    ),
    (
        COLOR_NORMAL,
        "Portafolio COD activo",
        f"{_fmt(val_cod_total)} en COD activo con {n_tran} pedidos en tránsito. "
        "Hacer seguimiento a los críticos para asegurar el recaudo.",
        "Ver en tránsito →",
    ),
]
for col, (color, titulo, texto, accion) in zip(rec_cols, recomendaciones):
    with col:
        st.markdown(f"""
        <div style="
            background:white;border:1px solid {BORDER_DEFAULT};
            border-radius:14px;padding:20px 22px;height:100%;
            border-top:3px solid {color};
        ">
            <p style="font-size:0.6rem;font-weight:700;letter-spacing:2px;
                      text-transform:uppercase;color:{color};margin:0 0 8px 0;">Recomendación</p>
            <p style="font-size:0.85rem;font-weight:700;color:{DEEP_INK};
                      margin:0 0 8px 0;">{titulo}</p>
            <p style="font-size:0.76rem;color:{GRAPHITE_GREY};line-height:1.5;margin:0 0 14px 0;">{texto}</p>
            <span style="font-size:0.68rem;font-weight:700;color:{color};letter-spacing:0.5px;">{accion}</span>
        </div>
        """, unsafe_allow_html=True)
