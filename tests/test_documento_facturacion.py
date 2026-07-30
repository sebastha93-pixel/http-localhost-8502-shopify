"""Con que comprobante se emite la factura del reemplazo en tienda.

Los prefijos de las cajas (FV-6/11/12) NO se pueden usar por API: Siigo
responde `document_settings` — "The id cannot be used". Son rangos DIAN del
punto de venta y su consecutivo lo lleva la caja; meter facturas ahi desde
fuera romperia la numeracion.

Mientras se habilita la resolucion de FV-5 «Cambios», el reemplazo se
factura con FV-1. Cambiar a FV-5 debe ser una variable de entorno.

LO QUE NO CAMBIA: la BODEGA sigue siendo la del punto. El prefijo dice quien
factura; la bodega dice de donde sale la prenda, y sale de esa tienda.
"""
from backend.services import tiendas


def test_por_defecto_se_factura_con_fv1():
    assert tiendas.documento_para_facturar("florida_caja1") == 11810
    assert tiendas.documento_para_facturar("arrayanes") == 11810


def test_no_usa_el_prefijo_de_la_caja():
    """FV-11 (31433) es justo el que Siigo rechaza."""
    assert tiendas.documento_para_facturar("florida_caja1") != tiendas.DOC_FV11


def test_se_cambia_a_fv5_por_entorno(monkeypatch):
    """El dia que FV-5 tenga resolucion: una variable, cero codigo."""
    monkeypatch.setenv("SIIGO_DOC_FACTURA_CAMBIO", "27154")
    assert tiendas.documento_para_facturar("florida_caja1") == 27154


def test_una_variable_basura_no_tumba_la_facturacion(monkeypatch):
    monkeypatch.setenv("SIIGO_DOC_FACTURA_CAMBIO", "no-es-un-numero")
    assert tiendas.documento_para_facturar("arrayanes") == 11810


def test_la_bodega_sigue_siendo_la_del_punto():
    """Lo que se factura sale del inventario de ESA tienda, no de MELONN."""
    assert tiendas.validar_para_facturar("florida_caja1")["bodega_id"] == 48
    assert tiendas.validar_para_facturar("arrayanes")["bodega_id"] == 37


def test_el_prefijo_de_la_caja_sigue_sirviendo_para_la_nota_credito():
    """La NC SI acepta FV-11 como factura referenciada: eso no se toco."""
    assert tiendas.obtener("florida_caja1")["documento_factura_id"] == tiendas.DOC_FV11
