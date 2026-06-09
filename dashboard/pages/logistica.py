"""
Módulo Logística — MALE'DENIM

Tab 📦 Contraentrega  (D2C COD únicamente, sin B2B)
  ⏳ Pendientes despacho  → código 26 · seller debe autorizar
  🚚 En tránsito          → códigos 5,7,24,28 · en bodega o con transportadora
  ⚠️ Novedades            → novedades externas (transportadora)
  📦 Entregados           → códigos 6,8 · COD cobrado

Tab 💳 Pedidos Pagos  (D2C prepago únicamente, sin B2B)
  🚚 En tránsito          → prepago despachado activo
  ⚠️ Novedades            → novedades externas + internas · cliente ya pagó

Tab 📊 Análisis
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except Exception:
    pass

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR,
    VENCIDO_COLOR, RESUELTO_COLOR, MAX_DIAS_ACTIVO,
    cargar_datos_api, render_sidebar, render_detalle, render_tabla, _parse_cod,
    usuario_activo,
)

from memoria import (
    disponible as mem_ok, guardar_snapshot,
    cargar_snapshots, historial_pedido,
    cargar_notas, agregar_nota,
    cargar_acciones, agregar_accion, TIPOS_ACCION,
)

# CSS ya está en app.py — no duplicar

# ── Guard de permisos ──────────────────────────────────────────────────────────
if "logistica" not in st.session_state.get("permisos", ["logistica"]):
    st.error("🔒 No tienes acceso al módulo de Logística.")
    st.stop()

# ── Helpers ────────────────────────────────────────────────────────────────────
FONT = dict(family="Arial, sans-serif", size=12, color=GRAPHITE_GREY)

COLOR_NIVEL = {
    "CRITICO":  CRITICO_COLOR,
    "RIESGO":   RIESGO_COLOR,
    "NORMAL":   NORMAL_COLOR,
    "VENCIDO":  VENCIDO_COLOR,
    "RESUELTO": RESUELTO_COLOR,
}

NOVEDAD_ES = {
    "Error - not able to process":                                    "Error · no procesa",
    "on stand by - not able to fulfil - no stock":                   "Sin stock",
    "Delivery not posible":                                           "Entrega no posible",
    "on stand by - not able to fulfil - expired promises":           "Promesa vencida",
    "All items reserved - fulfillment on hold - ext. conditionals":  "En espera · ext.",
    "All items reserved - fulfillment on hold - int. conditionals":  "En espera · int.",
    "on stand by - not able to fulfil - SM restriction":             "Restricción método envío",
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


def _kpi(num, label, sub="", bg=None, border=STEEL_BLUE):
    """
    KPI editorial — fondo blanco por defecto, accent lateral de color.
    Si `bg` se pasa explícitamente (color de marca), el texto se invierte
    automáticamente por el CSS para mantener contraste.
    """
    bg_style = f"background:{bg};" if bg else ""
    return (
        f'<div class="kpi-card" style="{bg_style}border-left:4px solid {border};">'
        f'<p class="kpi-label">{label}</p>'
        f'<div><p class="kpi-num">{num}</p>'
        f'<p class="kpi-sub">{sub}</p></div>'
        '</div>'
    )


def _render_memoria(orden: str):
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
            st.dataframe(df_h[["Fecha","Nivel","Score","Días","Novedad"]],
                         use_container_width=True, hide_index=True, height=160)

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
            tipo_ac = st.selectbox("Tipo", TIPOS_ACCION, label_visibility="collapsed")
            desc_ac = st.text_input("Descripción", placeholder="Descripción…", label_visibility="collapsed")
            if st.form_submit_button("➕ Registrar acción", use_container_width=True):
                if desc_ac.strip():
                    from datetime import datetime as _dt
                    _autor = f"{usuario_activo()} · {_dt.now().strftime('%d/%m/%Y %H:%M')}"
                    ok, err = agregar_accion(orden, tipo_ac, desc_ac, _autor)
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
            if st.form_submit_button("💬 Agregar nota", use_container_width=True):
                if nota_txt.strip():
                    from datetime import datetime as _dt
                    _autor_n = f"{usuario_activo()} · {_dt.now().strftime('%d/%m/%Y %H:%M')}"
                    ok, err = agregar_nota(orden, _autor_n, nota_txt)
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

_fuente       = _meta.get("fuente", "")
_fa           = _meta.get("fetched_at")
_fa_txt       = _fa.strftime("%d/%m/%Y %H:%M") if _fa else ""
_datos_frescos = _fuente in ("api_live",)   # solo API real = datos confiables para Pendientes

# Pendientes requiere datos muy recientes — máx 10 minutos
_edad_seg = (datetime.now() - _fa).total_seconds() if _fa else 99999

if _meta.get("bg_refresh"):
    st.info(
        "🔄 Actualizando datos en segundo plano — la próxima carga mostrará datos frescos.",
        icon="⏳",
    )
elif _fuente in ("csv_bootstrap", "stale"):
    st.warning(
        f"⚠️ Mostrando datos del {_fa_txt} · actualizando en segundo plano.",
        icon="⚠️",
    )

# ── Segmentación ───────────────────────────────────────────────────────────────
# Las 4 pestañas de Contraentrega muestran TODAS las órdenes activas (COD + prepago)
# filtradas únicamente por estado Melonn — sin restricción de tipo de recaudo.
df_cod = df_all[df_all["Tipo_Recaudo"] == "Contraentrega"].copy()   # para KPIs y métricas COD
df_pre = df_all[df_all["Tipo_Recaudo"] == "Prepago"].copy()

# ── Tabs operativas ────────────────────────────────────────────────────────────
# Contraentregas → siempre desde df_cod (D2C COD únicamente)
# Pedidos Pagos  → siempre desde df_pre (D2C prepago únicamente)
df_pend    = df_cod[df_cod["Estado_Code"] == 26].copy()
df_tran    = df_cod[df_cod["Estado_Code"].isin([5, 7, 24, 28])].copy()
df_nov_cod = df_cod[df_cod["Sub_Estado"] == "novedad"].copy()
df_ent     = df_cod[df_cod["Estado_Code"].isin([6, 8])].copy()
df_nov_pre  = df_pre[df_pre["Sub_Estado"] == "novedad"].copy()
df_tran_pre = df_pre[df_pre["Sub_Estado"] == "en_transito"].copy()
df_ent_pre  = df_pre[df_pre["Sub_Estado"] == "entregado"].copy()

# Entregados: solo semana en curso (lunes → domingo)
_lunes   = date.today() - pd.Timedelta(days=date.today().weekday())
_domingo = _lunes + pd.Timedelta(days=6)

def _es_esta_semana(fecha_str):
    try:
        f = pd.to_datetime(str(fecha_str)).date()
        return _lunes <= f <= _domingo
    except Exception:
        return False

df_ent     = df_ent[df_ent["F. Creación"].apply(_es_esta_semana)].copy()
df_ent_pre = df_ent_pre[df_ent_pre["F. Creación"].apply(_es_esta_semana)].copy()

# Filtros del sidebar
def _filtrar(df):
    d = df.copy()
    if filtro_nivel:
        d = d[d["Nivel"].isin(filtro_nivel)]
    if filtro_zona:
        d = d[d["Zona"].isin(filtro_zona)]
    return d

df_pend_f     = _filtrar(df_pend)
df_tran_f     = _filtrar(df_tran)
df_nov_cod_f  = _filtrar(df_nov_cod)
df_ent_f      = _filtrar(df_ent)
df_nov_pre_f  = _filtrar(df_nov_pre)
df_tran_pre_f = _filtrar(df_tran_pre)
df_ent_pre_f  = _filtrar(df_ent_pre)

# Métricas globales — usar Valor_num pre-calculado (vectorizado, sin .apply)
def _sum_valor(df):
    """Suma Valor_num si existe, fallback a .apply para compatibilidad."""
    if "Valor_num" in df.columns:
        return float(df["Valor_num"].sum())
    return float(df["Valor COD"].apply(_parse_cod).sum())

val_cod_total   = _sum_valor(df_cod)
val_ent_total   = _sum_valor(df_ent)
val_nov_cod     = _sum_valor(df_nov_cod)
n_criticos      = int((df_tran["Nivel"] == "CRITICO").sum())
n_riesgo        = int((df_tran["Nivel"] == "RIESGO").sum())
_n_cod_activas  = len(df_pend) + len(df_tran) + len(df_nov_cod) + len(df_ent)
_n_pre_total    = len(df_tran_pre) + len(df_nov_pre) + len(df_ent_pre)

# ── Encabezado ─────────────────────────────────────────────────────────────────
st.markdown(f"""
    <p class="titulo-panel">📦 LOGÍSTICA</p>
    <p class="subtitulo">Trazabilidad operativa · MALE'DENIM · {date.today().strftime('%d/%m/%Y')}</p>
    <hr style='margin:10px 0;'>
""", unsafe_allow_html=True)

# KPIs globales
k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    st.markdown(_kpi(
        len(df_pend), "PEND. DESPACHO", "Autorización requerida",
        border=RIESGO_COLOR if len(df_pend) > 0 else STEEL_BLUE,
    ), unsafe_allow_html=True)
with k2:
    c = CRITICO_COLOR if n_criticos > 0 else (RIESGO_COLOR if n_riesgo > 0 else NORMAL_COLOR)
    st.markdown(_kpi(len(df_tran), "EN TRÁNSITO COD",
                     f"{n_criticos} crít · {n_riesgo} riesgo", border=c), unsafe_allow_html=True)
with k3:
    st.markdown(_kpi(len(df_nov_cod), "NOV. COD",
                     _fmt_m(val_nov_cod) + " en riesgo" if val_nov_cod > 0 else "Sin novedades",
                     border=CRITICO_COLOR if len(df_nov_cod) > 0 else STEEL_BLUE),
                unsafe_allow_html=True)
with k4:
    st.markdown(_kpi(len(df_ent), "ENTREGADOS COD", _fmt_m(val_ent_total) + " cobrado",
                     border=RESUELTO_COLOR), unsafe_allow_html=True)
with k5:
    st.markdown(_kpi(_n_pre_total, "PEDIDOS PAGOS",
                     f"{len(df_tran_pre)} tránsito · {len(df_nov_pre)} novedades",
                     border=RIESGO_COLOR if len(df_nov_pre) > 0 else STEEL_BLUE),
                unsafe_allow_html=True)
with k6:
    st.markdown(_kpi(_fmt_m(val_cod_total), "PORTAFOLIO COD", "Total activo",
                     border=COD_COLOR), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── TABS PRINCIPALES ───────────────────────────────────────────────────────────
tab_cod, tab_pre, tab_ana = st.tabs([
    f"📦  Contraentrega  ({_n_cod_activas})",
    f"💳  Pedidos Pagos  ({_n_pre_total})",
    "📊  Análisis",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CONTRAENTREGA
# ══════════════════════════════════════════════════════════════════════════════
with tab_cod:
    st_pend, st_tran, st_nov, st_res = st.tabs([
        f"⏳  Pendientes por despacho  ({len(df_pend_f)})",
        f"🚚  En tránsito  ({len(df_tran_f)})",
        f"⚠️  Novedades  ({len(df_nov_cod_f)})",
        f"📦  Entregados  ({len(df_ent_f)})",
    ])

    # ── Pendientes por despacho ───────────────────────────────────────────────
    with st_pend:
        st.caption(
            "Contraentregas que requieren autorización del seller — "
            "estado Melonn: **Alistamiento en espera · Seller**."
        )

        # Indicador de frescura — no fuerza refresh automático para evitar lentitud
        if not _datos_frescos or _edad_seg > 1800:
            st.info(
                f"📡 Datos de hace {int(_edad_seg/60)} min. "
                "Presiona **↻ Actualizar datos** para sincronizar con Melonn.",
                icon="🕐",
            )

        df_auth_f = df_pend_f

        if df_pend_f.empty:
            st.success("✅ Sin pedidos pendientes de despacho en este momento.")
        else:
            val_auth  = _sum_valor(df_auth_f)

            p1, p2 = st.columns(2)
            with p1:
                st.markdown(_kpi(
                    len(df_auth_f), "ESPERAN AUTORIZACIÓN",
                    "Alistamiento en espera · Seller",
                    border=RIESGO_COLOR,
                ), unsafe_allow_html=True)
            with p2:
                st.markdown(_kpi(
                    _fmt_m(val_auth), "VALOR COD · PENDIENTE",
                    "Por autorizar despacho", border=COD_COLOR,
                ), unsafe_allow_html=True)

            # ── Tabla principal: solo las que requieren autorización ───────────
            st.markdown("<br>", unsafe_allow_html=True)
            COLS_A = ["Orden","Cliente","Teléfono","Ciudad","Estado",
                      "Método Envío","F. Creación","Valor COD","Link Melonn"]
            COLS_A = [c for c in COLS_A if c in df_pend_f.columns]

            if df_auth_f.empty:
                st.success("✅ Sin órdenes en espera de autorización seller.")
                _sel_pend = None
            else:
                st.markdown(
                    "<div class='sec-title'>🔑 Autorización requerida — alistado en espera · seller</div>",
                    unsafe_allow_html=True,
                )
                _sel_pend = render_tabla(df_auth_f, COLS_A, key="tbl_pend", height=360)

            # ── Panel de autorización de despacho ─────────────────────────────
            sel_p = _sel_pend is not None

            if sel_p:
                fila_auth    = df_auth_f.iloc[_sel_pend]
                orden_auth   = str(fila_auth.get("Orden", ""))
                orden_melonn = str(fila_auth.get("Orden Melonn", ""))
                cliente_auth = str(fila_auth.get("Cliente", "—"))
                ciudad_auth  = str(fila_auth.get("Ciudad", "—"))
                metodo_auth  = str(fila_auth.get("Método Envío", "—"))
                cod_auth     = str(fila_auth.get("Valor COD", "—"))
                estado_auth  = str(fila_auth.get("Estado", "—"))
                link_auth    = str(fila_auth.get("Link Melonn", ""))

                admin_url = (
                    f"https://app.melonn.com/sell-orders?search={orden_melonn}"
                    if orden_melonn else link_auth
                )
                _k_auth = f"_auth_ok_{orden_auth}"

                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown(
                    f"<div class='sec-title' style='color:{RIESGO_COLOR};'>🚀 Autorizar despacho</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"""<div style="background:white;border:1px solid {RIESGO_COLOR}33;
                        border-left:4px solid {RIESGO_COLOR};border-radius:8px;
                        padding:16px 20px;margin-bottom:12px;">
                      <div style="display:flex;gap:32px;flex-wrap:wrap;">
                        <div>
                          <div style="font-size:0.6rem;color:#909090;letter-spacing:2px;text-transform:uppercase;margin-bottom:3px;">Orden</div>
                          <div style="font-weight:700;color:{DEEP_INK};font-size:0.95rem;">#{orden_auth}</div>
                          <div style="font-size:0.75rem;color:#909090;">{orden_melonn}</div>
                        </div>
                        <div>
                          <div style="font-size:0.6rem;color:#909090;letter-spacing:2px;text-transform:uppercase;margin-bottom:3px;">Cliente</div>
                          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{cliente_auth}</div>
                          <div style="font-size:0.75rem;color:#909090;">{ciudad_auth}</div>
                        </div>
                        <div>
                          <div style="font-size:0.6rem;color:#909090;letter-spacing:2px;text-transform:uppercase;margin-bottom:3px;">Transportadora · Estado</div>
                          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{metodo_auth}</div>
                          <div style="font-size:0.75rem;color:{RIESGO_COLOR};font-weight:700;">{estado_auth}</div>
                        </div>
                        <div>
                          <div style="font-size:0.6rem;color:#909090;letter-spacing:2px;text-transform:uppercase;margin-bottom:3px;">Valor COD</div>
                          <div style="font-weight:700;color:{COD_COLOR};font-size:1rem;">${cod_auth}</div>
                        </div>
                      </div>
                      <div style="margin-top:10px;background:{RIESGO_COLOR}12;border:1px solid {RIESGO_COLOR}33;
                                  border-radius:5px;padding:6px 12px;font-size:0.68rem;
                                  color:{RIESGO_COLOR};font-weight:700;letter-spacing:1px;">
                        ⏸ ALISTADO EN ESPERA · SELLER — Usa el botón para liberar el hold y autorizar despacho
                      </div>
                    </div>""",
                    unsafe_allow_html=True,
                )

                # Feedback resultado de la última autorización
                if _k_auth in st.session_state:
                    resultado_auth = st.session_state[_k_auth]
                    if isinstance(resultado_auth, tuple):
                        estado_r, msg_r = resultado_auth
                        if estado_r == "ok":
                            st.success(f"✅ {msg_r}", icon="✅")
                        else:
                            st.error(f"❌ Error API Melonn: {msg_r}")
                    else:
                        st.success(f"✅ Despacho autorizado para #{orden_auth}", icon="✅")

                col_btn1, col_btn2, _col_sp = st.columns([1.4, 1.2, 2])
                with col_btn1:
                    with st.form(key=f"form_auth_{orden_auth}", clear_on_submit=True):
                        shipping_override = st.text_input(
                            "Código método envío (opcional)",
                            placeholder="Dejar vacío para usar el asignado",
                        )
                        submitted = st.form_submit_button(
                            "🚀 Autorizar despacho en Melonn",
                            use_container_width=True,
                            type="primary",
                        )
                        if submitted:
                            _usuario = usuario_activo()
                            _ts      = date.today().strftime("%d/%m/%Y")
                            with st.spinner("Enviando a Melonn…"):
                                import importlib, melonn_client as _mc
                                importlib.reload(_mc)
                                ok_api, msg_api = _mc.release_hold_fulfillment(
                                    orden_melonn,
                                    shipping_method_code=shipping_override.strip() or None,
                                )
                            if ok_api:
                                if mem_ok():
                                    agregar_accion(
                                        orden_auth,
                                        "despacho_autorizado",
                                        f"Despacho autorizado vía API Melonn · {metodo_auth} · COD ${cod_auth}",
                                        f"{_usuario} · {_ts}",
                                    )
                                st.session_state[_k_auth] = ("ok", f"{msg_api} · {_usuario} · {_ts}")
                                st.rerun()
                            else:
                                st.session_state[_k_auth] = ("err", msg_api)
                                st.rerun()

                with col_btn2:
                    if admin_url:
                        st.markdown(
                            f"""<a href="{admin_url}" target="_blank"
                                style="display:block;text-align:center;padding:8px 12px;
                                       background:{GRAPHITE_GREY};color:white;border-radius:6px;
                                       font-size:0.83rem;font-weight:600;text-decoration:none;
                                       margin-top:2px;">
                                🔗 Ver en Melonn
                            </a>""",
                            unsafe_allow_html=True,
                        )

            if sel_p:
                with st.expander("Detalle del pedido", expanded=False):
                    render_detalle(df_auth_f, tab_key="pend")
                    _render_memoria(str(df_auth_f.iloc[_sel_pend]["Orden"]))


            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button(
                "⬇️ Descargar pendientes (.CSV)",
                data=df_pend_f.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"maledenim_pendientes_{date.today()}.csv",
                mime="text/csv",
            )

    # ── En tránsito ───────────────────────────────────────────────────────────
    with st_tran:
        st.caption(
            "Órdenes activas en proceso de despacho — códigos Melonn 5 (empacada) · 7 (con transportadora) · 24 (preparada) · 28 (lista para empaque)."
        )
        if df_tran_f.empty:
            st.success("✅ Sin pedidos COD en tránsito.")
        else:
            df_t_riesgo = df_tran_f[df_tran_f["Nivel"] != "VENCIDO"]
            n_crit  = len(df_t_riesgo[df_t_riesgo["Nivel"] == "CRITICO"])
            n_ries  = len(df_t_riesgo[df_t_riesgo["Nivel"] == "RIESGO"])
            n_norm  = len(df_t_riesgo[df_t_riesgo["Nivel"] == "NORMAL"])
            val_tr  = _sum_valor(df_t_riesgo[df_t_riesgo["Nivel"].isin(["CRITICO","RIESGO"])])

            t1, t2, t3, t4 = st.columns(4)
            with t1:
                st.markdown(f"""<div class="kpi-card" style="border-left:4px solid {CRITICO_COLOR};">
                    <p class="kpi-num">{n_crit}</p><p class="kpi-label">CRÍTICO</p>
                    <p class="kpi-sub">Acción inmediata</p></div>""", unsafe_allow_html=True)
            with t2:
                st.markdown(f"""<div class="kpi-card" style="border-left:4px solid {RIESGO_COLOR};">
                    <p class="kpi-num">{n_ries}</p><p class="kpi-label">EN RIESGO</p>
                    <p class="kpi-sub">Monitorear hoy</p></div>""", unsafe_allow_html=True)
            with t3:
                st.markdown(f"""<div class="kpi-card" style="border-left:4px solid {NORMAL_COLOR};">
                    <p class="kpi-num">{n_norm}</p><p class="kpi-label">NORMAL</p>
                    <p class="kpi-sub">Sin acción</p></div>""", unsafe_allow_html=True)
            with t4:
                st.markdown(_kpi(_fmt_m(val_tr), "COD EN RIESGO",
                                 "Recaudo comprometido", border=COD_COLOR), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            COLS_T = ["Nivel","Orden","Cliente","Teléfono","Ciudad","Zona","Estado",
                      "Días","Días sobre SLA","F. Despacho","F. Promesa",
                      "Promesa vencida","Valor COD","Método Envío","Link Melonn"]
            COLS_T = [c for c in COLS_T if c in df_tran_f.columns]

            st.markdown("<div class='sec-title'>Lista de trabajo — COD en tránsito</div>",
                        unsafe_allow_html=True)
            _sel_tran = render_tabla(df_tran_f, COLS_T, key="tbl_tran", height=420)

            with st.expander("Detalle del pedido", expanded=_sel_tran is not None):
                if _sel_tran is None:
                    st.caption("Selecciona una fila para ver el detalle.")
                else:
                    render_detalle(df_tran_f, tab_key="tran")
                    _render_memoria(str(df_tran_f.iloc[_sel_tran]["Orden"]))

            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button("⬇️ Descargar en tránsito (.CSV)",
                data=df_tran_f.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"maledenim_transito_cod_{date.today()}.csv", mime="text/csv")

    # ── Novedades COD ─────────────────────────────────────────────────────────
    with st_nov:
        st.caption("COD con novedad externa activa — transportadora no pudo entregar o hay condición externa bloqueante. Requiere gestión.")
        if df_nov_cod_f.empty:
            st.success("✅ Sin novedades COD activas.")
        else:
            val_nov = _sum_valor(df_nov_cod_f)
            n1, n2, n3 = st.columns(3)
            with n1:
                st.markdown(_kpi(len(df_nov_cod_f), "NOVEDADES COD",
                                 "Requieren gestión", border=CRITICO_COLOR),
                            unsafe_allow_html=True)
            with n2:
                st.markdown(_kpi(_fmt_m(val_nov), "COD EN RIESGO",
                                 "Riesgo de no cobro", border=COD_COLOR), unsafe_allow_html=True)
            with n3:
                tipo_comun = (df_nov_cod_f["Estado"].value_counts().index[0]
                              if not df_nov_cod_f.empty else "—")
                st.markdown(_kpi(df_nov_cod_f["Estado"].nunique(), "TIPOS NOVEDAD",
                                 NOVEDAD_ES.get(tipo_comun, tipo_comun)[:28], border=RIESGO_COLOR),
                            unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            COLS_NC = ["Nivel","Orden","Cliente","Teléfono","Ciudad","Zona",
                       "Días","Valor COD","Estado","F. Despacho","F. Promesa",
                       "Promesa vencida","Método Envío","Link Melonn"]
            COLS_NC = [c for c in COLS_NC if c in df_nov_cod_f.columns]
            st.markdown("<div class='sec-title'>Lista de trabajo — novedades COD</div>",
                        unsafe_allow_html=True)
            _sel_nov_cod = render_tabla(df_nov_cod_f, COLS_NC, key="tbl_nov_cod", height=400)

            with st.expander("Detalle del pedido", expanded=_sel_nov_cod is not None):
                if _sel_nov_cod is None:
                    st.caption("Selecciona una fila para ver el detalle.")
                else:
                    render_detalle(df_nov_cod_f, tab_key="nov_cod")
                    _render_memoria(str(df_nov_cod_f.iloc[_sel_nov_cod]["Orden"]))

            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button("⬇️ Descargar novedades COD (.CSV)",
                data=df_nov_cod_f.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"maledenim_novedades_cod_{date.today()}.csv", mime="text/csv")

    # ── Entregados ────────────────────────────────────────────────────────────
    with st_res:
        st.caption("COD entregado al comprador — códigos Melonn 6 (recogido) y 8 (entregado). Ventana: mes + 15 días.")
        if df_ent_f.empty:
            st.info("Sin pedidos COD entregados en la ventana actual (mes + últimos 15 días).")
        else:
            val_ent  = _sum_valor(df_ent_f)
            n_c6     = len(df_ent_f[df_ent_f["Estado_Code"] == 6])
            n_c8     = len(df_ent_f[df_ent_f["Estado_Code"] == 8])
            avg_dias = int(df_ent_f["Días"].mean()) if not df_ent_f.empty else 0

            e1, e2, e3 = st.columns(3)
            with e1:
                st.markdown(_kpi(len(df_ent_f), "ENTREGADOS COD",
                                 f"{n_c6} recogidos · {n_c8} entregados",
                                 border=RESUELTO_COLOR), unsafe_allow_html=True)
            with e2:
                st.markdown(_kpi(_fmt_m(val_ent), "COD COBRADO",
                                 "Total recaudado en ventana", border=COD_COLOR), unsafe_allow_html=True)
            with e3:
                st.markdown(_kpi(f"{avg_dias}d", "DÍAS PROMEDIO",
                                 "Desde despacho hasta entrega", border=STEEL_BLUE), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            COLS_E = ["Estado","Orden","Cliente","Ciudad","F. Creación",
                      "F. Despacho","Valor COD","Método Envío","Días","Link Melonn"]
            COLS_E = [c for c in COLS_E if c in df_ent_f.columns]
            st.markdown("<div class='sec-title'>Pedidos COD entregados — ventana actual</div>",
                        unsafe_allow_html=True)
            render_tabla(df_ent_f, COLS_E, key="tbl_ent", height=380)

            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button("⬇️ Descargar entregados (.CSV)",
                data=df_ent_f.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"maledenim_entregados_cod_{date.today()}.csv", mime="text/csv")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PEDIDOS PAGOS (trazabilidad completa prepago D2C)
# ══════════════════════════════════════════════════════════════════════════════
with tab_pre:
    st.caption(
        "Pedidos de pago previo D2C — trazabilidad completa: en tránsito y novedades activas."
    )

    # KPIs globales prepago
    pp1, pp2, pp3, pp4 = st.columns(4)
    with pp1:
        st.markdown(_kpi(len(df_tran_pre_f), "EN TRÁNSITO",
                         "Prepago con transportadora", border=STEEL_BLUE), unsafe_allow_html=True)
    with pp2:
        st.markdown(_kpi(len(df_nov_pre_f), "NOVEDADES",
                         "Requieren gestión",
                         border=CRITICO_COLOR if len(df_nov_pre_f) > 0 else STEEL_BLUE),
                    unsafe_allow_html=True)
    with pp3:
        st.markdown(_kpi(len(df_ent_pre_f), "ENTREGADOS",
                         "Cliente recibió el pedido",
                         border=RESUELTO_COLOR), unsafe_allow_html=True)
    with pp4:
        avg_d = int(df_tran_pre_f["Días"].mean()) if not df_tran_pre_f.empty else 0
        st.markdown(_kpi(f"{avg_d}d", "DÍAS PROMEDIO",
                         "Tránsito prepago", border=GRAPHITE_GREY), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    pre_tran_tab, pre_nov_tab, pre_ent_tab = st.tabs([
        f"🚚  En tránsito  ({len(df_tran_pre_f)})",
        f"⚠️  Novedades  ({len(df_nov_pre_f)})",
        f"📦  Entregados  ({len(df_ent_pre_f)})",
    ])

    # ── En tránsito prepago ───────────────────────────────────────────────────
    with pre_tran_tab:
        st.caption("Pedidos prepago despachados activos — trazabilidad de entrega.")
        if df_tran_pre_f.empty:
            st.success("✅ Sin pedidos prepago en tránsito.")
        else:
            COLS_PT = ["Nivel","Orden","Cliente","Teléfono","Ciudad","Zona","Estado",
                       "Días","Días sobre SLA","F. Despacho","F. Promesa",
                       "Promesa vencida","Método Envío","Link Melonn"]
            COLS_PT = [c for c in COLS_PT if c in df_tran_pre_f.columns]
            st.markdown("<div class='sec-title'>Pedidos prepago en tránsito</div>",
                        unsafe_allow_html=True)
            _sel_tpre = render_tabla(df_tran_pre_f, COLS_PT, key="tbl_tran_pre", height=400)
            with st.expander("Detalle del pedido", expanded=_sel_tpre is not None):
                if _sel_tpre is None:
                    st.caption("Selecciona una fila para ver el detalle.")
                else:
                    render_detalle(df_tran_pre_f, tab_key="tran_pre")
                    _render_memoria(str(df_tran_pre_f.iloc[_sel_tpre]["Orden"]))
            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button("⬇️ Descargar tránsito prepago (.CSV)",
                data=df_tran_pre_f.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"maledenim_transito_prepago_{date.today()}.csv", mime="text/csv")

    # ── Novedades prepago ─────────────────────────────────────────────────────
    with pre_nov_tab:
        st.caption(
            "Novedades activas — incluye novedades externas (transportadora) "
            "e internas (Melonn). El cliente ya pagó."
        )
        if df_nov_pre_f.empty:
            st.success("✅ Sin novedades en pedidos de pago previo.")
        else:
            # Filtro por tipo
            _opciones_tipo = ["Todos los tipos"] + list(
                df_nov_pre_f["Estado"]
                .map(lambda x: NOVEDAD_ES.get(x, x))
                .value_counts()
                .index
            )
            _tipo_sel = st.selectbox(
                "🔎 Filtrar por tipo", _opciones_tipo, key="filtro_tipo_pre",
            )
            df_pre_vista = (
                df_nov_pre_f if _tipo_sel == "Todos los tipos"
                else df_nov_pre_f[
                    df_nov_pre_f["Estado"].map(lambda x: NOVEDAD_ES.get(x, x)) == _tipo_sel
                ]
            )

            COLS_PP = ["Nivel","Orden","Cliente","Teléfono","Ciudad","Zona",
                       "Días","Estado","F. Despacho","F. Promesa",
                       "Promesa vencida","Método Envío","Link Melonn"]
            COLS_PP = [c for c in COLS_PP if c in df_pre_vista.columns]
            st.markdown(
                f"<div class='sec-title'>Novedades prepago — {_tipo_sel} ({len(df_pre_vista)})</div>",
                unsafe_allow_html=True,
            )
            _sel_pre = render_tabla(df_pre_vista, COLS_PP, key="tbl_nov_pre", height=400)

            with st.expander("Detalle del pedido", expanded=_sel_pre is not None):
                if _sel_pre is None:
                    st.caption("Selecciona una fila para ver el detalle.")
                else:
                    render_detalle(df_pre_vista, tab_key="nov_pre")
                    _render_memoria(str(df_pre_vista.iloc[_sel_pre]["Orden"]))

            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button("⬇️ Descargar novedades prepago (.CSV)",
                data=df_pre_vista.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"maledenim_novedades_prepago_{date.today()}.csv", mime="text/csv")

    # ── Entregados prepago ────────────────────────────────────────────────────
    with pre_ent_tab:
        st.caption("Pedidos prepago entregados al comprador — código Melonn 8.")
        if df_ent_pre_f.empty:
            st.success("✅ Sin pedidos prepago entregados en la ventana actual.")
        else:
            COLS_EP = ["Orden","Cliente","Teléfono","Ciudad","Estado",
                       "F. Creación","F. Despacho","Días","Método Envío","Link Melonn"]
            COLS_EP = [c for c in COLS_EP if c in df_ent_pre_f.columns]
            st.markdown("<div class='sec-title'>Pedidos prepago entregados</div>",
                        unsafe_allow_html=True)
            _sel_ep = render_tabla(df_ent_pre_f, COLS_EP, key="tbl_ent_pre", height=380)
            with st.expander("Detalle del pedido", expanded=_sel_ep is not None):
                if _sel_ep is None:
                    st.caption("Selecciona una fila para ver el detalle.")
                else:
                    render_detalle(df_ent_pre_f, tab_key="ent_pre")
                    _render_memoria(str(df_ent_pre_f.iloc[_sel_ep]["Orden"]))
            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button("⬇️ Descargar entregados prepago (.CSV)",
                data=df_ent_pre_f.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"maledenim_entregados_prepago_{date.today()}.csv", mime="text/csv")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ANÁLISIS
# ══════════════════════════════════════════════════════════════════════════════
with tab_ana:
    st.markdown("<div class='sec-title' style='margin-top:0;'>Visualizaciones operativas</div>",
                unsafe_allow_html=True)

    df_ref = df_tran[df_tran["Nivel"] != "VENCIDO"].copy()

    # ── Tendencias históricas ──────────────────────────────────────────────────
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
                    fig_t.add_trace(go.Scatter(x=df_snaps["Fecha"], y=df_snaps["criticos"],
                        name="Crítico", line=dict(color=CRITICO_COLOR, width=2.5), mode="lines+markers"))
                    fig_t.add_trace(go.Scatter(x=df_snaps["Fecha"], y=df_snaps["en_riesgo"],
                        name="En riesgo", line=dict(color=RIESGO_COLOR, width=2.5), mode="lines+markers"))
                    fig_t.add_trace(go.Scatter(x=df_snaps["Fecha"], y=df_snaps["normales"],
                        name="Normal", line=dict(color=NORMAL_COLOR, width=2), mode="lines+markers"))
                    fig_t = _lay(fig_t, 240)
                    fig_t.update_layout(legend=dict(orientation="h", y=1.1, font=dict(color=GRAPHITE_GREY, size=11)))
                    st.plotly_chart(fig_t, use_container_width=True)
                with tc2:
                    st.markdown("<div class='sec-title'>Valor COD en riesgo ($)</div>", unsafe_allow_html=True)
                    fig_v = go.Figure(go.Bar(x=df_snaps["Fecha"], y=df_snaps["valor_cod_riesgo"],
                        marker_color=COD_COLOR,
                        text=df_snaps["valor_cod_riesgo"].apply(
                            lambda v: f"${v/1e6:.1f}M" if v >= 1e6 else f"${v/1e3:.0f}K"),
                        textposition="outside", textfont=dict(color=GRAPHITE_GREY, size=11)))
                    fig_v = _lay(fig_v, 240)
                    fig_v.update_layout(showlegend=False)
                    st.plotly_chart(fig_v, use_container_width=True)

    # ── Riesgo en tránsito ─────────────────────────────────────────────────────
    with st.expander("🎯 Riesgo en tránsito · COD", expanded=True):
        if df_ref.empty:
            st.info("Sin pedidos COD en tránsito activos.")
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("<div class='sec-title'>Por nivel de riesgo</div>", unsafe_allow_html=True)
                nc = df_ref["Nivel"].value_counts().reindex(["CRITICO","RIESGO","NORMAL"]).fillna(0)
                fig_d = go.Figure(go.Pie(labels=nc.index, values=nc.values, hole=0.55,
                    marker_colors=[CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR],
                    textfont=dict(color="white", size=12),
                    hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"))
                fig_d.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                    margin=dict(l=0,r=0,t=10,b=0), height=220, showlegend=True,
                    legend=dict(orientation="h", y=-0.08, font=dict(color=GRAPHITE_GREY, size=11)),
                    annotations=[dict(text=f"<b>{len(df_ref)}</b>", x=0.5, y=0.5,
                                      font_size=18, font_color=DEEP_INK, showarrow=False)])
                st.plotly_chart(fig_d, use_container_width=True)
            with c2:
                st.markdown("<div class='sec-title'>Cumplimiento SLA</div>", unsafe_allow_html=True)
                dentro = len(df_ref[df_ref["Días sobre SLA"] <= 0])
                fuera  = len(df_ref[df_ref["Días sobre SLA"] > 0])
                fig_s = go.Figure(go.Pie(labels=["Dentro SLA","Fuera SLA"], values=[dentro, fuera],
                    hole=0.55, marker_colors=[NORMAL_COLOR, CRITICO_COLOR],
                    textfont=dict(color="white", size=12)))
                fig_s.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                    margin=dict(l=0,r=0,t=10,b=0), height=220, showlegend=True,
                    legend=dict(orientation="h", y=-0.08, font=dict(color=GRAPHITE_GREY, size=11)))
                st.plotly_chart(fig_s, use_container_width=True)
            with c3:
                st.markdown("<div class='sec-title'>Por zona</div>", unsafe_allow_html=True)
                zn = df_ref.groupby("Zona").size().sort_values(ascending=True).reset_index(name="Pedidos")
                fig_z = px.bar(zn, y="Zona", x="Pedidos", orientation="h",
                               height=220, color_discrete_sequence=[STEEL_BLUE], text="Pedidos")
                fig_z.update_traces(textposition="outside", textfont=dict(color=GRAPHITE_GREY, size=11))
                fig_z = _lay(fig_z, 220)
                fig_z.update_layout(showlegend=False)
                st.plotly_chart(fig_z, use_container_width=True)

    # ── Métodos de envío ───────────────────────────────────────────────────────
    with st.expander("🚚 Métodos de envío", expanded=False):
        df_m = df_cod[df_cod["Sub_Estado"].isin(["en_transito","novedad"])].copy()
        if df_m.empty:
            st.info("Sin datos.")
        else:
            m1, m2 = st.columns(2)
            with m1:
                st.markdown("<div class='sec-title'>Volumen activo por método</div>", unsafe_allow_html=True)
                mv = df_m.groupby("Método Envío").size().sort_values(ascending=True).reset_index(name="Pedidos")
                fig_mv = px.bar(mv, y="Método Envío", x="Pedidos", orientation="h",
                                height=max(200, len(mv)*40), color_discrete_sequence=[STEEL_BLUE], text="Pedidos")
                fig_mv.update_traces(textposition="outside", textfont=dict(color=GRAPHITE_GREY, size=11))
                fig_mv = _lay(fig_mv, max(200, len(mv)*40))
                fig_mv.update_layout(showlegend=False)
                st.plotly_chart(fig_mv, use_container_width=True)
            with m2:
                st.markdown("<div class='sec-title'>Novedades por método</div>", unsafe_allow_html=True)
                mn = df_cod[df_cod["Sub_Estado"] == "novedad"].groupby("Método Envío").size()
                if mn.empty:
                    st.success("✅ Sin novedades por método.")
                else:
                    mn = mn.sort_values(ascending=True).reset_index(name="Novedades")
                    fig_mn = px.bar(mn, y="Método Envío", x="Novedades", orientation="h",
                                    height=max(200, len(mn)*40),
                                    color_discrete_sequence=[CRITICO_COLOR], text="Novedades")
                    fig_mn.update_traces(textposition="outside", textfont=dict(color=GRAPHITE_GREY, size=11))
                    fig_mn = _lay(fig_mn, max(200, len(mn)*40))
                    fig_mn.update_layout(showlegend=False)
                    st.plotly_chart(fig_mn, use_container_width=True)

    # ── Tiempo en tránsito ─────────────────────────────────────────────────────
    with st.expander("⏱️ Tiempo en tránsito · COD", expanded=False):
        if df_ref.empty:
            st.info("Sin datos.")
        else:
            h1, h2 = st.columns(2)
            with h1:
                st.markdown("<div class='sec-title'>Distribución de días</div>", unsafe_allow_html=True)
                fig_h = px.histogram(df_ref, x="Días", nbins=15,
                                     color_discrete_sequence=[STEEL_BLUE], height=260)
                fig_h.update_traces(marker_line_color="white", marker_line_width=1)
                fig_h = _lay(fig_h, 260)
                fig_h.update_layout(bargap=0.05, xaxis_title="Días", yaxis_title="Pedidos")
                st.plotly_chart(fig_h, use_container_width=True)
            with h2:
                st.markdown("<div class='sec-title'>Rango por nivel</div>", unsafe_allow_html=True)
                fig_b = px.box(df_ref, x="Nivel", y="Días", color="Nivel",
                               color_discrete_map=COLOR_NIVEL,
                               category_orders={"Nivel":["CRITICO","RIESGO","NORMAL"]}, height=260)
                fig_b = _lay(fig_b, 260)
                fig_b.update_layout(showlegend=False, xaxis_title="", yaxis_title="Días")
                st.plotly_chart(fig_b, use_container_width=True)

    # ── Novedades activas ──────────────────────────────────────────────────────
    with st.expander("⚠️ Análisis de novedades", expanded=False):
        df_todas_nov = df_all[df_all["Sub_Estado"] == "novedad"].copy()
        if df_todas_nov.empty:
            st.success("✅ Sin novedades activas.")
        else:
            an1, an2 = st.columns(2)
            with an1:
                st.markdown("<div class='sec-title'>Por tipo</div>", unsafe_allow_html=True)
                nov_cnt = (df_todas_nov["Estado"].map(NOVEDAD_ES).fillna(df_todas_nov["Estado"])
                           .value_counts().sort_values(ascending=True).reset_index())
                nov_cnt.columns = ["Novedad","Cantidad"]
                fig_nv = px.bar(nov_cnt, y="Novedad", x="Cantidad", orientation="h",
                                height=max(200, len(nov_cnt)*36),
                                color_discrete_sequence=[CRITICO_COLOR], text="Cantidad")
                fig_nv.update_traces(textposition="outside", textfont=dict(color=GRAPHITE_GREY, size=11))
                fig_nv = _lay(fig_nv, max(200, len(nov_cnt)*36))
                fig_nv.update_layout(showlegend=False)
                st.plotly_chart(fig_nv, use_container_width=True)
            with an2:
                st.markdown("<div class='sec-title'>COD vs Prepago</div>", unsafe_allow_html=True)
                tc = df_todas_nov["Tipo_Recaudo"].value_counts()
                fig_tc = go.Figure(go.Pie(labels=tc.index, values=tc.values, hole=0.55,
                    marker_colors=[COD_COLOR, RIESGO_COLOR],
                    textfont=dict(color="white", size=12)))
                fig_tc.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                    margin=dict(l=0,r=0,t=10,b=0), height=260, showlegend=True,
                    legend=dict(orientation="h", y=-0.08, font=dict(color=GRAPHITE_GREY, size=11)))
                st.plotly_chart(fig_tc, use_container_width=True)

    # ── Valor COD en riesgo ────────────────────────────────────────────────────
    with st.expander("💸 Valor COD en riesgo", expanded=False):
        df_cod2 = df_ref.copy()
        # Usa Valor_num pre-calculado (vectorizado) en vez de .apply
        df_cod2["Valor $"] = (df_cod2["Valor_num"] if "Valor_num" in df_cod2.columns
                              else df_cod2["Valor COD"].apply(_parse_cod))
        v1, v2 = st.columns(2)
        with v1:
            st.markdown("<div class='sec-title'>Por zona y nivel</div>", unsafe_allow_html=True)
            cv = df_cod2.groupby(["Zona","Nivel"])["Valor $"].sum().reset_index()
            cv["Nivel"] = pd.Categorical(cv["Nivel"], ["CRITICO","RIESGO","NORMAL"], ordered=True)
            fig_cv = px.bar(cv, y="Zona", x="Valor $", color="Nivel",
                            color_discrete_map=COLOR_NIVEL, orientation="h",
                            barmode="stack", height=240)
            fig_cv = _lay(fig_cv, 240)
            fig_cv.update_layout(
                legend=dict(orientation="h", y=1.12, font=dict(color=GRAPHITE_GREY, size=11)),
                xaxis_tickformat="$,.0f")
            st.plotly_chart(fig_cv, use_container_width=True)
        with v2:
            st.markdown("<div class='sec-title'>Por método envío (excepciones)</div>", unsafe_allow_html=True)
            ce = (df_cod2[df_cod2["Nivel"].isin(["CRITICO","RIESGO"])]
                  .groupby("Método Envío")["Valor $"].sum()
                  .sort_values(ascending=True).reset_index())
            if not ce.empty:
                fig_ce = px.bar(ce, y="Método Envío", x="Valor $", orientation="h",
                                height=240, color_discrete_sequence=[CRITICO_COLOR])
                fig_ce = _lay(fig_ce, 240)
                fig_ce.update_layout(showlegend=False, xaxis_tickformat="$,.0f")
                st.plotly_chart(fig_ce, use_container_width=True)
            else:
                st.success("✅ Sin COD en excepción.")
