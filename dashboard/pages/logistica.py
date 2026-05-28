"""
Módulo Logística — MALE'DENIM
Tabs: Insights · Contraentregas · Pago Previo · Análisis
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date

# Cargar .env localmente (en Streamlit Cloud usa Secrets)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except Exception:
    pass

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR,
    cargar_datos, render_sidebar, render_detalle, _parse_cod,
    render_tabla,
)
from memoria import (
    disponible as mem_ok, guardar_snapshot,
    cargar_snapshots, historial_pedido,
    cargar_notas, agregar_nota,
    cargar_acciones, agregar_accion, TIPOS_ACCION,
)

st.markdown(CSS, unsafe_allow_html=True)

# ── Helpers de gráficos ────────────────────────────────────────────────────────
COLOR_NIVEL = {"CRITICO": CRITICO_COLOR, "RIESGO": RIESGO_COLOR, "NORMAL": NORMAL_COLOR}
FONT = dict(family="Arial, sans-serif", size=12, color=GRAPHITE_GREY)

def _lay(fig, h=280):
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=10, t=30, b=0), font=FONT, height=h,
    )
    fig.update_xaxes(tickfont=dict(color=GRAPHITE_GREY), gridcolor="#f0ede8", zeroline=False)
    fig.update_yaxes(tickfont=dict(color=GRAPHITE_GREY), gridcolor="#f0ede8", zeroline=False)
    return fig

def _hbar(df_in, y, x, color, h=260, text_col=None):
    """Barra horizontal simple."""
    fig = px.bar(df_in, y=y, x=x, orientation="h", height=h,
                 color_discrete_sequence=[color],
                 text=text_col or x)
    fig.update_traces(textposition="outside",
                      textfont=dict(color=GRAPHITE_GREY, size=11))
    fig = _lay(fig, h=h)
    fig.update_layout(showlegend=False)
    return fig


def _render_memoria(orden: str):
    """Sección de trazabilidad dentro del detalle de un pedido."""
    if not mem_ok():
        st.caption("ℹ️ Conecta Supabase para activar la memoria.")
        return

    st.markdown(f"<div class='sec-title' style='margin-top:16px;'>🧠 TRAZABILIDAD — {orden}</div>",
                unsafe_allow_html=True)

    col_h, col_acc, col_nota = st.columns([1.4, 1.3, 1.3])

    # ── Historial del pedido ────────────────────────────────────────────────────
    with col_h:
        st.markdown("**📅 Historial en cargas anteriores**")
        df_h = historial_pedido(orden)
        if df_h.empty:
            st.caption("Sin registros anteriores.")
        else:
            df_h["Fecha"] = df_h["Fecha"].dt.strftime("%d/%m %H:%M")
            st.dataframe(
                df_h[["Fecha","Nivel","Score","Días","Novedad"]],
                use_container_width=True, hide_index=True, height=160,
            )

    # ── Acciones ────────────────────────────────────────────────────────────────
    with col_acc:
        st.markdown("**⚡ Acciones registradas**")

        # Mostrar mensaje pendiente de operación anterior
        _k_ac_msg = f"_msg_accion_{orden}"
        if _k_ac_msg in st.session_state:
            _ok, _msg = st.session_state.pop(_k_ac_msg)
            if _ok:
                st.success(_msg, icon="✅")
            else:
                st.error(_msg, icon="❌")

        df_ac = cargar_acciones(orden)
        if not df_ac.empty:
            for _, r in df_ac.iterrows():
                ts_str = r["creada_en"].strftime("%d/%m %H:%M") if pd.notna(r["creada_en"]) else ""
                st.markdown(
                    f"<div style='background:white;border-left:3px solid {STEEL_BLUE};"
                    f"padding:6px 10px;margin-bottom:4px;border-radius:3px;font-size:0.8rem;'>"
                    f"<b>{r['tipo']}</b> · {r['autor']} · {ts_str}<br>"
                    f"<span style='color:{GRAPHITE_GREY};'>{r['descripcion']}</span></div>",
                    unsafe_allow_html=True)
        else:
            st.caption("Sin acciones registradas.")

        with st.form(key=f"form_accion_{orden}", clear_on_submit=True):
            tipo_ac  = st.selectbox("Tipo", TIPOS_ACCION, label_visibility="collapsed")
            desc_ac  = st.text_input("Descripción", placeholder="Descripción de la acción...",
                                     label_visibility="collapsed")
            autor_ac = st.text_input("Quién", placeholder="Tu nombre",
                                     label_visibility="collapsed")
            if st.form_submit_button("➕ Registrar acción", use_container_width=True):
                if desc_ac.strip():
                    ok, err = agregar_accion(orden, tipo_ac, desc_ac, autor_ac)
                    if ok:
                        st.session_state[_k_ac_msg] = (True, "Acción guardada correctamente")
                    else:
                        st.session_state[_k_ac_msg] = (False, f"No se pudo guardar: {err}")
                    st.rerun()
                else:
                    st.warning("Escribe una descripción antes de registrar.")

    # ── Notas ────────────────────────────────────────────────────────────────────
    with col_nota:
        st.markdown("**📝 Notas del equipo**")

        # Mostrar mensaje pendiente de operación anterior
        _k_n_msg = f"_msg_nota_{orden}"
        if _k_n_msg in st.session_state:
            _ok, _msg = st.session_state.pop(_k_n_msg)
            if _ok:
                st.success(_msg, icon="✅")
            else:
                st.error(_msg, icon="❌")

        df_n = cargar_notas(orden)
        if not df_n.empty:
            for _, r in df_n.iterrows():
                ts_str = r["creada_en"].strftime("%d/%m %H:%M") if pd.notna(r["creada_en"]) else ""
                st.markdown(
                    f"<div style='background:white;border-left:3px solid {NORMAL_COLOR};"
                    f"padding:6px 10px;margin-bottom:4px;border-radius:3px;font-size:0.8rem;'>"
                    f"<b>{r['autor']}</b> · {ts_str}<br>"
                    f"<span style='color:{GRAPHITE_GREY};'>{r['nota']}</span></div>",
                    unsafe_allow_html=True)
        else:
            st.caption("Sin notas aún.")

        with st.form(key=f"form_nota_{orden}", clear_on_submit=True):
            nota_txt = st.text_area("Nueva nota", placeholder="Escribe una nota...",
                                    height=68, label_visibility="collapsed")
            autor_n  = st.text_input("Quién", placeholder="Tu nombre",
                                     label_visibility="collapsed")
            if st.form_submit_button("💬 Agregar nota", use_container_width=True):
                if nota_txt.strip():
                    ok, err = agregar_nota(orden, autor_n, nota_txt)
                    if ok:
                        st.session_state[_k_n_msg] = (True, "Nota guardada correctamente")
                    else:
                        st.session_state[_k_n_msg] = (False, f"No se pudo guardar: {err}")
                    st.rerun()
                else:
                    st.warning("Escribe una nota antes de guardar.")

# ── Sidebar ────────────────────────────────────────────────────────────────────
ruta_csv, ts, filtro_nivel, filtro_zona = render_sidebar("Logística")

# ── Pantalla de bienvenida ─────────────────────────────────────────────────────
if not ruta_csv:
    st.markdown(f"""
        <p class="titulo-panel">📦 LOGÍSTICA</p>
        <p class="subtitulo">Gestión operativa · MALE'DENIM</p>
        <hr style='margin:10px 0 28px;'>
    """, unsafe_allow_html=True)
    st.markdown(f"""
    <div style="background:white;border-radius:10px;border:1px solid rgba(33,48,51,0.07);
                padding:36px 40px;max-width:480px;margin:0 auto;
                box-shadow:0 2px 12px rgba(0,0,0,0.06);text-align:center;">
        <div style="font-size:2rem;margin-bottom:14px;">📂</div>
        <div style="font-size:1rem;font-weight:700;color:{DEEP_INK};margin-bottom:6px;">
            Sube el reporte de Melonn
        </div>
        <div style="font-size:0.8rem;color:#505050;line-height:1.6;">
            Usa el panel izquierdo para cargar el CSV.<br>
            El sistema prioriza los pedidos críticos automáticamente.
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── Cargar datos ───────────────────────────────────────────────────────────────
try:
    with st.spinner("Procesando pedidos..."):
        df_all, omitidos = cargar_datos(ruta_csv, ts)
except Exception as e:
    st.error(f"❌ Error al cargar: {e}")
    st.stop()

# ── Auto-guardar snapshot en Supabase (una vez por CSV) ────────────────────────
_snap_key = f"snap_guardado_{ts}"
if mem_ok() and not st.session_state.get(_snap_key):
    with st.spinner("Guardando snapshot en memoria..."):
        snap_id = guardar_snapshot(df_all, ts, omitidos if isinstance(omitidos, int) else sum(omitidos.values()) if isinstance(omitidos, dict) else 0)
    if snap_id:
        st.session_state[_snap_key] = snap_id

df_cod     = df_all[df_all["COD"] == "SÍ"]
df_prepago = df_all[df_all["COD"] == "—"]

df_filt = df_all.copy()
if filtro_nivel: df_filt = df_filt[df_filt["Nivel"].isin(filtro_nivel)]
if filtro_zona:  df_filt = df_filt[df_filt["Zona"].isin(filtro_zona)]

df_cod_f = df_filt[df_filt["COD"] == "SÍ"]
df_pre_f = df_filt[df_filt["COD"] == "—"]

total    = len(df_all)
criticos = len(df_all[df_all["Nivel"] == "CRITICO"])
riesgo_n = len(df_all[df_all["Nivel"] == "RIESGO"])
normales = len(df_all[df_all["Nivel"] == "NORMAL"])
pct_exc  = round((criticos + riesgo_n) / total * 100) if total else 0
valor_cod_riesgo = df_cod[df_cod["Nivel"].isin(["CRITICO","RIESGO"])]["Valor COD"].apply(_parse_cod).sum()

def _fmt_m(v):
    """Formatea montos: 15.1M, 897K, etc."""
    if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
    if v >= 1_000:     return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"
omit_total = sum(omitidos.values()) if isinstance(omitidos, dict) else int(omitidos or 0)

# ── Encabezado + KPIs globales ─────────────────────────────────────────────────
st.markdown(f"""
    <p class="titulo-panel">📦 LOGÍSTICA</p>
    <p class="subtitulo">Gestión operativa · MALE'DENIM · {ts}</p>
    <hr style='margin:10px 0;'>
""", unsafe_allow_html=True)

k1,k2,k3,k4,k5 = st.columns(5)
color_pct = CRITICO_COLOR if pct_exc > 40 else (RIESGO_COLOR if pct_exc > 20 else NORMAL_COLOR)
with k1:
    st.markdown(f"""<div class="kpi-card kpi-crit">
        <p class="kpi-num">{criticos}</p><p class="kpi-label">CRÍTICOS</p>
        <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
with k2:
    st.markdown(f"""<div class="kpi-card kpi-ries">
        <p class="kpi-num">{riesgo_n}</p><p class="kpi-label">EN RIESGO</p>
        <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
with k3:
    st.markdown(f"""<div class="kpi-card kpi-norm">
        <p class="kpi-num">{normales}</p><p class="kpi-label">NORMAL</p>
        <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
with k4:
    st.markdown(f"""<div class="kpi-card kpi-extra">
        <p class="kpi-num">{_fmt_m(valor_cod_riesgo)}</p>
        <p class="kpi-label">COD EN RIESGO</p>
        <p class="kpi-sub">Recaudo comprometido</p></div>""", unsafe_allow_html=True)
with k5:
    st.markdown(f"""<div class="kpi-card" style="background:{color_pct};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{pct_exc}%</p><p class="kpi-label">EN EXCEPCIÓN</p>
        <p class="kpi-sub">{criticos+riesgo_n} de {total} pedidos</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── TABS ───────────────────────────────────────────────────────────────────────
tab_ins, tab_cod, tab_pre, tab_ana = st.tabs([
    f"📊  Insights  ({total})",
    f"💰  Contraentregas  ({len(df_cod_f)} COD)",
    f"✅  Pago Previo  ({len(df_pre_f)})",
    "📈  Análisis",
])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — INSIGHTS
# ════════════════════════════════════════════════════════════════════════════════
with tab_ins:
    dias_prom = df_all["Días"].mean() if not df_all.empty else 0
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        st.markdown(f"""<div class="kpi-card kpi-extra">
            <p class="kpi-num">{len(df_cod)}</p><p class="kpi-label">PEDIDOS COD</p>
            <p class="kpi-sub">{round(len(df_cod)/total*100) if total else 0}% del total</p></div>""",
            unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{len(df_prepago)}</p><p class="kpi-label">PAGO PREVIO</p>
            <p class="kpi-sub">{round(len(df_prepago)/total*100) if total else 0}% del total</p></div>""",
            unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{dias_prom:.1f}</p><p class="kpi-label">DÍAS PROMEDIO</p>
            <p class="kpi-sub">Tiempo en tránsito</p></div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{omit_total}</p><p class="kpi-label">OMITIDOS</p>
            <p class="kpi-sub">Entregados / sin estado</p></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    with st.expander("📊 Distribución por zona y transportadora", expanded=True):
        cg1, cg2 = st.columns(2)
        with cg1:
            st.markdown("<div class='sec-title'>Pedidos por zona</div>", unsafe_allow_html=True)
            if not df_filt.empty:
                zd = (df_filt.groupby(["Zona","Nivel"]).size().reset_index(name="Pedidos"))
                zd["Nivel"] = pd.Categorical(zd["Nivel"], ["CRITICO","RIESGO","NORMAL"], ordered=True)
                fig_z = px.bar(zd, y="Zona", x="Pedidos", color="Nivel",
                               color_discrete_map=COLOR_NIVEL, orientation="h",
                               barmode="stack", height=220)
                fig_z = _lay(fig_z, 220)
                fig_z.update_layout(legend=dict(orientation="h", y=1.12,
                                    font=dict(color=GRAPHITE_GREY, size=11)))
                st.plotly_chart(fig_z, use_container_width=True)
        with cg2:
            st.markdown("<div class='sec-title'>Excepciones por transportadora</div>", unsafe_allow_html=True)
            te = (df_filt[df_filt["Nivel"].isin(["CRITICO","RIESGO"])]
                  ["Transportadora"].value_counts().reset_index())
            te.columns = ["Transportadora","Pedidos"]
            if not te.empty:
                fig_t = px.bar(te, y="Transportadora", x="Pedidos",
                               orientation="h", height=220,
                               color_discrete_sequence=[RIESGO_COLOR], text="Pedidos")
                fig_t.update_traces(textposition="outside",
                                    textfont=dict(color=GRAPHITE_GREY, size=11))
                fig_t = _lay(fig_t, 220)
                fig_t.update_layout(showlegend=False)
                st.plotly_chart(fig_t, use_container_width=True)
            else:
                st.success("✅ Sin excepciones en transportadoras.")

    with st.expander("🚨 Top 20 excepciones activas", expanded=True):
        df_exc = df_filt[df_filt["Nivel"].isin(["CRITICO","RIESGO"])].copy()
        if df_exc.empty:
            st.success("✅ Sin excepciones.")
        else:
            COLS_TOP = ["Prioridad","Nivel","Score","Orden","Cliente","Ciudad","Zona",
                        "Días","Días sobre SLA","COD","Valor COD","Transportadora","Novedad"]
            cols_d = [c for c in COLS_TOP if c in df_exc.columns]
            st.dataframe(df_exc[cols_d].head(20), use_container_width=True,
                         height=300, hide_index=True,
                         column_config={
                             "Score": st.column_config.NumberColumn("Score", format="%d"),
                             "Días":  st.column_config.NumberColumn("Días", format="%d"),
                             "Días sobre SLA": st.column_config.NumberColumn("Días s/SLA", format="%d"),
                         })
            st.caption(f"Top 20 de {len(df_exc)} excepciones")

    with st.expander("📋 Novedades más frecuentes", expanded=False):
        nov = (df_all[df_all["Novedad"] != "NINGUNO"]["Novedad"]
               .value_counts().head(8).sort_values(ascending=True).reset_index())
        nov.columns = ["Novedad","Cantidad"]
        if not nov.empty:
            fig_n = px.bar(nov, y="Novedad", x="Cantidad", orientation="h",
                           height=260, color_discrete_sequence=[CRITICO_COLOR], text="Cantidad")
            fig_n.update_traces(textposition="outside",
                                textfont=dict(color=GRAPHITE_GREY, size=11))
            fig_n = _lay(fig_n, 260)
            fig_n.update_layout(showlegend=False)
            st.plotly_chart(fig_n, use_container_width=True)
        else:
            st.info("Sin novedades registradas.")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — CONTRAENTREGAS (COD)
# ════════════════════════════════════════════════════════════════════════════════
with tab_cod:
    df_c = df_cod_f.copy()
    n_crit_c = len(df_c[df_c["Nivel"] == "CRITICO"])
    n_ries_c = len(df_c[df_c["Nivel"] == "RIESGO"])
    n_norm_c = len(df_c[df_c["Nivel"] == "NORMAL"])
    val_riesgo = df_c[df_c["Nivel"].isin(["CRITICO","RIESGO"])]["Valor COD"].apply(_parse_cod).sum()
    val_total  = df_cod["Valor COD"].apply(_parse_cod).sum()

    st.caption("Pedidos con recaudo pendiente · COD activo")

    k1,k2,k3,k4,k5 = st.columns(5)
    with k1:
        st.markdown(f"""<div class="kpi-card kpi-crit">
            <p class="kpi-num">{n_crit_c}</p><p class="kpi-label">CRÍTICO</p>
            <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
    with k2:
        st.markdown(f"""<div class="kpi-card kpi-ries">
            <p class="kpi-num">{n_ries_c}</p><p class="kpi-label">EN RIESGO</p>
            <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
    with k3:
        st.markdown(f"""<div class="kpi-card kpi-norm">
            <p class="kpi-num">{n_norm_c}</p><p class="kpi-label">NORMAL</p>
            <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
    with k4:
        st.markdown(f"""<div class="kpi-card kpi-extra">
            <p class="kpi-num" style="font-size:1.1rem;">${val_riesgo:,.0f}</p>
            <p class="kpi-label">COD EN RIESGO</p>
            <p class="kpi-sub">Recaudo comprometido</p></div>""", unsafe_allow_html=True)
    with k5:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{len(df_cod)}</p><p class="kpi-label">TOTAL COD</p>
            <p class="kpi-sub">${val_total:,.0f} portafolio</p></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if df_c.empty:
        st.success("✅ Sin pedidos COD con los filtros seleccionados.")
    else:
        COLS_C = ["Prioridad","Nivel","Score","Orden","Cliente","Teléfono",
                  "Ciudad","Zona","Días","Días sobre SLA","Valor COD",
                  "Transportadora","Novedad","Motivo riesgo"]
        COLS_C = [c for c in COLS_C if c in df_c.columns]

        st.markdown("<div class='sec-title'>Lista de trabajo</div>", unsafe_allow_html=True)
        render_tabla(df_c, COLS_C, key="tabla_cod", height=420)

        hay_sel_cod = bool(
            st.session_state.get("tabla_cod", {}).get("selection", {}).get("rows")
        )
        with st.expander("Detalle del pedido", expanded=hay_sel_cod):
            if not hay_sel_cod:
                st.caption("Selecciona una fila para ver el detalle.")
            else:
                render_detalle(df_c, tab_key="cod")
                # Obtener número de orden del pedido seleccionado
                _rows_cod = st.session_state.get("tabla_cod", {}).get("selection", {}).get("rows", [])
                if _rows_cod:
                    _orden_cod = str(df_c.iloc[_rows_cod[0]]["Orden"])
                    _render_memoria(_orden_cod)

        st.markdown("<br>", unsafe_allow_html=True)
        st.download_button(
            "⬇️ Descargar lista COD (.CSV)",
            data=df_c.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"maledenim_COD_{date.today()}.csv",
            mime="text/csv",
        )


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — PAGO PREVIO
# ════════════════════════════════════════════════════════════════════════════════
with tab_pre:
    df_p = df_pre_f.copy()
    n_crit_p = len(df_p[df_p["Nivel"] == "CRITICO"])
    n_ries_p = len(df_p[df_p["Nivel"] == "RIESGO"])
    n_norm_p = len(df_p[df_p["Nivel"] == "NORMAL"])
    n_prom   = len(df_p[df_p["Promesa vencida"] == "SÍ"]) if "Promesa vencida" in df_p.columns else 0
    pct_p    = round((n_crit_p+n_ries_p)/len(df_prepago)*100) if len(df_prepago) > 0 else 0

    st.caption("Pedidos con pago confirmado · prepago")

    k1,k2,k3,k4,k5 = st.columns(5)
    with k1:
        st.markdown(f"""<div class="kpi-card kpi-crit">
            <p class="kpi-num">{n_crit_p}</p><p class="kpi-label">CRÍTICO</p>
            <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
    with k2:
        st.markdown(f"""<div class="kpi-card kpi-ries">
            <p class="kpi-num">{n_ries_p}</p><p class="kpi-label">EN RIESGO</p>
            <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
    with k3:
        st.markdown(f"""<div class="kpi-card kpi-norm">
            <p class="kpi-num">{n_norm_p}</p><p class="kpi-label">NORMAL</p>
            <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
    with k4:
        st.markdown(f"""<div class="kpi-card kpi-extra">
            <p class="kpi-num">{n_prom}</p><p class="kpi-label">PROMESA VENCIDA</p>
            <p class="kpi-sub">Cliente esperó demasiado</p></div>""", unsafe_allow_html=True)
    with k5:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">{len(df_prepago)}</p><p class="kpi-label">TOTAL PREPAGO</p>
            <p class="kpi-sub">{pct_p}% en excepción</p></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if df_p.empty:
        st.success("✅ Sin pedidos prepago con los filtros seleccionados.")
    else:
        COLS_P = ["Prioridad","Nivel","Score","Orden","Cliente","Teléfono",
                  "Ciudad","Zona","Días","Días sobre SLA","Promesa vencida",
                  "Transportadora","Novedad","Motivo riesgo"]
        COLS_P = [c for c in COLS_P if c in df_p.columns]

        st.markdown("<div class='sec-title'>Lista de trabajo</div>", unsafe_allow_html=True)
        render_tabla(df_p, COLS_P, key="tabla_prepago", height=420)

        hay_sel_pre = bool(
            st.session_state.get("tabla_prepago", {}).get("selection", {}).get("rows")
        )
        with st.expander("Detalle del pedido", expanded=hay_sel_pre):
            if not hay_sel_pre:
                st.caption("Selecciona una fila para ver el detalle.")
            else:
                render_detalle(df_p, tab_key="prepago")
                _rows_pre = st.session_state.get("tabla_prepago", {}).get("selection", {}).get("rows", [])
                if _rows_pre:
                    _orden_pre = str(df_p.iloc[_rows_pre[0]]["Orden"])
                    _render_memoria(_orden_pre)

        st.markdown("<br>", unsafe_allow_html=True)
        st.download_button(
            "⬇️ Descargar lista Pago Previo (.CSV)",
            data=df_p.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"maledenim_prepago_{date.today()}.csv",
            mime="text/csv",
        )


# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — ANÁLISIS
# ════════════════════════════════════════════════════════════════════════════════
with tab_ana:
    st.markdown("<div class='sec-title' style='margin-top:0;'>Visualizaciones avanzadas del estado logístico</div>",
                unsafe_allow_html=True)

    # ── Tendencias históricas (Supabase) ────────────────────────────────────────
    with st.expander("📈 Tendencias históricas — Evolución de cargas", expanded=mem_ok()):
        if not mem_ok():
            st.info("Conecta Supabase para ver la evolución a lo largo del tiempo.")
        else:
            df_snaps = cargar_snapshots(30)
            if df_snaps.empty:
                st.caption("Aún no hay snapshots guardados. Carga un CSV para comenzar.")
            else:
                df_snaps = df_snaps.sort_values("cargado_en")
                df_snaps["Fecha"] = df_snaps["cargado_en"].dt.strftime("%d/%m")

                tc1, tc2 = st.columns(2)
                with tc1:
                    st.markdown("<div class='sec-title'>Pedidos críticos y en riesgo</div>", unsafe_allow_html=True)
                    fig_t = go.Figure()
                    fig_t.add_trace(go.Scatter(
                        x=df_snaps["Fecha"], y=df_snaps["criticos"],
                        name="Crítico", line=dict(color=CRITICO_COLOR, width=2.5),
                        mode="lines+markers"))
                    fig_t.add_trace(go.Scatter(
                        x=df_snaps["Fecha"], y=df_snaps["en_riesgo"],
                        name="En riesgo", line=dict(color=RIESGO_COLOR, width=2.5),
                        mode="lines+markers"))
                    fig_t.add_trace(go.Scatter(
                        x=df_snaps["Fecha"], y=df_snaps["normales"],
                        name="Normal", line=dict(color=NORMAL_COLOR, width=2),
                        mode="lines+markers"))
                    fig_t = _lay(fig_t, 240)
                    fig_t.update_layout(legend=dict(
                        orientation="h", y=1.1, font=dict(color=GRAPHITE_GREY, size=11)))
                    st.plotly_chart(fig_t, use_container_width=True)

                with tc2:
                    st.markdown("<div class='sec-title'>Valor COD en riesgo ($)</div>", unsafe_allow_html=True)
                    fig_v = go.Figure(go.Bar(
                        x=df_snaps["Fecha"], y=df_snaps["valor_cod_riesgo"],
                        marker_color=COD_COLOR,
                        text=df_snaps["valor_cod_riesgo"].apply(lambda v: f"${v/1e6:.1f}M" if v>=1e6 else f"${v/1e3:.0f}K"),
                        textposition="outside",
                        textfont=dict(color=GRAPHITE_GREY, size=11),
                    ))
                    fig_v = _lay(fig_v, 240)
                    fig_v.update_layout(showlegend=False)
                    st.plotly_chart(fig_v, use_container_width=True)

                st.markdown("<div class='sec-title'>Detalle de snapshots</div>", unsafe_allow_html=True)
                st.dataframe(
                    df_snaps[["Fecha","nombre_csv","total","criticos","en_riesgo","normales","valor_cod_riesgo"]]
                    .rename(columns={"nombre_csv":"CSV","total":"Total","criticos":"Críticos",
                                     "en_riesgo":"En riesgo","normales":"Normales","valor_cod_riesgo":"COD $"}),
                    use_container_width=True, hide_index=True, height=200,
                )

    # ── Fila 1: Donuts ──────────────────────────────────────────────────────────
    with st.expander("🎯 Resumen de riesgo", expanded=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("<div class='sec-title'>Por nivel</div>", unsafe_allow_html=True)
            nc = df_all["Nivel"].value_counts().reindex(["CRITICO","RIESGO","NORMAL"]).fillna(0)
            fig_d1 = go.Figure(go.Pie(
                labels=nc.index, values=nc.values, hole=0.55,
                marker_colors=[CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR],
                textfont=dict(color="white", size=12),
                hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
            ))
            fig_d1.update_layout(
                plot_bgcolor="white", paper_bgcolor="white",
                margin=dict(l=0,r=0,t=10,b=0), height=220,
                showlegend=True,
                legend=dict(orientation="h", y=-0.08, font=dict(color=GRAPHITE_GREY, size=11)),
                annotations=[dict(text=f"<b>{total}</b>", x=0.5, y=0.5,
                                  font_size=18, font_color=DEEP_INK, showarrow=False)],
            )
            st.plotly_chart(fig_d1, use_container_width=True)

        with col2:
            st.markdown("<div class='sec-title'>COD vs Pago previo</div>", unsafe_allow_html=True)
            tc = df_all["COD"].map({"SÍ":"COD","—":"Pago previo"}).value_counts()
            fig_d2 = go.Figure(go.Pie(
                labels=tc.index, values=tc.values, hole=0.55,
                marker_colors=[COD_COLOR, STEEL_BLUE],
                textfont=dict(color="white", size=12),
                hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
            ))
            fig_d2.update_layout(
                plot_bgcolor="white", paper_bgcolor="white",
                margin=dict(l=0,r=0,t=10,b=0), height=220, showlegend=True,
                legend=dict(orientation="h", y=-0.08, font=dict(color=GRAPHITE_GREY, size=11)),
            )
            st.plotly_chart(fig_d2, use_container_width=True)

        with col3:
            st.markdown("<div class='sec-title'>Cumplimiento SLA</div>", unsafe_allow_html=True)
            dentro = len(df_all[df_all["Días sobre SLA"] <= 0])
            fuera  = len(df_all[df_all["Días sobre SLA"] > 0])
            fig_d3 = go.Figure(go.Pie(
                labels=["Dentro de SLA","Fuera de SLA"],
                values=[dentro, fuera], hole=0.55,
                marker_colors=[NORMAL_COLOR, CRITICO_COLOR],
                textfont=dict(color="white", size=12),
                hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
            ))
            fig_d3.update_layout(
                plot_bgcolor="white", paper_bgcolor="white",
                margin=dict(l=0,r=0,t=10,b=0), height=220, showlegend=True,
                legend=dict(orientation="h", y=-0.08, font=dict(color=GRAPHITE_GREY, size=11)),
            )
            st.plotly_chart(fig_d3, use_container_width=True)

    # ── Fila 2: Por zona ────────────────────────────────────────────────────────
    with st.expander("🗺️ Por zona", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<div class='sec-title'>Pedidos por zona y nivel</div>", unsafe_allow_html=True)
            zn = (df_all.groupby(["Zona","Nivel"]).size().reset_index(name="Pedidos"))
            zn["Nivel"] = pd.Categorical(zn["Nivel"], ["CRITICO","RIESGO","NORMAL"], ordered=True)
            fig_z2 = px.bar(zn, y="Zona", x="Pedidos", color="Nivel",
                            color_discrete_map=COLOR_NIVEL, orientation="h",
                            barmode="stack", height=260)
            fig_z2 = _lay(fig_z2, 260)
            fig_z2.update_layout(legend=dict(orientation="h", y=1.12,
                                 font=dict(color=GRAPHITE_GREY, size=11)))
            st.plotly_chart(fig_z2, use_container_width=True)

        with col2:
            st.markdown("<div class='sec-title'>Días promedio por zona</div>", unsafe_allow_html=True)
            dz = df_all.groupby("Zona")["Días"].mean().sort_values(ascending=True).reset_index()
            dz.columns = ["Zona","Días prom"]
            dz["color"] = dz["Días prom"].apply(
                lambda d: CRITICO_COLOR if d > 10 else (RIESGO_COLOR if d > 6 else NORMAL_COLOR))
            fig_dz = px.bar(dz, y="Zona", x="Días prom", color="color",
                            color_discrete_map="identity", orientation="h", height=260,
                            text=dz["Días prom"].round(1).astype(str)+"d")
            fig_dz.update_traces(textposition="outside",
                                 textfont=dict(color=GRAPHITE_GREY, size=11))
            fig_dz = _lay(fig_dz, 260)
            fig_dz.update_layout(showlegend=False)
            st.plotly_chart(fig_dz, use_container_width=True)

    # ── Fila 3: Transportadoras ─────────────────────────────────────────────────
    with st.expander("🚚 Transportadoras", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<div class='sec-title'>Volumen total</div>", unsafe_allow_html=True)
            tv = (df_all.groupby("Transportadora").size()
                  .sort_values(ascending=True).reset_index(name="Pedidos"))
            fig_tv = px.bar(tv, y="Transportadora", x="Pedidos",
                            orientation="h", height=280,
                            color_discrete_sequence=[STEEL_BLUE], text="Pedidos")
            fig_tv.update_traces(textposition="outside",
                                 textfont=dict(color=GRAPHITE_GREY, size=11))
            fig_tv = _lay(fig_tv, 280)
            fig_tv.update_layout(showlegend=False)
            st.plotly_chart(fig_tv, use_container_width=True)

        with col2:
            st.markdown("<div class='sec-title'>Excepciones por transportadora</div>", unsafe_allow_html=True)
            te2 = (df_all[df_all["Nivel"].isin(["CRITICO","RIESGO"])]
                   .groupby(["Transportadora","Nivel"]).size().reset_index(name="Pedidos"))
            te2["Nivel"] = pd.Categorical(te2["Nivel"], ["CRITICO","RIESGO"], ordered=True)
            fig_te2 = px.bar(te2, y="Transportadora", x="Pedidos", color="Nivel",
                             color_discrete_map=COLOR_NIVEL, orientation="h",
                             barmode="stack", height=280)
            fig_te2 = _lay(fig_te2, 280)
            fig_te2.update_layout(legend=dict(orientation="h", y=1.12,
                                  font=dict(color=GRAPHITE_GREY, size=11)))
            st.plotly_chart(fig_te2, use_container_width=True)

    # ── Fila 4: Tiempo en tránsito ──────────────────────────────────────────────
    with st.expander("⏱️ Tiempo en tránsito", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<div class='sec-title'>Distribución de días</div>", unsafe_allow_html=True)
            fig_h = px.histogram(df_all, x="Días", nbins=20,
                                 color_discrete_sequence=[STEEL_BLUE], height=260)
            fig_h.update_traces(marker_line_color="white", marker_line_width=1)
            fig_h = _lay(fig_h, 260)
            fig_h.update_layout(bargap=0.05,
                                xaxis_title="Días en tránsito",
                                yaxis_title="Pedidos")
            st.plotly_chart(fig_h, use_container_width=True)

        with col2:
            st.markdown("<div class='sec-title'>Rango por nivel</div>", unsafe_allow_html=True)
            fig_b = px.box(df_all, x="Nivel", y="Días", color="Nivel",
                           color_discrete_map=COLOR_NIVEL,
                           category_orders={"Nivel":["CRITICO","RIESGO","NORMAL"]},
                           height=260)
            fig_b = _lay(fig_b, 260)
            fig_b.update_layout(showlegend=False,
                                xaxis_title="", yaxis_title="Días en tránsito")
            st.plotly_chart(fig_b, use_container_width=True)

    # ── Fila 5: Ciudades y novedades ────────────────────────────────────────────
    with st.expander("📍 Ciudades y novedades", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<div class='sec-title'>Top 10 ciudades</div>", unsafe_allow_html=True)
            ciu = (df_all.groupby("Ciudad").size()
                   .sort_values(ascending=True).tail(10).reset_index(name="Pedidos"))
            fig_ciu = px.bar(ciu, y="Ciudad", x="Pedidos", orientation="h",
                             height=300, color_discrete_sequence=[DEEP_INK], text="Pedidos")
            fig_ciu.update_traces(textposition="outside",
                                  textfont=dict(color=GRAPHITE_GREY, size=11))
            fig_ciu = _lay(fig_ciu, 300)
            fig_ciu.update_layout(showlegend=False)
            st.plotly_chart(fig_ciu, use_container_width=True)

        with col2:
            st.markdown("<div class='sec-title'>Novedades frecuentes</div>", unsafe_allow_html=True)
            nov2 = (df_all[df_all["Novedad"] != "NINGUNO"]["Novedad"]
                    .value_counts().head(10)
                    .sort_values(ascending=True).reset_index())
            nov2.columns = ["Novedad","Cantidad"]
            if not nov2.empty:
                fig_nov2 = px.bar(nov2, y="Novedad", x="Cantidad", orientation="h",
                                  height=300, color_discrete_sequence=[RIESGO_COLOR],
                                  text="Cantidad")
                fig_nov2.update_traces(textposition="outside",
                                       textfont=dict(color=GRAPHITE_GREY, size=11))
                fig_nov2 = _lay(fig_nov2, 300)
                fig_nov2.update_layout(showlegend=False)
                st.plotly_chart(fig_nov2, use_container_width=True)
            else:
                st.info("Sin novedades registradas.")

    # ── Fila 6: COD en riesgo ────────────────────────────────────────────────────
    with st.expander("💸 Valor COD en riesgo", expanded=False):
        df_cod2 = df_all[df_all["COD"] == "SÍ"].copy()
        df_cod2["Valor $"] = df_cod2["Valor COD"].apply(_parse_cod)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<div class='sec-title'>Por zona y nivel</div>", unsafe_allow_html=True)
            cv = (df_cod2.groupby(["Zona","Nivel"])["Valor $"].sum().reset_index())
            cv["Nivel"] = pd.Categorical(cv["Nivel"], ["CRITICO","RIESGO","NORMAL"], ordered=True)
            fig_cv = px.bar(cv, y="Zona", x="Valor $", color="Nivel",
                            color_discrete_map=COLOR_NIVEL, orientation="h",
                            barmode="stack", height=240)
            fig_cv = _lay(fig_cv, 240)
            fig_cv.update_layout(legend=dict(orientation="h", y=1.12,
                                 font=dict(color=GRAPHITE_GREY, size=11)),
                                 xaxis_tickformat="$,.0f")
            st.plotly_chart(fig_cv, use_container_width=True)

        with col2:
            st.markdown("<div class='sec-title'>Por transportadora (excepciones)</div>",
                        unsafe_allow_html=True)
            ce = (df_cod2[df_cod2["Nivel"].isin(["CRITICO","RIESGO"])]
                  .groupby("Transportadora")["Valor $"]
                  .sum().sort_values(ascending=True).reset_index())
            if not ce.empty:
                fig_ce = px.bar(ce, y="Transportadora", x="Valor $",
                                orientation="h", height=240,
                                color_discrete_sequence=[CRITICO_COLOR])
                fig_ce = _lay(fig_ce, 240)
                fig_ce.update_layout(showlegend=False, xaxis_tickformat="$,.0f")
                st.plotly_chart(fig_ce, use_container_width=True)
            else:
                st.success("✅ Sin COD en excepción.")
