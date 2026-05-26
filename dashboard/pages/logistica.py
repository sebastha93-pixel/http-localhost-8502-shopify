"""
Módulo Logística — MALE'DENIM
Insights · Contraentregas · Pago Previo — todo en una sola página con tabs.
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
    cargar_datos, color_nivel, render_sidebar, render_detalle, _parse_cod,
    bar_chart_zona_nivel, render_tabla, simple_bar,
)

st.markdown(CSS, unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────────────────
ruta_csv, ts, filtro_nivel, filtro_zona = render_sidebar("Logística")

# ── Pantalla de bienvenida si no hay CSV ───────────────────────────────────────
if not ruta_csv:
    st.markdown(f"""
        <p class="titulo-panel">📦 LOGÍSTICA</p>
        <p class="subtitulo">Gestión operativa · MALE'DENIM</p>
        <hr style='margin:10px 0 24px;'>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:white;border-radius:6px;border-left:4px solid {STEEL_BLUE};
                padding:28px 32px;max-width:620px;margin:0 auto;">
        <div style="font-size:0.65rem;letter-spacing:3px;color:{STEEL_BLUE};
                    text-transform:uppercase;margin-bottom:12px;">CÓMO EMPEZAR</div>
        <div style="display:flex;flex-direction:column;gap:16px;">
            <div style="display:flex;align-items:flex-start;gap:14px;">
                <div style="background:{DEEP_INK};color:white;border-radius:50%;
                            width:28px;height:28px;display:flex;align-items:center;
                            justify-content:center;font-weight:900;font-size:0.85rem;
                            flex-shrink:0;">1</div>
                <div>
                    <div style="font-weight:700;color:{DEEP_INK};font-size:0.9rem;">
                        Exporta el reporte de Melonn</div>
                    <div style="color:{GRAPHITE_GREY};font-size:0.8rem;margin-top:2px;">
                        En Melonn: <strong>Reportes → Pedidos activos → Exportar CSV</strong>
                    </div>
                </div>
            </div>
            <div style="display:flex;align-items:flex-start;gap:14px;">
                <div style="background:{STEEL_BLUE};color:white;border-radius:50%;
                            width:28px;height:28px;display:flex;align-items:center;
                            justify-content:center;font-weight:900;font-size:0.85rem;
                            flex-shrink:0;">2</div>
                <div>
                    <div style="font-weight:700;color:{DEEP_INK};font-size:0.9rem;">
                        Sube el archivo CSV en el panel izquierdo</div>
                    <div style="color:{GRAPHITE_GREY};font-size:0.8rem;margin-top:2px;">
                        Usa el botón <strong>Browse files</strong> o arrastra el CSV aquí
                    </div>
                </div>
            </div>
            <div style="display:flex;align-items:flex-start;gap:14px;">
                <div style="background:{NORMAL_COLOR};color:white;border-radius:50%;
                            width:28px;height:28px;display:flex;align-items:center;
                            justify-content:center;font-weight:900;font-size:0.85rem;
                            flex-shrink:0;">3</div>
                <div>
                    <div style="font-weight:700;color:{DEEP_INK};font-size:0.9rem;">
                        Navega entre Insights · Contraentregas · Pago Previo</div>
                    <div style="color:{GRAPHITE_GREY};font-size:0.8rem;margin-top:2px;">
                        El sistema prioriza los pedidos más urgentes automáticamente
                    </div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""<div class="kpi-card kpi-crit" style="text-align:center;opacity:0.4;">
            <p style="font-size:2rem;margin:0;">🔴</p>
            <p class="kpi-label" style="margin-top:6px;">Críticos</p>
            <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""<div class="kpi-card kpi-ries" style="text-align:center;opacity:0.4;">
            <p style="font-size:2rem;margin:0;">🟠</p>
            <p class="kpi-label" style="margin-top:6px;">En riesgo</p>
            <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
    with col3:
        st.markdown(f"""<div class="kpi-card kpi-norm" style="text-align:center;opacity:0.4;">
            <p style="font-size:2rem;margin:0;">🟢</p>
            <p class="kpi-label" style="margin-top:6px;">Normal</p>
            <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
    st.stop()

# ── Cargar datos ───────────────────────────────────────────────────────────────
try:
    with st.spinner("Procesando pedidos..."):
        df_all, omitidos = cargar_datos(ruta_csv, ts)
except Exception as e:
    st.error(f"❌ Error al cargar el archivo: {e}")
    st.info("Verifica que el archivo sea un CSV exportado directamente desde Melonn.")
    st.stop()

# ── Separar COD vs Prepago ─────────────────────────────────────────────────────
df_cod     = df_all[df_all["COD"] == "SÍ"]
df_prepago = df_all[df_all["COD"] == "—"]

# Aplicar filtros
df_filt = df_all.copy()
if filtro_nivel: df_filt = df_filt[df_filt["Nivel"].isin(filtro_nivel)]
if filtro_zona:  df_filt = df_filt[df_filt["Zona"].isin(filtro_zona)]

df_cod_f  = df_filt[df_filt["COD"] == "SÍ"]
df_pre_f  = df_filt[df_filt["COD"] == "—"]

total      = len(df_all)
criticos   = len(df_all[df_all["Nivel"] == "CRITICO"])
riesgo_n   = len(df_all[df_all["Nivel"] == "RIESGO"])
normales   = len(df_all[df_all["Nivel"] == "NORMAL"])
pct_exc    = round((criticos + riesgo_n) / total * 100) if total else 0
valor_cod_riesgo = df_cod[df_cod["Nivel"].isin(["CRITICO","RIESGO"])]["Valor COD"].apply(_parse_cod).sum()

# ── Encabezado ─────────────────────────────────────────────────────────────────
st.markdown(f"""
    <p class="titulo-panel">📦 LOGÍSTICA</p>
    <p class="subtitulo">Gestión operativa · MALE'DENIM · {ts}</p>
    <hr style='margin:10px 0;'>
""", unsafe_allow_html=True)

# ── KPIs rápidos siempre visibles ──────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
color_pct = CRITICO_COLOR if pct_exc > 40 else (RIESGO_COLOR if pct_exc > 20 else NORMAL_COLOR)
with k1:
    st.markdown(f"""<div class="kpi-card kpi-crit">
        <p class="kpi-num">{criticos}</p><p class="kpi-label">🔴 Críticos</p>
        <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
with k2:
    st.markdown(f"""<div class="kpi-card kpi-ries">
        <p class="kpi-num">{riesgo_n}</p><p class="kpi-label">🟠 En riesgo</p>
        <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
with k3:
    st.markdown(f"""<div class="kpi-card kpi-norm">
        <p class="kpi-num">{normales}</p><p class="kpi-label">🟢 Normal</p>
        <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
with k4:
    st.markdown(f"""<div class="kpi-card kpi-extra">
        <p class="kpi-num" style="font-size:1.2rem;">${valor_cod_riesgo:,.0f}</p>
        <p class="kpi-label">💸 COD en riesgo</p>
        <p class="kpi-sub">Recaudo comprometido</p></div>""", unsafe_allow_html=True)
with k5:
    st.markdown(f"""<div class="kpi-card" style="background:{color_pct};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{pct_exc}%</p><p class="kpi-label">En excepción</p>
        <p class="kpi-sub">{criticos+riesgo_n} de {total} pedidos</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── TABS PRINCIPALES ───────────────────────────────────────────────────────────
tab_ins, tab_cod, tab_pre = st.tabs([
    f"📊  Insights  ({total} pedidos)",
    f"💰  Contraentregas  ({len(df_cod_f)} COD)",
    f"✅  Pago Previo  ({len(df_pre_f)} pedidos)",
])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — INSIGHTS
# ════════════════════════════════════════════════════════════════════════════════
with tab_ins:

    # ── COD vs Prepago ──
    c1, c2, c3, c4 = st.columns(4)
    dias_prom = df_all["Días"].mean() if not df_all.empty else 0
    with c1:
        st.markdown(f"""<div class="kpi-card kpi-extra">
            <p class="kpi-num">{len(df_cod)}</p><p class="kpi-label">Pedidos COD</p>
            <p class="kpi-sub">{round(len(df_cod)/total*100) if total else 0}% del total</p></div>""",
            unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{len(df_prepago)}</p><p class="kpi-label">Pago previo</p>
            <p class="kpi-sub">{round(len(df_prepago)/total*100) if total else 0}% del total</p></div>""",
            unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{dias_prom:.1f}</p><p class="kpi-label">Días promedio</p>
            <p class="kpi-sub">Tiempo en tránsito</p></div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{omitidos}</p><p class="kpi-label">Omitidos</p>
            <p class="kpi-sub">Entregados / sin estado</p></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Gráficos colapsables ──
    with st.expander("📊 Distribución por zona y transportadora", expanded=True):
        cg1, cg2 = st.columns(2)
        with cg1:
            st.markdown("<div class='sec-title'>Por zona</div>", unsafe_allow_html=True)
            if not df_filt.empty:
                bar_chart_zona_nivel(df_filt, height=200)
            else:
                st.info("Sin datos con los filtros actuales.")
        with cg2:
            st.markdown("<div class='sec-title'>Transportadora — excepciones</div>", unsafe_allow_html=True)
            transp = df_filt[df_filt["Nivel"].isin(["CRITICO","RIESGO"])]["Transportadora"].value_counts()
            if not transp.empty:
                simple_bar(transp, color=RIESGO_COLOR, height=200)
            else:
                st.success("✅ Sin excepciones en transportadoras.")

    with st.expander("🚨 Top 20 excepciones activas", expanded=True):
        df_exc = df_filt[df_filt["Nivel"].isin(["CRITICO","RIESGO"])].copy()
        if df_exc.empty:
            st.success("✅ Sin excepciones con los filtros actuales.")
        else:
            COLS_TOP = ["Prioridad","Nivel","Score","Orden","Cliente","Ciudad","Zona",
                        "Días","Días sobre SLA","COD","Valor COD","Transportadora","Novedad"]
            cols_disp = [c for c in COLS_TOP if c in df_exc.columns]
            st.dataframe(df_exc[cols_disp].head(20),
                use_container_width=True, height=300, hide_index=True,
                column_config={
                    "Score": st.column_config.NumberColumn("Score", format="%d"),
                    "Días":  st.column_config.NumberColumn("Días",  format="%d"),
                    "Días sobre SLA": st.column_config.NumberColumn("Días s/SLA", format="%d"),
                })
            st.caption(f"Top 20 de {len(df_exc)} excepciones · ordenadas por prioridad")

    with st.expander("📋 Novedades más frecuentes", expanded=False):
        novedades = df_all[df_all["Novedad"] != "NINGUNO"]["Novedad"].value_counts().head(8)
        if not novedades.empty:
            simple_bar(novedades, color=CRITICO_COLOR, height=180)
        else:
            st.info("Sin novedades registradas.")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — CONTRAENTREGAS (COD)
# ════════════════════════════════════════════════════════════════════════════════
with tab_cod:
    df_c = df_cod_f.copy()

    n_crit_c   = len(df_c[df_c["Nivel"] == "CRITICO"])
    n_ries_c   = len(df_c[df_c["Nivel"] == "RIESGO"])
    n_norm_c   = len(df_c[df_c["Nivel"] == "NORMAL"])
    val_riesgo = df_c[df_c["Nivel"].isin(["CRITICO","RIESGO"])]["Valor COD"].apply(_parse_cod).sum()
    val_total  = df_cod["Valor COD"].apply(_parse_cod).sum()

    st.caption("Pedidos con recaudo pendiente. Los críticos representan riesgo de pérdida de dinero.")

    k1,k2,k3,k4,k5 = st.columns(5)
    with k1:
        st.markdown(f"""<div class="kpi-card kpi-crit">
            <p class="kpi-num">{n_crit_c}</p><p class="kpi-label">🔴 Crítico</p>
            <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
    with k2:
        st.markdown(f"""<div class="kpi-card kpi-ries">
            <p class="kpi-num">{n_ries_c}</p><p class="kpi-label">🟠 En riesgo</p>
            <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
    with k3:
        st.markdown(f"""<div class="kpi-card kpi-norm">
            <p class="kpi-num">{n_norm_c}</p><p class="kpi-label">🟢 Normal</p>
            <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
    with k4:
        st.markdown(f"""<div class="kpi-card kpi-extra">
            <p class="kpi-num" style="font-size:1.1rem;">${val_riesgo:,.0f}</p>
            <p class="kpi-label">💸 En riesgo</p>
            <p class="kpi-sub">Recaudo comprometido</p></div>""", unsafe_allow_html=True)
    with k5:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{len(df_cod)}</p><p class="kpi-label">Total COD</p>
            <p class="kpi-sub">${val_total:,.0f} portafolio</p></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if df_c.empty:
        st.success("✅ Sin pedidos COD con los filtros seleccionados.")
    else:
        with st.expander("📊 Análisis visual", expanded=False):
            cg1, cg2 = st.columns(2)
            with cg1:
                st.markdown("<div class='sec-title'>Por zona — COD</div>", unsafe_allow_html=True)
                bar_chart_zona_nivel(df_c, height=200)
            with cg2:
                st.markdown("<div class='sec-title'>Días en tránsito — excepciones</div>", unsafe_allow_html=True)
                df_exc_c = df_c[df_c["Nivel"].isin(["CRITICO","RIESGO"])]
                if not df_exc_c.empty:
                    bins = pd.cut(df_exc_c["Días"], bins=[0,2,4,7,10,15,30],
                                  labels=["1-2d","3-4d","5-7d","8-10d","11-15d","16d+"])
                    simple_bar(bins.value_counts().sort_index(), color=CRITICO_COLOR, height=200)
                else:
                    st.info("Sin excepciones.")

        with st.expander(f"📋 Lista de trabajo — {len(df_c)} pedidos COD", expanded=True):
            st.caption("Críticos primero · mayor riesgo de pérdida de dinero")
            COLS_C = ["Prioridad","Nivel","Score","Orden","Cliente","Teléfono",
                      "Ciudad","Zona","Días","Días sobre SLA","Valor COD",
                      "Transportadora","Novedad","Motivo riesgo"]
            COLS_C = [c for c in COLS_C if c in df_c.columns]
            render_tabla(df_c, COLS_C, key="tabla_cod", height=400)
            st.download_button(
                "⬇️ Descargar lista COD (.CSV)",
                data=df_c.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"maledenim_COD_{date.today()}.csv",
                mime="text/csv",
            )

        with st.expander("🔍 Detalle de pedido + seguimiento de guía", expanded=False):
            render_detalle(df_c, tab_key="cod")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — PAGO PREVIO
# ════════════════════════════════════════════════════════════════════════════════
with tab_pre:
    df_p = df_pre_f.copy()

    n_crit_p  = len(df_p[df_p["Nivel"] == "CRITICO"])
    n_ries_p  = len(df_p[df_p["Nivel"] == "RIESGO"])
    n_norm_p  = len(df_p[df_p["Nivel"] == "NORMAL"])
    n_prom    = len(df_p[df_p["Promesa vencida"] == "SÍ"]) if "Promesa vencida" in df_p.columns else 0
    pct_p     = round((n_crit_p + n_ries_p) / len(df_prepago) * 100) if len(df_prepago) > 0 else 0

    st.caption("Pedidos ya cobrados. El riesgo aquí es reputacional — el cliente espera su entrega.")

    k1,k2,k3,k4,k5 = st.columns(5)
    with k1:
        st.markdown(f"""<div class="kpi-card kpi-crit">
            <p class="kpi-num">{n_crit_p}</p><p class="kpi-label">🔴 Crítico</p>
            <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
    with k2:
        st.markdown(f"""<div class="kpi-card kpi-ries">
            <p class="kpi-num">{n_ries_p}</p><p class="kpi-label">🟠 En riesgo</p>
            <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
    with k3:
        st.markdown(f"""<div class="kpi-card kpi-norm">
            <p class="kpi-num">{n_norm_p}</p><p class="kpi-label">🟢 Normal</p>
            <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
    with k4:
        st.markdown(f"""<div class="kpi-card kpi-extra">
            <p class="kpi-num">{n_prom}</p><p class="kpi-label">⏰ Promesa vencida</p>
            <p class="kpi-sub">Cliente esperó demasiado</p></div>""", unsafe_allow_html=True)
    with k5:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{len(df_prepago)}</p><p class="kpi-label">Total prepago</p>
            <p class="kpi-sub">{pct_p}% en excepción</p></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if df_p.empty:
        st.success("✅ Sin pedidos prepago con los filtros seleccionados. ¡Todo en orden!")
    else:
        with st.expander("📊 Análisis visual", expanded=False):
            cg1, cg2 = st.columns(2)
            with cg1:
                st.markdown("<div class='sec-title'>Por zona — Pago previo</div>", unsafe_allow_html=True)
                bar_chart_zona_nivel(df_p, height=200)
            with cg2:
                st.markdown("<div class='sec-title'>Transportadora — excepciones</div>", unsafe_allow_html=True)
                df_exc_p = df_p[df_p["Nivel"].isin(["CRITICO","RIESGO"])]
                if not df_exc_p.empty:
                    simple_bar(df_exc_p["Transportadora"].value_counts(), color=RIESGO_COLOR, height=200)
                else:
                    st.info("Sin excepciones.")

        with st.expander(f"📋 Lista de trabajo — {len(df_p)} pedidos prepago", expanded=True):
            st.caption("El riesgo es reputacional — el cliente ya pagó y espera su pedido")
            COLS_P = ["Prioridad","Nivel","Score","Orden","Cliente","Teléfono",
                      "Ciudad","Zona","Días","Días sobre SLA","Promesa vencida",
                      "Transportadora","Novedad","Motivo riesgo"]
            COLS_P = [c for c in COLS_P if c in df_p.columns]
            render_tabla(df_p, COLS_P, key="tabla_prepago", height=400)
            st.download_button(
                "⬇️ Descargar lista Pago Previo (.CSV)",
                data=df_p.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"maledenim_prepago_{date.today()}.csv",
                mime="text/csv",
            )

        with st.expander("🔍 Detalle de pedido + seguimiento de guía", expanded=False):
            render_detalle(df_p, tab_key="prepago")
