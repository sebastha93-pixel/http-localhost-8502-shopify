"""
Módulo Logística — MALE'DENIM
Tres vistas operativas:
  1. COD — Pendientes por despachar
  2. COD — En tránsito (seguimiento hasta entrega/cobro)
  3. Novedades — Problemas activos (COD + Prepago)
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

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except Exception:
    pass

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR, VENCIDO_COLOR,
    MAX_DIAS_ACTIVO,
    cargar_datos_api, render_sidebar, render_detalle, _parse_cod, render_tabla,
)
from memoria import (
    disponible as mem_ok, guardar_snapshot,
    cargar_snapshots, historial_pedido,
    cargar_notas, agregar_nota,
    cargar_acciones, agregar_accion, TIPOS_ACCION,
)

st.markdown(CSS, unsafe_allow_html=True)

# ── Guard de permisos ──────────────────────────────────────────────────────────
if "logistica" not in st.session_state.get("permisos", ["logistica"]):
    st.error("🔒 No tienes acceso al módulo de Logística.")
    st.stop()

# ── Helpers ────────────────────────────────────────────────────────────────────
COLOR_NIVEL = {
    "CRITICO": CRITICO_COLOR,
    "RIESGO":  RIESGO_COLOR,
    "NORMAL":  NORMAL_COLOR,
    "VENCIDO": VENCIDO_COLOR,
}
FONT = dict(family="Arial, sans-serif", size=12, color=GRAPHITE_GREY)

NOVEDAD_ES = {
    "Delivery not posible":                                          "Entrega no posible",
    "Packed - on hold":                                             "Paquete retenido",
    "All items reserved - fulfillment on hold - ext. conditionals": "Fulfillment en espera",
    "on stand by - not able to fulfil - no stock":                  "Sin stock",
}

def _lay(fig, h=280):
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=10, t=30, b=0), font=FONT, height=h,
    )
    fig.update_xaxes(tickfont=dict(color=GRAPHITE_GREY), gridcolor="#f0ede8", zeroline=False)
    fig.update_yaxes(tickfont=dict(color=GRAPHITE_GREY), gridcolor="#f0ede8", zeroline=False)
    return fig

def _fmt_m(v):
    if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
    if v >= 1_000:     return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"

def _kpi(num, label, sub, bg=DEEP_INK, border=STEEL_BLUE):
    return f"""<div class="kpi-card" style="background:{bg};border-left:4px solid {border};">
        <p class="kpi-num">{num}</p>
        <p class="kpi-label">{label}</p>
        <p class="kpi-sub">{sub}</p>
    </div>"""


def _render_memoria(orden: str):
    """Trazabilidad: historial, acciones y notas de un pedido."""
    if not mem_ok():
        st.caption("ℹ️ Conecta Supabase para activar la memoria.")
        return

    st.markdown(
        f"<div class='sec-title' style='margin-top:16px;'>🧠 TRAZABILIDAD — {orden}</div>",
        unsafe_allow_html=True,
    )
    col_h, col_acc, col_nota = st.columns([1.4, 1.3, 1.3])

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

    with col_acc:
        st.markdown("**⚡ Acciones registradas**")
        _k = f"_msg_accion_{orden}"
        if _k in st.session_state:
            ok, msg = st.session_state.pop(_k)
            (st.success if ok else st.error)(msg, icon="✅" if ok else "❌")
        df_ac = cargar_acciones(orden)
        if not df_ac.empty:
            for _, r in df_ac.iterrows():
                ts = r["creada_en"].strftime("%d/%m %H:%M") if pd.notna(r["creada_en"]) else ""
                st.markdown(
                    f"<div style='background:white;border-left:3px solid {STEEL_BLUE};"
                    f"padding:6px 10px;margin-bottom:4px;border-radius:3px;font-size:0.8rem;'>"
                    f"<b>{r['tipo']}</b> · {r['autor']} · {ts}<br>"
                    f"<span style='color:{GRAPHITE_GREY};'>{r['descripcion']}</span></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Sin acciones registradas.")
        with st.form(key=f"form_accion_{orden}", clear_on_submit=True):
            tipo_ac  = st.selectbox("Tipo", TIPOS_ACCION, label_visibility="collapsed")
            desc_ac  = st.text_input("Descripción", placeholder="Descripción…", label_visibility="collapsed")
            autor_ac = st.text_input("Quién", placeholder="Tu nombre", label_visibility="collapsed")
            if st.form_submit_button("➕ Registrar acción", use_container_width=True):
                if desc_ac.strip():
                    ok, err = agregar_accion(orden, tipo_ac, desc_ac, autor_ac)
                    st.session_state[_k] = (ok, "Acción guardada" if ok else f"Error: {err}")
                    st.rerun()
                else:
                    st.warning("Escribe una descripción.")

    with col_nota:
        st.markdown("**📝 Notas del equipo**")
        _kn = f"_msg_nota_{orden}"
        if _kn in st.session_state:
            ok, msg = st.session_state.pop(_kn)
            (st.success if ok else st.error)(msg, icon="✅" if ok else "❌")
        df_n = cargar_notas(orden)
        if not df_n.empty:
            for _, r in df_n.iterrows():
                ts = r["creada_en"].strftime("%d/%m %H:%M") if pd.notna(r["creada_en"]) else ""
                st.markdown(
                    f"<div style='background:white;border-left:3px solid {NORMAL_COLOR};"
                    f"padding:6px 10px;margin-bottom:4px;border-radius:3px;font-size:0.8rem;'>"
                    f"<b>{r['autor']}</b> · {ts}<br>"
                    f"<span style='color:{GRAPHITE_GREY};'>{r['nota']}</span></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Sin notas aún.")
        with st.form(key=f"form_nota_{orden}", clear_on_submit=True):
            nota_txt = st.text_area("Nota", placeholder="Escribe una nota…",
                                    height=68, label_visibility="collapsed")
            autor_n  = st.text_input("Quién", placeholder="Tu nombre", label_visibility="collapsed")
            if st.form_submit_button("💬 Agregar nota", use_container_width=True):
                if nota_txt.strip():
                    ok, err = agregar_nota(orden, autor_n, nota_txt)
                    st.session_state[_kn] = (ok, "Nota guardada" if ok else f"Error: {err}")
                    st.rerun()
                else:
                    st.warning("Escribe una nota.")


# ── Sidebar ────────────────────────────────────────────────────────────────────
activo, filtro_nivel, filtro_zona = render_sidebar("Logística")

# ── Cargar datos ───────────────────────────────────────────────────────────────
try:
    df_all, omitidos, _meta = cargar_datos_api()
except Exception as e:
    st.error(f"❌ Error inesperado cargando datos: {e}")
    st.stop()

if df_all.empty:
    st.markdown(f"""
    <div style="background:white;border-radius:10px;padding:40px;text-align:center;
                max-width:500px;margin:40px auto;box-shadow:0 2px 12px rgba(0,0,0,0.06);">
        <div style="font-size:2rem;margin-bottom:12px;">📡</div>
        <div style="font-size:1rem;font-weight:700;color:{DEEP_INK};">Sin datos de Melonn</div>
        <div style="font-size:0.82rem;color:#606060;margin-top:8px;line-height:1.6;">
            La API está temporalmente no disponible.<br>
            Presiona <b>↻ Actualizar datos</b> en el sidebar para reintentar.
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

_fuente = _meta.get("fuente", "")
_fa     = _meta.get("fetched_at")
_fa_txt = _fa.strftime("%d/%m/%Y %H:%M") if _fa else ""
if _fuente in ("csv_bootstrap", "stale"):
    st.warning(
        f"⚠️ Mostrando datos del {_fa_txt} (caché). "
        "Presiona **↻ Actualizar datos** para sincronizar con Melonn.",
        icon="⚠️",
    )

ts = _fa_txt or "api"

# ── Segmentación operativa ─────────────────────────────────────────────────────
#
# Solo llegan pedidos que ya pasaron el filtro en melonn_client:
#   • COD:    todos los estados no resueltos
#   • Prepago: solo los que tienen una novedad activa
#
# Aquí los dividimos por sub_estado_logistico (columna "Sub_Estado")
#
df_cod = df_all[df_all["Tipo_Recaudo"] == "Contraentrega"].copy()
df_pre = df_all[df_all["Tipo_Recaudo"] == "Prepago"].copy()       # solo tiene novedades

# COD → pendientes por despachar (en bodega, aún no enviados)
df_cod_pendiente = df_cod[df_cod["Sub_Estado"] == "pendiente_despacho"].copy()

# COD → despachados, seguimiento hasta entrega y cobro
df_cod_transito  = df_cod[df_cod["Sub_Estado"].isin(["en_transito", "novedad", "otro"])].copy()

# Pedidos con novedad activa (COD + Prepago)
df_novedades = df_all[df_all["Sub_Estado"] == "novedad"].copy()

# Sub-conjuntos para métricas
df_cod_transito_activo = df_cod_transito[df_cod_transito["Nivel"] != "VENCIDO"]
df_vencido             = df_cod_transito[df_cod_transito["Nivel"] == "VENCIDO"]

# KPIs globales
n_pendientes  = len(df_cod_pendiente)
n_transito    = len(df_cod_transito_activo)
n_novedades   = len(df_novedades)
n_vencidos    = len(df_vencido)
n_criticos    = len(df_cod_transito_activo[df_cod_transito_activo["Nivel"] == "CRITICO"])
n_riesgo      = len(df_cod_transito_activo[df_cod_transito_activo["Nivel"] == "RIESGO"])
val_cod_total = df_cod["Valor COD"].apply(_parse_cod).sum()
val_cod_riesgo = (
    df_cod_transito_activo[df_cod_transito_activo["Nivel"].isin(["CRITICO","RIESGO"])]
    ["Valor COD"].apply(_parse_cod).sum()
)

# Aplicar filtros del sidebar (solo a vistas operativas, no a VENCIDO)
def _aplicar_filtros(df):
    d = df.copy()
    if filtro_nivel:
        d = d[d["Nivel"].isin(filtro_nivel)]
    if filtro_zona:
        d = d[d["Zona"].isin(filtro_zona)]
    return d

df_cod_pend_f  = _aplicar_filtros(df_cod_pendiente)
df_cod_tran_f  = _aplicar_filtros(df_cod_transito)
df_novedades_f = _aplicar_filtros(df_novedades)

# ── Encabezado ─────────────────────────────────────────────────────────────────
st.markdown(f"""
    <p class="titulo-panel">📦 LOGÍSTICA</p>
    <p class="subtitulo">Trazabilidad operativa · MALE'DENIM · {ts}</p>
    <hr style='margin:10px 0;'>
""", unsafe_allow_html=True)

# ── KPIs globales ──────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.markdown(_kpi(n_pendientes, "PENDIENTES DESPACHO", "COD en bodega",
                     bg=DEEP_INK, border=STEEL_BLUE), unsafe_allow_html=True)
with k2:
    color_tr = CRITICO_COLOR if n_criticos > 0 else (RIESGO_COLOR if n_riesgo > 0 else NORMAL_COLOR)
    st.markdown(_kpi(n_transito, "EN TRÁNSITO · COD",
                     f"{n_criticos} críticos · {n_riesgo} en riesgo",
                     bg=DEEP_INK, border=color_tr), unsafe_allow_html=True)
with k3:
    st.markdown(_kpi(n_novedades, "NOVEDADES ACTIVAS",
                     f"{len(df_pre)} prepago · {len(df_novedades[df_novedades['Tipo_Recaudo']=='Contraentrega'])} COD",
                     bg=CRITICO_COLOR if n_novedades > 0 else DEEP_INK,
                     border=CRITICO_COLOR), unsafe_allow_html=True)
with k4:
    st.markdown(_kpi(_fmt_m(val_cod_riesgo), "COD EN RIESGO",
                     "Recaudo comprometido",
                     bg=DEEP_INK, border=COD_COLOR), unsafe_allow_html=True)
with k5:
    st.markdown(_kpi(n_vencidos, "SIN CONFIRMAR",
                     f">{MAX_DIAS_ACTIVO}d · verificar",
                     bg=VENCIDO_COLOR, border="#909090"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── TABS ───────────────────────────────────────────────────────────────────────
tab_pend, tab_tran, tab_nov, tab_ana = st.tabs([
    f"📦  Pendientes despacho  ({len(df_cod_pend_f)})",
    f"🚚  En tránsito · COD  ({len(df_cod_tran_f)})",
    f"⚠️  Novedades  ({len(df_novedades_f)})",
    "📊  Análisis",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — PENDIENTES POR DESPACHAR (COD)
# ══════════════════════════════════════════════════════════════════════════════
with tab_pend:
    st.caption(
        "Pedidos contraentrega confirmados en bodega Melonn — aún no despachados. "
        "Acá debes asegurarte de que salgan a tiempo para cumplir la promesa de entrega."
    )

    if df_cod_pend_f.empty:
        st.success("✅ Sin pedidos pendientes de despacho en este momento.")
    else:
        # KPIs del tab
        p1, p2, p3, p4 = st.columns(4)
        val_pend = df_cod_pend_f["Valor COD"].apply(_parse_cod).sum()
        with p1:
            st.markdown(_kpi(len(df_cod_pend_f), "PENDIENTES",
                             "Por salir de bodega"), unsafe_allow_html=True)
        with p2:
            st.markdown(_kpi(_fmt_m(val_pend), "VALOR COD",
                             "Portafolio pendiente", border=COD_COLOR), unsafe_allow_html=True)
        with p3:
            n_packed = len(df_cod_pend_f[df_cod_pend_f["Estado"].str.contains("Empacado|reservado|Listo", case=False, na=False)])
            st.markdown(_kpi(n_packed, "EMPACADOS / LISTOS",
                             "Listos para despachar", border=NORMAL_COLOR), unsafe_allow_html=True)
        with p4:
            n_hold = len(df_cod_pend_f[df_cod_pend_f["Estado"].str.contains("espera|hold|stock", case=False, na=False)])
            color_hold = RIESGO_COLOR if n_hold > 0 else DEEP_INK
            st.markdown(_kpi(n_hold, "EN ESPERA / SIN STOCK",
                             "Requieren atención", border=color_hold), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        COLS_PEND = ["Orden", "Cliente", "Teléfono", "Ciudad", "Zona",
                     "Estado", "Valor COD", "Transportadora", "F. Creación", "Link Melonn"]
        COLS_PEND = [c for c in COLS_PEND if c in df_cod_pend_f.columns]

        st.markdown("<div class='sec-title'>Lista de trabajo — pendientes</div>", unsafe_allow_html=True)
        render_tabla(df_cod_pend_f, COLS_PEND, key="tabla_pend", height=420)

        hay_sel = bool(st.session_state.get("tabla_pend", {}).get("selection", {}).get("rows"))
        with st.expander("Detalle del pedido", expanded=hay_sel):
            if not hay_sel:
                st.caption("Selecciona una fila para ver el detalle.")
            else:
                render_detalle(df_cod_pend_f, tab_key="pend")
                rows = st.session_state.get("tabla_pend", {}).get("selection", {}).get("rows", [])
                if rows:
                    _render_memoria(str(df_cod_pend_f.iloc[rows[0]]["Orden"]))

        st.markdown("<br>", unsafe_allow_html=True)
        st.download_button(
            "⬇️ Descargar pendientes (.CSV)",
            data=df_cod_pend_f.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"maledenim_pendientes_{date.today()}.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — EN TRÁNSITO · COD
# ══════════════════════════════════════════════════════════════════════════════
with tab_tran:
    st.caption(
        "Pedidos contraentrega ya despachados — en camino al cliente. "
        "Seguimiento de riesgo hasta la entrega y el cobro del COD."
    )

    df_t = df_cod_tran_f.copy()
    df_t_activo  = df_t[df_t["Nivel"] != "VENCIDO"]
    df_t_vencido = df_t[df_t["Nivel"] == "VENCIDO"]

    n_crit = len(df_t_activo[df_t_activo["Nivel"] == "CRITICO"])
    n_ries = len(df_t_activo[df_t_activo["Nivel"] == "RIESGO"])
    n_norm = len(df_t_activo[df_t_activo["Nivel"] == "NORMAL"])
    n_venc = len(df_t_vencido)
    val_t  = df_t_activo["Valor COD"].apply(_parse_cod).sum()
    val_t_riesgo = (
        df_t_activo[df_t_activo["Nivel"].isin(["CRITICO","RIESGO"])]
        ["Valor COD"].apply(_parse_cod).sum()
    )

    t1, t2, t3, t4, t5 = st.columns(5)
    with t1:
        st.markdown(f"""<div class="kpi-card kpi-crit">
            <p class="kpi-num">{n_crit}</p><p class="kpi-label">CRÍTICO</p>
            <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
    with t2:
        st.markdown(f"""<div class="kpi-card kpi-ries">
            <p class="kpi-num">{n_ries}</p><p class="kpi-label">EN RIESGO</p>
            <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
    with t3:
        st.markdown(f"""<div class="kpi-card kpi-norm">
            <p class="kpi-num">{n_norm}</p><p class="kpi-label">NORMAL</p>
            <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
    with t4:
        st.markdown(_kpi(_fmt_m(val_t_riesgo), "COD EN RIESGO",
                         "Recaudo comprometido", border=COD_COLOR), unsafe_allow_html=True)
    with t5:
        st.markdown(_kpi(n_venc, "SIN CONFIRMAR",
                         f">{MAX_DIAS_ACTIVO}d sin actualizar",
                         bg=VENCIDO_COLOR, border="#909090"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if df_t_activo.empty and df_t_vencido.empty:
        st.success("✅ Sin pedidos COD en tránsito con los filtros seleccionados.")
    else:
        COLS_T = ["Prioridad", "Nivel", "Score", "Orden", "Cliente", "Teléfono",
                  "Ciudad", "Zona", "Días", "Días sobre SLA", "Valor COD",
                  "Transportadora", "Estado", "Motivo riesgo", "F. Despacho", "Link Melonn"]
        COLS_T = [c for c in COLS_T if c in df_t.columns]

        st.markdown("<div class='sec-title'>Lista de trabajo — en tránsito</div>", unsafe_allow_html=True)
        render_tabla(df_t, COLS_T, key="tabla_tran", height=420)

        hay_sel_t = bool(st.session_state.get("tabla_tran", {}).get("selection", {}).get("rows"))
        with st.expander("Detalle del pedido", expanded=hay_sel_t):
            if not hay_sel_t:
                st.caption("Selecciona una fila para ver el detalle.")
            else:
                render_detalle(df_t, tab_key="tran")
                rows = st.session_state.get("tabla_tran", {}).get("selection", {}).get("rows", [])
                if rows:
                    _render_memoria(str(df_t.iloc[rows[0]]["Orden"]))

        # Pedidos sin confirmar entrega
        if n_venc > 0:
            with st.expander(
                f"📋 Sin confirmar entrega — {n_venc} pedidos (>{MAX_DIAS_ACTIVO}d sin actualizar)",
                expanded=False,
            ):
                st.caption(
                    f"Llevan más de {MAX_DIAS_ACTIVO} días despachados sin confirmación de entrega en Melonn. "
                    "Probablemente entregados sin actualizar estado. Verifica con el cliente o la guía."
                )
                COLS_V = ["Orden", "Cliente", "Teléfono", "Ciudad", "Zona", "Días",
                          "Valor COD", "Transportadora", "F. Despacho", "Link Melonn"]
                COLS_V = [c for c in COLS_V if c in df_t_vencido.columns]
                st.dataframe(
                    df_t_vencido[COLS_V],
                    use_container_width=True, height=260, hide_index=True,
                    column_config={
                        "Días":       st.column_config.NumberColumn("Días", format="%d"),
                        "Link Melonn": st.column_config.LinkColumn("Guía", display_text="Ver"),
                    },
                )
                st.download_button(
                    "⬇️ Descargar sin confirmar (.CSV)",
                    data=df_t_vencido[COLS_V].to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"maledenim_sin_confirmar_{date.today()}.csv",
                    mime="text/csv",
                )

        st.markdown("<br>", unsafe_allow_html=True)
        st.download_button(
            "⬇️ Descargar en tránsito COD (.CSV)",
            data=df_t.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"maledenim_transito_cod_{date.today()}.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — NOVEDADES ACTIVAS (COD + PREPAGO)
# ══════════════════════════════════════════════════════════════════════════════
with tab_nov:
    st.caption(
        "Todos los pedidos con una novedad activa de entrega — requieren gestión. "
        "COD: riesgo de no cobro. Prepago: cliente ya pagó y la entrega falló."
    )

    df_n = df_novedades_f.copy()

    if df_n.empty:
        st.success("✅ Sin novedades activas en este momento.")
    else:
        df_n_cod  = df_n[df_n["Tipo_Recaudo"] == "Contraentrega"]
        df_n_pre  = df_n[df_n["Tipo_Recaudo"] == "Prepago"]

        val_cod_nov = df_n_cod["Valor COD"].apply(_parse_cod).sum()

        n1, n2, n3, n4 = st.columns(4)
        with n1:
            st.markdown(_kpi(len(df_n), "NOVEDADES TOTALES",
                             "Requieren gestión",
                             bg=CRITICO_COLOR, border=CRITICO_COLOR), unsafe_allow_html=True)
        with n2:
            st.markdown(_kpi(len(df_n_cod), "COD CON NOVEDAD",
                             _fmt_m(val_cod_nov) + " en riesgo",
                             border=COD_COLOR), unsafe_allow_html=True)
        with n3:
            st.markdown(_kpi(len(df_n_pre), "PREPAGO CON NOVEDAD",
                             "Cliente ya pagó",
                             border=RIESGO_COLOR), unsafe_allow_html=True)
        with n4:
            tipo_mas_comun = (
                df_n["Estado"].value_counts().index[0]
                if not df_n.empty else "—"
            )
            novedad_label = NOVEDAD_ES.get(tipo_mas_comun, tipo_mas_comun)
            st.markdown(_kpi(df_n["Estado"].nunique(), "TIPOS DE NOVEDAD",
                             novedad_label[:28],
                             border=RIESGO_COLOR), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── COD con novedad ──────────────────────────────────────────────────
        if not df_n_cod.empty:
            st.markdown(
                f"<div class='sec-title' style='border-left:3px solid {COD_COLOR};padding-left:10px;'>"
                f"💰 Contra Entrega — {len(df_n_cod)} novedades"
                f"&nbsp;&nbsp;<span style='font-weight:400;color:{GRAPHITE_GREY};font-size:0.72rem;'>"
                f"{_fmt_m(val_cod_nov)} en riesgo de no cobro</span></div>",
                unsafe_allow_html=True,
            )
            COLS_NC = ["Nivel", "Orden", "Cliente", "Teléfono", "Ciudad", "Zona",
                       "Días", "Valor COD", "Estado", "Transportadora",
                       "F. Despacho", "Link Melonn"]
            COLS_NC = [c for c in COLS_NC if c in df_n_cod.columns]
            render_tabla(df_n_cod, COLS_NC, key="tabla_nov_cod", height=320)

            hay_sel_nc = bool(st.session_state.get("tabla_nov_cod", {}).get("selection", {}).get("rows"))
            with st.expander("Detalle — COD novedad", expanded=hay_sel_nc):
                if not hay_sel_nc:
                    st.caption("Selecciona una fila para ver el detalle.")
                else:
                    render_detalle(df_n_cod, tab_key="nov_cod")
                    rows = st.session_state.get("tabla_nov_cod", {}).get("selection", {}).get("rows", [])
                    if rows:
                        _render_memoria(str(df_n_cod.iloc[rows[0]]["Orden"]))

        # ── Prepago con novedad ───────────────────────────────────────────────
        if not df_n_pre.empty:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='sec-title' style='border-left:3px solid {RIESGO_COLOR};padding-left:10px;'>"
                f"✅ Pago Previo — {len(df_n_pre)} novedades"
                f"&nbsp;&nbsp;<span style='font-weight:400;color:{GRAPHITE_GREY};font-size:0.72rem;'>"
                f"Cliente pagó · entrega fallida</span></div>",
                unsafe_allow_html=True,
            )
            COLS_NP = ["Nivel", "Orden", "Cliente", "Teléfono", "Ciudad", "Zona",
                       "Días", "Estado", "Transportadora",
                       "F. Despacho", "Link Melonn"]
            COLS_NP = [c for c in COLS_NP if c in df_n_pre.columns]
            render_tabla(df_n_pre, COLS_NP, key="tabla_nov_pre", height=320)

            hay_sel_np = bool(st.session_state.get("tabla_nov_pre", {}).get("selection", {}).get("rows"))
            with st.expander("Detalle — Prepago novedad", expanded=hay_sel_np):
                if not hay_sel_np:
                    st.caption("Selecciona una fila para ver el detalle.")
                else:
                    render_detalle(df_n_pre, tab_key="nov_pre")
                    rows = st.session_state.get("tabla_nov_pre", {}).get("selection", {}).get("rows", [])
                    if rows:
                        _render_memoria(str(df_n_pre.iloc[rows[0]]["Orden"]))

        st.markdown("<br>", unsafe_allow_html=True)
        st.download_button(
            "⬇️ Descargar novedades (.CSV)",
            data=df_n.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"maledenim_novedades_{date.today()}.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — ANÁLISIS
# ══════════════════════════════════════════════════════════════════════════════
with tab_ana:
    st.markdown(
        "<div class='sec-title' style='margin-top:0;'>Visualizaciones operativas</div>",
        unsafe_allow_html=True,
    )

    # Referencia: pedidos COD en tránsito activos (excluye VENCIDO y pendientes)
    df_ref = df_cod_transito_activo.copy()

    # ── Tendencias históricas ───────────────────────────────────────────────────
    with st.expander("📈 Tendencias históricas", expanded=mem_ok()):
        if not mem_ok():
            st.info("Conecta Supabase para ver la evolución a lo largo del tiempo.")
        else:
            df_snaps = cargar_snapshots(30)
            if df_snaps.empty:
                st.caption("Aún no hay snapshots guardados.")
            else:
                df_snaps = df_snaps.sort_values("cargado_en")
                df_snaps["Fecha"] = df_snaps["cargado_en"].dt.strftime("%d/%m")
                tc1, tc2 = st.columns(2)
                with tc1:
                    st.markdown("<div class='sec-title'>Evolución de riesgo</div>", unsafe_allow_html=True)
                    fig_t = go.Figure()
                    fig_t.add_trace(go.Scatter(
                        x=df_snaps["Fecha"], y=df_snaps["criticos"],
                        name="Crítico", line=dict(color=CRITICO_COLOR, width=2.5), mode="lines+markers"))
                    fig_t.add_trace(go.Scatter(
                        x=df_snaps["Fecha"], y=df_snaps["en_riesgo"],
                        name="En riesgo", line=dict(color=RIESGO_COLOR, width=2.5), mode="lines+markers"))
                    fig_t.add_trace(go.Scatter(
                        x=df_snaps["Fecha"], y=df_snaps["normales"],
                        name="Normal", line=dict(color=NORMAL_COLOR, width=2), mode="lines+markers"))
                    fig_t = _lay(fig_t, 240)
                    fig_t.update_layout(legend=dict(orientation="h", y=1.1,
                                        font=dict(color=GRAPHITE_GREY, size=11)))
                    st.plotly_chart(fig_t, use_container_width=True)
                with tc2:
                    st.markdown("<div class='sec-title'>Valor COD en riesgo ($)</div>", unsafe_allow_html=True)
                    fig_v = go.Figure(go.Bar(
                        x=df_snaps["Fecha"], y=df_snaps["valor_cod_riesgo"],
                        marker_color=COD_COLOR,
                        text=df_snaps["valor_cod_riesgo"].apply(
                            lambda v: f"${v/1e6:.1f}M" if v >= 1e6 else f"${v/1e3:.0f}K"),
                        textposition="outside",
                        textfont=dict(color=GRAPHITE_GREY, size=11),
                    ))
                    fig_v = _lay(fig_v, 240)
                    fig_v.update_layout(showlegend=False)
                    st.plotly_chart(fig_v, use_container_width=True)

    # ── Riesgo en tránsito COD ──────────────────────────────────────────────────
    with st.expander("🎯 Riesgo en tránsito · COD", expanded=True):
        if df_ref.empty:
            st.info("Sin pedidos COD en tránsito activos.")
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown("<div class='sec-title'>Por nivel de riesgo</div>", unsafe_allow_html=True)
                nc = df_ref["Nivel"].value_counts().reindex(["CRITICO","RIESGO","NORMAL"]).fillna(0)
                fig_d1 = go.Figure(go.Pie(
                    labels=nc.index, values=nc.values, hole=0.55,
                    marker_colors=[CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR],
                    textfont=dict(color="white", size=12),
                    hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
                ))
                fig_d1.update_layout(
                    plot_bgcolor="white", paper_bgcolor="white",
                    margin=dict(l=0,r=0,t=10,b=0), height=220, showlegend=True,
                    legend=dict(orientation="h", y=-0.08, font=dict(color=GRAPHITE_GREY, size=11)),
                    annotations=[dict(text=f"<b>{len(df_ref)}</b>", x=0.5, y=0.5,
                                      font_size=18, font_color=DEEP_INK, showarrow=False)],
                )
                st.plotly_chart(fig_d1, use_container_width=True)

            with col2:
                st.markdown("<div class='sec-title'>Cumplimiento SLA</div>", unsafe_allow_html=True)
                dentro = len(df_ref[df_ref["Días sobre SLA"] <= 0])
                fuera  = len(df_ref[df_ref["Días sobre SLA"] > 0])
                fig_d2 = go.Figure(go.Pie(
                    labels=["Dentro de SLA","Fuera de SLA"],
                    values=[dentro, fuera], hole=0.55,
                    marker_colors=[NORMAL_COLOR, CRITICO_COLOR],
                    textfont=dict(color="white", size=12),
                ))
                fig_d2.update_layout(
                    plot_bgcolor="white", paper_bgcolor="white",
                    margin=dict(l=0,r=0,t=10,b=0), height=220, showlegend=True,
                    legend=dict(orientation="h", y=-0.08, font=dict(color=GRAPHITE_GREY, size=11)),
                )
                st.plotly_chart(fig_d2, use_container_width=True)

            with col3:
                st.markdown("<div class='sec-title'>Por zona</div>", unsafe_allow_html=True)
                zn = df_ref.groupby("Zona").size().sort_values(ascending=True).reset_index(name="Pedidos")
                fig_zn = px.bar(zn, y="Zona", x="Pedidos", orientation="h",
                                height=220, color_discrete_sequence=[STEEL_BLUE], text="Pedidos")
                fig_zn.update_traces(textposition="outside", textfont=dict(color=GRAPHITE_GREY, size=11))
                fig_zn = _lay(fig_zn, 220)
                fig_zn.update_layout(showlegend=False)
                st.plotly_chart(fig_zn, use_container_width=True)

    # ── Transportadoras ─────────────────────────────────────────────────────────
    with st.expander("🚚 Transportadoras", expanded=False):
        if df_ref.empty:
            st.info("Sin datos.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("<div class='sec-title'>Volumen en tránsito COD</div>", unsafe_allow_html=True)
                tv = df_ref.groupby("Transportadora").size().sort_values(ascending=True).reset_index(name="Pedidos")
                fig_tv = px.bar(tv, y="Transportadora", x="Pedidos", orientation="h",
                                height=280, color_discrete_sequence=[STEEL_BLUE], text="Pedidos")
                fig_tv.update_traces(textposition="outside", textfont=dict(color=GRAPHITE_GREY, size=11))
                fig_tv = _lay(fig_tv, 280)
                fig_tv.update_layout(showlegend=False)
                st.plotly_chart(fig_tv, use_container_width=True)
            with col2:
                st.markdown("<div class='sec-title'>Excepciones por transportadora</div>", unsafe_allow_html=True)
                te = (df_ref[df_ref["Nivel"].isin(["CRITICO","RIESGO"])]
                      .groupby(["Transportadora","Nivel"]).size().reset_index(name="Pedidos"))
                if not te.empty:
                    te["Nivel"] = pd.Categorical(te["Nivel"], ["CRITICO","RIESGO"], ordered=True)
                    fig_te = px.bar(te, y="Transportadora", x="Pedidos", color="Nivel",
                                    color_discrete_map=COLOR_NIVEL, orientation="h",
                                    barmode="stack", height=280)
                    fig_te = _lay(fig_te, 280)
                    fig_te.update_layout(legend=dict(orientation="h", y=1.12,
                                         font=dict(color=GRAPHITE_GREY, size=11)))
                    st.plotly_chart(fig_te, use_container_width=True)
                else:
                    st.success("✅ Sin excepciones por transportadora.")

    # ── Tiempo en tránsito ──────────────────────────────────────────────────────
    with st.expander("⏱️ Tiempo en tránsito · COD", expanded=False):
        if df_ref.empty:
            st.info("Sin datos.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("<div class='sec-title'>Distribución de días</div>", unsafe_allow_html=True)
                fig_h = px.histogram(df_ref, x="Días", nbins=15,
                                     color_discrete_sequence=[STEEL_BLUE], height=260)
                fig_h.update_traces(marker_line_color="white", marker_line_width=1)
                fig_h = _lay(fig_h, 260)
                fig_h.update_layout(bargap=0.05, xaxis_title="Días en tránsito", yaxis_title="Pedidos")
                st.plotly_chart(fig_h, use_container_width=True)
            with col2:
                st.markdown("<div class='sec-title'>Rango por nivel de riesgo</div>", unsafe_allow_html=True)
                fig_b = px.box(df_ref, x="Nivel", y="Días", color="Nivel",
                               color_discrete_map=COLOR_NIVEL,
                               category_orders={"Nivel":["CRITICO","RIESGO","NORMAL"]},
                               height=260)
                fig_b = _lay(fig_b, 260)
                fig_b.update_layout(showlegend=False, xaxis_title="", yaxis_title="Días en tránsito")
                st.plotly_chart(fig_b, use_container_width=True)

    # ── Novedades ───────────────────────────────────────────────────────────────
    with st.expander("⚠️ Tipos de novedad", expanded=False):
        if df_novedades.empty:
            st.success("✅ Sin novedades activas.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("<div class='sec-title'>Novedades por tipo</div>", unsafe_allow_html=True)
                nov = (df_novedades["Estado"].map(NOVEDAD_ES).fillna(df_novedades["Estado"])
                       .value_counts().sort_values(ascending=True).reset_index())
                nov.columns = ["Novedad","Cantidad"]
                fig_n = px.bar(nov, y="Novedad", x="Cantidad", orientation="h",
                               height=260, color_discrete_sequence=[CRITICO_COLOR], text="Cantidad")
                fig_n.update_traces(textposition="outside", textfont=dict(color=GRAPHITE_GREY, size=11))
                fig_n = _lay(fig_n, 260)
                fig_n.update_layout(showlegend=False)
                st.plotly_chart(fig_n, use_container_width=True)
            with col2:
                st.markdown("<div class='sec-title'>COD vs Prepago en novedad</div>", unsafe_allow_html=True)
                tc = df_novedades["Tipo_Recaudo"].value_counts()
                fig_tc = go.Figure(go.Pie(
                    labels=tc.index, values=tc.values, hole=0.55,
                    marker_colors=[COD_COLOR, RIESGO_COLOR],
                    textfont=dict(color="white", size=12),
                ))
                fig_tc.update_layout(
                    plot_bgcolor="white", paper_bgcolor="white",
                    margin=dict(l=0,r=0,t=10,b=0), height=260, showlegend=True,
                    legend=dict(orientation="h", y=-0.08, font=dict(color=GRAPHITE_GREY, size=11)),
                )
                st.plotly_chart(fig_tc, use_container_width=True)

    # ── Valor COD en riesgo ──────────────────────────────────────────────────────
    with st.expander("💸 Valor COD en riesgo", expanded=False):
        df_cod2 = df_ref.copy()
        df_cod2["Valor $"] = df_cod2["Valor COD"].apply(_parse_cod)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<div class='sec-title'>Por zona y nivel</div>", unsafe_allow_html=True)
            cv = df_cod2.groupby(["Zona","Nivel"])["Valor $"].sum().reset_index()
            cv["Nivel"] = pd.Categorical(cv["Nivel"], ["CRITICO","RIESGO","NORMAL"], ordered=True)
            fig_cv = px.bar(cv, y="Zona", x="Valor $", color="Nivel",
                            color_discrete_map=COLOR_NIVEL, orientation="h",
                            barmode="stack", height=240)
            fig_cv = _lay(fig_cv, 240)
            fig_cv.update_layout(
                legend=dict(orientation="h", y=1.12, font=dict(color=GRAPHITE_GREY, size=11)),
                xaxis_tickformat="$,.0f",
            )
            st.plotly_chart(fig_cv, use_container_width=True)
        with col2:
            st.markdown("<div class='sec-title'>Por transportadora (excepciones)</div>", unsafe_allow_html=True)
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
