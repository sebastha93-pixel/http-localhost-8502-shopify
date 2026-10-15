"""La promoción «la segunda prenda a $1.000». Pura.

LA REGLA (Sebastián, 2026-10-14): de las prendas del listado que lleva la
clienta, se ordenan de mayor a menor precio y, por cada par, la más barata
queda en el precio de la promoción. Con 3 prendas, una queda en $1.000; con
4, dos; con 5, dos.

Se cuenta por UNIDAD, no por línea: dos del mismo jean son un par.

La calcula IGUAL el servidor y la caja (`frontend/lib/pos/promo.ts`). La caja
la muestra; el servidor la vuelve a calcular al cerrar y es la que vale.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

__all__ = ["descuentos_segunda_a_precio", "referencia_de"]


def referencia_de(sku: str) -> str:
    """`93634-1T12` → `93634-1`. Lo que no trae talla es su propio código."""
    s = (sku or "").strip().upper()
    i = s.rfind("T")
    return s[:i] if i > 0 else s


def descuentos_segunda_a_precio(
        lineas: List[Tuple[str, int, int]], precio_promo: int) -> Dict[str, int]:
    """`lineas`: `(sku, cantidad, precio unitario)` de las que participan, en
    centavos. Devuelve `{sku: descuento total de esa línea}`.

    Una prenda que ya cuesta menos que el precio de la promoción no se
    «descuenta» hacia arriba: queda en lo que vale.
    """
    unidades = []
    for orden, (sku, cantidad, precio) in enumerate(lineas):
        unidades.extend((precio, orden, sku) for _ in range(max(int(cantidad), 0)))
    # De mayor a menor; a igual precio, en el orden del carrito.
    unidades.sort(key=lambda u: (-u[0], u[1]))
    descuentos: Dict[str, int] = {}
    for i in range(1, len(unidades), 2):
        precio, _, sku = unidades[i]
        rebaja = max(int(precio) - int(precio_promo), 0)
        if rebaja:
            descuentos[sku] = descuentos.get(sku, 0) + rebaja
    return descuentos
