"""
MALE'DENIM OS — Design System
Tokens de color, tipografía, espaciado y CSS global.
"""

# ── Paleta corporativa ─────────────────────────────────────────────────────────
PURE_BLACK     = "#000000"
DEEP_INK       = "#213033"
GRAPHITE_GREY  = "#606060"
SOFT_CONCRETE  = "#E1E1DF"
STEEL_BLUE     = "#87A6B8"

# ── Complementarios ────────────────────────────────────────────────────────────
NAVY           = "#0C457A"
CREAM          = "#F1EAD8"
KHAKI          = "#7B6E42"
TEAL           = "#036A73"
FOREST         = "#373D2F"
BURGUNDY       = "#59204D"
PEACH          = "#F7C5A0"
RUST           = "#B95902"
MAUVE          = "#D19EBD"
CRIMSON        = "#990012"

# ── Surface / UI ──────────────────────────────────────────────────────────────
SURFACE_BG     = "#F7F5F2"   # fondo principal
SURFACE_CARD   = "#FFFFFF"   # cards
SURFACE_HOVER  = "#F2F0ED"   # hover states
BORDER_DEFAULT = "#E6E4E0"   # bordes suaves
BORDER_STRONG  = "#D4D2CE"

# ── Estados operativos ─────────────────────────────────────────────────────────
COLOR_CRITICO  = CRIMSON      # #990012
COLOR_RIESGO   = RUST         # #B95902
COLOR_NORMAL   = TEAL         # #036A73
COLOR_PENDIENTE= KHAKI        # #7B6E42
COLOR_INFO     = NAVY         # #0C457A
COLOR_NEUTRO   = GRAPHITE_GREY

# Fondos suaves para badges
BG_CRITICO  = "#FDF0F0"
BG_RIESGO   = "#FDF4EE"
BG_NORMAL   = "#EFF8F7"
BG_PENDIENTE= "#F5F3EC"
BG_INFO     = "#EEF3FA"
BG_NEUTRO   = "#F4F4F2"

# ── CSS Global ────────────────────────────────────────────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Reset Streamlit ────────────────────────────────────────────────────────── */
#MainMenu, footer, header,
[data-testid="stDeployButton"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"]          { visibility: hidden !important; display: none !important; }

/* ── App background ─────────────────────────────────────────────────────────── */
html, body, .stApp                      { background: #F7F5F2 !important; }
.main .block-container                  {
    padding: 2rem 2.5rem 3rem !important;
    max-width: 100% !important;
    font-family: 'Inter', sans-serif;
}

/* ── Sidebar ────────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0D1A1D 0%, #1A2B2F 60%, #213033 100%) !important;
    border-right: 1px solid rgba(135,166,184,0.08) !important;
    width: 236px !important;
}
[data-testid="stSidebarContent"]        { padding: 0 !important; }
[data-testid="stSidebarHeader"]         { display: none !important; }
[data-testid="stSidebarNavItems"]       { padding: 6px 12px 0 !important; }

/* Nav links */
[data-testid="stSidebarNavLink"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.68rem !important;
    font-weight: 600 !important;
    letter-spacing: 1.8px !important;
    text-transform: uppercase !important;
    color: rgba(225,225,223,0.72) !important;
    border-radius: 7px !important;
    padding: 9px 12px !important;
    margin: 1px 0 !important;
    transition: all 0.15s ease !important;
}
[data-testid="stSidebarNavLink"]:hover  {
    background: rgba(135,166,184,0.10) !important;
    color: #E1E1DF !important;
}
[data-testid="stSidebarNavLink"][aria-selected="true"] {
    background: rgba(135,166,184,0.15) !important;
    border-left: 2px solid #87A6B8 !important;
    color: #FFFFFF !important;
    padding-left: 10px !important;
}
[data-testid="stSidebarNavSeparator"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.52rem !important;
    letter-spacing: 3px !important;
    color: rgba(135,166,184,0.45) !important;
    padding: 14px 14px 4px !important;
    text-transform: uppercase !important;
}

/* ── Tipografía global ──────────────────────────────────────────────────────── */
h1, h2, h3, h4, h5, h6,
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
    font-family: 'Inter', sans-serif !important;
    color: #213033 !important;
}

/* ── Tabs ────────────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tablist"]  {
    background: transparent !important;
    border-bottom: 1.5px solid #E6E4E0 !important;
    gap: 0 !important;
    padding: 0 !important;
}
[data-testid="stTabs"] button[role="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    letter-spacing: 1.2px !important;
    text-transform: uppercase !important;
    color: #606060 !important;
    background: transparent !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    padding: 10px 18px !important;
    border-radius: 0 !important;
    transition: all 0.15s !important;
}
[data-testid="stTabs"] button[role="tab"]:hover {
    color: #213033 !important;
    background: rgba(33,48,51,0.04) !important;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #213033 !important;
    border-bottom: 2px solid #213033 !important;
}
[data-testid="stTabs"] [role="tabpanel"] {
    padding: 20px 0 0 !important;
}

/* ── Botones ─────────────────────────────────────────────────────────────────── */
.stButton > button {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
    border-radius: 8px !important;
    padding: 9px 18px !important;
    transition: all 0.15s !important;
}
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {
    background: #213033 !important;
    color: white !important;
    border: none !important;
}
.stButton > button[kind="primary"]:hover {
    background: #0D1A1D !important;
}
.stButton > button[kind="secondary"],
.stButton > button[data-testid="baseButton-secondary"] {
    background: white !important;
    color: #213033 !important;
    border: 1px solid #E6E4E0 !important;
}
.stButton > button[kind="secondary"]:hover {
    background: #F7F5F2 !important;
    border-color: #D4D2CE !important;
}

/* ── Inputs ──────────────────────────────────────────────────────────────────── */
.stTextInput > div > input,
.stSelectbox > div > div,
.stTextArea > div > textarea {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.82rem !important;
    border: 1px solid #E6E4E0 !important;
    border-radius: 8px !important;
    background: white !important;
    color: #213033 !important;
    box-shadow: none !important;
}
.stTextInput > div > input:focus,
.stSelectbox > div > div:focus,
.stTextArea > div > textarea:focus {
    border-color: #87A6B8 !important;
    box-shadow: 0 0 0 3px rgba(135,166,184,0.15) !important;
}

/* ── DataFrames / Tablas ─────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #E6E4E0 !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}
[data-testid="stDataFrame"] table                { font-family: 'Inter', sans-serif !important; }
[data-testid="stDataFrame"] th {
    background: #F7F5F2 !important;
    color: #606060 !important;
    font-size: 0.65rem !important;
    font-weight: 600 !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid #E6E4E0 !important;
    padding: 10px 14px !important;
}
[data-testid="stDataFrame"] td {
    font-size: 0.82rem !important;
    color: #213033 !important;
    padding: 10px 14px !important;
    border-bottom: 1px solid #F2F0ED !important;
}
[data-testid="stDataFrame"] tr:last-child td     { border-bottom: none !important; }
[data-testid="stDataFrame"] tr:hover td          { background: #F7F5F2 !important; }

/* ── Alertas / Info boxes ────────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.82rem !important;
    border-left-width: 3px !important;
}

/* ── Expanders ───────────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #E6E4E0 !important;
    border-radius: 12px !important;
    background: white !important;
}
[data-testid="stExpander"] summary {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.5px !important;
    color: #213033 !important;
    padding: 14px 16px !important;
}

/* ── Métricas nativas ────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: white !important;
    border: 1px solid #E6E4E0 !important;
    border-radius: 14px !important;
    padding: 16px 20px !important;
}
[data-testid="stMetricLabel"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.65rem !important;
    font-weight: 600 !important;
    letter-spacing: 2px !important;
    text-transform: uppercase !important;
    color: #606060 !important;
}
[data-testid="stMetricValue"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 1.7rem !important;
    font-weight: 700 !important;
    color: #213033 !important;
}

/* ── Scrollbars ──────────────────────────────────────────────────────────────── */
::-webkit-scrollbar               { width: 5px; height: 5px; }
::-webkit-scrollbar-track         { background: transparent; }
::-webkit-scrollbar-thumb         { background: #D4D2CE; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover   { background: #87A6B8; }

/* ── Download button ─────────────────────────────────────────────────────────── */
.stDownloadButton > button {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.8px !important;
    background: white !important;
    color: #213033 !important;
    border: 1px solid #E6E4E0 !important;
    border-radius: 8px !important;
    padding: 8px 16px !important;
}

/* ── Dividers ────────────────────────────────────────────────────────────────── */
hr { border: none !important; border-top: 1px solid #E6E4E0 !important; margin: 1rem 0 !important; }

/* ── Selectbox label ─────────────────────────────────────────────────────────── */
.stSelectbox label, .stTextInput label, .stTextArea label {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.65rem !important;
    font-weight: 600 !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
    color: #606060 !important;
}

/* ── Caption ─────────────────────────────────────────────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.72rem !important;
    color: #606060 !important;
}

/* ── Spinner ─────────────────────────────────────────────────────────────────── */
.stSpinner > div { border-top-color: #213033 !important; }

</style>
"""
