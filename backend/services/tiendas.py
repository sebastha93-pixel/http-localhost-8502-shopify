"""
backend.services.tiendas — Puntos de venta físicos para el cambio omnicanal.

Una clienta compra online y va a cambiar a la tienda. El caso necesita saber:
  · con qué prefijo de factura vender desde ese punto (Florida FV-11/FV-12,
    Arrayanes FV-6),
  · a qué bodega ingresa la prenda devuelta,
  · con qué formas de pago se cobra el excedente allí.

Los ids son de la cuenta Siigo de la marca. Se pueden sobreescribir por env
(TIENDAS_JSON) sin tocar código, para que otra marca configure los suyos.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

log = logging.getLogger("tiendas")

# Formas de pago por punto (ids verificados en el descubrimiento Siigo).
_PAGO_DATAFONO_FLORIDA = 12244
_PAGO_CAJA_FLORIDA = 12243
_PAGO_DATAFONO_ARRAYANES = 8987
_PAGO_CAJA_ARRAYANES = 8282

# Bodegas de Siigo — ids REALES de la API, leídos de GET /warehouses.
#
# OJO: el número que se ve en la pantalla de Siigo NO es el id de la API.
# Estuvieron configuradas como 5 y 3 (los códigos visibles) y Siigo rechazó
# la nota crédito con "The warehouse doesn't exist: 5". Es el mismo patrón de
# los tipos de documento (FV-11 se ve como 11 y su id es 31433).
#
#   16 INSUMOS · 32 MELONN · 37 Arrayanes · 45 Segundas · 48 Florida
BODEGA_FLORIDA = 48
BODEGA_ARRAYANES = 37

# Tipos de documento por punto de venta. Siigo NO los expone en
# /document-types (devuelve 9 y faltan justo estos), así que se dedujeron de
# facturas reales con /siigo/prefijos:
#   FV-6  → 29192  (ej. FV-6-10703)
#   FV-11 → 31433  (ej. FV-11-1333)
#   FV-12 → 31434  (ej. FV-12-417)
DOC_FV6 = 29192
DOC_FV11 = 31433
DOC_FV12 = 31434

# ── Con qué comprobante se EMITE la factura del reemplazo ──────────────────
# Los prefijos de arriba sirven para IDENTIFICAR la compra y para que la nota
# crédito referencie la factura del punto. Pero NO se puede emitir con ellos:
#
#   POST /invoices  →  document_settings
#                      "The id cannot be used, you must verify the document
#                       settings"  ·  Params: ["document.id"]
#
# Y `/document-types` nunca los devuelve — esa ausencia era la señal, no un
# descuido. Son rangos DIAN de las cajas: su consecutivo lo lleva el punto de
# venta, y meterle facturas desde fuera rompería la numeración.
#
# Mientras se habilita la resolución de FV-5 «Factura de venta Cambios»
# (id 27154, hoy inactivo), el reemplazo se factura con FV-1. El día que FV-5
# esté listo basta poner SIIGO_DOC_FACTURA_CAMBIO=27154 en Railway.
DOC_FV1_ONLINE = 11810
DOC_FV5_CAMBIOS = 27154

# Un PUNTO DE VENTA es una caja: tiene su propio prefijo de facturación pero
# puede compartir bodega con otra caja de la misma tienda. Florida factura
# desde dos cajas (FV-11 y FV-12) y ambas descargan/ingresan a la bodega 48.
#
# `documento_factura_id` queda en None hasta confirmarlo con
# /siigo/tipos-documento: el sistema se niega a facturar con un id adivinado
# porque saldría con el prefijo de otro punto y descuadraría la numeración DIAN.
TIENDAS_DEFAULT: dict[str, dict] = {
    "florida_caja1": {
        "nombre": "Florida · Caja 1",
        "tienda": "Florida",
        "prefijo_factura": "FV-11",
        "documento_factura_id": DOC_FV11,
        "bodega_nombre": "Florida",
        "bodega_id": BODEGA_FLORIDA,
        "formas_pago": [
            {"id": _PAGO_DATAFONO_FLORIDA, "nombre": "Datáfono Florida"},
            {"id": _PAGO_CAJA_FLORIDA, "nombre": "Efectivo · Caja Florida"},
        ],
    },
    "florida_caja2": {
        "nombre": "Florida · Caja 2",
        "tienda": "Florida",
        "prefijo_factura": "FV-12",
        "documento_factura_id": DOC_FV12,
        "bodega_nombre": "Florida",
        "bodega_id": BODEGA_FLORIDA,     # misma bodega que la caja 1
        "formas_pago": [
            {"id": _PAGO_DATAFONO_FLORIDA, "nombre": "Datáfono Florida"},
            {"id": _PAGO_CAJA_FLORIDA, "nombre": "Efectivo · Caja Florida"},
        ],
    },
    "arrayanes": {
        "nombre": "Arrayanes",
        "tienda": "Arrayanes",
        "prefijo_factura": "FV-6",
        "documento_factura_id": DOC_FV6,
        "bodega_nombre": "Arrayanes",
        "bodega_id": BODEGA_ARRAYANES,
        "formas_pago": [
            {"id": _PAGO_DATAFONO_ARRAYANES, "nombre": "Datáfono Arrayanes"},
            {"id": _PAGO_CAJA_ARRAYANES, "nombre": "Efectivo · Caja Arrayanes"},
        ],
    },
}


def _config() -> dict[str, dict]:
    """Config efectiva. TIENDAS_JSON (env) se fusiona sobre el default."""
    base = {k: dict(v) for k, v in TIENDAS_DEFAULT.items()}
    crudo = os.environ.get("TIENDAS_JSON", "").strip()
    if not crudo:
        return base
    try:
        override = json.loads(crudo)
        for clave, datos in (override or {}).items():
            base.setdefault(clave, {}).update(datos or {})
    except Exception as e:  # noqa: BLE001
        log.warning(f"[tiendas] TIENDAS_JSON invalido, se ignora: {e}")
    return base


def listar() -> list[dict]:
    """Tiendas con su estado de configuración, para el selector del panel."""
    salida = []
    for clave, t in _config().items():
        salida.append({
            "clave": clave,
            "nombre": t.get("nombre"),
            "tienda": t.get("tienda"),
            "prefijo_factura": t.get("prefijo_factura"),
            "bodega_id": t.get("bodega_id"),
            "formas_pago": t.get("formas_pago") or [],
            "lista": bool(t.get("documento_factura_id") and t.get("bodega_id")),
            "falta": [c for c in ("documento_factura_id", "bodega_id")
                      if not t.get(c)],
        })
    return salida


def obtener(clave: str) -> Optional[dict]:
    return _config().get((clave or "").strip().lower())


def validar_para_facturar(clave: str) -> dict:
    """Devuelve la tienda lista para emitir, o explica qué falta.

    No se factura con ids adivinados: un documento equivocado sale con el
    prefijo de otro punto de venta y descuadra la numeración DIAN.
    """
    t = obtener(clave)
    if t is None:
        raise ValueError(f"tienda_desconocida: {clave}")
    faltan = [c for c in ("documento_factura_id", "bodega_id") if not t.get(c)]
    if faltan:
        raise ValueError(
            f"tienda_sin_configurar: a {t.get('nombre')} le falta {', '.join(faltan)}. "
            f"Descúbrelos con /siigo/tipos-documento y /siigo/bodegas y cárgalos "
            f"en TIENDAS_JSON.")
    return t


def forma_pago_valida(clave: str, payment_id: int) -> bool:
    """La forma de pago debe ser de esa tienda (no la caja de la otra)."""
    t = obtener(clave)
    if not t:
        return False
    return any(int(p["id"]) == int(payment_id) for p in (t.get("formas_pago") or []))


def bodegas_invalidas(bodegas_siigo: list[dict]) -> Optional[list[dict]]:
    """Puntos de venta cuya bodega NO sirve para emitir en Siigo.

    Siigo exige que la bodega "exista en Siigo nube y esté activa". Si no,
    rechaza el documento con `invalid_reference`. Peor: mientras el campo iba
    mal formado, Siigo lo descartaba en silencio y el error no aparecía nunca
    —el inventario simplemente no se movía.

    Devuelve **None** si no se pudo consultar Siigo: sin datos no se puede
    afirmar que la configuración esté bien, y decir "todo ok" sería mentir.
    """
    if not bodegas_siigo:
        return None
    activas = {int(b["id"]) for b in bodegas_siigo
               if b.get("id") is not None and b.get("active", True)}
    existentes = {int(b["id"]) for b in bodegas_siigo if b.get("id") is not None}

    malas = []
    for clave, t in _config().items():
        bod = t.get("bodega_id")
        if bod is None:
            continue
        bod = int(bod)
        if bod not in existentes:
            motivo = "no_existe"
        elif bod not in activas:
            motivo = "inactiva"
        else:
            continue
        malas.append({"tienda": clave, "nombre": t.get("nombre"),
                      "bodega_id": bod, "motivo": motivo})
    return malas


def documento_para_facturar(clave: str) -> int:
    """Comprobante con el que SÍ se puede emitir por API.

    Ojo: esto solo decide el PREFIJO. La bodega sigue siendo la del punto
    (`bodega_id`), así que la prenda nueva sale del inventario de esa tienda
    aunque la factura lleve otro consecutivo.
    """
    crudo = os.environ.get("SIIGO_DOC_FACTURA_CAMBIO", "").strip()
    if crudo:
        try:
            return int(crudo)
        except ValueError:
            log.warning(f"[tiendas] SIIGO_DOC_FACTURA_CAMBIO invalido "
                        f"({crudo!r}), se usa FV-1")
    return DOC_FV1_ONLINE


def pagos_ajenos(clave: str, pagos: list[dict]) -> list[int]:
    """Medios de pago que NO son de esa caja.

    Cobrar en el datáfono de Florida un cambio de Arrayanes descuadra las dos
    cajas a la vez. El ANTICIPO se exceptúa: lo pone el sistema al aplicar el
    crédito de la nota crédito, no la cajera, y no entra al arqueo.
    """
    from backend.services.fiscal_logic import ANTICIPO_CLIENTES_ID
    malos = []
    for p in (pagos or []):
        pid = int(p.get("id") or 0)
        if not pid or pid == ANTICIPO_CLIENTES_ID:
            continue
        if not forma_pago_valida(clave, pid):
            malos.append(pid)
    return malos


def centro_costo_de(clave: str) -> Optional[int]:
    """Centro de costos del punto, si está configurado.

    FV-5 «Cambios» lo exige (`cost_center_obligatorio: true`) y no trae uno
    por defecto. Va por punto de venta a propósito: así el cambio queda
    contabilizado en la tienda donde ocurrió.

    Devuelve None mientras no se configure — y con FV-1, que no lo pide, todo
    sigue funcionando. Los ids se leen de GET /cost-centers; el número que se
    ve en la pantalla de Siigo NO sirve (ya nos pasó con bodegas y documentos).
    """
    t = obtener(clave) or {}
    v = t.get("centro_costo_id")
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        log.warning(f"[tiendas] centro_costo_id invalido en {clave}: {v!r}")
        return None
