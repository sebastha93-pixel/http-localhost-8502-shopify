"""
Módulo compartido: colores, estilos, carga de datos y helpers.
Importado por cada página del dashboard.
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

# ── Paleta de marca MALE'DENIM ────────────────────────────────────────────────
DEEP_INK      = "#213033"
STEEL_BLUE    = "#87a6b8"
GRAPHITE_GREY = "#606060"
SOFT_CONCRETE = "#e1e1df"
CRITICO_COLOR = "#990012"
RIESGO_COLOR  = "#b95902"
NORMAL_COLOR  = "#036a73"
COD_COLOR     = "#59204d"

ZONAS_ES = {
    "MEDELLIN":       "Medellín / Área Metro",
    "BOGOTA_RAPIDAS": "Bogotá / Zonas Rápidas",
    "PRINCIPALES":    "Ciudades Principales",
    "SECUNDARIAS":    "Municipios / Pueblos",
    "REEXPEDIDO":     "Reexpedido",
}
ESTADOS_ES = {
    "Shipped - in transit":     "En tránsito",
    "Delivery not posible":     "Entrega no posible",
    "Packed":                   "Empacado",
    "Packed - on hold":         "Empacado - retenido",
    "Prepared for dispatch":    "Listo para despacho",
    "Delivered to buyer":       "Entregado",
    "Picked-up by buyer":       "Recogido",
    "Canceled":                 "Cancelado",
    "All items reserved - ready for fulfillment": "Reservado - listo",
    "All items reserved - fulfillment on hold - ext. conditionals": "Reservado - en espera",
    "on stand by - not able to fulfil - no stock": "Sin stock",
}

DEFAULT_CSV = str(Path(__file__).parent.parent / "data" / "logistica" / "raw" / "melonn_2026-05-12.csv")

# ── CSS global ────────────────────────────────────────────────────────────────
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Base ──────────────────────────────────────────────────────────────────── */
html, body, [class*="css"], .stMarkdown, .stText,
[data-testid="stMarkdownContainer"] * {{
  font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif !important;
}}
.stApp {{ background-color: #f0ede8 !important; }}
.main .block-container {{
  padding: 2rem 2.5rem 3rem !important;
  max-width: 1500px !important;
}}

/* ── Sidebar ───────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{
  background-color: {DEEP_INK} !important;
  border-right: 1px solid rgba(135,166,184,0.12) !important;
}}
[data-testid="stSidebar"] * {{ color: #e0dedd !important; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(135,166,184,0.18) !important; margin: 12px 0 !important; }}
[data-testid="stSidebar"] label {{ font-size:0.7rem !important; letter-spacing:1px !important; text-transform:uppercase !important; font-weight:600 !important; color: #c8cdd0 !important; }}
[data-testid="stSidebarNavItems"] {{ padding-top:0 !important; }}
[data-testid="stSidebarNavLink"] {{
  border-radius: 5px !important;
  font-size: 0.68rem !important;
  font-weight: 700 !important;
  letter-spacing: 2.5px !important;
  text-transform: uppercase !important;
  padding: 10px 14px !important;
  margin: 2px 4px !important;
  color: rgba(224,222,221,0.88) !important;
  transition: all 0.15s ease !important;
}}
[data-testid="stSidebarNavLink"]:hover {{
  background: rgba(135,166,184,0.12) !important;
  color: white !important;
}}
[data-testid="stSidebarNavLink"][aria-selected="true"] {{
  background: rgba(135,166,184,0.18) !important;
  border-left: 3px solid {STEEL_BLUE} !important;
  color: white !important;
}}

/* ── Tabs ──────────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  background: transparent !important;
  border-bottom: 1px solid rgba(33,48,51,0.12) !important;
  gap: 0 !important;
  padding: 0 !important;
}}
[data-baseweb="tab"] {{
  font-family: 'Inter', sans-serif !important;
  font-size: 0.67rem !important;
  font-weight: 700 !important;
  letter-spacing: 2px !important;
  text-transform: uppercase !important;
  color: #909090 !important;
  padding: 10px 20px 12px !important;
  background: transparent !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  margin-bottom: -1px !important;
  transition: color 0.15s ease !important;
}}
[data-baseweb="tab"][aria-selected="true"] {{
  color: {DEEP_INK} !important;
  border-bottom: 2px solid {DEEP_INK} !important;
  background: transparent !important;
}}
[data-baseweb="tab"]:hover {{ color: {DEEP_INK} !important; }}
[data-testid="stTabPanel"] {{ padding-top: 20px !important; background: transparent !important; }}
[data-baseweb="tab-highlight"] {{ display: none !important; }}
[data-baseweb="tab-border"] {{ display: none !important; }}

/* ── KPI Cards ─────────────────────────────────────────────────────────────── */
.kpi-card {{
  border-radius: 10px;
  padding: 18px 20px;
  margin-bottom: 4px;
  height: 116px;
  box-sizing: border-box;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
  box-shadow: 0 2px 12px rgba(0,0,0,0.14), 0 1px 3px rgba(0,0,0,0.08);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}}
.kpi-card:hover {{
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0,0,0,0.18), 0 2px 6px rgba(0,0,0,0.1);
}}
.kpi-crit  {{ background: linear-gradient(135deg, #990012 0%, #7a0010 100%); border-left: 3px solid #ff2244; }}
.kpi-ries  {{ background: linear-gradient(135deg, #b95902 0%, #9a4a00 100%); border-left: 3px solid #f5a623; }}
.kpi-norm  {{ background: linear-gradient(135deg, #036a73 0%, #025560 100%); border-left: 3px solid {STEEL_BLUE}; }}
.kpi-extra {{ background: linear-gradient(135deg, #59204d 0%, #451840 100%); border-left: 3px solid {STEEL_BLUE}; }}
.kpi-num   {{
  font-family: 'Inter', 'Arial Black', sans-serif;
  font-size: 1.85rem;
  font-weight: 800;
  color: white;
  margin: 0;
  line-height: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: -0.5px;
}}
.kpi-label {{
  font-family: 'Inter', sans-serif;
  font-size: 0.58rem;
  color: rgba(255,255,255,0.92);
  margin: 6px 0 0;
  letter-spacing: 2.5px;
  text-transform: uppercase;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.kpi-sub {{
  font-size: 0.62rem;
  color: rgba(255,255,255,0.82);
  margin: 3px 0 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 400;
}}

/* ── Section titles ────────────────────────────────────────────────────────── */
.sec-title {{
  font-family: 'Inter', sans-serif;
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: #3a5f6a;
  margin: 20px 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(58,95,106,0.18);
}}

/* ── Panel header ──────────────────────────────────────────────────────────── */
.titulo-panel {{
  font-family: 'Inter', 'Arial Black', sans-serif;
  font-size: 1.55rem;
  font-weight: 800;
  color: {DEEP_INK};
  letter-spacing: -0.8px;
  margin: 0;
  line-height: 1.1;
}}
.subtitulo {{
  font-size: 0.62rem;
  color: #505050;
  letter-spacing: 3px;
  text-transform: uppercase;
  margin-top: 4px;
  font-weight: 500;
}}

/* ── Sidebar brand ─────────────────────────────────────────────────────────── */
.logo-sidebar {{
  font-family: 'Inter', 'Arial Black', sans-serif;
  font-size: 1.15rem;
  font-weight: 800;
  color: white !important;
  line-height: 1;
  letter-spacing: 1px;
}}
.logo-tagline {{
  font-size: 0.55rem;
  letter-spacing: 5px;
  color: #a8c8d8 !important;
  margin-top: 3px;
  font-weight: 600;
}}

/* ── Expanders como cards ──────────────────────────────────────────────────── */
[data-testid="stExpander"] {{
  background: white !important;
  border: 1px solid rgba(33,48,51,0.07) !important;
  border-radius: 10px !important;
  box-shadow: 0 1px 6px rgba(0,0,0,0.05) !important;
  overflow: hidden !important;
  margin-bottom: 12px !important;
}}
[data-testid="stExpander"] details summary {{
  font-family: 'Inter', sans-serif !important;
  font-size: 0.68rem !important;
  font-weight: 700 !important;
  letter-spacing: 1.5px !important;
  text-transform: uppercase !important;
  color: {DEEP_INK} !important;
  padding: 14px 18px !important;
  user-select: none;
}}
[data-testid="stExpander"] details summary:hover {{
  background: rgba(33,48,51,0.02) !important;
}}
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
  padding: 4px 18px 18px !important;
}}

/* ── DataFrames ────────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] > div {{
  border-radius: 8px !important;
  overflow: hidden !important;
  box-shadow: 0 1px 6px rgba(0,0,0,0.06) !important;
  border: 1px solid rgba(33,48,51,0.07) !important;
}}

/* ── Botones ───────────────────────────────────────────────────────────────── */
.stButton > button {{
  font-family: 'Inter', sans-serif !important;
  font-size: 0.65rem !important;
  font-weight: 700 !important;
  letter-spacing: 2px !important;
  text-transform: uppercase !important;
  border-radius: 5px !important;
  border: 1.5px solid {DEEP_INK} !important;
  background: transparent !important;
  color: {DEEP_INK} !important;
  padding: 8px 18px !important;
  transition: all 0.15s ease !important;
}}
.stButton > button:hover {{
  background: {DEEP_INK} !important;
  color: #f0ede8 !important;
  border-color: {DEEP_INK} !important;
}}
.stButton > button[kind="primary"] {{
  background: {DEEP_INK} !important;
  color: #f0ede8 !important;
}}
.stButton > button[kind="primary"]:hover {{
  background: {STEEL_BLUE} !important;
  border-color: {STEEL_BLUE} !important;
  color: {DEEP_INK} !important;
}}
.stButton > button:disabled {{
  opacity: 0.35 !important;
  cursor: not-allowed !important;
}}

/* ── Download button ───────────────────────────────────────────────────────── */
.stDownloadButton button {{
  background: {DEEP_INK} !important;
  color: #f0ede8 !important;
  border: none !important;
  border-radius: 5px !important;
  letter-spacing: 2px;
  font-size: 0.65rem;
  font-weight: 700 !important;
  text-transform: uppercase;
  transition: all 0.15s ease !important;
}}
.stDownloadButton button:hover {{
  background: {STEEL_BLUE} !important;
  color: {DEEP_INK} !important;
}}

/* ── Labels de widgets (contenido principal) ───────────────────────────────── */
.stSelectbox > label p,
.stMultiSelect > label p,
.stTextInput > label p,
.stTextArea > label p,
.stSlider > label p,
.stDateInput > label p,
.stCheckbox > label p,
.stRadio > label p,
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] span {{
  color: {DEEP_INK} !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 0.72rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.3px !important;
}}

/* ── Inputs ────────────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {{
  border-radius: 5px !important;
  border: 1.5px solid rgba(33,48,51,0.18) !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 0.82rem !important;
  background: white !important;
  color: {DEEP_INK} !important;
  transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
}}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {{
  border-color: {STEEL_BLUE} !important;
  box-shadow: 0 0 0 3px rgba(135,166,184,0.18) !important;
}}
input::placeholder, textarea::placeholder {{
  color: #888888 !important;
  opacity: 1 !important;
}}

/* ── Select box: contenedor, valor seleccionado, placeholder ───────────────── */
[data-baseweb="select"] > div:first-child {{
  border-radius: 5px !important;
  border: 1.5px solid rgba(33,48,51,0.18) !important;
  background: white !important;
  font-size: 0.82rem !important;
}}
[data-baseweb="select"] span,
[data-baseweb="select"] div[class*="ValueContainer"] span,
[data-baseweb="select"] div[class*="singleValue"],
[data-baseweb="select"] div[class*="placeholder"],
[data-baseweb="select"] input {{
  color: {DEEP_INK} !important;
  font-family: 'Inter', sans-serif !important;
}}
[data-baseweb="select"] div[class*="placeholder"] {{
  color: #888888 !important;
}}

/* ── Dropdown menu del select ──────────────────────────────────────────────── */
[data-baseweb="menu"] li,
[data-baseweb="menu"] li span,
[data-baseweb="popover"] li span {{
  color: {DEEP_INK} !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 0.82rem !important;
}}

/* ── Multiselect: tags ─────────────────────────────────────────────────────── */
[data-baseweb="tag"] span {{
  color: {DEEP_INK} !important;
}}

/* ── Alerts ────────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {{
  border-radius: 7px !important;
  font-size: 0.8rem !important;
  font-family: 'Inter', sans-serif !important;
}}

/* ── Captions ──────────────────────────────────────────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] p {{
  font-size: 0.67rem !important;
  letter-spacing: 0.5px !important;
  color: #555555 !important;
  font-family: 'Inter', sans-serif !important;
}}

/* ── Headings ──────────────────────────────────────────────────────────────── */
h1,h2,h3,h4,h5 {{
  font-family: 'Inter', sans-serif !important;
  color: {DEEP_INK} !important;
  font-weight: 700 !important;
}}
hr {{ border-color: rgba(33,48,51,0.1) !important; margin: 14px 0 !important; }}

/* ── Spinner ───────────────────────────────────────────────────────────────── */
[data-testid="stSpinner"] p {{
  font-size: 0.75rem !important;
  letter-spacing: 1px !important;
  color: {GRAPHITE_GREY} !important;
}}

/* ── Scrollbar ─────────────────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width: 4px; height: 4px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: rgba(135,166,184,0.35); border-radius: 2px; }}
::-webkit-scrollbar-thumb:hover {{ background: rgba(135,166,184,0.6); }}

/* ── Ocultar chrome Streamlit ──────────────────────────────────────────────── */
#MainMenu {{ visibility: hidden !important; }}
footer {{ visibility: hidden !important; }}
[data-testid="stDeployButton"] {{ display: none !important; }}
[data-testid="stStatusWidget"] {{ display: none !important; }}
[data-testid="stToolbar"] {{ display: none !important; }}
</style>
"""

# ── Carga y procesamiento ─────────────────────────────────────────────────────
def _procesar_df(pedidos: list) -> pd.DataFrame:
    rows = []
    for p in pedidos:
        r = calcular_riesgo(
            ciudad=p["ciudad_destino"],
            dias_en_transito=p["dias_en_transito"],
            incidencia_raw=p.get("incidencia", "NINGUNO"),
            es_contraentrega=p["es_contraentrega"],
        )
        rows.append({
            "Prioridad":       r.prioridad,
            "Nivel":           r.nivel,
            "Score":           r.score,
            "Orden":           p.get("orden_tienda") or p.get("orden_melonn", ""),
            "Cliente":         p.get("nombre_comprador", ""),
            "Teléfono":        p.get("telefono_comprador", ""),
            "Ciudad":          p["ciudad_destino"],
            "Zona":            ZONAS_ES.get(r.zona_info.zona, r.zona_info.zona),
            "Días":            p["dias_en_transito"],
            "SLA Crítico":     r.zona_info.sla_critico,
            "Días sobre SLA":  max(0, p["dias_en_transito"] - r.zona_info.sla_critico + 1),
            "COD":             "SÍ" if p["es_contraentrega"] else "—",
            "Valor COD":       p.get("valor_cod_raw", ""),
            "Transportadora":  p.get("transportadora", ""),
            "Estado":          ESTADOS_ES.get(p.get("estado_melonn",""), p.get("estado_melonn","")),
            "Novedad":         p.get("incidencia", "NINGUNO"),
            "Categoría":       r.incidencia_info.categoria,
            "Promesa vencida": "SÍ" if p.get("promesa_vencida") else "—",
            "F. Despacho":     str(p.get("fecha_despacho") or ""),
            "Motivo riesgo":   r.motivos[0] if r.motivos else "—",
            "Link Melonn":     p.get("link_guia", ""),
        })
    df = pd.DataFrame(rows)
    return df.sort_values(["Prioridad","Días sobre SLA"], ascending=[True,False]).reset_index(drop=True)

@st.cache_data(show_spinner=False)
def cargar_datos(ruta: str, ts: str):
    pedidos, omitidos = leer_csv_melonn(ruta, solo_activos=True)
    df = _procesar_df(pedidos)
    return df, omitidos

def color_nivel(val):
    return {
        "CRITICO": f"background-color:{CRITICO_COLOR}22;color:{CRITICO_COLOR};font-weight:700",
        "RIESGO":  f"background-color:{RIESGO_COLOR}22;color:{RIESGO_COLOR};font-weight:600",
        "NORMAL":  f"background-color:{NORMAL_COLOR}22;color:{NORMAL_COLOR}",
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

# ── Sidebar compartido ────────────────────────────────────────────────────────
def render_sidebar(page_label: str):
    """Renderiza sidebar con logo, uploader y filtros. Retorna (ruta_csv, ts, filtros)."""
    with st.sidebar:
        st.markdown(f"""
            <div style="padding:8px 0 14px 0;">
                <div class="logo-sidebar">MALE'DENIM</div>
                <div class="logo-tagline">THAT FITS</div>
            </div>
        """, unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:0.68rem;letter-spacing:2px;color:{STEEL_BLUE};text-transform:uppercase;margin-bottom:10px;'>{page_label}</div>", unsafe_allow_html=True)
        st.divider()

        archivo = st.file_uploader("Cargar reporte Melonn (CSV)", type=["csv"])

        st.divider()
        st.markdown(f"<div style='font-size:0.68rem;letter-spacing:2px;color:{STEEL_BLUE};text-transform:uppercase;margin-bottom:6px;'>Filtros</div>", unsafe_allow_html=True)

        filtro_nivel = st.multiselect(
            "Nivel de riesgo",
            ["CRITICO","RIESGO","NORMAL"],
            default=["CRITICO","RIESGO"],
        )
        filtro_zona = st.multiselect("Zona logística", list(ZONAS_ES.values()), default=[])

        st.divider()
        st.markdown(f"<div style='font-size:0.68rem;color:{STEEL_BLUE};'>{date.today().strftime('%d / %m / %Y')}</div>", unsafe_allow_html=True)

    if archivo:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(archivo.read())
            ruta_csv = tmp.name
        ts = archivo.name
    else:
        # En Streamlit Cloud el CSV demo puede no existir → None para manejarlo en cada página
        if Path(DEFAULT_CSV).exists():
            ruta_csv = DEFAULT_CSV
            ts = "Demo — melonn_2026-05-12"
        else:
            ruta_csv = None
            ts = "Sin datos — sube un CSV de Melonn"

    return ruta_csv, ts, filtro_nivel, filtro_zona

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
          <div style="font-size:0.78rem;color:#909090;margin-top:2px;">{fila['Transportadora']}</div>
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
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Modalidad pago</div>
          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{fila['COD']}</div>
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

    st.markdown(f"<div class='sec-title' style='margin-top:14px;'>Seguimiento Melonn — {fila['Transportadora']}</div>", unsafe_allow_html=True)

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
          .st{{font-size:0.68rem;letter-spacing:1.5px;text-transform:uppercase;color:{GRAPHITE_GREY};}}
          .st.ok{{color:{NORMAL_COLOR};}} .st.err{{color:{RIESGO_COLOR};}}
        </style></head><body>
        <div class="wrap">
          <a class="btn" href="{link}" target="_blank">→ ABRIR TRACKING</a>
          <div>
            <div class="tag">{fila['Orden']} · {fila['Transportadora']}</div>
            <div class="st" id="s">Abriendo guía automáticamente...</div>
          </div>
        </div>
        <script>
        (function(){{
          var w=window.open("{link}","_blank","noopener,noreferrer");
          var s=document.getElementById('s');
          if(w){{s.textContent='✓ Guía abierta en nueva pestaña';s.className='st ok';}}
          else{{s.textContent='Bloqueado — usa el botón';s.className='st err';}}
        }})();
        </script></body></html>
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


def render_tabla(df: pd.DataFrame, cols: list, key: str, height: int = 440):
    """
    Renderiza la tabla de pedidos con selección de fila y colores de nivel.
    Separa styling de on_select para compatibilidad con Streamlit Cloud.
    Retorna el índice de fila seleccionada (o None).
    """
    NIVEL_COLORES = {"CRITICO": CRITICO_COLOR, "RIESGO": RIESGO_COLOR, "NORMAL": NORMAL_COLOR}

    # Columnas numéricas que formateamos
    fmt = {}
    for c in ["Score", "Días", "Días sobre SLA"]:
        if c in cols:
            fmt[c] = "{:.0f}"

    # Styler solo para colorear — sin on_select
    styled = df[cols].style
    if "Nivel" in cols:
        styled = styled.map(color_nivel, subset=["Nivel"])
    if fmt:
        styled = styled.format(fmt)

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
