"""
Módulo compartido: colores, estilos, carga de datos y helpers.
Importado por cada página del dashboard.
"""

import sys
from pathlib import Path
import streamlit as st
import pandas as pd
from datetime import date, datetime
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from ingest import leer_csv_melonn
from riesgo import calcular_riesgo

# ── Paleta de marca MALE'DENIM ────────────────────────────────────────────────
DEEP_INK      = "#213033"
STEEL_BLUE    = "#87a6b8"
GRAPHITE_GREY = "#606060"
SOFT_CONCRETE = "#e1e1df"
CRITICO_COLOR = "#990012"
RIESGO_COLOR  = "#b95902"
NORMAL_COLOR  = "#036a73"
COD_COLOR     = "#59204d"

ZONAS_ES = {
    "MEDELLIN":       "Medellín / Área Metro",
    "BOGOTA_RAPIDAS": "Bogotá / Zonas Rápidas",
    "PRINCIPALES":    "Ciudades Principales",
    "SECUNDARIAS":    "Municipios / Pueblos",
    "REEXPEDIDO":     "Reexpedido",
}
ESTADOS_ES = {
    "Shipped - in transit":     "En tránsito",
    "Delivery not posible":     "Entrega no posible",
    "Packed":                   "Empacado",
    "Packed - on hold":         "Empacado - retenido",
    "Prepared for dispatch":    "Listo para despacho",
    "Delivered to buyer":       "Entregado",
    "Picked-up by buyer":       "Recogido",
    "Canceled":                 "Cancelado",
    "All items reserved - ready for fulfillment": "Reservado - listo",
    "All items reserved - fulfillment on hold - ext. conditionals": "Reservado - en espera",
    "on stand by - not able to fulfil - no stock": "Sin stock",
}

DEFAULT_CSV = str(Path(__file__).parent.parent / "data" / "raw" / "melonn_2026-05-12.csv")

# ── CSS global ────────────────────────────────────────────────────────────────
CSS = f"""
<style>
  .stApp {{ background-color: {SOFT_CONCRETE}; }}
  [data-testid="stSidebar"] {{ background-color: {DEEP_INK} !important; }}
  [data-testid="stSidebar"] * {{ color: {SOFT_CONCRETE} !important; }}
  [data-testid="stSidebar"] hr {{ border-color: {STEEL_BLUE}44 !important; }}
  .logo-sidebar {{ font-family:'Arial Black',sans-serif; font-size:1.3rem;
                   font-weight:900; color:white !important; line-height:1; }}
  .logo-tagline  {{ font-size:0.62rem; letter-spacing:4px; color:{STEEL_BLUE} !important; }}
  .kpi-card  {{ border-radius:4px; padding:16px 18px; margin-bottom:4px; }}
  .kpi-crit  {{ background:{CRITICO_COLOR}; border-left:4px solid #ff0022; }}
  .kpi-ries  {{ background:{RIESGO_COLOR};  border-left:4px solid #f5a623; }}
  .kpi-norm  {{ background:{NORMAL_COLOR};  border-left:4px solid {STEEL_BLUE}; }}
  .kpi-extra {{ background:{COD_COLOR};     border-left:4px solid {STEEL_BLUE}; }}
  .kpi-num   {{ font-size:2rem; font-weight:900; color:white; margin:0;
                line-height:1; font-family:'Arial Black',sans-serif; }}
  .kpi-label {{ font-size:0.68rem; color:rgba(255,255,255,0.8); margin:3px 0 0;
                letter-spacing:2px; text-transform:uppercase; }}
  .kpi-sub   {{ font-size:0.62rem; color:rgba(255,255,255,0.5); margin:2px 0 0; }}
  .sec-title {{ font-size:0.68rem; font-weight:700; letter-spacing:3px;
                text-transform:uppercase; color:{GRAPHITE_GREY};
                margin:18px 0 6px; padding-bottom:3px;
                border-bottom:1px solid {STEEL_BLUE}44; }}
  .titulo-panel {{ font-family:'Arial Black',sans-serif; font-size:1.5rem;
                   font-weight:900; color:{DEEP_INK}; letter-spacing:-0.5px; margin:0; }}
  .subtitulo    {{ font-size:0.72rem; color:{GRAPHITE_GREY}; letter-spacing:2px;
                   text-transform:uppercase; margin-top:2px; }}
  h1,h2,h3,h4,h5 {{ color:{DEEP_INK} !important; }}
  hr {{ border-color:{STEEL_BLUE}33 !important; }}
  .stDownloadButton button {{
    background:{DEEP_INK} !important; color:{SOFT_CONCRETE} !important;
    border:none !important; border-radius:2px !important;
    letter-spacing:1.5px; font-size:0.72rem; text-transform:uppercase;
  }}
  .stDownloadButton button:hover {{ background:{STEEL_BLUE} !important; color:{DEEP_INK} !important; }}
</style>
"""

# ── Carga y procesamiento ─────────────────────────────────────────────────────
def _procesar_df(pedidos: list) -> pd.DataFrame:
    rows = []
    for p in pedidos:
        r = calcular_riesgo(
            ciudad=p["ciudad_destino"],
            dias_en_transito=p["dias_en_transito"],
            incidencia_raw=p.get("incidencia", "NINGUNO"),
            es_contraentrega=p["es_contraentrega"],
        )
        rows.append({
            "Prioridad":       r.prioridad,
            "Nivel":           r.nivel,
            "Score":           r.score,
            "Orden":           p.get("orden_tienda") or p.get("orden_melonn", ""),
            "Cliente":         p.get("nombre_comprador", ""),
            "Teléfono":        p.get("telefono_comprador", ""),
            "Ciudad":          p["ciudad_destino"],
            "Zona":            ZONAS_ES.get(r.zona_info.zona, r.zona_info.zona),
            "Días":            p["dias_en_transito"],
            "SLA Crítico":     r.zona_info.sla_critico,
            "Días sobre SLA":  max(0, p["dias_en_transito"] - r.zona_info.sla_critico + 1),
            "COD":             "SÍ" if p["es_contraentrega"] else "—",
            "Valor COD":       p.get("valor_cod_raw", ""),
            "Transportadora":  p.get("transportadora", ""),
            "Estado":          ESTADOS_ES.get(p.get("estado_melonn",""), p.get("estado_melonn","")),
            "Novedad":         p.get("incidencia", "NINGUNO"),
            "Categoría":       r.incidencia_info.categoria,
            "Promesa vencida": "SÍ" if p.get("promesa_vencida") else "—",
            "F. Despacho":     str(p.get("fecha_despacho") or ""),
            "Motivo riesgo":   r.motivos[0] if r.motivos else "—",
            "Link Melonn":     p.get("link_guia", ""),
        })
    df = pd.DataFrame(rows)
    return df.sort_values(["Prioridad","Días sobre SLA"], ascending=[True,False]).reset_index(drop=True)

@st.cache_data(show_spinner=False)
def cargar_datos(ruta: str, ts: str):
    pedidos, omitidos = leer_csv_melonn(ruta, solo_activos=True)
    df = _procesar_df(pedidos)
    return df, omitidos

def color_nivel(val):
    return {
        "CRITICO": f"background-color:{CRITICO_COLOR}22;color:{CRITICO_COLOR};font-weight:700",
        "RIESGO":  f"background-color:{RIESGO_COLOR}22;color:{RIESGO_COLOR};font-weight:600",
        "NORMAL":  f"background-color:{NORMAL_COLOR}22;color:{NORMAL_COLOR}",
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
    """Renderiza sidebar con logo, uploader y filtros. Retorna (ruta_csv, ts, filtros)."""
    with st.sidebar:
        st.markdown(f"""
            <div style="padding:8px 0 14px 0;">
                <div class="logo-sidebar">MALE'DENIM</div>
                <div class="logo-tagline">THAT FITS</div>
            </div>
        """, unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:0.68rem;letter-spacing:2px;color:{STEEL_BLUE};text-transform:uppercase;margin-bottom:10px;'>{page_label}</div>", unsafe_allow_html=True)
        st.divider()

        archivo = st.file_uploader("Cargar reporte Melonn (CSV)", type=["csv"])

        st.divider()
        st.markdown(f"<div style='font-size:0.68rem;letter-spacing:2px;color:{STEEL_BLUE};text-transform:uppercase;margin-bottom:6px;'>Filtros</div>", unsafe_allow_html=True)

        filtro_nivel = st.multiselect(
            "Nivel de riesgo",
            ["CRITICO","RIESGO","NORMAL"],
            default=["CRITICO","RIESGO"],
        )
        filtro_zona = st.multiselect("Zona logística", list(ZONAS_ES.values()), default=[])

        st.divider()
        st.markdown(f"<div style='font-size:0.68rem;color:{STEEL_BLUE};'>{date.today().strftime('%d / %m / %Y')}</div>", unsafe_allow_html=True)

    if archivo:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(archivo.read())
            ruta_csv = tmp.name
        ts = archivo.name
    else:
        ruta_csv = DEFAULT_CSV
        ts = "Demo — melonn_2026-05-12"

    return ruta_csv, ts, filtro_nivel, filtro_zona

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

    st.markdown(f"""
    <div style="background:white;border-radius:4px;border-left:4px solid {nc};padding:18px 22px;margin-top:8px;">
        <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:14px;">
            <div>
                <div style="font-size:0.62rem;letter-spacing:2px;color:{GRAPHITE_GREY};text-transform:uppercase;">Cliente</div>
                <div style="font-size:1.05rem;font-weight:700;color:{DEEP_INK};">{fila['Cliente']}</div>
                <div style="font-size:0.82rem;color:{GRAPHITE_GREY};">{fila['Teléfono']}</div>
            </div>
            <div style="text-align:center;">
                <div style="font-size:0.62rem;letter-spacing:2px;color:{GRAPHITE_GREY};text-transform:uppercase;">Nivel · Score</div>
                <div style="font-size:1.3rem;font-weight:900;color:{nc};">{fila['Nivel']}</div>
                <div style="font-size:0.9rem;color:{GRAPHITE_GREY};">{int(fila['Score'])}/100</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:0.62rem;letter-spacing:2px;color:{GRAPHITE_GREY};text-transform:uppercase;">Orden · Transportadora</div>
                <div style="font-size:0.95rem;font-weight:700;color:{DEEP_INK};">{fila['Orden']}</div>
                <div style="font-size:0.82rem;color:{GRAPHITE_GREY};">{fila['Transportadora']}</div>
            </div>
        </div>
        <hr style="border-color:{SOFT_CONCRETE};margin:10px 0;">
        <div style="display:flex;gap:28px;flex-wrap:wrap;">
            <div>
                <span style="font-size:0.65rem;color:{GRAPHITE_GREY};letter-spacing:1px;">CIUDAD</span><br>
                <span style="font-weight:600;color:{DEEP_INK};">{fila['Ciudad']}</span>
                <span style="font-size:0.78rem;color:{GRAPHITE_GREY};"> · {fila['Zona']}</span>
            </div>
            <div>
                <span style="font-size:0.65rem;color:{GRAPHITE_GREY};letter-spacing:1px;">DÍAS EN TRÁNSITO</span><br>
                <span style="font-weight:600;color:{nc};">{int(fila['Días'])} días</span>
                <span style="font-size:0.78rem;color:{GRAPHITE_GREY};"> · SLA crítico: {int(fila['SLA Crítico'])}d</span>
            </div>
            <div>
                <span style="font-size:0.65rem;color:{GRAPHITE_GREY};letter-spacing:1px;">PAGO</span><br>
                <span style="font-weight:600;color:{DEEP_INK};">{fila['COD']}</span>
                <span style="font-size:0.78rem;color:{GRAPHITE_GREY};"> {fila['Valor COD']}</span>
            </div>
            <div>
                <span style="font-size:0.65rem;color:{GRAPHITE_GREY};letter-spacing:1px;">NOVEDAD</span><br>
                <span style="font-weight:600;color:{DEEP_INK};">{fila['Novedad']}</span>
                <span style="font-size:0.78rem;color:{GRAPHITE_GREY};"> ({fila['Categoría']})</span>
            </div>
        </div>
        <div style="margin-top:10px;padding:8px 12px;background:{SOFT_CONCRETE};border-radius:2px;">
            <span style="font-size:0.65rem;color:{GRAPHITE_GREY};letter-spacing:1px;">MOTIVO · </span>
            <span style="font-size:0.82rem;font-weight:600;color:{DEEP_INK};">{fila['Motivo riesgo']}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"<div class='sec-title' style='margin-top:14px;'>Seguimiento Melonn — {fila['Transportadora']}</div>", unsafe_allow_html=True)

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
          .st{{font-size:0.68rem;letter-spacing:1.5px;text-transform:uppercase;color:{GRAPHITE_GREY};}}
          .st.ok{{color:{NORMAL_COLOR};}} .st.err{{color:{RIESGO_COLOR};}}
        </style></head><body>
        <div class="wrap">
          <a class="btn" href="{link}" target="_blank">→ ABRIR TRACKING</a>
          <div>
            <div class="tag">{fila['Orden']} · {fila['Transportadora']}</div>
            <div class="st" id="s">Abriendo guía automáticamente...</div>
          </div>
        </div>
        <script>
        (function(){{
          var w=window.open("{link}","_blank","noopener,noreferrer");
          var s=document.getElementById('s');
          if(w){{s.textContent='✓ Guía abierta en nueva pestaña';s.className='st ok';}}
          else{{s.textContent='Bloqueado — usa el botón';s.className='st err';}}
        }})();
        </script></body></html>
        """, height=48)
    else:
        st.warning("Sin link de seguimiento para este pedido.")


# ── Helper de gráficos — compatible con todas las versiones de Altair ─────────
def bar_chart_zona_nivel(df: pd.DataFrame, height: int = 220) -> None:
    """
    Bar chart apilado por Zona × Nivel con colores de marca.
    Import de altair es lazy para aislar errores de compatibilidad.
    """
    import altair as alt  # lazy — no rompe el módulo si altair falla al cargar

    data = (
        df.groupby(["Zona", "Nivel"])
        .size()
        .reset_index(name="Pedidos")
    )
    if data.empty:
        st.info("Sin datos para graficar.")
        return

    orden_nivel = ["CRITICO", "RIESGO", "NORMAL"]
    colores     = [CRITICO_COLOR, RIESGO_COLOR, NORMAL_COLOR]

    chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X("Zona:N", sort="-y", axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("Pedidos:Q"),
            color=alt.Color(
                "Nivel:N",
                scale=alt.Scale(domain=orden_nivel, range=colores),
                legend=alt.Legend(title="Nivel"),
            ),
            tooltip=["Zona:N", "Nivel:N", "Pedidos:Q"],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, use_container_width=True)
