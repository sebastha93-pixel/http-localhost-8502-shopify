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

# Configuración por defecto. `documento_factura_id` y `bodega_id` quedan en
# None hasta confirmarlos con /siigo/tipos-documento y /siigo/bodegas: el
# sistema se niega a facturar con un id adivinado.
TIENDAS_DEFAULT: dict[str, dict] = {
    "florida": {
        "nombre": "Florida",
        "prefijo_factura": "FV-11",
        "documento_factura_id": None,
        "bodega_nombre": "Florida",
        "bodega_id": None,
        "formas_pago": [
            {"id": _PAGO_DATAFONO_FLORIDA, "nombre": "Datáfono Florida"},
            {"id": _PAGO_CAJA_FLORIDA, "nombre": "Efectivo · Caja Florida"},
        ],
    },
    "arrayanes": {
        "nombre": "Arrayanes",
        "prefijo_factura": "FV-6",
        "documento_factura_id": None,
        "bodega_nombre": "Arrayanes",
        "bodega_id": None,
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
            "prefijo_factura": t.get("prefijo_factura"),
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
