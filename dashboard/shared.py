"""
Módulo compartido: colores, estilos, carga de datos y helpers.
Importado por cada página del dashboard.
v2 — render_sidebar retorna (activo, filtro_nivel, filtro_zona)
"""

import sys
from pathlib import Path
import streamlit as st
import pandas as pd
from datetime import date, datetime
import streamlit.components.v1 as components

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))                    # dashboard/ → design_system, components
sys.path.insert(0, str(_HERE.parent / "src"))     # src/ → melonn_client, riesgo, etc.

from ingest import leer_csv_melonn
from riesgo import calcular_riesgo
try:
    import melonn_client
    _MELONN_API_DISPONIBLE = True
except Exception:
    _MELONN_API_DISPONIBLE = False

# ── Design system ─────────────────────────────────────────────────────────────
from design_system import (
    CSS,
    DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE,
    COLOR_CRITICO as CRITICO_COLOR,
    COLOR_RIESGO  as RIESGO_COLOR,
    COLOR_NORMAL  as NORMAL_COLOR,
    COLOR_PENDIENTE,
    TEAL, NAVY, RUST, CRIMSON, BURGUNDY,
    SURFACE_CARD, BORDER_DEFAULT, SURFACE_BG,
)
# Aliases de compatibilidad para módulos existentes
CRITICO_COLOR   = "#990012"
RIESGO_COLOR    = "#b95902"
NORMAL_COLOR    = "#036a73"
COD_COLOR       = "#59204d"
VENCIDO_COLOR   = "#606060"
RESUELTO_COLOR  = "#2d6a4f"   # verde oscuro — novedad solucionada

MAX_DIAS_ACTIVO = 20  # días máx. en tránsito; pasado esto → VENCIDO (posiblemente entregado sin actualizar)

ZONAS_ES = {
    "MEDELLIN":       "Medellín / Área Metro",
    "BOGOTA_RAPIDAS": "Bogotá / Zonas Rápidas",
    "PRINCIPALES":    "Ciudades Principales",
    "SECUNDARIAS":    "Municipios / Pueblos",
    "REEXPEDIDO":     "Reexpedido",
}
ESTADOS_ES = {
    # ── Novedades (códigos 1, 2) ─────────────────────────────────────────────
    "Received - valid":                              "Recibida · válida",
    "Recibida - valida":                             "Recibida · válida",
    "All items reserved - ready for fulfillment":    "Reservada · lista alistamiento",
    "Recibida - valida - lista para alistamiento":   "Reservada · lista alistamiento",
    # ── Pendiente despacho (código 26) ──────────────────────────────────────
    "All items reserved - fulfillment on hold":      "Alistamiento en espera · Seller",
    "Alistamiento en espera - Seller":               "Alistamiento en espera · Seller",
    "Packed - on hold":                              "Alistamiento en espera · Seller",
    # ── En tránsito (códigos 5, 6, 7, 24, 28) ──────────────────────────────
    "Packed":                                        "Empacada · lista para despacho",
    "Empacada":                                      "Empacada · lista para despacho",
    "Prepared for dispatch":                         "Preparada para despacho",
    "Preparada para despacho":                       "Preparada para despacho",
    "Shipped - in transit":                          "En tránsito",
    "Despachada - en tránsito":                      "En tránsito",
    "En tránsito":                                   "En tránsito",
    "Ready For Packing":                             "Lista para empaque · bodega",
    "Lista para empaque":                            "Lista para empaque · bodega",
    "Picked-up by buyer":                            "Recogida · finalizada",
    "Recogida por el comprador":                     "Recogida · finalizada",
    # ── Novedades ────────────────────────────────────────────────────────────
    "Error - not able to process":                   "Error · no procesa",
    "Error - no es posible procesar":                "Error · no procesa",
    "on stand by - not able to fulfil - no stock":   "Sin stock",
    "En espera - sin stock":                         "Sin stock",
    "Delivery not posible":                          "Entrega no posible",
    "Entrega no posible":                            "Entrega no posible",
    "on stand by - not able to fulfil - expired promises": "Promesa vencida",
    "En espera - promesas vencidas":                 "Promesa vencida",
    "All items reserved - fulfillment on hold - ext. conditionals": "En espera · ext.",
    "All items reserved - fulfillment on hold - int. conditionals": "En espera · int.",
    "on stand by - not able to fulfil - SM restriction": "Restricción método envío",
    "Restricción método de envío":                   "Restricción método envío",
}

DEFAULT_CSV = str(Path(__file__).parent.parent / "data" / "logistica" / "raw" / "melonn_2026-05-12.csv")


# ── Sesión / usuario activo ───────────────────────────────────────────────────
def usuario_activo() -> str:
    """
    Retorna el nombre del usuario logueado para registrarlo en acciones/notas.
    Fallback a username si no hay nombre, o 'dashboard' si no hay sesión.
    """
    try:
        nombre = st.session_state.get("name") or st.session_state.get("username") or ""
        return nombre.strip() or "dashboard"
    except Exception:
        return "dashboard"


# ── Carga y procesamiento ─────────────────────────────────────────────────────
def _dias_reales(p: dict) -> int:
    """
    Calcula días en tránsito dinámicamente desde fecha_despacho → hoy.
    Fallback al valor almacenado si no hay fecha.
    """
    fd = p.get("fecha_despacho")
    if fd:
        try:
            return max(0, (date.today() - date.fromisoformat(str(fd))).days)
        except Exception:
            pass
    return int(p.get("dias_en_transito") or 0)


def _promesa_vencida(p: dict, sla_critico: int) -> str:
    """
    Retorna 'SÍ' si la fecha de promesa ya venció, '—' si no.
    Orden de prioridad para la fecha de promesa:
      1. fecha_promesa del pedido (viene de Melonn CSV o bootstrap)
      2. fecha_despacho + sla_critico (estimado por zona) — solo para tránsito
    """
    from datetime import timedelta
    fp = p.get("fecha_promesa")
    if not fp:
        # Estimar promesa a partir de fecha_despacho + SLA de zona
        fd = p.get("fecha_despacho")
        if fd:
            try:
                fd_obj  = date.fromisoformat(str(fd))
                fp      = str(fd_obj + timedelta(days=sla_critico))
                # Guardar la promesa estimada en el pedido para que se muestre
                p["fecha_promesa"] = fp
            except Exception:
                return "—"
        else:
            return "—"
    try:
        return "SÍ" if date.today() > date.fromisoformat(str(fp)) else "—"
    except Exception:
        return "—"


def _procesar_df(pedidos: list) -> pd.DataFrame:
    """
    Convierte la lista de pedidos en DataFrame con clasificación de riesgo.

    Columnas clave añadidas:
      Sub_Estado  → pendiente_despacho | en_transito | novedad | otro
      Tipo_Recaudo → Contraentrega | Prepago
      Nivel        → CRITICO | RIESGO | NORMAL | VENCIDO

    VENCIDO aplica solo a pedidos en tránsito (COD o Prepago) que superan
    MAX_DIAS_ACTIVO sin confirmación de entrega — nunca a pendientes de despacho.
    """
    rows = []
    for p in pedidos:
        dias_real = _dias_reales(p)
        sub       = p.get("sub_estado_logistico", "en_transito")
        es_cod    = p["es_contraentrega"]

        # Calculamos riesgo en todos los casos para obtener zona_info y SLA
        r = calcular_riesgo(
            ciudad=p["ciudad_destino"],
            dias_en_transito=dias_real,
            incidencia_raw=p.get("incidencia", "NINGUNO"),
            es_contraentrega=es_cod,
        )

        # ENTREGADO: pedido cobrado/entregado — no aplica riesgo
        es_entregado = (sub == "entregado")

        # RESUELTO: novedad solucionada — no aplica riesgo ni VENCIDO
        es_resuelto = (sub == "resuelto")

        # VENCIDO: solo en_transito/novedad con >MAX_DIAS_ACTIVO sin confirmar
        es_vencido = (
            not es_resuelto
            and not es_entregado
            and dias_real > MAX_DIAS_ACTIVO
            and sub in ("en_transito", "novedad")
        )

        if es_entregado:
            nivel     = "NORMAL"
            prioridad = 20
            score     = 100
            motivo    = "Pedido entregado · COD cobrado"
            categoria = "OK"
        elif es_resuelto:
            nivel     = "RESUELTO"
            prioridad = 10
            score     = 100
            motivo    = "Novedad solucionada · pedido recogido"
            categoria = "OK"
        elif es_vencido:
            nivel     = "VENCIDO"
            prioridad = 6
            score     = 0
            motivo    = f"Sin confirmación · {dias_real}d en tránsito"
            categoria = "OK"
        else:
            nivel     = r.nivel
            prioridad = r.prioridad
            score     = r.score
            motivo    = r.motivos[0] if r.motivos else "—"
            categoria = r.incidencia_info.categoria

        # Calcular promesa ANTES del append — no aplica a entregados/resueltos
        _prom_vencida = (
            _promesa_vencida(p, r.zona_info.sla_critico)
            if not es_resuelto and not es_entregado else "—"
        )

        rows.append({
            "Prioridad":       prioridad,
            "Nivel":           nivel,
            "Score":           score,
            "Sub_Estado":      sub,
            "Tipo_Recaudo":    "Contraentrega" if es_cod else "Prepago",
            "Orden":           p.get("orden_tienda") or p.get("orden_melonn", ""),
            "Orden Melonn":    p.get("orden_melonn", ""),
            "Cliente":         p.get("nombre_comprador", ""),
            "Teléfono":        p.get("telefono_comprador", ""),
            "Ciudad":          p.get("ciudad_destino", ""),
            "Zona":            ZONAS_ES.get(r.zona_info.zona, r.zona_info.zona),
            "Días":            dias_real,
            "SLA Crítico":     r.zona_info.sla_critico,
            "Días sobre SLA":  max(0, dias_real - r.zona_info.sla_critico + 1),
            "Valor COD":       p.get("valor_cod_raw", ""),
            "Método Envío":    p.get("transportadora", ""),
            "Estado":          ESTADOS_ES.get(p.get("estado_melonn",""), p.get("estado_melonn","")),
            "Estado_Code":     int(p.get("estado_melonn_code") or 0),
            "Novedad":         p.get("incidencia", "NINGUNO"),
            "Categoría":       categoria,
            "F. Promesa":      str(p.get("fecha_promesa") or ""),
            "Promesa vencida": _prom_vencida,
            "F. Despacho":     str(p.get("fecha_despacho") or ""),
            "F. Creación":     str(p.get("fecha_creacion") or ""),
            "Motivo riesgo":   motivo,
            "Link Melonn":     p.get("link_guia", ""),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["Prioridad","Días sobre SLA"], ascending=[True,False]).reset_index(drop=True)

@st.cache_data(show_spinner=False)
def cargar_datos(ruta: str, ts: str):
    """Carga desde CSV (fallback cuando no hay API)."""
    pedidos, omitidos = leer_csv_melonn(ruta, solo_activos=True)
    df = _procesar_df(pedidos)
    return df, omitidos

_SS_DATOS = "_api_datos"   # (df, omitidos, meta) en session_state
_SS_TS    = "_api_datos_ts" # datetime del último fetch
_SS_TTL   = 1800            # 30 min en memoria — coincide con TTL de Supabase

def cargar_datos_api(forzar_refresh: bool = False):
    """
    Carga pedidos desde Melonn con caché en session_state.

    Flujo:
      1. Si hay datos en session_state con < 5 min → retorna instantáneo (sin Supabase)
      2. Si forzar_refresh o caché vencido → fetch desde Supabase/API → guarda en session_state

    Esto elimina la llamada a Supabase en cada re-render de Streamlit
    (cada click, selección de tabla, cambio de tab).
    """
    if not _MELONN_API_DISPONIBLE:
        return pd.DataFrame(), {}, {"fuente": "no_api"}

    _refresh = forzar_refresh or st.session_state.pop("_melonn_refresh", False)

    # ── Caché en memoria (session_state) ─────────────────────────────────────
    if not _refresh:
        _cached = st.session_state.get(_SS_DATOS)
        _ts     = st.session_state.get(_SS_TS)
        if _cached is not None and _ts is not None:
            if (datetime.now() - _ts).total_seconds() < _SS_TTL:
                return _cached   # ← instantáneo, cero red

    # ── Fetch desde Supabase o API ────────────────────────────────────────────
    resultado = melonn_client.obtener_pedidos_activos(forzar_refresh=_refresh)
    if len(resultado) == 3:
        pedidos, omitidos, meta = resultado
    else:
        pedidos, omitidos = resultado
        meta = {}

    if meta.get("refresh_bloqueado"):
        st.session_state["_refresh_bloqueado"] = True

    if not pedidos:
        result = (pd.DataFrame(), omitidos, meta)
    else:
        df = _procesar_df(pedidos)
        result = (df, omitidos, meta)

    # Guardar en session_state para las próximas interacciones
    st.session_state[_SS_DATOS] = result
    st.session_state[_SS_TS]    = datetime.now()
    return result

def api_melonn_activa() -> bool:
    """True si el API key está configurado y el módulo disponible."""
    return _MELONN_API_DISPONIBLE and melonn_client.credenciales_ok()

def color_nivel(val):
    return {
        "CRITICO": f"background-color:{CRITICO_COLOR}22;color:{CRITICO_COLOR};font-weight:700",
        "RIESGO":  f"background-color:{RIESGO_COLOR}22;color:{RIESGO_COLOR};font-weight:600",
        "NORMAL":  f"background-color:{NORMAL_COLOR}22;color:{NORMAL_COLOR}",
        "VENCIDO": f"background-color:{VENCIDO_COLOR}18;color:{VENCIDO_COLOR};font-style:italic",
    }.get(val, "")

def _parse_cod(v: str) -> float:
    try:
        s = str(v).strip()
        if not s or s in ("-","No aplica","nan"): return 0.0
        if "," in s: s = s.replace(".","").replace(",",".")
        else: s = s.replace(",","")
        return float(s)
    except Exception:
        return 0.0

# ── Sidebar compartido ────────────────────────────────────────────────────────
def render_sidebar(page_label: str):
    """
    Sidebar del módulo logístico.
    Siempre usa la API / caché — sin carga manual de CSV.
    Retorna (activo: bool, filtro_nivel: list, filtro_zona: list)
    """
    with st.sidebar:
        st.markdown(f"""
            <div style="padding:8px 0 14px 0;">
                <div class="logo-sidebar">MALE'DENIM</div>
                <div class="logo-tagline">THAT FITS</div>
            </div>
        """, unsafe_allow_html=True)
        st.markdown(
            f"<div style='font-size:0.68rem;letter-spacing:2px;color:{STEEL_BLUE};"
            f"text-transform:uppercase;margin-bottom:10px;'>{page_label}</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # ── Estado del caché ───────────────────────────────────────────────────
        _api_ok = _MELONN_API_DISPONIBLE and melonn_client.credenciales_ok()
        if _api_ok:
            try:
                _info = melonn_client.cache_info()
            except Exception:
                _info = None

            if _info:
                _age_s = int(_info["age_s"])
                if _age_s < 60:
                    _age_txt = "ahora mismo"
                elif _age_s < 3600:
                    _age_txt = f"hace {_age_s // 60}min"
                else:
                    _age_txt = f"hace {_age_s // 3600}h"

                _fuente_info = _info.get("fuente", "api_live")
                if _fuente_info == "csv_upload":
                    _color = "#4a86e8"
                    _icon  = "📄"
                    _tag   = "CSV CARGADO"
                    _sub   = f"{_info['total']} pedidos · {_age_txt}"
                elif _fuente_info == "csv_bootstrap":
                    _color = "#f5a623"
                    _icon  = "⚠"
                    _tag   = "DATOS BOOTSTRAP"
                    _sub   = f"{_info['total']} pedidos genéricos · carga un CSV real"
                elif _info.get("stale") or _fuente_info == "stale":
                    _color, _icon, _tag = "#f5a623", "⚠", "CACHÉ DESACTUALIZADO"
                    _sub = f"{_info['total']} pedidos · {_age_txt}"
                else:
                    _color, _icon, _tag = "#52b788", "✓", "MELONN SINCRONIZADO"
                    _sub = f"{_info['total']} pedidos · {_age_txt}"
            else:
                _color, _icon, _tag = "#f5a623", "↻", "SIN DATOS AÚN"
                _sub = "Presiona actualizar"

            st.markdown(f"""
            <div style="background:#1a3a2a;border:1px solid #2d6a4f;border-radius:6px;
                        padding:10px 12px;margin-bottom:8px;">
                <div style="font-size:0.62rem;color:{_color};letter-spacing:1px;font-weight:700;">
                    {_icon} {_tag}
                </div>
                <div style="font-size:0.65rem;color:{_color};margin-top:3px;">{_sub}</div>
            </div>
            """, unsafe_allow_html=True)

            # Aviso si el último refresh fue bloqueado por cooldown
            if st.session_state.pop("_refresh_bloqueado", False):
                st.warning("⏳ Sincronizado hace menos de 5 min — usando caché actual.", icon="ℹ️")

            if st.button("↻ Actualizar datos", key="btn_refresh_melonn", use_container_width=True):
                st.session_state["_melonn_refresh"] = True
                st.rerun()
        else:
            st.markdown(f"""
            <div style="background:rgba(153,0,18,0.15);border:1px solid #990012;border-radius:6px;
                        padding:10px 12px;margin-bottom:8px;">
                <div style="font-size:0.62rem;color:#ff6b6b;letter-spacing:1px;font-weight:700;">
                    ✗ API NO CONFIGURADA
                </div>
                <div style="font-size:0.62rem;color:#ff6b6b;margin-top:3px;">
                    Agrega MELONN_API_KEY en Secrets
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.divider()
        st.markdown(
            f"<div style='font-size:0.68rem;letter-spacing:2px;color:{STEEL_BLUE};"
            f"text-transform:uppercase;margin-bottom:6px;'>Filtros</div>",
            unsafe_allow_html=True,
        )
        filtro_nivel = st.multiselect("Nivel de riesgo", ["CRITICO", "RIESGO", "NORMAL", "VENCIDO"], default=[])
        filtro_zona  = st.multiselect("Zona logística", list(ZONAS_ES.values()), default=[])

        st.divider()
        st.markdown(
            f"<div style='font-size:0.68rem;color:{STEEL_BLUE};'>"
            f"{date.today().strftime('%d / %m / %Y')}</div>",
            unsafe_allow_html=True,
        )

    activo = _MELONN_API_DISPONIBLE and melonn_client.credenciales_ok()
    return activo, filtro_nivel, filtro_zona

# ── Detalle de pedido + guía ──────────────────────────────────────────────────
def render_detalle(df_tab: pd.DataFrame, tab_key: str):
    """Card de detalle + auto-apertura de guía Melonn."""
    if df_tab.empty:
        return

    st.markdown(f"<div class='sec-title'>Detalle de pedido y guía transportadora</div>", unsafe_allow_html=True)

    nivel_icono = {"CRITICO":"🔴","RIESGO":"🟠","NORMAL":"🟢"}
    etiquetas = {
        row["Orden"]: f"{nivel_icono.get(row['Nivel'],'·')} {row['Orden']}  ·  {row['Cliente'][:22]}  ·  {row['Ciudad']}  ·  {int(row['Días'])}d"
        for _, row in df_tab.iterrows()
    }
    opciones = list(etiquetas.keys())

    idx_default = 0
    tabla_key = f"tabla_{tab_key}"
    if (tabla_key in st.session_state
            and st.session_state[tabla_key].get("selection",{}).get("rows")):
        fi = st.session_state[tabla_key]["selection"]["rows"][0]
        if fi < len(df_tab):
            o = df_tab.iloc[fi]["Orden"]
            if o in opciones:
                idx_default = opciones.index(o)

    orden_sel = st.selectbox(
        "Buscar pedido (número de orden, cliente o ciudad)",
        opciones,
        index=idx_default,
        format_func=lambda o: etiquetas[o],
        key=f"sel_{tab_key}",
    )
    fila = df_tab[df_tab["Orden"] == orden_sel].iloc[0]
    nc   = {"CRITICO":CRITICO_COLOR,"RIESGO":RIESGO_COLOR,"NORMAL":NORMAL_COLOR}.get(fila["Nivel"], GRAPHITE_GREY)
    link = fila.get("Link Melonn","") or ""

    _badge_bg  = f"{nc}18"
    _badge_txt = nc
    st.markdown(f"""
    <div style="background:white;border-radius:10px;border:1px solid rgba(33,48,51,0.07);
                border-left:4px solid {nc};padding:20px 24px;margin-top:10px;
                box-shadow:0 2px 12px rgba(0,0,0,0.06);">
      <!-- fila 1: cliente / nivel / orden -->
      <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:16px;align-items:flex-start;">
        <div>
          <div style="font-size:0.58rem;letter-spacing:2.5px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Cliente</div>
          <div style="font-size:1.05rem;font-weight:700;color:{DEEP_INK};line-height:1.2;">{fila['Cliente']}</div>
          <div style="font-size:0.78rem;color:#909090;margin-top:2px;">{fila['Teléfono']}</div>
        </div>
        <div style="text-align:center;">
          <div style="font-size:0.58rem;letter-spacing:2.5px;color:#909090;text-transform:uppercase;margin-bottom:6px;">Nivel riesgo</div>
          <div style="display:inline-block;background:{_badge_bg};color:{_badge_txt};
                      font-size:0.7rem;font-weight:700;letter-spacing:2px;
                      text-transform:uppercase;padding:5px 12px;border-radius:20px;">
            {fila['Nivel']}
          </div>
          <div style="font-size:0.8rem;color:#909090;margin-top:5px;font-weight:500;">{int(fila['Score'])}/100</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.58rem;letter-spacing:2.5px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Orden</div>
          <div style="font-size:0.95rem;font-weight:700;color:{DEEP_INK};">{fila['Orden']}</div>
          <div style="font-size:0.78rem;color:#909090;margin-top:2px;">{fila.get('Método Envío', fila.get('Transportadora',''))}</div>
        </div>
      </div>
      <!-- separador -->
      <div style="height:1px;background:rgba(33,48,51,0.07);margin:14px 0;"></div>
      <!-- fila 2: datos operativos -->
      <div style="display:flex;gap:32px;flex-wrap:wrap;">
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Ciudad · Zona</div>
          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{fila['Ciudad']}</div>
          <div style="font-size:0.73rem;color:#909090;">{fila['Zona']}</div>
        </div>
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Tránsito · SLA</div>
          <div style="font-weight:700;color:{nc};font-size:0.85rem;">{int(fila['Días'])} días</div>
          <div style="font-size:0.73rem;color:#909090;">SLA crítico: {int(fila['SLA Crítico'])}d</div>
        </div>
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Despacho · Promesa</div>
          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{fila.get('F. Despacho','') or '—'}</div>
          <div style="font-size:0.73rem;color:{'#c0392b' if fila.get('Promesa vencida') == 'SÍ' else '#909090'};">
            {'⚠ ' if fila.get('Promesa vencida') == 'SÍ' else ''}{fila.get('F. Promesa','') or '—'}
          </div>
        </div>
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Modalidad pago</div>
          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{fila.get('Tipo_Recaudo', fila.get('COD','—'))}</div>
          <div style="font-size:0.73rem;color:#909090;">{fila['Valor COD']}</div>
        </div>
        <div>
          <div style="font-size:0.58rem;letter-spacing:2px;color:#909090;text-transform:uppercase;margin-bottom:3px;">Novedad</div>
          <div style="font-weight:600;color:{DEEP_INK};font-size:0.85rem;">{fila['Novedad']}</div>
          <div style="font-size:0.73rem;color:#909090;">{fila['Categoría']}</div>
        </div>
      </div>
      <!-- motivo riesgo -->
      <div style="margin-top:12px;padding:10px 14px;background:#f8f7f4;border-radius:6px;
                  border-left:3px solid {nc}22;">
        <span style="font-size:0.58rem;color:#909090;letter-spacing:2px;text-transform:uppercase;">Motivo · </span>
        <span style="font-size:0.8rem;font-weight:600;color:{DEEP_INK};">{fila['Motivo riesgo']}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"<div class='sec-title' style='margin-top:14px;'>Seguimiento Melonn — {fila.get('Método Envío', fila.get('Transportadora',''))}</div>", unsafe_allow_html=True)

    if link:
        components.html(f"""
        <!DOCTYPE html><html><head>
        <style>
          *{{margin:0;padding:0;box-sizing:border-box;font-family:Arial,sans-serif;}}
          body{{background:transparent;}}
          .wrap{{display:flex;align-items:center;gap:14px;padding:2px 0;}}
          .btn{{background:{DEEP_INK};color:{SOFT_CONCRETE};padding:8px 16px;font-size:0.68rem;
                letter-spacing:2px;text-transform:uppercase;text-decoration:none;
                border-radius:2px;font-weight:700;white-space:nowrap;}}
          .btn:hover{{background:{STEEL_BLUE};color:{DEEP_INK};}}
          .tag{{font-size:0.68rem;color:{STEEL_BLUE};letter-spacing:1px;}}
          .sub{{font-size:0.68rem;letter-spacing:1px;color:{GRAPHITE_GREY};}}
        </style></head><body>
        <div class="wrap">
          <a class="btn" href="{link}" target="_blank">→ ABRIR TRACKING</a>
          <div>
            <div class="tag">{fila['Orden']} · {fila.get('Método Envío', fila.get('Transportadora',''))}</div>
            <div class="sub">Haz clic en el botón para abrir la guía</div>
          </div>
        </div>
        </body></html>
        """, height=48)
    else:
        st.warning("Sin link de seguimiento para este pedido.")


# ── Helper de gráficos — compatible con todas las versiones de Altair ─────────
def simple_bar(serie: pd.Series, color: str = "#87a6b8", height: int = 200) -> None:
    """Bar chart de una serie simple usando plotly (compatible Python 3.14)."""
    import plotly.express as px
    df_p = serie.reset_index()
    df_p.columns = ["x", "y"]
    fig = px.bar(df_p, x="x", y="y", color_discrete_sequence=[color], height=height)
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
        xaxis_title="", yaxis_title="",
        font=dict(color=GRAPHITE_GREY, size=11),
    )
    fig.update_xaxes(tickangle=-20, tickfont=dict(color=GRAPHITE_GREY))
    fig.update_yaxes(tickfont=dict(color=GRAPHITE_GREY))
    st.plotly_chart(fig, use_container_width=True)


def render_tabla(df: pd.DataFrame, cols: list, key: str, height: int = 440):
    """
    Renderiza la tabla de pedidos con selección de fila y colores de nivel.
    Separa styling de on_select para compatibilidad con Streamlit Cloud.
    Retorna el índice de fila seleccionada (o None).
    """
    NIVEL_COLORES = {"CRITICO": CRITICO_COLOR, "RIESGO": RIESGO_COLOR, "NORMAL": NORMAL_COLOR}

    # Columnas numéricas que formateamos
    fmt = {}
    for c in ["Score", "Días", "Días sobre SLA"]:
        if c in cols:
            fmt[c] = "{:.0f}"

    # Styler solo para colorear — sin on_select
    styled = df[cols].style
    if "Nivel" in cols:
        styled = styled.map(color_nivel, subset=["Nivel"])
    if fmt:
        styled = styled.format(fmt)

    # Tabla con selección (sin Styler — incompatible con on_select en Cloud)
    event = st.dataframe(
        df[cols],
        use_container_width=True,
        height=height,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=key,
        column_config={
            "Nivel": st.column_config.Column("Nivel", help="🔴 Crítico  🟠 Riesgo  🟢 Normal"),
            "Score": st.column_config.NumberColumn("Score", format="%d"),
            "Días":  st.column_config.NumberColumn("Días", format="%d"),
            "Días sobre SLA": st.column_config.NumberColumn("Días s/SLA", format="%d"),
            "Link Melonn": st.column_config.LinkColumn("Link", display_text="Ver"),
        } if any(c in cols for c in ["Nivel","Score","Días","Link Melonn"]) else None,
    )

    sel_rows = event.selection.rows if hasattr(event, "selection") else []
    return sel_rows[0] if sel_rows else None


def bar_chart_zona_nivel(df: pd.DataFrame, height: int = 220) -> None:
    """
    Bar chart apilado por Zona × Nivel con colores de marca.
    Usa plotly (compatible con Python 3.14, sin el bug de altair TypedDict).
    """
    import plotly.express as px

    data = (
        df.groupby(["Zona", "Nivel"])
        .size()
        .reset_index(name="Pedidos")
    )
    if data.empty:
        st.info("Sin datos para graficar.")
        return

    orden_nivel = ["CRITICO", "RIESGO", "NORMAL"]
    color_map   = {
        "CRITICO": CRITICO_COLOR,
        "RIESGO":  RIESGO_COLOR,
        "NORMAL":  NORMAL_COLOR,
    }
    data["Nivel"] = pd.Categorical(data["Nivel"], categories=orden_nivel, ordered=True)
    data = data.sort_values(["Zona", "Nivel"])

    fig = px.bar(
        data,
        x="Zona", y="Pedidos", color="Nivel",
        color_discrete_map=color_map,
        barmode="stack",
        height=height,
        labels={"Pedidos": "Pedidos", "Zona": ""},
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", y=1.05, x=0,
                    font=dict(color=GRAPHITE_GREY)),
        font=dict(size=11, color=GRAPHITE_GREY),
    )
    fig.update_xaxes(tickangle=-20, tickfont=dict(color=GRAPHITE_GREY))
    fig.update_yaxes(tickfont=dict(color=GRAPHITE_GREY))
    st.plotly_chart(fig, use_container_width=True)
