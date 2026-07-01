"""
backend.services.remision_ocr
─────────────────────────────
Lee la imagen/PDF de la remisión que envía la textilera (Primatela, etc.),
la manda a Claude con visión y devuelve JSON estructurado listo para
prellenar el formulario de ingreso de tela.

Uso:
    from backend.services.remision_ocr import extraer_remision
    data = extraer_remision(bytes_del_archivo, mime_type="application/pdf")
    # → {"textilera": "PRIMATELA SAS", "rollos": [...], ...}
"""
from __future__ import annotations

import base64
import io
import json
import os
from typing import Optional

import anthropic


# Haiku 4.5 con visión — 3-5× más rápido que Sonnet, precisión suficiente
# para remisiones de textilera (tablas simples de una página).
MODELO = "claude-haiku-4-5-20251001"
MAX_TOKENS = 3000
MAX_PAGINAS_PDF = 8   # cortamos ahí para no reventar tokens; suficiente para remisiones típicas
MAX_LADO_PX = 1568    # Anthropic recomienda ≤1568px lado largo para visión (más rápido, sin pérdida)

SYSTEM_PROMPT = """\
Eres un asistente experto en leer remisiones y órdenes de despacho de textileras \
colombianas (Primatela, Fabricato, Coltejer, etc.). Recibes una o más imágenes \
de una remisión y debes extraer los datos estructurados en JSON estricto.

Devuelve EXACTAMENTE este esquema (sin texto extra, solo JSON):
{
  "textilera": "NOMBRE COMPLETO EN MAYÚSCULAS (ej. PRIMATELA SAS)",
  "nit_textilera": "NIT o null",
  "numero_documento": "número de remisión/factura/orden despacho",
  "tipo_documento": "remision | factura | lista_empaque",
  "fecha": "YYYY-MM-DD",
  "orden_compra": "OC del cliente o null",
  "observaciones": "notas relevantes o null",
  "rollos": [
    {
      "numero_rollo": "número o etiqueta del rollo según la textilera",
      "lote_fabrica": "lote de fábrica o partida (si aparece)",
      "tono": "tono/matiz del color (Ej. INDIGO 03, TONO A, etc.)",
      "referencia_tela": "referencia interna de la tela (ej. SANDDENIM 12OZ)",
      "descripcion_tela": "descripción completa de la tela (composición + peso si está)",
      "costo_metro": 12800.0,
      "metros_inicial": 55.0
    }
  ]
}

Reglas de extracción:
- Cada fila de la tabla de rollos = un elemento en "rollos". No inventes rollos.
- "metros_inicial" es OBLIGATORIO y debe ser > 0. Si no lo ves, pon 0 y déjalo para revisión humana.
- "descripcion_tela" es OBLIGATORIO. Si sale en varias columnas (composición + gramaje), únelas.
- Números con coma decimal ("55,3") convertir a punto ("55.3").
- Si un campo no aparece, usa null (no inventes).
- Si son varias páginas de la misma remisión, junta TODOS los rollos en un solo array.
- Fechas en español ("15 de marzo de 2026") convertir a formato ISO YYYY-MM-DD.
"""


def _redimensionar(pil_img, max_lado: int = MAX_LADO_PX):
    """Redimensiona PIL image manteniendo aspecto — lado largo ≤ max_lado.
    Fotos de celular vienen a 3000-4000px; bajarlas a 1568px acelera 2× sin perder OCR.
    """
    w, h = pil_img.size
    lado = max(w, h)
    if lado <= max_lado:
        return pil_img
    factor = max_lado / lado
    nw, nh = int(w * factor), int(h * factor)
    from PIL import Image
    return pil_img.resize((nw, nh), Image.LANCZOS)


def _pdf_a_imagenes(pdf_bytes: bytes, max_paginas: int = MAX_PAGINAS_PDF) -> list[bytes]:
    """Convierte PDF a lista de JPEG (bytes) — una por página, ya redimensionadas."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_bytes)
    imagenes = []
    total = min(len(pdf), max_paginas)
    for i in range(total):
        page = pdf[i]
        # Scale 1.5 ~ 108 DPI (suficiente porque luego redimensionamos)
        pil_img = page.render(scale=1.5).to_pil().convert("RGB")
        pil_img = _redimensionar(pil_img, MAX_LADO_PX)
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=85, optimize=True)
        imagenes.append(buf.getvalue())
    pdf.close()
    return imagenes


def _imagen_a_jpeg_optimizada(img_bytes: bytes) -> bytes:
    """Toma una foto (JPG/PNG/WEBP), la abre, la redimensiona y la re-exporta como JPEG.
    Esto convierte una foto de 4MB en ~300KB — 10× menos tokens, muchísimo más rápido.
    """
    from PIL import Image
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    im = _redimensionar(im, MAX_LADO_PX)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


def _preparar_contenido_imagenes(archivos: list[tuple[bytes, str]]) -> list[dict]:
    """Convierte imágenes (bytes + mime) al formato de content-blocks de Anthropic."""
    bloques: list[dict] = []
    for img_bytes, mime in archivos:
        bloques.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,
                "data": base64.standard_b64encode(img_bytes).decode(),
            },
        })
    return bloques


def _limpiar_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:].strip()
        raw = raw.rsplit("```", 1)[0].strip()
    return raw


def extraer_remision(archivo_bytes: bytes, mime_type: str) -> dict:
    """Extrae la remisión desde bytes de un PDF o imagen.

    Returns: {"ok": True, "data": {...}} o {"ok": False, "error": "..."}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY no configurada"}

    # Normalizar el input a lista de (bytes, mime_type) de imágenes PNG/JPG
    if mime_type == "application/pdf":
        try:
            paginas = _pdf_a_imagenes(archivo_bytes)
        except Exception as e:
            return {"ok": False, "error": f"No se pudo abrir el PDF: {e}"}
        if not paginas:
            return {"ok": False, "error": "El PDF está vacío"}
        archivos = [(b, "image/jpeg") for b in paginas]
    elif mime_type in ("image/jpeg", "image/jpg", "image/png", "image/webp"):
        # Redimensionar + re-comprimir como JPEG optimizado antes de mandar a Claude.
        # Foto de celular 4MB → ~300KB, 3-4× más rápido.
        try:
            optimizada = _imagen_a_jpeg_optimizada(archivo_bytes)
        except Exception as e:
            return {"ok": False, "error": f"No se pudo procesar la imagen: {e}"}
        archivos = [(optimizada, "image/jpeg")]
    else:
        return {"ok": False, "error": f"Tipo no soportado: {mime_type}. Sube PDF/JPG/PNG."}

    try:
        client = anthropic.Anthropic(api_key=api_key)
        contenido = _preparar_contenido_imagenes(archivos)
        contenido.append({
            "type": "text",
            "text": "Extrae la remisión completa en el JSON del schema. Solo JSON, sin texto extra.",
        })
        resp = client.messages.create(
            model=MODELO,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": contenido}],
        )
        raw = resp.content[0].text
        raw = _limpiar_json(raw)
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"IA devolvió JSON inválido: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Error IA: {str(e)[:200]}"}

    # Validaciones mínimas
    rollos = data.get("rollos") or []
    if not isinstance(rollos, list) or not rollos:
        return {"ok": False, "error": "La IA no encontró rollos en el documento"}

    # Normalizar tipo_documento a los valores que acepta el backend
    tipo = (data.get("tipo_documento") or "remision").lower()
    if tipo not in ("remision", "factura", "lista_empaque"):
        tipo = "remision"
    data["tipo_documento"] = tipo

    return {"ok": True, "data": data, "paginas_procesadas": len(archivos)}
