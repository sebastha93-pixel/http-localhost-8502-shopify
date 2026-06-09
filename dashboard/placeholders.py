"""
MALE'DENIM OS — Páginas placeholder ("Próximamente")
Cada función es una página de Streamlit. Se registran con st.Page() en app.py.
Mantiene el design system y muestra de qué se va a tratar cada módulo.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import streamlit as st

from shared import (
    CSS, DEEP_INK, GRAPHITE_GREY, STEEL_BLUE,
    dash_hero, dash_section,
)


def _proximamente(title: str, descripcion: str, icon: str = "○",
                  features: list = None, tone: str = "blue"):
    """Render genérico de página 'Próximamente'."""
    st.markdown(CSS, unsafe_allow_html=True)

    # Guard básico
    if "logistica" not in st.session_state.get("permisos", ["logistica"]):
        st.error("🔒 Sin acceso.")
        st.stop()

    dash_hero(title.capitalize(), descripcion)

    # Card central con info
    feats_html = ""
    if features:
        feats_html = '<div style="margin-top:18px;">'
        for f in features:
            feats_html += (
                '<div style="display:flex;align-items:center;gap:10px;'
                'padding:8px 0;border-bottom:1px solid #F4F2EE;'
                'font-size:0.86rem;color:#1A1A1A;">'
                '<span style="color:#87A6B8;">›</span>'
                f'<span>{f}</span>'
                '</div>'
            )
        feats_html += '</div>'

    body = (
        '<div style="background:white;border:1px solid #ECECEC;'
        'border-radius:16px;padding:48px 32px;text-align:center;'
        'box-shadow:0 1px 2px rgba(0,0,0,0.03);">'
        f'<div class="dash-chip--{tone}" style="width:56px;height:56px;'
        'border-radius:14px;display:inline-flex;align-items:center;'
        f'justify-content:center;font-size:1.4rem;margin-bottom:18px;">{icon}</div>'
        f'<h2 style="font-size:1.2rem;font-weight:700;color:#1A1A1A;'
        f'margin:0 0 6px 0;letter-spacing:-0.3px;">Próximamente</h2>'
        f'<p style="font-size:0.84rem;color:#6B7280;margin:0 0 4px 0;'
        f'max-width:480px;margin-left:auto;margin-right:auto;line-height:1.55;">'
        f'{descripcion}</p>'
        '</div>'
    )

    if feats_html:
        feats_card = (
            '<div style="background:white;border:1px solid #ECECEC;'
            'border-radius:16px;padding:24px;margin-top:18px;'
            'box-shadow:0 1px 2px rgba(0,0,0,0.03);">'
            '<p style="font-size:0.6rem;font-weight:700;letter-spacing:1.6px;'
            'text-transform:uppercase;color:#9CA0A4;margin:0 0 4px 0;">'
            'Qué incluirá este módulo</p>'
            f'{feats_html}'
            '</div>'
        )
        body = body + feats_card

    st.markdown(body, unsafe_allow_html=True)


# ── Operaciones ────────────────────────────────────────────────────────────────
def contraentrega():
    _proximamente(
        "Contraentrega",
        "Gestión completa de pedidos contra entrega — autorizaciones, seguimiento de recaudo y trazabilidad de pagos.",
        icon="◆", tone="khaki",
        features=[
            "Pendientes por autorizar (acción directa con Melonn)",
            "Recaudo COD esperado vs efectivo",
            "Comparativo por transportadora",
            "Diferencias por conciliar",
        ],
    )

def envios():
    _proximamente(
        "Envíos",
        "Trazabilidad de despachos en tiempo real — SLA por zona, cumplimiento por transportadora, alertas operativas.",
        icon="→", tone="blue",
        features=[
            "Envíos del día con cumplimiento SLA",
            "Tiempo promedio por zona logística",
            "Comparativo de transportadoras",
            "Alertas de retrasos automáticas",
        ],
    )

def devoluciones():
    _proximamente(
        "Devoluciones",
        "Análisis de devoluciones — motivos, costos, impacto financiero y patrones por referencia.",
        icon="↩", tone="orange",
        features=[
            "Devoluciones activas en proceso",
            "Top motivos y referencias",
            "Costo total de devoluciones",
            "Impacto en margen por SKU",
        ],
    )

def incidencias():
    _proximamente(
        "Incidencias",
        "Centro de gestión de novedades operativas — cliente, transportadora, seguimiento y resolución.",
        icon="!", tone="red",
        features=[
            "Incidencias críticas activas",
            "Por categoría (cliente, transportadora, seguimiento)",
            "Histórico de resolución",
            "Acciones pendientes asignadas",
        ],
    )


# ── Finanzas ───────────────────────────────────────────────────────────────────
def finanzas():
    _proximamente(
        "Finanzas",
        "Vista financiera consolidada — flujo de caja, recaudo, pendientes por plataforma y forecast.",
        icon="$", tone="green",
        features=[
            "Recaudo esperado vs recibido",
            "Pendientes por plataforma (Addi, Wompi, MercadoPago, Suma Pay)",
            "Flujo bancario Bancolombia + Davivienda",
            "Forecast de caja a 30 días",
        ],
    )

def facturacion():
    _proximamente(
        "Facturación",
        "Estado de facturación MarketHub + Siigo — facturas emitidas, pendientes, notas crédito y DIAN.",
        icon="≡", tone="blue",
        features=[
            "Pedidos facturados vs pendientes",
            "Errores de MarketHub",
            "Facturas y notas crédito Siigo",
            "Estado de transmisión DIAN",
        ],
    )


# ── Comercial ──────────────────────────────────────────────────────────────────
def comercial():
    _proximamente(
        "Comercial",
        "Performance de ventas — meta mensual, ventas por canal, ticket promedio y top productos.",
        icon="↗", tone="green",
        features=[
            "Ventas hoy vs ventas del mes",
            "Cumplimiento de meta mensual",
            "Ticket promedio y conversión",
            "Top productos por revenue",
        ],
    )

def inventario():
    _proximamente(
        "Inventario",
        "Control de stock — disponible, crítico, curvas por talla, rotación y aging.",
        icon="◫", tone="khaki",
        features=[
            "Stock disponible y crítico",
            "Curvas por talla y referencia",
            "Rotación y aging del inventario",
            "Productos ganadores vs lentos",
        ],
    )


# ── Inteligencia ───────────────────────────────────────────────────────────────
def inteligencia():
    _proximamente(
        "Inteligencia",
        "Hallazgos automáticos con recomendaciones accionables sobre logística, devoluciones, transportadoras y ventas.",
        icon="★", tone="blue",
        features=[
            "Hallazgos automáticos sobre operación",
            "Recomendaciones por referencia y ciudad",
            "Anomalías de SLA y desembolsos",
            "Acciones sugeridas con impacto estimado",
        ],
    )

def reportes():
    _proximamente(
        "Reportes",
        "Reportes financieros, logísticos, comerciales e inventario. Exportar a Excel/PDF o programar envío automático.",
        icon="▤", tone="gray",
        features=[
            "Reportes financieros (recaudo, conciliación, flujo)",
            "Reportes logísticos (SLA, devoluciones, transportadoras)",
            "Reportes comerciales (ventas, top SKUs, canales)",
            "Exportar Excel / PDF · envío programado",
        ],
    )


# ── Configuración ──────────────────────────────────────────────────────────────
def configuracion():
    _proximamente(
        "Configuración",
        "Ajustes globales del sistema — SLAs por zona, matriz logística, reglas de conciliación, permisos.",
        icon="⚙", tone="gray",
        features=[
            "SLA por zona logística",
            "Matriz logística y reglas de incidencias",
            "Estados de conciliación",
            "Reglas de negocio personalizadas",
        ],
    )

def integraciones():
    _proximamente(
        "Integraciones",
        "Estado y configuración de todas las APIs — Shopify, Melonn, pasarelas de pago, bancos, MarketHub, Siigo, Kommo.",
        icon="◈", tone="green",
        features=[
            "Estado conectado · última sincronización · errores",
            "Reconectar cuentas (OAuth / API keys)",
            "Logs de eventos por integración",
            "Webhooks activos y configuración",
        ],
    )
