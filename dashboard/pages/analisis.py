"""
Análisis Logístico — MALE'DENIM
Página independiente de visualizaciones y métricas avanzadas.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR,
    cargar_datos, render_sidebar, _parse_cod,
)

st.markdown(CSS, unsafe_allow_html=True)

# ── Paleta y helpers ───────────────────────────────────────────────────────────
COLOR_NIVEL = {"CRITICO": CRITICO_COLOR, "RIESGO": RIESGO_COLOR, "NORMAL": NORMAL_COLOR}
FONT = dict(family="Arial, sans-serif", size=12, color=GRAPHITE_GREY)

def _layout(fig, height=300, margin=None):
    m = margin or dict(l=10, r=10, t=30, b=10)
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        margin=m, font=FONT, height=height,
        xaxis=dict(gridcolor="#f0f0f0", tickfont=dict(color=GRAPHITE_GREY)),
        yaxis=dict(gridcolor="#f0f0f0", tickfont=dict(color=GRAPHITE_GREY)),
    )
    return fig

# ── Sidebar ────────────────────────────────────────────────────────────────────
ruta_csv, ts, filtro_nivel, filtro_zona = render_sidebar("Análisis")

if not ruta_csv:
    st.markdown(f"""
        <p class="titulo-panel">📈 ANÁLISIS</p>
        <p class="subtitulo">Visualizaciones logísticas · MALE'DENIM</p>
        <hr style='margin:10px 0 24px;'>
    """, unsafe_allow_html=True)
    st.info("📂 Sube el reporte CSV de Melonn en el sidebar para ver el análisis.")
    st.stop()

try:
    with st.spinner("Procesando datos..."):
        df_all, _ = cargar_datos(ruta_csv, ts)
except Exception as e:
    st.error(f"Error al cargar: {e}")
    st.stop()

df = df_all.copy()
if filtro_nivel: df = df[df["Nivel"].isin(filtro_nivel)]
if filtro_zona:  df = df[df["Zona"].isin(filtro_zona)]

total = len(df_all)

# ── Encabezado ─────────────────────────────────────────────────────────────────
st.markdown(f"""
    <p class="titulo-panel">📈 ANÁLISIS</p>
    <p class="subtitulo">Visualizaciones logísticas · MALE'DENIM · {ts}</p>
    <hr style='margin:10px 0 18px;'>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 1 — RESUMEN DE RIESGO
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🎯 Resumen de riesgo", expanded=True):
    col1, col2, col3 = st.columns([1.2, 1, 1])

    # ── Donut de nivel ──
    with col1:
        st.markdown("<div class='sec-title'>Distribución por nivel</div>", unsafe_allow_html=True)
        nivel_counts = df_all["Nivel"].value_counts().reindex(["CRITICO","RIESGO","NORMAL"]).fillna(0)
        fig_donut = go.Figure(go.Pie(
            labels=nivel_counts.index,
            values=nivel_counts.values,
            hole=0.55,
            marker_colors=[CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR],
            textfont=dict(color="white", size=12),
            hovertemplate="%{label}: %{value} pedidos (%{percent})<extra></extra>",
        ))
        fig_donut.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=0, r=0, t=10, b=0), height=240,
            showlegend=True,
            legend=dict(orientation="h", y=-0.05, font=dict(color=GRAPHITE_GREY, size=11)),
            annotations=[dict(text=f"<b>{total}</b><br><span style='font-size:10px'>pedidos</span>",
                              x=0.5, y=0.5, font_size=16, font_color=DEEP_INK,
                              showarrow=False)],
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    # ── COD vs Prepago ──
    with col2:
        st.markdown("<div class='sec-title'>COD vs Pago previo</div>", unsafe_allow_html=True)
        tipo_counts = df_all["COD"].map({"SÍ": "COD", "—": "Pago previo"}).value_counts()
        fig_tipo = go.Figure(go.Pie(
            labels=tipo_counts.index,
            values=tipo_counts.values,
            hole=0.55,
            marker_colors=[COD_COLOR, STEEL_BLUE],
            textfont=dict(color="white", size=12),
            hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
        ))
        fig_tipo.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=0, r=0, t=10, b=0), height=240,
            showlegend=True,
            legend=dict(orientation="h", y=-0.05, font=dict(color=GRAPHITE_GREY, size=11)),
        )
        st.plotly_chart(fig_tipo, use_container_width=True)

    # ── SLA cumplimiento ──
    with col3:
        st.markdown("<div class='sec-title'>Cumplimiento SLA</div>", unsafe_allow_html=True)
        dentro  = len(df_all[df_all["Días sobre SLA"] <= 0])
        fuera   = len(df_all[df_all["Días sobre SLA"] > 0])
        fig_sla = go.Figure(go.Pie(
            labels=["Dentro de SLA", "Fuera de SLA"],
            values=[dentro, fuera],
            hole=0.55,
            marker_colors=[NORMAL_COLOR, CRITICO_COLOR],
            textfont=dict(color="white", size=12),
            hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
        ))
        fig_sla.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=0, r=0, t=10, b=0), height=240,
            showlegend=True,
            legend=dict(orientation="h", y=-0.05, font=dict(color=GRAPHITE_GREY, size=11)),
        )
        st.plotly_chart(fig_sla, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 2 — ANÁLISIS POR ZONA
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🗺️ Análisis por zona", expanded=True):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("<div class='sec-title'>Pedidos por zona y nivel</div>", unsafe_allow_html=True)
        zona_nivel = (df_all.groupby(["Zona","Nivel"])
                      .size().reset_index(name="Pedidos"))
        zona_nivel["Nivel"] = pd.Categorical(zona_nivel["Nivel"],
                                             ["CRITICO","RIESGO","NORMAL"], ordered=True)
        zona_nivel = zona_nivel.sort_values(["Zona","Nivel"])
        fig_zona = px.bar(
            zona_nivel, y="Zona", x="Pedidos", color="Nivel",
            color_discrete_map=COLOR_NIVEL, orientation="h",
            barmode="stack", height=280,
        )
        fig_zona = _layout(fig_zona, height=280)
        fig_zona.update_layout(legend=dict(orientation="h", y=1.08,
                               font=dict(color=GRAPHITE_GREY)))
        st.plotly_chart(fig_zona, use_container_width=True)

    with col2:
        st.markdown("<div class='sec-title'>Días promedio por zona</div>", unsafe_allow_html=True)
        dias_zona = (df_all.groupby("Zona")["Días"]
                     .mean().sort_values(ascending=True).reset_index())
        dias_zona.columns = ["Zona", "Días promedio"]
        dias_zona["color"] = dias_zona["Días promedio"].apply(
            lambda d: CRITICO_COLOR if d > 10 else (RIESGO_COLOR if d > 6 else NORMAL_COLOR))
        fig_dias = px.bar(
            dias_zona, y="Zona", x="Días promedio",
            color="color", color_discrete_map="identity",
            orientation="h", height=280,
            text=dias_zona["Días promedio"].round(1).astype(str) + "d",
        )
        fig_dias.update_traces(textposition="outside",
                               textfont=dict(color=GRAPHITE_GREY, size=11))
        fig_dias = _layout(fig_dias, height=280)
        fig_dias.update_layout(showlegend=False)
        st.plotly_chart(fig_dias, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 3 — TRANSPORTADORAS
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🚚 Análisis por transportadora", expanded=True):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("<div class='sec-title'>Volumen total por transportadora</div>", unsafe_allow_html=True)
        transp_vol = (df_all.groupby("Transportadora")
                      .size().sort_values(ascending=True)
                      .reset_index(name="Pedidos"))
        fig_tv = px.bar(transp_vol, y="Transportadora", x="Pedidos",
                        orientation="h", height=300,
                        color_discrete_sequence=[STEEL_BLUE],
                        text="Pedidos")
        fig_tv.update_traces(textposition="outside",
                             textfont=dict(color=GRAPHITE_GREY, size=11))
        fig_tv = _layout(fig_tv, height=300)
        fig_tv.update_layout(showlegend=False)
        st.plotly_chart(fig_tv, use_container_width=True)

    with col2:
        st.markdown("<div class='sec-title'>Excepciones por transportadora</div>", unsafe_allow_html=True)
        exc = df_all[df_all["Nivel"].isin(["CRITICO","RIESGO"])]
        transp_exc = (exc.groupby(["Transportadora","Nivel"])
                      .size().reset_index(name="Pedidos"))
        transp_exc["Nivel"] = pd.Categorical(transp_exc["Nivel"],
                                             ["CRITICO","RIESGO"], ordered=True)
        fig_te = px.bar(
            transp_exc, y="Transportadora", x="Pedidos", color="Nivel",
            color_discrete_map=COLOR_NIVEL, orientation="h",
            barmode="stack", height=300,
        )
        fig_te = _layout(fig_te, height=300)
        fig_te.update_layout(legend=dict(orientation="h", y=1.08,
                             font=dict(color=GRAPHITE_GREY)))
        st.plotly_chart(fig_te, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 4 — TIEMPO EN TRÁNSITO
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("⏱️ Tiempo en tránsito", expanded=False):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("<div class='sec-title'>Distribución de días en tránsito</div>", unsafe_allow_html=True)
        fig_hist = px.histogram(
            df_all, x="Días", nbins=20,
            color_discrete_sequence=[STEEL_BLUE], height=280,
        )
        fig_hist.update_traces(marker_line_color="white", marker_line_width=1)
        fig_hist = _layout(fig_hist, height=280)
        fig_hist.update_layout(bargap=0.05,
                               xaxis_title="Días en tránsito",
                               yaxis_title="Cantidad de pedidos")
        st.plotly_chart(fig_hist, use_container_width=True)

    with col2:
        st.markdown("<div class='sec-title'>Rango de días por nivel</div>", unsafe_allow_html=True)
        fig_box = px.box(
            df_all, x="Nivel", y="Días", color="Nivel",
            color_discrete_map=COLOR_NIVEL,
            category_orders={"Nivel": ["CRITICO","RIESGO","NORMAL"]},
            height=280,
        )
        fig_box = _layout(fig_box, height=280)
        fig_box.update_layout(showlegend=False,
                              xaxis_title="", yaxis_title="Días en tránsito")
        st.plotly_chart(fig_box, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 5 — CIUDADES Y NOVEDADES
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("📍 Ciudades y novedades", expanded=False):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("<div class='sec-title'>Top 10 ciudades con más pedidos</div>", unsafe_allow_html=True)
        top_ciudad = (df_all.groupby("Ciudad").size()
                      .sort_values(ascending=True).tail(10)
                      .reset_index(name="Pedidos"))
        fig_ciu = px.bar(top_ciudad, y="Ciudad", x="Pedidos",
                         orientation="h", height=320,
                         color_discrete_sequence=[DEEP_INK],
                         text="Pedidos")
        fig_ciu.update_traces(textposition="outside",
                              textfont=dict(color=GRAPHITE_GREY, size=11))
        fig_ciu = _layout(fig_ciu, height=320)
        fig_ciu.update_layout(showlegend=False)
        st.plotly_chart(fig_ciu, use_container_width=True)

    with col2:
        st.markdown("<div class='sec-title'>Novedades más frecuentes</div>", unsafe_allow_html=True)
        novedades = (df_all[df_all["Novedad"] != "NINGUNO"]["Novedad"]
                     .value_counts().head(10)
                     .sort_values(ascending=True)
                     .reset_index())
        novedades.columns = ["Novedad","Cantidad"]
        fig_nov = px.bar(novedades, y="Novedad", x="Cantidad",
                         orientation="h", height=320,
                         color_discrete_sequence=[RIESGO_COLOR],
                         text="Cantidad")
        fig_nov.update_traces(textposition="outside",
                              textfont=dict(color=GRAPHITE_GREY, size=11))
        fig_nov = _layout(fig_nov, height=320)
        fig_nov.update_layout(showlegend=False)
        st.plotly_chart(fig_nov, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 6 — COD: VALOR EN RIESGO
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("💸 Valor COD en riesgo", expanded=False):
    df_cod = df_all[df_all["COD"] == "SÍ"].copy()
    df_cod["Valor COD $"] = df_cod["Valor COD"].apply(_parse_cod)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("<div class='sec-title'>Valor COD por zona y nivel</div>", unsafe_allow_html=True)
        cod_zona = (df_cod.groupby(["Zona","Nivel"])["Valor COD $"]
                    .sum().reset_index())
        cod_zona["Nivel"] = pd.Categorical(cod_zona["Nivel"],
                                           ["CRITICO","RIESGO","NORMAL"], ordered=True)
        fig_cv = px.bar(
            cod_zona, y="Zona", x="Valor COD $", color="Nivel",
            color_discrete_map=COLOR_NIVEL, orientation="h",
            barmode="stack", height=260,
        )
        fig_cv = _layout(fig_cv, height=260)
        fig_cv.update_layout(legend=dict(orientation="h", y=1.08,
                             font=dict(color=GRAPHITE_GREY)),
                             xaxis_tickformat="$,.0f")
        st.plotly_chart(fig_cv, use_container_width=True)

    with col2:
        st.markdown("<div class='sec-title'>Valor COD por transportadora (crítico + riesgo)</div>",
                    unsafe_allow_html=True)
        cod_exc = df_cod[df_cod["Nivel"].isin(["CRITICO","RIESGO"])]
        cod_transp = (cod_exc.groupby("Transportadora")["Valor COD $"]
                      .sum().sort_values(ascending=True)
                      .reset_index())
        fig_ct = px.bar(cod_transp, y="Transportadora", x="Valor COD $",
                        orientation="h", height=260,
                        color_discrete_sequence=[CRITICO_COLOR])
        fig_ct = _layout(fig_ct, height=260)
        fig_ct.update_layout(showlegend=False, xaxis_tickformat="$,.0f")
        st.plotly_chart(fig_ct, use_container_width=True)
