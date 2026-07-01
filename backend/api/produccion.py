"""
backend.api.produccion — Router del módulo Producción.

Prefijo: /api/produccion
Auth: reutiliza core.security (require_role / require_permission).

FASE 1 · Bloque 2: Ingreso + Inventario.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from backend.core.security import CurrentUser, require_role, require_permission
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
        return {"ok": True, "consecutivo": svc.next_consecutivo(prefijo)}
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
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
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
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
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


@router.get("/ingreso")
def listar_ingresos(
    textilera: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    return {"ingresos": svc.listar_ingresos(textilera=textilera, estado=estado, limit=limit)}


@router.get("/ingreso/{ingreso_id}")
def detalle_ingreso(
    ingreso_id: str,
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
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
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    return {"rollos": svc.listar_rollos(tela=tela, estado=estado, tono=tono, limit=limit)}


@router.get("/rollos/{rollo_id}")
def detalle_rollo(
    rollo_id: str,
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    r = svc.obtener_rollo(rollo_id)
    if not r:
        raise HTTPException(404, "Rollo no encontrado")
    return r


@router.get("/rollos/barcode/{barcode}")
def rollo_por_barcode(
    barcode: str,
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    r = svc.obtener_rollo_por_barcode(barcode)
    if not r:
        raise HTTPException(404, "Rollo no encontrado")
    return r


@router.get("/inventario/resumen")
def inventario_resumen(
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    return {"resumen": svc.inventario_resumen()}


# ═══════════════════════════════════════════════════════════════════════
# ETIQUETA (PDF Zebra 10×10 con Code128)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/rollos/{rollo_id}/etiqueta")
def etiqueta_rollo(
    rollo_id: str,
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
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


def _generar_etiqueta_pdf(rollo: dict) -> bytes:
    """Genera una etiqueta 10×10 cm en PDF con:
    - Código de barras Code128 (barcode del rollo)
    - Código interno legible arriba
    - Descripción tela · tono · ancho · metros · lote · fecha
    Usa reportlab (ya presente en requirements para otros PDFs).
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import mm
    from reportlab.pdfgen import canvas
    from reportlab.graphics.barcode import code128
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF

    buf = BytesIO()
    # Página 100 × 100 mm
    W, H = 100 * mm, 100 * mm
    c = canvas.Canvas(buf, pagesize=(W, H))

    # Header: código interno
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(W / 2, H - 10 * mm, rollo["codigo_interno"])

    # Barcode Code128
    bc = code128.Code128(rollo["barcode"], barHeight=18 * mm, barWidth=0.5 * mm)
    bc_w = bc.width
    bc.drawOn(c, (W - bc_w) / 2, H - 40 * mm)

    # Datos
    c.setFont("Helvetica-Bold", 11)
    y = H - 55 * mm
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

    c.showPage()
    c.save()
    return buf.getvalue()


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
    tela:    Optional[str] = None
    color:   Optional[str] = None
    iva_pct: Optional[float] = None
    margen:  Optional[float] = None
    items:   Optional[list[PrecosteoItemIn]] = None
    es_muestra_diseno: Optional[bool] = None


@router.get("/precosteo/categorias")
def categorias_precosteo(_: CurrentUser = Depends(require_permission("operaciones", "ver"))) -> dict:
    return {"categorias": list(svc.CATEGORIAS_PRECOSTEO)}


@router.post("/precosteo")
def crear_precosteo(
    body: PrecosteoIn,
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
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
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    return {"precosteos": svc.listar_precosteos(
        estado=estado, tela=tela, limit=limit,
        disponibles_para_corte=disponibles_para_corte,
    )}


@router.get("/precosteo/{precosteo_id}")
def detalle_precosteo(
    precosteo_id: str,
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    p = svc.obtener_precosteo(precosteo_id)
    if not p:
        raise HTTPException(404, "no_encontrado")
    return p


@router.patch("/precosteo/{precosteo_id}")
def actualizar_precosteo(
    precosteo_id: str,
    body: PrecosteoUpdate,
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    try:
        return svc.actualizar_precosteo(
            precosteo_id,
            nombre=body.nombre,
            tela=body.tela,
            color=body.color,
            iva_pct=body.iva_pct,
            margen=body.margen,
            items=[i.model_dump() for i in body.items] if body.items is not None else None,
            es_muestra_diseno=body.es_muestra_diseno,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"actualizar: {str(e)[:200]}")


@router.post("/precosteo/{precosteo_id}/firmar")
def firmar_precosteo(
    precosteo_id: str,
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
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
    _: CurrentUser = Depends(require_permission("operaciones", "borrar")),
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
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
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
        )
        return {"ok": True, "foto_url": url}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"foto: {str(e)[:200]}")


# Bloque 4 — Orden de Corte + cierre
# Bloque 5 — Informe teórico vs real
# Bloque 6 — Remisiones + Insumos


# ═══════════════════════════════════════════════════════════════════════
# BLOQUE 4 — ORDEN DE CORTE
# ═══════════════════════════════════════════════════════════════════════

class CrearCorteBody(BaseModel):
    referencia_id:         str
    largo_trazo:           float = Field(gt=0)
    curva_trazo:           dict = Field(default_factory=dict)
    cantidad_programada:   Optional[int] = None
    promedio_tecnico:      Optional[float] = None
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
    retazos_cantidad:  Optional[int] = None
    fecha_entrega:     Optional[str] = None
    precio_corte:      Optional[float] = None


class AutorizarCorteBody(BaseModel):
    destinatarios:  Optional[list[str]] = None
    mensaje_extra:  Optional[str] = None


@router.post("/corte")
def crear_corte(
    body: CrearCorteBody,
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    try:
        oc = svc.crear_orden_corte(
            referencia_id=body.referencia_id,
            largo_trazo=body.largo_trazo,
            curva_trazo=body.curva_trazo,
            cantidad_programada=body.cantidad_programada,
            promedio_tecnico=body.promedio_tecnico,
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
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
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
    file: UploadFile = File(...),
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    contenido = await file.read()
    if len(contenido) > 15 * 1024 * 1024:
        raise HTTPException(413, "archivo_mayor_a_15MB")
    if not contenido:
        raise HTTPException(400, "archivo_vacio")
    try:
        url = svc.subir_trazos_corte(
            oc_id,
            file_bytes=contenido,
            filename=file.filename or "trazos.pdf",
            content_type=file.content_type or "application/pdf",
        )
        return {"ok": True, "trazos_url": url}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"trazos: {str(e)[:200]}")


@router.get("/corte")
def listar_cortes(
    estado: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    return {"ordenes": svc.listar_ordenes_corte(estado=estado, limit=limit)}


@router.get("/corte/{oc_id}")
def detalle_corte(
    oc_id: str,
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    oc = svc.obtener_orden_corte(oc_id)
    if not oc:
        raise HTTPException(404, "Orden de corte no encontrada")
    return oc


@router.post("/corte/{oc_id}/pistolear")
def pistolear_rollo(
    oc_id: str,
    body: PistolearRolloBody,
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    try:
        oc = svc.asignar_rollo_a_corte(
            oc_id=oc_id,
            barcode=body.barcode,
            metros_reservar=body.metros_reservar,
        )
        return {"ok": True, "orden_corte": oc}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"pistolear: {str(e)[:200]}")


@router.delete("/corte/{oc_id}/rollo/{rollo_id}")
def quitar_rollo(
    oc_id: str,
    rollo_id: str,
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    try:
        oc = svc.quitar_rollo_de_corte(oc_id=oc_id, rollo_id=rollo_id)
        return {"ok": True, "orden_corte": oc}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/corte/{oc_id}/cerrar")
def cerrar_corte(
    oc_id: str,
    body: CerrarCorteBody,
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
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
            retazos_cantidad=body.retazos_cantidad,
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
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
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


class ConfeccionistaUpdate(BaseModel):
    nombre:    Optional[str] = None
    telefono:  Optional[str] = None
    direccion: Optional[str] = None
    activo:    Optional[bool] = None


class RemisionIn(BaseModel):
    confeccionista_id: str
    fecha_recogida:    str
    orden_corte_ids:   list[str] = Field(min_length=1)


@router.get("/confeccionistas")
def listar_confeccionistas(
    incluir_inactivos: bool = False,
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    return {"confeccionistas": svc.listar_confeccionistas(incluir_inactivos=incluir_inactivos)}


@router.post("/confeccionistas")
def crear_confeccionista(
    body: ConfeccionistaIn,
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    try:
        return {"ok": True, "confeccionista": svc.crear_confeccionista(
            nombre=body.nombre, telefono=body.telefono, direccion=body.direccion,
        )}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"crear_conf: {str(e)[:200]}")


@router.patch("/confeccionistas/{cid}")
def actualizar_confeccionista(
    cid: str,
    body: ConfeccionistaUpdate,
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    try:
        campos = body.model_dump(exclude_unset=True)
        return {"ok": True, "confeccionista": svc.actualizar_confeccionista(cid, **campos)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"actualizar_conf: {str(e)[:200]}")


@router.get("/remisiones")
def listar_remisiones(
    estado: Optional[str] = None,
    confeccionista_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    return {"remisiones": svc.listar_remisiones(
        estado=estado, confeccionista_id=confeccionista_id, limit=limit,
    )}


@router.post("/remisiones")
def crear_remision(
    body: RemisionIn,
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    try:
        rem = svc.crear_remision(
            confeccionista_id=body.confeccionista_id,
            fecha_recogida=body.fecha_recogida,
            orden_corte_ids=body.orden_corte_ids,
            created_by=user.email,
        )
        return {"ok": True, "remision": rem}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"crear_remision: {str(e)[:200]}")


@router.get("/remisiones/{rem_id}")
def detalle_remision(
    rem_id: str,
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    rem = svc.obtener_remision(rem_id)
    if not rem:
        raise HTTPException(404, "no_encontrada")
    return rem


@router.post("/remisiones/{rem_id}/recogida")
def marcar_recogida(
    rem_id: str,
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    try:
        return {"ok": True, "remision": svc.marcar_remision_recogida(rem_id)}
    except ValueError as e:
        raise HTTPException(400, str(e))
