"""
Male Denim OS — Punto de entrada principal
Autenticación con streamlit-authenticator antes de mostrar cualquier módulo.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

import base64, io, time
from datetime import datetime, timedelta
import streamlit as st
from PIL import Image

# Timer global — mide tiempo desde el inicio del script hasta el final del render
_T0 = time.perf_counter()

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
    _remember = st.session_state.get("remember_me", False)
    _auth     = _build_auth(remember_me=_remember)

    # ── PRIMER PASO: leer cookie / state ANTES de cualquier render ────────────
    # streamlit-authenticator necesita inicializarse para que la cookie sea leída.
    # Lo hacemos en un placeholder no visible para que NO renderice el form aquí.
    _status_pre = st.session_state.get("authentication_status")

    # ── Si NO hay sesión, renderizar login inline (sin st.navigation) ─────────
    if _status_pre is not True:
        # Ocultar el sidebar agresivamente — antes de cualquier widget
        st.markdown("""
<style>
[data-testid="stSidebar"], section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"] {
    display: none !important;
    visibility: hidden !important;
}
.main .block-container { max-width: 460px !important; padding-top: 6rem !important; }
</style>
""", unsafe_allow_html=True)

        st.markdown("""
<div style="text-align:center;margin-bottom:32px;">
  <div class="login-brand">MALE'DENIM</div>
  <div class="login-tagline">That Fits</div>
  <div class="login-divider" style="margin:18px auto;"></div>
</div>
""", unsafe_allow_html=True)

        _auth.login()

        _rem   = st.session_state.get("remember_me", False)
        _nuevo = st.checkbox(
            "Recordarme en este dispositivo", value=_rem, key="chk_remember",
            help="Mantiene la sesión activa aunque cierres el navegador (30 días)",
        )
        if _nuevo != _rem:
            st.session_state["remember_me"] = _nuevo
            st.rerun()

        if st.session_state.get("authentication_status") is False:
            st.error("Usuario o contraseña incorrectos.", icon="🔒")
        if st.session_state.get("authentication_status") is True:
            st.rerun()
        st.stop()   # detiene la ejecución antes de que se intente st.navigation

    # ── Hay sesión → continuar con la navegación autenticada ──────────────────
    _status = True

    if _status is True:
        _check_inactivity(_auth)
        _username = st.session_state.get("username", "")
        _role     = _get_role(_username)
        _permisos = _get_permisos(_username, _role)

        st.session_state["permisos"]  = _permisos
        st.session_state["user_role"] = _role

        # ── Estado de la caché Melonn (cacheado en session_state, no golpea Supabase) ──
        try:
            from shared import _cache_info_rapido, _invalidar_cache_info
            _info = _cache_info_rapido()
        except Exception:
            _info = None
            _invalidar_cache_info = lambda: None

        if _info:
            _age = int(_info.get("age_s", 0))
            _age_txt = (f"hace {_age//3600}h" if _age >= 3600
                        else f"hace {_age//60}min" if _age >= 60
                        else "ahora")
            _total   = _info.get("total", 0)
            _stale   = _info.get("stale") or False
            _sync_tag   = "Desactualizado" if _stale else "Sincronizado"
            _sync_color = "#f5a623" if _stale else "#52b788"
            _sync_sub   = f"{_total} pedidos · {_age_txt}"
        else:
            _sync_tag, _sync_color, _sync_sub = "Sin datos", "#87a6b8", "Presiona actualizar"

        # ── ÚNICO sidebar de la app ──────────────────────────────────────────────
        with st.sidebar:
            # Logo
            st.markdown("""
            <div style="padding:18px 4px 14px;margin-bottom:6px;
                        border-bottom:1px solid rgba(135,166,184,0.1);">
              <p style="font-size:1rem;font-weight:800;letter-spacing:4px;
                        color:#fff;margin:0;line-height:1;">MALE'DENIM</p>
              <p style="font-size:0.5rem;font-weight:600;letter-spacing:5px;
                        color:rgba(135,166,184,0.65);margin:3px 0 0 0;">THAT FITS</p>
            </div>
            """, unsafe_allow_html=True)

        # La navegación de Streamlit se renderiza automáticamente entre los dos bloques

        with st.sidebar:
            # Estado de sincronización
            st.markdown(f"""
            <div style="background:rgba(135,166,184,0.08);
                        border:1px solid rgba(135,166,184,0.18);
                        border-radius:8px;padding:10px 12px;margin:12px 0 8px;">
              <div style="font-size:0.55rem;color:{_sync_color};letter-spacing:1.5px;
                          font-weight:700;text-transform:uppercase;">● {_sync_tag}</div>
              <div style="font-size:0.65rem;color:rgba(225,225,223,0.7);margin-top:3px;">{_sync_sub}</div>
            </div>
            """, unsafe_allow_html=True)

            if st.button("↻  Actualizar datos", use_container_width=True, key="btn_refresh"):
                st.session_state["_melonn_refresh"] = True
                _invalidar_cache_info()
                st.rerun()

            # Footer: usuario + logout
            _role_label = "Admin" if _role == "admin" else "Usuario"
            _full_name  = st.session_state.get("name", _username)
            st.markdown(f"""
            <div style="margin-top:18px;padding-top:14px;
                        border-top:1px solid rgba(135,166,184,0.1);">
              <div style="font-size:0.55rem;color:#87a6b8;letter-spacing:1.5px;
                          text-transform:uppercase;margin-bottom:2px;">{_role_label}</div>
              <div style="font-size:0.78rem;color:#e0dedd;font-weight:600;
                          margin-bottom:8px;">{_full_name}</div>
            </div>
            """, unsafe_allow_html=True)

            if st.button("⎋  Cerrar sesión", use_container_width=True, key="btn_logout"):
                _auth.logout()
                for k in ("_api_datos","_api_datos_ts","_cache_info","_cache_info_ts"):
                    st.session_state.pop(k, None)
                st.rerun()

            _elapsed_ms = int((time.perf_counter() - _T0) * 1000)
            st.markdown(f"""
            <p style="font-size:0.5rem;color:rgba(135,166,184,0.35);
                      letter-spacing:1px;margin:12px 0 0 0;text-align:center;">
              MALE'DENIM OS · v1.0 · {_elapsed_ms}ms
            </p>
            """, unsafe_allow_html=True)

        # ── Construir navegación según el mockup ─────────────────────────────────
        from placeholders import (
            contraentrega, envios, devoluciones, incidencias,
            finanzas as finanzas_page, facturacion,
            comercial as comercial_page, inventario,
            inteligencia, reportes,
            configuracion,
        )

        _home = [st.Page("pages/home.py", title="Centro de Control", icon="🏠", default=True)]

        _ops = []
        if "logistica" in _permisos:
            _ops.append(st.Page("pages/logistica.py", title="Logística", icon="📦"))
            _ops.append(st.Page(contraentrega, title="Contraentrega", icon="💵", url_path="contraentrega"))
            _ops.append(st.Page(envios,        title="Envíos",        icon="🚚", url_path="envios"))
            _ops.append(st.Page(devoluciones,  title="Devoluciones",  icon="🔄", url_path="devoluciones"))
            _ops.append(st.Page(incidencias,   title="Incidencias",   icon="⚠️", url_path="incidencias"))

        _fin = []
        if "conciliacion" in _permisos:
            _fin.append(st.Page(finanzas_page,                   title="Finanzas",     icon="💰", url_path="finanzas"))
            _fin.append(st.Page("pages/3_conciliacion.py",       title="Conciliación", icon="🔗"))
            _fin.append(st.Page(facturacion,                     title="Facturación",  icon="🧾", url_path="facturacion"))
        if "mercadopago"  in _permisos:
            _fin.append(st.Page("pages/mercadopago.py",          title="MercadoPago",  icon="💳"))

        _com = []
        if "comercial" in _permisos:
            _com.append(st.Page("pages/4_shopify.py", title="Comercial",  icon="📈"))
            _com.append(st.Page(inventario,           title="Inventario", icon="📋", url_path="inventario"))

        _int = []
        _int.append(st.Page(inteligencia, title="Inteligencia", icon="🧠", url_path="inteligencia"))
        _int.append(st.Page(reportes,     title="Reportes",     icon="📊", url_path="reportes"))

        _pages = {"": _home}
        if _ops: _pages["Operaciones"]  = _ops
        if _fin: _pages["Finanzas"]     = _fin
        if _com: _pages["Comercial"]    = _com
        if _int: _pages["Inteligencia"] = _int

        _conf = []
        _conf.append(st.Page(configuracion, title="Configuración", icon="⚙️", url_path="configuracion"))
        if _role == "admin":
            _conf.append(st.Page("pages/usuarios.py", title="Usuarios", icon="👥"))
        _conf.append(st.Page("pages/integraciones.py", title="Integraciones", icon="🔌"))
        _pages["Configuración"] = _conf

    pg = st.navigation(_pages)
    pg.run()
