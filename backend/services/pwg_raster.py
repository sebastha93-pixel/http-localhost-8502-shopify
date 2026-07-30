"""pwg_raster.py — PDF → PWG-Raster, el único formato que imprime la RICOH.

POR QUÉ EXISTE (2026-07-30)
--------------------------
La RICOH M 320F de la red **no interpreta PDF**. Se le preguntó su propia
identificación y solo declara dos lenguajes:

    MFG:RICOH;CMD:JBGRD,URF;MDL:M 320F

JBGRD es el raster propietario de RICOH (lo produce el driver de Windows) y
URF es Apple Raster (lo produce AirPrint). Ni PDF, ni PCL, ni PostScript.

Se probaron cinco caminos con el PDF real de la remisión REM-2026-0010,
midiendo la cola IPP de la impresora (no "parece que sí"):

    PDF crudo al 9100 .......... la impresora no registra nada. DESCARTADO
    PWG-Raster crudo al 9100 ... no registra nada
    URF crudo al 9100 .......... no registra nada
    PDF por IPP :631 ........... crea el job y lo cierra con 0 HOJAS
    PWG-Raster por IPP :631 .... job #518 completado, 1 hoja, sin errores ✓

O sea: el puerto 9100 de esa máquina está muerto para TODO formato, y por IPP
solo sirve el raster. Por eso el agente marcaba "impresa" sin que saliera
papel: mandar los bytes y confirmar son dos pasos, y el primero "tiene éxito"
aunque la hoja no exista nunca.

EL FORMATO NO SE ADIVINÓ. Se tomó el PWG que generó CUPS (el que la impresora
sí imprimió), se decodificó byte a byte hasta consumirlo exacto (69.843 de
69.843) y de ahí salieron los valores de cabecera y la compresión que usa este
módulo. Las térmicas (Honeywell/SAT) NO pasan por acá: esas sí hablan ZPL/TSPL
nativo por el 9100 y siguen igual.
"""
from __future__ import annotations

import logging
import struct

log = logging.getLogger(__name__)

# 600 dpi es la resolución NATIVA de la máquina (lo dice ella en
# pwg-raster-document-resolution-supported), así que no resamplea y el texto
# chico y el QR de la remisión salen lo más nítidos posible. Se probaron en
# físico 200 y 600: las dos imprimen (jobs #521 y #522, 1 hoja, completados).
# Cuesta ~34 MB de RAM al rasterizar la página y deja un archivo de ~460 KB.
# Si alguna vez hay que bajar consumo, 200 dpi está verificado y son ~140 KB.
DPI = 600

# Márgenes no imprimibles de la máquina: 4,24 mm por lado (los reporta ella en
# media-col). En píxeles a 200 dpi son los 33 que puso CUPS.
MARGEN_PULGADAS = 33 / 200

_CABECERA = 1796          # tamaño de cups_page_header2_t
_CSPACE_SGRAY = 18        # CUPS_CSPACE_SW: 0 = negro, 255 = blanco (como PIL "L")


def _cabecera_pagina(ancho: int, alto: int, dpi: int,
                     pagina_pt: tuple[float, float],
                     total_paginas: int) -> bytes:
    """Los 1796 bytes de cabecera, todo big-endian.

    Los valores son los que CUPS escribió en el archivo que la RICOH imprimió;
    van explícitos y con nombre para que se puedan tocar sabiendo qué es cada
    uno, en vez de arrastrar un blob binario copiado.
    """
    h = bytearray(_CABECERA)

    def txt(off: int, s: str) -> None:
        b = s.encode("latin-1")[:63]
        h[off:off + len(b)] = b

    def u32(off: int, v: int) -> None:
        struct.pack_into(">I", h, off, int(v))

    txt(0, "PwgRaster")                       # MediaClass: obligatorio en PWG
    txt(1732, "Letter")                       # cupsPageSizeName

    u32(276, dpi)                             # HWResolution[0]
    u32(280, dpi)                             # HWResolution[1]
    u32(352, int(round(pagina_pt[0])))        # PageSize[0] en puntos
    u32(356, int(round(pagina_pt[1])))        # PageSize[1]
    u32(372, ancho)                           # cupsWidth  (píxeles)
    u32(376, alto)                            # cupsHeight
    u32(384, 8)                               # cupsBitsPerColor
    u32(388, 8)                               # cupsBitsPerPixel
    u32(392, ancho)                           # cupsBytesPerLine (8 bpp, 1 color)
    u32(396, 0)                               # cupsColorOrder = chunked
    u32(400, _CSPACE_SGRAY)                   # cupsColorSpace
    u32(404, 0)                               # cupsCompression
    u32(420, 1)                               # cupsNumColors
    u32(340, 1)                               # NumCopies

    # cupsInteger[]: los campos propios de PWG. Offsets 452 + 4*i.
    m = int(round(MARGEN_PULGADAS * dpi))
    entero = {
        0: total_paginas,      # TotalPageCount
        1: 4,                  # CrossFeedTransform (tal cual lo puso CUPS)
        2: 0,                  # FeedTransform
        3: m,                  # ImageBoxLeft   ─┐ área imprimible, sin los
        4: m,                  # ImageBoxTop     │ márgenes mecánicos de la
        5: ancho - m - 1,      # ImageBoxRight   │ máquina
        6: alto - m - 1,       # ImageBoxBottom ─┘
        7: 0xFFFFFF,           # AlternatePrimary (blanco en sRGB)
    }
    for i, v in entero.items():
        u32(452 + 4 * i, v)
    return bytes(h)


def _comprimir_linea(linea: bytes, ancho: int) -> bytes:
    """Compresión de línea de PWG-Raster (estilo PackBits, 1 byte por píxel):

        0..127   -> repetir el píxel siguiente (n+1) veces
        129..255 -> vienen (257-n) píxeles literales
        128      -> reservado, no se usa

    OJO con el caso de un solo píxel suelto: como literal daría 257-1 = 256 y
    no cabe en un byte, así que se emite con la forma "repetir 1 vez" (byte 0).
    """
    out = bytearray()
    i = 0
    while i < ancho:
        px = linea[i]
        fin = i
        while fin + 1 < ancho and linea[fin + 1] == px and (fin - i + 1) < 128:
            fin += 1
        repetidos = fin - i + 1
        if repetidos >= 2:
            out.append(repetidos - 1)
            out.append(px)
            i += repetidos
            continue
        # Píxeles que no se repiten: se juntan como literales hasta 128, y se
        # corta en cuanto aparece una pareja igual (ahí conviene la otra forma).
        ini = i
        while i < ancho and (i - ini) < 128:
            if i + 1 < ancho and linea[i] == linea[i + 1]:
                break
            i += 1
        n = i - ini
        if n == 1:
            out.append(0)
            out.append(linea[ini])
        else:
            out.append(257 - n)
            out += linea[ini:i]
    return bytes(out)


def _codificar_pagina(px: bytes, ancho: int, alto: int) -> bytes:
    """Líneas comprimidas, agrupando líneas idénticas consecutivas (una hoja de
    remisión es casi toda blanca, así que esto la deja en pocos KB)."""
    out = bytearray()
    y = 0
    while y < alto:
        linea = px[y * ancho:(y + 1) * ancho]
        repite = 0
        while (repite < 255 and y + repite + 1 < alto
               and px[(y + repite + 1) * ancho:(y + repite + 2) * ancho] == linea):
            repite += 1
        out.append(repite)                      # 0 = la línea va una sola vez
        out += _comprimir_linea(linea, ancho)
        y += repite + 1
    return bytes(out)


def pdf_a_pwg(pdf: bytes, *, dpi: int = DPI) -> bytes:
    """Convierte un PDF completo a PWG-Raster listo para mandar por IPP.

    Devuelve los bytes del archivo (magic RaS2 + una cabecera y un bloque de
    raster por página). Lanza excepción si el PDF no se puede rasterizar — el
    llamador NO debe caer al PDF crudo, porque eso es justo lo que la impresora
    tira a la basura en silencio.
    """
    import pypdfium2 as pdfium

    # Mismo uso de pypdfium2 que remision_ocr.py, que ya corre en Railway:
    # bytes crudos y .render(scale=…).to_pil(). La escala de grises se hace con
    # PIL para no depender de un kwarg que cambia entre versiones de la lib.
    doc = pdfium.PdfDocument(pdf)
    try:
        total = len(doc)
        if total == 0:
            raise ValueError("el PDF no tiene páginas")

        partes = [b"RaS2"]
        for n in range(total):
            pagina = doc[n]
            ancho_pt, alto_pt = pagina.get_size()
            img = pagina.render(scale=dpi / 72.0).to_pil().convert("L")
            ancho, alto = img.size
            partes.append(_cabecera_pagina(ancho, alto, dpi,
                                           (ancho_pt, alto_pt), total))
            partes.append(_codificar_pagina(img.tobytes(), ancho, alto))
    finally:
        doc.close()
    salida = b"".join(partes)
    log.info(f"pwg: {total} pág · {dpi} dpi · {len(salida) // 1024} KB")
    return salida
