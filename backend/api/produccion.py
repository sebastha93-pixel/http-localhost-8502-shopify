"""
backend.api.produccion — Router del módulo Producción.

Prefijo: /api/produccion
Auth: reutiliza core.security (require_role / require_permission).

FASE 1 · Bloque 2: Ingreso + Inventario.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from backend.core.security import (CurrentUser, require_role, require_permission,
                                    require_permission_estricto, tiene_permiso_costos,
                                    require_permission_any, tiene_permiso)
from backend.services import produccion as svc

router = APIRouter(prefix="/api/produccion", tags=["produccion"])


# ═══════════════════════════════════════════════════════════════════════
# Health & debug
# ═══════════════════════════════════════════════════════════════════════

@router.get("/health")
def health(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    return svc.health_check()


@router.get("/consecutivo/{prefijo}")
def consecutivo(
    prefijo: str,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    prefijo = prefijo.upper().strip()
    if prefijo not in ("ING", "ROLLO", "OC", "REM", "RI", "PC"):
        raise HTTPException(400, "prefijo_invalido")
    try:
        # Solo lectura — antes incrementaba el contador con cada GET/refresh.
        return {"ok": True, **svc.peek_consecutivo(prefijo)}
    except Exception as e:
        raise HTTPException(500, f"consecutivo: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════════════════
# INGRESO DE TELA (bodega)
# ═══════════════════════════════════════════════════════════════════════

class RolloIn(BaseModel):
    numero_rollo:     Optional[str] = None
    serial:           Optional[str] = None
    lote_fabrica:     Optional[str] = None
    tono:             Optional[str] = None
    referencia_tela:  Optional[str] = None
    descripcion_tela: str = Field(min_length=1)
    ancho:            Optional[float] = None
    costo_metro:      Optional[float] = None
    metros_inicial:   float = Field(gt=0)


class IngresoIn(BaseModel):
    textilera:        str = Field(min_length=1)
    nit_textilera:    Optional[str] = None
    numero_documento: str = Field(min_length=1)
    tipo_documento:   str = Field(pattern="^(remision|factura|lista_empaque|consulta)$")
    fecha:            str  # YYYY-MM-DD
    orden_compra:     Optional[str] = None
    observaciones:    Optional[str] = None
    rollos:           list[RolloIn] = Field(min_length=1)


@router.post("/ingreso/parse-documento")
async def parse_documento_ingreso(
    file: UploadFile = File(...),
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "modificar")),
) -> dict:
    """OCR/IA: lee remisión (PDF/JPG/PNG) de la textilera y devuelve JSON estructurado
    listo para prellenar el form de ingreso. No guarda nada — el usuario revisa y guarda.
    """
    from backend.services.remision_ocr import extraer_remision
    contenido = await file.read()
    if len(contenido) > 25 * 1024 * 1024:
        raise HTTPException(413, "Archivo muy grande (>25MB)")
    if not contenido:
        raise HTTPException(400, "Archivo vacío")
    mime = (file.content_type or "").lower()
    if not mime:
        # inferir por extensión
        name = (file.filename or "").lower()
        if name.endswith(".pdf"):   mime = "application/pdf"
        elif name.endswith((".jpg", ".jpeg")): mime = "image/jpeg"
        elif name.endswith(".png"): mime = "image/png"
    res = extraer_remision(contenido, mime)
    if not res.get("ok"):
        raise HTTPException(422, res.get("error") or "No se pudo extraer la remisión")
    return res


@router.post("/ingreso")
def crear_ingreso(
    body: IngresoIn,
    user: CurrentUser = Depends(require_permission("produccion_ingreso", "modificar")),
) -> dict:
    """Crea una orden de ingreso completa (cabecera + N rollos + movimientos)."""
    try:
        result = svc.crear_ingreso(
            textilera=body.textilera,
            nit_textilera=body.nit_textilera,
            numero_documento=body.numero_documento,
            tipo_documento=body.tipo_documento,
            fecha=body.fecha,
            orden_compra=body.orden_compra,
            observaciones=body.observaciones,
            rollos=[r.model_dump() for r in body.rollos],
            created_by=user.email,
        )
        return {"ok": True, **result}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"crear_ingreso: {str(e)[:200]}")


@router.patch("/ingreso/{ingreso_id}")
def actualizar_ingreso(
    ingreso_id: str,
    body: dict,
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "modificar")),
) -> dict:
    """Edita la cabecera del ingreso (textilera, documento, fecha, OC, notas)."""
    try:
        return svc.actualizar_ingreso(ingreso_id, **(body or {}))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"actualizar_ingreso: {str(e)[:200]}")


@router.patch("/ingreso/rollos/{rollo_id}")
def actualizar_rollo_ingreso(
    rollo_id: str,
    body: dict,
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "modificar")),
) -> dict:
    """Corrige un rollo. Metros solo si el rollo está intacto."""
    try:
        return svc.actualizar_rollo_ingreso(rollo_id, **(body or {}))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"actualizar_rollo: {str(e)[:200]}")


@router.delete("/ingreso/{ingreso_id}")
def eliminar_ingreso(
    ingreso_id: str,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Elimina el ingreso completo revirtiendo inventario.
    Requiere autorización de administrador; falla si algún rollo ya se consumió."""
    try:
        return svc.eliminar_ingreso(ingreso_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"eliminar_ingreso: {str(e)[:200]}")


@router.get("/ingreso")
def listar_ingresos(
    textilera: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "ver")),
) -> dict:
    return {"ingresos": svc.listar_ingresos(textilera=textilera, estado=estado, limit=limit)}


@router.get("/ingreso/{ingreso_id}")
def detalle_ingreso(
    ingreso_id: str,
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "ver")),
) -> dict:
    ing = svc.obtener_ingreso(ingreso_id)
    if not ing:
        raise HTTPException(404, "Ingreso no encontrado")
    return ing


# ═══════════════════════════════════════════════════════════════════════
# ROLLOS + INVENTARIO
# ═══════════════════════════════════════════════════════════════════════

@router.get("/rollos")
def listar_rollos(
    tela: Optional[str] = None,
    estado: Optional[str] = None,
    tono: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
    _: CurrentUser = Depends(require_permission_any(("produccion_ingreso", "produccion_cortador"), "ver")),
) -> dict:
    return {"rollos": svc.listar_rollos(tela=tela, estado=estado, tono=tono, limit=limit)}


@router.get("/rollos/{rollo_id}")
def detalle_rollo(
    rollo_id: str,
    _: CurrentUser = Depends(require_permission_any(("produccion_ingreso", "produccion_cortador"), "ver")),
) -> dict:
    r = svc.obtener_rollo(rollo_id)
    if not r:
        raise HTTPException(404, "Rollo no encontrado")
    return r


@router.get("/rollos/barcode/{barcode}")
def rollo_por_barcode(
    barcode: str,
    _: CurrentUser = Depends(require_permission_any(("produccion_ingreso", "produccion_cortador"), "ver")),
) -> dict:
    r = svc.obtener_rollo_por_barcode(barcode)
    if not r:
        raise HTTPException(404, "Rollo no encontrado")
    return r


@router.get("/inventario/resumen")
def inventario_resumen(
    user: CurrentUser = Depends(require_permission_any(("produccion_ingreso", "produccion_cortador"), "ver")),
) -> dict:
    resumen = svc.inventario_resumen()
    # Los valores de compra son costos — solo produccion_costos los ve.
    if not tiene_permiso_costos(user):
        resumen = [{k: v for k, v in r.items() if k != "valor_estimado"} for r in resumen]
    return {"resumen": resumen}


# ═══════════════════════════════════════════════════════════════════════
# ETIQUETA (PDF Zebra 10×10 con Code128)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/rollos/{rollo_id}/etiqueta")
def etiqueta_rollo(
    rollo_id: str,
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "ver")),
):
    """Genera PDF de etiqueta 10×10 cm con barcode Code128.
    Compatible con impresoras Zebra en modo raster (PDF).
    """
    r = svc.obtener_rollo(rollo_id)
    if not r:
        raise HTTPException(404, "Rollo no encontrado")
    try:
        pdf = _generar_etiqueta_pdf(r)
    except Exception as e:
        raise HTTPException(500, f"etiqueta: {str(e)[:200]}")
    filename = f"etiqueta_{r['codigo_interno']}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _dibujar_etiqueta(c, W, H, rollo: dict) -> None:
    """Dibuja UNA etiqueta 10×10 en el canvas (página actual)."""
    from reportlab.lib.pagesizes import mm
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF

    # Header: código interno
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(W / 2, H - 9 * mm, rollo["codigo_interno"])

    # QR grande y centrado — codifica el barcode (mismo valor que antes)
    qr_size = 42 * mm
    qr = QrCodeWidget(rollo["barcode"])
    b = qr.getBounds()
    escala = qr_size / max(b[2] - b[0], b[3] - b[1])
    d = Drawing(qr_size, qr_size,
                transform=[escala, 0, 0, escala, -b[0] * escala, -b[1] * escala])
    d.add(qr)
    renderPDF.draw(d, c, (W - qr_size) / 2, H - 12 * mm - qr_size)

    # Barcode legible bajo el QR (por si hay que digitarlo a mano)
    c.setFont("Helvetica", 8)
    c.drawCentredString(W / 2, H - 14 * mm - qr_size, rollo["barcode"])

    # Datos
    c.setFont("Helvetica-Bold", 11)
    y = H - 22 * mm - qr_size
    c.drawCentredString(W / 2, y, (rollo.get("descripcion_tela") or "—").upper())
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    tono = rollo.get("tono") or "—"
    ancho = rollo.get("ancho") or "—"
    metros = rollo.get("metros_inicial") or 0
    lote = rollo.get("lote_fabrica") or "—"
    c.drawCentredString(W / 2, y, f"Tono: {tono}   ·   Ancho: {ancho} cm")
    y -= 5 * mm
    c.drawCentredString(W / 2, y, f"Metros: {metros}   ·   Lote: {lote}")
    y -= 5 * mm
    fecha = rollo.get("fecha_ingreso") or ""
    c.drawCentredString(W / 2, y, f"Ingreso: {fecha}")

    # Footer marca
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(W / 2, 5 * mm, "MALE'DENIM · Rollo de tela")


def _generar_etiquetas_pdf(rollos: list[dict]) -> bytes:
    """PDF con UNA PÁGINA POR ROLLO — cada etiqueta con su propia info.
    (El bug anterior: 'imprimir todas' generaba una sola etiqueta.)"""
    from io import BytesIO
    from reportlab.lib.pagesizes import mm
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    W, H = 100 * mm, 100 * mm
    c = canvas.Canvas(buf, pagesize=(W, H))
    for rollo in rollos:
        _dibujar_etiqueta(c, W, H, rollo)
        c.showPage()   # ← página nueva por rollo
    c.save()
    return buf.getvalue()


def _generar_etiqueta_pdf(rollo: dict) -> bytes:
    """Etiqueta individual (compat)."""
    return _generar_etiquetas_pdf([rollo])


class EtiquetasLoteBody(BaseModel):
    rollo_ids: list[str] = Field(min_length=1, max_length=200)


@router.post("/rollos/etiquetas")
def etiquetas_lote(
    body: EtiquetasLoteBody,
    _: CurrentUser = Depends(require_permission_any(("produccion_ingreso", "produccion_cortador"), "ver")),
):
    """PDF con las etiquetas de los rollos seleccionados — una página por rollo."""
    rollos = []
    for rid in body.rollo_ids:
        r = svc.obtener_rollo(rid)
        if r:
            rollos.append(r)
    if not rollos:
        raise HTTPException(404, "Ningún rollo encontrado")
    try:
        pdf = _generar_etiquetas_pdf(rollos)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"etiquetas: {str(e)[:200]}")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="etiquetas_{len(rollos)}_rollos.pdf"'},
    )


# ═══════════════════════════════════════════════════════════════════════
# AJUSTE MANUAL DE STOCK
# ═══════════════════════════════════════════════════════════════════════

class AjusteIn(BaseModel):
    metros_delta: float
    nota:         str = Field(min_length=3)


@router.post("/rollos/{rollo_id}/ajuste")
def ajuste_stock(
    rollo_id: str,
    body: AjusteIn,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Ajuste manual de stock — solo admin. metros_delta puede ser negativo."""
    try:
        return svc.ajustar_stock(
            rollo_id=rollo_id,
            metros_delta=body.metros_delta,
            nota=body.nota,
            usuario=user.email,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"ajuste: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════════════════
# PRECOSTEO
# ═══════════════════════════════════════════════════════════════════════

class PrecosteoItemIn(BaseModel):
    categoria:      str = Field(min_length=1)
    item:           str = Field(min_length=1)
    valor_unitario: float = Field(ge=0)
    cantidad:       float = Field(gt=0)
    iva:            float = Field(ge=0, default=0)


class PrecosteoIn(BaseModel):
    codigo_referencia: str = Field(min_length=1)
    nombre:            str = Field(min_length=1)
    tela:              Optional[str] = None
    color:             Optional[str] = None
    iva_pct:           float = 19
    margen:            float = 0
    items:             list[PrecosteoItemIn] = []
    es_muestra_diseno: bool = False


class PrecosteoUpdate(BaseModel):
    nombre:  Optional[str] = None
    codigo_referencia: Optional[str] = None
    tela:    Optional[str] = None
    color:   Optional[str] = None
    iva_pct: Optional[float] = None
    margen:  Optional[float] = None
    items:   Optional[list[PrecosteoItemIn]] = None
    es_muestra_diseno: Optional[bool] = None


@router.get("/precosteo/categorias")
def categorias_precosteo(_: CurrentUser = Depends(require_permission_estricto("produccion_costos", "ver"))) -> dict:
    return {"categorias": list(svc.CATEGORIAS_PRECOSTEO)}


@router.post("/precosteo")
def crear_precosteo(
    body: PrecosteoIn,
    user: CurrentUser = Depends(require_permission_estricto("produccion_costos", "modificar")),
) -> dict:
    try:
        return svc.crear_precosteo(
            codigo_referencia=body.codigo_referencia,
            nombre=body.nombre,
            tela=body.tela or "",
            color=body.color or "",
            iva_pct=body.iva_pct,
            margen=body.margen,
            items=[i.model_dump() for i in body.items],
            created_by=user.email,
            es_muestra_diseno=body.es_muestra_diseno,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"crear_precosteo: {str(e)[:200]}")


@router.get("/precosteo")
def listar_precosteos(
    estado: Optional[str] = None,
    tela: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    disponibles_para_corte: bool = False,
    _: CurrentUser = Depends(require_permission_estricto("produccion_costos", "ver")),
) -> dict:
    return {"precosteos": svc.listar_precosteos(
        estado=estado, tela=tela, limit=limit,
        disponibles_para_corte=disponibles_para_corte,
    )}


@router.get("/precosteo/{precosteo_id}")
def detalle_precosteo(
    precosteo_id: str,
    _: CurrentUser = Depends(require_permission_estricto("produccion_costos", "ver")),
) -> dict:
    p = svc.obtener_precosteo(precosteo_id)
    if not p:
        raise HTTPException(404, "no_encontrado")
    return p


@router.patch("/precosteo/{precosteo_id}")
def actualizar_precosteo(
    precosteo_id: str,
    body: PrecosteoUpdate,
    user: CurrentUser = Depends(require_permission_estricto("produccion_costos", "modificar")),
) -> dict:
    try:
        return svc.actualizar_precosteo(
            precosteo_id,
            nombre=body.nombre,
            codigo_referencia=body.codigo_referencia,
            tela=body.tela,
            color=body.color,
            iva_pct=body.iva_pct,
            margen=body.margen,
            items=[i.model_dump() for i in body.items] if body.items is not None else None,
            es_muestra_diseno=body.es_muestra_diseno,
            usuario_id=user.id,
        )
    except ValueError as e:
        if str(e) == "precosteo_bloqueado":
            raise HTTPException(403, "Este producto ya está autorizado. Solo quien puede autorizar precosteos (Sebastián o María Alejandra) puede editarlo.")
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"actualizar: {str(e)[:200]}")


@router.post("/precosteo/{precosteo_id}/duplicar")
def duplicar_precosteo(
    precosteo_id: str,
    user: CurrentUser = Depends(require_permission_estricto("produccion_costos", "modificar")),
) -> dict:
    """Copia un precosteo (borrador o autorizado) a un NUEVO borrador editable.
    Para reprogramaciones o referencias parecidas. No modifica el original."""
    try:
        return svc.duplicar_precosteo(precosteo_id, created_by=user.email)
    except ValueError as e:
        if str(e) == "no_encontrado":
            raise HTTPException(404, "Precosteo no encontrado")
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"duplicar: {str(e)[:200]}")


@router.post("/precosteo/{precosteo_id}/firmar")
def firmar_precosteo(
    precosteo_id: str,
    user: CurrentUser = Depends(require_permission_estricto("produccion_costos", "modificar")),
) -> dict:
    """Firma y bloquea. Requiere flag `puede_autorizar_precosteo` en usuarios."""
    try:
        return svc.firmar_precosteo(precosteo_id, usuario_id=user.id)
    except ValueError as e:
        # sin_permiso, ya_bloqueado, no_encontrado → 403 vs 400 vs 404
        msg = str(e)
        if msg == "sin_permiso_autorizar_precosteo":
            raise HTTPException(403, "No tienes permiso para autorizar precosteo. Pide a un admin activar el flag.")
        if msg == "no_encontrado":
            raise HTTPException(404, "Precosteo no encontrado")
        raise HTTPException(400, msg)


@router.delete("/precosteo/{precosteo_id}")
def eliminar_precosteo(
    precosteo_id: str,
    _: CurrentUser = Depends(require_permission_estricto("produccion_costos", "borrar")),
) -> dict:
    try:
        svc.eliminar_precosteo(precosteo_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/precosteo/{precosteo_id}/foto")
async def subir_foto(
    precosteo_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission_estricto("produccion_costos", "modificar")),
) -> dict:
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "imagen_mayor_a_5MB")
    try:
        url = svc.subir_foto_precosteo(
            precosteo_id,
            file_bytes=content,
            filename=file.filename or "foto.jpg",
            content_type=file.content_type or "image/jpeg",
            usuario_id=user.id,
        )
        return {"ok": True, "foto_url": url}
    except ValueError as e:
        if str(e) == "precosteo_bloqueado":
            raise HTTPException(403, "Este producto ya está autorizado. Solo Sebastián o María Alejandra pueden cambiar la foto.")
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"foto: {str(e)[:200]}")


# Bloque 4 — Orden de Corte + cierre
# Bloque 5 — Informe teórico vs real
# Bloque 6 — Remisiones + Insumos


# ═══════════════════════════════════════════════════════════════════════
# BLOQUE 4 — ORDEN DE CORTE
# ═══════════════════════════════════════════════════════════════════════

class CorteReferenciaIn(BaseModel):
    referencia_id:       str
    curva_trazo:         dict = Field(default_factory=dict)
    cantidad_programada: Optional[int] = None
    promedio_tecnico:    Optional[float] = None


class CrearCorteBody(BaseModel):
    # Legacy (una sola referencia) — se sigue aceptando:
    referencia_id:         Optional[str] = None
    curva_trazo:           dict = Field(default_factory=dict)
    cantidad_programada:   Optional[int] = None
    promedio_tecnico:      Optional[float] = None
    # Nuevo: varias referencias en un mismo tendido.
    referencias:           Optional[list[CorteReferenciaIn]] = None
    num_capas:             Optional[int] = None   # capas del tendido (manual)
    largo_trazo:           float = Field(gt=0)
    responsable:           Optional[str] = None
    fecha_envio:           Optional[str] = None
    indicaciones:          Optional[str] = None
    destinatarios_correo:  list[str] = Field(default_factory=list)
    trazos_url:            Optional[str] = None


class PistolearRolloBody(BaseModel):
    barcode:         str = Field(min_length=1)
    metros_reservar: float = Field(gt=0)


class CerrarCorteBody(BaseModel):
    consumo_real_cortador: float = Field(gt=0)
    merma_tipo:        Optional[str] = None
    merma_valor:       Optional[float] = None
    # Informe del cortador
    referencia_lote:   Optional[str] = None
    capas_real:        Optional[int] = None
    promedio_real:     Optional[float] = None
    unidades_cortadas: Optional[dict] = None
    unidades_por_referencia: Optional[dict] = None  # {ref_id: {talla: qty}} — cierre por referencia
    retazos_cantidad:  Optional[int] = None
    espigas_metros:    Optional[dict] = None   # {"4": 1.2, "6-16": 2.4, ...} m extendidos
    retazos_metros:    Optional[float] = None  # retazos medidos en METROS
    fecha_entrega:     Optional[str] = None
    precio_corte:      Optional[float] = None


class AutorizarCorteBody(BaseModel):
    destinatarios:  Optional[list[str]] = None
    mensaje_extra:  Optional[str] = None


@router.post("/corte")
def crear_corte(
    body: CrearCorteBody,
    user: CurrentUser = Depends(require_permission("produccion_corte", "modificar")),
) -> dict:
    try:
        oc = svc.crear_orden_corte(
            referencia_id=body.referencia_id,
            largo_trazo=body.largo_trazo,
            curva_trazo=body.curva_trazo,
            cantidad_programada=body.cantidad_programada,
            promedio_tecnico=body.promedio_tecnico,
            num_capas=body.num_capas,
            referencias=[r.model_dump() for r in body.referencias] if body.referencias else None,
            responsable=body.responsable,
            fecha_envio=body.fecha_envio,
            indicaciones=body.indicaciones,
            destinatarios_correo=body.destinatarios_correo,
            trazos_url=body.trazos_url,
            created_by=user.email,
        )
        return {"ok": True, "orden_corte": oc}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"crear_corte: {str(e)[:200]}")


@router.post("/corte/{oc_id}/autorizar")
def autorizar_corte(
    oc_id: str,
    body: AutorizarCorteBody,
    user: CurrentUser = Depends(require_permission("produccion_corte", "modificar")),
) -> dict:
    try:
        oc = svc.autorizar_orden_corte(
            oc_id,
            destinatarios=body.destinatarios,
            mensaje_extra=body.mensaje_extra,
            usuario=user.email,
        )
        return {"ok": True, **oc}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"autorizar_corte: {str(e)[:200]}")


@router.post("/corte/{oc_id}/trazos")
async def subir_trazos_corte(
    oc_id: str,
    files: List[UploadFile] = File(...),
    _: CurrentUser = Depends(require_permission("produccion_corte", "modificar")),
) -> dict:
    """Sube 1..N archivos de trazo/molde (Optitex, PDF, imagen). Máx 10 por corte."""
    archivos = []
    for f in files:
        contenido = await f.read()
        if len(contenido) > 15 * 1024 * 1024:
            raise HTTPException(413, f"{f.filename}: archivo_mayor_a_15MB")
        if not contenido:
            continue
        archivos.append({
            "file_bytes": contenido,
            "filename": f.filename or "trazo.pdf",
            "content_type": f.content_type or "application/octet-stream",
        })
    if not archivos:
        raise HTTPException(400, "sin_archivos")
    try:
        lista = svc.subir_trazos_corte(oc_id, archivos=archivos)
        return {"ok": True, "trazos": lista}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"trazos: {str(e)[:200]}")


@router.delete("/corte/{oc_id}/trazos")
def eliminar_trazo_corte(
    oc_id: str,
    url: str = Query(..., description="URL del trazo a eliminar"),
    _: CurrentUser = Depends(require_permission("produccion_corte", "modificar")),
) -> dict:
    try:
        lista = svc.eliminar_trazo_corte(oc_id, url)
        return {"ok": True, "trazos": lista}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"eliminar_trazo: {str(e)[:200]}")


def _es_solo_cortador(user: CurrentUser) -> bool:
    """Cortador puro: tiene permiso de cortador pero NO el módulo completo."""
    return (tiene_permiso(user, "produccion_cortador", "ver")
            and not tiene_permiso(user, "produccion_corte", "ver")
            and user.rol != "admin")


def _corte_es_del_cortador(oc: dict, user: CurrentUser) -> bool:
    """El corte le pertenece si el responsable coincide con su nombre."""
    resp = (oc.get("responsable") or "").strip().upper()
    nombre = (user.nombre or "").strip().upper()
    if not resp or not nombre:
        return False
    return resp in nombre or nombre in resp


@router.get("/corte")
def listar_cortes(
    estado: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    sin_remision: Optional[str] = None,  # 'confeccion' | 'terminacion'
    marcar_remisiones: bool = False,
    user: CurrentUser = Depends(require_permission_any(("produccion_corte", "produccion_cortador"), "ver")),
) -> dict:
    ordenes = svc.listar_ordenes_corte(
        estado=estado, limit=limit, sin_remision=sin_remision,
        marcar_remisiones=marcar_remisiones)
    # Cortador puro: SOLO ve los cortes donde él es el responsable
    if _es_solo_cortador(user):
        ordenes = [oc for oc in ordenes if _corte_es_del_cortador(oc, user)]
    return {"ordenes": ordenes}


@router.get("/usuarios-correo")
def usuarios_correo(
    _: CurrentUser = Depends(require_permission("produccion_corte", "ver")),
) -> dict:
    """Lista liviana de usuarios (nombre + email + es_cortador) para elegir
    destinatarios del correo de la orden de corte. Solo diseñador/manager."""
    from backend.services import usuarios as usr
    out = []
    for u in usr.listar():
        email = (u.get("email") or "").strip()
        if not email or not u.get("activo"):
            continue
        perms = u.get("permisos") or {}
        es_cortador = bool(perms.get("produccion_cortador")) and not perms.get("produccion_corte")
        out.append({"nombre": u.get("nombre") or email, "email": email, "es_cortador": es_cortador})
    out.sort(key=lambda x: (not x["es_cortador"], (x["nombre"] or "").upper()))
    return {"usuarios": out}


@router.get("/corte/{oc_id}")
def detalle_corte(
    oc_id: str,
    user: CurrentUser = Depends(require_permission_any(("produccion_corte", "produccion_cortador"), "ver")),
) -> dict:
    oc = svc.obtener_orden_corte(oc_id)
    if not oc:
        raise HTTPException(404, "Orden de corte no encontrada")
    if _es_solo_cortador(user) and not _corte_es_del_cortador(oc, user):
        raise HTTPException(403, "Este corte no está asignado a ti")
    return oc


@router.post("/corte/{oc_id}/pistolear")
def pistolear_rollo(
    oc_id: str,
    body: PistolearRolloBody,
    _: CurrentUser = Depends(require_permission("produccion_corte", "modificar")),
) -> dict:
    try:
        oc = svc.asignar_rollo_a_corte(
            oc_id=oc_id,
            barcode=body.barcode,
            metros_reservar=body.metros_reservar,
        )
        return {"ok": True, "orden_corte": oc}
    except ValueError as e:
        msg = {
            "codigo_ambiguo": "Ese número de rollo lo tienen varios rollos. Escanea el código interno (ROLLO-…) para identificar el correcto.",
            "rollo_no_encontrado": "Rollo no encontrado. Verifica el código interno o el número del rollo.",
        }.get(str(e), str(e))
        raise HTTPException(400, msg)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"pistolear: {str(e)[:200]}")


@router.post("/corte/{oc_id}/verificar-rollo")
def verificar_rollo_corte(
    oc_id: str,
    body: dict,
    _: CurrentUser = Depends(require_permission_any(("produccion_corte", "produccion_cortador"), "ver")),
) -> dict:
    """Cortador: escanea un rollo para confirmar que está asignado a este corte. No modifica nada."""
    try:
        return svc.verificar_rollo_corte(oc_id, (body or {}).get("barcode") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"verificar_rollo: {str(e)[:200]}")


@router.delete("/corte/{oc_id}/rollo/{rollo_id}")
def quitar_rollo(
    oc_id: str,
    rollo_id: str,
    _: CurrentUser = Depends(require_permission("produccion_corte", "modificar")),
) -> dict:
    try:
        oc = svc.quitar_rollo_de_corte(oc_id=oc_id, rollo_id=rollo_id)
        return {"ok": True, "orden_corte": oc}
    except ValueError as e:
        raise HTTPException(400, str(e))


class AutoAsignarBody(BaseModel):
    tono: Optional[str] = None


@router.post("/corte/{oc_id}/auto-asignar")
def auto_asignar(
    oc_id: str,
    body: AutoAsignarBody,
    _: CurrentUser = Depends(require_permission("produccion_corte", "modificar")),
) -> dict:
    """Auto-selecciona rollos disponibles de la misma TELA + TONO y los agrega
    hasta cubrir los metros teóricos. Evita mezclar tonos por error humano.
    """
    try:
        res = svc.auto_asignar_rollos_por_tono(oc_id=oc_id, tono=body.tono)
        oc = svc.obtener_orden_corte(oc_id)
        return {"ok": res["ok"], "resultado": res, "orden_corte": oc}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"auto_asignar: {str(e)[:200]}")


@router.post("/corte/{oc_id}/cerrar")
def cerrar_corte(
    oc_id: str,
    body: CerrarCorteBody,
    user: CurrentUser = Depends(require_permission_any(("produccion_corte", "produccion_cortador"), "modificar")),
) -> dict:
    # Cortador puro: solo puede cerrar SUS cortes asignados
    if _es_solo_cortador(user):
        oc_check = svc.obtener_orden_corte(oc_id)
        if not oc_check or not _corte_es_del_cortador(oc_check, user):
            raise HTTPException(403, "Este corte no está asignado a ti")
    try:
        oc = svc.cerrar_orden_corte(
            oc_id=oc_id,
            consumo_real_cortador=body.consumo_real_cortador,
            merma_tipo=body.merma_tipo,
            merma_valor=body.merma_valor,
            usuario=user.email,
            referencia_lote=body.referencia_lote,
            capas_real=body.capas_real,
            promedio_real=body.promedio_real,
            unidades_cortadas=body.unidades_cortadas,
            unidades_por_referencia=body.unidades_por_referencia,
            retazos_cantidad=body.retazos_cantidad,
            espigas_metros=body.espigas_metros,
            retazos_metros=body.retazos_metros,
            fecha_entrega=body.fecha_entrega,
            precio_corte=body.precio_corte,
        )
        return {"ok": True, "orden_corte": oc}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"cerrar_corte: {str(e)[:200]}")


@router.delete("/corte/{oc_id}")
def eliminar_corte(
    oc_id: str,
    _: CurrentUser = Depends(require_permission("produccion_corte", "borrar")),
) -> dict:
    try:
        svc.eliminar_orden_corte(oc_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ═══════════════════════════════════════════════════════════════════════
# BLOQUE 6A — CONFECCIONISTAS + REMISIONES
# ═══════════════════════════════════════════════════════════════════════

class ConfeccionistaIn(BaseModel):
    nombre:    str = Field(min_length=2)
    telefono:  Optional[str] = None
    direccion: Optional[str] = None
    documento: Optional[str] = None  # cédula/NIT — ancla del cruce Siigo
    tipo:      str = "confeccion"  # 'confeccion' | 'terminacion' | 'lavanderia' | 'otros'


class ConfeccionistaUpdate(BaseModel):
    nombre:    Optional[str] = None
    telefono:  Optional[str] = None
    direccion: Optional[str] = None
    documento: Optional[str] = None
    activo:    Optional[bool] = None
    tipo:      Optional[str] = None


class RemisionIn(BaseModel):
    confeccionista_id: str
    fecha_recogida:    str
    orden_corte_ids:   list[str] = Field(min_length=1)
    tipo:              str = "confeccion"  # 'confeccion' | 'terminacion'


@router.get("/confeccionistas")
def listar_confeccionistas(
    incluir_inactivos: bool = False,
    tipo: Optional[str] = None,
    _: CurrentUser = Depends(require_permission_any(("produccion_proveedores", "produccion_cortador"), "ver")),
) -> dict:
    return {"confeccionistas": svc.listar_confeccionistas(
        incluir_inactivos=incluir_inactivos, tipo=tipo,
    )}


@router.post("/confeccionistas")
def crear_confeccionista(
    body: ConfeccionistaIn,
    _: CurrentUser = Depends(require_permission("produccion_proveedores", "modificar")),
) -> dict:
    try:
        return {"ok": True, "confeccionista": svc.crear_confeccionista(
            nombre=body.nombre, telefono=body.telefono,
            direccion=body.direccion, tipo=body.tipo,
            documento=body.documento,
        )}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"crear_conf: {str(e)[:200]}")


@router.patch("/confeccionistas/{cid}")
def actualizar_confeccionista(
    cid: str,
    body: ConfeccionistaUpdate,
    _: CurrentUser = Depends(require_permission("produccion_proveedores", "modificar")),
) -> dict:
    try:
        campos = body.model_dump(exclude_unset=True)
        return {"ok": True, "confeccionista": svc.actualizar_confeccionista(cid, **campos)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"actualizar_conf: {str(e)[:200]}")


class ResetProduccionBody(BaseModel):
    confirmacion: str  # debe ser exactamente "RESET"


@router.post("/admin/reset-datos")
def reset_datos_produccion(
    body: ResetProduccionBody,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Borra TODOS los datos transaccionales de producción (telas, cortes,
    remisiones, precosteos, insumos, proveedores, consecutivos).
    CONSERVA usuarios. Solo admin + confirmación explícita. IRREVERSIBLE."""
    if body.confirmacion != "RESET":
        raise HTTPException(400, "confirmacion_invalida: escribe RESET")
    try:
        res = svc.reset_datos_produccion()
        # Rastro en auditoría (tabla acciones) — best effort
        try:
            sb = svc._sb()
            if sb is not None:
                sb.table("acciones").insert({
                    "orden": "PRODUCCION",
                    "tipo": "reset_produccion",
                    "descripcion": f"Reset módulo producción: {res.get('borradas')}",
                    "autor": user.email,
                }).execute()
        except Exception:
            pass
        return res
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"reset: {str(e)[:200]}")


@router.get("/mis-despachos")
def mis_despachos(
    user: CurrentUser = Depends(require_permission_any(("produccion_corte", "produccion_cortador"), "ver")),
) -> dict:
    """Control interno del cortador: unidades despachadas por corte.
    El cortador puro solo ve sus propios cortes."""
    rows = svc.despachos_por_corte()
    if _es_solo_cortador(user):
        rows = [r for r in rows if _corte_es_del_cortador(r, user)]
    return {"despachos": rows}


@router.get("/remisiones")
def listar_remisiones(
    estado: Optional[str] = None,
    confeccionista_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    _: CurrentUser = Depends(require_permission("produccion_remisiones", "ver")),
) -> dict:
    return {"remisiones": svc.listar_remisiones(
        estado=estado, confeccionista_id=confeccionista_id, limit=limit,
    )}


@router.post("/remisiones")
def crear_remision(
    body: RemisionIn,
    user: CurrentUser = Depends(require_permission_any(("produccion_remisiones", "produccion_cortador"), "modificar")),
) -> dict:
    # El cortador puro solo genera la remisión CONFECCIONISTA de SUS cortes
    # (después de guardar y confirmar el informe). No puede tocar terminación
    # ni cortes de otros.
    if _es_solo_cortador(user):
        if body.tipo != "confeccion":
            raise HTTPException(403, "El cortador solo genera remisiones de confección.")
        for oc_id in body.orden_corte_ids:
            oc_check = svc.obtener_orden_corte(oc_id)
            if not oc_check or not _corte_es_del_cortador(oc_check, user):
                raise HTTPException(403, "Solo puedes generar remisiones de los cortes asignados a ti.")
    try:
        rem = svc.crear_remision(
            confeccionista_id=body.confeccionista_id,
            fecha_recogida=body.fecha_recogida,
            orden_corte_ids=body.orden_corte_ids,
            created_by=user.email,
            tipo=body.tipo,
        )
        extra: dict = {}
        import os as _os
        modo_agente = _os.environ.get("IMPRESION_AGENTE", "").strip().lower() in (
            "1", "true", "si", "sí", "yes", "on")
        # Impresión de la remisión (corte + insumos):
        #  · modo agente → la remisión ya está en la cola (impresa_at NULL) y el
        #    agente local la imprime en la RICOH por IP. El frontend NO abre el
        #    diálogo del navegador (evita doble impresión).
        #  · sin agente → flujo anterior: email-to-print en terminación, y en
        #    confección el frontend abre el diálogo del navegador.
        if modo_agente:
            extra["impresion"] = "agente"
        elif body.tipo == "terminacion":
            extra["impresion"] = _imprimir_remision(rem)
        if body.tipo == "terminacion":
            try:
                extra["whatsapp"] = svc._notificar_remision_whatsapp(rem)
            except Exception as e:
                import logging as _lg
                _lg.getLogger(__name__).warning(f"[wa] notif terminacion fallo: {e}")
                extra["whatsapp"] = []
        return {"ok": True, "remision": rem, **extra}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"crear_remision: {str(e)[:200]}")


@router.get("/remisiones/{rem_id}")
def detalle_remision(
    rem_id: str,
    _: CurrentUser = Depends(require_permission_any(("produccion_remisiones", "produccion_cortador"), "ver")),
) -> dict:
    rem = svc.obtener_remision(rem_id)
    if not rem:
        raise HTTPException(404, "no_encontrada")
    return rem


@router.post("/remisiones/{rem_id}/recogida")
def marcar_recogida(
    rem_id: str,
    user: CurrentUser = Depends(require_permission_any(("produccion_remisiones", "produccion_cortador"), "modificar")),
) -> dict:
    try:
        return {"ok": True, "remision": svc.marcar_remision_recogida(rem_id, usuario=user.email)}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ═══════════════════════════════════════════════════════════════════════
# INSUMOS REQUERIDOS POR ORDEN DE CORTE (auto desde precosteo)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/corte/{oc_id}/insumos-requeridos")
def insumos_requeridos_corte(
    oc_id: str,
    tipo: Optional[str] = None,  # 'confeccion' | 'terminacion' | None (ambos)
    user: CurrentUser = Depends(require_permission("produccion_corte", "ver")),
) -> dict:
    """Calcula los insumos requeridos multiplicando item.cantidad × cantidad_a_cortar.
    Con `tipo=confeccion` filtra a categoría INSUMO CONFECCION;
    con `tipo=terminacion` filtra a INSUMO TERMINACION.
    Sin `tipo` devuelve ambas.
    Sin permiso `produccion_costos`, los valores $ se OCULTAN (solo cantidades).
    """
    cats: Optional[tuple[str, ...]] = None
    t = (tipo or "").lower().strip()
    if t == "confeccion":
        cats = ("INSUMO CONFECCION",)
    elif t == "terminacion":
        cats = ("INSUMO TERMINACION",)
    try:
        res = svc.calcular_insumos_requeridos_corte(oc_id, categorias=cats)
        if not tiene_permiso_costos(user):
            res.pop("total_costo", None)
            for it in (res.get("items") or []):
                it.pop("valor_unitario", None)
                it.pop("costo_total", None)
        return res
    except ValueError as e:
        raise HTTPException(404 if str(e) == "orden_no_encontrada" else 400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"insumos_requeridos: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════════════════
# HOJA DE RUTA · admin (autenticado)
# ═══════════════════════════════════════════════════════════════════════

class CrearRutaBody(BaseModel):
    orden_corte_id:           str
    confeccionista_id:        str
    precio_confeccion:        Optional[float] = None
    fecha_entrega_confeccion: Optional[str] = None
    remision_id:              Optional[str] = None


class ActualizarRutaBody(BaseModel):
    confeccionista_id:         Optional[str] = None
    terminacion_id:            Optional[str] = None
    lavanderia_id:             Optional[str] = None
    precio_confeccion:         Optional[float] = None
    precio_terminacion:        Optional[float] = None
    fecha_entrega_confeccion:  Optional[str] = None
    remision_lavanderia_url:   Optional[str] = None
    notas:                     Optional[str] = None


class CambiarEtapaBody(BaseModel):
    etapa: str


@router.get("/rutas")
def listar_rutas(
    etapa: Optional[str] = None,
    confeccionista_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    _: CurrentUser = Depends(require_permission("produccion_remisiones", "ver")),
) -> dict:
    return {"rutas": svc.listar_rutas(
        etapa=etapa, confeccionista_id=confeccionista_id, limit=limit
    )}


@router.post("/rutas")
def crear_ruta(
    body: CrearRutaBody,
    user: CurrentUser = Depends(require_permission("produccion_remisiones", "modificar")),
) -> dict:
    try:
        return {"ok": True, "ruta": svc.crear_ruta_lote(
            orden_corte_id=body.orden_corte_id,
            confeccionista_id=body.confeccionista_id,
            precio_confeccion=body.precio_confeccion,
            fecha_entrega_confeccion=body.fecha_entrega_confeccion,
            remision_id=body.remision_id,
            created_by=user.email,
        )}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"crear_ruta: {str(e)[:200]}")


@router.get("/rutas/por-corte/{oc_id}")
def ruta_por_corte(
    oc_id: str,
    _: CurrentUser = Depends(require_permission_any(("produccion_remisiones", "produccion_cortador"), "ver")),
) -> dict:
    r = svc.obtener_ruta_por_corte(oc_id)
    if not r:
        raise HTTPException(404, "no_encontrada")
    return r


@router.patch("/rutas/{ruta_id}")
def actualizar_ruta(
    ruta_id: str,
    body: ActualizarRutaBody,
    _: CurrentUser = Depends(require_permission("produccion_remisiones", "modificar")),
) -> dict:
    try:
        campos = body.model_dump(exclude_unset=True)
        return {"ok": True, "ruta": svc.actualizar_ruta_lote(ruta_id, **campos)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/rutas/{ruta_id}/remision-lavanderia")
async def subir_remision_lavanderia(
    ruta_id: str,
    file: UploadFile = File(...),
    lavanderia_id: Optional[str] = Form(None),
    _: CurrentUser = Depends(require_permission("produccion_remisiones", "modificar")),
) -> dict:
    """Sube la foto/PDF de la remisión de recogida de la lavandería.
    Al subirla, la etapa del lote pasa a 'lavanderia' INMEDIATAMENTE."""
    try:
        data = await file.read()
        if len(data) > 15 * 1024 * 1024:
            raise HTTPException(400, "archivo_muy_grande_max_15mb")
        res = svc.subir_remision_lavanderia(
            ruta_id,
            file_bytes=data,
            filename=file.filename or "remision.pdf",
            content_type=file.content_type or "application/octet-stream",
            lavanderia_id=lavanderia_id or None,
        )
        return {"ok": True, **res}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"remision_lavanderia: {str(e)[:200]}")


@router.post("/rutas/{ruta_id}/etapa")
def cambiar_etapa(
    ruta_id: str,
    body: CambiarEtapaBody,
    _: CurrentUser = Depends(require_permission("produccion_remisiones", "modificar")),
) -> dict:
    try:
        return {"ok": True, "ruta": svc.cambiar_etapa_ruta(ruta_id, body.etapa)}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ═══════════════════════════════════════════════════════════════════════
# HOJA DE RUTA · público (sin auth) — para el link del confeccionista
# ═══════════════════════════════════════════════════════════════════════

publico = APIRouter(prefix="/api/publico", tags=["publico"])


@publico.get("/lote/{token}")
def lote_publico(token: str) -> dict:
    """Vista pública del lote — sin autenticación.
    Solo lo que el confeccionista debe ver: ficha técnica, curva de tallas,
    cantidad total e insumos de CONFECCIÓN con cantidades.
    NO se envía NINGÚN precio (regla de Sebastián 2026-07: el link al
    confeccionista va sin precio), ni valores unitarios de insumos, costos
    totales, ni datos del informe del cortador.
    """
    r = svc.obtener_ruta_por_token(token)
    if not r:
        raise HTTPException(404, "lote_no_encontrado")

    oc = r.get("orden_corte") or {}
    ref = oc.get("referencia") or {}
    conf = r.get("confeccionista") or {}
    total_unidades = 0
    if oc.get("unidades_cortadas"):
        total_unidades = sum(int(v or 0) for v in (oc.get("unidades_cortadas") or {}).values())
    if total_unidades == 0:
        total_unidades = int(oc.get("cantidad_programada") or 0)

    # Insumos: SOLO categoría INSUMO CONFECCION (los de terminación van en
    # una remisión aparte, más adelante en el flujo).
    insumos_publicos: list[dict] = []
    try:
        calc = svc.calcular_insumos_requeridos_corte(
            r["orden_corte_id"],
            categorias=("INSUMO CONFECCION",),
        )
        for it in (calc.get("items") or []):
            # Solo nombre + cantidad total — sin valor unitario ni costo.
            insumos_publicos.append({
                "item":            it.get("item"),
                "total_requerido": it.get("total_requerido"),
            })
    except Exception:
        pass

    return {
        "consecutivo":               oc.get("consecutivo"),
        "referencia_codigo":         ref.get("codigo_referencia"),
        "referencia_nombre":         ref.get("nombre"),
        "tela":                      ref.get("tela"),
        "color":                     ref.get("color"),
        "foto_url":                  ref.get("foto_url"),
        "referencia_lote":           oc.get("referencia_lote"),
        "curva":                     oc.get("curva_trazo"),
        "unidades_cortadas":         oc.get("unidades_cortadas"),
        "total_unidades":            total_unidades,
        "fecha_entrega":             r.get("fecha_entrega_confeccion") or oc.get("fecha_entrega"),
        "confeccionista_nombre":     conf.get("nombre"),
        "etapa":                     r.get("etapa"),
        "aceptado_at":               r.get("aceptado_at"),
        "insumos":                   insumos_publicos,
    }


@publico.post("/lote/{token}/aceptar")
def aceptar_lote_publico(token: str) -> dict:
    """Endpoint público. El confeccionista clickea "Aceptar lote" desde el link.
    Al aceptar, el lote pasa directo a EN CONFECCIÓN (regla de negocio:
    aceptar = ya lo tiene y empieza a trabajar). Estampa ambas fechas.
    """
    r = svc.obtener_ruta_por_token(token)
    if not r:
        raise HTTPException(404, "lote_no_encontrado")
    if r.get("etapa") != "asignado":
        raise HTTPException(400, f"ya_aceptado_o_en_progreso:{r.get('etapa')}")
    try:
        svc.cambiar_etapa_ruta(r["id"], "aceptado")          # estampa aceptado_at
        ruta = svc.cambiar_etapa_ruta(r["id"], "en_confeccion")  # estampa inicio
        return {"ok": True, "ruta": ruta}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Vista pública de TERMINACIÓN — proveedor de terminación
@publico.get("/terminacion/{token}")
def terminacion_publica(token: str) -> dict:
    """Vista para el proveedor de terminación (planchado / empaque / etiqueta).
    Solo lo necesario: ficha técnica + cantidad + insumos de TERMINACIÓN.
    NO se envía precio ni info del confeccionista.
    """
    r = svc.obtener_ruta_por_token_terminacion(token)
    if not r:
        raise HTTPException(404, "lote_no_encontrado")

    oc = r.get("orden_corte") or {}
    ref = oc.get("referencia") or {}
    term = r.get("terminacion") or {}
    total = 0
    if oc.get("unidades_cortadas"):
        total = sum(int(v or 0) for v in (oc.get("unidades_cortadas") or {}).values())
    if total == 0:
        total = int(oc.get("cantidad_programada") or 0)

    insumos_pub: list[dict] = []
    try:
        calc = svc.calcular_insumos_requeridos_corte(
            r["orden_corte_id"],
            categorias=("INSUMO TERMINACION",),
        )
        for it in (calc.get("items") or []):
            insumos_pub.append({
                "item":            it.get("item"),
                "total_requerido": it.get("total_requerido"),
            })
    except Exception:
        pass

    return {
        "consecutivo":       oc.get("consecutivo"),
        "referencia_codigo": ref.get("codigo_referencia"),
        "referencia_nombre": ref.get("nombre"),
        "tela":              ref.get("tela"),
        "color":             ref.get("color"),
        "foto_url":          ref.get("foto_url"),
        "referencia_lote":   oc.get("referencia_lote"),
        "curva":             oc.get("curva_trazo"),
        "unidades_cortadas": oc.get("unidades_cortadas"),
        "total_unidades":    total,
        "fecha_entrega":     oc.get("fecha_entrega"),
        "terminacion_nombre": term.get("nombre"),
        "etapa":             r.get("etapa"),
        "recibido_at":       r.get("terminacion_recibida_at"),
        "insumos":           insumos_pub,
    }


@publico.post("/terminacion/{token}/recibir")
def recibir_terminacion_publica(token: str) -> dict:
    """El proveedor de terminación confirma que ya recibió el lote."""
    r = svc.obtener_ruta_por_token_terminacion(token)
    if not r:
        raise HTTPException(404, "lote_no_encontrado")
    if r.get("etapa") in ("terminacion_recibida", "terminacion_terminada", "despachado"):
        raise HTTPException(400, f"ya_recibido:{r.get('etapa')}")
    try:
        return {"ok": True, "ruta": svc.cambiar_etapa_ruta(r["id"], "terminacion_recibida")}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Notas del confeccionista y del proveedor de terminación (público)
class NotaBody(BaseModel):
    nota: str = Field(min_length=1, max_length=2000)


@publico.post("/lote/{token}/nota")
def guardar_nota_lote(token: str, body: NotaBody) -> dict:
    """El confeccionista deja una nota — se agrega al timeline (no sobrescribe)."""
    r = svc.obtener_ruta_por_token(token)
    if not r:
        raise HTTPException(404, "lote_no_encontrado")
    try:
        svc.crear_nota_ruta(ruta_id=r["id"], actor="confeccionista",
                             mensaje=body.nota,
                             autor=(r.get("confeccionista") or {}).get("nombre"))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        # Fallback si la migración de notas_hoja_ruta aún no corrió → guarda en campo viejo
        try:
            svc.actualizar_ruta_lote(r["id"], nota_confeccionista=body.nota)
            return {"ok": True, "warning": "notas timeline no disponible, guardado en campo legacy"}
        except Exception:
            raise HTTPException(500, f"guardar_nota: {str(e)[:200]}")


@publico.post("/terminacion/{token}/nota")
def guardar_nota_terminacion(token: str, body: NotaBody) -> dict:
    """El proveedor de terminación deja una nota — se agrega al timeline."""
    r = svc.obtener_ruta_por_token_terminacion(token)
    if not r:
        raise HTTPException(404, "lote_no_encontrado")
    try:
        svc.crear_nota_ruta(ruta_id=r["id"], actor="terminacion",
                             mensaje=body.nota,
                             autor=(r.get("terminacion") or {}).get("nombre"))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        try:
            svc.actualizar_ruta_lote(r["id"], nota_terminacion=body.nota)
            return {"ok": True, "warning": "notas timeline no disponible, guardado en campo legacy"}
        except Exception:
            raise HTTPException(500, f"guardar_nota: {str(e)[:200]}")


# ── Admin: listar y agregar notas de una ruta
class NotaAdminBody(BaseModel):
    mensaje: str = Field(min_length=1, max_length=5000)


@router.get("/rutas/{ruta_id}/notas")
def listar_notas_ruta(
    ruta_id: str,
    _: CurrentUser = Depends(require_permission_any(("produccion_remisiones", "produccion_cortador"), "ver")),
) -> dict:
    return {"notas": svc.listar_notas_ruta(ruta_id)}


@router.post("/rutas/{ruta_id}/notas")
def agregar_nota_ruta(
    ruta_id: str,
    body: NotaAdminBody,
    user: CurrentUser = Depends(require_permission_any(("produccion_remisiones", "produccion_cortador"), "modificar")),
) -> dict:
    try:
        return {"ok": True, "nota": svc.crear_nota_ruta(
            ruta_id=ruta_id, actor="admin",
            mensaje=body.mensaje, autor=user.email,
        )}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ═══════════════════════════════════════════════════════════════════════
# TABLERO DE PRODUCCIÓN
# ═══════════════════════════════════════════════════════════════════════

@router.get("/tablero")
def tablero(
    user: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    """KPIs de producción: inventario, eficiencia de corte y ruta de lotes.
    Sin permiso `produccion_costos` se oculta el valor $ del inventario."""
    try:
        res = svc.tablero_produccion()
        if not tiene_permiso_costos(user) and res.get("inventario"):
            res["inventario"]["valor_estimado"] = None
        return res
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"tablero: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════════════════
# CRUCE SIIGO · costeo real (Bloque 5)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/costeo-real")
def costeo_real(
    desde: Optional[str] = None,  # YYYY-MM-DD — por defecto todos los lotes cortados
    _: CurrentUser = Depends(require_permission_estricto("produccion_costos", "ver")),
) -> dict:
    """Cruza lotes cortados vs Documentos Soporte de Siigo (pagos a confección).
    Devuelve comparación teórico vs real + alertas de desviación.
    """
    try:
        return svc.cruce_costeo_siigo(desde=desde)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"costeo_real: {str(e)[:200]}")


@router.get("/alertas")
def alertas_produccion(
    incluir_costeo: bool = True,
    user: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    """Todas las alertas de producción (stock bajo + lotes estancados + cruce Siigo).
    Las alertas de costeo (traen valores $) solo con permiso `produccion_costos`."""
    try:
        return svc.alertas_produccion(
            incluir_costeo=incluir_costeo and tiene_permiso_costos(user))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"alertas: {str(e)[:200]}")


@router.post("/alertas/digest")
def enviar_digest_manual(
    force: bool = False,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Dispara el resumen diario de alertas por correo AHORA (para probar el canal).
    Con force=true envía aunque no haya alertas.
    """
    from backend.core import produccion_scheduler
    try:
        return produccion_scheduler.enviar_digest(force=force)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"digest: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════════════════
# REMISIÓN IMPRIMIBLE (PDF carta con QR)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/remisiones/{rem_id}/pdf")
def remision_pdf(
    rem_id: str,
    _: CurrentUser = Depends(require_permission_any(("produccion_remisiones", "produccion_cortador"), "ver")),
):
    """PDF imprimible de la remisión: cabecera, órdenes, insumos a separar
    (solo cantidades, sin valores) y firmas. QR con el consecutivo."""
    rem = svc.obtener_remision(rem_id)
    if not rem:
        raise HTTPException(404, "Remisión no encontrada")
    try:
        pdf = _generar_remision_pdf(rem)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"remision_pdf: {str(e)[:200]}")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="remision_{rem.get("consecutivo","")}.pdf"'},
    )


# ── Cola de impresión (agente local por IP → RICOH) ──────────────────────
# El agente local corre en un PC de la red de MALE'DENIM: pide las remisiones
# pendientes, baja cada PDF de /remisiones/{id}/pdf y lo manda a la RICOH por
# su IP (puerto 9100). Al terminar marca cada una como impresa.
@router.get("/impresion/pendientes")
def impresion_pendientes(
    _: CurrentUser = Depends(require_permission_any(("produccion_remisiones", "produccion_cortador"), "ver")),
):
    return {"pendientes": svc.remisiones_pendientes_impresion()}


@router.post("/impresion/{rem_id}/impresa")
def impresion_marcar_impresa(
    rem_id: str,
    _: CurrentUser = Depends(require_permission_any(("produccion_remisiones", "produccion_cortador"), "ver")),
):
    return {"ok": svc.marcar_remision_impresa(rem_id)}


@router.post("/impresion/{rem_id}/reimprimir")
def impresion_reimprimir(
    rem_id: str,
    _: CurrentUser = Depends(require_permission("produccion_remisiones", "modificar")),
):
    """Vuelve a encolar la remisión (para reimprimir manualmente)."""
    return {"ok": svc.marcar_remision_reimprimir(rem_id)}


def _generar_remision_pdf(rem: dict) -> bytes:
    """Remisión formato carta. Confección = el proveedor RECOGE;
    terminación = MALE'DENIM DESPACHA. Sin valores $ — es un documento
    de entrega física, no comercial."""
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF

    es_term = (rem.get("tipo") or "confeccion") == "terminacion"
    titulo = "REMISIÓN DE TERMINACIÓN" if es_term else "REMISIÓN DE CONFECCIÓN"
    prov = rem.get("confeccionista") or {}

    buf = BytesIO()
    W, H = letter
    c = canvas.Canvas(buf, pagesize=letter)

    # ── Cabecera ──
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, H - 20 * mm, "MALE'DENIM")
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, H - 25 * mm, "That Fits · Producción")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(W - 45 * mm, H - 18 * mm, titulo)
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(W - 45 * mm, H - 25 * mm, rem.get("consecutivo") or "")

    # QR con el consecutivo (regla: todo código nuevo del módulo es QR)
    qr_size = 22 * mm
    qr = QrCodeWidget(rem.get("consecutivo") or rem.get("id") or "")
    b = qr.getBounds()
    esc = qr_size / max(b[2] - b[0], b[3] - b[1])
    d = Drawing(qr_size, qr_size, transform=[esc, 0, 0, esc, -b[0] * esc, -b[1] * esc])
    d.add(qr)
    renderPDF.draw(d, c, W - 40 * mm, H - 38 * mm)

    c.line(20 * mm, H - 40 * mm, W - 20 * mm, H - 40 * mm)

    # ── Datos del proveedor ──
    y = H - 48 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "PROVEEDOR TERMINACIÓN" if es_term else "CONFECCIONISTA")
    c.setFont("Helvetica", 10)
    y -= 5 * mm
    c.drawString(20 * mm, y, prov.get("nombre") or "—")
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, f"Tel: {prov.get('telefono') or '—'}   ·   Dir: {prov.get('direccion') or '—'}")
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(W - 20 * mm, H - 48 * mm, "FECHA DESPACHO" if es_term else "FECHA RECOGIDA")
    c.setFont("Helvetica", 10)
    c.drawRightString(W - 20 * mm, H - 53 * mm, rem.get("fecha_recogida") or "—")

    # ── Lotes entregados — formato del cuaderno: desglose POR TALLA,
    #    tela, promedio real y metros consumidos ──
    y -= 12 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "CANTIDADES DE CORTE ENTREGADAS")
    total_unidades = 0
    for it in (rem.get("items") or []):
        oc = it.get("orden_corte") or {}
        ref = oc.get("referencia") or {}
        unid_map = {t: int(v or 0) for t, v in (oc.get("unidades_cortadas") or {}).items() if int(v or 0) > 0}
        unid = sum(unid_map.values()) or int(oc.get("cantidad_programada") or 0)
        total_unidades += unid

        # Referencia grande (como el 85609-2 del cuaderno)
        y -= 8 * mm
        c.setFont("Helvetica-Bold", 13)
        c.drawString(20 * mm, y, f"{ref.get('codigo_referencia') or '—'}")
        c.setFont("Helvetica", 9)
        c.drawString(60 * mm, y, (ref.get("nombre") or "")[:34])
        c.drawRightString(W - 20 * mm, y, f"Lote {oc.get('consecutivo') or '—'}")

        # Tallas: fila TALLA / fila CANTIDAD
        if unid_map:
            tallas_ord = sorted(unid_map.keys(), key=lambda t: (len(t), t))
            y -= 7 * mm
            x = 25 * mm
            col = min(16 * mm, (W - 70 * mm) / max(len(tallas_ord), 1))
            c.setFont("Helvetica-Bold", 9)
            for t in tallas_ord:
                c.drawCentredString(x, y, f"T{t}")
                x += col
            c.setFont("Helvetica-Bold", 8)
            c.drawRightString(W - 20 * mm, y, "TOTAL")
            y -= 5.5 * mm
            x = 25 * mm
            c.setFont("Helvetica", 10)
            for t in tallas_ord:
                c.drawCentredString(x, y, str(unid_map[t]))
                x += col
            c.setFont("Helvetica-Bold", 11)
            c.drawRightString(W - 20 * mm, y, str(unid))
            # línea bajo las tallas
            y -= 2 * mm
            c.line(22 * mm, y, W - 20 * mm, y)

        # Tela · promedio · metros · retazos (los datos del informe)
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        tela = ref.get("tela") or "—"
        color = ref.get("color") or ""
        prom = oc.get("promedio_real")
        metros = oc.get("consumo_real_cortador")
        retazos_m = oc.get("retazos_metros")
        partes = [f"Tela: {tela}{(' ' + color) if color else ''}"]
        if prom:    partes.append(f"Prom: {float(prom):.3f}")
        if metros:  partes.append(f"Tela usada: {float(metros):.2f} m")
        if retazos_m: partes.append(f"Retazos: {float(retazos_m):.2f} m")
        c.drawString(20 * mm, y, "   ·   ".join(partes))
        if oc.get("referencia_lote"):
            y -= 5 * mm
            c.drawString(20 * mm, y, f"Ref. lote: {oc.get('referencia_lote')}")

    y -= 4 * mm
    c.line(20 * mm, y, W - 20 * mm, y)
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(W - 20 * mm, y, f"TOTAL ENTREGADO: {total_unidades} unidades")

    # ── Insumos a separar (cantidades, sin valores) ──
    tipo_insumo = "terminacion" if es_term else "confeccion"
    cats = ("INSUMO TERMINACION",) if es_term else ("INSUMO CONFECCION",)
    y -= 10 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, f"INSUMOS ENTREGADOS ({tipo_insumo.upper()})")
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(20 * mm, y, "Insumo")
    c.drawRightString(W - 20 * mm, y, "Cantidad")
    y -= 1.5 * mm
    c.line(20 * mm, y, W - 20 * mm, y)
    c.setFont("Helvetica", 9)
    for it in (rem.get("items") or []):
        try:
            calc = svc.calcular_insumos_requeridos_corte(it["orden_corte_id"], categorias=cats)
            for ins in (calc.get("items") or []):
                y -= 5.5 * mm
                if y < 45 * mm:  # salto de página si se llena
                    c.showPage()
                    y = H - 25 * mm
                    c.setFont("Helvetica", 9)
                c.drawString(20 * mm, y, str(ins.get("item") or "—"))
                c.drawRightString(W - 20 * mm, y, f"{ins.get('total_requerido') or 0:,.0f}".replace(",", "."))
        except Exception:
            continue

    # ── Firmas ──
    y_f = 30 * mm
    c.line(25 * mm, y_f, 85 * mm, y_f)
    c.line(W - 85 * mm, y_f, W - 25 * mm, y_f)
    c.setFont("Helvetica", 8)
    c.drawCentredString(55 * mm, y_f - 5 * mm, "Entrega · MALE'DENIM")
    c.drawCentredString(W - 55 * mm, y_f - 5 * mm, f"Recibe · {prov.get('nombre') or 'Proveedor'}")

    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(W / 2, 12 * mm, "Documento de entrega física — no es factura ni cuenta de cobro.")

    c.showPage()
    c.save()
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════
# INVENTARIO DE INSUMOS
# ═══════════════════════════════════════════════════════════════════════

class InsumoItemIn(BaseModel):
    nombre:    str = Field(min_length=1)
    categoria: str = "INSUMO CONFECCION"
    cantidad:  float = Field(gt=0)
    unidad:    str = "und"


class IngresoInsumosBody(BaseModel):
    items:   list[InsumoItemIn] = Field(min_length=1, max_length=100)
    doc_ref: Optional[str] = None   # factura/remisión del proveedor de insumos


@router.get("/insumos")
def listar_insumos(
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "ver")),
) -> dict:
    # Backfill perezoso: insumos viejos sin código QR reciben el suyo acá
    try:
        svc.asegurar_codigos_insumos()
    except Exception:
        pass
    return {"insumos": svc.listar_insumos()}


def _dibujar_etiqueta_insumo(c, W, H, ins: dict) -> None:
    """Etiqueta del insumo (QR + código + nombre). Escala PROPORCIONAL a W×H
    para que funcione en cualquier medida de adhesivo (chico o grande)."""
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF

    codigo = ins.get("codigo") or ""
    menor = min(W, H)
    pad = menor * 0.06
    compacto = menor < 40 * 2.834  # < ~40 mm de lado → modo compacto

    # Código arriba
    fs_code = max(5.0, menor * 0.10)
    c.setFont("Helvetica-Bold", fs_code)
    c.drawCentredString(W / 2, H - pad - fs_code, codigo or "SIN CÓDIGO")

    # QR centrado — ocupa el ancho disponible o ~50% del alto, lo que sea menor
    qr_size = min(W - 2 * pad, H * 0.52)
    qr = QrCodeWidget(codigo or ins.get("id") or "")
    b = qr.getBounds()
    escala = qr_size / max(b[2] - b[0], b[3] - b[1])
    d = Drawing(qr_size, qr_size,
                transform=[escala, 0, 0, escala, -b[0] * escala, -b[1] * escala])
    d.add(qr)
    qr_y = H - pad - fs_code * 1.5 - qr_size
    renderPDF.draw(d, c, (W - qr_size) / 2, qr_y)

    # Nombre abajo del QR (truncado al ancho)
    fs_name = max(4.5, menor * 0.065)
    c.setFont("Helvetica-Bold", fs_name)
    max_chars = max(6, int((W - 2 * pad) / (fs_name * 0.58)))
    nombre = (ins.get("nombre") or "—").upper()[:max_chars]
    y = qr_y - fs_name * 1.4
    c.drawCentredString(W / 2, y, nombre)

    # Categoría/unidad + pie solo si hay espacio (etiquetas no compactas)
    if not compacto:
        c.setFont("Helvetica", fs_name * 0.82)
        c.drawCentredString(W / 2, y - fs_name * 1.5,
                            f"{ins.get('categoria') or '—'} · {ins.get('unidad') or 'und'}")
        c.setFont("Helvetica-Oblique", max(5.0, menor * 0.05))
        c.drawCentredString(W / 2, pad, "MALE'DENIM · Insumo")


class EtiquetasInsumosBody(BaseModel):
    insumo_ids: list[str] = Field(min_length=1, max_length=200)
    ancho_mm: float = Field(100, ge=20, le=210)   # tamaño del adhesivo (default 10x10cm)
    alto_mm: float = Field(100, ge=20, le=297)


@router.post("/insumos/etiquetas")
def etiquetas_insumos(
    body: EtiquetasInsumosBody,
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "ver")),
) -> Response:
    """PDF con una página por insumo — etiqueta QR para marcar cajas/estantes."""
    from io import BytesIO
    from reportlab.lib.pagesizes import mm
    from reportlab.pdfgen import canvas as _canvas

    svc.asegurar_codigos_insumos()
    todos = {i["id"]: i for i in svc.listar_insumos()}
    seleccion = [todos[i] for i in body.insumo_ids if i in todos]
    if not seleccion:
        raise HTTPException(404, "insumos_no_encontrados")
    buf = BytesIO()
    W, H = body.ancho_mm * mm, body.alto_mm * mm
    c = _canvas.Canvas(buf, pagesize=(W, H))
    for ins in seleccion:
        _dibujar_etiqueta_insumo(c, W, H, ins)
        c.showPage()
    c.save()
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="etiquetas_insumos.pdf"'})


@router.get("/insumos/barcode/{codigo}")
def insumo_por_codigo(
    codigo: str,
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "ver")),
) -> dict:
    """Lookup por QR pistoleado — para entradas/salidas escaneando."""
    ins = svc.obtener_insumo_por_codigo(codigo)
    if not ins:
        raise HTTPException(404, "insumo_no_encontrado")
    return ins


@router.patch("/insumos/{insumo_id}")
def editar_insumo(
    insumo_id: str,
    body: dict,
    user: CurrentUser = Depends(require_permission("produccion_ingreso", "modificar")),
) -> dict:
    """Edita un insumo ya registrado (nombre, categoría, unidad y/o stock)."""
    try:
        return svc.actualizar_insumo(
            insumo_id,
            nombre=body.get("nombre"),
            categoria=body.get("categoria"),
            unidad=body.get("unidad"),
            cantidad_disponible=body.get("cantidad_disponible"),
            usuario=user.nombre or user.email,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"editar_insumo: {str(e)[:200]}")


@router.get("/insumos/movimientos")
def movimientos_insumos(
    limit: int = Query(100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission("produccion_ingreso", "ver")),
) -> dict:
    return {"movimientos": svc.movimientos_insumos(limit=limit)}


@router.patch("/insumos/movimientos/{mov_id}")
def corregir_movimiento_insumo(
    mov_id: str,
    body: dict,
    user: CurrentUser = Depends(require_permission("produccion_ingreso", "modificar")),
) -> dict:
    """Corrige la cantidad de un ingreso de insumos (ajusta stock por la diferencia)."""
    try:
        return svc.corregir_movimiento_insumo(mov_id, float(body.get("cantidad") or 0), user.nombre or user.email)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"corregir_movimiento: {str(e)[:200]}")


@router.delete("/insumos/movimientos/{mov_id}")
def eliminar_movimiento_insumo(
    mov_id: str,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Elimina un ingreso de insumos revirtiendo el stock. Solo administrador."""
    try:
        return svc.eliminar_movimiento_insumo(mov_id, user.nombre or user.email)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"eliminar_movimiento: {str(e)[:200]}")


@router.post("/insumos/ingreso")
def ingreso_insumos(
    body: IngresoInsumosBody,
    user: CurrentUser = Depends(require_permission("produccion_ingreso", "modificar")),
) -> dict:
    """Entrada de insumos al inventario (la salida es automática al
    entregar remisiones)."""
    try:
        return svc.ingreso_insumos(
            items=[i.model_dump() for i in body.items],
            doc_ref=body.doc_ref,
            usuario=user.email,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"ingreso_insumos: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════════════════
# SEPARACIÓN DE INSUMOS (checklist + responsable)
# ═══════════════════════════════════════════════════════════════════════

class SeparacionBody(BaseModel):
    tipo:        str = Field(pattern="^(confeccion|terminacion)$")
    items:       dict = {}
    responsable: Optional[str] = None   # BAY | HENRY HURTADO
    ok:          bool = False


@router.post("/rutas/{ruta_id}/separacion")
def guardar_separacion(
    ruta_id: str,
    body: SeparacionBody,
    user: CurrentUser = Depends(require_permission("produccion_remisiones", "modificar")),
) -> dict:
    """Checklist de separación de insumos: marca items contados y el
    'todo OK' final con responsable (BAY / HENRY HURTADO)."""
    try:
        sep = svc.guardar_separacion(
            ruta_id, tipo=body.tipo, items=body.items,
            responsable=body.responsable, ok=body.ok, usuario=user.email,
        )
        impresion = "manual"
        if body.ok:
            # Al confirmar el conteo, mandar la remisión a la impresora RICOH.
            # Auto-total si PRINTER_EMAIL está configurado (email-to-print);
            # si no, el frontend abre el PDF con el diálogo de impresión.
            impresion = _imprimir_remision_de_ruta(ruta_id, body.tipo)
        return {"ok": True, "separacion": sep, "impresion": impresion}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"separacion: {str(e)[:200]}")


def _remision_de_ruta(ruta_id: str, tipo: str) -> Optional[dict]:
    """Encuentra la remisión del tipo dado asociada al lote de esta ruta."""
    import os as _os
    sb = svc._sb()
    if sb is None:
        return None
    ruta = (sb.table("hoja_ruta_lote").select("orden_corte_id")
              .eq("id", ruta_id).limit(1).execute()).data
    if not ruta:
        return None
    items = (sb.table("remision_items").select("remision_id")
               .eq("orden_corte_id", ruta[0]["orden_corte_id"]).execute()).data or []
    for it in items:
        rem = svc.obtener_remision(it["remision_id"])
        if rem and (rem.get("tipo") or "confeccion") == tipo:
            return rem
    return None


def _imprimir_remision_de_ruta(ruta_id: str, tipo: str) -> str:
    """Busca la remisión del lote y la manda a la impresora."""
    rem = _remision_de_ruta(ruta_id, tipo)
    if not rem:
        return "manual"
    return _imprimir_remision(rem)


def _imprimir_remision(rem: dict) -> str:
    """Envía el PDF de la remisión a la impresora (email-to-print de la RICOH).
    Devuelve 'auto' si se despachó a la impresora, 'manual' si el frontend
    debe abrir el diálogo de impresión."""
    import base64
    import os as _os
    printer_email = _os.environ.get("PRINTER_EMAIL", "").strip()
    resend_key = _os.environ.get("RESEND_API_KEY", "").strip()
    if not (printer_email and resend_key):
        return "manual"
    try:
        pdf = _generar_remision_pdf(rem)
        import httpx as _httpx
        r = _httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}",
                     "Content-Type": "application/json"},
            json={
                "from": _os.environ.get("RESEND_FROM", "orden-corte@maledenim.com").strip(),
                "to": [printer_email],
                "subject": f"Imprimir remisión {rem.get('consecutivo')}",
                "text": "Remisión adjunta para impresión automática.",
                "attachments": [{
                    "filename": f"remision_{rem.get('consecutivo')}.pdf",
                    "content": base64.b64encode(pdf).decode(),
                }],
            },
            timeout=25,
        )
        if r.status_code < 400:
            return "auto"
        import logging as _lg
        _lg.getLogger(__name__).warning(f"[print] resend fallo: {r.text[:200]}")
    except Exception as e:
        import logging as _lg
        _lg.getLogger(__name__).warning(f"[print] fallo: {e}")
    return "manual"
