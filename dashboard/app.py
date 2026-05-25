"""
Male Denim OS — Punto de entrada principal
Usa st.navigation() para organizar los módulos en secciones.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import streamlit as st

st.set_page_config(
    page_title="MALE'DENIM OS",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE = Path(__file__).parent / "pages"

pg = st.navigation({
    "📦 Logística": [
        st.Page(str(BASE / "logistica" / "0_insights.py"),       title="Insights",         icon="📊"),
        st.Page(str(BASE / "logistica" / "1_contraentregas.py"), title="Contraentregas",   icon="💰"),
        st.Page(str(BASE / "logistica" / "2_pago_previo.py"),    title="Pago Previo",      icon="✅"),
    ],
    "💼 Conciliación": [
        st.Page(str(BASE / "3_conciliacion.py"),                  title="Conciliación",     icon="💼"),
    ],
    "🛍️ Comercial": [
        st.Page(str(BASE / "4_shopify.py"),                       title="Shopify",          icon="🛍️"),
    ],
})

pg.run()
