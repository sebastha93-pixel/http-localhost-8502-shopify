"""
Male Denim OS — Punto de entrada principal
3 módulos: Logística · Conciliación · Shopify
"""

import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

import base64, io
import streamlit as st
from PIL import Image

_FAVICON = _HERE / "assets" / "favicon.png"
_icon = Image.open(_FAVICON) if _FAVICON.exists() else "📦"

st.set_page_config(
    page_title="MALE'DENIM OS",
    page_icon=_icon,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inyectar favicon vía HTML para que el browser tab lo tome correctamente
if _FAVICON.exists():
    _buf = io.BytesIO()
    Image.open(_FAVICON).save(_buf, format="PNG")
    _b64 = base64.b64encode(_buf.getvalue()).decode()
    st.markdown(
        f'<link rel="shortcut icon" href="data:image/png;base64,{_b64}" type="image/png">'
        f'<link rel="icon" href="data:image/png;base64,{_b64}" type="image/png">',
        unsafe_allow_html=True,
    )

# Estilo del sidebar global — refinado, editorial
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

/* Fondo sidebar */
[data-testid="stSidebar"] { background-color: #213033 !important; }

/* Logo en el header del sidebar (nombre de la app) */
[data-testid="stSidebarHeader"] {
  padding: 20px 20px 12px !important;
  border-bottom: 1px solid rgba(135,166,184,0.12) !important;
}

/* Nav items */
[data-testid="stSidebarNavItems"] { padding: 10px 8px 0 !important; }
[data-testid="stSidebarNavLink"] {
  font-family: 'Inter', sans-serif !important;
  border-radius: 6px !important;
  font-size: 0.65rem !important;
  font-weight: 700 !important;
  letter-spacing: 2.5px !important;
  text-transform: uppercase !important;
  padding: 10px 14px !important;
  margin: 2px 0 !important;
  color: rgba(224,222,221,0.88) !important;
  transition: all 0.15s ease !important;
}
[data-testid="stSidebarNavLink"]:hover {
  background: rgba(135,166,184,0.12) !important;
  color: white !important;
}
[data-testid="stSidebarNavLink"][aria-selected="true"] {
  background: rgba(135,166,184,0.18) !important;
  border-left: 3px solid #87a6b8 !important;
  color: white !important;
  padding-left: 11px !important;
}

/* Separador entre secciones nav */
[data-testid="stSidebarNavSeparator"] {
  font-family: 'Inter', sans-serif !important;
  font-size: 0.52rem !important;
  letter-spacing: 3px !important;
  opacity: 0.45 !important;
  padding: 14px 14px 4px !important;
  color: #87a6b8 !important;
}

/* Ocultar chrome */
#MainMenu { visibility: hidden !important; }
footer { visibility: hidden !important; }
[data-testid="stDeployButton"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

pg = st.navigation([
    st.Page("pages/logistica.py",      title="LOGÍSTICA"),
    st.Page("pages/3_conciliacion.py", title="CONCILIACIÓN"),
    st.Page("pages/4_shopify.py",      title="COMERCIAL"),
])

pg.run()
