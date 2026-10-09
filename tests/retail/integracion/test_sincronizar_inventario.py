"""El inventario del POS, igual al de Siigo — contra un Siigo de mentira.

Tres cosas que esto no puede hacer mal: poner en cero media tienda por una
lectura cortada, devolverle al estante lo que se acaba de vender, y cambiar un
saldo sin dejar su asiento.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")


def _p(code, nombre, arrayanes=0, florida=0, precio=149900, **extra):
    base = {"code": code, "name": f"{code} {nombre}", "stock_control": True,
            "tax_included": True, "account_group": {"name": "SKINNY"},
            "prices": [{"price_list": [{"value": precio}]}],
            "warehouses": [{"id": 37, "name": "Arrayanes", "quantity": arrayanes},
                           {"id": 48, "name": "Florida", "quantity": florida}],
            "additional_fields": {"barcode": code}}
    base.update(extra)
    return base


@pytest.fixture()
def base():
    from backend.modules.retail.migraciones.runner import aplicar, revertir
    from backend.modules.retail.sembrar_tiendas import sembrar
    revertir(URL)
    aplicar(URL)
    sembrar(URL, aplicar=True)
    motor = create_engine(URL.replace("+psycopg", "+psycopg"), future=True)
    yield motor
    motor.dispose()
    revertir(URL)


def _sinc(productos, **kw):
    from backend.modules.retail.sincronizar_inventario import sincronizar
    kw.setdefault("precios_de_lista", lambda codigos: {})   # sin salir a Shopify
    return sincronizar(URL, productos=productos, aplicar=True, **kw)


def _saldos(motor, ubicacion="tienda:arrayanes"):
    with motor.connect() as c:
        return {r[0]: r[1] for r in c.execute(text("""
            SELECT v.sku, s.cantidad FROM retail.stock_ubicacion s
              JOIN retail.variantes v ON v.id = s.variante_id
             WHERE s.ubicacion_id = :u"""), {"u": ubicacion})}


def test_cada_tienda_recibe_SU_bodega(base):
    r = _sinc([_p("26602-1T6", "JEAN FLARE", arrayanes=2, florida=5),
               _p("95613-1T12", "JEAN WIDE", arrayanes=8)])
    assert _saldos(base) == {"26602-1T6": 2, "95613-1T12": 8}
    assert _saldos(base, "tienda:florida") == {"26602-1T6": 5}
    assert r["tiendas"]["arrayanes"]["nuevos"] == 2
    assert r["tiendas"]["arrayanes"]["unidades"] == 10


def test_las_bolsas_entran_con_el_codigo_de_siigo(base):
    _sinc([_p("5353", "BOLSA MALE PEQUEÑA", arrayanes=97, precio=1000),
           _p("5354", "BOLSA MALE GRANDE", arrayanes=109, precio=2000)])
    assert _saldos(base) == {"5353": 97, "5354": 109}
    with base.connect() as c:
        assert c.execute(text("SELECT precio_con_iva FROM retail.variantes "
                              "WHERE sku = '5353'")).scalar() == 100000


def test_lo_que_llega_sube_lo_que_sale_baja_y_cada_cambio_deja_asiento(base):
    _sinc([_p("26602-1T6", "JEAN", arrayanes=2), _p("95613-1T12", "JEAN", arrayanes=8)])
    r = _sinc([_p("26602-1T6", "JEAN", arrayanes=6),      # llegó mercancía
               _p("95613-1T12", "JEAN", arrayanes=0)])    # se trasladó toda
    assert _saldos(base) == {"26602-1T6": 6, "95613-1T12": 0}
    t = r["tiendas"]["arrayanes"]
    assert (t["saldos_cambiados"], t["puestos_en_cero"]) == (1, 1)
    with base.connect() as c:
        libro = c.execute(text("""
            SELECT delta, saldo_despues, motivo, referencia_tipo
              FROM retail.movimientos_inventario
             WHERE ubicacion_id = 'tienda:arrayanes' ORDER BY id""")).all()
    assert [tuple(m) for m in libro] == [
        (2, 2, "ajuste_conteo", "sincronizacion_siigo"),
        (8, 8, "ajuste_conteo", "sincronizacion_siigo"),
        (4, 6, "ajuste_conteo", "sincronizacion_siigo"),
        (-8, 0, "ajuste_conteo", "sincronizacion_siigo")]


def test_sin_cambios_no_escribe_nada(base):
    productos = [_p("26602-1T6", "JEAN", arrayanes=2)]
    _sinc(productos)
    r = _sinc(productos)
    t = r["tiendas"]["arrayanes"]
    assert (t["nuevos"], t["saldos_cambiados"], t["puestos_en_cero"],
            t["datos_actualizados"]) == (0, 0, 0, 0)
    with base.connect() as c:
        assert c.execute(text(
            "SELECT count(*) FROM retail.movimientos_inventario")).scalar() == 1


def test_un_precio_que_cambio_en_siigo_cambia_en_la_caja(base):
    _sinc([_p("26602-1T6", "JEAN", arrayanes=2)])
    r = _sinc([_p("26602-1T6", "JEAN", arrayanes=2, precio=129900)])
    assert r["tiendas"]["arrayanes"]["datos_actualizados"] == 1
    with base.connect() as c:
        assert c.execute(text("SELECT precio_con_iva FROM retail.variantes"
                              )).scalar() == 12990000


def test_NO_le_devuelve_al_estante_lo_que_se_vendio_y_aun_no_se_factura(base):
    """Siigo baja su inventario cuando entra la FACTURA. Entre el cobro y la
    factura todavía cuenta la prenda: copiar su número la haría reaparecer."""
    _sinc([_p("26602-1T6", "JEAN", arrayanes=2)])
    with base.begin() as c:
        vid = c.execute(text("SELECT id FROM retail.variantes")).scalar()
        c.execute(text("UPDATE retail.stock_ubicacion SET cantidad = 1"))
        c.execute(text("""
            INSERT INTO retail.sesiones_caja (id, tienda_id, caja_id,
                numero_turno, estado, base_inicial, abierta_por, abierta_en)
            VALUES ('01JQ8X4T5N6P0F1R8S9V0W1X2Y', 'arrayanes', 'arrayanes_caja1',
                    1, 'abierta', 0, 'maria', now())"""))
        c.execute(text("""
            INSERT INTO retail.ventas (id, numero, prefijo, consecutivo,
                tienda_id, caja_id, sesion_id, cajera_id, estado,
                estado_fiscal, total, pagado, cerrada_en)
            VALUES ('01JQ8X4T5N7V0F1R8S9V0W1X2Y', 'ARRPOS-1', 'ARRPOS', 1,
                    'arrayanes', 'arrayanes_caja1',
                    '01JQ8X4T5N6P0F1R8S9V0W1X2Y', 'maria', 'cerrada',
                    'pendiente', 14990000, 14990000, now())"""))
        c.execute(text("""
            INSERT INTO retail.venta_lineas (id, venta_id, orden, variante_id,
                sku, descripcion, cantidad, precio_unitario, total_linea,
                base_gravable, iva_monto)
            VALUES ('01JQ8X4T5N7V0F1R8S9V0W1X3Y', '01JQ8X4T5N7V0F1R8S9V0W1X2Y',
                    1, :v, '26602-1T6', 'Jean', 1, 14990000, 14990000,
                    12596639, 2393361)"""), {"v": vid})

    r = _sinc([_p("26602-1T6", "JEAN", arrayanes=2)])     # Siigo aún dice 2
    assert _saldos(base) == {"26602-1T6": 1}
    assert r["tiendas"]["arrayanes"]["sin_facturar_descontadas"] == 1

    # Entra la factura: Siigo baja a 1 y la venta ya no está pendiente.
    with base.begin() as c:
        c.execute(text("UPDATE retail.ventas SET estado_fiscal = 'emitido'"))
    _sinc([_p("26602-1T6", "JEAN", arrayanes=1)])
    assert _saldos(base) == {"26602-1T6": 1}


def test_una_lectura_que_dejaria_media_tienda_en_cero_NO_se_aplica(base):
    from backend.modules.retail.sincronizar_inventario import LecturaSospechosa
    todos = [_p(f"9{n:04d}-1T6", "JEAN", arrayanes=3) for n in range(40)]
    _sinc(todos)
    with pytest.raises(LecturaSospechosa, match="media"):
        _sinc(todos[:5])
    assert len([s for s in _saldos(base).values() if s == 3]) == 40


def test_el_ensayo_no_escribe(base):
    from backend.modules.retail.sincronizar_inventario import sincronizar
    r = sincronizar(URL, productos=[_p("26602-1T6", "JEAN", arrayanes=2)],
                    aplicar=False, precios_de_lista=lambda c: {})
    assert r["tiendas"]["arrayanes"]["nuevos"] == 1 and r["aplicado"] is False
    assert _saldos(base) == {}


def test_dos_prendas_con_la_misma_etiqueta_no_tumban_la_sincronizacion(base):
    """El código de barras es único en la tabla. La segunda se queda sin él y
    se sigue encontrando por su SKU."""
    _sinc([_p("26602-1T6", "JEAN", arrayanes=2),
           _p("26602-1T8", "JEAN", arrayanes=1,
              additional_fields={"barcode": "26602-1T6"})])
    assert _saldos(base) == {"26602-1T6": 2, "26602-1T8": 1}


def test_la_prenda_con_precio_en_cero_en_siigo_ENTRA_con_el_de_la_tienda_en_linea(base):
    """`94609-1`: sin esto la caja no la encuentra aunque esté colgada."""
    pedidos = []

    def lista(codigos):
        pedidos.append(list(codigos))
        return {"94609-1T6": 149900}

    r = _sinc([_p("94609-1T6", "JEAN WIDE LEG", arrayanes=4, florida=3, precio=0),
               _p("26602-1T6", "JEAN", arrayanes=2)], precios_de_lista=lista)
    assert pedidos == [["94609-1T6"]]            # una sola consulta, sólo lo que falta
    assert _saldos(base) == {"94609-1T6": 4, "26602-1T6": 2}
    assert _saldos(base, "tienda:florida") == {"94609-1T6": 3}
    with base.connect() as c:
        assert c.execute(text("SELECT precio_con_iva FROM retail.variantes "
                              "WHERE sku = '94609-1T6'")).scalar() == 14990000
    assert r["tiendas"]["arrayanes"]["precio_prestado"] == [
        "94609-1T6 $149.900 (tienda_en_linea)"]


def test_si_la_tienda_en_linea_no_contesta_lo_demas_se_sincroniza_igual(base):
    r = _sinc([_p("94609-1T6", "JEAN", arrayanes=4, precio=0),
               _p("26602-1T6", "JEAN", arrayanes=2)],
              precios_de_lista=lambda codigos: {})
    assert _saldos(base) == {"26602-1T6": 2}
    assert r["tiendas"]["arrayanes"]["fuera"] == 1
