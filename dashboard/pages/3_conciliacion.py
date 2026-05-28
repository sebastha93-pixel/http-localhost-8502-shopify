"""
Panel de Conciliación Financiera — MALE'DENIM
Cruza: pedidos ↔ pagos (Wompi/Addi) ↔ COD (Melonn) ↔ banco

Fuentes de datos que acepta:
  - CSV de transacciones Wompi
  - CSV de liquidación COD Melonn
  - CSV de extracto bancario
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
from datetime import date
import tempfile, os

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR,
)
from conciliacion import (
    ingestar_wompi, ingestar_liquidacion_melonn, ingestar_banco,
    conciliar_wompi_vs_pedidos, conciliar_cod_vs_banco,
    resumen_conciliacion, generar_reporte_conciliacion,
    pedidos_sin_conciliar,
)
from db import get_conn

st.markdown(CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
        <div style="background:{DEEP_INK};padding:20px 16px 12px;margin:-1rem -1rem 1rem;
                    border-bottom:3px solid {STEEL_BLUE};">
            <div style="font-family:'Arial Black',sans-serif;font-size:1.1rem;
                        color:white;letter-spacing:2px;">MALE'DENIM</div>
            <div style="font-size:0.6rem;color:{STEEL_BLUE};letter-spacing:3px;margin-top:2px;">
                CONCILIACIÓN FINANCIERA
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("#### Cargar archivos")
    st.caption("Sube los reportes de cada fuente para iniciar la conciliación.")

    wompi_file  = st.file_uploader("Reporte Wompi (.csv)", type=["csv"], key="wompi_up")
    liq_file    = st.file_uploader("Liquidación COD Melonn (.csv)", type=["csv"], key="liq_up")
    banco_file  = st.file_uploader("Extracto bancario (.csv)", type=["csv"], key="banco_up")
    ref_liq     = st.text_input("Referencia liquidación", placeholder="LIQ-2026-05", key="ref_liq")

    st.markdown("---")
    btn_ingestar   = st.button("📥  Ingestar fuentes", use_container_width=True)
    btn_conciliar  = st.button("⚡  Ejecutar conciliación", use_container_width=True, type="primary")
    btn_reporte    = st.button("📄  Generar reporte CSV", use_container_width=True)

# ── Encabezado ────────────────────────────────────────────────────────────────
col_h, col_ts = st.columns([3, 1])
with col_h:
    st.markdown(f"""
        <p class="titulo-panel">💼 CONCILIACIÓN</p>
        <p class="subtitulo">Reconciliación financiera · Pedidos ↔ Pagos ↔ Banco · MALE'DENIM</p>
    """, unsafe_allow_html=True)
with col_ts:
    st.markdown(f"""
        <div style="text-align:right;padding-top:4px;">
            <div style="font-size:0.68rem;color:{GRAPHITE_GREY};letter-spacing:1px;">
                {__import__('datetime').datetime.now(__import__('datetime').timezone(__import__('datetime').timedelta(hours=-5))).strftime('%d/%m/%Y %H:%M')} COL
            </div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)

# ── Lógica de botones ─────────────────────────────────────────────────────────

def _guardar_temp(uploaded) -> str:
    """Guarda un UploadedFile en un archivo temporal y retorna la ruta."""
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded.read())
        return tmp.name


if btn_ingestar:
    if not any([wompi_file, liq_file, banco_file]):
        st.warning("Sube al menos un archivo para ingestar.")
    else:
        with st.spinner("Ingeriando fuentes..."):
            msgs = []
            if wompi_file:
                ruta = _guardar_temp(wompi_file)
                r = ingestar_wompi(ruta)
                os.unlink(ruta)
                msgs.append(f"**Wompi:** {r.insertados} nuevos · {r.actualizados} actualizados · {len(r.errores)} errores")
            if liq_file:
                ruta = _guardar_temp(liq_file)
                r = ingestar_liquidacion_melonn(ruta, ref_liq or None)
                os.unlink(ruta)
                msgs.append(f"**Melonn COD:** {r.insertados} pedidos vinculados · {len(r.errores)} errores")
            if banco_file:
                ruta = _guardar_temp(banco_file)
                r = ingestar_banco(ruta)
                os.unlink(ruta)
                msgs.append(f"**Banco:** {r.insertados} movimientos · {len(r.errores)} errores")
        for m in msgs:
            st.success(m)

if btn_conciliar:
    with st.spinner("Cruzando fuentes..."):
        rc_w = conciliar_wompi_vs_pedidos()
        rc_c = conciliar_cod_vs_banco()
    st.success(
        f"Wompi: {rc_w.conciliados} ok · {rc_w.diferencias} dif · {rc_w.sin_pedido} sin pedido  |  "
        f"COD: {rc_c.conciliados} ok · {rc_c.diferencias} dif · {rc_c.sin_pago} sin ingreso"
    )

if btn_reporte:
    ruta = generar_reporte_conciliacion()
    with open(ruta, "rb") as f:
        st.download_button(
            "⬇ Descargar conciliacion.csv",
            data=f.read(),
            file_name=ruta.name,
            mime="text/csv",
        )

# ── KPIs ──────────────────────────────────────────────────────────────────────
stats = resumen_conciliacion()

k1, k2, k3, k4, k5 = st.columns(5)

pct = stats["pct_conciliado"]
color_pct = NORMAL_COLOR if pct >= 90 else (RIESGO_COLOR if pct >= 60 else CRITICO_COLOR)

with k1:
    st.markdown(f"""<div class="kpi-card" style="background:{DEEP_INK};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{stats['total_pedidos']}</p>
        <p class="kpi-label">Total pedidos</p>
        <p class="kpi-sub">{stats['conciliados']} conciliados</p></div>""", unsafe_allow_html=True)
with k2:
    st.markdown(f"""<div class="kpi-card" style="background:{color_pct};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{pct:.0f}%</p>
        <p class="kpi-label">% conciliado</p>
        <p class="kpi-sub">{stats['total_pedidos'] - stats['conciliados']} pendientes</p></div>""", unsafe_allow_html=True)
with k3:
    bg3 = CRITICO_COLOR if stats["con_diferencia"] > 0 else NORMAL_COLOR
    st.markdown(f"""<div class="kpi-card" style="background:{bg3};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{stats['con_diferencia']}</p>
        <p class="kpi-label">Con diferencia</p>
        <p class="kpi-sub">${stats['suma_diferencias']:,.0f} total</p></div>""", unsafe_allow_html=True)
with k4:
    st.markdown(f"""<div class="kpi-card kpi-extra" style="background:{COD_COLOR};">
        <p class="kpi-num">{stats['cod_recaudo_pendiente']}</p>
        <p class="kpi-label">COD por recaudar</p>
        <p class="kpi-sub">Activos en tránsito</p></div>""", unsafe_allow_html=True)
with k5:
    bg5 = RIESGO_COLOR if stats["pagos_sin_cruzar"] > 0 else NORMAL_COLOR
    st.markdown(f"""<div class="kpi-card" style="background:{bg5};border-left:4px solid {STEEL_BLUE};">
        <p class="kpi-num">{stats['pagos_sin_cruzar']}</p>
        <p class="kpi-label">Pagos sin cruzar</p>
        <p class="kpi-sub">{stats['movimientos_sin_cruzar']} mov. banco</p></div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Tabs de detalle ───────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Todos los pedidos",
    "⚠️ Diferencias",
    "💰 COD pendiente",
    "🏦 Movimientos banco",
])

# ── TAB 1: Todos los pedidos ──────────────────────────────────────────────────
with tab1:
    st.markdown(f"<div class='sec-title'>Estado de conciliación por pedido</div>", unsafe_allow_html=True)

    with get_conn() as conn:
        df_ped = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT orden_melonn, orden_shopify, nombre_cliente, ciudad_destino,
                   metodo_pago, es_contraentrega, precio_venta, valor_cod,
                   valor_desembolsado, estado_pago, estado_recaudo,
                   estado_conciliacion, diferencia, fecha_pedido, conciliado
            FROM pedidos
            ORDER BY conciliado ASC, diferencia DESC, fecha_pedido ASC
        """).fetchall()])

    if not df_ped.empty:
        df_ped["conciliado"] = df_ped["conciliado"].map({1: "✅ OK", 0: "⏳ Pendiente"})
        df_ped["es_contraentrega"] = df_ped["es_contraentrega"].map({1: "SÍ", 0: "—"})

        col_filtro, _ = st.columns([2, 3])
        with col_filtro:
            filtro_est = st.selectbox(
                "Filtrar por estado",
                ["Todos", "⏳ Pendiente", "✅ OK", "Diferencias"],
                key="filtro_concil"
            )

        df_show = df_ped.copy()
        if filtro_est == "⏳ Pendiente":
            df_show = df_show[df_show["conciliado"] == "⏳ Pendiente"]
        elif filtro_est == "✅ OK":
            df_show = df_show[df_show["conciliado"] == "✅ OK"]
        elif filtro_est == "Diferencias":
            df_show = df_show[df_show["estado_conciliacion"] == "diferencia"]

        COLS_SHOW = ["orden_melonn", "orden_shopify", "nombre_cliente", "ciudad_destino",
                     "metodo_pago", "es_contraentrega", "precio_venta", "valor_cod",
                     "valor_desembolsado", "estado_pago", "estado_conciliacion",
                     "diferencia", "fecha_pedido", "conciliado"]

        st.dataframe(
            df_show[COLS_SHOW],
            use_container_width=True,
            height=420,
            hide_index=True,
        )
        st.caption(f"{len(df_show)} pedidos mostrados")
    else:
        st.info("No hay datos de pedidos en la base de datos.")

# ── TAB 2: Diferencias ────────────────────────────────────────────────────────
with tab2:
    st.markdown("<div class='sec-title'>Pedidos con diferencias de valor</div>", unsafe_allow_html=True)

    with get_conn() as conn:
        df_dif = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT orden_melonn, orden_shopify, nombre_cliente,
                   metodo_pago, precio_venta, valor_desembolsado,
                   diferencia, estado_conciliacion, fecha_pedido, fecha_desembolso
            FROM pedidos
            WHERE estado_conciliacion = 'diferencia'
            ORDER BY ABS(diferencia) DESC
        """).fetchall()])

    if df_dif.empty:
        st.success("✅ Sin diferencias detectadas.")
    else:
        total_dif = df_dif["diferencia"].sum()
        st.markdown(f"""
        <div style="background:{CRITICO_COLOR};color:white;padding:12px 16px;
                    border-radius:4px;margin-bottom:16px;">
            <strong>{len(df_dif)} pedidos con diferencias</strong> ·
            Suma total: <strong>${total_dif:,.0f}</strong>
        </div>
        """, unsafe_allow_html=True)

        st.dataframe(
            df_dif.style.format({
                "precio_venta":       "${:,.0f}",
                "valor_desembolsado": "${:,.0f}",
                "diferencia":         "${:,.0f}",
            }),
            use_container_width=True,
            height=360,
            hide_index=True,
        )

# ── TAB 3: COD pendiente ──────────────────────────────────────────────────────
with tab3:
    st.markdown("<div class='sec-title'>Contraentregas por recaudar</div>", unsafe_allow_html=True)
    st.caption("Pedidos COD activos (aún en tránsito) con recaudo pendiente.")

    with get_conn() as conn:
        df_cod = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT orden_melonn, orden_shopify, nombre_cliente, ciudad_destino,
                   valor_cod, estado_melonn, nivel_riesgo, dias_en_transito,
                   transportadora, estado_recaudo, fecha_despacho
            FROM pedidos
            WHERE es_contraentrega = 1
              AND estado_recaudo = 'pendiente'
              AND fecha_entrega IS NULL
            ORDER BY nivel_riesgo ASC, dias_en_transito DESC
        """).fetchall()])

    if df_cod.empty:
        st.success("✅ Sin COD pendientes.")
    else:
        total_val = df_cod["valor_cod"].fillna(0).sum()

        c1, c2 = st.columns(2)
        with c1:
            st.metric("Pedidos COD activos", len(df_cod))
        with c2:
            st.metric("Valor total en tránsito", f"${total_val:,.0f}")

        st.dataframe(
            df_cod.style.format({"valor_cod": "${:,.0f}", "dias_en_transito": "{:.0f}"}),
            use_container_width=True,
            height=380,
            hide_index=True,
        )

# ── TAB 4: Movimientos bancarios ──────────────────────────────────────────────
with tab4:
    st.markdown("<div class='sec-title'>Movimientos bancarios ingresados</div>", unsafe_allow_html=True)

    with get_conn() as conn:
        df_banco = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT fecha, descripcion, valor, tipo, origen, referencia, conciliado
            FROM movimientos_banco
            ORDER BY fecha DESC, id DESC
        """).fetchall()])

    if df_banco.empty:
        st.info("No hay movimientos bancarios. Carga tu extracto en el sidebar.")
        st.markdown(f"""
        <div style="background:white;border:1px dashed {STEEL_BLUE};border-radius:4px;
                    padding:20px;text-align:center;color:{GRAPHITE_GREY};font-size:0.85rem;">
            📂 Carga el extracto bancario (.csv) en el panel lateral izquierdo<br>
            y haz clic en <strong>Ingestar fuentes</strong>
        </div>
        """, unsafe_allow_html=True)
    else:
        df_banco["conciliado"] = df_banco["conciliado"].map({1: "✅", 0: "⏳"})
        col_f, _ = st.columns([2, 3])
        with col_f:
            filtro_origen = st.selectbox(
                "Filtrar por origen",
                ["Todos"] + sorted(df_banco["origen"].dropna().unique().tolist()),
                key="filtro_banco"
            )
        df_b = df_banco if filtro_origen == "Todos" else df_banco[df_banco["origen"] == filtro_origen]

        st.dataframe(
            df_b.style.format({"valor": "${:,.0f}"}),
            use_container_width=True,
            height=360,
            hide_index=True,
        )

        ing  = df_banco[df_banco["tipo"] == "ingreso"]["valor"].sum()
        egr  = df_banco[df_banco["tipo"] == "egreso"]["valor"].sum()
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Total ingresos", f"${ing:,.0f}")
        with c2: st.metric("Total egresos",  f"${egr:,.0f}")
        with c3: st.metric("Saldo neto",     f"${ing-egr:,.0f}")

# ── Nota de ayuda ─────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"""
<div style="padding:14px 18px;background:white;border-radius:4px;
            border-left:3px solid {STEEL_BLUE};">
    <span style="font-size:0.72rem;color:{GRAPHITE_GREY};letter-spacing:1px;">
        FLUJO DE CONCILIACIÓN ·
        (1) Sube los CSVs → (2) <em>Ingestar fuentes</em> →
        (3) <em>Ejecutar conciliación</em> → (4) Revisar diferencias →
        (5) <em>Generar reporte CSV</em>
    </span>
</div>
""", unsafe_allow_html=True)
