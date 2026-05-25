"""
Panel Shopify — MALE'DENIM
Pedidos, productos, clientes y estado de sincronización.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
from datetime import date
import json

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR, simple_bar,
)
from db import get_conn
import shopify_scheduler as scheduler

st.set_page_config(
    page_title="MALE'DENIM · Shopify",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)


# ── Helper mensaje vacío (definido aquí para estar disponible en los tabs) ─────
def _msg_vacio(entidad: str, emoji: str) -> None:
    st.markdown(f"""
    <div style="background:white;border:1px dashed {STEEL_BLUE};border-radius:4px;
                padding:40px;text-align:center;color:{GRAPHITE_GREY};">
        <div style="font-size:2rem;">{emoji}</div>
        <div style="font-size:0.9rem;margin-top:8px;">
            Sin {entidad} sincronizados aún.
        </div>
        <div style="font-size:0.78rem;margin-top:6px;color:{STEEL_BLUE};">
            Configura las credenciales en .env y usa el botón <strong>🔄 Todo</strong> del sidebar.
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── Arrancar scheduler si hay credenciales ────────────────────────────────────
scheduler.iniciar()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
        <div style="background:{DEEP_INK};padding:20px 16px 12px;margin:-1rem -1rem 1rem;
                    border-bottom:3px solid {STEEL_BLUE};">
            <div style="font-family:'Arial Black',sans-serif;font-size:1.1rem;
                        color:white;letter-spacing:2px;">MALE'DENIM</div>
            <div style="font-size:0.6rem;color:{STEEL_BLUE};letter-spacing:3px;margin-top:2px;">
                INTEGRACIÓN SHOPIFY
            </div>
        </div>
    """, unsafe_allow_html=True)

    est = scheduler.estado()

    # Estado de conexión
    if est["credenciales_ok"]:
        st.markdown(f"""
        <div style="background:#1a3a2a;border:1px solid #2d6a4f;border-radius:4px;
                    padding:10px 12px;margin-bottom:12px;">
            <div style="font-size:0.65rem;color:#52b788;letter-spacing:1px;">✓ CONECTADO</div>
            <div style="font-size:0.75rem;color:white;margin-top:2px;">{est['store']}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background:#3a1a1a;border:1px solid {CRITICO_COLOR};border-radius:4px;
                    padding:10px 12px;margin-bottom:12px;">
            <div style="font-size:0.65rem;color:#ff6b6b;letter-spacing:1px;">✗ SIN CREDENCIALES</div>
            <div style="font-size:0.7rem;color:{GRAPHITE_GREY};margin-top:4px;">
                Edita el archivo .env con tu token de Shopify
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.expander("¿Cómo configurarlo?"):
            st.code("""# En el archivo .env:
SHOPIFY_STORE=maledenim.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_...""")
            st.caption("Crea la app en: Shopify Admin → Configuración → Apps → Desarrollar apps")

    st.markdown("---")
    st.markdown("#### Sincronización manual")

    dias_sync = st.slider("Días hacia atrás", 1, 180, 30, key="dias_sync")
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        btn_sync_todo  = st.button("🔄 Todo", use_container_width=True,
                                   disabled=not est["credenciales_ok"])
    with col_b2:
        btn_sync_prod  = st.button("📦 Productos", use_container_width=True,
                                   disabled=not est["credenciales_ok"])

    btn_sync_cli = st.button("👥 Solo clientes", use_container_width=True,
                             disabled=not est["credenciales_ok"])

    if est["ultima_sync"]:
        st.caption(f"Última sync: {est['ultima_sync']}")
    if est["activo"]:
        st.caption(f"⏱ Auto-sync cada {est['intervalo_horas']:.0f}h activo")

# ── Sincronización desde botones ──────────────────────────────────────────────
if btn_sync_todo:
    from shopify_sync import sincronizar_todo
    with st.spinner("Sincronizando todo desde Shopify..."):
        r = sincronizar_todo(dias_pedidos=dias_sync)
    st.success("Sincronización completa.")
    st.rerun()

if btn_sync_prod:
    from shopify_sync import sincronizar_productos
    with st.spinner("Sincronizando productos..."):
        r = sincronizar_productos()
    st.success(f"Productos: {r['insertados']} nuevos · {r['actualizados']} actualizados")
    st.rerun()

if btn_sync_cli:
    from shopify_sync import sincronizar_clientes
    with st.spinner("Sincronizando clientes..."):
        r = sincronizar_clientes()
    st.success(f"Clientes: {r['insertados']} nuevos · {r['actualizados']} actualizados")
    st.rerun()

# ── Encabezado ────────────────────────────────────────────────────────────────
col_h, col_ts = st.columns([3, 1])
with col_h:
    st.markdown(f"""
        <p class="titulo-panel">🛍️ SHOPIFY</p>
        <p class="subtitulo">Pedidos · Productos · Clientes · MALE'DENIM</p>
    """, unsafe_allow_html=True)
with col_ts:
    st.markdown(f"""
        <div style="text-align:right;padding-top:4px;">
            <div style="font-size:0.68rem;color:{GRAPHITE_GREY};letter-spacing:1px;">
                {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')}
            </div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

# ── KPIs de la DB ─────────────────────────────────────────────────────────────
try:
    with get_conn() as conn:
        n_pedidos   = conn.execute("SELECT COUNT(*) FROM pedidos WHERE fuente='shopify_api'").fetchone()[0]
        n_productos = conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
        n_activos   = conn.execute("SELECT COUNT(*) FROM productos WHERE estado='active'").fetchone()[0]
        n_borradores= conn.execute("SELECT COUNT(*) FROM productos WHERE estado='draft'").fetchone()[0]
        n_clientes  = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
        val_pedidos = conn.execute("SELECT COALESCE(SUM(precio_venta),0) FROM pedidos WHERE fuente='shopify_api'").fetchone()[0]
except Exception as _dbe:
    n_pedidos = n_productos = n_activos = n_borradores = n_clientes = 0
    val_pedidos = 0.0

k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{n_pedidos:,}</p>
        <p class="kpi-label">Pedidos Shopify</p>
        <p class="kpi-sub">${val_pedidos:,.0f} facturado</p></div>""", unsafe_allow_html=True)
with k2:
    st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{n_productos:,}</p>
        <p class="kpi-label">Productos</p>
        <p class="kpi-sub">{n_activos} activos · {n_borradores} borradores</p></div>""", unsafe_allow_html=True)
with k3:
    st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{n_clientes:,}</p>
        <p class="kpi-label">Clientes</p>
        <p class="kpi-sub">Base de datos</p></div>""", unsafe_allow_html=True)
with k4:
    # Próximo lanzamiento
    with get_conn() as conn:
        prox = conn.execute("""
            SELECT titulo, fecha_publicacion FROM productos
            WHERE fecha_publicacion >= date('now') AND estado IN ('active','draft')
            ORDER BY fecha_publicacion ASC LIMIT 1
        """).fetchone()
    if prox:
        st.markdown(f"""<div class="kpi-card" style="background:#1a3a5a;border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num" style="font-size:0.9rem;">{prox['fecha_publicacion']}</p>
            <p class="kpi-label">Próx. lanzamiento</p>
            <p class="kpi-sub" style="font-size:0.65rem;">{prox['titulo'][:30]}</p></div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">—</p>
            <p class="kpi-label">Próx. lanzamiento</p>
            <p class="kpi-sub">Sin fechas futuras</p></div>""", unsafe_allow_html=True)
with k5:
    # Sync log
    with get_conn() as conn:
        ultima = conn.execute("""
            SELECT fecha_sync, estado FROM shopify_sync_log
            ORDER BY fecha_sync DESC LIMIT 1
        """).fetchone()
    if ultima:
        color_sync = NORMAL_COLOR if ultima["estado"] == "ok" else CRITICO_COLOR
        st.markdown(f"""<div class="kpi-card" style="background:{color_sync};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num" style="font-size:0.85rem;">{ultima['fecha_sync'][:16]}</p>
            <p class="kpi-label">Última sync</p>
            <p class="kpi-sub">{ultima['estado'].upper()}</p></div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
            <p class="kpi-num">—</p>
            <p class="kpi-label">Sin sincronizar</p>
            <p class="kpi-sub">Usa los botones del sidebar</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "🛒 Pedidos",
    "👕 Productos",
    "👥 Clientes",
    "📅 Lanzamientos",
])

# ── TAB 1: Pedidos Shopify ────────────────────────────────────────────────────
with tab1:
    st.markdown("<div class='sec-title'>Pedidos sincronizados desde Shopify</div>", unsafe_allow_html=True)

    with get_conn() as conn:
        df_ped = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT orden_shopify, nombre_cliente, email_cliente, ciudad_destino,
                   fecha_pedido, precio_venta, metodo_pago, estado_pago,
                   es_contraentrega, nivel_riesgo, estado_melonn, fuente
            FROM pedidos
            ORDER BY fecha_pedido DESC
            LIMIT 500
        """).fetchall()])

    if df_ped.empty:
        _msg_vacio("pedidos", "🛒")
    else:
        col_f1, col_f2, _ = st.columns([2, 2, 3])
        with col_f1:
            f_estado = st.selectbox("Estado pago", ["Todos","pagado","pendiente","devuelto"], key="f_est_ped")
        with col_f2:
            f_canal  = st.selectbox("Canal", ["Todos"] + sorted(df_ped["fuente"].dropna().unique().tolist()), key="f_canal")

        df_p = df_ped.copy()
        if f_estado != "Todos":
            df_p = df_p[df_p["estado_pago"] == f_estado]
        if f_canal != "Todos":
            df_p = df_p[df_p["fuente"] == f_canal]

        df_p["es_contraentrega"] = df_p["es_contraentrega"].map({1:"SÍ", 0:"—"})

        st.dataframe(
            df_p.style.format({"precio_venta": "${:,.0f}"}),
            use_container_width=True, height=420, hide_index=True,
        )
        st.caption(f"{len(df_p)} pedidos")


# ── TAB 2: Productos ──────────────────────────────────────────────────────────
with tab2:
    st.markdown("<div class='sec-title'>Catálogo de productos</div>", unsafe_allow_html=True)

    with get_conn() as conn:
        df_prod = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT titulo, estado, tipo, proveedor, precio_min, precio_max,
                   inventario_total, tags, fecha_publicacion, fecha_creacion
            FROM productos
            ORDER BY fecha_publicacion DESC NULLS LAST, fecha_creacion DESC
        """).fetchall()])

    if df_prod.empty:
        _msg_vacio("productos", "👕")
    else:
        col_f1, col_f2, _ = st.columns([2, 2, 3])
        with col_f1:
            f_estado_p = st.selectbox("Estado", ["Todos","active","draft","archived"], key="f_est_prod")
        with col_f2:
            tipos = ["Todos"] + sorted(df_prod["tipo"].dropna().unique().tolist())
            f_tipo = st.selectbox("Tipo", tipos, key="f_tipo_prod")

        df_pr = df_prod.copy()
        if f_estado_p != "Todos":
            df_pr = df_pr[df_pr["estado"] == f_estado_p]
        if f_tipo != "Todos":
            df_pr = df_pr[df_pr["tipo"] == f_tipo]

        ESTADO_EMOJI = {"active": "✅ Activo", "draft": "📝 Borrador", "archived": "📦 Archivado"}
        df_pr["estado"] = df_pr["estado"].map(lambda x: ESTADO_EMOJI.get(x, x))

        st.dataframe(
            df_pr.style.format({
                "precio_min": "${:,.0f}",
                "precio_max": "${:,.0f}",
            }),
            use_container_width=True, height=420, hide_index=True,
        )
        st.caption(f"{len(df_pr)} productos")


# ── TAB 3: Clientes ───────────────────────────────────────────────────────────
with tab3:
    st.markdown("<div class='sec-title'>Base de clientes</div>", unsafe_allow_html=True)

    with get_conn() as conn:
        df_cli = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT nombre, email, telefono, ciudad, region,
                   total_pedidos, total_gastado, acepta_marketing,
                   fecha_primer_pedido, fecha_ultimo_pedido
            FROM clientes
            ORDER BY total_gastado DESC
        """).fetchall()])

    if df_cli.empty:
        _msg_vacio("clientes", "👥")
    else:
        cg1, cg2, cg3 = st.columns(3)
        with cg1:
            top5 = df_cli.nlargest(5, "total_gastado")[["nombre","total_gastado","total_pedidos"]]
            st.markdown("<div class='sec-title' style='font-size:0.75rem'>Top 5 por valor</div>", unsafe_allow_html=True)
            st.dataframe(top5.style.format({"total_gastado":"${:,.0f}"}), height=200, hide_index=True, use_container_width=True)
        with cg2:
            ciud = df_cli["ciudad"].value_counts().head(5)
            st.markdown("<div class='sec-title' style='font-size:0.75rem'>Ciudades top</div>", unsafe_allow_html=True)
            simple_bar(ciud, color=STEEL_BLUE, height=200)
        with cg3:
            mktg = df_cli["acepta_marketing"].value_counts()
            mktg.index = mktg.index.map({1:"Acepta marketing", 0:"No acepta"})
            st.markdown("<div class='sec-title' style='font-size:0.75rem'>Marketing</div>", unsafe_allow_html=True)
            simple_bar(mktg, color=COD_COLOR, height=200)

        st.markdown("<br>", unsafe_allow_html=True)
        df_cli["acepta_marketing"] = df_cli["acepta_marketing"].map({1:"✓", 0:"—"})
        st.dataframe(
            df_cli.style.format({"total_gastado": "${:,.0f}"}),
            use_container_width=True, height=380, hide_index=True,
        )
        st.caption(f"{len(df_cli)} clientes")


# ── TAB 4: Lanzamientos ───────────────────────────────────────────────────────
with tab4:
    st.markdown("<div class='sec-title'>Calendario de lanzamientos de producto</div>", unsafe_allow_html=True)
    st.caption("Basado en la fecha de publicación (published_at) de cada producto en Shopify.")

    with get_conn() as conn:
        df_lanz = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT titulo, estado, tipo, precio_min, precio_max,
                   inventario_total, fecha_publicacion, tags
            FROM productos
            WHERE fecha_publicacion IS NOT NULL
            ORDER BY fecha_publicacion DESC
        """).fetchall()])

    if df_lanz.empty:
        _msg_vacio("lanzamientos", "📅")
    else:
        col_f1, col_f2, _ = st.columns([2, 2, 3])
        with col_f1:
            periodos = ["Todos", "Próximos", "Este mes", "Últimos 3 meses", "Este año"]
            f_periodo = st.selectbox("Período", periodos, key="f_periodo_lanz")
        with col_f2:
            f_est_lanz = st.selectbox("Estado", ["Todos","active","draft"], key="f_est_lanz")

        import datetime as dt_mod
        hoy = date.today()
        df_lz = df_lanz.copy()
        df_lz["fecha_publicacion"] = pd.to_datetime(df_lz["fecha_publicacion"], errors="coerce")

        if f_periodo == "Próximos":
            df_lz = df_lz[df_lz["fecha_publicacion"].dt.date >= hoy]
        elif f_periodo == "Este mes":
            df_lz = df_lz[
                (df_lz["fecha_publicacion"].dt.year == hoy.year) &
                (df_lz["fecha_publicacion"].dt.month == hoy.month)
            ]
        elif f_periodo == "Últimos 3 meses":
            hace3m = hoy.replace(month=hoy.month - 3) if hoy.month > 3 else hoy.replace(year=hoy.year-1, month=hoy.month+9)
            df_lz = df_lz[df_lz["fecha_publicacion"].dt.date >= hace3m]
        elif f_periodo == "Este año":
            df_lz = df_lz[df_lz["fecha_publicacion"].dt.year == hoy.year]

        if f_est_lanz != "Todos":
            df_lz = df_lz[df_lz["estado"] == f_est_lanz]

        # Indicador visual próximo/pasado
        df_lz["⏱"] = df_lz["fecha_publicacion"].dt.date.apply(
            lambda d: "🔜 Próximo" if d >= hoy else "✅ Publicado"
        )
        df_lz["fecha_publicacion"] = df_lz["fecha_publicacion"].dt.strftime("%d/%m/%Y")
        ESTADO_EMOJI = {"active": "✅ Activo", "draft": "📝 Borrador"}
        df_lz["estado"] = df_lz["estado"].map(lambda x: ESTADO_EMOJI.get(x, x))

        st.dataframe(
            df_lz[["⏱","fecha_publicacion","titulo","estado","tipo","precio_min","precio_max","inventario_total","tags"]]
            .style.format({"precio_min": "${:,.0f}", "precio_max": "${:,.0f}"}),
            use_container_width=True, height=440, hide_index=True,
        )
        st.caption(f"{len(df_lz)} lanzamientos")

        # Mini línea de tiempo por mes
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("<div class='sec-title'>Lanzamientos por mes</div>", unsafe_allow_html=True)
        df_timeline = df_lanz.copy()
        df_timeline["mes"] = pd.to_datetime(df_timeline["fecha_publicacion"], errors="coerce").dt.to_period("M").astype(str)
        conteo_mes = df_timeline.groupby("mes").size().reset_index(name="lanzamientos")
        conteo_mes = conteo_mes.sort_values("mes").tail(12)
        if not conteo_mes.empty:
            simple_bar(conteo_mes.set_index("mes")["lanzamientos"], color=STEEL_BLUE, height=180)


