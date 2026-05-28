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
import io
from datetime import date, datetime, timedelta
import json

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR, simple_bar,
)
from db import get_conn
import shopify_scheduler as scheduler

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

# ── Auto-sync al inicio de cada sesión nueva ─────────────────────────────────
# Se ejecuta UNA sola vez por sesión (session_state actúa de guardia).
# Si los datos tienen más de INTERVALO_HORAS, sincroniza automáticamente.
scheduler.iniciar()   # arranca hilo de fondo si no estaba activo

if not st.session_state.get("_sync_session_ok"):
    st.session_state["_sync_session_ok"] = True  # marcar antes por si hay rerun
    _est0 = scheduler.estado()
    if _est0["credenciales_ok"] and _est0["desactualizado"]:
        with st.spinner("♻️ Actualizando datos de Shopify..."):
            scheduler.sincronizar_si_necesario()
        st.rerun()

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
        _h = est.get("horas_desde_sync")
        _prox = f"próx. en {max(0, round(est['intervalo_horas'] - _h, 1))}h" if _h is not None else ""
        st.markdown(f"""
        <div style="background:#1a3a2a;border:1px solid #2d6a4f;border-radius:4px;
                    padding:10px 12px;margin-bottom:8px;">
            <div style="font-size:0.65rem;color:#52b788;letter-spacing:1px;">✓ CONECTADO · AUTO-SYNC</div>
            <div style="font-size:0.75rem;color:white;margin-top:2px;">{est['store']}</div>
            <div style="font-size:0.65rem;color:#52b788;margin-top:4px;">
                ⏱ cada {est['intervalo_horas']:.0f}h · {_prox}
            </div>
        </div>
        """, unsafe_allow_html=True)
        if est["ultima_sync"]:
            st.caption(f"Última actualización: {est['ultima_sync']}")
    else:
        st.markdown(f"""
        <div style="background:#3a1a1a;border:1px solid {CRITICO_COLOR};border-radius:4px;
                    padding:10px 12px;margin-bottom:12px;">
            <div style="font-size:0.65rem;color:#ff6b6b;letter-spacing:1px;">✗ SIN CREDENCIALES</div>
            <div style="font-size:0.7rem;color:{GRAPHITE_GREY};margin-top:4px;">
                Agrega SHOPIFY_STORE y SHOPIFY_ACCESS_TOKEN en Streamlit Cloud → Secrets
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # Forzar sync manual (en expander para no ocupar espacio)
    with st.expander("🔧 Forzar actualización manual"):
        dias_sync = st.slider("Días hacia atrás", 1, 180, 30, key="dias_sync")
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            btn_sync_todo = st.button("🔄 Todo", use_container_width=True,
                                      disabled=not est["credenciales_ok"])
        with col_b2:
            btn_sync_prod = st.button("📦 Productos", use_container_width=True,
                                      disabled=not est["credenciales_ok"])
        btn_sync_cli = st.button("👥 Solo clientes", use_container_width=True,
                                 disabled=not est["credenciales_ok"])
        st.caption("Útil para traer datos históricos más atrás.")

# ── Sincronización manual desde botones ───────────────────────────────────────
if btn_sync_todo:
    from shopify_sync import sincronizar_todo
    with st.spinner("Sincronizando todo desde Shopify..."):
        sincronizar_todo(dias_pedidos=dias_sync)
    # Resetear guardia para que la próxima sesión también auto-sincronice
    st.session_state["_sync_session_ok"] = True
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
        n_activos   = conn.execute("SELECT COUNT(*) FROM productos WHERE estado='active' AND inventario_total > 0").fetchone()[0]
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
        <p class="kpi-sub">{n_activos} c/stock · {n_borradores} borradores</p></div>""", unsafe_allow_html=True)
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
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🛒 Pedidos",
    "👕 Productos",
    "👥 Clientes",
    "📅 Lanzamientos",
    "📥 Informes",
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


# ── TAB 5: INFORMES ───────────────────────────────────────────────────────────
with tab5:
    st.markdown("<div class='sec-title'>Generador de informes personalizados</div>", unsafe_allow_html=True)
    st.caption("Configura los filtros, elige las columnas y descarga el informe en CSV o Excel.")

    INFORMES = {
        "Pedidos":   "pedidos",
        "Productos": "productos",
        "Clientes":  "clientes",
    }

    COLS_PEDIDOS = {
        "Orden":           "orden_shopify",
        "Fecha":           "fecha_pedido",
        "Cliente":         "nombre_cliente",
        "Email":           "email_cliente",
        "Teléfono":        "telefono_cliente",
        "Ciudad":          "ciudad_destino",
        "Región":          "region_destino",
        "Producto":        "producto",
        "SKU":             "sku",
        "Cantidad":        "cantidad",
        "Precio venta":    "precio_venta",
        "Método pago":     "metodo_pago",
        "Estado pago":     "estado_pago",
        "Contraentrega":   "es_contraentrega",
        "Valor COD":       "valor_cod",
        "Transportadora":  "transportadora",
        "Estado Melonn":   "estado_melonn",
        "Nivel riesgo":    "nivel_riesgo",
        "Zona":            "zona_logistica",
        "Días tránsito":   "dias_en_transito",
        "Canal":           "canal",
    }

    COLS_PRODUCTOS = {
        "Título":         "titulo",
        "Estado":         "estado",
        "Tipo":           "tipo",
        "Proveedor":      "proveedor",
        "Precio mín":     "precio_min",
        "Precio máx":     "precio_max",
        "Inventario":     "inventario_total",
        "Tags":           "tags",
        "Publicación":    "fecha_publicacion",
        "Creación":       "fecha_creacion",
    }

    COLS_CLIENTES = {
        "Nombre":          "nombre",
        "Email":           "email",
        "Teléfono":        "telefono",
        "Ciudad":          "ciudad",
        "Región":          "region",
        "Pedidos":         "total_pedidos",
        "Total gastado":   "total_gastado",
        "Marketing":       "acepta_marketing",
        "Primer pedido":   "fecha_primer_pedido",
        "Último pedido":   "fecha_ultimo_pedido",
    }

    # ── Configuración del informe ──────────────────────────────────────────────
    cfg1, cfg2 = st.columns([1, 2])

    with cfg1:
        tipo_informe = st.selectbox("📋 Tipo de informe", list(INFORMES.keys()), key="inf_tipo")

        if tipo_informe == "Pedidos":
            # Rango de fechas
            st.markdown("**Período**")
            fc1, fc2 = st.columns(2)
            with fc1:
                fecha_desde = st.date_input("Desde", value=date.today() - timedelta(days=30), key="inf_desde")
            with fc2:
                fecha_hasta = st.date_input("Hasta", value=date.today(), key="inf_hasta")

            # Filtros adicionales
            st.markdown("**Filtros**")
            f_estado_inf = st.multiselect("Estado pago", ["pagado","pendiente","devuelto","fallido"],
                                          default=[], key="inf_est_pago")
            f_cod_inf = st.selectbox("Tipo pago", ["Todos","Solo COD","Solo prepago"], key="inf_cod")
            f_nivel_inf = st.multiselect("Nivel riesgo", ["CRITICO","RIESGO","NORMAL"],
                                         default=[], key="inf_nivel")
            COLS_DISP = COLS_PEDIDOS

        elif tipo_informe == "Productos":
            f_estado_prod_inf = st.multiselect("Estado", ["active","draft","archived"],
                                               default=["active"], key="inf_est_prod")
            f_stock_inf = st.checkbox("Solo con inventario > 0", value=True, key="inf_stock")
            COLS_DISP = COLS_PRODUCTOS

        else:  # Clientes
            f_mktg_inf = st.selectbox("Marketing", ["Todos","Acepta","No acepta"], key="inf_mktg")
            f_ciu_inf  = st.text_input("Ciudad (contiene)", key="inf_ciudad", placeholder="Medellín...")
            COLS_DISP = COLS_CLIENTES

    with cfg2:
        st.markdown("**Columnas a incluir**")
        cols_sel = st.multiselect(
            "Selecciona columnas",
            list(COLS_DISP.keys()),
            default=list(COLS_DISP.keys()),
            key="inf_cols",
        )

    st.markdown("---")

    # ── Generar informe ────────────────────────────────────────────────────────
    if st.button("⚙️ Generar informe", type="primary", use_container_width=False):
        try:
            with get_conn() as conn:
                if tipo_informe == "Pedidos":
                    q = "SELECT * FROM pedidos WHERE fuente='shopify_api' AND fecha_pedido BETWEEN ? AND ?"
                    params = [str(fecha_desde), str(fecha_hasta)]
                    df_inf = pd.DataFrame([dict(r) for r in conn.execute(q, params).fetchall()])

                    if not df_inf.empty:
                        if f_estado_inf:
                            df_inf = df_inf[df_inf["estado_pago"].isin(f_estado_inf)]
                        if f_cod_inf == "Solo COD":
                            df_inf = df_inf[df_inf["es_contraentrega"] == 1]
                        elif f_cod_inf == "Solo prepago":
                            df_inf = df_inf[df_inf["es_contraentrega"] == 0]
                        if f_nivel_inf:
                            df_inf = df_inf[df_inf["nivel_riesgo"].isin(f_nivel_inf)]
                        df_inf["es_contraentrega"] = df_inf["es_contraentrega"].map({1:"SÍ", 0:"—"})

                elif tipo_informe == "Productos":
                    q = "SELECT * FROM productos"
                    df_inf = pd.DataFrame([dict(r) for r in conn.execute(q).fetchall()])
                    if not df_inf.empty:
                        if f_estado_prod_inf:
                            df_inf = df_inf[df_inf["estado"].isin(f_estado_prod_inf)]
                        if f_stock_inf:
                            df_inf = df_inf[df_inf["inventario_total"] > 0]

                else:  # Clientes
                    q = "SELECT * FROM clientes"
                    df_inf = pd.DataFrame([dict(r) for r in conn.execute(q).fetchall()])
                    if not df_inf.empty:
                        if f_mktg_inf == "Acepta":
                            df_inf = df_inf[df_inf["acepta_marketing"] == 1]
                        elif f_mktg_inf == "No acepta":
                            df_inf = df_inf[df_inf["acepta_marketing"] == 0]
                        if f_ciu_inf:
                            df_inf = df_inf[df_inf["ciudad"].str.contains(f_ciu_inf, case=False, na=False)]
                        df_inf["acepta_marketing"] = df_inf["acepta_marketing"].map({1:"Sí", 0:"No"})

            if df_inf.empty:
                st.warning("Sin registros con los filtros seleccionados.")
            else:
                # Seleccionar y renombrar columnas
                cols_db   = [COLS_DISP[c] for c in cols_sel if c in COLS_DISP and COLS_DISP[c] in df_inf.columns]
                cols_name = [c for c in cols_sel if c in COLS_DISP and COLS_DISP[c] in df_inf.columns]
                df_export = df_inf[cols_db].copy()
                df_export.columns = cols_name

                st.session_state["informe_df"]     = df_export
                st.session_state["informe_nombre"] = tipo_informe
                st.rerun()

        except Exception as e:
            st.error(f"Error generando informe: {e}")

    # ── Mostrar y descargar ────────────────────────────────────────────────────
    if "informe_df" in st.session_state and st.session_state["informe_df"] is not None:
        df_show = st.session_state["informe_df"]
        nombre  = st.session_state.get("informe_nombre", "informe")
        hoy_str = date.today().strftime("%Y%m%d")

        st.markdown(f"<div class='sec-title'>{len(df_show):,} registros — listo para descargar</div>",
                    unsafe_allow_html=True)

        # Preview
        st.dataframe(df_show.head(200), use_container_width=True, height=360, hide_index=True)

        # Botones de descarga
        dc1, dc2, dc3 = st.columns([1, 1, 3])

        with dc1:
            csv_bytes = df_show.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇️ Descargar CSV",
                data=csv_bytes,
                file_name=f"maledenim_{nombre.lower()}_{hoy_str}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with dc2:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df_show.to_excel(writer, index=False, sheet_name=nombre)
            buf.seek(0)
            st.download_button(
                "⬇️ Descargar Excel",
                data=buf.getvalue(),
                file_name=f"maledenim_{nombre.lower()}_{hoy_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        with dc3:
            if st.button("🗑 Limpiar", use_container_width=False):
                st.session_state["informe_df"] = None
                st.rerun()
