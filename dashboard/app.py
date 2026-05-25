"""
Panel Principal — MALE'DENIM · Sistema de Inteligencia Logística
Página de inicio con resumen ejecutivo.
Ejecutar: streamlit run dashboard/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import streamlit as st
import pandas as pd
from datetime import date, datetime

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR,
    cargar_datos, color_nivel, render_sidebar, _parse_cod,
    bar_chart_zona_nivel,
)

# DB stats (puede fallar si el DB no está inicializado aún)
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from conciliacion import resumen_conciliacion as _res_concil
    _stats_concil = _res_concil()
except Exception:
    _stats_concil = None

st.set_page_config(
    page_title="MALE'DENIM · Panel Logístico",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
ruta_csv, ts, filtro_nivel, filtro_zona = render_sidebar("Resumen General")

# ── Datos ─────────────────────────────────────────────────────────────────────
try:
    with st.spinner("Procesando pedidos..."):
        df_all, omitidos = cargar_datos(ruta_csv, ts)
except Exception as e:
    st.error(f"Error al cargar el archivo: {e}")
    st.stop()

df_cod     = df_all[df_all["COD"] == "SÍ"]
df_prepago = df_all[df_all["COD"] == "—"]

# ── Encabezado ────────────────────────────────────────────────────────────────
col_h, col_ts = st.columns([3, 1])
with col_h:
    st.markdown(f"""
        <p class="titulo-panel">MALE'DENIM</p>
        <p class="subtitulo">Panel de Inteligencia Logística — Resumen General</p>
    """, unsafe_allow_html=True)
with col_ts:
    st.markdown(f"""
        <div style="text-align:right;padding-top:4px;">
            <div style="font-size:0.68rem;color:{GRAPHITE_GREY};letter-spacing:1px;">
                {datetime.now().strftime('%d/%m/%Y %H:%M')}
            </div>
            <div style="font-size:0.62rem;color:{STEEL_BLUE};">{ts}</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

# ── KPIs globales ─────────────────────────────────────────────────────────────
total        = len(df_all)
crit_total   = len(df_all[df_all["Nivel"] == "CRITICO"])
ries_total   = len(df_all[df_all["Nivel"] == "RIESGO"])
norm_total   = len(df_all[df_all["Nivel"] == "NORMAL"])

crit_cod     = len(df_cod[df_cod["Nivel"] == "CRITICO"])
crit_pre     = len(df_prepago[df_prepago["Nivel"] == "CRITICO"])
valor_riesgo = df_cod[df_cod["Nivel"].isin(["CRITICO","RIESGO"])]["Valor COD"].apply(_parse_cod).sum()

st.markdown(f"<div class='sec-title'>Visión global — {total} pedidos activos</div>", unsafe_allow_html=True)
k1,k2,k3,k4 = st.columns(4)
with k1:
    st.markdown(f"""<div class="kpi-card kpi-crit">
        <p class="kpi-num">{crit_total}</p><p class="kpi-label">Crítico total</p>
        <p class="kpi-sub">{crit_cod} COD · {crit_pre} prepago</p></div>""", unsafe_allow_html=True)
with k2:
    st.markdown(f"""<div class="kpi-card kpi-ries">
        <p class="kpi-num">{ries_total}</p><p class="kpi-label">En riesgo</p>
        <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
with k3:
    st.markdown(f"""<div class="kpi-card kpi-norm">
        <p class="kpi-num">{norm_total}</p><p class="kpi-label">Normal</p>
        <p class="kpi-sub">Sin acción requerida</p></div>""", unsafe_allow_html=True)
with k4:
    st.markdown(f"""<div class="kpi-card kpi-extra">
        <p class="kpi-num" style="font-size:1.3rem;">${valor_riesgo:,.0f}</p>
        <p class="kpi-label">COD en riesgo ($)</p>
        <p class="kpi-sub">Recaudo comprometido</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Tarjetas de acceso a paneles ──────────────────────────────────────────────
st.markdown(f"<div class='sec-title'>Paneles operativos</div>", unsafe_allow_html=True)

pc1, pc2 = st.columns(2)

with pc1:
    exc_cod = len(df_cod[df_cod["Nivel"].isin(["CRITICO","RIESGO"])])
    st.markdown(f"""
    <a href="/contraentregas" target="_self" style="text-decoration:none;">
    <div style="background:{COD_COLOR};border-radius:4px;padding:24px 28px;cursor:pointer;
                border-left:5px solid {STEEL_BLUE};transition:opacity 0.2s;">
        <div style="font-size:0.68rem;letter-spacing:3px;color:rgba(255,255,255,0.6);
                    text-transform:uppercase;margin-bottom:8px;">Panel Operativo</div>
        <div style="font-size:1.6rem;font-weight:900;color:white;
                    font-family:'Arial Black',sans-serif;">💰 Contraentregas</div>
        <div style="font-size:0.85rem;color:rgba(255,255,255,0.7);margin-top:4px;">
            Recaudo pendiente · {len(df_cod)} pedidos activos
        </div>
        <div style="margin-top:16px;display:flex;gap:16px;">
            <div style="background:rgba(255,255,255,0.15);border-radius:3px;padding:8px 14px;text-align:center;">
                <div style="font-size:1.4rem;font-weight:900;color:white;">{crit_cod}</div>
                <div style="font-size:0.6rem;color:rgba(255,255,255,0.7);letter-spacing:1px;text-transform:uppercase;">Críticos</div>
            </div>
            <div style="background:rgba(255,255,255,0.15);border-radius:3px;padding:8px 14px;text-align:center;">
                <div style="font-size:1.1rem;font-weight:900;color:white;">${valor_riesgo:,.0f}</div>
                <div style="font-size:0.6rem;color:rgba(255,255,255,0.7);letter-spacing:1px;text-transform:uppercase;">En riesgo</div>
            </div>
        </div>
    </div>
    </a>
    """, unsafe_allow_html=True)

with pc2:
    exc_pre = len(df_prepago[df_prepago["Nivel"].isin(["CRITICO","RIESGO"])])
    st.markdown(f"""
    <a href="/pago_previo" target="_self" style="text-decoration:none;">
    <div style="background:{DEEP_INK};border-radius:4px;padding:24px 28px;cursor:pointer;
                border-left:5px solid {STEEL_BLUE};transition:opacity 0.2s;">
        <div style="font-size:0.68rem;letter-spacing:3px;color:rgba(255,255,255,0.6);
                    text-transform:uppercase;margin-bottom:8px;">Panel Operativo</div>
        <div style="font-size:1.6rem;font-weight:900;color:white;
                    font-family:'Arial Black',sans-serif;">✅ Pago Previo</div>
        <div style="font-size:0.85rem;color:rgba(255,255,255,0.7);margin-top:4px;">
            Entrega a tiempo · {len(df_prepago)} pedidos activos
        </div>
        <div style="margin-top:16px;display:flex;gap:16px;">
            <div style="background:rgba(255,255,255,0.15);border-radius:3px;padding:8px 14px;text-align:center;">
                <div style="font-size:1.4rem;font-weight:900;color:white;">{crit_pre}</div>
                <div style="font-size:0.6rem;color:rgba(255,255,255,0.7);letter-spacing:1px;text-transform:uppercase;">Críticos</div>
            </div>
            <div style="background:rgba(255,255,255,0.15);border-radius:3px;padding:8px 14px;text-align:center;">
                <div style="font-size:1.4rem;font-weight:900;color:white;">{exc_pre}</div>
                <div style="font-size:0.6rem;color:rgba(255,255,255,0.7);letter-spacing:1px;text-transform:uppercase;">Excepciones</div>
            </div>
        </div>
    </div>
    </a>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Tarjeta de Conciliación ───────────────────────────────────────────────────
if _stats_concil:
    pct_c = _stats_concil.get("pct_conciliado", 0)
    dif_c = _stats_concil.get("con_diferencia", 0)
    cod_c = _stats_concil.get("cod_recaudo_pendiente", 0)
    color_concil = "#2d6a4f" if pct_c >= 90 else ("#b95902" if pct_c >= 60 else "#990012")
    st.markdown(f"""
    <a href="/conciliacion" target="_self" style="text-decoration:none;">
    <div style="background:{color_concil};border-radius:4px;padding:20px 28px;cursor:pointer;
                border-left:5px solid {STEEL_BLUE};">
        <div style="font-size:0.68rem;letter-spacing:3px;color:rgba(255,255,255,0.6);
                    text-transform:uppercase;margin-bottom:6px;">Módulo Financiero</div>
        <div style="display:flex;align-items:center;gap:20px;">
            <div style="font-size:1.4rem;font-weight:900;color:white;
                        font-family:'Arial Black',sans-serif;">💼 Conciliación</div>
            <div style="display:flex;gap:12px;margin-left:auto;">
                <div style="background:rgba(255,255,255,0.15);border-radius:3px;padding:6px 12px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:900;color:white;">{pct_c:.0f}%</div>
                    <div style="font-size:0.6rem;color:rgba(255,255,255,0.7);letter-spacing:1px;text-transform:uppercase;">Conciliado</div>
                </div>
                <div style="background:rgba(255,255,255,0.15);border-radius:3px;padding:6px 12px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:900;color:white;">{dif_c}</div>
                    <div style="font-size:0.6rem;color:rgba(255,255,255,0.7);letter-spacing:1px;text-transform:uppercase;">Diferencias</div>
                </div>
                <div style="background:rgba(255,255,255,0.15);border-radius:3px;padding:6px 12px;text-align:center;">
                    <div style="font-size:1.2rem;font-weight:900;color:white;">{cod_c}</div>
                    <div style="font-size:0.6rem;color:rgba(255,255,255,0.7);letter-spacing:1px;text-transform:uppercase;">COD pendiente</div>
                </div>
            </div>
        </div>
    </div>
    </a>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Gráfico resumen global ────────────────────────────────────────────────────
st.markdown(f"<div class='sec-title'>Resumen por zona — todos los pedidos</div>", unsafe_allow_html=True)

df_filt = df_all.copy()
if filtro_nivel: df_filt = df_filt[df_filt["Nivel"].isin(filtro_nivel)]
if filtro_zona:  df_filt = df_filt[df_filt["Zona"].isin(filtro_zona)]

if not df_filt.empty:
    bar_chart_zona_nivel(df_filt, height=220)
else:
    st.info("Sin datos con los filtros actuales.")

# ── Nota de navegación ────────────────────────────────────────────────────────
st.markdown(f"""
<div style="margin-top:20px;padding:14px 18px;background:white;border-radius:4px;
            border-left:3px solid {STEEL_BLUE};">
    <span style="font-size:0.72rem;color:{GRAPHITE_GREY};letter-spacing:1px;">
        NAVEGACIÓN · Usa el menú lateral izquierdo para ir a cada panel operativo,
        o haz clic directamente en las tarjetas de arriba.
    </span>
</div>
""", unsafe_allow_html=True)
