"""
Panel de Contraentregas (COD) — MALE'DENIM
Pedidos con recaudo pendiente en campo.
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
    cargar_datos, color_nivel, render_sidebar, render_detalle, _parse_cod,
    bar_chart_zona_nivel, render_tabla, simple_bar,
)

st.markdown(CSS, unsafe_allow_html=True)

ruta_csv, ts, filtro_nivel, filtro_zona = render_sidebar("Contraentregas")

if not ruta_csv:
    st.info("📂 Sube el reporte CSV de Melonn en el sidebar para ver las contraentregas.")
    st.stop()

try:
    with st.spinner("Procesando pedidos..."):
        df_all, _ = cargar_datos(ruta_csv, ts)
except Exception as e:
    st.error(f"Error al cargar el archivo: {e}")
    st.stop()

df = df_all[df_all["COD"] == "SÍ"].copy()
if filtro_nivel: df = df[df["Nivel"].isin(filtro_nivel)]
if filtro_zona:  df = df[df["Zona"].isin(filtro_zona)]

# ── Encabezado ────────────────────────────────────────────────────────────────
st.markdown(f"""
    <p class="titulo-panel">💰 CONTRAENTREGAS</p>
    <p class="subtitulo">Recaudo pendiente · MALE'DENIM · {ts}</p>
    <hr style='margin:10px 0;'>
""", unsafe_allow_html=True)

# ── KPIs ──────────────────────────────────────────────────────────────────────
df_base_cod = df_all[df_all["COD"] == "SÍ"]
total_cod   = len(df_base_cod)
n_crit      = len(df[df["Nivel"] == "CRITICO"])
n_ries      = len(df[df["Nivel"] == "RIESGO"])
n_norm      = len(df[df["Nivel"] == "NORMAL"])
valor_riesgo = df[df["Nivel"].isin(["CRITICO","RIESGO"])]["Valor COD"].apply(_parse_cod).sum()
valor_total  = df_base_cod["Valor COD"].apply(_parse_cod).sum()

k1,k2,k3,k4,k5 = st.columns(5)
with k1:
    st.markdown(f"""<div class="kpi-card kpi-crit">
        <p class="kpi-num">{n_crit}</p><p class="kpi-label">Crítico</p>
        <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
with k2:
    st.markdown(f"""<div class="kpi-card kpi-ries">
        <p class="kpi-num">{n_ries}</p><p class="kpi-label">En riesgo</p>
        <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
with k3:
    st.markdown(f"""<div class="kpi-card kpi-norm">
        <p class="kpi-num">{n_norm}</p><p class="kpi-label">Normal</p>
        <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
with k4:
    st.markdown(f"""<div class="kpi-card kpi-extra">
        <p class="kpi-num" style="font-size:1.2rem;">${valor_riesgo:,.0f}</p>
        <p class="kpi-label">$ en riesgo</p>
        <p class="kpi-sub">Recaudo comprometido</p></div>""", unsafe_allow_html=True)
with k5:
    st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{total_cod}</p><p class="kpi-label">Total COD activo</p>
        <p class="kpi-sub">${valor_total:,.0f} portafolio</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Gráficos ──────────────────────────────────────────────────────────────────
cg1, cg2 = st.columns(2)
with cg1:
    st.markdown("<div class='sec-title'>Por zona — COD</div>", unsafe_allow_html=True)
    if not df.empty:
        bar_chart_zona_nivel(df, height=200)
    else:
        st.info("Sin datos.")

with cg2:
    st.markdown("<div class='sec-title'>Días en tránsito — excepciones</div>", unsafe_allow_html=True)
    df_exc = df[df["Nivel"].isin(["CRITICO","RIESGO"])]
    if not df_exc.empty:
        bins = pd.cut(df_exc["Días"], bins=[0,2,4,7,10,15,30],
                      labels=["1-2d","3-4d","5-7d","8-10d","11-15d","16d+"])
        simple_bar(bins.value_counts().sort_index(), color=CRITICO_COLOR, height=200)
    else:
        st.info("Sin excepciones.")

# ── Lista de trabajo ──────────────────────────────────────────────────────────
st.markdown(f"<div class='sec-title'>Lista de trabajo — {len(df)} pedidos COD</div>", unsafe_allow_html=True)
st.caption("Pedidos con recaudo pendiente. Críticos primero — mayor riesgo de pérdida de dinero.")

COLS = ["Prioridad","Nivel","Score","Orden","Cliente","Teléfono",
        "Ciudad","Zona","Días","Días sobre SLA","Valor COD",
        "Transportadora","Novedad","Motivo riesgo"]
COLS = [c for c in COLS if c in df.columns]

if df.empty:
    st.success("Sin pedidos COD con los filtros seleccionados.")
else:
    render_tabla(df, COLS, key="tabla_cod", height=440)

    st.download_button(
        "DESCARGAR LISTA COD (.CSV)",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"maledenim_COD_{date.today()}.csv",
        mime="text/csv",
    )

    render_detalle(df, tab_key="cod")
