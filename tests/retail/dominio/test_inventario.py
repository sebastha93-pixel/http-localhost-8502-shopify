"""SaldoUbicacion — el inventario como libro contable, no como campo mutable.

`stock = stock - 1` no se puede auditar. Una suma de asientos sí: el saldo
siempre debe poder reconstruirse sumando el libro mayor (INV-I4), y un job
diario lo verifica.

La decisión que más se nota en la tienda es INV-I2: **estando sin internet se
permite el negativo**. Bloquear la venta de una prenda que la clienta tiene en
la mano pierde plata real para proteger un dato. El negativo se registra, se
alerta, y se corrige en el conteo.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.modules.retail.domain.inventario.errores import SinStock
from backend.modules.retail.domain.inventario.motivo import Motivo
from backend.modules.retail.domain.inventario.saldo import SaldoUbicacion
from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

AHORA = datetime(2026, 8, 5, 19, 42, tzinfo=timezone.utc)
UBI = "tienda:florida"
VAR = "01JQ8X4T5N6P7R8S9V0W1X2Y3Z"


def saldo(cantidad=5) -> SaldoUbicacion:
    return SaldoUbicacion(ubicacion_id=UBI, variante_id=VAR, cantidad=cantidad)


# ── Reservas ────────────────────────────────────────────────────────────────

def test_reservar_baja_lo_disponible_pero_no_la_cantidad():
    """La prenda sigue en la tienda hasta que la venta se cierra."""
    s = saldo(5)
    s.reservar(2, referencia="venta:abc", ahora=AHORA)
    assert s.disponible() == 3
    assert s.cantidad == 5
    assert s.reservado() == 2


def test_no_se_reserva_mas_de_lo_disponible():
    """INV-I1. Estando en línea no se promete lo que no hay."""
    s = saldo(2)
    with pytest.raises(SinStock) as e:
        s.reservar(3, referencia="venta:abc", ahora=AHORA)
    assert "2" in str(e.value)
    assert s.reservado() == 0  # no quedó reservado a medias


def test_dos_reservas_compiten_por_la_ultima_unidad():
    """La segunda caja que intenta vender la última prenda no lo logra."""
    s = saldo(1)
    s.reservar(1, referencia="venta:caja1", ahora=AHORA)
    with pytest.raises(SinStock):
        s.reservar(1, referencia="venta:caja2", ahora=AHORA)


def test_sin_internet_si_se_permite_el_negativo():
    """INV-I2. La prenda física ya está en la mano de la clienta.

    Bloquear la venta pierde plata real para proteger un dato que de todos
    modos está desactualizado. Se registra el negativo y se alerta.
    """
    s = saldo(0)
    reserva = s.reservar(1, referencia="venta:offline", ahora=AHORA,
                         permitir_negativo=True)
    assert reserva.sobregiro is True
    assert s.disponible() == -1


def test_liberar_una_reserva_devuelve_lo_disponible():
    s = saldo(5)
    r = s.reservar(2, referencia="venta:abc", ahora=AHORA)
    s.liberar(r.id)
    assert s.disponible() == 5
    assert s.reservado() == 0


def test_las_reservas_de_un_carrito_abandonado_vencen():
    """INV-I6. Sin esto, el stock se evapora en carritos muertos."""
    s = saldo(5)
    s.reservar(2, referencia="venta:abandonada", ahora=AHORA)
    assert s.disponible() == 3

    vencidas = s.purgar_reservas_vencidas(
        ahora=AHORA + timedelta(minutes=16), ttl_minutos=15)
    assert len(vencidas) == 1
    assert s.disponible() == 5


def test_una_reserva_reciente_no_vence():
    s = saldo(5)
    s.reservar(2, referencia="venta:viva", ahora=AHORA)
    assert s.purgar_reservas_vencidas(
        ahora=AHORA + timedelta(minutes=5), ttl_minutos=15) == []
    assert s.disponible() == 3


# ── Asientos del libro mayor ────────────────────────────────────────────────

def test_confirmar_la_reserva_descarga_el_stock_y_deja_asiento():
    s = saldo(5)
    r = s.reservar(2, referencia="venta:abc", ahora=AHORA)
    mov = s.confirmar(r.id, usuario_id="maria", ahora=AHORA)

    assert s.cantidad == 3
    assert s.reservado() == 0
    assert mov.delta == -2
    assert mov.motivo is Motivo.VENTA
    assert mov.saldo_despues == 3
    assert mov.referencia_id == "venta:abc"


def test_todo_asiento_lleva_referencia_trazable():
    """INV-I3. Un asiento sin origen no se puede auditar."""
    s = saldo(5)
    with pytest.raises(ReglaDeNegocio):
        s.ingresar(3, motivo=Motivo.INGRESO_COMPRA, referencia="",
                   usuario_id="maria", ahora=AHORA)


def test_ingresar_sube_el_saldo():
    s = saldo(5)
    mov = s.ingresar(3, motivo=Motivo.INGRESO_COMPRA,
                     referencia="remision:123", usuario_id="maria", ahora=AHORA)
    assert s.cantidad == 8
    assert mov.delta == 3


def test_un_asiento_es_inmutable():
    """INV-I5. Corregir es un movimiento contrario, no una edición."""
    s = saldo(5)
    mov = s.ingresar(3, motivo=Motivo.INGRESO_COMPRA, referencia="r:1",
                     usuario_id="maria", ahora=AHORA)
    with pytest.raises(Exception):
        mov.delta = 99  # type: ignore[misc]


def test_ajustar_por_conteo_genera_el_asiento_de_la_diferencia():
    s = saldo(5)
    mov = s.ajustar(3, motivo_texto="conteo físico del 5 de agosto",
                    usuario_id="laura", ahora=AHORA)
    assert s.cantidad == 3
    assert mov.delta == -2
    assert mov.motivo is Motivo.AJUSTE_CONTEO


def test_un_ajuste_sin_explicacion_no_se_acepta():
    s = saldo(5)
    with pytest.raises(ReglaDeNegocio):
        s.ajustar(3, motivo_texto="", usuario_id="laura", ahora=AHORA)


def test_ajustar_a_la_misma_cantidad_no_genera_asiento():
    """Un conteo que confirma el saldo no es un movimiento."""
    s = saldo(5)
    assert s.ajustar(5, motivo_texto="conteo físico", usuario_id="laura",
                     ahora=AHORA) is None
    assert s.cantidad == 5


# ── INV-I4: el saldo tiene que ser la suma del libro ────────────────────────

def test_el_saldo_se_reconstruye_sumando_el_libro():
    """El job diario que detecta un saldo materializado corrupto."""
    s = saldo(0)
    asientos = [
        s.ingresar(10, motivo=Motivo.INGRESO_COMPRA, referencia="r:1",
                   usuario_id="maria", ahora=AHORA),
    ]
    r = s.reservar(3, referencia="venta:abc", ahora=AHORA)
    asientos.append(s.confirmar(r.id, usuario_id="maria", ahora=AHORA))
    asientos.append(s.ajustar(6, motivo_texto="conteo", usuario_id="laura",
                              ahora=AHORA))

    assert s.cantidad == 6
    assert SaldoUbicacion.saldo_segun_libro(asientos) == 6
    assert s.cuadra_con_el_libro(asientos)


def test_detecta_un_saldo_que_no_cuadra_con_el_libro():
    s = saldo(0)
    asientos = [s.ingresar(10, motivo=Motivo.INGRESO_COMPRA, referencia="r:1",
                           usuario_id="maria", ahora=AHORA)]
    s.cantidad = 99  # alguien tocó la tabla por fuera
    assert not s.cuadra_con_el_libro(asientos)


# ── Bordes ──────────────────────────────────────────────────────────────────

def test_no_se_reserva_una_cantidad_que_no_es_positiva():
    s = saldo(5)
    for mala in [0, -1]:
        with pytest.raises(ReglaDeNegocio):
            s.reservar(mala, referencia="venta:abc", ahora=AHORA)


def test_confirmar_una_reserva_que_no_existe():
    s = saldo(5)
    with pytest.raises(ReglaDeNegocio):
        s.confirmar("no-existe", usuario_id="maria", ahora=AHORA)


def test_no_se_confirma_dos_veces_la_misma_reserva():
    """Reintentar el cierre de una venta no puede descargar el stock dos veces."""
    s = saldo(5)
    r = s.reservar(2, referencia="venta:abc", ahora=AHORA)
    s.confirmar(r.id, usuario_id="maria", ahora=AHORA)
    with pytest.raises(ReglaDeNegocio):
        s.confirmar(r.id, usuario_id="maria", ahora=AHORA)
    assert s.cantidad == 3
