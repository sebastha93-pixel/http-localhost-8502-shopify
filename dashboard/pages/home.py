"""
MALE'DENIM OS — Centro de Control
v2 — componentes editoriales del Iteración 1.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import streamlit as st
import pandas as pd
from datetime import date

from shared import (
    CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY,
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR, RESUELTO_COLOR,
    cargar_datos_api, _parse_cod,
    md_header, md_section, md_kpi, md_badge, md_alert, md_empty,
)

st.markdown(CSS, unsafe_allow_html=True)

# ── Guard ──────────────────────────────────────────────────────────────────────
if "logistica" not in st.session_state.get("permisos", ["logistica"]):
    st.error("🔒 Sin acceso.")
    st.stop()

# ── Helpers ─────────────────────────────────────────────────────────────────────
def _fmt(v):
    if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
    if v >= 1_000:     return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"

# ── Cargar datos ─────────────────────────────────────────────────────────────────
try:
    df_all, _, _meta = cargar_datos_api()
except Exception:
    df_all, _meta = pd.DataFrame(), {}

_fuente = _meta.get("fuente", "")
_fa     = _meta.get("fetched_at")
_fa_txt = _fa.strftime("%d/%m · %H:%M") if _fa else "—"
_bg_ref = _meta.get("bg_refresh", False)

if not df_all.empty:
    df_cod = df_all[df_all["Tipo_Recaudo"] == "Contraentrega"]
    df_pre = df_all[df_all["Tipo_Recaudo"] == "Prepago"]
    n_pend    = len(df_cod[df_cod["Estado_Code"].isin([26, 29])])
    n_tran    = len(df_cod[df_cod["Estado_Code"].isin([5, 7, 24, 28])])
    n_nov_cod = len(df_cod[df_cod["Sub_Estado"] == "novedad"])
    n_nov_pre = len(df_pre[df_pre["Sub_Estado"] == "novedad"])
    n_tran_pre= len(df_pre[df_pre["Sub_Estado"] == "en_transito"])
    n_critico = len(df_all[df_all["Nivel"] == "CRITICO"])
    n_riesgo  = len(df_all[df_all["Nivel"] == "RIESGO"])
    val_cod   = df_cod["Valor COD"].apply(_parse_cod).sum()
    val_riesgo= (df_cod[df_cod["Nivel"].isin(["CRITICO","RIESGO"])]["Valor COD"].apply(_parse_cod).sum())
    n_total   = len(df_all)
else:
    n_pend = n_tran = n_nov_cod = n_nov_pre = n_tran_pre = 0
    n_critico = n_riesgo = n_total = 0
    val_cod = val_riesgo = 0
    df_cod = df_pre = pd.DataFrame()

# ── Header ───────────────────────────────────────────────────────────────────────
_user = (st.session_state.get("name") or st.session_state.get("username") or "Equipo").split()[0]

_meta_extra = ""
if _bg_ref:
    _meta_extra = '<p style="font-size:0.62rem;color:#036A73;margin:3px 0 0 0;font-weight:600;">● Actualizando en background</p>'

md_header(
    title=f"Hola, {_user}",
    subtitle=f"Estado general de MALE'DENIM OS · {date.today().strftime('%d de %B, %Y')}",
    meta_label="Última sincronización",
    meta_value=_fa_txt,
    meta_extra=_meta_extra,
)

# ── KPIs superiores ──────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)

with k1:
    st.markdown(md_kpi(
        str(n_total), "Pedidos activos", "Total en operación",
        accent=STEEL_BLUE,
    ), unsafe_allow_html=True)
with k2:
    st.markdown(md_kpi(
        str(n_critico), "Críticos", "Acción inmediata",
        accent="#990012" if n_critico else STEEL_BLUE,
    ), unsafe_allow_html=True)
with k3:
    st.markdown(md_kpi(
        str(n_riesgo), "En riesgo", "Monitorear hoy",
        accent="#B95902" if n_riesgo else STEEL_BLUE,
    ), unsafe_allow_html=True)
with k4:
    st.markdown(md_kpi(
        _fmt(val_cod), "Portafolio COD", "Total contraentrega",
        accent="#0C457A",
    ), unsafe_allow_html=True)
with k5:
    st.markdown(md_kpi(
        _fmt(val_riesgo), "COD en riesgo", "Recaudo comprometido",
        accent="#B95902" if val_riesgo else STEEL_BLUE,
    ), unsafe_allow_html=True)

# ── Dos columnas: Alertas + Salud ────────────────────────────────────────────────
col_izq, col_der = st.columns([1.15, 1], gap="large")

with col_izq:
    md_section("Alertas prioritarias", "Lo que necesita atención ahora")

    alerts = []
    if n_critico > 0:
        alerts.append(md_alert(
            f"{n_critico} pedido{'s' if n_critico>1 else ''} en estado CRÍTICO",
            f"Superaron el SLA · Valor en riesgo: {_fmt(val_riesgo)}",
            level="critico", action="Ver logística",
        ))
    if n_nov_cod > 0:
        alerts.append(md_alert(
            f"{n_nov_cod} novedad{'es' if n_nov_cod>1 else ''} activa{'s' if n_nov_cod>1 else ''} en COD",
            "Transportadora no pudo entregar. Requieren gestión urgente.",
            level="riesgo", action="Gestionar",
        ))
    if n_pend > 0:
        alerts.append(md_alert(
            f"{n_pend} pedido{'s' if n_pend>1 else ''} pendiente{'s' if n_pend>1 else ''} de despacho",
            "Esperan autorización del seller en Melonn para salir.",
            level="pendiente", action="Autorizar",
        ))
    if n_nov_pre > 0:
        alerts.append(md_alert(
            f"{n_nov_pre} novedad en pedidos pagados",
            "Clientes que pagaron y no han recibido. Riesgo de chargeback.",
            level="info",
        ))

    if alerts:
        st.markdown("".join(alerts), unsafe_allow_html=True)
    else:
        md_empty("Sin alertas activas", "Todo está operando con normalidad.", icon="✓")

with col_der:
    md_section("Salud operativa", f"Actualizado: {_fa_txt}")

    def _row(label, val, level):
        return f"""
        <div style="display:flex;justify-content:space-between;align-items:center;
                    padding:11px 0;border-bottom:1px solid #F2F0EC;">
          <span style="font-size:0.78rem;color:{DEEP_INK};font-weight:500;">{label}</span>
          {md_badge(str(val), level)}
        </div>"""

    rows = (
          _row("COD pendientes de despacho", n_pend,    "critico" if n_pend > 0 else "normal")
        + _row("COD en tránsito",            n_tran,    "info")
        + _row("Novedades COD activas",      n_nov_cod, "critico" if n_nov_cod > 0 else "normal")
        + _row("Prepago en tránsito",        n_tran_pre,"info")
        + _row("Novedades prepago",          n_nov_pre, "pendiente" if n_nov_pre > 0 else "normal")
    )
    st.markdown(f'<div class="md-card">{rows}</div>', unsafe_allow_html=True)

# ── Fila inferior ─────────────────────────────────────────────────────────────────
col_a, col_b, col_c = st.columns(3, gap="large")

with col_a:
    md_section("Módulos del sistema")
    modulos = [
        ("📦", "Logística",     "Pedidos activos y novedades",  True),
        ("💰", "Conciliación",  "Próximamente",                 False),
        ("📊", "Comercial",     "Próximamente",                 False),
        ("💳", "MercadoPago",   "Próximamente",                 False),
    ]
    rows_html = ""
    for icon, nombre, desc, activo in modulos:
        op = "1" if activo else "0.45"
        arrow = f'<span style="font-size:0.7rem;color:{STEEL_BLUE};">→</span>' if activo else ""
        rows_html += f"""
        <div style="display:flex;align-items:center;gap:12px;padding:10px 14px;
                    background:white;border:1px solid #E6E4E0;border-radius:10px;
                    margin-bottom:6px;opacity:{op};">
          <span style="font-size:1rem;">{icon}</span>
          <div style="flex:1;">
            <p style="font-size:0.78rem;font-weight:700;color:{DEEP_INK};margin:0;">{nombre}</p>
            <p style="font-size:0.66rem;color:{GRAPHITE_GREY};margin:0;">{desc}</p>
          </div>
          {arrow}
        </div>"""
    st.markdown(rows_html, unsafe_allow_html=True)

with col_b:
    md_section("Integraciones")
    integraciones = [
        ("Melonn API",   _fuente == "api_live", _fa_txt if _fuente == "api_live" else "Sin datos frescos"),
        ("Supabase",     True,                  "Conectado"),
        ("Shopify",      False,                 "Pendiente"),
        ("MercadoPago",  False,                 "Pendiente"),
        ("Wompi",        False,                 "Pendiente"),
    ]
    rows_html = ""
    for nombre, ok, estado_txt in integraciones:
        dot = "#036A73" if ok else "#D4D2CE"
        rows_html += f"""
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:9px 14px;background:white;border:1px solid #E6E4E0;
                    border-radius:10px;margin-bottom:6px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <div style="width:7px;height:7px;border-radius:50%;background:{dot};flex-shrink:0;"></div>
            <span style="font-size:0.78rem;font-weight:600;color:{DEEP_INK};">{nombre}</span>
          </div>
          <span style="font-size:0.64rem;color:{GRAPHITE_GREY};">{estado_txt}</span>
        </div>"""
    st.markdown(rows_html, unsafe_allow_html=True)

with col_c:
    md_section("Distribución COD activo")
    if not df_cod.empty and len(df_cod) > 0:
        total_cod = len(df_cod)
        items = [
            ("Pendientes",   n_pend,    "#7B6E42"),
            ("En tránsito",  n_tran,    "#0C457A"),
            ("Novedades",    n_nov_cod, "#B95902"),
        ]
        bars_html = ""
        for label, n, color in items:
            pct = round(n / total_cod * 100) if total_cod > 0 else 0
            w   = max(2, pct)
            bars_html += f"""
            <div style="margin-bottom:14px;">
              <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
                <span style="font-size:0.74rem;font-weight:600;color:{DEEP_INK};">{label}</span>
                <span style="font-size:0.7rem;color:{GRAPHITE_GREY};">{n} · {pct}%</span>
              </div>
              <div style="background:#F2F0EC;border-radius:99px;height:5px;overflow:hidden;">
                <div style="background:{color};width:{w}%;height:100%;border-radius:99px;"></div>
              </div>
            </div>"""
        st.markdown(f'<div class="md-card">{bars_html}</div>', unsafe_allow_html=True)
    else:
        md_empty("Sin datos", "Presiona ↻ Actualizar", icon="○")

# ── Recomendaciones ───────────────────────────────────────────────────────────────
md_section("Recomendaciones operativas", "Inteligencia automática del sistema")

rec_cols = st.columns(3, gap="large")
recs = [
    ("#B95902", "Novedades transportadora",
     f"{n_nov_cod} pedido{'s' if n_nov_cod!=1 else ''} con 'Delivery not posible'. "
     "Contactar cliente para verificar dirección antes de re-intentar entrega.",
     "Gestionar novedades"),
    ("#0C457A", "Pedidos pendientes de despacho",
     f"{n_pend} pedido{'s' if n_pend!=1 else ''} esperan autorización seller en Melonn. "
     "Revisar y autorizar para no perder la ventana de entrega del día.",
     "Autorizar en Melonn"),
    ("#036A73", "Portafolio COD activo",
     f"{_fmt(val_cod)} en COD con {n_tran} pedidos en tránsito. "
     "Hacer seguimiento a los críticos para asegurar el recaudo.",
     "Ver en tránsito"),
]
for col, (color, titulo, texto, accion) in zip(rec_cols, recs):
    with col:
        st.markdown(f"""
        <div class="md-card md-card--accent-top" style="border-top-color:{color};height:100%;">
          <p style="font-size:0.55rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;
                    color:{color};margin:0 0 8px 0;">Recomendación</p>
          <p style="font-size:0.85rem;font-weight:700;color:{DEEP_INK};margin:0 0 8px 0;">{titulo}</p>
          <p style="font-size:0.74rem;color:{GRAPHITE_GREY};line-height:1.5;margin:0 0 14px 0;">{texto}</p>
          <span style="font-size:0.66rem;font-weight:700;color:{color};">{accion} →</span>
        </div>
        """, unsafe_allow_html=True)
