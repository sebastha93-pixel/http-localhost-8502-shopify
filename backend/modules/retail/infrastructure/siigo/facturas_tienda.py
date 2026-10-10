"""Buscar en Siigo las facturas que las tiendas emitieron con Siigo POS.

Son las de ANTES del 2026-10-09. El POS no las tiene, y la clienta que compró
esas semanas va a volver a cambiar la prenda.

LOS TRES COMPROBANTES DE TIENDA, medidos contra la cuenta el 2026-10-10:

    FV-6   prefijo TARR  id 29192  Arrayanes
    FV-11  prefijo FL    id 31433  Florida · caja 1
    FV-12  prefijo FP    id 31434  Florida · caja 2

Lo que la clienta trae impreso es el prefijo y el número (`TARR-11451`); el
filtro de Siigo es por `name`, que es el código interno (`FV-6-11451`). Aquí
se traduce de uno a otro.

Y LA TIENDA EN LÍNEA (2026-10-10):

    FV-1   prefijo FE    id 11810  maledenim.com

La clienta que compró por la página también llega a la tienda a cambiar. Esa
factura no es de ninguna caja: se trae a la caja QUE ATIENDE, y la prenda
entra al inventario de esa tienda. Lo que NO se hace es devolverle efectivo
del cajón —pagó por otro canal—: sale con otra prenda o con crédito.

Mayoristas sigue fuera: su cambio se tramita por Postventa.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional

__all__ = ["COMPROBANTES", "PREFIJO_EN_LINEA", "nombres_a_buscar", "buscar",
           "leer", "es_de_tienda"]

PREFIJO_EN_LINEA = "FE"

#  código FV → (prefijo impreso, id del comprobante, tienda, caja)
COMPROBANTES = {
    6:  {"prefijo": "TARR", "documento_id": 29192, "tienda_id": "arrayanes",
         "caja_id": "arrayanes_caja1"},
    11: {"prefijo": "FL", "documento_id": 31433, "tienda_id": "florida",
         "caja_id": "florida_caja1"},
    12: {"prefijo": "FP", "documento_id": 31434, "tienda_id": "florida",
         "caja_id": "florida_caja2"},
    #  Sin tienda ni caja: son las de quien atiende el cambio.
    1:  {"prefijo": PREFIJO_EN_LINEA, "documento_id": 11810, "tienda_id": None,
         "caja_id": None},
}
_POR_PREFIJO = {v["prefijo"]: k for k, v in COMPROBANTES.items()}
_POR_DOCUMENTO = {v["documento_id"]: v for v in COMPROBANTES.values()}


def es_de_tienda(factura: dict) -> Optional[dict]:
    """El comprobante de esa factura si la caja le puede hacer el cambio
    (tiendas y tienda en línea), o `None` si es de otro canal."""
    return _POR_DOCUMENTO.get(int((factura.get("document") or {}).get("id") or 0))


def nombres_a_buscar(q: str, tienda_id: Optional[str] = None) -> List[str]:
    """De lo que se tecleó, los `name` de Siigo que hay que probar.

        TARR-11451, tarr11451  → ['FV-6-11451']
        FV-6-11451             → ['FV-6-11451']
        FE-67700               → ['FV-1-67700']
        11451, en Arrayanes    → ['FV-6-11451', 'FV-1-11451']

    Vacío si no parece el número de una factura que la caja pueda cambiar.

    EL NÚMERO SUELTO SE BUSCA SÓLO EN LA TIENDA QUE PREGUNTA. Probar los tres
    comprobantes son tres peticiones a una cuenta que aguanta una por segundo
    y que comparte ese cupo con todo lo demás: medido en vivo, «2077» tardó
    un minuto. La clienta casi siempre vuelve a donde compró; si compró en la
    otra tienda, el papel trae el prefijo y con él se encuentra de una.
    La tienda en línea se prueba siempre, de última: no es de ninguna tienda.
    """
    crudo = (q or "").strip().upper()
    m = re.fullmatch(r"FV[\s-]*(\d+)[\s-]*(\d+)", crudo)
    if m:
        return [f"FV-{int(m.group(1))}-{int(m.group(2))}"] \
            if int(m.group(1)) in COMPROBANTES else []
    m = re.fullmatch(r"([A-Z]+)[\s-]*(\d+)", crudo)
    if m:
        codigo = _POR_PREFIJO.get(m.group(1))
        return [f"FV-{codigo}-{int(m.group(2))}"] if codigo else []
    if re.fullmatch(r"\d{1,7}", crudo):
        return [f"FV-{c}-{int(crudo)}" for c, v in COMPROBANTES.items()
                if not tienda_id or v["tienda_id"] in (tienda_id, None)]
    return []


def buscar(q: str, *, tienda_id: Optional[str] = None,
           tope: int = 20) -> List[dict]:
    """Las facturas de tienda que casan con lo tecleado: por número, o todas
    las de una cédula. `tienda_id` es la tienda que pregunta."""
    from backend.services.siigo import siigo_get

    salida: List[dict] = []
    vistos = set()

    def agregar(filas):
        for f in filas or []:
            if f.get("id") in vistos or es_de_tienda(f) is None:
                continue
            vistos.add(f.get("id"))
            salida.append(f)

    nombres = nombres_a_buscar(q, tienda_id)
    for i, nombre in enumerate(nombres):
        if i:
            time.sleep(1.1)           # la cuenta aguanta ~1 petición por segundo
        r = siigo_get("/invoices", {"name": nombre, "page": 1, "page_size": 5})
        # El filtro se COMPRUEBA: Siigo a veces lo ignora y devuelve la lista.
        agregar([f for f in (r.get("results") or []) if f.get("name") == nombre])

    digitos = re.sub(r"\D", "", q or "")
    if len(digitos) >= 6 and digitos == re.sub(r"[\s.]", "", (q or "").strip()):
        if nombres:
            time.sleep(1.1)
        r = siigo_get("/invoices", {"customer_identification": digitos,
                                    "page": 1, "page_size": 50})
        agregar([f for f in (r.get("results") or [])
                 if str((f.get("customer") or {}).get("identification")) == digitos])

    salida.sort(key=lambda f: f.get("date") or "", reverse=True)
    return salida[:tope]


def leer(siigo_id: str) -> dict:
    from backend.services.siigo import siigo_get
    return siigo_get(f"/invoices/{siigo_id}")
