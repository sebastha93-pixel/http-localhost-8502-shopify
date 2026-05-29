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
from datetime import datetime, timedelta
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
_INACTIVITY_HOURS = 3   # logout automático si no hay actividad en X horas

def _build_auth(remember_me: bool = False):
    """
    Construye el autenticador desde st.secrets.
    remember_me=True  → cookie dura 30 días (persiste al cerrar navegador)
    remember_me=False → cookie dura 0 días  (sesión de navegador, expira al cerrar)
    """
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
    cookie      = st.secrets.get("cookie", {})
    expiry_days = int(cookie.get("expiry_days", 30)) if remember_me else 0
    return stauth.Authenticate(
        creds,
        str(cookie.get("name", "maledenim_auth")),
        str(cookie.get("key",  "maledenim_key_2026")),
        expiry_days,
    )


def _check_inactivity(auth) -> bool:
    """
    Retorna True (y hace logout) si el usuario lleva más de _INACTIVITY_HOURS
    sin ninguna interacción. Actualiza last_activity en cada llamada.
    """
    ahora = datetime.now()
    ultima = st.session_state.get("last_activity")

    if ultima and (ahora - ultima) > timedelta(hours=_INACTIVITY_HOURS):
        auth.logout()
        st.session_state.clear()
        st.warning(
            f"⏱️ Sesión cerrada por inactividad ({_INACTIVITY_HOURS} horas). "
            "Inicia sesión nuevamente.",
            icon="🔒",
        )
        st.rerun()
        return True

    st.session_state["last_activity"] = ahora
    return False


_TODOS_LOS_MODULOS = ["logistica", "comercial", "mercadopago", "conciliacion"]

def _buscar_usuario(username: str) -> dict:
    """
    Busca el dict de un usuario en secrets sin importar mayúsculas.
    streamlit-authenticator puede guardar el username con capitalización
    diferente a la clave en secrets (ej. 'Lgarcia' vs 'lgarcia').
    """
    usuarios = st.secrets.get("credentials", {}).get("usernames", {})
    # Búsqueda exacta primero
    if username in usuarios:
        return dict(usuarios[username])
    # Fallback: comparación insensible a mayúsculas
    username_lower = username.lower()
    for key, data in usuarios.items():
        if key.lower() == username_lower:
            return dict(data)
    return {}


def _get_role(username: str) -> str:
    try:
        return str(_buscar_usuario(username).get("role", "user"))
    except Exception:
        return "user"


def _get_permisos(username: str, role: str) -> list:
    """
    Retorna lista de módulos habilitados para el usuario.
    Admin siempre tiene todos los módulos.
    """
    if role == "admin":
        return _TODOS_LOS_MODULOS.copy()
    try:
        raw = _buscar_usuario(username).get("permisos", [])
        return list(raw) if raw else []
    except Exception:
        return []


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
    # Leer preferencia "recordarme" guardada en session_state
    _remember = st.session_state.get("remember_me", False)
    _auth = _build_auth(remember_me=_remember)

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

    # ── Checkbox "Recordarme" debajo del form de login ─────────────────────────
    if not st.session_state.get("authentication_status"):
        _rem_nuevo = st.checkbox(
            "Recordarme en este dispositivo",
            value=_remember,
            key="chk_remember",
            help="Mantiene la sesión activa aunque cierres el navegador (30 días)",
        )
        if _rem_nuevo != _remember:
            st.session_state["remember_me"] = _rem_nuevo
            st.rerun()

    _status = st.session_state.get("authentication_status")

    if _status is True:
        # ── Verificar inactividad antes de mostrar el app ──────────────────────
        _check_inactivity(_auth)
        # ── Autenticado: mostrar app ───────────────────────────────────────────
        _username = st.session_state.get("username", "")
        _role     = _get_role(_username)
        _permisos = _get_permisos(_username, _role)

        # Guardar en session_state para que cada página pueda verificar
        st.session_state["permisos"] = _permisos
        st.session_state["user_role"] = _role

        # Logout + info usuario al fondo del sidebar
        with st.sidebar:
            _role_label = "Admin" if _role == "admin" else "Usuario"
            st.markdown(
                f"<div style='position:fixed;bottom:16px;left:0;width:240px;"
                f"padding:10px 16px;border-top:1px solid rgba(135,166,184,0.15);'>"
                f"<div style='font-size:0.6rem;color:#87a6b8;letter-spacing:1px;"
                f"text-transform:uppercase;margin-bottom:3px;'>{_role_label}</div>"
                f"<div style='font-size:0.78rem;color:#e0dedd;font-weight:600;'>"
                f"{st.session_state.get('name', _username)}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button("⎋  Cerrar sesión", use_container_width=True,
                         key="btn_logout"):
                _auth.logout()
                st.rerun()

        # ── Construir navegación según permisos ────────────────────────────────
        _ops = []
        if "logistica"  in _permisos: _ops.append(st.Page("pages/logistica.py",  title="LOGÍSTICA"))
        if "comercial"  in _permisos: _ops.append(st.Page("pages/4_shopify.py",  title="COMERCIAL"))

        _fin = []
        if "mercadopago"  in _permisos: _fin.append(st.Page("pages/mercadopago.py",    title="MERCADOPAGO"))
        if "conciliacion" in _permisos: _fin.append(st.Page("pages/3_conciliacion.py", title="CONCILIACIÓN"))

        _pages = {}
        if _ops: _pages["OPERACIONES"] = _ops
        if _fin: _pages["FINANZAS"]    = _fin
        if _role == "admin":
            _pages["CONFIGURACIÓN"] = [st.Page("pages/usuarios.py", title="USUARIOS")]

        if not _pages:
            st.warning("No tienes módulos asignados. Contacta al administrador.")
            st.stop()

        pg = st.navigation(_pages)
        pg.run()

    elif _status is False:
        st.error("Usuario o contraseña incorrectos. Intenta de nuevo.", icon="🔒")

    # Si _status is None → login form ya visible, nada más que hacer
