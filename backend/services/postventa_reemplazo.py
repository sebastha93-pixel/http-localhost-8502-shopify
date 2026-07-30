"""
backend.services.postventa_reemplazo — Qué prenda se lleva la clienta.

En un cambio presencial la asesora elige la referencia nueva ahí mismo, con
la clienta enfrente. Lo que no puede pasar es facturar algo que esa tienda no
tiene: quedaría un documento fiscal emitido y una clienta esperando una prenda
inexistente, y el inventario descuadrado.

Por eso la disponibilidad se mide en la bodega de ESE punto. Que haya cuatro
en Arrayanes no sirve de nada si la clienta está en Florida.

Solo lectura sobre el inventario de Siigo.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("postventa_reemplazo")


def _talla_num(talla: str) -> tuple:
    """Para ordenar 4, 8, 10, 12 y no '10' antes que '4'."""
    t = (talla or "").strip()
    try:
        return (0, int(t))
    except ValueError:
        return (1, 0)


def opciones_con_stock(inventario: dict, bodega_nombre: str, *,
                       q: str = "", limite: int = 60) -> list[dict]:
    """Referencias que ESA tienda puede entregar hoy.

    `inventario` es lo que devuelve `siigo.inventario_por_bodega()`: cada fila
    trae `stock` como {nombre_bodega: cantidad}. Se filtra por la bodega del
    punto y se descarta lo que esté en cero.
    """
    filas = (inventario or {}).get("referencias") or []
    objetivo = (bodega_nombre or "").strip()
    if not objetivo:
        return []

    termino = (q or "").strip().lower()
    salida = []
    for f in filas:
        if not isinstance(f, dict):
            continue
        cant = (f.get("stock") or {}).get(objetivo)
        if not cant or cant <= 0:
            continue
        if termino:
            heno = " ".join(str(f.get(k) or "") for k in
                            ("code", "referencia", "nombre", "talla")).lower()
            if termino not in heno:
                continue
        salida.append({
            "code": f.get("code"),
            "referencia": f.get("referencia"),
            "talla": f.get("talla"),
            "nombre": f.get("nombre"),
            "stock": int(cant),
            "bodega": objetivo,
        })

    salida.sort(key=lambda o: (o.get("referencia") or "", _talla_num(o.get("talla"))))
    return salida[:limite]


def verificar_disponible(inventario: dict, bodega_nombre: str,
                         code: str) -> tuple[bool, str]:
    """¿Se puede entregar esta prenda en este punto?

    Devuelve False cuando no hay inventario que consultar: sin datos no se
    puede afirmar que haya, y facturar a ciegas es justo lo que se quiere
    evitar.
    """
    if not (inventario or {}).get("referencias"):
        return False, ("No se pudo leer el inventario de Siigo, así que no se "
                       "puede confirmar que la prenda esté disponible.")
    code = (code or "").strip()
    for o in opciones_con_stock(inventario, bodega_nombre):
        if o["code"] == code:
            return True, f"{o['stock']} disponible(s) en {bodega_nombre}"
    return False, (f"{code or 'La referencia'} no tiene existencias en "
                   f"{bodega_nombre}.")


# ── Qué hace la clienta con el crédito de la nota crédito ──────────────────
# La NC ya dejó un ANTICIPO a su nombre en Siigo. Solo hay dos caminos.
SALIDAS = ("reemplazo", "saldo_a_favor")


def decide_factura(salida: str) -> bool:
    """¿Esta salida emite factura de reemplazo?

    `saldo_a_favor` NO emite: el anticipo se queda a nombre de la clienta y se
    consume cuando vuelva. Emitir una factura ahí inventaría una venta.
    """
    if salida not in SALIDAS:
        raise ValueError(f"salida_invalida: {salida}. Permitidas: {SALIDAS}")
    return salida == "reemplazo"


def texto_saldo_a_favor(monto: float) -> str:
    """Lo que queda escrito en el historial del caso. Es el respaldo de la
    clienta cuando vuelva a reclamarlo, así que lleva el monto exacto."""
    return (f"La clienta deja ${monto:,.0f} como saldo a favor. No se emite "
            f"factura de reemplazo; el anticipo queda a su nombre en Siigo."
            ).replace(",", ".")
