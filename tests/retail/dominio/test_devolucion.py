"""Las reglas que protegen una devolución.

UNA DEVOLUCIÓN NO ES UNA ANULACIÓN, y confundirlas es el error caro. La
anulación deshace una venta del turno EN CURSO: la plata vuelve del mismo
arqueo que la recibió y no hace falta documento fiscal (INV-V11). La
devolución llega días después, con la factura ya emitida y el arqueo de ese
día cerrado y firmado — necesita nota crédito, y por eso el caso lo abre
Postventa, que es donde vive el motor fiscal.

Lo que el agregado protege es lo que Postventa no puede saber: cuánto se
vendió de verdad, cuánto se devolvió ya, y si lo que la cajera está pidiendo
cabe dentro de eso.
"""
from __future__ import annotations

import pytest

from backend.modules.retail.domain.devolucion.devolucion import (
    Devolucion,
    LineaDevuelta,
    LineaVendida,
)
from backend.modules.retail.domain.devolucion.motivo import MotivoDevolucion
from backend.modules.retail.domain.devolucion.reembolso import Reembolso
from backend.modules.retail.domain.venta.errores import ReglaDeNegocio


def _vendidas(**kw) -> list[LineaVendida]:
    """Dos líneas: 2 jeans de $100.000 y 1 short de $50.000."""
    base = {"jean": 2, "short": 1}
    base.update(kw)
    return [
        LineaVendida(sku="MD1042-10", cantidad=base["jean"],
                     precio_unitario_con_iva_centavos=10_000_000),
        LineaVendida(sku="MD1043-12", cantidad=base["short"],
                     precio_unitario_con_iva_centavos=5_000_000),
    ]


def _armar(seleccion, *, vendidas=None, ya_devuelto=None,
           motivo=MotivoDevolucion.TALLA, reembolso=Reembolso.EFECTIVO,
           venta_anulada=False, turno_abierto=True) -> Devolucion:
    return Devolucion.armar(
        venta_id="01J000000000000000000000AB",
        numero="FL-1537",
        lineas_vendidas=vendidas if vendidas is not None else _vendidas(),
        ya_devuelto=ya_devuelto or {},
        seleccion=seleccion,
        motivo=motivo,
        reembolso=reembolso,
        moneda="COP",
        venta_anulada=venta_anulada,
        turno_abierto=turno_abierto,
    )


# ── Lo que se puede devolver ────────────────────────────────────────────────

def test_devolver_una_linea_cobra_lo_que_esa_linea_costo():
    d = _armar({"MD1042-10": 1})
    assert d.total.centavos == 10_000_000
    assert [(l.sku, l.cantidad) for l in d.lineas] == [("MD1042-10", 1)]


def test_el_total_suma_varias_lineas():
    d = _armar({"MD1042-10": 2, "MD1043-12": 1})
    assert d.total.centavos == 25_000_000


def test_el_iva_viaja_separado_porque_la_nota_credito_lo_exige():
    """La NC discrimina base e IVA. Se deriva del precio de vitrina línea por
    línea —nunca del total— por lo mismo que en la venta (INV-V12): sumar y
    después partir mete un peso de diferencia que a fin de mes es un
    descuadre que nadie sabe explicar."""
    d = _armar({"MD1042-10": 1})
    assert d.iva.centavos + d.base_gravable.centavos == d.total.centavos
    assert d.iva.centavos == 1_596_639


# ── INV-D1 · no se devuelve más de lo que se vendió ─────────────────────────

def test_no_se_devuelve_mas_cantidad_de_la_vendida():
    with pytest.raises(ReglaDeNegocio, match="se vendieron 2"):
        _armar({"MD1042-10": 3})


def test_no_se_devuelve_una_referencia_que_no_estaba_en_la_venta():
    with pytest.raises(ReglaDeNegocio, match="no está en la venta"):
        _armar({"MD9999-10": 1})


def test_lo_YA_DEVUELTO_descuenta_del_saldo():
    """La segunda visita. Sin esto, una clienta devuelve la misma prenda dos
    veces y se le paga dos veces — y en el libro de inventario entran dos
    unidades que sólo salieron una vez."""
    with pytest.raises(ReglaDeNegocio, match="queda 1"):
        _armar({"MD1042-10": 2}, ya_devuelto={"MD1042-10": 1})


def test_lo_ya_devuelto_deja_pasar_lo_que_todavia_cabe():
    d = _armar({"MD1042-10": 1}, ya_devuelto={"MD1042-10": 1})
    assert d.total.centavos == 10_000_000


def test_una_linea_agotada_por_devoluciones_previas_ya_no_se_puede_pedir():
    with pytest.raises(ReglaDeNegocio, match="ya se devolvió completa"):
        _armar({"MD1043-12": 1}, ya_devuelto={"MD1043-12": 1})


# ── INV-D2 · cantidades y selección ─────────────────────────────────────────

def test_no_se_admite_una_devolucion_vacia():
    with pytest.raises(ReglaDeNegocio, match="al menos un artículo"):
        _armar({})


def test_una_cantidad_en_cero_no_cuenta_como_seleccion():
    with pytest.raises(ReglaDeNegocio, match="al menos un artículo"):
        _armar({"MD1042-10": 0})


def test_una_cantidad_negativa_se_rechaza():
    with pytest.raises(ReglaDeNegocio, match="mayor que cero"):
        _armar({"MD1042-10": -1})


# ── INV-D3 · una venta anulada no se devuelve ───────────────────────────────

def test_una_venta_anulada_no_admite_devolucion():
    """Ya se deshizo entera y su plata volvió por el arqueo. Devolverla otra
    vez es pagar dos veces la misma prenda."""
    with pytest.raises(ReglaDeNegocio, match="anulada"):
        _armar({"MD1042-10": 1}, venta_anulada=True)


# ── INV-D4 · el reembolso en efectivo necesita caja abierta ─────────────────

def test_reembolso_en_efectivo_exige_turno_abierto():
    """No es burocracia: el efectivo sale de un cajón que en ese momento tiene
    que estar contado y bajo el nombre de alguien. Sin turno abierto no hay
    de dónde sacarlo ni a quién anotárselo."""
    with pytest.raises(ReglaDeNegocio, match="turno abierto"):
        _armar({"MD1042-10": 1}, reembolso=Reembolso.EFECTIVO,
               turno_abierto=False)


def test_los_otros_reembolsos_NO_exigen_turno():
    """Devolver al método original o dejar crédito en tienda no toca el cajón,
    así que no hay razón para pedir una caja abierta — y pedirla dejaría a la
    clienta esperando a que alguien abra turno para nada."""
    for r in (Reembolso.METODO_ORIGINAL, Reembolso.CREDITO_TIENDA):
        d = _armar({"MD1042-10": 1}, reembolso=r, turno_abierto=False)
        assert d.reembolso is r


def test_solo_el_efectivo_mueve_el_arqueo():
    """Lo que decide si hay movimiento de caja es el MÉTODO, no el monto."""
    assert _armar({"MD1042-10": 1}, reembolso=Reembolso.EFECTIVO).sale_del_cajon
    assert not _armar({"MD1042-10": 1},
                      reembolso=Reembolso.METODO_ORIGINAL).sale_del_cajon
    assert not _armar({"MD1042-10": 1},
                      reembolso=Reembolso.CREDITO_TIENDA).sale_del_cajon


# ── INV-D5 · motivo y método son obligatorios y cerrados ────────────────────

def test_el_motivo_tiene_que_ser_uno_de_los_cuatro():
    """Un campo libre aquí se llena de «cambio» y «devolución», que no dicen
    nada. El motivo es lo único que después permite saber si una referencia
    se devuelve por talla —problema de horma— o por defecto —problema de
    taller—, y eso cambia a quién se le reclama."""
    with pytest.raises(ValueError):
        MotivoDevolucion("porque si")


def test_los_cuatro_motivos_del_handoff_existen():
    assert {m.value for m in MotivoDevolucion} == {
        "talla", "defecto", "no_le_gusto", "cambio_modelo"}


def test_los_tres_reembolsos_del_handoff_existen():
    assert {r.value for r in Reembolso} == {
        "efectivo", "metodo_original", "credito_tienda"}


# ── Lo que el agregado entrega hacia afuera ─────────────────────────────────

def test_lleva_el_numero_de_la_venta_para_que_postventa_la_encuentre():
    d = _armar({"MD1042-10": 1})
    assert d.numero == "FL-1537"
    assert d.venta_id == "01J000000000000000000000AB"


def test_las_lineas_devueltas_conservan_su_precio_unitario():
    """El precio va con la LÍNEA y no se recalcula del catálogo: si la prenda
    subió de precio desde que se vendió, devolver al precio de hoy sería
    regalarle plata a la clienta —o quitársela—."""
    d = _armar({"MD1042-10": 2})
    assert d.lineas[0] == LineaDevuelta(
        sku="MD1042-10", cantidad=2,
        precio_unitario_con_iva_centavos=10_000_000)
