"""
Male Denim OS — Punto de entrada principal
Usa st.navigation() para organizar los módulos en secciones.
"""

import sys
from pathlib import Path

# Asegurar que dashboard/ y src/ estén en el path
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

import streamlit as st

st.set_page_config(
    page_title="MALE'DENIM OS",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

pg = st.navigation({
    "📦 Logística": [
        st.Page("pages/logistica/0_insights.py",       title="Insights",       icon="📊"),
        st.Page("pages/logistica/1_contraentregas.py", title="Contraentregas", icon="💰"),
        st.Page("pages/logistica/2_pago_previo.py",    title="Pago Previo",    icon="✅"),
    ],
    "💼 Conciliación": [
        st.Page("pages/3_conciliacion.py",             title="Conciliación",   icon="💼"),
    ],
    "🛍️ Comercial": [
        st.Page("pages/4_shopify.py",                  title="Shopify",        icon="🛍️"),
    ],
})

pg.run()
