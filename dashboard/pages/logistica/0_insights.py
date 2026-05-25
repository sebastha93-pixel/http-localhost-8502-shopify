"""
Insights Logísticos — MALE'DENIM
Página principal del módulo de logística con KPIs y tendencias operativas.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
from datetime import date

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR,
    cargar_datos, render_sidebar, _parse_cod, bar_chart_zona_nivel, simple_bar,
)

st.set_page_config(
    page_title="MALE'DENIM · Logística",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

ruta_csv, ts, filtro_nivel, filtro_zona = render_sidebar("Insights Logísticos")

if not ruta_csv:
    st.info("📂 Sube el reporte CSV de Melonn en el sidebar para ver los insights.")
    st.stop()

try:
    with st.spinner("Procesando..."):
        df_all, omitidos = cargar_datos(ruta_csv, ts)
except Exception as e:
    st.error(f"Error al cargar: {e}")
    st.stop()

df_cod     = df_all[df_all["COD"] == "SÍ"]
df_prepago = df_all[df_all["COD"] == "—"]

# Filtrar
df_filt = df_all.copy()
if filtro_nivel: df_filt = df_filt[df_filt["Nivel"].isin(filtro_nivel)]
if filtro_zona:  df_filt = df_filt[df_filt["Zona"].isin(filtro_zona)]

# ── Encabezado ────────────────────────────────────────────────────────────────
st.markdown(f"""
    <p class="titulo-panel">📦 LOGÍSTICA</p>
    <p class="subtitulo">Insights operativos · {ts}</p>
    <hr style='margin:10px 0;'>
""", unsafe_allow_html=True)

total      = len(df_all)
criticos   = len(df_all[df_all["Nivel"] == "CRITICO"])
riesgo_n   = len(df_all[df_all["Nivel"] == "RIESGO"])
normales   = len(df_all[df_all["Nivel"] == "NORMAL"])
crit_cod   = len(df_cod[df_cod["Nivel"] == "CRITICO"])
crit_pre   = len(df_prepago[df_prepago["Nivel"] == "CRITICO"])
valor_cod_riesgo = df_cod[df_cod["Nivel"].isin(["CRITICO","RIESGO"])]["Valor COD"].apply(_parse_cod).sum()
pct_exc    = round((criticos + riesgo_n) / total * 100) if total else 0

# ── KPIs fila 1 ───────────────────────────────────────────────────────────────
st.markdown(f"<div class='sec-title'>Resumen operativo — {total} pedidos activos</div>", unsafe_allow_html=True)

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(f"""<div class="kpi-card kpi-crit">
        <p class="kpi-num">{criticos}</p><p class="kpi-label">Críticos totales</p>
        <p class="kpi-sub">{crit_cod} COD · {crit_pre} prepago</p></div>""", unsafe_allow_html=True)
with k2:
    st.markdown(f"""<div class="kpi-card kpi-ries">
        <p class="kpi-num">{riesgo_n}</p><p class="kpi-label">En riesgo</p>
        <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
with k3:
    st.markdown(f"""<div class="kpi-card kpi-norm">
        <p class="kpi-num">{normales}</p><p class="kpi-label">Normal</p>
        <p class="kpi-sub">Sin acción requerida</p></div>""", unsafe_allow_html=True)
with k4:
    color_pct = CRITICO_COLOR if pct_exc > 40 else (RIESGO_COLOR if pct_exc > 20 else NORMAL_COLOR)
    st.markdown(f"""<div class="kpi-card" style="background:{color_pct};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{pct_exc}%</p><p class="kpi-label">En excepción</p>
        <p class="kpi-sub">{criticos + riesgo_n} de {total} pedidos</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── KPIs fila 2 — COD vs Prepago ─────────────────────────────────────────────
st.markdown("<div class='sec-title'>COD vs Pago Previo</div>", unsafe_allow_html=True)

k5, k6, k7, k8 = st.columns(4)
with k5:
    st.markdown(f"""<div class="kpi-card kpi-extra">
        <p class="kpi-num">{len(df_cod)}</p><p class="kpi-label">Pedidos COD</p>
        <p class="kpi-sub">{round(len(df_cod)/total*100) if total else 0}% del total</p></div>""", unsafe_allow_html=True)
with k6:
    st.markdown(f"""<div class="kpi-card" style="background:{COD_COLOR};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num" style="font-size:1.3rem;">${valor_cod_riesgo:,.0f}</p>
        <p class="kpi-label">COD en riesgo</p>
        <p class="kpi-sub">Recaudo comprometido</p></div>""", unsafe_allow_html=True)
with k7:
    st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{len(df_prepago)}</p><p class="kpi-label">Pago previo</p>
        <p class="kpi-sub">{round(len(df_prepago)/total*100) if total else 0}% del total</p></div>""", unsafe_allow_html=True)
with k8:
    dias_prom = df_all["Días"].mean() if not df_all.empty else 0
    st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{dias_prom:.1f}</p><p class="kpi-label">Días promedio</p>
        <p class="kpi-sub">Tiempo en tránsito</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Gráficos ──────────────────────────────────────────────────────────────────
cg1, cg2 = st.columns(2)

with cg1:
    st.markdown("<div class='sec-title'>Distribución por zona</div>", unsafe_allow_html=True)
    if not df_filt.empty:
        bar_chart_zona_nivel(df_filt, height=220)
    else:
        st.info("Sin datos.")

with cg2:
    st.markdown("<div class='sec-title'>Distribución por transportadora</div>", unsafe_allow_html=True)
    if not df_filt.empty:
        transp = df_filt[df_filt["Nivel"].isin(["CRITICO","RIESGO"])]["Transportadora"].value_counts()
        if not transp.empty:
            simple_bar(transp, color=RIESGO_COLOR, height=220)
        else:
            st.success("Sin excepciones en transportadoras.")
    else:
        st.info("Sin datos.")

st.markdown("<br>", unsafe_allow_html=True)

# ── Top excepciones ───────────────────────────────────────────────────────────
st.markdown("<div class='sec-title'>Top excepciones activas</div>", unsafe_allow_html=True)

df_exc = df_filt[df_filt["Nivel"].isin(["CRITICO","RIESGO"])].copy()
if df_exc.empty:
    st.success("✅ Sin excepciones con los filtros actuales.")
else:
    COLS_TOP = ["Prioridad","Nivel","Score","Orden","Cliente","Ciudad","Zona",
                "Días","Días sobre SLA","COD","Valor COD","Transportadora","Novedad"]
    cols_disp = [c for c in COLS_TOP if c in df_exc.columns]
    st.dataframe(
        df_exc[cols_disp].head(20),
        use_container_width=True,
        height=320,
        hide_index=True,
        column_config={
            "Score": st.column_config.NumberColumn("Score", format="%d"),
            "Días":  st.column_config.NumberColumn("Días",  format="%d"),
            "Días sobre SLA": st.column_config.NumberColumn("Días s/SLA", format="%d"),
        },
    )
    st.caption(f"Top 20 de {len(df_exc)} excepciones · ordenadas por prioridad")

# ── Novedades más frecuentes ──────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("<div class='sec-title'>Novedades más frecuentes</div>", unsafe_allow_html=True)

if not df_all.empty:
    novedades = df_all[df_all["Novedad"] != "NINGUNO"]["Novedad"].value_counts().head(8)
    if not novedades.empty:
        simple_bar(novedades, color=CRITICO_COLOR, height=180)
    else:
        st.info("Sin novedades registradas.")
