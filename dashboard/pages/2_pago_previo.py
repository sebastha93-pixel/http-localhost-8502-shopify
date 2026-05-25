"""
Panel de Pago Previo — MALE'DENIM
Pedidos ya pagados. Enfoque en entrega a tiempo.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
from datetime import date

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR,
    cargar_datos, color_nivel, render_sidebar, render_detalle,
    bar_chart_zona_nivel,
)

st.set_page_config(
    page_title="MALE'DENIM · Pago Previo",
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
ruta_csv, ts, filtro_nivel, filtro_zona = render_sidebar("Pago Previo")

# ── Datos ─────────────────────────────────────────────────────────────────────
try:
    with st.spinner("Procesando pedidos..."):
        df_all, _ = cargar_datos(ruta_csv, ts)
except Exception as e:
    st.error(f"Error al cargar el archivo: {e}")
    st.stop()

# Solo prepago
df = df_all[df_all["COD"] == "—"].copy()

# Aplicar filtros
if filtro_nivel:
    df = df[df["Nivel"].isin(filtro_nivel)]
if filtro_zona:
    df = df[df["Zona"].isin(filtro_zona)]

# ── Encabezado ────────────────────────────────────────────────────────────────
col_h, col_ts = st.columns([3, 1])
with col_h:
    st.markdown(f"""
        <p class="titulo-panel">✅ PAGO PREVIO</p>
        <p class="subtitulo">Pedidos pagados · Enfoque en entrega a tiempo · MALE'DENIM</p>
    """, unsafe_allow_html=True)
with col_ts:
    st.markdown(f"""
        <div style="text-align:right;padding-top:4px;">
            <div style="font-size:0.68rem;color:{GRAPHITE_GREY};letter-spacing:1px;">
                {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')}
            </div>
            <div style="font-size:0.62rem;color:{STEEL_BLUE};">{ts}</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

# ── KPIs ──────────────────────────────────────────────────────────────────────
df_base_pre = df_all[df_all["COD"] == "—"]
total_pre   = len(df_base_pre)
n_crit      = len(df[df["Nivel"] == "CRITICO"])
n_ries      = len(df[df["Nivel"] == "RIESGO"])
n_norm      = len(df[df["Nivel"] == "NORMAL"])
n_prom_venc = len(df[df["Promesa vencida"] == "SÍ"])
n_en_riesgo = n_crit + n_ries

k1, k2, k3, k4, k5 = st.columns(5)
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
        <p class="kpi-sub">Cliente ya esperó demasiado</p></div>""", unsafe_allow_html=True)
with k5:
    pct = round(n_en_riesgo / total_pre * 100) if total_pre > 0 else 0
    st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{total_pre}</p><p class="kpi-label">Total prepago activo</p>
        <p class="kpi-sub">{pct}% en excepción</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Gráficos ──────────────────────────────────────────────────────────────────
cg1, cg2 = st.columns(2)

with cg1:
    st.markdown("<div class='sec-title'>Distribución por zona — Pago Previo</div>", unsafe_allow_html=True)
    if not df.empty:
        bar_chart_zona_nivel(df, height=200)
    else:
        st.info("Sin datos.")

with cg2:
    st.markdown("<div class='sec-title'>Transportadora — pedidos en excepción</div>", unsafe_allow_html=True)
    df_exc = df[df["Nivel"].isin(["CRITICO","RIESGO"])]
    if not df_exc.empty:
        transp_counts = df_exc["Transportadora"].value_counts()
        st.bar_chart(transp_counts, height=200, color=RIESGO_COLOR)
    else:
        st.info("Sin excepciones.")

# ── Lista de trabajo ──────────────────────────────────────────────────────────
st.markdown(f"<div class='sec-title'>Lista de trabajo — {len(df)} pedidos prepago</div>", unsafe_allow_html=True)
st.caption("Pedidos ya cobrados. El riesgo aquí es reputacional — cliente espera su pedido.")

COLS = ["Prioridad","Nivel","Score","Orden","Cliente","Teléfono",
        "Ciudad","Zona","Días","Días sobre SLA","Promesa vencida",
        "Transportadora","Novedad","Motivo riesgo"]

if df.empty:
    st.success("Sin pedidos prepago con los filtros seleccionados. ¡Todo en orden!")
else:
    st.dataframe(
        df[COLS].style
            .applymap(color_nivel, subset=["Nivel"])
            .format({"Score":"{:.0f}","Días":"{:.0f}","Días sobre SLA":"{:.0f}"}),
        use_container_width=True,
        height=440,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="tabla_prepago",
    )

    st.download_button(
        "DESCARGAR LISTA PAGO PREVIO (.CSV)",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"maledenim_prepago_{date.today()}.csv",
        mime="text/csv",
    )

    render_detalle(df, tab_key="prepago")
