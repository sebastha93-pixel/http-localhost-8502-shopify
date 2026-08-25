"""
backend.api.finanzas — Dashboard financiero + integración MercadoPago.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from backend.core.security import CurrentUser, get_current_user, require_role, require_permission
from backend.services import melonn as melonn_svc
from backend.services import metricas as metricas_svc
from backend.services import addi as addi_svc

_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


log = logging.getLogger("maledenim.finanzas")

router = APIRouter(prefix="/api/finanzas", tags=["finanzas"])


# ── Modelos ──────────────────────────────────────────────────────────

class PagoMP(BaseModel):
    mp_id: str = ""
    valor_bruto: float = 0.0
    comision: float = 0.0
    valor_neto: float = 0.0
    email: str = ""
    nombre_pagador: str = ""
    fecha_aprobado: str = ""
    estado: str = ""
    descripcion: str = ""
    external_reference: str = ""

    # Cinturón de seguridad del borde. mp_client ya normaliza los null, pero
    # este modelo NO puede volver a tumbar la vista de finanzas completa por un
    # solo pago incompleto: el 2026-07-30, UN pago sin email de 386 devolvía 500
    # en todo el endpoint (y en la consola se veía como un error de CORS).
    # Un default no basta: pydantic valida el None igual si la clave viene.
    @field_validator("mp_id", "email", "nombre_pagador", "fecha_aprobado",
                     "estado", "descripcion", "external_reference", mode="before")
    @classmethod
    def _texto_vacio_si_null(cls, v):
        return "" if v is None else v

    @field_validator("valor_bruto", "comision", "valor_neto", mode="before")
    @classmethod
    def _cero_si_null(cls, v):
        return 0.0 if v is None else v


class PagosMPResponse(BaseModel):
    pagos: list[PagoMP]
    total: int
    valor_bruto_total: float
    valor_neto_total: float
    comision_total: float
    desde: str
    hasta: str


class ResumenFinanzas(BaseModel):
    # COD
    cod_total:          float
    cod_pendientes:     float    # esperan despacho
    cod_transito:       float    # en ruta
    cod_novedades:      float    # con incidencia
    cod_entregados:     float    # entregado BRUTO en la ventana (sigue creciendo)
    # ── Cartera real, cruzada contra las facturas de Siigo ──────────────
    # `cod_entregados` suma TODO lo entregado en 90 días y nunca descuenta lo
    # que Melonn ya consignó: el 2026-08-10 mostraba $168.388.033 cuando la
    # deuda real era $36.552.345. Se dejan las dos: la bruta sirve de operación,
    # la real es la que se le reclama a Melonn. Ver services/cartera_cod.py.
    # OJO CON LOS NOMBRES: la primera versión decía `cod_melonn_debe` usando el
    # `balance` de la factura como señal de cobro. Está mal: 1.328 de 1.329
    # facturas COD se cierran contra la cuenta "CONTRA ENTREGA CREDITO 10 DIAS",
    # así que saldo 0 = venta a crédito registrada, NO plata recibida. Cuánto
    # consignó Melonn se mide en la conciliación. Ver services/cartera_cod.py.
    cartera_disponible:   bool = False   # False = Siigo no respondió; NO es cero
    cartera_motivo:       Optional[str] = None
    cod_facturado_credito:   float = 0.0   # facturado contra la cuenta de COD
    n_cod_facturado_credito: int = 0
    cod_cobrado_directo:  float = 0.0      # facturado y pagado por otro medio
    n_cod_cobrado_directo: int = 0
    cod_sin_facturar:     float = 0.0      # SIN ninguna factura (cualquier medio)
    n_cod_sin_facturar:   int = 0
    cod_recaudo_medible:  bool = False
    cod_nota_recaudo:     Optional[str] = None
    # La deuda REAL: entregado menos lo que Melonn reporta haber recaudado.
    # Sale del módulo de conciliación; Siigo no tiene este dato.
    cod_melonn_debe:      float = 0.0
    n_cod_melonn_debe:    int = 0
    cod_melonn_recaudado: float = 0.0
    n_cod_melonn_recaudado: int = 0
    n_cod_total:        int
    n_cod_pendientes:   int
    n_cod_transito:     int
    n_cod_novedades:    int
    n_cod_entregados:   int
    # MercadoPago (últimos 30 días)
    mp_total:           float
    mp_neto:            float
    mp_comisiones:      float
    n_mp:               int
    # Meta
    fuente:             str
    fetched_at:         str


# ── Endpoint resumen ─────────────────────────────────────────────────

@router.get("/resumen", response_model=ResumenFinanzas)
def resumen(_: CurrentUser = Depends(get_current_user)) -> ResumenFinanzas:
    """Resumen financiero consolidado: COD activo, entregado, MP último mes."""
    # Cargar pedidos enriquecidos
    try:
        data = melonn_svc.obtener_pedidos(forzar_refresh=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn error: {exc}")

    pedidos = [metricas_svc.clasificar(p) for p in data["pedidos"]]
    cods = [p for p in pedidos if p.get("tipo_recaudo") == "Contraentrega"]

    def _val(arr, pred):
        return sum(p.get("valor_num", 0) for p in arr if pred(p))

    def _code(p): return int(p.get("estado_melonn_code") or 0)

    cod_pend     = [p for p in cods if _code(p) in (26, 29)]
    cod_tran     = [p for p in cods if _code(p) in (5, 7, 24, 28)]
    cod_nov      = [p for p in cods if p.get("es_novedad_visible")]
    cod_entreg   = [p for p in cods if _code(p) in (6, 8)]

    # MercadoPago — últimos 30 días
    mp_total = mp_neto = mp_com = 0.0
    n_mp = 0
    try:
        import mp_client as mp
        desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        pagos = mp.obtener_pagos(fecha_desde=desde, limit_total=1000)
        n_mp = len(pagos)
        mp_total = sum(p.get("valor_bruto", 0) for p in pagos)
        mp_neto  = sum(p.get("valor_neto", 0)  for p in pagos)
        mp_com   = sum(p.get("comision", 0)    for p in pagos)
    except Exception as e:
        print(f"[finanzas] MP error: {e}")

    # ── Cartera real contra Siigo ────────────────────────────────────
    # Si falla, el resumen sigue saliendo: la cartera se marca como no
    # disponible y la pantalla lo dice. Un tablero que muestra $0 de deuda
    # porque Siigo no contestó es peor que uno que dice "no pude consultar".
    from backend.services import cartera_cod as cartera_svc
    try:
        cart = cartera_svc.cruzar(pedidos)
    except Exception as e:
        log.warning(f"[finanzas] cartera COD falló: {str(e)[:140]}")
        cart = {"disponible": False, "motivo": str(e)[:120]}

    return ResumenFinanzas(
        cartera_disponible=bool(cart.get("disponible")),
        cartera_motivo=cart.get("motivo"),
        cod_facturado_credito=cart.get("facturado_credito", 0.0),
        n_cod_facturado_credito=cart.get("n_facturado_credito", 0),
        cod_cobrado_directo=cart.get("cobrado_directo", 0.0),
        n_cod_cobrado_directo=cart.get("n_cobrado_directo", 0),
        cod_sin_facturar=cart.get("sin_facturar", 0.0),
        n_cod_sin_facturar=cart.get("n_sin_facturar", 0),
        cod_recaudo_medible=bool(cart.get("recaudo_medible")),
        cod_nota_recaudo=cart.get("nota_recaudo"),
        cod_melonn_debe=cart.get("melonn_debe", 0.0),
        n_cod_melonn_debe=cart.get("n_melonn_debe", 0),
        cod_melonn_recaudado=cart.get("melonn_recaudado", 0.0),
        n_cod_melonn_recaudado=cart.get("n_melonn_recaudado", 0),
        cod_total=sum(p.get("valor_num", 0) for p in cods),
        cod_pendientes=sum(p.get("valor_num", 0) for p in cod_pend),
        cod_transito=sum(p.get("valor_num", 0) for p in cod_tran),
        cod_novedades=sum(p.get("valor_num", 0) for p in cod_nov),
        cod_entregados=sum(p.get("valor_num", 0) for p in cod_entreg),
        n_cod_total=len(cods),
        n_cod_pendientes=len(cod_pend),
        n_cod_transito=len(cod_tran),
        n_cod_novedades=len(cod_nov),
        n_cod_entregados=len(cod_entreg),
        mp_total=mp_total,
        mp_neto=mp_neto,
        mp_comisiones=mp_com,
        n_mp=n_mp,
        fuente=data["fuente"],
        fetched_at=data["fetched_at"],
    )


# ── Endpoint MercadoPago ─────────────────────────────────────────────

@router.get("/cartera-cod")
def cartera_cod_detalle(
    _: CurrentUser = Depends(get_current_user),
) -> dict:
    """Detalle de la cartera de contraentrega cruzada contra Siigo.

    Dos listas para perseguir plata:
      · `abiertas`     facturas COD entregadas con saldo, de la más vieja a la
                       más nueva — es lo que hay que reclamarle a Melonn.
      · `sin_factura`  pedidos ENTREGADOS que no tienen factura de venta. Salió
                       mercancía, el cliente pagó, y no hay factura: eso lo
                       arregla contabilidad, no Melonn.
    """
    from backend.services import cartera_cod as cartera_svc
    try:
        data = melonn_svc.obtener_pedidos(forzar_refresh=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn error: {exc}")
    pedidos = [metricas_svc.clasificar(p) for p in data["pedidos"]]
    return cartera_svc.cruzar(pedidos)


@router.get("/mercadopago", response_model=PagosMPResponse)
def listar_pagos_mp(
    desde: Optional[str] = Query(default=None, description="YYYY-MM-DD, default últimos 30d"),
    hasta: Optional[str] = Query(default=None, description="YYYY-MM-DD, default hoy"),
    limit: int = Query(default=500, le=2000),
    _: CurrentUser = Depends(get_current_user),
) -> PagosMPResponse:
    """Pagos aprobados de MercadoPago en el rango dado (default últimos 30d)."""
    import mp_client as mp

    if not desde:
        desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not hasta:
        hasta = datetime.now().strftime("%Y-%m-%d")

    try:
        pagos_raw = mp.obtener_pagos(fecha_desde=desde, fecha_hasta=hasta, limit_total=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MercadoPago error: {exc}")

    pagos = [PagoMP(**p) for p in pagos_raw]
    return PagosMPResponse(
        pagos=pagos,
        total=len(pagos),
        valor_bruto_total=sum(p.valor_bruto for p in pagos),
        valor_neto_total=sum(p.valor_neto for p in pagos),
        comision_total=sum(p.comision for p in pagos),
        desde=desde,
        hasta=hasta,
    )


# ── Addi ────────────────────────────────────────────────────────────

class AddiStatusResponse(BaseModel):
    ok: bool
    error: Optional[str] = None
    base_url: Optional[str] = None
    token_path: Optional[str] = None


class TransaccionAddi(BaseModel):
    addi_id: str
    valor_bruto: float
    estado: str
    fecha: str
    email_cliente: str
    nombre_cliente: str
    external_ref: str


class TransaccionesAddiResponse(BaseModel):
    transacciones: list[TransaccionAddi]
    total: int
    valor_total: float
    desde: str
    hasta: str


@router.get("/addi/status", response_model=AddiStatusResponse)
def addi_status(_: CurrentUser = Depends(get_current_user)) -> AddiStatusResponse:
    """Verifica conectividad y credenciales Addi (intenta obtener access_token)."""
    r = addi_svc.status()
    return AddiStatusResponse(**r)


@router.get("/addi", response_model=TransaccionesAddiResponse)
def listar_addi(
    desde: Optional[str] = Query(default=None),
    hasta: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=2000),
    _: CurrentUser = Depends(get_current_user),
) -> TransaccionesAddiResponse:
    """Transacciones Addi en el rango dado (default últimos 30d)."""
    if not desde:
        desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not hasta:
        hasta = datetime.now().strftime("%Y-%m-%d")

    try:
        raw = addi_svc.obtener_transacciones(fecha_desde=desde, fecha_hasta=hasta, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Addi error: {exc}")

    transacciones = []
    for r in raw:
        r.pop("_raw", None)  # No exponemos el payload crudo al frontend
        transacciones.append(TransaccionAddi(**r))

    return TransaccionesAddiResponse(
        transacciones=transacciones,
        total=len(transacciones),
        valor_total=sum(t.valor_bruto for t in transacciones),
        desde=desde,
        hasta=hasta,
    )


# ═══════════════════════════════════════════════════════════════════════
# CONCILIACIÓN BANCARIA · el OS le pregunta al servicio de recon
# ═══════════════════════════════════════════════════════════════════════
#
# La conciliación vive en `male-denim-reconciliation` (Railway), con su propia
# API y su propio schema `recon` en la MISMA Supabase — que PostgREST no expone,
# así que la costura es HTTP. Ver backend/services/recon_client.py para el por qué.
#
# Estos endpoints son un PROXY a propósito: la API key del servicio de
# conciliación no puede viajar al navegador. El OS la guarda y responde ya
# masticado.
#
# Ninguno devuelve 5xx si el otro servicio está caído: responden
# `disponible: false` con el motivo, y la pantalla lo dice. Un tablero de plata
# que muestra ceros sin avisar es peor que uno que muestra el error.

@router.get("/conciliacion/estado")
def conciliacion_estado(_: CurrentUser = Depends(get_current_user)) -> dict:
    """¿Está conectado el módulo de conciliación bancaria?"""
    from backend.services import recon_client
    return recon_client.salud()


@router.get("/conciliacion/resumen")
def conciliacion_resumen(
    forzar: bool = Query(default=False, description="Ignora el caché de 90s"),
    _: CurrentUser = Depends(get_current_user),
) -> dict:
    """Pendiente por plataforma, cruces hechos y excepciones abiertas.

    `por_plataforma` es la respuesta a "cuánto esperar de cada pasarela": el dato
    que el OS no podía calcular solo, porque el eslabón de la consignación vive
    en el otro servicio.
    """
    from backend.services import recon_client
    return recon_client.resumen(forzar=forzar)


@router.get("/conciliacion/liquidaciones")
def conciliacion_liquidaciones(
    limite: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(get_current_user),
) -> dict:
    """Los lotes de liquidación: cada consignación agrupada por pasarela.

    Trae `descompuesto`: un lote sin el detalle de los pedidos que lo componen se
    vería igual que uno cuadrado al peso, y no es lo mismo.
    """
    from backend.services import recon_client
    return recon_client.liquidaciones(limite=limite)


@router.get("/conciliacion/excepciones")
def conciliacion_excepciones(
    limite: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(get_current_user),
) -> dict:
    """Lo que el motor no pudo cuadrar — la lista de trabajo real."""
    from backend.services import recon_client
    return recon_client.excepciones(limite=limite)
