"""La búsqueda de una factura en Siigo por su marca, contra un Siigo que se
porta COMO SE MIDIÓ el 2026-11-18 — no como uno supondría.

Lo medido, contra la cuenta real (`GET /invoices`, comprobante 80108):

    date_start=2026-11-17 & date_end=2026-11-17  → 0 facturas
    date_start=2026-11-17 & date_end=2026-11-18  → las 7 del 17, ninguna del 18
    created_start=2026-11-17                     → todas las creadas desde el 17,
                                                   lleven la fecha que lleven

O sea: `date_end` NO incluye su día. La búsqueda vieja pedía «del día de la
venta al día de la venta» y Siigo contestaba vacío SIEMPRE: el POS creía que la
factura no había llegado y la volvía a mandar. Así salieron 41 facturas de más
entre el 15-oct y el 17-nov (15 ventas), todas aceptadas por la DIAN.

Y lo segundo que se midió: la factura que Siigo crea pero no alcanza a mandar
a la DIAN ese día queda con la fecha del día en que por fin sale (las del 17
quedaron con fecha 18). Buscar por la fecha de la factura no sirve; se busca
por la de CREACIÓN.
"""
import asyncio

import pytest

from backend.modules.retail.infrastructure.siigo import emisor_factura

MARCA = "POS ARRPOS-44446 · 01M7XXXXXXXXXXXXXXXXXXXXXX"
DOC = 80107


def _siigo_medido(facturas):
    """Un `siigo_get` que filtra como filtra el de verdad."""
    pedidos = []

    def siigo_get(ruta, params=None):
        p = dict(params or {})
        pedidos.append(p)
        assert ruta == "/invoices"
        filas = [f for f in facturas if f["document"]["id"] == p.get("document_id")]
        if "date_start" in p:
            filas = [f for f in filas if f["date"] >= p["date_start"]]
        if "date_end" in p:                       # EXCLUYE su día
            filas = [f for f in filas if f["date"] < p["date_end"]]
        if "created_start" in p:
            filas = [f for f in filas
                     if f["metadata"]["created"][:10] >= p["created_start"]]
        tam = int(p.get("page_size", 25))
        ini = (int(p.get("page", 1)) - 1) * tam
        return {"results": filas[ini:ini + tam],
                "pagination": {"total_results": len(filas)}}
    return siigo_get, pedidos


def _factura(*, fecha, creada, marca=MARCA, numero=556):
    return {"id": f"id-{numero}", "document": {"id": DOC}, "prefix": "ARRT",
            "number": numero, "date": fecha, "observations": marca,
            "metadata": {"created": creada}}


def _buscar(monkeypatch, facturas, *, dia_venta="2026-11-17"):
    from backend.services import siigo
    falso, pedidos = _siigo_medido(facturas)
    monkeypatch.setattr(siigo, "siigo_get", falso)
    hallada = asyncio.run(emisor_factura.SiigoIO().buscar_por_marca(
        documento_id=DOC, desde=dia_venta, marca=MARCA))
    return hallada, pedidos


def test_encuentra_la_factura_del_mismo_dia_de_la_venta(monkeypatch):
    """EL CASO DE TODOS LOS DÍAS, y el que estaba roto: se vendió hoy, el
    envío se cortó, la factura SÍ está en Siigo con fecha de hoy."""
    f = _factura(fecha="2026-11-17", creada="2026-11-17T15:56:18.487")
    hallada, _ = _buscar(monkeypatch, [f])
    assert hallada is not None and hallada["number"] == 556


def test_encuentra_la_que_siigo_dejo_con_fecha_del_dia_siguiente(monkeypatch):
    """Creada el 17, enviada a la DIAN el 18: Siigo le cambia la fecha."""
    f = _factura(fecha="2026-11-18", creada="2026-11-17T15:56:18.487")
    hallada, _ = _buscar(monkeypatch, [f])
    assert hallada is not None and hallada["number"] == 556


def test_no_adopta_la_factura_de_otra_venta(monkeypatch):
    f = _factura(fecha="2026-11-17", creada="2026-11-17T15:56:18.487",
                 marca="POS ARRPOS-44445 · 01M7YYYYYYYYYYYYYYYYYYYYYY")
    hallada, _ = _buscar(monkeypatch, [f])
    assert hallada is None


def test_la_busca_aunque_haya_mas_de_una_pagina(monkeypatch):
    otras = [_factura(fecha="2026-11-17", creada="2026-11-17T10:00:00",
                      marca=f"POS ARRPOS-{n} · x", numero=n) for n in range(1, 131)]
    f = _factura(fecha="2026-11-17", creada="2026-11-17T15:56:18.487")
    hallada, pedidos = _buscar(monkeypatch, otras + [f])
    assert hallada is not None and hallada["number"] == 556
    assert len(pedidos) == 2


@pytest.mark.parametrize("creada", ["2026-11-16T23:59:59", "2026-11-17T00:00:01"])
def test_un_dia_de_margen_por_el_reloj_de_siigo(monkeypatch, creada):
    """La hora de creación la pone Siigo con SU reloj; una venta de la
    medianoche no puede quedar por fuera por unos segundos."""
    f = _factura(fecha="2026-11-17", creada=creada)
    hallada, _ = _buscar(monkeypatch, [f])
    assert hallada is not None
