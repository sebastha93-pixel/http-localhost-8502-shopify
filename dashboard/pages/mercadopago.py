"""
MercadoPago — MALE DENIM OS
Sincronización y conciliación de pagos MercadoPago.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from shared import CSS, DEEP_INK, STEEL_BLUE, NORMAL_COLOR, CRITICO_COLOR, RIESGO_COLOR, SOFT_CONCRETE
import mp_client
from db import get_conn

st.markdown(CSS, unsafe_allow_html=True)

# Guard: solo usuarios con acceso al módulo mercadopago
if "mercadopago" not in st.session_state.get("permisos", ["mercadopago"]):
    st.error("🔒 No tienes acceso al módulo MercadoPago.")
    st.stop()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="padding:18px 0 6px 0; border-bottom:2px solid {STEEL_BLUE}22; margin-bottom:20px;">
  <span style="font-size:0.6rem; letter-spacing:3px; color:{STEEL_BLUE}; font-weight:700; text-transform:uppercase;">
    MALE DENIM OS · FINANZAS
  </span><br>
  <span style="font-size:1.6rem; font-weight:800; color:{DEEP_INK}; letter-spacing:-0.5px;">
    MercadoPago
  </span>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"<p style='color:{STEEL_BLUE};font-size:0.7rem;letter-spacing:2px;font-weight:700;text-transform:uppercase;'>SINCRONIZACIÓN</p>", unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        fecha_desde = st.date_input("Desde", value=datetime.now().date() - timedelta(days=90), key="mp_desde")
    with col_b:
        fecha_hasta = st.date_input("Hasta", value=datetime.now().date(), key="mp_hasta")

    if st.button("↻ Sincronizar pagos", use_container_width=True, type="primary"):
        with st.spinner("Descargando pagos de MercadoPago..."):
            try:
                resultado = mp_client.sincronizar_pagos_mp(
                    fecha_desde=str(fecha_desde),
                    fecha_hasta=str(fecha_hasta),
                )
                st.session_state["mp_sync_resultado"] = resultado
                st.success("Sincronización completada")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    # Resultado de última sync
    if "mp_sync_resultado" in st.session_state:
        r = st.session_state["mp_sync_resultado"]
        st.markdown("---")
        st.markdown(f"<p style='color:{STEEL_BLUE};font-size:0.65rem;letter-spacing:1.5px;font-weight:700;'>ÚLTIMA SINCRONIZACIÓN</p>", unsafe_allow_html=True)
        st.markdown(f"**{r['total_mp']}** pagos en MP · **{r['nuevos']}** nuevos")
        st.markdown(f"✅ {r['matcheados']} matcheados · ⚠️ {r['sin_match']} sin match")
        if r['nuevos'] > 0:
            st.markdown(f"**Tasa match:** {r['tasa_match']}%")
        if r['errores']:
            st.warning(f"{r['errores']} errores")


# ── Stats generales ───────────────────────────────────────────────────────────
try:
    stats = mp_client.stats_mp()
except Exception as e:
    stats = None
    st.error(f"Error cargando stats: {e}")

if stats:
    c1, c2, c3, c4 = st.columns(4)

    def _kpi(col, label, val, sub="", color=DEEP_INK):
        col.markdown(f"""
        <div style="background:white;padding:16px 18px;border-radius:8px;
                    border:1px solid {STEEL_BLUE}22;box-shadow:0 1px 4px rgba(0,0,0,0.05);">
          <div style="font-size:0.6rem;letter-spacing:2px;color:{STEEL_BLUE};font-weight:700;text-transform:uppercase;">{label}</div>
          <div style="font-size:1.6rem;font-weight:800;color:{color};margin:4px 0 2px;">{val}</div>
          <div style="font-size:0.72rem;color:#888;">{sub}</div>
        </div>
        """, unsafe_allow_html=True)

    _kpi(c1, "Total pagos", stats["total"], f"Último: {stats['ultima_transaccion'] or 'N/A'}")
    _kpi(c2, "Matcheados", stats["matcheados"], f"{stats['tasa_match']}% tasa de match", NORMAL_COLOR)
    _kpi(c3, "Sin match", stats["sin_match"], "Revisión manual pendiente",
         CRITICO_COLOR if stats["sin_match"] > 0 else DEEP_INK)

    valor_fmt = f"${stats['valor_total']:,.0f}".replace(",", ".")
    _kpi(c4, "Valor total", valor_fmt, "COP · pagos aprobados")

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📋 Todos los pagos", "⚠️ Sin match", "✅ Conciliados"])

# Cargar datos
@st.cache_data(ttl=120)
def _load_pagos():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                pp.referencia_plataforma AS mp_id,
                pp.fecha_transaccion     AS fecha,
                pp.valor_bruto           AS valor,
                pp.comision,
                pp.valor_neto,
                pp.estado,
                pp.conciliado,
                pp.orden_shopify,
                p.nombre_cliente,
                p.email_cliente,
                p.estado_melonn
            FROM pagos_plataforma pp
            LEFT JOIN pedidos p ON pp.pedido_id = p.id
            WHERE pp.plataforma = 'mercadopago'
            ORDER BY pp.fecha_transaccion DESC
        """).fetchall()
    return pd.DataFrame([dict(r) for r in rows])

try:
    df = _load_pagos()
except Exception as e:
    df = pd.DataFrame()
    st.error(f"Error cargando pagos: {e}")

with tab1:
    if df.empty:
        st.info("No hay pagos sincronizados aún. Usa el botón **↻ Sincronizar pagos** en el sidebar.")
    else:
        # Formateo para mostrar
        df_show = df.copy()
        df_show["valor"] = df_show["valor"].apply(lambda x: f"${x:,.0f}".replace(",", ".") if pd.notna(x) else "")
        df_show["comision"] = df_show["comision"].apply(lambda x: f"${x:,.0f}".replace(",", ".") if pd.notna(x) else "")
        df_show["valor_neto"] = df_show["valor_neto"].apply(lambda x: f"${x:,.0f}".replace(",", ".") if pd.notna(x) else "")
        df_show["match"] = df_show["conciliado"].apply(lambda x: "✅" if x else "⚠️")

        cols = ["fecha", "mp_id", "valor", "comision", "valor_neto", "orden_shopify", "nombre_cliente", "match"]
        st.dataframe(
            df_show[cols].rename(columns={
                "fecha": "Fecha", "mp_id": "MP ID", "valor": "Valor bruto",
                "comision": "Comisión", "valor_neto": "Neto", "orden_shopify": "Orden Shopify",
                "nombre_cliente": "Cliente", "match": "Match",
            }),
            use_container_width=True,
            height=480,
        )

with tab2:
    df_sin = df[df["conciliado"] == 0] if not df.empty else pd.DataFrame()
    if df_sin.empty:
        st.success("Todos los pagos tienen pedido asociado. 🎉")
    else:
        st.warning(f"**{len(df_sin)} pagos** sin pedido asociado. Revisar manualmente.")
        df_sin_show = df_sin[["fecha", "mp_id", "valor", "email_cliente"]].copy()
        df_sin_show["valor"] = df_sin_show["valor"].apply(lambda x: f"${x:,.0f}".replace(",", ".") if pd.notna(x) else "")
        st.dataframe(
            df_sin_show.rename(columns={
                "fecha": "Fecha", "mp_id": "MP ID", "valor": "Valor", "email_cliente": "Email pagador",
            }),
            use_container_width=True,
        )

with tab3:
    df_ok = df[df["conciliado"] == 1] if not df.empty else pd.DataFrame()
    if df_ok.empty:
        st.info("Aún no hay pagos conciliados.")
    else:
        valor_total = df_ok["valor"].sum() if "valor" in df_ok else 0
        st.markdown(f"**{len(df_ok)} pagos conciliados** · Total: **${valor_total:,.0f}** COP".replace(",", "."))

        df_ok_show = df_ok[["fecha", "mp_id", "valor", "valor_neto", "orden_shopify", "nombre_cliente", "estado_melonn"]].copy()
        df_ok_show["valor"] = df_ok_show["valor"].apply(lambda x: f"${x:,.0f}".replace(",", ".") if pd.notna(x) else "")
        df_ok_show["valor_neto"] = df_ok_show["valor_neto"].apply(lambda x: f"${x:,.0f}".replace(",", ".") if pd.notna(x) else "")
        st.dataframe(
            df_ok_show.rename(columns={
                "fecha": "Fecha", "mp_id": "MP ID", "valor": "Valor bruto",
                "valor_neto": "Neto", "orden_shopify": "Orden Shopify",
                "nombre_cliente": "Cliente", "estado_melonn": "Estado logístico",
            }),
            use_container_width=True,
            height=480,
        )
