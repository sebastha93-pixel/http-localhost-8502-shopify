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

# Estilo del sidebar global — compacto y de marca
st.markdown("""
<style>
/* Ocultar decoración por defecto de la navegación */
[data-testid="stSidebarNavItems"] { padding-top: 0 !important; }
[data-testid="stSidebarNavLink"] {
    border-radius: 3px !important;
    font-size: 0.82rem !important;
    letter-spacing: 0.5px !important;
    padding: 8px 14px !important;
    margin: 1px 0 !important;
}
[data-testid="stSidebarNavLink"]:hover {
    background: rgba(135,166,184,0.15) !important;
}
[data-testid="stSidebarNavLink"][aria-selected="true"] {
    background: rgba(135,166,184,0.25) !important;
    border-left: 3px solid #87a6b8 !important;
}
/* Cabecera de sección */
[data-testid="stSidebarNavSeparator"] {
    font-size: 0.6rem !important;
    letter-spacing: 3px !important;
    opacity: 0.6 !important;
}
</style>
""", unsafe_allow_html=True)

pg = st.navigation([
    st.Page("pages/logistica.py",      title="LOGÍSTICA"),
    st.Page("pages/3_conciliacion.py", title="CONCILIACIÓN"),
    st.Page("pages/4_shopify.py",      title="COMERCIAL"),
])

pg.run()
