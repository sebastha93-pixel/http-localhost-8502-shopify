"""
backend.services.lavado_render — etiqueta de lavado renderizada como IMAGEN.

La SAT TT448 no tiene las tipografías de marca (Times New Roman, Arial,
Segoe UI). En vez de las fuentes internas (feas), se compone la etiqueta
con Pillow usando las fuentes reales + el logo + los símbolos oficiales,
y se envía a la impresora como MAPA DE BITS por TSPL (comando BITMAP),
con corte nativo por etiqueta. Fidelidad idéntica a BarTender.

Layout calcado de la etiqueta física de referencia (2026-07-23):
  logo · REF · composición · (aire) · MADE IN COLOMBIA/legal ·
  (aire) · cuidados EN · cuidados ES · símbolos.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# 203 dpi = 8 dots/mm. Ancho útil 27.5 mm → 220 dots; se usa 224 (28 bytes
# exactos para TSPL BITMAP). Largo dinámico según el contenido.
DPMM = 8
ANCHO = 224
MARGEN_COSTURA = 96          # ~12 mm en blanco arriba y abajo (zona de costura)

_BASE = Path(__file__).resolve().parent.parent / "assets" / "lavado"
_FONTS = _BASE / "fonts"
_SYMS = _BASE / "symbols"

_font_cache: dict = {}


def _font(nombre: str, px: int):
    from PIL import ImageFont
    clave = (nombre, px)
    if clave not in _font_cache:
        _font_cache[clave] = ImageFont.truetype(str(_FONTS / nombre), px)
    return _font_cache[clave]


def _ancho_texto(draw, txt: str, font) -> int:
    x0, _, x1, _ = draw.textbbox((0, 0), txt, font=font)
    return x1 - x0


_MARGEN_LAT = 8   # 1 mm de aire a cada lado — nada toca el borde


def _centrado(draw, y: int, txt: str, font, img_w: int = ANCHO) -> int:
    """Dibuja centrado, AUTOENCOGIENDO la fuente si la línea no cabe en el
    ancho útil (evita que el texto se corte contra el borde de la tira).
    Devuelve el alto de línea consumido."""
    from PIL import ImageFont
    util = img_w - 2 * _MARGEN_LAT
    x0, y0, x1, y1 = draw.textbbox((0, 0), txt, font=font)
    if (x1 - x0) > util and getattr(font, "path", None):
        px = getattr(font, "size", 20)
        while px > 11:
            px -= 1
            font = ImageFont.truetype(font.path, px)
            x0, y0, x1, y1 = draw.textbbox((0, 0), txt, font=font)
            if (x1 - x0) <= util:
                break
    x = (img_w - (x1 - x0)) // 2 - x0
    draw.text((x, y - y0), txt, font=font, fill=0)
    return (y1 - y0)


def _envolver(draw, txt: str, font, max_w: int) -> list[str]:
    palabras = txt.split()
    lineas, linea = [], ""
    for w in palabras:
        cand = (linea + " " + w).strip()
        if linea and _ancho_texto(draw, cand, font) > max_w:
            lineas.append(linea)
            linea = w
        else:
            linea = cand
    if linea:
        lineas.append(linea)
    return lineas


def _cargar_logo(max_w: int, alto_objetivo: int = 0):
    from PIL import Image, ImageOps
    p = _BASE / "logo.png"
    if not p.exists():
        return None
    logo = Image.open(p).convert("L")
    # Recortar bordes blancos para maximizar el logo en el ancho disponible.
    inv = ImageOps.invert(logo)
    caja = inv.getbbox()
    if caja:
        logo = logo.crop(caja)
    w, h = logo.size
    if alto_objetivo:
        # Escala por ALTO (la marca a 18 pt ≈ 51 px de alto de mancha)
        nueva_h = alto_objetivo
        nueva_w = max(1, int(w * nueva_h / h))
        if nueva_w > max_w:                    # no exceder el ancho útil
            nueva_w = max_w
            nueva_h = max(1, int(h * nueva_w / w))
    else:
        nueva_w = min(max_w, ANCHO - 20)
        nueva_h = max(1, int(h * nueva_w / w))
    return logo.resize((nueva_w, nueva_h), Image.LANCZOS)


def _cargar_simbolo(nombre: str, alto: int):
    from PIL import Image
    p = _SYMS / nombre
    if not p.exists():
        return None
    im = Image.open(p).convert("L")
    w, h = im.size
    nueva_w = max(1, int(w * alto / h))
    return im.resize((nueva_w, alto), Image.LANCZOS)


def _paleta_1bit(img):
    """A blanco/negro 1-bit con umbral (los antialias grises → negro sólido)."""
    return img.convert("L").point(lambda v: 0 if v < 160 else 255, mode="1")


def render_etiqueta(codigo: str, composicion: str) -> bytes:
    """Devuelve la imagen 1-bit (PIL mode '1') de la etiqueta completa."""
    from PIL import Image, ImageDraw

    # Tamaños EXACTOS pedidos por Sebastián (2026-07-23), en PUNTOS → px a
    # 203 dpi (1 pt = 203/72 = 2.82 px): marca 18pt=51 · REF 10pt=28 · resto 6pt=17.
    PT = 203 / 72
    px_marca = round(18 * PT)   # 51
    f_ref = _font("TimesNewRoman.ttf", round(10 * PT))   # 28
    f_comp = _font("Arial.ttf", round(6 * PT))           # 17
    f_care = _font("Arial.ttf", round(6 * PT))           # 17
    f_legal = _font("ArialBold.ttf", round(6 * PT))      # 17 (≈ Segoe UI Semibold)

    # Lienzo alto provisional; se recorta al final.
    img = Image.new("L", (ANCHO, 1600), 255)
    draw = ImageDraw.Draw(img)
    y = MARGEN_COSTURA

    # ── Logo (imagen real) o respaldo de texto ──
    logo = _cargar_logo(ANCHO - 16, alto_objetivo=round(px_marca * 1.6))
    if logo is not None:
        lx = (ANCHO - logo.size[0]) // 2
        img.paste(logo, (lx, y))
        y += logo.size[1] + 22
    else:
        # Marca a 18 pt (respaldo hasta montar el logo real).
        y += _centrado(draw, y, "MALE", _font("Arial.ttf", px_marca)); y += 4
        y += _centrado(draw, y, "D E N I M", _font("Arial.ttf", round(px_marca * 0.42))); y += 22

    # ── Referencia (Times New Roman) ──
    y += _centrado(draw, y, f"REF {codigo}", f_ref) + 12

    # ── Composición (Arial) ──
    if composicion:
        for ln in _envolver(draw, composicion.upper(), f_comp, ANCHO - 16):
            y += _centrado(draw, y, ln, f_comp) + 6
    y += 26   # aire (sin filetes)

    # ── Bloque legal (Arial Bold ≈ Segoe Semibold) ──
    for ln in ("MADE IN COLOMBIA", "HECHO POR DIRTY JEANS",
               "NIT 901680460-1", "SIC 1036844755"):
        y += _centrado(draw, y, ln, f_legal) + 5
    y += 26

    # ── Cuidados EN / ES (Arial) ──
    for ln in ("MACHINE WASH WARM", "NO BLEACH", "TUMBLE DRY LOW", "COOL IRON"):
        y += _centrado(draw, y, ln, f_care) + 6
    y += 16
    for ln in ("LAVADORA AGUA TIBIA", "NO BLANQUEADOR",
               "SECADORA BAJA TEMP", "PLANCHA TIBIA"):
        y += _centrado(draw, y, ln, f_care) + 6
    y += 24

    # ── Símbolos de cuidado (PNG oficiales) en fila ──
    nombres = ["lavadora.png", "no_bleach.png", "secadora.png",
               "plancha.png", "no_secadora.png"]
    simbolos = [s for s in (_cargar_simbolo(n, 40) for n in nombres) if s]
    if simbolos:
        sep = 8
        total = sum(s.size[0] for s in simbolos) + sep * (len(simbolos) - 1)
        x = max(4, (ANCHO - total) // 2)
        alto_max = max(s.size[1] for s in simbolos)
        for s in simbolos:
            img.paste(s, (x, y + (alto_max - s.size[1]) // 2))
            x += s.size[0] + sep
        y += alto_max

    y += MARGEN_COSTURA
    recorte = img.crop((0, 0, ANCHO, y))
    return _paleta_1bit(recorte)


def tspl_etiqueta(codigo: str, composicion: str, copias: int = 1,
                  cortar: bool = True) -> bytes:
    """Trabajo TSPL completo con la etiqueta como BITMAP + corte por etiqueta."""
    img = render_etiqueta(codigo, composicion)
    w, h = img.size
    ancho_bytes = (w + 7) // 8
    # PIL '1': bit 1 = blanco, 0 = negro → coincide con TSPL BITMAP mode 0.
    datos = img.tobytes()
    # Largo FÍSICO fijo de la etiqueta = 130 mm (Sebastián 2026-07-23): el
    # corte cae siempre en el borde de la etiqueta, no ajustado al contenido.
    cab = (f"SIZE 27.5 mm,130 mm\r\nGAP 0,0\r\nDIRECTION 0\r\n"
           f"DENSITY 12\r\nSET CUTTER {1 if cortar else 0}\r\nCLS\r\n").encode()
    bitmap = f"BITMAP 0,0,{ancho_bytes},{h},0,".encode() + datos + b"\r\n"
    pie = f"PRINT {max(1, copias)},1\r\n".encode()
    return cab + bitmap + pie
