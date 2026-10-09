"""Sacar el catálogo de una tienda del inventario de Siigo.

Las trampas de este archivo no se inventaron: salieron cargando las 681
prendas de Arrayanes el 2026-10-01, y cada una habría llegado al mostrador.

Corre SIN base y SIN red: `filas_de_productos` es una función pura sobre la
respuesta de Siigo. Lo que se prueba es la traducción, que es donde está el
riesgo — pedirle productos a Siigo ya lo hace otro código.
"""
from __future__ import annotations

from backend.modules.retail.catalogo_desde_siigo import (
    filas_de_productos,
    ref_talla,
)


def _producto(**cambios):
    base = {
        "code": "26602-1T6",
        "name": "26602-1T6 JEAN FLARE GRIS HUMO CON DIRTY.",
        "account_group": {"id": 1354, "name": "CAMPANA"},
        "stock_control": True,
        "tax_included": True,
        "prices": [{"currency_code": "COP",
                    "price_list": [{"name": "Precio de venta 1",
                                    "value": 149900}]}],
        "warehouses": [{"id": 32, "name": "MELONN", "quantity": 8.0},
                       {"id": 37, "name": "Arrayanes", "quantity": 2.0},
                       {"id": 48, "name": "Florida", "quantity": 3.0}],
        "additional_fields": {"barcode": "26602-1T6"},
    }
    base.update(cambios)
    return base


# ── Lo normal ───────────────────────────────────────────────────────────────

def test_toma_la_cantidad_de_SU_bodega_y_no_la_total():
    """`available_quantity` suma Melonn y las dos tiendas. Cargar eso haría
    que la cajera ofrezca trece prendas donde hay dos."""
    filas, problemas = filas_de_productos([_producto()], "Arrayanes")
    assert problemas == []
    assert filas[0]["cantidad"] == 2
    assert filas_de_productos([_producto()], "Florida")[0][0]["cantidad"] == 3


def test_el_nombre_pierde_el_codigo_que_siigo_le_repite_adelante():
    fila = filas_de_productos([_producto()], "Arrayanes")[0][0]
    assert fila["nombre"] == "JEAN FLARE GRIS HUMO CON DIRTY"
    assert fila["referencia"] == "26602-1" and fila["talla"] == "6"
    assert fila["categoria"] == "Campana"


def test_lo_que_no_tiene_existencia_en_esa_bodega_no_entra():
    """Un catálogo con todo el inventario de la marca hace que se ofrezca lo
    que no está en la percha."""
    sin_stock = _producto(warehouses=[{"name": "Arrayanes", "quantity": 0}])
    filas, problemas = filas_de_productos([sin_stock], "Arrayanes")
    assert filas == [] and problemas == []     # no es un problema: no está


def test_la_bolsa_SE_VENDE_y_entra_con_su_codigo_tal_cual():
    """`5353` no tiene talla que extraer, pero va cobrada en casi todas las
    facturas de la tienda. Su SKU es el código de Siigo: «5353TU» sería un
    producto que Siigo no conoce y la factura se rechazaría."""
    bolsa = _producto(code="5353", name="BOLSA MALE PEQUEÑA",
                      prices=[{"price_list": [{"value": 1000}]}],
                      additional_fields={"barcode": "5353"})
    [fila], problemas = filas_de_productos([bolsa], "Arrayanes")
    assert problemas == []
    assert (fila["sku"], fila["referencia"], fila["talla"]) == ("5353", "5353", "U")
    assert fila["precio"] == 1000 and fila["cantidad"] == 2


def test_lo_que_no_tiene_precio_de_venta_se_reporta():
    """`010` (sin IVA incluido), `101` (sin precio) y un llavero a $1."""
    filas, problemas = filas_de_productos(
        [_producto(code="010", name="CAJA", tax_included=False),
         _producto(code="101", name="GENERICO", prices=[]),
         _producto(code="002LLAVERO", name="LLAVERO",
                   prices=[{"price_list": [{"value": 1}]}])], "Arrayanes")
    assert filas == [] and len(problemas) == 3


def test_la_bodega_se_puede_pedir_por_su_id():
    assert filas_de_productos([_producto()], 48)[0][0]["cantidad"] == 3
    assert filas_de_productos([_producto()], 37)[0][0]["sku"] == "26602-1T6"


# ── EL PRECIO, que es donde duele ───────────────────────────────────────────

def test_el_precio_marcado_con_iva_se_toma_tal_cual():
    """Es el de la etiqueta: $149.900, no ×1,19."""
    assert filas_de_productos([_producto()], "Arrayanes")[0][0]["precio"] == 149900


def test_un_producto_SIN_iva_incluido_no_se_carga_a_ciegas():
    """UNO de 682 estaba marcado distinto y su precio salía $190.281 — el
    único que no terminaba en 900. Cargarlo es vender a un precio inventado:
    se reporta y se deja fuera para que alguien lo mire en Siigo."""
    raro = _producto(code="H31503-1T30", tax_included=False,
                     prices=[{"price_list": [{"value": 159900}]}])
    filas, problemas = filas_de_productos([raro], "Arrayanes")
    assert filas == []
    assert "SIN IVA incluido" in problemas[0] and "190.281" in problemas[0]


def test_sin_precio_no_se_carga():
    """Pasa con la referencia 94609-1 entera. Sin precio no hay venta."""
    filas, problemas = filas_de_productos(
        [_producto(code="94609-1T4", prices=[])], "Arrayanes")
    assert filas == [] and "sin precio" in problemas[0]


# ── EL CÓDIGO DE BARRAS, que es lo que escanea la pistola ───────────────────

def test_el_codigo_de_la_etiqueta_viaja_aunque_no_sea_el_sku():
    """A `42606-1T10` le falta la «T» en la etiqueta y a toda la `13625-2` le
    pusieron el código de la `13625-1`. Son 11 de 687 en Arrayanes: sin este
    campo, la pistola escanea esas prendas y no pasa nada."""
    sin_t = _producto(code="42606-1T10",
                      additional_fields={"barcode": "42606-110"})
    otra_ref = _producto(code="13625-2T4",
                         additional_fields={"barcode": "13625-1T4"})
    filas, _ = filas_de_productos([sin_t, otra_ref], "Arrayanes")
    assert [f["codigo_barras"] for f in filas] == ["42606-110", "13625-1T4"]


def test_un_sku_repetido_se_avisa():
    """Dos filas del mismo SKU se pisarían al cargar, y la segunda gana en
    silencio: el stock quedaría con la cantidad equivocada."""
    _, problemas = filas_de_productos([_producto(), _producto()], "Arrayanes")
    assert any("aparece 2 veces" in p for p in problemas)


# ── El parser del SKU ───────────────────────────────────────────────────────

def test_ref_talla_entiende_numeros_y_letras():
    assert ref_talla("92633-1T6") == ("92633-1", "6")
    assert ref_talla("95613-1T12") == ("95613-1", "12")
    assert ref_talla("70112-2TM") == ("70112-2", "M")
    assert ref_talla("010") == ("", "")
    assert ref_talla("") == ("", "")
