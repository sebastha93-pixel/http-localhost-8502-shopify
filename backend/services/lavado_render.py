"""
backend.services.lavado_render — etiqueta de lavado como PLANTILLA editable.

La etiqueta es un LAYOUT de elementos con posición absoluta (x, y):
  · texto      — una o varias líneas (\\n), con fuente/tamaño/alineación
  · logo       — imagen (assets/lavado/logo.png)
  · simbolos    — fila de PNG de cuidado

El editor visual de la app arrastra esos elementos y edita su texto; guarda
el layout en `plantillas_etiqueta`. El MISMO layout se rasteriza aquí con
Pillow (fuentes de marca reales) → BITMAP TSPL a la SAT, con corte. Así lo
que se ve en el editor es lo que se imprime.

Variables en los textos: {{REF}} y {{COMPOSICION}} se sustituyen al imprimir.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def dividir_composicion(txt: str) -> list[str]:
    """'87% ALGODON, 8% POLYESTER 5% ELASTANO' → un material por línea.
    Si no reconoce el patrón, devuelve la línea entera."""
    partes = re.findall(r"\d+\s*%\s*[^%\d]+", txt or "")
    # Quita separadores colgantes (coma/;/·/guion) al final de cada material.
    limpio = [p.strip().strip(",;·-").strip() for p in partes]
    limpio = [p for p in limpio if p]
    return limpio or ([txt.strip()] if txt.strip() else [])

DPMM = 8
ANCHO = 224                 # 27.5 mm
LARGO_DOTS = 130 * DPMM     # 1040 = 130 mm

_BASE = Path(__file__).resolve().parent.parent / "assets" / "lavado"
_FONTS = _BASE / "fonts"
_SYMS = _BASE / "symbols"

# Fuentes de marca → archivo bundleado.
FUENTES = {
    "TimesNewRoman": "TimesNewRoman.ttf",
    "Arial": "Arial.ttf",
    "ArialBold": "ArialBold.ttf",
}

_font_cache: dict = {}


def _font(fuente: str, px: int):
    from PIL import ImageFont
    arch = FUENTES.get(fuente, "Arial.ttf")
    clave = (arch, px)
    if clave not in _font_cache:
        _font_cache[clave] = ImageFont.truetype(str(_FONTS / arch), px)
    return _font_cache[clave]


# ─── Layout por defecto (reproduce el diseño aprobado 2026-07-23) ──────────
# x = centro cuando align="center"; y = borde superior del elemento.
def layout_por_defecto() -> dict:
    cx = ANCHO // 2
    els: list[dict] = [
        {"id": "logo", "tipo": "logo", "x": cx, "y": 92, "alto": 82, "align": "center"},
        {"id": "ref", "tipo": "texto", "x": cx, "y": 232, "texto": "REF {{REF}}",
         "fuente": "TimesNewRoman", "tam": 28, "align": "center"},
        {"id": "composicion", "tipo": "texto", "x": cx, "y": 278, "texto": "{{COMPOSICION}}",
         "fuente": "Arial", "tam": 17, "align": "center", "por_material": True},
    ]
    # Un elemento por LÍNEA (se arrastran uno a uno en el editor).
    def apilar(prefijo: str, lineas: list[str], y0: int, fuente: str, paso: int = 26):
        y = y0
        for i, ln in enumerate(lineas):
            els.append({"id": f"{prefijo}{i + 1}", "tipo": "texto", "x": cx, "y": y,
                        "texto": ln, "fuente": fuente, "tam": 17, "align": "center"})
            y += paso

    apilar("legal", ["MADE IN COLOMBIA", "HECHO POR DIRTY JEANS",
                     "NIT 901680460-1", "SIC 1036844755"], 380, "ArialBold")
    apilar("care_en", ["MACHINE WASH WARM", "NO BLEACH",
                       "TUMBLE DRY LOW", "COOL IRON"], 520, "Arial")
    apilar("care_es", ["LAVADORA AGUA TIBIA", "NO BLANQUEADOR",
                       "SECADORA BAJA TEMP", "PLANCHA TIBIA"], 660, "Arial")
    els.append({"id": "simbolos", "tipo": "simbolos", "x": cx, "y": 810, "alto": 40, "align": "center",
                "items": ["lavadora.png", "no_bleach.png", "secadora.png", "plancha.png", "no_secadora.png"]})
    return {"ancho": ANCHO, "alto": LARGO_DOTS, "elementos": els}


def _sustituir(txt: str, codigo: str, composicion: str) -> str:
    return (txt.replace("{{REF}}", codigo or "")
               .replace("{{COMPOSICION}}", composicion or "")).strip()


def _cargar_logo(alto: int):
    from PIL import Image, ImageOps
    p = _BASE / "logo.png"
    if not p.exists():
        return None
    logo = Image.open(p).convert("L")
    caja = ImageOps.invert(logo).getbbox()
    if caja:
        logo = logo.crop(caja)
    w, h = logo.size
    nw = max(1, int(w * alto / h))
    # Tope físico: el logo no puede ser más ancho que la etiqueta (27.5 mm).
    # Se limita MANTENIENDO proporción (recalcula alto) → nunca se deforma.
    if nw > ANCHO:
        nw = ANCHO
        alto = max(1, int(h * nw / w))
    return logo.resize((nw, alto), Image.LANCZOS)


def _cargar_simbolo(nombre: str, alto: int):
    from PIL import Image
    p = _SYMS / nombre
    if not p.exists():
        return None
    im = Image.open(p).convert("L")
    w, h = im.size
    return im.resize((max(1, int(w * alto / h)), alto), Image.LANCZOS)


def render_layout(layout: dict, codigo: str, composicion: str):
    """Rasteriza un layout a imagen 1-bit (PIL '1'), 224 × 1040."""
    from PIL import Image, ImageDraw
    img = Image.new("L", (ANCHO, LARGO_DOTS), 255)
    draw = ImageDraw.Draw(img)

    for el in layout.get("elementos", []):
        tipo = el.get("tipo")
        x = int(el.get("x", ANCHO // 2))
        y = int(el.get("y", 0))
        align = el.get("align", "center")

        if tipo == "texto":
            txt = _sustituir(el.get("texto", ""), codigo, composicion)
            font = _font(el.get("fuente", "Arial"), int(el.get("tam", 17)))
            # Composición: un material por línea (98% ALGODON / 2% ELASTANO).
            # Por id "composicion" también, para layouts guardados sin el flag.
            if el.get("por_material") or el.get("id") == "composicion":
                txt = "\n".join(dividir_composicion(txt))
            max_w = int(el.get("max_w") or 0)
            # Envolver por palabra si se definió un ancho máximo (composición).
            lineas_txt: list[str] = []
            for raw in txt.split("\n"):
                if max_w and raw.strip():
                    cur = ""
                    for w_ in raw.split():
                        cand = (cur + " " + w_).strip()
                        bb = draw.textbbox((0, 0), cand, font=font)
                        if cur and (bb[2] - bb[0]) > max_w:
                            lineas_txt.append(cur); cur = w_
                        else:
                            cur = cand
                    if cur:
                        lineas_txt.append(cur)
                else:
                    lineas_txt.append(raw)
            cy = y
            for linea in lineas_txt:
                if not linea.strip():
                    cy += int(el.get("tam", 17)) + 4
                    continue
                bx0, by0, bx1, by1 = draw.textbbox((0, 0), linea, font=font)
                w_linea = bx1 - bx0
                if align == "center":
                    px = x - w_linea // 2 - bx0
                elif align == "right":
                    px = x - w_linea - bx0
                else:
                    px = x - bx0
                draw.text((px, cy - by0), linea, font=font, fill=0)
                cy += (by1 - by0) + 8

        elif tipo == "logo":
            logo = _cargar_logo(int(el.get("alto", 82)))
            if logo:
                lx = x - logo.size[0] // 2 if align == "center" else x
                img.paste(logo, (int(lx), y))

        elif tipo == "simbolos":
            alto = int(el.get("alto", 40))
            syms = [s for s in (_cargar_simbolo(n, alto) for n in el.get("items", [])) if s]
            if syms:
                sep = 8
                total = sum(s.size[0] for s in syms) + sep * (len(syms) - 1)
                sx = x - total // 2 if align == "center" else x
                for s in syms:
                    img.paste(s, (int(sx), y))
                    sx += s.size[0] + sep

    return img.point(lambda v: 0 if v < 160 else 255, mode="1")


def render_etiqueta(codigo: str, composicion: str, layout: Optional[dict] = None):
    """Compat: rasteriza el layout dado (o el por defecto)."""
    return render_layout(layout or layout_por_defecto(), codigo, composicion)


def tspl_etiqueta(codigo: str, composicion: str, copias: int = 1,
                  cortar: bool = True, layout: Optional[dict] = None) -> bytes:
    """Trabajo TSPL: layout → BITMAP + corte por etiqueta (SIZE 27.5×130mm)."""
    img = render_etiqueta(codigo, composicion, layout=layout)
    w, h = img.size
    ancho_bytes = (w + 7) // 8
    datos = img.tobytes()   # PIL '1': bit 1=blanco, 0=negro (= TSPL BITMAP mode 0)
    cab = (f"SIZE 27.5 mm,130 mm\r\nGAP 0,0\r\nDIRECTION 0\r\n"
           f"DENSITY 12\r\nSET CUTTER {1 if cortar else 0}\r\nCLS\r\n").encode()
    bitmap = f"BITMAP 0,0,{ancho_bytes},{h},0,".encode() + datos + b"\r\n"
    pie = f"PRINT {max(1, copias)},1\r\n".encode()
    return cab + bitmap + pie
