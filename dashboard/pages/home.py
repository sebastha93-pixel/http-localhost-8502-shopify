"""
MALE'DENIM OS — Centro de Control
Importa SOLO desde shared.py — sin dependencias externas.
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
    CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR, COD_COLOR, RESUELTO_COLOR,
    MAX_DIAS_ACTIVO, cargar_datos_api, render_sidebar, _parse_cod, usuario_activo,
)

st.markdown(CSS, unsafe_allow_html=True)

# ── Guard ──────────────────────────────────────────────────────────────────────
if "logistica" not in st.session_state.get("permisos", ["logistica"]):
    st.error("🔒 Sin acceso.")
    st.stop()

# ── Sidebar ─────────────────────────────────────────────────────────────────────
render_sidebar("Centro de Control")

# ── Helpers ─────────────────────────────────────────────────────────────────────
def _fmt(v):
    if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
    if v >= 1_000:     return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"

def _kpi(value, label, sub="", color=STEEL_BLUE):
    return f"""
    <div class="kpi-card" style="border-left:3px solid {color};">
      <p class="kpi-label">{label}</p>
      <p class="kpi-num">{value}</p>
      <p class="kpi-sub">{sub}</p>
    </div>"""

def _badge(text, color, bg):
    return f"""<span style="background:{bg};color:{color};font-size:0.6rem;font-weight:700;
    letter-spacing:1.5px;text-transform:uppercase;padding:3px 9px;border-radius:20px;
    border:1px solid {color}22;">{text}</span>"""

def _alert(title, msg, color, bg, action=""):
    return f"""
    <div style="background:{bg};border:1px solid {color}22;border-left:3px solid {color};
    border-radius:10px;padding:13px 16px;margin-bottom:8px;display:flex;
    align-items:flex-start;gap:12px;">
      <div style="flex:1;">
        <p style="font-size:0.78rem;font-weight:700;color:{DEEP_INK};margin:0 0 2px 0;">{title}</p>
        <p style="font-size:0.73rem;color:{GRAPHITE_GREY};margin:0;line-height:1.4;">{msg}</p>
      </div>
      {f'<span style="font-size:0.65rem;font-weight:700;color:{color};white-space:nowrap;">{action} →</span>' if action else ""}
    </div>"""

def _card(html, padding="20px 22px", border_top=""):
    bt = f"border-top:3px solid {border_top};" if border_top else ""
    return f"""<div style="background:white;border:1px solid #E6E4E0;border-radius:12px;
    padding:{padding};box-shadow:0 1px 4px rgba(33,48,51,0.05);{bt}">{html}</div>"""

# ── Cargar datos ─────────────────────────────────────────────────────────────────
try:
    df_all, _, _meta = cargar_datos_api()
except Exception:
    df_all, _meta = pd.DataFrame(), {}

_fuente = _meta.get("fuente", "")
_fa     = _meta.get("fetched_at")
_fa_txt = _fa.strftime("%d/%m %H:%M") if _fa else "—"
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
st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:flex-end;
            margin-bottom:24px;padding-bottom:18px;border-bottom:1px solid #E6E4E0;">
  <div>
    <p style="font-size:1.55rem;font-weight:800;color:{DEEP_INK};
              letter-spacing:-0.3px;margin:0 0 3px 0;line-height:1;">
      Hola, {_user} 👋
    </p>
    <p style="font-size:0.78rem;color:{GRAPHITE_GREY};margin:0;">
      Estado general de MALE'DENIM OS · {date.today().strftime('%d de %B, %Y')}
    </p>
  </div>
  <div style="text-align:right;">
    <p style="font-size:0.6rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;
              color:{GRAPHITE_GREY};margin:0 0 2px 0;">Última sincronización</p>
    <p style="font-size:0.8rem;font-weight:600;color:{DEEP_INK};margin:0;">{_fa_txt}</p>
    {f'<p style="font-size:0.65rem;color:#036a73;margin:2px 0 0 0;">🔄 Actualizando en background</p>' if _bg_ref else ""}
  </div>
</div>
""", unsafe_allow_html=True)

# ── KPIs ─────────────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
with k1: st.markdown(_kpi(n_total, "Pedidos activos", "Total en operación", STEEL_BLUE), unsafe_allow_html=True)
with k2: st.markdown(_kpi(n_critico, "Críticos", "Acción inmediata", CRITICO_COLOR if n_critico else STEEL_BLUE), unsafe_allow_html=True)
with k3: st.markdown(_kpi(n_riesgo, "En riesgo", "Monitorear hoy", RIESGO_COLOR if n_riesgo else STEEL_BLUE), unsafe_allow_html=True)
with k4: st.markdown(_kpi(_fmt(val_cod), "Portafolio COD", "Total contraentrega", "#0C457A"), unsafe_allow_html=True)
with k5: st.markdown(_kpi(_fmt(val_riesgo), "COD en riesgo", "Recaudo comprometido", RIESGO_COLOR if val_riesgo else STEEL_BLUE), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Dos columnas ─────────────────────────────────────────────────────────────────
col_izq, col_der = st.columns([1.15, 1], gap="large")

with col_izq:
    st.markdown('<p class="sec-title">Alertas prioritarias</p>', unsafe_allow_html=True)

    alerts_html = ""
    if n_critico > 0:
        alerts_html += _alert(
            f"{n_critico} pedido{'s' if n_critico>1 else ''} en estado CRÍTICO",
            f"Superaron el SLA · Valor en riesgo: {_fmt(val_riesgo)}",
            CRITICO_COLOR, "#FDF0F0", "Ver logística"
        )
    if n_nov_cod > 0:
        alerts_html += _alert(
            f"{n_nov_cod} novedad{'es' if n_nov_cod>1 else ''} activa{'s' if n_nov_cod>1 else ''} en COD",
            "Transportadora no pudo entregar. Requieren gestión urgente.",
            RIESGO_COLOR, "#FDF4EE", "Gestionar"
        )
    if n_pend > 0:
        alerts_html += _alert(
            f"{n_pend} pedido{'s' if n_pend>1 else ''} pendiente{'s' if n_pend>1 else ''} de despacho",
            "Esperan autorización del seller en Melonn para salir.",
            "#7b6e42", "#F5F3EC", "Autorizar"
        )
    if n_nov_pre > 0:
        alerts_html += _alert(
            f"{n_nov_pre} novedad en pedidos pagados",
            "Clientes que pagaron y no han recibido. Riesgo de chargeback.",
            "#0C457A", "#EEF3FA"
        )
    if not alerts_html:
        alerts_html = _card(f"""
        <div style="text-align:center;padding:16px 0;">
          <p style="font-size:1.4rem;margin:0 0 6px 0;">✓</p>
          <p style="font-size:0.82rem;font-weight:700;color:{DEEP_INK};margin:0 0 3px 0;">Sin alertas activas</p>
          <p style="font-size:0.72rem;color:{GRAPHITE_GREY};margin:0;">Todo operando con normalidad.</p>
        </div>""")

    st.markdown(alerts_html, unsafe_allow_html=True)

with col_der:
    st.markdown('<p class="sec-title">Salud operativa</p>', unsafe_allow_html=True)

    def _semaforo_row(label, val, estado):
        cfg = {
            "ok":  ("#036a73","#EFF8F7"),
            "warn":("#7b6e42","#F5F3EC"),
            "crit":("#990012","#FDF0F0"),
        }.get(estado, (GRAPHITE_GREY,"#F4F4F2"))
        return f"""
        <div style="display:flex;justify-content:space-between;align-items:center;
                    padding:10px 0;border-bottom:1px solid #F2F0ED;">
          <span style="font-size:0.78rem;color:{DEEP_INK};font-weight:500;">{label}</span>
          <span style="background:{cfg[1]};color:{cfg[0]};font-size:0.65rem;font-weight:700;
                       letter-spacing:1px;padding:3px 10px;border-radius:20px;">{val}</span>
        </div>"""

    rows = (
        _semaforo_row("COD pendientes de despacho", str(n_pend),    "crit" if n_pend > 0 else "ok")
      + _semaforo_row("COD en tránsito",            str(n_tran),    "ok")
      + _semaforo_row("Novedades COD activas",      str(n_nov_cod), "crit" if n_nov_cod > 0 else "ok")
      + _semaforo_row("Prepago en tránsito",        str(n_tran_pre),"ok")
      + _semaforo_row("Novedades prepago",          str(n_nov_pre), "warn" if n_nov_pre > 0 else "ok")
    )
    st.markdown(_card(rows), unsafe_allow_html=True)

# ── Fila inferior ─────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
col_a, col_b, col_c = st.columns(3, gap="large")

with col_a:
    st.markdown('<p class="sec-title">Módulos del sistema</p>', unsafe_allow_html=True)
    modulos = [
        ("📦", "Logística",     "Pedidos activos y novedades",  True),
        ("💰", "Conciliación",  "Pendiente de implementar",     False),
        ("📊", "Comercial",     "Pendiente de implementar",     False),
        ("💳", "MercadoPago",   "Pendiente de implementar",     False),
    ]
    rows_html = ""
    for icon, nombre, desc, activo in modulos:
        op = "1" if activo else "0.45"
        rows_html += f"""
        <div style="display:flex;align-items:center;gap:12px;padding:10px 14px;
                    background:white;border:1px solid #E6E4E0;border-radius:9px;
                    margin-bottom:6px;opacity:{op};">
          <span style="font-size:1rem;">{icon}</span>
          <div style="flex:1;">
            <p style="font-size:0.76rem;font-weight:700;color:{DEEP_INK};margin:0;">{nombre}</p>
            <p style="font-size:0.66rem;color:{GRAPHITE_GREY};margin:0;">{desc}</p>
          </div>
          {'<span style="font-size:0.68rem;color:' + STEEL_BLUE + ';">→</span>' if activo else ""}
        </div>"""
    st.markdown(rows_html, unsafe_allow_html=True)

with col_b:
    st.markdown('<p class="sec-title">Integraciones</p>', unsafe_allow_html=True)
    integraciones = [
        ("Melonn API",   _fuente == "api_live", _fa_txt if _fuente == "api_live" else "Sin datos frescos"),
        ("Supabase",     True,                  "Conectado"),
        ("Shopify",      False,                 "Pendiente"),
        ("MercadoPago",  False,                 "Pendiente"),
        ("Wompi",        False,                 "Pendiente"),
    ]
    rows_html = ""
    for nombre, ok, estado_txt in integraciones:
        dot = "#036a73" if ok else "#D4D2CE"
        rows_html += f"""
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:9px 14px;background:white;border:1px solid #E6E4E0;
                    border-radius:9px;margin-bottom:5px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <div style="width:7px;height:7px;border-radius:50%;background:{dot};flex-shrink:0;"></div>
            <span style="font-size:0.76rem;font-weight:600;color:{DEEP_INK};">{nombre}</span>
          </div>
          <span style="font-size:0.64rem;color:{GRAPHITE_GREY};">{estado_txt}</span>
        </div>"""
    st.markdown(rows_html, unsafe_allow_html=True)

with col_c:
    st.markdown('<p class="sec-title">Distribución COD activo</p>', unsafe_allow_html=True)
    if not df_cod.empty and len(df_cod) > 0:
        total_cod = len(df_cod)
        items = [
            ("Pendientes",   n_pend,    "#7b6e42"),
            ("En tránsito",  n_tran,    "#0C457A"),
            ("Novedades",    n_nov_cod, RIESGO_COLOR),
        ]
        rows_html = ""
        for label, n, color in items:
            pct = round(n / total_cod * 100) if total_cod > 0 else 0
            bar_w = max(2, pct)
            rows_html += f"""
            <div style="margin-bottom:14px;">
              <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
                <span style="font-size:0.74rem;font-weight:600;color:{DEEP_INK};">{label}</span>
                <span style="font-size:0.7rem;color:{GRAPHITE_GREY};">{n} · {pct}%</span>
              </div>
              <div style="background:#F2F0ED;border-radius:99px;height:5px;overflow:hidden;">
                <div style="background:{color};width:{bar_w}%;height:100%;border-radius:99px;"></div>
              </div>
            </div>"""
        st.markdown(_card(rows_html), unsafe_allow_html=True)
    else:
        st.markdown(_card(f"""
        <p style="font-size:0.76rem;color:{GRAPHITE_GREY};text-align:center;margin:8px 0;">
          Sin datos — presiona ↻ Actualizar</p>"""), unsafe_allow_html=True)

# ── Recomendaciones ───────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<p class="sec-title">Recomendaciones operativas</p>', unsafe_allow_html=True)

rec_cols = st.columns(3, gap="large")
recs = [
    (RIESGO_COLOR,  "Novedades transportadora",
     f"{n_nov_cod} pedido{'s' if n_nov_cod!=1 else ''} con 'Delivery not posible'. "
     "Contactar cliente para verificar dirección antes de re-intentar entrega.",
     "Gestionar novedades"),
    ("#0C457A", "Pedidos pendientes de despacho",
     f"{n_pend} pedido{'s' if n_pend!=1 else ''} esperan autorización seller en Melonn. "
     "Revisar y autorizar para no perder la ventana de entrega del día.",
     "Autorizar en Melonn"),
    (NORMAL_COLOR, "Portafolio COD activo",
     f"{_fmt(val_cod)} en COD con {n_tran} pedidos en tránsito. "
     "Hacer seguimiento a los pedidos críticos para asegurar el recaudo.",
     "Ver en tránsito"),
]
for col, (color, titulo, texto, accion) in zip(rec_cols, recs):
    with col:
        st.markdown(f"""
        <div style="background:white;border:1px solid #E6E4E0;border-radius:12px;
                    padding:20px 22px;border-top:3px solid {color};
                    box-shadow:0 1px 4px rgba(33,48,51,0.05);">
          <p style="font-size:0.58rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;
                    color:{color};margin:0 0 8px 0;">Recomendación</p>
          <p style="font-size:0.84rem;font-weight:700;color:{DEEP_INK};margin:0 0 8px 0;">{titulo}</p>
          <p style="font-size:0.74rem;color:{GRAPHITE_GREY};line-height:1.5;margin:0 0 14px 0;">{texto}</p>
          <span style="font-size:0.67rem;font-weight:700;color:{color};">{accion} →</span>
        </div>
        """, unsafe_allow_html=True)
