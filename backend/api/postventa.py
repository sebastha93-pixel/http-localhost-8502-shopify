"""
backend.api.postventa — Router del módulo MALE POSTVENTA IA (panel interno).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.security import CurrentUser, require_permission
from backend.services import postventa as svc
from backend.services import postventa_siigo as siigo_svc
from backend.services import postventa_shopify as shopify_svc
from backend.services import postventa_fiscal as fiscal_svc

router = APIRouter(prefix="/api/postventa", tags=["postventa"])


# ── Modelos ──────────────────────────────────────────────────────────
class CrearCasoIn(BaseModel):
    tipo: str
    reason: str
    customer_email: str = ""
    customer_phone: str = ""
    customer_name: str = ""
    customer_cedula: str = ""
    shopify_order_id: str = ""
    shopify_order_name: str = ""
    siigo_invoice_id: str = ""
    subreason: str = ""
    priority: str = "media"
    source: str = "interno"
    tienda: str = ""
    pago_excedente_id: Optional[int] = None
    assigned_to: Optional[str] = None


class ElegirReemplazoIn(BaseModel):
    requested_sku: str
    requested_variant: str = ""
    requested_price: Optional[float] = None


class SaldoAFavorIn(BaseModel):
    monto: float = 0


class ItemIn(BaseModel):
    original_sku: str = ""
    original_variant: str = ""
    original_price: float = 0
    requested_sku: str = ""
    requested_variant: str = ""
    requested_price: Optional[float] = None


class EvidenciaIn(BaseModel):
    file_url: str
    file_type: str = ""


class CambioEstadoIn(BaseModel):
    nuevo_estado: str
    motivo: str = ""


# ── Endpoints ────────────────────────────────────────────────────────
@router.get("/casos")
def listar(status: Optional[str] = None,
           _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    return svc.listar_casos(status=status)


@router.post("/casos")
def crear(body: CrearCasoIn,
          user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    try:
        caso = svc.crear_caso(**body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    svc.registrar_evento(caso["id"], "creado", f"Caso creado por {user.email}",
                         created_by=user.id)
    return caso


@router.get("/casos/{case_id}")
def detalle(case_id: str,
            _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    caso = svc.obtener_caso(case_id)
    if caso is None:
        raise HTTPException(404, "caso_no_encontrado")
    return caso


@router.patch("/casos/{case_id}/estado")
def cambiar_estado(case_id: str, body: CambioEstadoIn,
                   user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    try:
        return svc.cambiar_estado(case_id, body.nuevo_estado, actor=user.id,
                                  motivo=body.motivo)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/items")
def agregar_item(case_id: str, body: ItemIn,
                 _: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    return svc.agregar_item(case_id, **body.model_dump())


@router.post("/casos/{case_id}/evidencia")
def agregar_evidencia(case_id: str, body: EvidenciaIn,
                      user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    return svc.agregar_evidencia(case_id, body.file_url, body.file_type,
                                 uploaded_by=user.id)


@router.get("/shopify")
def buscar_shopify(email: str = "", telefono: str = "",
                   _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    return svc.pedido_shopify(email=email, telefono=telefono)


@router.get("/dashboard")
def dashboard(_: CurrentUser = Depends(require_permission("postventa", "ver"))):
    return svc.contadores_dashboard()


@router.get("/siigo/discovery")
def siigo_discovery(
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """FASE 0 del motor fiscal: descubrimiento SOLO LECTURA de la config Siigo
    (tipos de doc NC/FV, impuestos, formas de pago, vendedores) + muestra de
    facturas para ubicar el enlace con el pedido Shopify. No emite nada."""
    return siigo_svc.diagnostico()


@router.post("/casos/{case_id}/fiscal/preview")
def fiscal_preview(case_id: str,
                   _: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Arma la nota credito y la muestra. NO emite nada en Siigo."""
    try:
        return fiscal_svc.preview_nota_credito(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/fiscal/emitir")
def fiscal_emitir(case_id: str,
                  user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Emite en Siigo la NC previsualizada. Requiere confirmacion del equipo."""
    try:
        return fiscal_svc.emitir_nota_credito(case_id, actor=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"siigo: {str(e)[:300]}")


@router.post("/casos/{case_id}/fiscal/factura/preview")
def fiscal_factura_preview(case_id: str,
                           _: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Arma la factura del reemplazo (consume el anticipo). NO emite."""
    try:
        return fiscal_svc.preview_factura_reemplazo(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/fiscal/factura/emitir")
def fiscal_factura_emitir(case_id: str,
                          user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Emite en Siigo la factura del reemplazo. Requiere confirmacion."""
    try:
        return fiscal_svc.emitir_factura_reemplazo(case_id, actor=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"siigo: {str(e)[:300]}")


@router.get("/casos/{case_id}/fiscal/items-factura")
def fiscal_items_factura(case_id: str,
                         _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Items de la factura original del pedido, para elegir cual se devuelve."""
    try:
        return fiscal_svc.items_factura_del_caso(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"siigo: {str(e)[:300]}")


# ── Que se lleva la clienta ──────────────────────────────────────────
@router.get("/casos/{case_id}/reemplazo/opciones")
def reemplazo_opciones(
    case_id: str,
    q: str = "",
    _: CurrentUser = Depends(require_permission("postventa", "ver")),
):
    """Referencias que ESE punto puede entregar hoy, con su existencia.

    Sin esto se puede facturar una prenda que la tienda no tiene: queda un
    documento fiscal emitido y una clienta esperando algo inexistente."""
    from backend.services import postventa_reemplazo as R
    from backend.services import tiendas
    from backend.services import siigo

    caso = svc.obtener_caso(case_id)
    if caso is None:
        raise HTTPException(404, "caso_no_encontrado")
    clave = caso.get("tienda")
    if not clave:
        raise HTTPException(400, "El caso no es de tienda: no hay bodega "
                                 "contra la cual verificar existencias.")
    t = tiendas.obtener(clave) or {}
    bodega = t.get("bodega_nombre") or t.get("tienda")
    if not siigo.siigo_configurado():
        raise HTTPException(503, "Siigo no configurado.")
    inv = siigo.inventario_por_bodega()
    return {"bodega": bodega, "tienda": t.get("nombre"),
            "opciones": R.opciones_con_stock(inv, bodega, q=q)}


@router.post("/casos/{case_id}/reemplazo")
def reemplazo_elegir(
    case_id: str, body: ElegirReemplazoIn,
    user: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Fija la prenda del reemplazo. Se niega si esa tienda no la tiene."""
    from backend.services import postventa_reemplazo as R
    from backend.services import tiendas
    from backend.services import siigo

    caso = svc.obtener_caso(case_id)
    if caso is None:
        raise HTTPException(404, "caso_no_encontrado")
    clave = caso.get("tienda")
    if clave:
        t = tiendas.obtener(clave) or {}
        bodega = t.get("bodega_nombre") or t.get("tienda")
        inv = siigo.inventario_por_bodega() if siigo.siigo_configurado() else {}
        ok, detalle = R.verificar_disponible(inv, bodega, body.requested_sku)
        if not ok:
            raise HTTPException(400, detalle)
    try:
        item = svc.elegir_reemplazo(case_id, requested_sku=body.requested_sku,
                                    requested_variant=body.requested_variant,
                                    requested_price=body.requested_price)
    except ValueError as e:
        raise HTTPException(400, str(e))
    svc.registrar_evento(case_id, "reemplazo_elegido",
                         f"Se lleva {body.requested_sku}", created_by=user.id)
    return item


@router.post("/casos/{case_id}/saldo-a-favor")
def reemplazo_saldo_a_favor(
    case_id: str, body: SaldoAFavorIn,
    user: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """La clienta no se lleva nada hoy: el credito queda a su nombre.

    NO se emite factura de reemplazo — hacerlo inventaria una venta. El
    anticipo ya esta en Siigo desde la nota credito y se consume cuando
    vuelva. Se deja escrito el monto: es el respaldo de la clienta."""
    from backend.services import postventa_reemplazo as R
    caso = svc.obtener_caso(case_id)
    if caso is None:
        raise HTTPException(404, "caso_no_encontrado")
    svc.registrar_evento(case_id, "saldo_a_favor",
                         R.texto_saldo_a_favor(body.monto), created_by=user.id)
    try:
        svc.cambiar_estado(case_id, "cerrado", actor=user.email)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "monto": body.monto}


@router.get("/casos/{case_id}/timeline")
def timeline(case_id: str,
             _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Historial del caso: estados, notificaciones, documentos fiscales."""
    return svc.timeline_caso(case_id)


@router.get("/casos/{case_id}/items")
def items(case_id: str,
          _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Items del caso (lo que se devuelve y su reemplazo)."""
    return svc.items_caso(case_id)


@router.get("/shopify/discovery")
def shopify_discovery(
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Que permisos tiene el token de Shopify: si puede descontar ventas,
    registrar retornos o reservar inventario. Solo lectura."""
    return shopify_svc.diagnostico()


class GuiaIn(BaseModel):
    guia: str
    transportadora: str = ""


class RecepcionIn(BaseModel):
    notas: str = ""


@router.get("/casos/{case_id}/logistica")
def logistica(case_id: str,
              _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Guias, fechas y costos del caso."""
    return svc.obtener_logistica(case_id) or {}


@router.post("/casos/{case_id}/logistica/guia-retorno")
def guia_retorno(case_id: str, body: GuiaIn,
                 user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Asigna la guia de la devolucion y pone el caso en transito."""
    try:
        return svc.registrar_guia_retorno(case_id, guia=body.guia,
                                          transportadora=body.transportadora,
                                          actor=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/logistica/recibir")
def recibir(case_id: str, body: RecepcionIn,
            user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Confirma que la prenda llego a bodega. Desbloquea el despacho."""
    return svc.confirmar_recepcion(case_id, actor=user.id, notas=body.notas)


@router.post("/casos/{case_id}/logistica/despachar")
def despachar(case_id: str, body: GuiaIn,
              user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Registra el despacho del reemplazo. Exige que el retorno ya llego."""
    try:
        return svc.registrar_despacho(case_id, guia=body.guia,
                                      transportadora=body.transportadora,
                                      actor=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/impacto-ventas")
def impacto_ventas(desde: str = "", hasta: str = "",
                   _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    """Lo que la postventa le resta a las ventas del periodo (venta neta real)."""
    return svc.impacto_ventas(desde=desde, hasta=hasta)


@router.get("/shopify/auth")
def shopify_auth_estado(
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Que token de Shopify se esta usando: modelo nuevo (client_credentials,
    24h) o legacy. No expone secretos."""
    from backend.services import shopify_auth
    return shopify_auth.diagnostico()


@router.post("/shopify/auth/refrescar")
def shopify_auth_refrescar(
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Descarta el token cacheado y pide uno nuevo.

    Util tras reinstalar la app o cambiar scopes: el token de 24h guardado
    conserva los permisos con los que se emitio."""
    from backend.services import shopify_auth
    shopify_auth.invalidar()
    return {"refrescado": True, **shopify_auth.diagnostico()}


@router.post("/banco-pruebas")
def banco_pruebas(
    total: int = 20,
    dry_run: bool = True,
    user: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Gate de N casos contra pedidos reales.

    dry_run=true (default): llega al PREVIEW y NO emite nada en Siigo.
    dry_run=false: emite (solo permitido con SIIGO_POSTVENTA_MODO=prueba).
    """
    from backend.services import postventa_banco_pruebas as banco
    return banco.correr(total=max(1, min(total, 40)), dry_run=dry_run,
                        actor=user.id)


@router.delete("/banco-pruebas")
def banco_pruebas_limpiar(
    confirmar: bool = False,
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Borra los casos creados por el banco de pruebas."""
    from backend.services import postventa_banco_pruebas as banco
    return banco.limpiar(confirmar=confirmar)


@router.get("/shopify/variantes")
def shopify_variantes_dx(
    precio_base: float = 125966.39,
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Diagnostico: que devuelve Shopify al pedir variantes y por que
    variante_mas_cara_que no encuentra nada. Solo lectura."""
    from backend.services import fiscal_shopify as FS
    return FS.diagnostico_variantes(precio_base)


@router.get("/siigo/tipos-documento")
def siigo_tipos_documento(
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Todos los tipos de factura con su prefijo (FV-6, FV-11, FV-12...).
    Necesario para facturar un cambio desde la tienda correcta."""
    from backend.services import postventa_siigo as s
    return s.tipos_documento_completos()


@router.get("/tiendas")
def listar_tiendas(
    _: CurrentUser = Depends(require_permission("postventa", "ver")),
):
    """Puntos de venta para atender un cambio presencial, con su estado de
    configuracion y las formas de pago disponibles alli."""
    from backend.services import tiendas
    return tiendas.listar()


@router.get("/siigo/prefijos")
def siigo_prefijos(
    _: CurrentUser = Depends(require_permission("postventa", "modificar")),
):
    """Id de cada tipo de factura deducido de facturas reales.

    /document-types no expone los tipos de las tiendas (FV-6, FV-11, FV-12);
    aqui se deducen recorriendo facturas existentes."""
    from backend.services import postventa_siigo as s
    return s.documentos_por_prefijo()


@router.get("/siigo/nota-credito")
def siigo_nota_credito(
    numero: int,
    _: CurrentUser = Depends(require_permission("postventa", "ver")),
):
    """Una NC ya emitida tal cual la guardo Siigo: a que bodega entro cada
    prenda y si fue a la DIAN. Solo lectura.

    Responde de un tiron la pregunta de despues de emitir: si el stock de la
    tienda no se movio, fue porque el item llego sin bodega (bug nuestro) o
    porque Siigo la tiene pero no mueve inventario (parametrizacion)."""
    from backend.services import postventa_siigo as s
    return s.nota_credito_por_numero(numero)


@router.get("/clientes/compras")
def compras_por_cedula(
    cedula: str,
    _: CurrentUser = Depends(require_permission("postventa", "ver")),
):
    """Compras de una clienta por cedula: online y de tienda, con sus prendas
    y si ya se les puede hacer nota credito. Evita pedirle el nº de pedido."""
    from backend.services import postventa_cliente
    return postventa_cliente.compras_por_cedula(cedula)


@router.get("/clientes/crudo")
def cliente_siigo_crudo(
    cedula: str,
    _: CurrentUser = Depends(require_permission("postventa", "ver")),
):
    """Diagnostico: QUE campos devuelve Siigo de verdad para esa cedula.

    Sirve para cuando un dato sale vacio en el panel (paso con la fecha) y hay
    que saber si el problema es el nombre del campo o que Siigo no lo manda.
    No inventa nada: muestra las llaves tal cual y solo los valores de fecha.
    """
    from backend.services import siigo
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    def _sonda(path: str, params: dict) -> dict:
        try:
            r = siigo.siigo_get(path, params)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:250]}
        filas = r.get("results", []) if isinstance(r, dict) else []
        if not filas or not isinstance(filas[0], dict):
            return {"resultados": len(filas), "llaves": []}
        f = filas[0]
        return {
            "resultados": len(filas),
            "llaves": sorted(f.keys()),
            # Solo campos de fecha y estructura — nunca montos ni PII completa.
            "fechas": {k: v for k, v in f.items()
                       if any(t in k.lower() for t in ("date", "created"))},
            "metadata": f.get("metadata"),
            "tipo_name": type(f.get("name")).__name__,
            "llaves_contacto": sorted((f.get("contacts") or [{}])[0].keys())
                               if f.get("contacts") else [],
        }

    return {
        "cedula": cedula,
        "invoices": _sonda("/invoices", {"customer_identification": cedula,
                                         "page_size": 3, "page": 1}),
        "customers": _sonda("/customers", {"identification": cedula}),
    }
