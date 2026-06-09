"""
MALE'DENIM OS — Integraciones
Estado en vivo de cada API. Test de conexión, última sincronización, errores.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import time
from datetime import datetime
import streamlit as st
import requests

from shared import (
    CSS, DEEP_INK, GRAPHITE_GREY, STEEL_BLUE,
    dash_hero, dash_section, dash_card_start, dash_card_end,
    dash_kpi,
)

st.markdown(CSS, unsafe_allow_html=True)

# ── Guard ──────────────────────────────────────────────────────────────────────
if "logistica" not in st.session_state.get("permisos", ["logistica"]):
    st.error("🔒 Sin acceso.")
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Tests de conexión — cacheados en session_state por 60s
# ─────────────────────────────────────────────────────────────────────────────
_SS_TESTS    = "_int_tests"
_SS_TESTS_TS = "_int_tests_ts"
_TESTS_TTL   = 60  # 1 min


def _secret(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, default) or default)
    except Exception:
        return default


def _test_melonn() -> dict:
    """Ping rápido a Melonn API."""
    t0 = time.time()
    try:
        import melonn_client as mc
        if not mc.credenciales_ok():
            return {"ok": False, "ms": 0, "msg": "Sin API key configurada"}
        resp = mc._get("sell-orders", params={"per_page": 1, "page": 0})
        elapsed = int((time.time() - t0) * 1000)
        if resp is None:
            return {"ok": False, "ms": elapsed, "msg": "Timeout / sin respuesta"}
        meta = resp.get("meta_data") or {}
        return {"ok": True, "ms": elapsed, "msg": f"Respuesta válida · {meta.get('total_count','?')} pedidos activos"}
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "msg": str(e)[:100]}


def _test_supabase() -> dict:
    t0 = time.time()
    try:
        from supabase import create_client
        url = _secret("SUPABASE_URL")
        key = _secret("SUPABASE_KEY")
        if not url or not key:
            return {"ok": False, "ms": 0, "msg": "URL/KEY no configurados"}
        sb = create_client(url, key)
        rows = sb.table("melonn_cache").select("id,fetched_at,total").execute().data
        elapsed = int((time.time() - t0) * 1000)
        return {"ok": True, "ms": elapsed, "msg": f"melonn_cache: {len(rows)} filas accesibles"}
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "msg": str(e)[:100]}


def _test_shopify() -> dict:
    t0 = time.time()
    try:
        store = _secret("SHOPIFY_STORE")
        token = _secret("SHOPIFY_ACCESS_TOKEN")
        ver   = _secret("SHOPIFY_API_VERSION", "2024-01")
        if not store or not token:
            return {"ok": False, "ms": 0, "msg": "STORE/TOKEN no configurados"}
        r = requests.get(
            f"https://{store}/admin/api/{ver}/shop.json",
            headers={"X-Shopify-Access-Token": token},
            timeout=8,
        )
        elapsed = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            shop = r.json().get("shop", {})
            return {"ok": True, "ms": elapsed,
                    "msg": f"{shop.get('name','—')} · {shop.get('domain','—')}"}
        return {"ok": False, "ms": elapsed, "msg": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "msg": str(e)[:100]}


def _test_mercadopago() -> dict:
    t0 = time.time()
    try:
        token = _secret("MP_ACCESS_TOKEN")
        if not token:
            return {"ok": False, "ms": 0, "msg": "MP_ACCESS_TOKEN no configurado"}
        r = requests.get(
            "https://api.mercadopago.com/v1/payments/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 1},
            timeout=8,
        )
        elapsed = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            data = r.json()
            total = data.get("paging", {}).get("total")
            return {"ok": True, "ms": elapsed, "msg": f"{total} pagos disponibles"}
        return {"ok": False, "ms": elapsed, "msg": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "msg": str(e)[:100]}


def _correr_tests(force: bool = False) -> dict:
    """Cachea resultados de tests en session_state por _TESTS_TTL."""
    if not force:
        cached = st.session_state.get(_SS_TESTS)
        ts     = st.session_state.get(_SS_TESTS_TS)
        if cached and ts and (datetime.now() - ts).total_seconds() < _TESTS_TTL:
            return cached
    res = {
        "melonn":      _test_melonn(),
        "supabase":    _test_supabase(),
        "shopify":     _test_shopify(),
        "mercadopago": _test_mercadopago(),
    }
    st.session_state[_SS_TESTS]    = res
    st.session_state[_SS_TESTS_TS] = datetime.now()
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Header + acciones
# ─────────────────────────────────────────────────────────────────────────────
_tools = '<div class="dash-toolbtn">🔄 Probar todas</div>'
dash_hero(
    "Integraciones",
    "Estado de cada conexión externa · prueba en vivo, sin necesidad de salir de la app.",
    tools_html=_tools,
)

# Trigger de re-test manual
_col1, _col2, _col3 = st.columns([1, 1, 4])
with _col1:
    _force = st.button("🔄 Probar conexiones", use_container_width=True, type="primary")

resultados = _correr_tests(force=_force)

# ─────────────────────────────────────────────────────────────────────────────
# KPIs arriba
# ─────────────────────────────────────────────────────────────────────────────
INTEGRACIONES_TODAS = [
    # (id, nombre, categoria, conectada_real)
    ("melonn",       "Melonn",         "Logística",   True),
    ("supabase",     "Supabase",       "Infra",       True),
    ("shopify",      "Shopify",        "Comercial",   True),
    ("mercadopago",  "MercadoPago",    "Pasarela",    True),
    ("wompi",        "Wompi",          "Pasarela",    False),
    ("addi",         "Addi",           "Pasarela",    False),
    ("sumapay",      "Suma Pay",       "Pasarela",    False),
    ("bancolombia",  "Bancolombia",    "Banco",       False),
    ("davivienda",   "Davivienda",     "Banco",       False),
    ("markethub",    "MarketHub",      "Facturación", False),
    ("siigo",        "Siigo",          "Contabilidad",False),
    ("kommo",        "Kommo",          "CRM",         False),
]

n_total       = len(INTEGRACIONES_TODAS)
n_conectadas  = sum(1 for k, _, _, real in INTEGRACIONES_TODAS
                    if real and resultados.get(k, {}).get("ok"))
n_errores     = sum(1 for k, _, _, real in INTEGRACIONES_TODAS
                    if real and not resultados.get(k, {}).get("ok"))
n_pendientes  = sum(1 for _, _, _, real in INTEGRACIONES_TODAS if not real)

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(dash_kpi(
        "INTEGRACIONES TOTALES", str(n_total),
        meta=f"{n_total} servicios mapeados",
    ), unsafe_allow_html=True)
with k2:
    st.markdown(dash_kpi(
        "CONECTADAS", str(n_conectadas),
        meta="Respondiendo correctamente", meta_dir="up" if n_conectadas else "",
    ), unsafe_allow_html=True)
with k3:
    st.markdown(dash_kpi(
        "CON ERRORES", str(n_errores),
        meta="Requieren atención" if n_errores else "Sin errores",
        meta_dir="down" if n_errores else "",
        value_danger=n_errores > 0,
    ), unsafe_allow_html=True)
with k4:
    st.markdown(dash_kpi(
        "PENDIENTES DE CONECTAR", str(n_pendientes),
        meta="Roadmap",
    ), unsafe_allow_html=True)

st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Lista de integraciones
# ─────────────────────────────────────────────────────────────────────────────
dash_section("Estado de conexión",
             f"Última verificación: {st.session_state.get(_SS_TESTS_TS, datetime.now()).strftime('%H:%M:%S')}")


def _render_row(key: str, nombre: str, categoria: str, conectada_real: bool) -> str:
    if not conectada_real:
        status_color = "#9CA0A4"
        status_bg    = "#F2F0EC"
        status_tag   = "Pendiente"
        ms_html      = ""
        msg          = "Integración en roadmap — sin conexión aún"
    else:
        res = resultados.get(key, {})
        if res.get("ok"):
            status_color = "#036A73"
            status_bg    = "#E6F4F2"
            status_tag   = "Conectado"
        else:
            status_color = "#990012"
            status_bg    = "#FDEEF0"
            status_tag   = "Error"
        ms = res.get("ms", 0)
        ms_html = (
            f'<span style="font-size:0.72rem;color:#6B7280;font-weight:500;'
            f'font-variant-numeric:tabular-nums;">{ms}ms</span>'
        ) if ms else ""
        msg = res.get("msg", "—")

    initial = nombre[0].upper()

    return (
        '<div style="display:grid;grid-template-columns:42px 1fr 100px 100px;'
        'align-items:center;gap:14px;padding:14px 16px;'
        'border-bottom:1px solid #F4F2EE;background:white;">'
        # Avatar/inicial
        '<div style="width:36px;height:36px;border-radius:10px;'
        f'background:#213033;color:white;font-size:0.86rem;font-weight:700;'
        f'display:inline-flex;align-items:center;justify-content:center;">{initial}</div>'
        # Nombre + categoría + mensaje
        '<div>'
        f'<div style="font-size:0.88rem;font-weight:600;color:#1A1A1A;'
        f'margin-bottom:2px;">{nombre}</div>'
        f'<div style="font-size:0.72rem;color:#6B7280;line-height:1.35;">'
        f'<span style="color:#9CA0A4;text-transform:uppercase;letter-spacing:1px;'
        f'font-weight:600;font-size:0.62rem;">{categoria}</span>'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;{msg}</div>'
        '</div>'
        # Tiempo de respuesta
        f'<div style="text-align:right;">{ms_html}</div>'
        # Status badge
        '<div style="text-align:right;">'
        f'<span style="background:{status_bg};color:{status_color};'
        'font-size:0.62rem;font-weight:700;letter-spacing:1.2px;'
        'text-transform:uppercase;padding:5px 10px;border-radius:20px;'
        f'border:1px solid {status_color}22;white-space:nowrap;">● {status_tag}</span>'
        '</div>'
        '</div>'
    )


rows = "".join(
    _render_row(k, n, c, real) for k, n, c, real in INTEGRACIONES_TODAS
)

st.markdown(
    dash_card_start() + rows + dash_card_end(),
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Logs / footer info
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
dash_section("Cómo agregar nuevas integraciones")

info_html = (
    '<div style="background:white;border:1px solid #ECECEC;border-radius:14px;'
    'padding:18px 22px;font-size:0.82rem;color:#1A1A1A;line-height:1.6;">'
    '<p style="margin:0 0 10px 0;font-weight:500;">'
    'Las credenciales viven en <b>.streamlit/secrets.toml</b> '
    '(local) o en <b>Streamlit Cloud → App settings → Secrets</b> (producción). '
    'Nunca se commitean al repo.'
    '</p>'
    '<p style="margin:0;color:#6B7280;font-size:0.78rem;">'
    'Las pruebas se cachean en memoria por 60s para no golpear las APIs en cada navegación. '
    'Presiona <b>"Probar conexiones"</b> para forzar nueva verificación.'
    '</p>'
    '</div>'
)
st.markdown(info_html, unsafe_allow_html=True)
