"""
Male Denim OS — Punto de entrada principal
Autenticación con streamlit-authenticator antes de mostrar cualquier módulo.
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

# Favicon
if _FAVICON.exists():
    _buf = io.BytesIO()
    Image.open(_FAVICON).save(_buf, format="PNG")
    _b64 = base64.b64encode(_buf.getvalue()).decode()
    st.markdown(
        f'<link rel="shortcut icon" href="data:image/png;base64,{_b64}" type="image/png">'
        f'<link rel="icon" href="data:image/png;base64,{_b64}" type="image/png">',
        unsafe_allow_html=True,
    )

# ── CSS global ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

[data-testid="stSidebar"] { background-color: #213033 !important; }
[data-testid="stSidebarHeader"] {
  padding: 20px 20px 12px !important;
  border-bottom: 1px solid rgba(135,166,184,0.12) !important;
}
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
[data-testid="stSidebarNavSeparator"] {
  font-family: 'Inter', sans-serif !important;
  font-size: 0.52rem !important;
  letter-spacing: 3px !important;
  opacity: 0.45 !important;
  padding: 14px 14px 4px !important;
  color: #87a6b8 !important;
}
#MainMenu { visibility: hidden !important; }
footer { visibility: hidden !important; }
[data-testid="stDeployButton"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }

/* ── Login page ─────────────────────────────────────────────────────────────── */
.login-brand {
  font-family: 'Inter', 'Arial Black', sans-serif;
  font-size: 2.2rem;
  font-weight: 800;
  color: #213033;
  letter-spacing: 2px;
  line-height: 1;
}
.login-tagline {
  font-size: 0.7rem;
  letter-spacing: 6px;
  color: #87a6b8;
  font-weight: 600;
  margin-top: 4px;
  text-transform: uppercase;
}
.login-divider {
  width: 40px;
  height: 2px;
  background: #213033;
  margin: 18px 0;
}
</style>
""", unsafe_allow_html=True)


# ── Autenticación ──────────────────────────────────────────────────────────────
def _build_auth():
    """Construye el autenticador desde st.secrets."""
    import streamlit_authenticator as stauth

    creds = {
        "usernames": {
            username: {
                "name":     str(data.get("name", username)),
                "email":    str(data.get("email", "")),
                "password": str(data.get("password", "")),
            }
            for username, data in st.secrets.get("credentials", {})
                                              .get("usernames", {}).items()
        }
    }
    cookie = st.secrets.get("cookie", {})
    return stauth.Authenticate(
        creds,
        str(cookie.get("name",        "maledenim_auth")),
        str(cookie.get("key",         "maledenim_key_2026")),
        int(cookie.get("expiry_days", 30)),
    )


def _get_role(username: str) -> str:
    try:
        return str(
            st.secrets["credentials"]["usernames"][username].get("role", "user")
        )
    except Exception:
        return "user"


# Verificar si auth está configurada en secrets
_AUTH_CONFIGURADA = (
    "credentials" in st.secrets
    and "cookie" in st.secrets
)

if not _AUTH_CONFIGURADA:
    # Sin auth configurada → corre sin protección (desarrollo local)
    pg = st.navigation({
        "OPERACIONES": [
            st.Page("pages/logistica.py", title="LOGÍSTICA"),
            st.Page("pages/4_shopify.py", title="COMERCIAL"),
        ],
        "FINANZAS": [
            st.Page("pages/mercadopago.py",    title="MERCADOPAGO"),
            st.Page("pages/3_conciliacion.py", title="CONCILIACIÓN"),
        ],
    })
    pg.run()

else:
    _auth = _build_auth()

    # ── Página de login ────────────────────────────────────────────────────────
    if not st.session_state.get("authentication_status"):
        # Ocultar sidebar durante el login
        st.markdown("""
        <style>
        [data-testid="stSidebar"] { display: none !important; }
        .main .block-container { max-width: 460px !important; padding-top: 6rem !important; }
        </style>
        """, unsafe_allow_html=True)

        # Branding
        st.markdown("""
        <div style="text-align:center;margin-bottom:32px;">
            <div class="login-brand">MALE'DENIM</div>
            <div class="login-tagline">That Fits</div>
            <div class="login-divider" style="margin:18px auto;"></div>
        </div>
        """, unsafe_allow_html=True)

    # Render login widget (siempre — gestiona cookies automáticamente)
    _auth.login()

    _status = st.session_state.get("authentication_status")

    if _status is True:
        # ── Autenticado: mostrar app ───────────────────────────────────────────
        _username = st.session_state.get("username", "")
        _role     = _get_role(_username)

        # Logout + info usuario al fondo del sidebar
        with st.sidebar:
            st.markdown(
                f"<div style='position:fixed;bottom:16px;left:0;width:240px;"
                f"padding:10px 16px;border-top:1px solid rgba(135,166,184,0.15);'>"
                f"<div style='font-size:0.6rem;color:#87a6b8;letter-spacing:1px;"
                f"text-transform:uppercase;'>Usuario</div>"
                f"<div style='font-size:0.78rem;color:#e0dedd;font-weight:600;margin-top:2px;'>"
                f"{st.session_state.get('name', _username)}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button("⎋  Cerrar sesión", use_container_width=True,
                         key="btn_logout"):
                _auth.logout()
                st.rerun()

        # Construir navegación según rol
        _pages = {
            "OPERACIONES": [
                st.Page("pages/logistica.py", title="LOGÍSTICA"),
                st.Page("pages/4_shopify.py", title="COMERCIAL"),
            ],
            "FINANZAS": [
                st.Page("pages/mercadopago.py",    title="MERCADOPAGO"),
                st.Page("pages/3_conciliacion.py", title="CONCILIACIÓN"),
            ],
        }
        if _role == "admin":
            _pages["CONFIGURACIÓN"] = [
                st.Page("pages/usuarios.py", title="USUARIOS"),
            ]

        pg = st.navigation(_pages)
        pg.run()

    elif _status is False:
        st.error("Usuario o contraseña incorrectos. Intenta de nuevo.", icon="🔒")

    # Si _status is None → login form ya visible, nada más que hacer
