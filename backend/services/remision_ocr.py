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


# Sonnet 4.5 con visión — mejor precisión que Haiku para tablas OCR densas.
MODELO = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 8000
MAX_PAGINAS_PDF = 8   # cortamos ahí para no reventar tokens; suficiente para remisiones típicas

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
      "serial": "serial/código interno del rollo (si aparece)",
      "lote_fabrica": "lote de fábrica o partida (si aparece)",
      "tono": "tono/matiz del color (Ej. INDIGO 03, TONO A, etc.)",
      "referencia_tela": "referencia interna de la tela (ej. SANDDENIM 12OZ)",
      "descripcion_tela": "descripción completa de la tela (composición + peso si está)",
      "ancho": 1.55,
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


def _pdf_a_imagenes(pdf_bytes: bytes, max_paginas: int = MAX_PAGINAS_PDF) -> list[bytes]:
    """Convierte PDF a lista de imágenes PNG (bytes) — una por página."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_bytes)
    imagenes = []
    total = min(len(pdf), max_paginas)
    for i in range(total):
        page = pdf[i]
        # Scale 2.0 = ~150 DPI, buena calidad para OCR de tablas
        pil_img = page.render(scale=2.0).to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG", optimize=True)
        imagenes.append(buf.getvalue())
    pdf.close()
    return imagenes


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
            paginas_png = _pdf_a_imagenes(archivo_bytes)
        except Exception as e:
            return {"ok": False, "error": f"No se pudo abrir el PDF: {e}"}
        if not paginas_png:
            return {"ok": False, "error": "El PDF está vacío"}
        archivos = [(b, "image/png") for b in paginas_png]
    elif mime_type in ("image/jpeg", "image/jpg", "image/png", "image/webp"):
        # Normalizar jpg → jpeg (Anthropic lo pide así)
        mime_ok = "image/jpeg" if mime_type in ("image/jpg", "image/jpeg") else mime_type
        archivos = [(archivo_bytes, mime_ok)]
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
