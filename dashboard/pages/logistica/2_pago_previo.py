"""
Panel de Pago Previo — MALE'DENIM
Pedidos ya pagados. Enfoque en entrega a tiempo.
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
    cargar_datos, color_nivel, render_sidebar, render_detalle,
    bar_chart_zona_nivel, render_tabla, simple_bar,
)

st.set_page_config(
    page_title="MALE'DENIM · Pago Previo",
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

ruta_csv, ts, filtro_nivel, filtro_zona = render_sidebar("Pago Previo")

if not ruta_csv:
    st.info("📂 Sube el reporte CSV de Melonn en el sidebar para ver los pedidos de pago previo.")
    st.stop()

try:
    with st.spinner("Procesando pedidos..."):
        df_all, _ = cargar_datos(ruta_csv, ts)
except Exception as e:
    st.error(f"Error al cargar el archivo: {e}")
    st.stop()

df = df_all[df_all["COD"] == "—"].copy()
if filtro_nivel: df = df[df["Nivel"].isin(filtro_nivel)]
if filtro_zona:  df = df[df["Zona"].isin(filtro_zona)]

# ── Encabezado ────────────────────────────────────────────────────────────────
st.markdown(f"""
    <p class="titulo-panel">✅ PAGO PREVIO</p>
    <p class="subtitulo">Pedidos pagados · Entrega a tiempo · MALE'DENIM · {ts}</p>
    <hr style='margin:10px 0;'>
""", unsafe_allow_html=True)

# ── KPIs ──────────────────────────────────────────────────────────────────────
df_base_pre = df_all[df_all["COD"] == "—"]
total_pre   = len(df_base_pre)
n_crit      = len(df[df["Nivel"] == "CRITICO"])
n_ries      = len(df[df["Nivel"] == "RIESGO"])
n_norm      = len(df[df["Nivel"] == "NORMAL"])
n_prom_venc = len(df[df["Promesa vencida"] == "SÍ"]) if "Promesa vencida" in df.columns else 0
n_en_riesgo = n_crit + n_ries

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
        <p class="kpi-num">{n_prom_venc}</p><p class="kpi-label">Promesa vencida</p>
        <p class="kpi-sub">Cliente esperó demasiado</p></div>""", unsafe_allow_html=True)
with k5:
    pct = round(n_en_riesgo / total_pre * 100) if total_pre > 0 else 0
    st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{total_pre}</p><p class="kpi-label">Total prepago</p>
        <p class="kpi-sub">{pct}% en excepción</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Gráficos ──────────────────────────────────────────────────────────────────
cg1, cg2 = st.columns(2)
with cg1:
    st.markdown("<div class='sec-title'>Por zona — Pago Previo</div>", unsafe_allow_html=True)
    if not df.empty:
        bar_chart_zona_nivel(df, height=200)
    else:
        st.info("Sin datos.")

with cg2:
    st.markdown("<div class='sec-title'>Transportadora — excepciones</div>", unsafe_allow_html=True)
    df_exc = df[df["Nivel"].isin(["CRITICO","RIESGO"])]
    if not df_exc.empty:
        transp_counts = df_exc["Transportadora"].value_counts()
        simple_bar(transp_counts, color=RIESGO_COLOR, height=200)
    else:
        st.info("Sin excepciones.")

# ── Lista de trabajo ──────────────────────────────────────────────────────────
st.markdown(f"<div class='sec-title'>Lista de trabajo — {len(df)} pedidos prepago</div>", unsafe_allow_html=True)
st.caption("Pedidos ya cobrados. El riesgo aquí es reputacional — el cliente espera su pedido.")

COLS = ["Prioridad","Nivel","Score","Orden","Cliente","Teléfono",
        "Ciudad","Zona","Días","Días sobre SLA","Promesa vencida",
        "Transportadora","Novedad","Motivo riesgo"]
COLS = [c for c in COLS if c in df.columns]

if df.empty:
    st.success("Sin pedidos prepago con los filtros seleccionados. ¡Todo en orden!")
else:
    render_tabla(df, COLS, key="tabla_prepago", height=440)

    st.download_button(
        "DESCARGAR LISTA PAGO PREVIO (.CSV)",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"maledenim_prepago_{date.today()}.csv",
        mime="text/csv",
    )

    render_detalle(df, tab_key="prepago")
