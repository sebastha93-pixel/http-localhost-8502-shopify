"""
MALE'DENIM OS — Inteligencia
Hallazgos automáticos sobre los datos vivos de Melonn + Shopify.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import unicodedata
from datetime import datetime, date, timedelta
from collections import Counter, defaultdict

import streamlit as st
import pandas as pd

from shared import (
    CSS, DEEP_INK, GRAPHITE_GREY, STEEL_BLUE,
    cargar_datos_api, _parse_cod,
    dash_hero, dash_section, dash_card_start, dash_card_end,
    dash_kpi, dash_rec_card,
)

st.markdown(CSS, unsafe_allow_html=True)

# ── Guard ──────────────────────────────────────────────────────────────────────
if "logistica" not in st.session_state.get("permisos", ["logistica"]):
    st.error("🔒 Sin acceso.")
    st.stop()


# ── Helpers ──────────────────────────────────────────────────────────────────────
def _norm(s):
    if not isinstance(s, str) or not s.strip():
        return "—"
    nfkd = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return nfkd.strip().title()


def _fmt_pct(v): return f"{v:+.1f}%" if v else "0%"


def _shopify_top_cached() -> list:
    """Top productos cacheado desde el módulo home (si ya estaba calculado)."""
    return st.session_state.get("_shopify_top", []) or []


def _ventas_serie_cached() -> list:
    """Serie de ventas cacheada (si home.py la cargó)."""
    snap = st.session_state.get("_shopify_snap") or {}
    return snap.get("serie") or []


# ── Header ──────────────────────────────────────────────────────────────────────
dash_hero(
    "Inteligencia",
    "Hallazgos automáticos sobre operación, ventas y logística — accionables.",
    tools_html='<div class="dash-toolbtn">🧠 Última actualización: ahora</div>',
)

# ── Cargar datos ─────────────────────────────────────────────────────────────────
try:
    df_all, _, _meta = cargar_datos_api()
except Exception:
    df_all, _meta = pd.DataFrame(), {}

if df_all.empty:
    st.markdown(
        '<div class="md-empty"><div class="md-empty__icon">○</div>'
        '<p class="md-empty__title">Sin datos para analizar</p>'
        '<p class="md-empty__sub">Presiona ↻ Actualizar datos en el sidebar.</p>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# Normalizar columnas para análisis
df_all = df_all.copy()
df_all["CiudadN"] = df_all["Ciudad"].apply(_norm)
df_all["Valor_num"] = df_all["Valor COD"].apply(_parse_cod)

df_cod = df_all[df_all["Tipo_Recaudo"] == "Contraentrega"]
df_pre = df_all[df_all["Tipo_Recaudo"] == "Prepago"]

# ════════════════════════════════════════════════════════════════════════════════
# GENERAR HALLAZGOS
# ════════════════════════════════════════════════════════════════════════════════
hallazgos = []   # cada uno: dict con titulo, body, recomendacion, tone, severidad, area


# ── Hallazgo 1: Ciudades con más concentración de novedades ──────────────────────
nov_por_ciudad = (
    df_all[df_all["Sub_Estado"] == "novedad"]
    .groupby("CiudadN").size()
    .sort_values(ascending=False)
)
total_por_ciudad = df_all.groupby("CiudadN").size()

if len(nov_por_ciudad) > 0:
    # Tasa de novedad por ciudad (novedades / total)
    tasas = []
    for ciudad, n_nov in nov_por_ciudad.items():
        if ciudad == "—": continue
        total = total_por_ciudad.get(ciudad, 1)
        if total >= 5:   # mínimo 5 pedidos para que sea significativo
            tasas.append((ciudad, n_nov, total, n_nov / total * 100))
    tasas.sort(key=lambda x: x[3], reverse=True)

    if tasas:
        peor = tasas[0]
        avg_tasa = sum(t[3] for t in tasas) / len(tasas)
        diff = peor[3] - avg_tasa
        if diff >= 5:   # solo reportar si está 5pp por encima del promedio
            hallazgos.append({
                "icon": "📍",
                "titulo": f"{peor[0]} tiene {peor[3]:.0f}% de novedades — {diff:+.0f}pp sobre promedio",
                "body": (
                    f"<b>{peor[1]}</b> de los <b>{peor[2]}</b> pedidos activos en "
                    f"<b>{peor[0]}</b> presentan novedad. El promedio del país es "
                    f"<b>{avg_tasa:.1f}%</b>."
                ),
                "recomendacion": "Revisar transportadora asignada en esa zona y validar direcciones antes de despachar.",
                "tone": "red",
                "severidad": 3,
                "area": "Logística",
            })


# ── Hallazgo 2: Pedidos con muchos días en tránsito (riesgo VENCIDO) ────────────
df_lentos = df_all[df_all["Días"] > 12]
if len(df_lentos) >= 3:
    valor_lento_cod = float(df_lentos[df_lentos["Tipo_Recaudo"] == "Contraentrega"]["Valor_num"].sum())
    hallazgos.append({
        "icon": "🐢",
        "titulo": f"{len(df_lentos)} pedidos con más de 12 días en tránsito",
        "body": (
            f"Hay <b>{len(df_lentos)} pedidos activos</b> que llevan más de 12 días sin "
            f"confirmar entrega. Valor COD comprometido: <b>${valor_lento_cod:,.0f}</b>."
        ),
        "recomendacion": "Llamar a la transportadora para confirmar estado real y, si es necesario, marcar como entregados.",
        "tone": "orange",
        "severidad": 2,
        "area": "Logística",
    })


# ── Hallazgo 3: Transportadoras con tasa de novedad alta ─────────────────────────
if "Método Envío" in df_all.columns:
    trans_stats = []
    for trans, group in df_all.groupby("Método Envío"):
        if not trans or len(group) < 10:
            continue
        n_nov = (group["Sub_Estado"] == "novedad").sum()
        tasa  = n_nov / len(group) * 100
        trans_stats.append((trans, len(group), n_nov, tasa))
    trans_stats.sort(key=lambda x: x[3], reverse=True)
    if trans_stats and trans_stats[0][3] >= 8:
        peor_t = trans_stats[0]
        hallazgos.append({
            "icon": "🚚",
            "titulo": f"Transportadora '{peor_t[0]}' con {peor_t[3]:.0f}% de novedades",
            "body": (
                f"De <b>{peor_t[1]} envíos</b> con <b>{peor_t[0]}</b>, "
                f"<b>{peor_t[2]}</b> presentan novedad. Tasa: <b>{peor_t[3]:.1f}%</b>."
            ),
            "recomendacion": "Evaluar acuerdo SLA con el operador o reasignar zonas conflictivas a otra transportadora.",
            "tone": "orange",
            "severidad": 2,
            "area": "Logística",
        })


# ── Hallazgo 4: Concentración del portafolio COD ────────────────────────────────
val_cod_total = float(df_cod["Valor_num"].sum())
val_cod_riesgo = float(df_cod[df_cod["Nivel"].isin(["CRITICO", "RIESGO"])]["Valor_num"].sum())
if val_cod_total > 0:
    pct_riesgo = val_cod_riesgo / val_cod_total * 100
    if pct_riesgo >= 5:
        hallazgos.append({
            "icon": "💰",
            "titulo": f"{pct_riesgo:.0f}% del COD activo en pedidos críticos/riesgo",
            "body": (
                f"<b>${val_cod_riesgo:,.0f}</b> de los <b>${val_cod_total:,.0f}</b> "
                f"en COD activo están en pedidos clasificados como crítico o riesgo."
            ),
            "recomendacion": "Priorizar contacto con clientes de los pedidos críticos antes del cierre del día.",
            "tone": "red" if pct_riesgo >= 10 else "orange",
            "severidad": 3 if pct_riesgo >= 10 else 2,
            "area": "Finanzas",
        })


# ── Hallazgo 5: Ratio COD vs Prepago ─────────────────────────────────────────────
if len(df_all) > 0:
    pct_cod = len(df_cod) / len(df_all) * 100
    if pct_cod >= 30:
        hallazgos.append({
            "icon": "💵",
            "titulo": f"{pct_cod:.0f}% de la operación es contra entrega",
            "body": (
                f"<b>{len(df_cod)}</b> de los <b>{len(df_all)}</b> pedidos activos son COD. "
                f"Esto implica capital flotante hasta que se recauda."
            ),
            "recomendacion": "Promover métodos de pago previos con descuentos para reducir capital de trabajo.",
            "tone": "blue",
            "severidad": 1,
            "area": "Finanzas",
        })


# ── Hallazgo 6: Top producto de Shopify ─────────────────────────────────────────
top_prods = _shopify_top_cached()
if top_prods and len(top_prods) >= 2:
    top1 = top_prods[0]
    rev1 = top1.get("revenue", 0)
    if rev1 > 0:
        hallazgos.append({
            "icon": "⭐",
            "titulo": f"'{top1.get('nombre','—')[:36]}' es el producto líder",
            "body": (
                f"Revenue últimos 7 días: <b>${rev1:,.0f}</b> · "
                f"<b>{top1.get('unidades',0)} unidades</b> vendidas. "
                f"Representa el <b>{top1.get('pct_del_total',0):.1f}%</b> de las ventas."
            ),
            "recomendacion": "Asegurar stock y considerar aumentar pauta en este SKU.",
            "tone": "green",
            "severidad": 1,
            "area": "Comercial",
        })


# ── Hallazgo 7: Tendencia de ventas (de Shopify) ────────────────────────────────
serie = _ventas_serie_cached()
if len(serie) >= 7:
    ultimos_3 = sum(serie[-3:]) / 3
    previos_3 = sum(serie[-7:-4]) / 3 if len(serie) >= 7 else ultimos_3
    if previos_3 > 0:
        cambio = (ultimos_3 - previos_3) / previos_3 * 100
        if abs(cambio) >= 15:
            tendencia = "alza" if cambio > 0 else "baja"
            hallazgos.append({
                "icon": "📈" if cambio > 0 else "📉",
                "titulo": f"Ventas con tendencia a la {tendencia} ({cambio:+.0f}%)",
                "body": (
                    f"Promedio últimos 3 días: <b>${ultimos_3:,.0f}</b>. "
                    f"Promedio 3 días previos: <b>${previos_3:,.0f}</b>. "
                    f"Cambio: <b>{cambio:+.1f}%</b>."
                ),
                "recomendacion": (
                    "Revisar pauta y stock disponible." if cambio > 0
                    else "Revisar pauta de marketing y campañas activas."
                ),
                "tone": "green" if cambio > 0 else "orange",
                "severidad": 2 if cambio < 0 else 1,
                "area": "Comercial",
            })


# ── Hallazgo 8: Pedidos pendientes de despacho ─────────────────────────────────
n_pend = len(df_cod[df_cod["Estado_Code"].isin([26, 29])])
if n_pend >= 3:
    hallazgos.append({
        "icon": "⏱",
        "titulo": f"{n_pend} pedidos esperan autorización del seller",
        "body": (
            f"Hay <b>{n_pend} pedidos COD</b> en estado "
            f"'Alistamiento en espera · Seller'. Esperan acción manual en Melonn."
        ),
        "recomendacion": "Autorizar los despachos desde el módulo Logística → Pendientes para no perder ventana de entrega.",
        "tone": "khaki",
        "severidad": 2,
        "area": "Logística",
    })


# Ordenar por severidad
hallazgos.sort(key=lambda h: -h["severidad"])


# ════════════════════════════════════════════════════════════════════════════════
# RENDER
# ════════════════════════════════════════════════════════════════════════════════
# KPIs
n_critico = sum(1 for h in hallazgos if h["severidad"] == 3)
n_alto    = sum(1 for h in hallazgos if h["severidad"] == 2)
n_info    = sum(1 for h in hallazgos if h["severidad"] == 1)
areas     = len({h["area"] for h in hallazgos}) or 1

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(dash_kpi(
        "HALLAZGOS TOTALES", str(len(hallazgos)),
        meta=f"Analizados {len(df_all)} pedidos",
    ), unsafe_allow_html=True)
with k2:
    st.markdown(dash_kpi(
        "ACCIÓN URGENTE", str(n_critico),
        meta="Severidad alta",
        meta_dir="down" if n_critico else "",
        value_danger=n_critico > 0,
    ), unsafe_allow_html=True)
with k3:
    st.markdown(dash_kpi(
        "ATENCIÓN", str(n_alto),
        meta="Severidad media",
    ), unsafe_allow_html=True)
with k4:
    st.markdown(dash_kpi(
        "ÁREAS CON HALLAZGOS", str(areas),
        meta="Logística, Finanzas, Comercial",
    ), unsafe_allow_html=True)

st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

# Filtro por área
_areas_disponibles = ["Todas"] + sorted({h["area"] for h in hallazgos})
_area_sel = st.selectbox(
    "Filtrar por área", _areas_disponibles, key="filtro_int_area",
    label_visibility="collapsed",
)
hallazgos_vista = (
    hallazgos if _area_sel == "Todas"
    else [h for h in hallazgos if h["area"] == _area_sel]
)

dash_section(f"Hallazgos activos ({len(hallazgos_vista)})", "")

if not hallazgos_vista:
    st.markdown(
        '<div class="md-empty"><div class="md-empty__icon">✓</div>'
        '<p class="md-empty__title">Sin hallazgos en esta área</p>'
        '<p class="md-empty__sub">Todo está operando dentro de parámetros normales.</p>'
        '</div>',
        unsafe_allow_html=True,
    )
else:
    # Render en grid de 2 columnas
    cards = []
    for h in hallazgos_vista:
        card = dash_rec_card(
            icon=h["icon"],
            body_html=f'<span style="font-size:0.7rem;color:#9CA0A4;letter-spacing:1px;'
                      f'text-transform:uppercase;font-weight:700;">{h["area"]}</span><br>'
                      f'<b style="font-size:0.95rem;color:#1A1A1A;">{h["titulo"]}</b><br><br>'
                      f'{h["body"]}',
            hint_html=f'<b>Recomendación:</b> {h["recomendacion"]}',
            tone=h["tone"],
        )
        cards.append(card)

    # Grid de 2 columnas
    grid_html = (
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">'
        + "".join(cards)
        + '</div>'
    )
    st.markdown(grid_html, unsafe_allow_html=True)


# ── Footer info ──────────────────────────────────────────────────────────────────
st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
st.markdown(
    '<div style="background:white;border:1px solid #ECECEC;border-radius:14px;'
    'padding:16px 20px;font-size:0.78rem;color:#6B7280;line-height:1.6;">'
    '<b style="color:#1A1A1A;">Cómo funciona:</b> '
    'Los hallazgos se calculan en tiempo real cruzando datos de Melonn '
    '(pedidos, novedades, tiempos en tránsito) con Shopify (ventas, productos). '
    'Solo se reportan si superan un umbral mínimo de significancia '
    '(ej. 5+ pedidos en una ciudad, 10+ pedidos con una transportadora).'
    '</div>',
    unsafe_allow_html=True,
)
