"""
Módulo compartido: colores, estilos, carga de datos y helpers.
Importado por cada página del dashboard.
v2 — render_sidebar retorna (activo, filtro_nivel, filtro_zona)
"""

import sys
from pathlib import Path
import streamlit as st
import pandas as pd
from datetime import date, datetime
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from ingest import leer_csv_melonn
from riesgo import calcular_riesgo
try:
    import melonn_client
    _MELONN_API_DISPONIBLE = True
except Exception:
    _MELONN_API_DISPONIBLE = False

# ── Paleta de marca MALE'DENIM ────────────────────────────────────────────────
DEEP_INK      = "#213033"
STEEL_BLUE    = "#87a6b8"
GRAPHITE_GREY = "#606060"
SOFT_CONCRETE = "#e1e1df"
CRITICO_COLOR   = "#990012"
RIESGO_COLOR    = "#b95902"
NORMAL_COLOR    = "#036a73"
COD_COLOR       = "#59204d"
VENCIDO_COLOR   = "#606060"   # gris — pedidos >MAX_DIAS_ACTIVO sin confirmar entrega
RESUELTO_COLOR  = "#2d6a4f"   # verde oscuro — novedad solucionada

MAX_DIAS_ACTIVO = 20  # días máx. en tránsito; pasado esto → VENCIDO (posiblemente entregado sin actualizar)

ZONAS_ES = {
    "MEDELLIN":       "Medellín / Área Metro",
    "BOGOTA_RAPIDAS": "Bogotá / Zonas Rápidas",
    "PRINCIPALES":    "Ciudades Principales",
    "SECUNDARIAS":    "Municipios / Pueblos",
    "REEXPEDIDO":     "Reexpedido",
}
ESTADOS_ES = {
    # ── Novedades (códigos 1, 2) ─────────────────────────────────────────────
    "Received - valid":                              "Recibida · válida",
    "Recibida - valida":                             "Recibida · válida",
    "All items reserved - ready for fulfillment":    "Reservada · lista alistamiento",
    "Recibida - valida - lista para alistamiento":   "Reservada · lista alistamiento",
    # ── Pendiente despacho (código 26) ──────────────────────────────────────
    "All items reserved - fulfillment on hold":      "Alistamiento en espera · Seller",
    "Alistamiento en espera - Seller":               "Alistamiento en espera · Seller",
    "Packed - on hold":                              "Alistamiento en espera · Seller",
    # ── En tránsito (códigos 5, 6, 7, 24, 28) ──────────────────────────────
    "Packed":                                        "Empacada · lista para despacho",
    "Empacada":                                      "Empacada · lista para despacho",
    "Prepared for dispatch":                         "Preparada para despacho",
    "Preparada para despacho":                       "Preparada para despacho",
    "Shipped - in transit":                          "En tránsito",
    "Despachada - en tránsito":                      "En tránsito",
    "En tránsito":                                   "En tránsito",
    "Ready For Packing":                             "Lista para empaque · bodega",
    "Lista para empaque":                            "Lista para empaque · bodega",
    "Picked-up by buyer":                            "Recogida · finalizada",
    "Recogida por el comprador":                     "Recogida · finalizada",
    # ── Novedades ────────────────────────────────────────────────────────────
    "Error - not able to process":                   "Error · no procesa",
    "Error - no es posible procesar":                "Error · no procesa",
    "on stand by - not able to fulfil - no stock":   "Sin stock",
    "En espera - sin stock":                         "Sin stock",
    "Delivery not posible":                          "Entrega no posible",
    "Entrega no posible":                            "Entrega no posible",
    "on stand by - not able to fulfil - expired promises": "Promesa vencida",
    "En espera - promesas vencidas":                 "Promesa vencida",
    "All items reserved - fulfillment on hold - ext. conditionals": "En espera · ext.",
    "All items reserved - fulfillment on hold - int. conditionals": "En espera · int.",
    "on stand by - not able to fulfil - SM restriction": "Restricción método envío",
    "Restricción método de envío":                   "Restricción método envío",
}

DEFAULT_CSV = str(Path(__file__).parent.parent / "data" / "logistica" / "raw" / "melonn_2026-05-12.csv")

# ── CSS global ─────────────────────────────────────────────────────────────────
# Paleta — usada en el CSS con f-string
_C_INK   = "#213033"
_C_STEEL = "#87a6b8"
_C_GREY  = "#606060"
_C_CRIT  = "#990012"
_C_RISK  = "#b95902"
_C_OK    = "#036a73"
_C_PEND  = "#7b6e42"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Reset ──────────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {{
  font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif !important;
}}
.stApp {{ background-color: #F7F5F2 !important; }}
.main .block-container {{
  padding: 2rem 2.5rem 3rem !important;
  max-width: 100% !important;
}}
#MainMenu {{ visibility: hidden !important; }}
footer {{ visibility: hidden !important; }}
[data-testid="stDeployButton"] {{ display: none !important; }}
[data-testid="stStatusWidget"] {{ display: none !important; }}
[data-testid="stToolbar"]      {{ display: none !important; }}

/* ── Sidebar ────────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #0D1A1D 0%, #1A2B2F 55%, {_C_INK} 100%) !important;
  border-right: 1px solid rgba(135,166,184,0.08) !important;
  min-width: 230px !important;
}}
[data-testid="stSidebar"] * {{ color: #e0dedd !important; }}
[data-testid="stSidebar"] hr {{
  border: none !important;
  border-top: 1px solid rgba(135,166,184,0.12) !important;
  margin: 10px 0 !important;
}}
[data-testid="stSidebarNavItems"] {{ padding: 6px 10px 0 !important; }}
[data-testid="stSidebarNavLink"] {{
  font-size: 0.66rem !important;
  font-weight: 700 !important;
  letter-spacing: 2px !important;
  text-transform: uppercase !important;
  color: rgba(224,222,221,0.75) !important;
  border-radius: 6px !important;
  padding: 9px 12px !important;
  margin: 1px 0 !important;
  transition: all 0.15s ease !important;
}}
[data-testid="stSidebarNavLink"]:hover {{
  background: rgba(135,166,184,0.12) !important;
  color: #ffffff !important;
}}
[data-testid="stSidebarNavLink"][aria-selected="true"] {{
  background: rgba(135,166,184,0.15) !important;
  border-left: 2px solid {_C_STEEL} !important;
  color: #ffffff !important;
  padding-left: 10px !important;
}}
[data-testid="stSidebarNavSeparator"] {{
  font-size: 0.5rem !important;
  letter-spacing: 3px !important;
  opacity: 0.4 !important;
  padding: 12px 12px 4px !important;
}}

/* ── Tabs ────────────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"],
[data-testid="stTabs"] [role="tablist"] {{
  background: transparent !important;
  border-bottom: 1.5px solid #E6E4E0 !important;
  gap: 0 !important; padding: 0 !important;
}}
[data-baseweb="tab"],
[data-testid="stTabs"] button[role="tab"] {{
  font-size: 0.68rem !important;
  font-weight: 700 !important;
  letter-spacing: 2px !important;
  text-transform: uppercase !important;
  color: #909090 !important;
  background: transparent !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  padding: 10px 18px 12px !important;
  margin-bottom: -1.5px !important;
}}
[data-baseweb="tab"][aria-selected="true"],
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
  color: {_C_INK} !important;
  border-bottom: 2px solid {_C_INK} !important;
}}
[data-baseweb="tab"]:hover,
[data-testid="stTabs"] button[role="tab"]:hover {{ color: {_C_INK} !important; }}
[data-testid="stTabPanel"]   {{ padding-top: 20px !important; background: transparent !important; }}
[data-baseweb="tab-highlight"],
[data-baseweb="tab-border"]  {{ display: none !important; }}

/* ── KPI cards ─────────────────────────────────────────────────────────────────
   Cards SIEMPRE blancas con accent lateral de color.
   Texto oscuro sobre blanco → contraste óptimo.
   Si por algún caso se aplica fondo oscuro inline, el override de abajo
   garantiza que texto y label cambien a claros.
   ─────────────────────────────────────────────────────────────────────────── */
.kpi-card {{
  background: #ffffff;
  border: 1px solid #E6E4E0;
  border-radius: 12px;
  padding: 18px 18px 16px;
  margin-bottom: 4px;
  min-height: 122px;
  box-sizing: border-box;
  display: flex; flex-direction: column; justify-content: space-between;
  box-shadow: 0 1px 3px rgba(33,48,51,0.04);
  transition: box-shadow 0.15s, transform 0.15s;
}}
.kpi-card:hover {{
  box-shadow: 0 4px 14px rgba(33,48,51,0.09);
  transform: translateY(-1px);
}}
.kpi-num {{
  font-size: 1.8rem;
  font-weight: 800;
  color: {_C_INK};
  margin: 6px 0 0 0;
  line-height: 1;
  letter-spacing: -0.6px;
}}
.kpi-label {{
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 1.5px;       /* reducido de 2.5px → labels caben en 1 línea */
  text-transform: uppercase;
  color: {_C_GREY};
  margin: 0;
  white-space: nowrap;          /* fuerza una sola línea */
  overflow: hidden;
  text-overflow: ellipsis;
}}
.kpi-sub {{
  font-size: 0.7rem;
  color: {_C_GREY};
  margin: 4px 0 0 0;
  line-height: 1.3;
  font-weight: 400;
}}

/* Si una kpi-card recibe fondo oscuro (inline style), invertimos texto */
.kpi-card[style*="background:#213033"] .kpi-num,
.kpi-card[style*="background:#000"]    .kpi-num,
.kpi-card[style*="background:#990012"] .kpi-num,
.kpi-card[style*="background:#0c457a"] .kpi-num,
.kpi-card[style*="background:#0C457A"] .kpi-num,
.kpi-card[style*="background:#036a73"] .kpi-num,
.kpi-card[style*="background:#036A73"] .kpi-num,
.kpi-card[style*="background:#B95902"] .kpi-num,
.kpi-card[style*="background:#b95902"] .kpi-num {{ color: #ffffff; }}
.kpi-card[style*="background:#213033"] .kpi-label,
.kpi-card[style*="background:#000"]    .kpi-label,
.kpi-card[style*="background:#990012"] .kpi-label,
.kpi-card[style*="background:#0c457a"] .kpi-label,
.kpi-card[style*="background:#0C457A"] .kpi-label,
.kpi-card[style*="background:#036a73"] .kpi-label,
.kpi-card[style*="background:#036A73"] .kpi-label,
.kpi-card[style*="background:#B95902"] .kpi-label,
.kpi-card[style*="background:#b95902"] .kpi-label {{ color: rgba(255,255,255,0.75); }}
.kpi-card[style*="background:#213033"] .kpi-sub,
.kpi-card[style*="background:#000"]    .kpi-sub,
.kpi-card[style*="background:#990012"] .kpi-sub,
.kpi-card[style*="background:#0c457a"] .kpi-sub,
.kpi-card[style*="background:#0C457A"] .kpi-sub,
.kpi-card[style*="background:#036a73"] .kpi-sub,
.kpi-card[style*="background:#036A73"] .kpi-sub,
.kpi-card[style*="background:#B95902"] .kpi-sub,
.kpi-card[style*="background:#b95902"] .kpi-sub {{ color: rgba(255,255,255,0.7); }}

/* ── Tipografía de página ────────────────────────────────────────────────────── */
.titulo-panel {{
  font-size: 1.5rem;
  font-weight: 800;
  color: {_C_INK};
  letter-spacing: -0.3px;
  margin: 0 0 2px 0;
  line-height: 1;
}}
.subtitulo {{
  font-size: 0.78rem;
  color: {_C_GREY};
  margin: 0 0 6px 0;
  font-weight: 400;
}}
.sec-title {{
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: {_C_GREY};
  margin: 18px 0 10px 0;
}}

/* ── Sidebar logo ────────────────────────────────────────────────────────────── */
.logo-sidebar {{
  font-size: 1rem;
  font-weight: 800;
  letter-spacing: 4px;
  color: #ffffff;
  line-height: 1;
}}
.logo-tagline {{
  font-size: 0.5rem;
  font-weight: 600;
  letter-spacing: 5px;
  color: rgba(135,166,184,0.65);
  text-transform: uppercase;
  margin-top: 3px;
}}

/* ── Botones ─────────────────────────────────────────────────────────────────── */
.stButton > button {{
  font-size: 0.7rem !important;
  font-weight: 700 !important;
  letter-spacing: 1.2px !important;
  text-transform: uppercase !important;
  border-radius: 8px !important;
  padding: 9px 18px !important;
  transition: all 0.15s !important;
}}
.stButton > button[kind="primary"] {{
  background: {_C_INK} !important;
  color: white !important;
  border: none !important;
}}
.stButton > button[kind="primary"]:hover {{
  background: #0D1A1D !important;
  box-shadow: 0 4px 12px rgba(33,48,51,0.25) !important;
}}

/* ── DataFrames ──────────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] iframe {{ border-radius: 10px !important; }}
[data-testid="stDataFrame"] th {{
  background: #F7F5F2 !important;
  color: {_C_GREY} !important;
  font-size: 0.6rem !important;
  font-weight: 700 !important;
  letter-spacing: 2px !important;
  text-transform: uppercase !important;
  padding: 10px 14px !important;
}}
[data-testid="stDataFrame"] td {{
  font-size: 0.82rem !important;
  color: {_C_INK} !important;
  padding: 10px 14px !important;
}}

/* ── Inputs ──────────────────────────────────────────────────────────────────── */
.stTextInput > div > input,
.stSelectbox > div > div,
.stTextArea > div > textarea {{
  border: 1px solid #E6E4E0 !important;
  border-radius: 8px !important;
  background: white !important;
  font-size: 0.82rem !important;
}}
.stTextInput > div > input:focus,
.stTextArea > div > textarea:focus {{
  border-color: {_C_STEEL} !important;
  box-shadow: 0 0 0 3px rgba(135,166,184,0.18) !important;
}}
.stSelectbox label, .stTextInput label, .stTextArea label {{
  font-size: 0.62rem !important;
  font-weight: 700 !important;
  letter-spacing: 1.5px !important;
  text-transform: uppercase !important;
  color: {_C_GREY} !important;
}}

/* ── Expanders ───────────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {{
  border: 1px solid #E6E4E0 !important;
  border-radius: 10px !important;
  background: white !important;
}}
[data-testid="stExpander"] summary {{
  font-size: 0.75rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.5px !important;
  color: {_C_INK} !important;
  padding: 12px 16px !important;
}}

/* ── Alertas ─────────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {{
  border-radius: 10px !important;
  font-size: 0.8rem !important;
  border-left-width: 3px !important;
}}

/* ── Métricas nativas ────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {{
  background: white !important;
  border: 1px solid #E6E4E0 !important;
  border-radius: 12px !important;
  padding: 16px 20px !important;
  box-shadow: 0 1px 4px rgba(33,48,51,0.05) !important;
}}
[data-testid="stMetricLabel"] {{
  font-size: 0.6rem !important;
  font-weight: 700 !important;
  letter-spacing: 2.5px !important;
  text-transform: uppercase !important;
  color: {_C_GREY} !important;
}}
[data-testid="stMetricValue"] {{
  font-size: 1.6rem !important;
  font-weight: 800 !important;
  color: {_C_INK} !important;
}}

/* ── Scrollbar ───────────────────────────────────────────────────────────────── */
::-webkit-scrollbar               {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-track         {{ background: transparent; }}
::-webkit-scrollbar-thumb         {{ background: #D4D2CE; border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover   {{ background: {_C_STEEL}; }}

/* ── Download button ─────────────────────────────────────────────────────────── */
.stDownloadButton > button {{
  font-size: 0.68rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.8px !important;
  background: white !important;
  color: {_C_INK} !important;
  border: 1px solid #E6E4E0 !important;
  border-radius: 8px !important;
}}

/* ── Divisor ─────────────────────────────────────────────────────────────────── */
hr {{ border: none !important; border-top: 1px solid #E6E4E0 !important; }}

/* ═════════════════════════════════════════════════════════════════════════════
   EDITORIAL DESIGN SYSTEM v2 — Iteración 1
   Componentes premium tipo Linear / Shopify Admin / Stripe Dashboard
   ═════════════════════════════════════════════════════════════════════════════ */

/* ── Page header (título XL + subtítulo + slot derecho) ──────────────────────── */
.md-header {{
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  padding-bottom: 18px;
  margin-bottom: 24px;
  border-bottom: 1px solid #E6E4E0;
  gap: 24px;
}}
.md-header__left  {{ flex: 1; min-width: 0; }}
.md-header__right {{ flex-shrink: 0; text-align: right; }}
.md-header__title {{
  font-size: 1.55rem;
  font-weight: 800;
  color: {_C_INK};
  letter-spacing: -0.5px;
  line-height: 1.05;
  margin: 0 0 4px 0;
}}
.md-header__subtitle {{
  font-size: 0.8rem;
  color: {_C_GREY};
  margin: 0;
  font-weight: 400;
}}
.md-header__meta-label {{
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 2.5px;
  text-transform: uppercase;
  color: {_C_GREY};
  margin: 0 0 2px 0;
}}
.md-header__meta-value {{
  font-size: 0.8rem;
  font-weight: 600;
  color: {_C_INK};
  margin: 0;
}}

/* ── Section header (label uppercase con tracking amplio) ────────────────────── */
.md-section {{
  margin: 24px 0 14px 0;
}}
.md-section__label {{
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: {_C_GREY};
  margin: 0 0 2px 0;
}}
.md-section__hint {{
  font-size: 0.74rem;
  color: {_C_GREY};
  margin: 0;
  font-weight: 400;
}}

/* ── KPI Card v2 — editorial, números grandes, jerarquía clara ───────────────── */
.md-kpi {{
  background: #FFFFFF;
  border: 1px solid #E6E4E0;
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 1px 3px rgba(33,48,51,0.04);
  transition: box-shadow 0.18s, transform 0.18s;
  position: relative;
  overflow: hidden;
  min-height: 118px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}}
.md-kpi:hover {{
  box-shadow: 0 4px 14px rgba(33,48,51,0.09);
}}
.md-kpi__accent {{
  position: absolute;
  top: 0; left: 0;
  width: 3px; height: 100%;
  border-radius: 14px 0 0 14px;
}}
.md-kpi__label {{
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 2.5px;
  text-transform: uppercase;
  color: {_C_GREY};
  margin: 0 0 8px 0;
  display: flex;
  align-items: center;
  gap: 6px;
}}
.md-kpi__value {{
  font-size: 1.9rem;
  font-weight: 800;
  color: {_C_INK};
  letter-spacing: -0.6px;
  line-height: 1;
  margin: 0 0 5px 0;
}}
.md-kpi__sub {{
  font-size: 0.7rem;
  color: {_C_GREY};
  margin: 0;
  line-height: 1.3;
  font-weight: 400;
}}
.md-kpi__delta {{
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.3px;
  margin-top: 6px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}}
.md-kpi__delta--up   {{ color: {_C_OK}; }}
.md-kpi__delta--down {{ color: {_C_CRIT}; }}

/* ── Badge v2 — paleta corporativa exacta ────────────────────────────────────── */
.md-badge {{
  display: inline-block;
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  padding: 3px 9px;
  border-radius: 20px;
  border: 1px solid transparent;
  white-space: nowrap;
}}
.md-badge--critico   {{ background: #FDEEF0; color: #990012; border-color: #99001222; }}
.md-badge--riesgo    {{ background: #FDF1E8; color: #B95902; border-color: #B9590222; }}
.md-badge--normal    {{ background: #E8F3F2; color: #036A73; border-color: #036A7322; }}
.md-badge--pendiente {{ background: #F4F0E6; color: #7B6E42; border-color: #7B6E4222; }}
.md-badge--info      {{ background: #E8F0F8; color: #0C457A; border-color: #0C457A22; }}
.md-badge--neutral   {{ background: #F2F0EC; color: #606060; border-color: #60606022; }}
.md-badge--entregado {{ background: #E8F3F2; color: #036A73; border-color: #036A7322; }}

/* ── Card genérica ───────────────────────────────────────────────────────────── */
.md-card {{
  background: #FFFFFF;
  border: 1px solid #E6E4E0;
  border-radius: 14px;
  padding: 20px 22px;
  box-shadow: 0 1px 3px rgba(33,48,51,0.04);
}}
.md-card--accent-top {{
  border-top-width: 3px;
}}

/* ── Alert card v2 ───────────────────────────────────────────────────────────── */
.md-alert {{
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 13px 16px;
  border-radius: 10px;
  border: 1px solid;
  border-left-width: 3px;
  margin-bottom: 8px;
  background: #FFFFFF;
}}
.md-alert__icon {{
  font-size: 0.9rem;
  font-weight: 700;
  min-width: 16px;
  text-align: center;
  margin-top: 1px;
}}
.md-alert__body  {{ flex: 1; min-width: 0; }}
.md-alert__title {{
  font-size: 0.78rem;
  font-weight: 700;
  color: {_C_INK};
  margin: 0 0 2px 0;
}}
.md-alert__msg {{
  font-size: 0.73rem;
  color: {_C_GREY};
  margin: 0;
  line-height: 1.45;
}}
.md-alert__action {{
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  white-space: nowrap;
  margin-top: 2px;
}}
.md-alert--critico   {{ background: #FDEEF0; border-color: #990012; }}
.md-alert--critico   .md-alert__icon, .md-alert--critico .md-alert__action {{ color: #990012; }}
.md-alert--riesgo    {{ background: #FDF1E8; border-color: #B95902; }}
.md-alert--riesgo    .md-alert__icon, .md-alert--riesgo .md-alert__action {{ color: #B95902; }}
.md-alert--normal    {{ background: #E8F3F2; border-color: #036A73; }}
.md-alert--normal    .md-alert__icon, .md-alert--normal .md-alert__action {{ color: #036A73; }}
.md-alert--pendiente {{ background: #F4F0E6; border-color: #7B6E42; }}
.md-alert--pendiente .md-alert__icon, .md-alert--pendiente .md-alert__action {{ color: #7B6E42; }}
.md-alert--info      {{ background: #E8F0F8; border-color: #0C457A; }}
.md-alert--info      .md-alert__icon, .md-alert--info .md-alert__action {{ color: #0C457A; }}

/* ── Empty state ────────────────────────────────────────────────────────────── */
.md-empty {{
  text-align: center;
  padding: 36px 24px;
  background: #FFFFFF;
  border: 1px dashed #D4D2CE;
  border-radius: 14px;
}}
.md-empty__icon {{
  font-size: 1.6rem;
  margin-bottom: 10px;
  color: {_C_STEEL};
}}
.md-empty__title {{
  font-size: 0.85rem;
  font-weight: 700;
  color: {_C_INK};
  margin: 0 0 4px 0;
}}
.md-empty__sub {{
  font-size: 0.72rem;
  color: {_C_GREY};
  margin: 0;
}}

/* ═════════════════════════════════════════════════════════════════════════════
   DASH v3 — Stripe / Linear / Ramp visual language
   Componentes nuevos para el rediseño del Centro de Control.
   Prefijo .dash-* — no rompen ningún componente existente.
   ═════════════════════════════════════════════════════════════════════════════ */

/* ── Page hero (saludo Hola, Sebastián) ──────────────────────────────────────── */
.dash-hero {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 24px;
}}
.dash-hero__title {{
  font-size: 1.7rem;
  font-weight: 700;
  color: #1A1A1A;
  letter-spacing: -0.6px;
  line-height: 1.1;
  margin: 0 0 4px 0;
}}
.dash-hero__sub {{
  font-size: 0.86rem;
  color: #6B7280;
  margin: 0;
  font-weight: 400;
}}
.dash-hero__tools {{
  display: flex; gap: 10px; align-items: center;
}}
.dash-toolbtn {{
  background: white;
  border: 1px solid #ECECEC;
  border-radius: 9px;
  padding: 7px 12px;
  font-size: 0.78rem;
  font-weight: 500;
  color: #213033;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}}
.dash-toolbtn:hover {{ background: #FAFAF8; border-color: #D4D2CE; }}
.dash-avatar {{
  width: 32px; height: 32px;
  border-radius: 50%;
  background: #213033;
  color: white;
  font-size: 0.7rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}}

/* ── Section header con "Ver detalle →" ──────────────────────────────────────── */
.dash-section {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}}
.dash-section__label {{
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 1.6px;
  text-transform: uppercase;
  color: #9CA0A4;
  margin: 0;
}}
.dash-section__link {{
  font-size: 0.74rem;
  color: #9CA0A4;
  font-weight: 500;
  text-decoration: none;
}}

/* ── Card base ──────────────────────────────────────────────────────────────── */
.dash-card {{
  background: white;
  border: 1px solid #ECECEC;
  border-radius: 16px;
  padding: 18px 20px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  height: 100%;
  box-sizing: border-box;
}}

/* ── KPI card v3 con sparkline (grid 2col — label y spark NUNCA se sobreponen) ── */
.dash-kpi {{
  background: white;
  border: 1px solid #ECECEC;
  border-radius: 16px;
  padding: 14px 16px 14px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  min-height: 116px;
  display: grid;
  grid-template-columns: 1fr 70px;
  grid-template-rows: auto auto 1fr auto;
  column-gap: 8px;
  row-gap: 2px;
  align-items: start;
}}
.dash-kpi__label {{
  grid-column: 1 / 2;
  grid-row: 1;
  font-size: 0.6rem;
  font-weight: 600;
  letter-spacing: 1.1px;       /* reducido — más espacio para texto */
  text-transform: uppercase;
  color: #9CA0A4;
  margin: 0;
  line-height: 1.2;
  /* permitir 2 líneas si necesario, sin truncar */
}}
.dash-kpi__spark {{
  grid-column: 2 / 3;
  grid-row: 1 / 3;
  width: 70px;
  height: 32px;
  opacity: 0.85;
  pointer-events: none;
  align-self: start;
  margin-top: -4px;
}}
.dash-kpi__value {{
  grid-column: 1 / -1;       /* ocupa ambas columnas, debajo del spark */
  grid-row: 3;
  font-size: 1.45rem;
  font-weight: 700;
  color: #1A1A1A;
  letter-spacing: -0.5px;
  line-height: 1.1;
  margin: 6px 0 4px 0;
}}
.dash-kpi__value--danger {{ color: #990012; }}
.dash-kpi__meta {{
  grid-column: 1 / -1;
  grid-row: 4;
  font-size: 0.72rem;
  color: #6B7280;
  font-weight: 500;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 4px;
}}
.dash-kpi__meta--up   {{ color: #036A73; }}
.dash-kpi__meta--down {{ color: #990012; }}
.dash-kpi__link {{
  grid-column: 1 / -1;
  grid-row: 4;
  font-size: 0.72rem;
  color: #6B7280;
  font-weight: 500;
}}

/* ── Alert row (lista de alertas) ────────────────────────────────────────────── */
.dash-alert {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 12px;
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.12s;
}}
.dash-alert:hover {{ background: #FAFAF8; }}
.dash-alert + .dash-alert {{ border-top: 1px solid #F4F2EE; }}
.dash-alert__chip {{
  width: 36px; height: 36px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  font-weight: 700;
  flex-shrink: 0;
}}
.dash-alert__body {{ flex: 1; min-width: 0; }}
.dash-alert__title {{
  font-size: 0.86rem;
  font-weight: 600;
  color: #1A1A1A;
  margin: 0 0 2px 0;
  line-height: 1.25;
}}
.dash-alert__sub {{
  font-size: 0.74rem;
  color: #6B7280;
  margin: 0;
  font-weight: 400;
}}
.dash-alert__arrow {{
  color: #9CA0A4;
  font-size: 1rem;
  flex-shrink: 0;
}}

/* ── Icon-badge chip (rojo/naranja/etc.) ─────────────────────────────────────── */
.dash-chip--red    {{ background: #FDEEF0; color: #990012; }}
.dash-chip--orange {{ background: #FDF1E8; color: #B95902; }}
.dash-chip--yellow {{ background: #FAF4DC; color: #8A6D1F; }}
.dash-chip--green  {{ background: #E6F4F2; color: #036A73; }}
.dash-chip--blue   {{ background: #E7EEF6; color: #0C457A; }}
.dash-chip--khaki  {{ background: #F1EAD8; color: #7B6E42; }}
.dash-chip--gray   {{ background: #F2F2F0; color: #606060; }}

/* ── Platform bar (Dinero pendiente por plataforma) ─────────────────────────── */
.dash-platform {{
  display: grid;
  grid-template-columns: 28px 1fr 90px;
  align-items: center;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid #F4F2EE;
}}
.dash-platform:last-child {{ border-bottom: none; }}
.dash-platform__icon {{
  width: 26px; height: 26px;
  border-radius: 7px;
  background: #213033;
  color: white;
  font-size: 0.66rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}}
.dash-platform__name {{
  font-size: 0.84rem;
  color: #1A1A1A;
  font-weight: 500;
}}
.dash-platform__bar-wrap {{
  flex: 1;
  height: 6px;
  background: #F2F0EC;
  border-radius: 99px;
  overflow: hidden;
  margin: 4px 0 0 0;
  grid-column: 2;
}}
.dash-platform__bar {{
  height: 100%;
  border-radius: 99px;
}}
.dash-platform__value {{
  font-size: 0.82rem;
  font-weight: 600;
  color: #1A1A1A;
  text-align: right;
  font-variant-numeric: tabular-nums;
}}

/* ── Order-status row con barra horizontal ───────────────────────────────────── */
.dash-status {{
  display: grid;
  grid-template-columns: 14px 80px 1fr 50px 50px;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid #F4F2EE;
}}
.dash-status:last-child {{ border-bottom: none; }}
.dash-status__dot {{
  width: 8px; height: 8px; border-radius: 50%;
}}
.dash-status__label {{ font-size: 0.84rem; color: #1A1A1A; font-weight: 500; }}
.dash-status__bar-wrap {{
  height: 6px;
  background: #F2F0EC;
  border-radius: 99px;
  overflow: hidden;
}}
.dash-status__bar {{ height: 100%; border-radius: 99px; }}
.dash-status__count {{
  font-size: 0.82rem;
  color: #1A1A1A;
  font-weight: 600;
  text-align: right;
  font-variant-numeric: tabular-nums;
}}
.dash-status__pct {{
  font-size: 0.78rem;
  color: #9CA0A4;
  font-weight: 500;
  text-align: right;
  font-variant-numeric: tabular-nums;
}}

/* ── Recommendation card ─────────────────────────────────────────────────────── */
.dash-rec {{
  background: white;
  border: 1px solid #ECECEC;
  border-radius: 14px;
  padding: 14px 16px;
  height: 100%;
  box-sizing: border-box;
}}
.dash-rec__icon {{
  width: 30px; height: 30px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 10px;
  font-size: 0.92rem;
}}
.dash-rec__body {{
  font-size: 0.82rem;
  color: #1A1A1A;
  font-weight: 500;
  line-height: 1.45;
  margin: 0 0 12px 0;
}}
.dash-rec__body b {{ font-weight: 700; }}
.dash-rec__hint {{
  font-size: 0.72rem;
  color: #6B7280;
  margin: 0;
  font-weight: 400;
  border-top: 1px solid #F2F0EC;
  padding-top: 8px;
}}
.dash-rec__hint b {{ font-weight: 600; color: #213033; }}

/* ── Quick action button ─────────────────────────────────────────────────────── */
.dash-quick {{
  background: white;
  border: 1px solid #ECECEC;
  border-radius: 14px;
  padding: 14px 18px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.82rem;
  font-weight: 600;
  color: #1A1A1A;
  cursor: pointer;
  transition: all 0.12s;
  text-decoration: none;
  white-space: nowrap;
}}
.dash-quick:hover {{
  background: #FAFAF8;
  border-color: #D4D2CE;
  transform: translateY(-1px);
}}
.dash-quick__icon {{
  width: 22px; height: 22px;
  border-radius: 6px;
  background: #F2F0EC;
  color: #213033;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.78rem;
  flex-shrink: 0;
}}

/* ── Top reference row ───────────────────────────────────────────────────────── */
.dash-topref {{
  display: grid;
  grid-template-columns: 26px 42px 1fr 110px 50px;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #F4F2EE;
}}
.dash-topref:last-child {{ border-bottom: none; }}
.dash-topref__rank {{
  font-size: 0.78rem;
  font-weight: 600;
  color: #6B7280;
}}
.dash-topref__thumb {{
  width: 36px; height: 36px;
  border-radius: 8px;
  background: #F2F0EC;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #9CA0A4;
  font-size: 0.78rem;
  overflow: hidden;
}}
.dash-topref__name {{
  font-size: 0.84rem;
  color: #1A1A1A;
  font-weight: 500;
}}
.dash-topref__val {{
  font-size: 0.84rem;
  font-weight: 600;
  text-align: right;
  color: #1A1A1A;
  font-variant-numeric: tabular-nums;
}}
.dash-topref__pct {{
  font-size: 0.78rem;
  color: #9CA0A4;
  text-align: right;
  font-variant-numeric: tabular-nums;
}}

/* ── Donut wrapper centrado ──────────────────────────────────────────────────── */
.dash-donut-wrap {{
  text-align: center;
  min-width: 0;       /* permite que flex item se encoja */
  flex: 1;
}}
.dash-donut-label {{
  font-size: 0.78rem;     /* reducido de 0.86 para que quepa en 1 línea */
  font-weight: 600;
  color: #1A1A1A;
  margin: 8px 0 2px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.dash-donut-sub {{
  font-size: 0.7rem;
  color: #6B7280;
  font-weight: 400;
  margin: 0;
  white-space: nowrap;
}}

/* ── Status legend (rojo/naranja/verde con puntos) ──────────────────────────── */
.dash-legend {{
  display: flex; flex-direction: column; gap: 6px;
}}
.dash-legend__item {{
  display: flex; align-items: center; gap: 8px;
  font-size: 0.78rem;
  color: #1A1A1A;
  font-weight: 500;
}}
.dash-legend__dot {{
  width: 8px; height: 8px; border-radius: 50%;
}}

</style>
"""

# ═════════════════════════════════════════════════════════════════════════════
# EDITORIAL HELPERS — Iteración 1
# Componentes premium reutilizables. Solo HTML/CSS, sin queries.
# ═════════════════════════════════════════════════════════════════════════════

def md_header(title: str, subtitle: str = "", meta_label: str = "", meta_value: str = "", meta_extra: str = ""):
    """Header de página editorial.  Sin indentación al inicio de línea: Streamlit lo trataría como code block."""
    subtitle_html = f'<p class="md-header__subtitle">{subtitle}</p>' if subtitle else ''
    right_html    = ""
    if meta_label or meta_value:
        ml = f'<p class="md-header__meta-label">{meta_label}</p>' if meta_label else ''
        mv = f'<p class="md-header__meta-value">{meta_value}</p>' if meta_value else ''
        right_html = f'<div class="md-header__right">{ml}{mv}{meta_extra}</div>'
    html = (
        '<div class="md-header">'
        f'<div class="md-header__left">'
        f'<h1 class="md-header__title">{title}</h1>{subtitle_html}'
        '</div>'
        f'{right_html}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def md_section(label: str, hint: str = ""):
    """Section divider con label uppercase + hint opcional."""
    hint_html = f'<p class="md-section__hint">{hint}</p>' if hint else ''
    html = f'<div class="md-section"><p class="md-section__label">{label}</p>{hint_html}</div>'
    st.markdown(html, unsafe_allow_html=True)


def md_kpi(value: str, label: str, sub: str = "", accent: str = STEEL_BLUE,
           delta: str = "", delta_up: bool = True, icon: str = "") -> str:
    """KPI card editorial. Retorna HTML para usar con st.markdown(..., unsafe_allow_html=True)."""
    delta_html = ""
    if delta:
        cls   = "md-kpi__delta--up" if delta_up else "md-kpi__delta--down"
        arrow = "↑" if delta_up else "↓"
        delta_html = f'<span class="md-kpi__delta {cls}">{arrow} {delta}</span>'
    icon_html = f'<span style="font-size:0.7rem;opacity:0.7;">{icon}</span>' if icon else ""
    sub_html  = f'<p class="md-kpi__sub">{sub}</p>' if sub else ''
    return (
        '<div class="md-kpi">'
        f'<div class="md-kpi__accent" style="background:{accent};"></div>'
        f'<p class="md-kpi__label">{icon_html}{label}</p>'
        '<div>'
        f'<p class="md-kpi__value">{value}</p>{sub_html}{delta_html}'
        '</div>'
        '</div>'
    )


def md_badge(text: str, level: str = "neutral") -> str:
    """
    Badge inline. Niveles: critico, riesgo, normal, pendiente, info, neutral, entregado.
    Uso: f'Estado: {md_badge("CRÍTICO", "critico")}'
    """
    return f'<span class="md-badge md-badge--{level.lower()}">{text}</span>'


def md_alert(title: str, msg: str, level: str = "info", icon: str = "", action: str = "") -> str:
    """Alert card. Retorna HTML."""
    icons_default = {"critico":"!", "riesgo":"!", "normal":"✓", "pendiente":"⏳", "info":"i"}
    _ic = icon or icons_default.get(level.lower(), "•")
    action_html = f'<span class="md-alert__action">{action} →</span>' if action else ''
    return (
        f'<div class="md-alert md-alert--{level.lower()}">'
        f'<span class="md-alert__icon">{_ic}</span>'
        '<div class="md-alert__body">'
        f'<p class="md-alert__title">{title}</p>'
        f'<p class="md-alert__msg">{msg}</p>'
        '</div>'
        f'{action_html}'
        '</div>'
    )


def md_empty(title: str, sub: str = "", icon: str = "○"):
    """Empty state elegante."""
    sub_html = f'<p class="md-empty__sub">{sub}</p>' if sub else ''
    html = (
        '<div class="md-empty">'
        f'<div class="md-empty__icon">{icon}</div>'
        f'<p class="md-empty__title">{title}</p>'
        f'{sub_html}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# DASH v3 — Helpers para los nuevos componentes del Centro de Control
# Estilo Stripe / Linear / Ramp. Prefijo dash_*.
# Retornan strings HTML (para columnas) o llaman st.markdown directamente.
# ═════════════════════════════════════════════════════════════════════════════

def dash_hero(title: str, subtitle: str = "", tools_html: str = ""):
    """Header de la página estilo Stripe — Hola, Sebastián + subtítulo + tools a la derecha."""
    sub  = f'<p class="dash-hero__sub">{subtitle}</p>' if subtitle else ''
    right = f'<div class="dash-hero__tools">{tools_html}</div>' if tools_html else ''
    html = (
        '<div class="dash-hero">'
        '<div>'
        f'<h1 class="dash-hero__title">{title}</h1>{sub}'
        '</div>'
        f'{right}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def dash_section(label: str, link_text: str = ""):
    """Section label + link 'Ver detalle →' a la derecha."""
    link = f'<span class="dash-section__link">{link_text} →</span>' if link_text else ''
    html = (
        '<div class="dash-section">'
        f'<p class="dash-section__label">{label}</p>{link}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def dash_card_start() -> str:
    """Abre un .dash-card. Usar con st.markdown(... + dash_card_end(), unsafe_allow_html=True)."""
    return '<div class="dash-card">'

def dash_card_end() -> str:
    return '</div>'


def dash_kpi(label: str, value: str, meta: str = "", meta_dir: str = "",
             link: str = "", value_danger: bool = False,
             spark_svg: str = "") -> str:
    """
    KPI card v3 con sparkline SVG opcional.
    - label: uppercase pequeño
    - value: número grande
    - meta:  '12.4% vs ayer' / '97.4% del esperado'
    - meta_dir: 'up' | 'down' | ''  → color verde/rojo
    - link: si se da, se muestra como meta en gris ('Ver detalle')
    - value_danger: true → valor en rojo
    - spark_svg: SVG inline para mini-gráfico
    """
    val_cls = ' dash-kpi__value--danger' if value_danger else ''
    meta_html = ''
    if meta:
        dir_cls = ''
        arrow   = ''
        if meta_dir == 'up':
            dir_cls, arrow = ' dash-kpi__meta--up', '↑ '
        elif meta_dir == 'down':
            dir_cls, arrow = ' dash-kpi__meta--down', '↓ '
        meta_html = f'<p class="dash-kpi__meta{dir_cls}">{arrow}{meta}</p>'
    elif link:
        meta_html = f'<p class="dash-kpi__link">{link} →</p>'

    spark_html = f'<div class="dash-kpi__spark">{spark_svg}</div>' if spark_svg else ''

    return (
        '<div class="dash-kpi">'
        f'{spark_html}'
        f'<p class="dash-kpi__label">{label}</p>'
        f'<p class="dash-kpi__value{val_cls}">{value}</p>'
        f'{meta_html}'
        '</div>'
    )


def dash_sparkline(values: list, color: str = "#1A1A1A",
                   width: int = 90, height: int = 36) -> str:
    """
    Genera un SVG sparkline con relleno gradiente.
    values: lista de números. Se normalizan automáticamente al espacio disponible.
    """
    if not values or len(values) < 2:
        return ''
    vmin, vmax = min(values), max(values)
    rng = (vmax - vmin) or 1.0
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = round(i / (n - 1) * width, 2)
        y = round(height - 2 - ((v - vmin) / rng) * (height - 4), 2)
        pts.append(f"{x},{y}")
    # Polyline para la línea + polygon con fill
    line_pts = " ".join(pts)
    poly_pts = f"0,{height} " + line_pts + f" {width},{height}"
    grad_id  = f"gr{abs(hash((color, width, height))) % 100000}"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<defs><linearGradient id="{grad_id}" x1="0" x2="0" y1="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.18"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
        '</linearGradient></defs>'
        f'<polygon points="{poly_pts}" fill="url(#{grad_id})"/>'
        f'<polyline points="{line_pts}" fill="none" stroke="{color}" '
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )


def dash_icon_badge(icon: str, tone: str = "gray") -> str:
    """Chip cuadrado con ícono. Tono: red, orange, yellow, green, blue, khaki, gray."""
    return f'<div class="dash-alert__chip dash-chip--{tone}">{icon}</div>'


def dash_alert_row(title: str, sub: str, tone: str = "gray", icon: str = "!") -> str:
    """
    Fila de alerta con icon-badge + título + subtítulo + flecha.
    Concatenar varias en un dash-card.
    """
    return (
        '<div class="dash-alert">'
        f'{dash_icon_badge(icon, tone)}'
        '<div class="dash-alert__body">'
        f'<p class="dash-alert__title">{title}</p>'
        f'<p class="dash-alert__sub">{sub}</p>'
        '</div>'
        '<span class="dash-alert__arrow">›</span>'
        '</div>'
    )


def dash_platform_row(name: str, icon: str, value: str,
                      bar_pct: float = 50.0, bar_color: str = "#213033",
                      icon_bg: str = "#213033") -> str:
    """Fila de plataforma: ícono + nombre + barra horizontal + valor monetario."""
    pct = max(2, min(100, bar_pct))
    return (
        '<div class="dash-platform">'
        f'<div class="dash-platform__icon" style="background:{icon_bg};">{icon}</div>'
        f'<span class="dash-platform__name">{name}</span>'
        f'<span class="dash-platform__value">{value}</span>'
        f'<div class="dash-platform__bar-wrap"><div class="dash-platform__bar" '
        f'style="width:{pct}%;background:{bar_color};"></div></div>'
        '</div>'
    )


def dash_status_row(label: str, count: int, pct: float,
                    color: str = "#036A73", bar_max_pct: float = 100.0) -> str:
    """Fila de pedidos por estado: dot + label + barra + número + %."""
    bar_w = max(2, min(100, bar_max_pct))
    return (
        '<div class="dash-status">'
        f'<span class="dash-status__dot" style="background:{color};"></span>'
        f'<span class="dash-status__label">{label}</span>'
        f'<div class="dash-status__bar-wrap"><div class="dash-status__bar" '
        f'style="width:{bar_w}%;background:{color};"></div></div>'
        f'<span class="dash-status__count">{count}</span>'
        f'<span class="dash-status__pct">{pct:.0f}%</span>'
        '</div>'
    )


def dash_rec_card(icon: str, body_html: str, hint_html: str = "", tone: str = "blue") -> str:
    """
    Card de recomendación inteligente. body_html admite <b> para destacar.
    hint_html va abajo con 'Recomendación: ...'.
    """
    hint = f'<p class="dash-rec__hint">{hint_html}</p>' if hint_html else ''
    return (
        '<div class="dash-rec">'
        f'<div class="dash-rec__icon dash-chip--{tone}">{icon}</div>'
        f'<p class="dash-rec__body">{body_html}</p>'
        f'{hint}'
        '</div>'
    )


def dash_quick_action(label: str, icon: str = "▸") -> str:
    """Botón de acceso rápido (visual only — para Streamlit usar st.button al lado)."""
    return (
        '<div class="dash-quick">'
        f'<span class="dash-quick__icon">{icon}</span>'
        f'<span>{label}</span>'
        '</div>'
    )


def dash_topref_row(rank: int, name: str, value: str, pct: str,
                    thumb_html: str = "") -> str:
    """Fila Top Referencias. thumb_html opcional (placeholder gris si vacío)."""
    if thumb_html:
        thumb_block = thumb_html if thumb_html.startswith("<div") else (
            '<div class="dash-topref__thumb">' + thumb_html + '</div>'
        )
    else:
        thumb_block = '<div class="dash-topref__thumb">◫</div>'
    return (
        '<div class="dash-topref">'
        f'<span class="dash-topref__rank">{rank}.</span>'
        f'{thumb_block}'
        f'<span class="dash-topref__name">{name}</span>'
        f'<span class="dash-topref__val">{value}</span>'
        f'<span class="dash-topref__pct">{pct}</span>'
        '</div>'
    )


def dash_donut(pct: float, color: str = "#036A73", size: int = 86,
               stroke: int = 7, center_text: str = "", track: str = "#F2F0EC") -> str:
    """
    Donut SVG inline. pct 0–100. Stroke fino tipo Stripe/Linear.
    center_text se renderiza dentro del donut. Si vacío, usa '{pct}%'.
    """
    pct = max(0, min(100, pct))
    r   = (size - stroke) / 2
    cx  = cy = size / 2
    circ = 2 * 3.141592653589793 * r
    dash = (pct / 100) * circ
    gap  = circ - dash
    txt  = center_text or f"{int(round(pct))}%"
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{track}" '
        f'stroke-width="{stroke}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-dasharray="{dash:.2f} {gap:.2f}" '
        f'transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" '
        f'font-family="Inter,sans-serif" font-size="17" font-weight="700" '
        f'fill="#1A1A1A">{txt}</text>'
        '</svg>'
    )


def dash_legend(items: list) -> str:
    """
    Leyenda de mapa. items = [(label, color), ...]
    """
    rows = "".join(
        f'<div class="dash-legend__item">'
        f'<span class="dash-legend__dot" style="background:{c};"></span>{l}'
        '</div>'
        for l, c in items
    )
    return f'<div class="dash-legend">{rows}</div>'


# ── Sesión / usuario activo ───────────────────────────────────────────────────
def usuario_activo() -> str:
    """
    Retorna el nombre del usuario logueado para registrarlo en acciones/notas.
    Fallback a username si no hay nombre, o 'dashboard' si no hay sesión.
    """
    try:
        nombre = st.session_state.get("name") or st.session_state.get("username") or ""
        return nombre.strip() or "dashboard"
    except Exception:
        return "dashboard"


# ── Carga y procesamiento ─────────────────────────────────────────────────────
def _dias_reales(p: dict) -> int:
    """
    Calcula días en tránsito dinámicamente desde fecha_despacho → hoy.
    Fallback al valor almacenado si no hay fecha.
    """
    fd = p.get("fecha_despacho")
    if fd:
        try:
            return max(0, (date.today() - date.fromisoformat(str(fd))).days)
        except Exception:
            pass
    return int(p.get("dias_en_transito") or 0)


def _promesa_vencida(p: dict, sla_critico: int) -> str:
    """
    Retorna 'SÍ' si la fecha de promesa ya venció, '—' si no.
    Orden de prioridad para la fecha de promesa:
      1. fecha_promesa del pedido (viene de Melonn CSV o bootstrap)
      2. fecha_despacho + sla_critico (estimado por zona) — solo para tránsito
    """
    from datetime import timedelta
    fp = p.get("fecha_promesa")
    if not fp:
        # Estimar promesa a partir de fecha_despacho + SLA de zona
        fd = p.get("fecha_despacho")
        if fd:
            try:
                fd_obj  = date.fromisoformat(str(fd))
                fp      = str(fd_obj + timedelta(days=sla_critico))
                # Guardar la promesa estimada en el pedido para que se muestre
                p["fecha_promesa"] = fp
            except Exception:
                return "—"
        else:
            return "—"
    try:
        return "SÍ" if date.today() > date.fromisoformat(str(fp)) else "—"
    except Exception:
        return "—"


def _procesar_df(pedidos: list) -> pd.DataFrame:
    """
    Convierte la lista de pedidos en DataFrame con clasificación de riesgo.

    Columnas clave añadidas:
      Sub_Estado  → pendiente_despacho | en_transito | novedad | otro
      Tipo_Recaudo → Contraentrega | Prepago
      Nivel        → CRITICO | RIESGO | NORMAL | VENCIDO

    VENCIDO aplica solo a pedidos en tránsito (COD o Prepago) que superan
    MAX_DIAS_ACTIVO sin confirmación de entrega — nunca a pendientes de despacho.
    """
    rows = []
    for p in pedidos:
        dias_real = _dias_reales(p)
        sub       = p.get("sub_estado_logistico", "en_transito")
        es_cod    = p["es_contraentrega"]

        # Calculamos riesgo en todos los casos para obtener zona_info y SLA
        r = calcular_riesgo(
            ciudad=p["ciudad_destino"],
            dias_en_transito=dias_real,
            incidencia_raw=p.get("incidencia", "NINGUNO"),
            es_contraentrega=es_cod,
        )

        # ENTREGADO: pedido cobrado/entregado — no aplica riesgo
        es_entregado = (sub == "entregado")

        # RESUELTO: novedad solucionada — no aplica riesgo ni VENCIDO
        es_resuelto = (sub == "resuelto")

        # VENCIDO: solo en_transito/novedad con >MAX_DIAS_ACTIVO sin confirmar
        es_vencido = (
            not es_resuelto
            and not es_entregado
            and dias_real > MAX_DIAS_ACTIVO
            and sub in ("en_transito", "novedad")
        )

        if es_entregado:
            nivel     = "NORMAL"
            prioridad = 20
            score     = 100
            motivo    = "Pedido entregado · COD cobrado"
            categoria = "OK"
        elif es_resuelto:
            nivel     = "RESUELTO"
            prioridad = 10
            score     = 100
            motivo    = "Novedad solucionada · pedido recogido"
            categoria = "OK"
        elif es_vencido:
            nivel     = "VENCIDO"
            prioridad = 6
            score     = 0
            motivo    = f"Sin confirmación · {dias_real}d en tránsito"
            categoria = "OK"
        else:
            nivel     = r.nivel
            prioridad = r.prioridad
            score     = r.score
            motivo    = r.motivos[0] if r.motivos else "—"
            categoria = r.incidencia_info.categoria

        # Calcular promesa ANTES del append — no aplica a entregados/resueltos
        _prom_vencida = (
            _promesa_vencida(p, r.zona_info.sla_critico)
            if not es_resuelto and not es_entregado else "—"
        )

        rows.append({
            "Prioridad":       prioridad,
            "Nivel":           nivel,
            "Score":           score,
            "Sub_Estado":      sub,
            "Tipo_Recaudo":    "Contraentrega" if es_cod else "Prepago",
            "Orden":           p.get("orden_tienda") or p.get("orden_melonn", ""),
            "Orden Melonn":    p.get("orden_melonn", ""),
            "Cliente":         p.get("nombre_comprador", ""),
            "Teléfono":        p.get("telefono_comprador", ""),
            "Ciudad":          p.get("ciudad_destino", ""),
            "Zona":            ZONAS_ES.get(r.zona_info.zona, r.zona_info.zona),
            "Días":            dias_real,
            "SLA Crítico":     r.zona_info.sla_critico,
            "Días sobre SLA":  max(0, dias_real - r.zona_info.sla_critico + 1),
            "Valor COD":       p.get("valor_cod_raw", ""),
            "Método Envío":    p.get("transportadora", ""),
            "Estado":          ESTADOS_ES.get(p.get("estado_melonn",""), p.get("estado_melonn","")),
            "Estado_Code":     int(p.get("estado_melonn_code") or 0),
            "Novedad":         p.get("incidencia", "NINGUNO"),
            "Categoría":       categoria,
            "F. Promesa":      str(p.get("fecha_promesa") or ""),
            "Promesa vencida": _prom_vencida,
            "F. Despacho":     str(p.get("fecha_despacho") or ""),
            "F. Creación":     str(p.get("fecha_creacion") or ""),
            "Motivo riesgo":   motivo,
            "Link Melonn":     p.get("link_guia", ""),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["Prioridad","Días sobre SLA"], ascending=[True,False]).reset_index(drop=True)

@st.cache_data(show_spinner=False)
def cargar_datos(ruta: str, ts: str):
    """Carga desde CSV (fallback cuando no hay API)."""
    pedidos, omitidos = leer_csv_melonn(ruta, solo_activos=True)
    df = _procesar_df(pedidos)
    return df, omitidos

_SS_DATOS = "_api_datos"   # (df, omitidos, meta) en session_state
_SS_TS    = "_api_datos_ts" # datetime del último fetch
_SS_TTL   = 7200            # 2 horas en memoria — sobrevive a una sesión completa

_SS_INFO    = "_cache_info"     # dict de cache_info() en session_state
_SS_INFO_TS = "_cache_info_ts"  # datetime de la última consulta
_SS_INFO_TTL= 120               # 2 min — el sidebar no golpea Supabase en cada navegación


def _cache_info_rapido():
    """
    cache_info() cacheado en session_state.
    Evita una query a Supabase en CADA navegación de página (la causa
    principal de lentitud al cambiar de módulo).
    """
    _info = st.session_state.get(_SS_INFO)
    _ts   = st.session_state.get(_SS_INFO_TS)
    if _info is not None and _ts is not None:
        if (datetime.now() - _ts).total_seconds() < _SS_INFO_TTL:
            return _info
    try:
        _info = melonn_client.cache_info()
    except Exception:
        _info = None
    st.session_state[_SS_INFO]    = _info
    st.session_state[_SS_INFO_TS] = datetime.now()
    return _info


def _invalidar_cache_info():
    """Llamar tras un refresh forzado para que el sidebar muestre el estado nuevo."""
    st.session_state.pop(_SS_INFO, None)
    st.session_state.pop(_SS_INFO_TS, None)

def cargar_datos_api(forzar_refresh: bool = False):
    """
    Carga pedidos desde Melonn con caché en session_state.

    Flujo:
      1. Si hay datos en session_state con < 5 min → retorna instantáneo (sin Supabase)
      2. Si forzar_refresh o caché vencido → fetch desde Supabase/API → guarda en session_state

    Esto elimina la llamada a Supabase en cada re-render de Streamlit
    (cada click, selección de tabla, cambio de tab).
    """
    if not _MELONN_API_DISPONIBLE:
        return pd.DataFrame(), {}, {"fuente": "no_api"}

    _refresh = forzar_refresh or st.session_state.pop("_melonn_refresh", False)

    # ── Caché en memoria (session_state) ─────────────────────────────────────
    if not _refresh:
        _cached = st.session_state.get(_SS_DATOS)
        _ts     = st.session_state.get(_SS_TS)
        if _cached is not None and _ts is not None:
            if (datetime.now() - _ts).total_seconds() < _SS_TTL:
                return _cached   # ← instantáneo, cero red

    # ── Fetch desde Supabase o API ────────────────────────────────────────────
    resultado = melonn_client.obtener_pedidos_activos(forzar_refresh=_refresh)
    if len(resultado) == 3:
        pedidos, omitidos, meta = resultado
    else:
        pedidos, omitidos = resultado
        meta = {}

    if meta.get("refresh_bloqueado"):
        st.session_state["_refresh_bloqueado"] = True

    if not pedidos:
        result = (pd.DataFrame(), omitidos, meta)
    else:
        df = _procesar_df(pedidos)
        result = (df, omitidos, meta)

    # Guardar en session_state para las próximas interacciones
    st.session_state[_SS_DATOS] = result
    st.session_state[_SS_TS]    = datetime.now()
    return result

def api_melonn_activa() -> bool:
    """True si el API key está configurado y el módulo disponible."""
    return _MELONN_API_DISPONIBLE and melonn_client.credenciales_ok()

def color_nivel(val):
    return {
        "CRITICO": f"background-color:{CRITICO_COLOR}22;color:{CRITICO_COLOR};font-weight:700",
        "RIESGO":  f"background-color:{RIESGO_COLOR}22;color:{RIESGO_COLOR};font-weight:600",
        "NORMAL":  f"background-color:{NORMAL_COLOR}22;color:{NORMAL_COLOR}",
        "VENCIDO": f"background-color:{VENCIDO_COLOR}18;color:{VENCIDO_COLOR};font-style:italic",
    }.get(val, "")

def _parse_cod(v: str) -> float:
    try:
        s = str(v).strip()
        if not s or s in ("-","No aplica","nan"): return 0.0
        if "," in s: s = s.replace(".","").replace(",",".")
        else: s = s.replace(",","")
        return float(s)
    except Exception:
        return 0.0

# ── Sidebar compartido — SOLO filtros (logo/status/logout van en app.py) ──────
def render_sidebar(page_label: str = ""):
    """
    Agrega filtros opcionales al sidebar.
    NO renderiza logo, status ni logout — esos van en app.py una sola vez.
    Retorna (activo: bool, filtro_nivel: list, filtro_zona: list)
    """
    with st.sidebar:
        filtro_nivel = st.multiselect(
            "Nivel de riesgo",
            ["CRITICO", "RIESGO", "NORMAL", "VENCIDO"],
            default=[],
            key=f"_f_nivel_{page_label}",
        )
        filtro_zona = st.multiselect(
            "Zona logística",
            list(ZONAS_ES.values()),
            default=[],
            key=f"_f_zona_{page_label}",
        )
    activo = _MELONN_API_DISPONIBLE and melonn_client.credenciales_ok()
    return activo, filtro_nivel, filtro_zona

# ── Detalle de pedido + guía ──────────────────────────────────────────────────
def render_detalle(df_tab: pd.DataFrame, tab_key: str):
    """Card de detalle + auto-apertura de guía Melonn."""
    if df_tab.empty:
        return

    st.markdown(f"<div class='sec-title'>Detalle de pedido y guía transportadora</div>", unsafe_allow_html=True)

    nivel_icono = {"CRITICO":"🔴","RIESGO":"🟠","NORMAL":"🟢"}
    etiquetas = {
        row["Orden"]: f"{nivel_icono.get(row['Nivel'],'·')} {row['Orden']}  ·  {row['Cliente'][:22]}  ·  {row['Ciudad']}  ·  {int(row['Días'])}d"
        for _, row in df_tab.iterrows()
    }
    opciones = list(etiquetas.keys())

    idx_default = 0
    tabla_key = f"tabla_{tab_key}"
    if (tabla_key in st.session_state
            and st.session_state[tabla_key].get("selection",{}).get("rows")):
        fi = st.session_state[tabla_key]["selection"]["rows"][0]
        if fi < len(df_tab):
            o = df_tab.iloc[fi]["Orden"]
            if o in opciones:
                idx_default = opciones.index(o)

    orden_sel = st.selectbox(
        "Buscar pedido (número de orden, cliente o ciudad)",
        opciones,
        index=idx_default,
        format_func=lambda o: etiquetas[o],
        key=f"sel_{tab_key}",
    )
    fila = df_tab[df_tab["Orden"] == orden_sel].iloc[0]
    nc   = {"CRITICO":CRITICO_COLOR,"RIESGO":RIESGO_COLOR,"NORMAL":NORMAL_COLOR}.get(fila["Nivel"], GRAPHITE_GREY)
    link = fila.get("Link Melonn","") or ""

    _badge_bg  = f"{nc}18"
    _badge_txt = nc
    st.markdown(f"""
    <div style="background:white;border-radius:10px;border:1px solid rgba(33,48,51,0.07);
                border-left:4px solid {nc};padding:20px 24px;margin-top:10px;
                box-shadow:0 2px 12px rgba(0,0,0,0.06);">
      <!-- fila 1: cliente / nivel / orden -->
      <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:16px;align-items:flex-start;">
        <div>
          <div style="font-size:0.58rem;letter-spacing:2.5px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Cliente</div>
          <div style="font-size:1.05rem;font-weight:700;color:{DEEP_INK};line-height:1.2;">{fila['Cliente']}</div>
          <div style="font-size:0.78rem;color:#909090;margin-top:2px;">{fila['Teléfono']}</div>
        </div>
        <div style="text-align:center;">
          <div style="font-size:0.58rem;letter-spacing:2.5px;color:#909090;text-transform:uppercase;margin-bottom:6px;">Nivel riesgo</div>
          <div style="display:inline-block;background:{_badge_bg};color:{_badge_txt};
                      font-size:0.7rem;font-weight:700;letter-spacing:2px;
                      text-transform:uppercase;padding:5px 12px;border-radius:20px;">
            {fila['Nivel']}
          </div>
          <div style="font-size:0.8rem;color:#909090;margin-top:5px;font-weight:500;">{int(fila['Score'])}/100</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.58rem;letter-spacing:2.5px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Orden</div>
          <div style="font-size:0.95rem;font-weight:700;color:{DEEP_INK};">{fila['Orden']}</div>
          <div style="font-size:0.78rem;color:#909090;margin-top:2px;">{fila.get('Método Envío', fila.get('Transportadora',''))}</div>
        </div>
      </div>
      <!-- separador -->
      <div style="height:1px;background:rgba(33,48,51,0.07);margin:14px 0;"></div>
      <!-- fila 2: datos operativos -->
      <div style="display:flex;gap:32px;flex-wrap:wrap;">
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Ciudad · Zona</div>
          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{fila['Ciudad']}</div>
          <div style="font-size:0.73rem;color:#909090;">{fila['Zona']}</div>
        </div>
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Tránsito · SLA</div>
          <div style="font-weight:700;color:{nc};font-size:0.85rem;">{int(fila['Días'])} días</div>
          <div style="font-size:0.73rem;color:#909090;">SLA crítico: {int(fila['SLA Crítico'])}d</div>
        </div>
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Despacho · Promesa</div>
          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{fila.get('F. Despacho','') or '—'}</div>
          <div style="font-size:0.73rem;color:{'#c0392b' if fila.get('Promesa vencida') == 'SÍ' else '#909090'};">
            {'⚠ ' if fila.get('Promesa vencida') == 'SÍ' else ''}{fila.get('F. Promesa','') or '—'}
          </div>
        </div>
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Modalidad pago</div>
          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{fila.get('Tipo_Recaudo', fila.get('COD','—'))}</div>
          <div style="font-size:0.73rem;color:#909090;">{fila['Valor COD']}</div>
        </div>
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Novedad</div>
          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{fila['Novedad']}</div>
          <div style="font-size:0.73rem;color:#909090;">{fila['Categoría']}</div>
        </div>
      </div>
      <!-- motivo riesgo -->
      <div style="margin-top:12px;padding:10px 14px;background:#f8f7f4;border-radius:6px;
                  border-left:3px solid {nc}22;">
        <span style="font-size:0.58rem;color:#909090;letter-spacing:2px;text-transform:uppercase;">Motivo · </span>
        <span style="font-size:0.8rem;font-weight:600;color:{DEEP_INK};">{fila['Motivo riesgo']}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"<div class='sec-title' style='margin-top:14px;'>Seguimiento Melonn — {fila.get('Método Envío', fila.get('Transportadora',''))}</div>", unsafe_allow_html=True)

    if link:
        components.html(f"""
        <!DOCTYPE html><html><head>
        <style>
          *{{margin:0;padding:0;box-sizing:border-box;font-family:Arial,sans-serif;}}
          body{{background:transparent;}}
          .wrap{{display:flex;align-items:center;gap:14px;padding:2px 0;}}
          .btn{{background:{DEEP_INK};color:{SOFT_CONCRETE};padding:8px 16px;font-size:0.68rem;
                letter-spacing:2px;text-transform:uppercase;text-decoration:none;
                border-radius:2px;font-weight:700;white-space:nowrap;}}
          .btn:hover{{background:{STEEL_BLUE};color:{DEEP_INK};}}
          .tag{{font-size:0.68rem;color:{STEEL_BLUE};letter-spacing:1px;}}
          .sub{{font-size:0.68rem;letter-spacing:1px;color:{GRAPHITE_GREY};}}
        </style></head><body>
        <div class="wrap">
          <a class="btn" href="{link}" target="_blank">→ ABRIR TRACKING</a>
          <div>
            <div class="tag">{fila['Orden']} · {fila.get('Método Envío', fila.get('Transportadora',''))}</div>
            <div class="sub">Haz clic en el botón para abrir la guía</div>
          </div>
        </div>
        </body></html>
        """, height=48)
    else:
        st.warning("Sin link de seguimiento para este pedido.")


# ── Helper de gráficos — compatible con todas las versiones de Altair ─────────
def simple_bar(serie: pd.Series, color: str = "#87a6b8", height: int = 200) -> None:
    """Bar chart de una serie simple usando plotly (compatible Python 3.14)."""
    import plotly.express as px
    df_p = serie.reset_index()
    df_p.columns = ["x", "y"]
    fig = px.bar(df_p, x="x", y="y", color_discrete_sequence=[color], height=height)
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
        xaxis_title="", yaxis_title="",
        font=dict(color=GRAPHITE_GREY, size=11),
    )
    fig.update_xaxes(tickangle=-20, tickfont=dict(color=GRAPHITE_GREY))
    fig.update_yaxes(tickfont=dict(color=GRAPHITE_GREY))
    st.plotly_chart(fig, use_container_width=True)


def safe_fmt_int(v):
    """Format int seguro contra NaN/None/string."""
    try:
        if pd.isna(v): return "—"
        return f"{int(float(v))}"
    except Exception:
        return "—" if v in (None, "") else str(v)


def safe_fmt_money(v):
    """Format monetario seguro contra NaN/None/string."""
    try:
        if pd.isna(v): return "—"
        return f"${float(v):,.0f}"
    except Exception:
        return "—" if v in (None, "") else str(v)


def render_tabla(df: pd.DataFrame, cols: list, key: str, height: int = 440):
    """
    Renderiza la tabla de pedidos con selección de fila y colores de nivel.
    El Styler ya no se usa porque st.dataframe(on_select=...) es incompatible
    con Styler en Streamlit Cloud. El formato lo hace column_config.
    """

    # Tabla con selección (sin Styler — incompatible con on_select en Cloud)
    event = st.dataframe(
        df[cols],
        use_container_width=True,
        height=height,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=key,
        column_config={
            "Nivel": st.column_config.Column("Nivel", help="🔴 Crítico  🟠 Riesgo  🟢 Normal"),
            "Score": st.column_config.NumberColumn("Score", format="%d"),
            "Días":  st.column_config.NumberColumn("Días", format="%d"),
            "Días sobre SLA": st.column_config.NumberColumn("Días s/SLA", format="%d"),
            "Link Melonn": st.column_config.LinkColumn("Link", display_text="Ver"),
        } if any(c in cols for c in ["Nivel","Score","Días","Link Melonn"]) else None,
    )

    sel_rows = event.selection.rows if hasattr(event, "selection") else []
    return sel_rows[0] if sel_rows else None


def bar_chart_zona_nivel(df: pd.DataFrame, height: int = 220) -> None:
    """
    Bar chart apilado por Zona × Nivel con colores de marca.
    Usa plotly (compatible con Python 3.14, sin el bug de altair TypedDict).
    """
    import plotly.express as px

    data = (
        df.groupby(["Zona", "Nivel"])
        .size()
        .reset_index(name="Pedidos")
    )
    if data.empty:
        st.info("Sin datos para graficar.")
        return

    orden_nivel = ["CRITICO", "RIESGO", "NORMAL"]
    color_map   = {
        "CRITICO": CRITICO_COLOR,
        "RIESGO":  RIESGO_COLOR,
        "NORMAL":  NORMAL_COLOR,
    }
    data["Nivel"] = pd.Categorical(data["Nivel"], categories=orden_nivel, ordered=True)
    data = data.sort_values(["Zona", "Nivel"])

    fig = px.bar(
        data,
        x="Zona", y="Pedidos", color="Nivel",
        color_discrete_map=color_map,
        barmode="stack",
        height=height,
        labels={"Pedidos": "Pedidos", "Zona": ""},
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", y=1.05, x=0,
                    font=dict(color=GRAPHITE_GREY)),
        font=dict(size=11, color=GRAPHITE_GREY),
    )
    fig.update_xaxes(tickangle=-20, tickfont=dict(color=GRAPHITE_GREY))
    fig.update_yaxes(tickfont=dict(color=GRAPHITE_GREY))
    st.plotly_chart(fig, use_container_width=True)
