"""
MALE'DENIM OS — Component Library
Componentes reutilizables en HTML/CSS para toda la app.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))  # dashboard/

import streamlit as st
from design_system import (
    DEEP_INK, STEEL_BLUE, GRAPHITE_GREY, SOFT_CONCRETE, SURFACE_BG,
    SURFACE_CARD, BORDER_DEFAULT,
    COLOR_CRITICO, COLOR_RIESGO, COLOR_NORMAL, COLOR_PENDIENTE, COLOR_INFO, COLOR_NEUTRO,
    BG_CRITICO, BG_RIESGO, BG_NORMAL, BG_PENDIENTE, BG_INFO, BG_NEUTRO,
    RUST, CRIMSON, TEAL, NAVY, KHAKI,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _status_cfg(level: str) -> tuple[str, str]:
    """Retorna (color_texto, color_fondo) para un nivel de estado."""
    m = {
        "CRITICO":   (COLOR_CRITICO,   BG_CRITICO),
        "CRÍTICO":   (COLOR_CRITICO,   BG_CRITICO),
        "RIESGO":    (COLOR_RIESGO,    BG_RIESGO),
        "NORMAL":    (COLOR_NORMAL,    BG_NORMAL),
        "OK":        (COLOR_NORMAL,    BG_NORMAL),
        "PENDIENTE": (COLOR_PENDIENTE, BG_PENDIENTE),
        "INFO":      (COLOR_INFO,      BG_INFO),
        "NEUTRO":    (COLOR_NEUTRO,    BG_NEUTRO),
        "ENTREGADO": (COLOR_NORMAL,    BG_NORMAL),
        "NOVEDAD":   (COLOR_RIESGO,    BG_RIESGO),
        "EN_TRANSITO":(COLOR_INFO,     BG_INFO),
    }
    return m.get(level.upper(), (COLOR_NEUTRO, BG_NEUTRO))


# ── Page header ────────────────────────────────────────────────────────────────

def page_header(title: str, subtitle: str = "", right_content: str = ""):
    st.markdown(f"""
    <div style="
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 28px;
        padding-bottom: 20px;
        border-bottom: 1px solid {BORDER_DEFAULT};
    ">
        <div>
            <h1 style="
                font-family: 'Inter', sans-serif;
                font-size: 1.6rem;
                font-weight: 800;
                color: {DEEP_INK};
                letter-spacing: -0.5px;
                margin: 0 0 4px 0;
                line-height: 1;
            ">{title}</h1>
            {f'<p style="font-size:0.8rem;color:{GRAPHITE_GREY};margin:0;font-weight:400;">{subtitle}</p>' if subtitle else ''}
        </div>
        {f'<div>{right_content}</div>' if right_content else ''}
    </div>
    """, unsafe_allow_html=True)


def section_header(title: str, subtitle: str = "", top_margin: int = 24):
    st.markdown(f"""
    <div style="margin-top:{top_margin}px; margin-bottom:14px;">
        <p style="
            font-family:'Inter',sans-serif;
            font-size:0.6rem;
            font-weight:700;
            letter-spacing:3px;
            text-transform:uppercase;
            color:{GRAPHITE_GREY};
            margin:0 0 2px 0;
        ">{title}</p>
        {f'<p style="font-size:0.78rem;color:{GRAPHITE_GREY};margin:0;">{subtitle}</p>' if subtitle else ''}
    </div>
    """, unsafe_allow_html=True)


# ── KPI Card ───────────────────────────────────────────────────────────────────

def kpi_card(
    value: str,
    label: str,
    sublabel: str = "",
    delta: str = "",
    delta_positive: bool = True,
    accent_color: str = STEEL_BLUE,
    icon: str = "",
    width: str = "100%",
):
    delta_color = COLOR_NORMAL if delta_positive else COLOR_CRITICO
    delta_html = f"""
        <div style="
            display:inline-flex;align-items:center;gap:4px;
            margin-top:6px;
            font-size:0.68rem;font-weight:600;
            color:{delta_color};
        ">{delta}</div>
    """ if delta else ""

    icon_html = f'<span style="font-size:1.1rem;margin-bottom:8px;display:block;">{icon}</span>' if icon else ""

    st.markdown(f"""
    <div style="
        background: {SURFACE_CARD};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: 14px;
        padding: 20px 22px;
        border-left: 3px solid {accent_color};
        width: {width};
        box-sizing: border-box;
        box-shadow: 0 1px 4px rgba(33,48,51,0.05);
    ">
        {icon_html}
        <p style="
            font-family:'Inter',sans-serif;
            font-size:0.58rem;
            font-weight:700;
            letter-spacing:2.5px;
            text-transform:uppercase;
            color:{GRAPHITE_GREY};
            margin:0 0 6px 0;
        ">{label}</p>
        <p style="
            font-family:'Inter',sans-serif;
            font-size:1.75rem;
            font-weight:800;
            color:{DEEP_INK};
            margin:0;
            line-height:1;
            letter-spacing:-0.5px;
        ">{value}</p>
        {f'<p style="font-size:0.68rem;color:{GRAPHITE_GREY};margin:4px 0 0 0;">{sublabel}</p>' if sublabel else ''}
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


# ── Alert Card ─────────────────────────────────────────────────────────────────

def alert_card(
    title: str,
    message: str,
    level: str = "INFO",
    action_label: str = "",
    icon: str = "",
):
    color, bg = _status_cfg(level)
    icons_map = {"CRITICO": "⚠", "RIESGO": "!", "NORMAL": "✓", "INFO": "i", "PENDIENTE": "⏳"}
    _icon = icon or icons_map.get(level.upper(), "•")

    st.markdown(f"""
    <div style="
        background: {bg};
        border: 1px solid {color}22;
        border-left: 3px solid {color};
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 8px;
        display: flex;
        align-items: flex-start;
        gap: 12px;
    ">
        <span style="
            font-size:0.85rem;font-weight:700;color:{color};
            min-width:18px;text-align:center;margin-top:1px;
        ">{_icon}</span>
        <div style="flex:1;">
            <p style="
                font-family:'Inter',sans-serif;
                font-size:0.78rem;font-weight:700;
                color:{DEEP_INK};margin:0 0 2px 0;
            ">{title}</p>
            <p style="
                font-family:'Inter',sans-serif;
                font-size:0.74rem;color:{GRAPHITE_GREY};margin:0;line-height:1.4;
            ">{message}</p>
        </div>
        {f'<span style="font-size:0.65rem;font-weight:700;color:{color};letter-spacing:1px;white-space:nowrap;margin-top:2px;">{action_label} →</span>' if action_label else ''}
    </div>
    """, unsafe_allow_html=True)


# ── Status Badge ───────────────────────────────────────────────────────────────

def badge(text: str, level: str = "NEUTRO") -> str:
    """Retorna HTML de un badge inline. Usar con unsafe_allow_html=True."""
    color, bg = _status_cfg(level)
    return f"""<span style="
        display:inline-block;
        background:{bg};
        color:{color};
        font-family:'Inter',sans-serif;
        font-size:0.6rem;
        font-weight:700;
        letter-spacing:1.5px;
        text-transform:uppercase;
        padding:3px 8px;
        border-radius:20px;
        border:1px solid {color}33;
        white-space:nowrap;
    ">{text}</span>"""


# ── Card wrapper ───────────────────────────────────────────────────────────────

def card_start(padding: str = "24px", radius: str = "14px") -> str:
    return f"""<div style="
        background:{SURFACE_CARD};
        border:1px solid {BORDER_DEFAULT};
        border-radius:{radius};
        padding:{padding};
        box-shadow:0 1px 4px rgba(33,48,51,0.05);
        margin-bottom:16px;
    ">"""

def card_end() -> str:
    return "</div>"


def card(content_html: str, padding: str = "24px", radius: str = "14px"):
    st.markdown(
        card_start(padding, radius) + content_html + card_end(),
        unsafe_allow_html=True,
    )


# ── Stat row (dentro de card) ──────────────────────────────────────────────────

def stat_row(items: list[tuple[str, str, str]]):
    """items = [(label, value, sublabel), ...]"""
    cols_html = ""
    for label, value, sublabel in items:
        cols_html += f"""
        <div style="flex:1;min-width:100px;">
            <p style="font-size:0.58rem;font-weight:700;letter-spacing:2px;
                      text-transform:uppercase;color:{GRAPHITE_GREY};margin:0 0 4px 0;">{label}</p>
            <p style="font-size:1.25rem;font-weight:800;color:{DEEP_INK};margin:0;line-height:1;">{value}</p>
            {f'<p style="font-size:0.68rem;color:{GRAPHITE_GREY};margin:2px 0 0 0;">{sublabel}</p>' if sublabel else ''}
        </div>"""
    st.markdown(f"""
    <div style="display:flex;gap:32px;flex-wrap:wrap;align-items:flex-start;">
        {cols_html}
    </div>
    """, unsafe_allow_html=True)


# ── Table header row ───────────────────────────────────────────────────────────

def table_header(columns: list[str], widths: list[str] = None) -> str:
    if not widths:
        widths = [f"{100//len(columns)}%" for _ in columns]
    cells = "".join(
        f'<th style="width:{w};padding:10px 14px;font-size:0.6rem;font-weight:700;'
        f'letter-spacing:2px;text-transform:uppercase;color:{GRAPHITE_GREY};'
        f'text-align:left;border-bottom:1px solid {BORDER_DEFAULT};'
        f'background:#F7F5F2;white-space:nowrap;">{c}</th>'
        for c, w in zip(columns, widths)
    )
    return f"<thead><tr>{cells}</tr></thead>"


def table_row_html(cells_html: list[str], on_hover: bool = True) -> str:
    hover = f'onmouseover="this.style.background=\'#F7F5F2\'" onmouseout="this.style.background=\'white\'"' if on_hover else ""
    tds = "".join(
        f'<td style="padding:11px 14px;border-bottom:1px solid #F2F0ED;'
        f'font-size:0.8rem;color:{DEEP_INK};vertical-align:middle;">{c}</td>'
        for c in cells_html
    )
    return f'<tr style="cursor:default;" {hover}>{tds}</tr>'


def table_wrap(header_html: str, rows_html: str) -> str:
    return f"""
    <div style="border:1px solid {BORDER_DEFAULT};border-radius:12px;overflow:hidden;background:white;">
    <table style="width:100%;border-collapse:collapse;font-family:'Inter',sans-serif;">
        {header_html}
        <tbody>{rows_html}</tbody>
    </table>
    </div>"""


# ── Empty state ────────────────────────────────────────────────────────────────

def empty_state(icon: str, title: str, subtitle: str = ""):
    st.markdown(f"""
    <div style="
        text-align:center;padding:48px 24px;
        background:white;border:1px solid {BORDER_DEFAULT};
        border-radius:14px;
    ">
        <div style="font-size:2rem;margin-bottom:12px;">{icon}</div>
        <p style="font-family:'Inter',sans-serif;font-size:0.88rem;
                  font-weight:700;color:{DEEP_INK};margin:0 0 6px 0;">{title}</p>
        {f'<p style="font-size:0.76rem;color:{GRAPHITE_GREY};margin:0;">{subtitle}</p>' if subtitle else ''}
    </div>
    """, unsafe_allow_html=True)


# ── Divider con label ──────────────────────────────────────────────────────────

def divider_label(text: str, top: int = 24, bottom: int = 16):
    st.markdown(f"""
    <div style="
        display:flex;align-items:center;gap:12px;
        margin:{top}px 0 {bottom}px 0;
    ">
        <span style="font-family:'Inter',sans-serif;font-size:0.58rem;font-weight:700;
                     letter-spacing:3px;text-transform:uppercase;color:{GRAPHITE_GREY};
                     white-space:nowrap;">{text}</span>
        <div style="flex:1;height:1px;background:{BORDER_DEFAULT};"></div>
    </div>
    """, unsafe_allow_html=True)


# ── Detail panel row ───────────────────────────────────────────────────────────

def detail_row(label: str, value: str, value_html: str = ""):
    _val = value_html if value_html else f'<span style="font-weight:600;color:{DEEP_INK};font-size:0.82rem;">{value}</span>'
    st.markdown(f"""
    <div style="
        display:flex;justify-content:space-between;align-items:center;
        padding:9px 0;border-bottom:1px solid #F2F0ED;
    ">
        <span style="font-size:0.65rem;font-weight:600;letter-spacing:1.5px;
                     text-transform:uppercase;color:{GRAPHITE_GREY};">{label}</span>
        {_val}
    </div>
    """, unsafe_allow_html=True)


# ── Progress bar ───────────────────────────────────────────────────────────────

def progress_bar(value: float, max_val: float, color: str = STEEL_BLUE, height: int = 6):
    pct = min(100, round((value / max_val * 100) if max_val else 0, 1))
    st.markdown(f"""
    <div style="background:#F2F0ED;border-radius:99px;height:{height}px;overflow:hidden;">
        <div style="background:{color};width:{pct}%;height:100%;
                    border-radius:99px;transition:width 0.3s ease;"></div>
    </div>
    """, unsafe_allow_html=True)


# ── Sidebar logo (usar en app.py) ──────────────────────────────────────────────

def sidebar_logo():
    st.sidebar.markdown(f"""
    <div style="padding:24px 16px 16px 16px;border-bottom:1px solid rgba(135,166,184,0.1);">
        <p style="
            font-family:'Inter',sans-serif;
            font-size:1.1rem;font-weight:800;
            letter-spacing:4px;color:#FFFFFF;
            margin:0;line-height:1;
        ">MALE'DENIM</p>
        <p style="
            font-family:'Inter',sans-serif;
            font-size:0.52rem;font-weight:600;
            letter-spacing:5px;color:rgba(135,166,184,0.7);
            margin:3px 0 0 0;text-transform:uppercase;
        ">THAT FITS</p>
    </div>
    """, unsafe_allow_html=True)


def sidebar_footer(username: str, role: str):
    st.sidebar.markdown(f"""
    <div style="
        position:fixed;bottom:0;left:0;width:236px;
        padding:12px 16px;
        border-top:1px solid rgba(135,166,184,0.1);
        background:linear-gradient(0deg,#0D1A1D,transparent);
    ">
        <p style="font-size:0.55rem;color:rgba(135,166,184,0.6);
                  letter-spacing:1.5px;text-transform:uppercase;margin:0 0 2px 0;">{role}</p>
        <p style="font-size:0.78rem;color:#E1E1DF;font-weight:600;margin:0;">{username}</p>
        <p style="font-size:0.52rem;color:rgba(135,166,184,0.4);
                  letter-spacing:1px;margin:6px 0 0 0;">MALE'DENIM OS v1.0</p>
    </div>
    """, unsafe_allow_html=True)
