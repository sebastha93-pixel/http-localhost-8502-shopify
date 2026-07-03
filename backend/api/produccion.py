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

from backend.core.security import (CurrentUser, require_role, require_permission,
                                    require_permission_estricto, tiene_permiso_costos)
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
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    user: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    return {"ingresos": svc.listar_ingresos(textilera=textilera, estado=estado, limit=limit)}


@router.get("/ingreso/{ingreso_id}")
def detalle_ingreso(
    ingreso_id: str,
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
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
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    return {"rollos": svc.listar_rollos(tela=tela, estado=estado, tono=tono, limit=limit)}


@router.get("/rollos/{rollo_id}")
def detalle_rollo(
    rollo_id: str,
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    r = svc.obtener_rollo(rollo_id)
    if not r:
        raise HTTPException(404, "Rollo no encontrado")
    return r


@router.get("/rollos/barcode/{barcode}")
def rollo_por_barcode(
    barcode: str,
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    r = svc.obtener_rollo_por_barcode(barcode)
    if not r:
        raise HTTPException(404, "Rollo no encontrado")
    return r


@router.get("/inventario/resumen")
def inventario_resumen(
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    return {"resumen": svc.inventario_resumen()}


# ═══════════════════════════════════════════════════════════════════════
# ETIQUETA (PDF Zebra 10×10 con Code128)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/rollos/{rollo_id}/etiqueta")
def etiqueta_rollo(
    rollo_id: str,
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
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
    _: CurrentUser = Depends(require_permission_estricto("produccion_costos", "modificar")),
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
    user: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    user: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    sin_remision: Optional[str] = None,  # 'confeccion' | 'terminacion'
    marcar_remisiones: bool = False,
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    return {"ordenes": svc.listar_ordenes_corte(
        estado=estado, limit=limit, sin_remision=sin_remision,
        marcar_remisiones=marcar_remisiones)}


@router.get("/corte/{oc_id}")
def detalle_corte(
    oc_id: str,
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    oc = svc.obtener_orden_corte(oc_id)
    if not oc:
        raise HTTPException(404, "Orden de corte no encontrada")
    return oc


@router.post("/corte/{oc_id}/pistolear")
def pistolear_rollo(
    oc_id: str,
    body: PistolearRolloBody,
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    user: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    _: CurrentUser = Depends(require_permission("produccion", "borrar")),
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
    tipo:      str = "confeccion"  # 'confeccion' | 'terminacion'


class ConfeccionistaUpdate(BaseModel):
    nombre:    Optional[str] = None
    telefono:  Optional[str] = None
    direccion: Optional[str] = None
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
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    return {"confeccionistas": svc.listar_confeccionistas(
        incluir_inactivos=incluir_inactivos, tipo=tipo,
    )}


@router.post("/confeccionistas")
def crear_confeccionista(
    body: ConfeccionistaIn,
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
) -> dict:
    try:
        return {"ok": True, "confeccionista": svc.crear_confeccionista(
            nombre=body.nombre, telefono=body.telefono,
            direccion=body.direccion, tipo=body.tipo,
        )}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"crear_conf: {str(e)[:200]}")


@router.patch("/confeccionistas/{cid}")
def actualizar_confeccionista(
    cid: str,
    body: ConfeccionistaUpdate,
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    return {"remisiones": svc.listar_remisiones(
        estado=estado, confeccionista_id=confeccionista_id, limit=limit,
    )}


@router.post("/remisiones")
def crear_remision(
    body: RemisionIn,
    user: CurrentUser = Depends(require_permission("produccion", "modificar")),
) -> dict:
    try:
        rem = svc.crear_remision(
            confeccionista_id=body.confeccionista_id,
            fecha_recogida=body.fecha_recogida,
            orden_corte_ids=body.orden_corte_ids,
            created_by=user.email,
            tipo=body.tipo,
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
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    rem = svc.obtener_remision(rem_id)
    if not rem:
        raise HTTPException(404, "no_encontrada")
    return rem


@router.post("/remisiones/{rem_id}/recogida")
def marcar_recogida(
    rem_id: str,
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
) -> dict:
    try:
        return {"ok": True, "remision": svc.marcar_remision_recogida(rem_id)}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ═══════════════════════════════════════════════════════════════════════
# INSUMOS REQUERIDOS POR ORDEN DE CORTE (auto desde precosteo)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/corte/{oc_id}/insumos-requeridos")
def insumos_requeridos_corte(
    oc_id: str,
    tipo: Optional[str] = None,  # 'confeccion' | 'terminacion' | None (ambos)
    user: CurrentUser = Depends(require_permission("produccion", "ver")),
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
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    return {"rutas": svc.listar_rutas(
        etapa=etapa, confeccionista_id=confeccionista_id, limit=limit
    )}


@router.post("/rutas")
def crear_ruta(
    body: CrearRutaBody,
    user: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    r = svc.obtener_ruta_por_corte(oc_id)
    if not r:
        raise HTTPException(404, "no_encontrada")
    return r


@router.patch("/rutas/{ruta_id}")
def actualizar_ruta(
    ruta_id: str,
    body: ActualizarRutaBody,
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
) -> dict:
    try:
        campos = body.model_dump(exclude_unset=True)
        return {"ok": True, "ruta": svc.actualizar_ruta_lote(ruta_id, **campos)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/rutas/{ruta_id}/etapa")
def cambiar_etapa(
    ruta_id: str,
    body: CambiarEtapaBody,
    _: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
    cantidad total, insumos de CONFECCIÓN con cantidades y SU valor acordado
    (precio_confeccion — regla de Sebastián: "el confeccionista solo ve el
    valor acordado de confección").
    NO se envía: precio de corte, valores unitarios de insumos, costos
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
        # Valor acordado del SERVICIO de confección — el único precio que ve.
        "precio_confeccion":         r.get("precio_confeccion"),
    }


@publico.post("/lote/{token}/aceptar")
def aceptar_lote_publico(token: str) -> dict:
    """Endpoint público. El confeccionista clickea el botón desde el link.
    Solo permite pasar de 'asignado' → 'aceptado'.
    """
    r = svc.obtener_ruta_por_token(token)
    if not r:
        raise HTTPException(404, "lote_no_encontrado")
    if r.get("etapa") != "asignado":
        raise HTTPException(400, f"ya_aceptado_o_en_progreso:{r.get('etapa')}")
    try:
        return {"ok": True, "ruta": svc.cambiar_etapa_ruta(r["id"], "aceptado")}
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
    _: CurrentUser = Depends(require_permission("produccion", "ver")),
) -> dict:
    return {"notas": svc.listar_notas_ruta(ruta_id)}


@router.post("/rutas/{ruta_id}/notas")
def agregar_nota_ruta(
    ruta_id: str,
    body: NotaAdminBody,
    user: CurrentUser = Depends(require_permission("produccion", "modificar")),
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
