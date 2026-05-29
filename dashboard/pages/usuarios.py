"""
Panel de gestión de usuarios — Solo admin
Permite crear nuevos usuarios y generar el bloque de secrets para Streamlit Cloud.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import bcrypt
from shared import CSS, DEEP_INK, STEEL_BLUE, GRAPHITE_GREY

st.markdown(CSS, unsafe_allow_html=True)

# Guard: solo admin puede acceder
if st.session_state.get("authentication_status") is not True:
    st.error("🔒 Acceso denegado. Inicia sesión primero.")
    st.stop()

# Leer rol desde session_state (lo pone app.py tras el login)
# Fallback a st.secrets si por alguna razón no está en session_state
_role = st.session_state.get("user_role", "")
if not _role:
    try:
        _role = str(
            st.secrets["credentials"]["usernames"]
            [st.session_state.get("username", "")].get("role", "user")
        )
    except Exception:
        _role = "user"

if _role != "admin":
    st.error("🔒 Solo el administrador puede gestionar usuarios.")
    st.stop()

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
    <p class="titulo-panel">👤 USUARIOS</p>
    <p class="subtitulo">Gestión de acceso · MALE'DENIM OS</p>
    <hr style='margin:10px 0 24px;'>
""", unsafe_allow_html=True)

# ── Usuarios actuales ──────────────────────────────────────────────────────────
st.markdown("<div class='sec-title'>Usuarios registrados</div>", unsafe_allow_html=True)

_MODULOS_LABEL = {
    "logistica":    "Logística",
    "comercial":    "Comercial",
    "mercadopago":  "MercadoPago",
    "conciliacion": "Conciliación",
}

try:
    _usuarios = st.secrets["credentials"]["usernames"]
    for _uname, _udata in _usuarios.items():
        _rol_u   = _udata.get("role", "user")
        _badge   = "🔑 Admin" if _rol_u == "admin" else "👤 Usuario"
        _color   = STEEL_BLUE if _rol_u == "admin" else GRAPHITE_GREY
        _perms_u = list(_udata.get("permisos", [])) if _rol_u != "admin" else list(_MODULOS_LABEL.keys())
        _tags    = " · ".join(_MODULOS_LABEL.get(p, p) for p in _perms_u) or "Sin módulos"
        st.markdown(f"""
        <div style="background:white;border-radius:8px;padding:14px 18px;margin-bottom:8px;
                    border:1px solid rgba(33,48,51,0.07);border-left:3px solid {_color};">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                    <div style="font-weight:700;color:{DEEP_INK};font-size:0.9rem;">
                        {_udata.get('name', _uname)}
                    </div>
                    <div style="font-size:0.72rem;color:{GRAPHITE_GREY};margin-top:2px;">
                        @{_uname} · {_udata.get('email', '—')}
                    </div>
                </div>
                <div style="font-size:0.65rem;color:{_color};font-weight:700;
                            letter-spacing:1px;text-transform:uppercase;">
                    {_badge}
                </div>
            </div>
            <div style="margin-top:8px;font-size:0.68rem;color:#505050;">
                <span style="color:#909090;letter-spacing:1px;text-transform:uppercase;
                             font-size:0.58rem;">Módulos · </span>{_tags}
            </div>
        </div>
        """, unsafe_allow_html=True)
except Exception as e:
    st.warning(f"No se pudieron leer los usuarios de Secrets: {e}")

st.markdown("<br>", unsafe_allow_html=True)

# ── Crear nuevo usuario ────────────────────────────────────────────────────────
st.markdown("<div class='sec-title'>Crear nuevo usuario</div>", unsafe_allow_html=True)
st.caption(
    "Completa el formulario → el sistema genera el bloque listo para pegar "
    "en los **Secrets de Streamlit Cloud**."
)

_MODULOS = {
    "logistica":    "📦 Logística",
    "comercial":    "🛍️ Comercial (Shopify)",
    "mercadopago":  "💳 MercadoPago",
    "conciliacion": "📊 Conciliación",
}

with st.form("form_nuevo_usuario", clear_on_submit=False):
    c1, c2 = st.columns(2)
    with c1:
        _new_username = st.text_input("Username (sin espacios)", placeholder="juan.perez")
        _new_name     = st.text_input("Nombre completo",         placeholder="Juan Pérez")
    with c2:
        _new_email    = st.text_input("Email",                   placeholder="juan@maledenim.co")
        _new_role     = st.selectbox("Rol", ["user", "admin"])
    _new_password = st.text_input("Contraseña inicial", type="password",
                                  placeholder="Mínimo 8 caracteres")

    st.markdown(
        "<div style='font-size:0.72rem;font-weight:600;color:#213033;"
        "margin:12px 0 6px;'>Módulos habilitados</div>",
        unsafe_allow_html=True,
    )
    _perm_cols = st.columns(len(_MODULOS))
    _new_permisos = []
    for i, (key, label) in enumerate(_MODULOS.items()):
        with _perm_cols[i]:
            if st.checkbox(label, value=True, key=f"perm_{key}"):
                _new_permisos.append(key)

    _submitted = st.form_submit_button("🔑 Generar credenciales", use_container_width=True)

if _submitted:
    _errs = []
    if not _new_username or " " in _new_username:
        _errs.append("Username inválido (sin espacios)")
    if not _new_name:
        _errs.append("Nombre completo requerido")
    if not _new_password or len(_new_password) < 8:
        _errs.append("Contraseña muy corta (mín. 8 caracteres)")
    if not _new_permisos and _new_role != "admin":
        _errs.append("Selecciona al menos un módulo")

    if _errs:
        for e in _errs:
            st.error(e)
    else:
        _hash = bcrypt.hashpw(_new_password.encode(), bcrypt.gensalt(12)).decode()
        _perms_toml = str(_new_permisos).replace("'", '"')

        _bloque = f"""[credentials.usernames.{_new_username}]
name     = "{_new_name}"
email    = "{_new_email}"
password = "{_hash}"
role     = "{_new_role}"
permisos = {_perms_toml}
"""
        st.success(
            f"✅ Credenciales generadas para **{_new_name}** (@{_new_username})",
            icon="🔑",
        )

        # Mostrar resumen de permisos
        _perm_labels = [_MODULOS[p] for p in _new_permisos if p in _MODULOS]
        st.markdown(
            f"**Módulos asignados:** {' · '.join(_perm_labels) if _perm_labels else '—'}"
        )

        st.markdown("#### Pega este bloque en Streamlit Cloud → App settings → Secrets")
        st.code(_bloque, language="toml")
        st.info(
            "1. Abre **Streamlit Cloud** → tu app → ⋮ **Manage app** → **Secrets**\n"
            "2. Copia el bloque de arriba y agrégalo al final del archivo\n"
            "3. Guarda — la app se reinicia automáticamente\n"
            "4. Comparte el **username** y la **contraseña inicial** con el usuario por un canal seguro",
            icon="📋",
        )

st.markdown("<br>", unsafe_allow_html=True)

# ── Cambiar mi contraseña ──────────────────────────────────────────────────────
st.markdown("<div class='sec-title'>Cambiar mi contraseña</div>", unsafe_allow_html=True)

with st.form("form_cambiar_pass", clear_on_submit=True):
    _curr_pass  = st.text_input("Contraseña actual",   type="password")
    _new_pass1  = st.text_input("Nueva contraseña",    type="password")
    _new_pass2  = st.text_input("Confirmar contraseña", type="password")
    _btn_change = st.form_submit_button("Actualizar contraseña", use_container_width=True)

if _btn_change:
    _my_uname = st.session_state.get("username", "")
    try:
        _stored_hash = st.secrets["credentials"]["usernames"][_my_uname]["password"]
    except Exception:
        _stored_hash = None

    if not _stored_hash or not bcrypt.checkpw(_curr_pass.encode(), _stored_hash.encode()):
        st.error("La contraseña actual no es correcta.")
    elif len(_new_pass1) < 8:
        st.error("La nueva contraseña debe tener al menos 8 caracteres.")
    elif _new_pass1 != _new_pass2:
        st.error("Las contraseñas nuevas no coinciden.")
    else:
        _new_hash = bcrypt.hashpw(_new_pass1.encode(), bcrypt.gensalt(12)).decode()
        st.success("✅ Nueva contraseña generada.", icon="🔑")
        st.markdown("#### Actualiza tu hash en Streamlit Secrets:")
        st.code(
            f'[credentials.usernames.{_my_uname}]\npassword = "{_new_hash}"',
            language="toml",
        )
        st.info(
            "Copia el nuevo hash y reemplázalo en **Streamlit Cloud → Secrets**.",
            icon="📋",
        )
