"""Cambiar una prenda comprada ANTES del POS, con su factura de Siigo POS.

Las tiendas facturaron con Siigo POS hasta el 2026-10-08. Esas ventas no están
en el POS y sus clientas van a volver. La factura se busca en Siigo, se trae
como registro —sin mover inventario ni caja— y se le hace el cambio.

La factura de la prueba tiene la FORMA REAL de `GET /invoices` (medida contra
la cuenta el 2026-10-10 con TARR-11451).
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

SESION = "01JQ8X4T5N6P0F1R8S9V0W1X2Y"

FACTURA = {
    "id": "aaaa1111-2222-3333-4444-555566667777",
    "document": {"id": 29192}, "name": "FV-6-11451", "prefix": "TARR",
    "number": 11451, "date": "2026-10-07", "cost_center": 677, "seller": 842,
    "customer": {"id": "c-1", "identification": "1037000111",
                 "name": ["Laura", "Gómez Ríos"], "branch_office": 0},
    "total": 285820.0, "balance": 0.0,
    "items": [
        # Un jean que el POS conoce, con 10 % de descuento.
        {"id": "i1", "code": "26602-1T6", "description": "JEAN FLARE GRIS HUMO",
         "quantity": 1.0, "price": 125966.39,
         "discount": {"percentage": 10.0, "value": 12596.64},
         "taxes": [{"id": 6352, "name": "IVA 19%", "percentage": 19.0,
                    "value": 21540.25}],
         "warehouse": {"id": 37, "name": "Arrayanes"}, "total": 134910.0},
        # Dos de otro, sin descuento.
        {"id": "i2", "code": "95613-1T12", "description": "JEAN WIDE LEG OSCURO",
         "quantity": 2.0, "price": 62983.19,
         "taxes": [{"id": 6352, "value": 23932.62}],
         "warehouse": {"id": 37, "name": "Arrayanes"}, "total": 149900.0},
        # El «genérico» de precio libre: el POS no lo tiene en catálogo.
        {"id": "i3", "code": "101", "description": "GENERICO-", "quantity": 1.0,
         "price": 848.74, "taxes": [{"id": 6352, "value": 161.26}],
         "warehouse": {"id": 37, "name": "Arrayanes"}, "total": 1010.0},
    ],
    "payments": [{"id": 8987, "name": "Datafono Arrayanes", "value": 285820.0}],
    "stamp": {"status": "Accepted", "cufe": "f" * 96},
}
EN_LINEA = {**FACTURA, "id": "bbbb1111-2222-3333-4444-555566667777",
            "document": {"id": 11810}, "name": "FV-1-67700", "prefix": "FE",
            "number": 67700}


def _p(code, arrayanes=0, florida=0):
    return {"code": code, "name": f"{code} JEAN", "stock_control": True,
            "tax_included": True, "account_group": {"name": "SKINNY"},
            "prices": [{"price_list": [{"value": 149900}]}],
            "warehouses": [{"id": 37, "name": "Arrayanes", "quantity": arrayanes},
                           {"id": 48, "name": "Florida", "quantity": florida}],
            "additional_fields": {"barcode": code}}


@pytest_asyncio.fixture()
async def tienda(monkeypatch):
    from backend.core.security import CurrentUser, get_current_user
    from backend.modules.retail.infrastructure.siigo import (
        clientes_siigo, facturas_tienda,
    )
    from backend.modules.retail.interfaces.http import dependencias
    from backend.modules.retail.interfaces.http.router import router
    from backend.modules.retail.migraciones.runner import aplicar, revertir
    from backend.modules.retail.sembrar_tiendas import sembrar
    from backend.modules.retail.sincronizar_inventario import sincronizar

    revertir(URL)
    aplicar(URL)
    sembrar(URL, aplicar=True)
    sincronizar(URL, aplicar=True, precios_de_lista=lambda c: {}, productos=[
        _p("26602-1T6", arrayanes=2, florida=4), _p("95613-1T12", arrayanes=8)])
    os.environ["RETAIL_DATABASE_URL"] = URL
    dependencias.reiniciar()
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "apagado")

    # ── Siigo de mentira ──
    pedidas = []

    def buscar(q, **kw):
        pedidas.append(q)
        if q.replace(".", "") in ("1037000111",):
            return [FACTURA]
        return [FACTURA] if "FV-6-11451" in facturas_tienda.nombres_a_buscar(q) else []
    monkeypatch.setattr(facturas_tienda, "buscar", buscar)
    monkeypatch.setattr(facturas_tienda, "leer", lambda sid: {
        FACTURA["id"]: FACTURA, EN_LINEA["id"]: EN_LINEA}[sid])
    monkeypatch.setattr(clientes_siigo, "buscar_por_documento", lambda d: {
        "siigo_customer_id": "c-1", "tipo_documento": "CC",
        "numero_documento": d, "dv": None, "nombre": "Laura",
        "apellido": "Gómez Ríos", "telefono": "3001112233",
        "correo": "laura@correo.com", "direccion": "", "ciudad": "",
        "activo_en_siigo": True})

    motor = create_engine(URL, future=True)
    with motor.begin() as c:
        c.execute(text(
            "INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas) "
            "VALUES ('maria','María R.','{arrayanes,florida}')"))

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="maria", email="m@male.com", nombre="María R.", rol="user",
        permisos={"retail": ["ver", "modificar"]})
    with TestClient(app) as c:
        # Turno abierto en ARRAYANES con $200.000 de base.
        r = c.post("/api/retail/caja/turno", json={
            "sesion_id": SESION, "tienda_id": "arrayanes",
            "caja_id": "arrayanes_caja1"})
        assert r.status_code == 200, r.text
        yield {"c": c, "motor": motor, "pedidas": pedidas}
    motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _uno(t, sql, **p):
    with t["motor"].connect() as c:
        return c.execute(text(sql), p).scalar()


def _todas(t, sql, **p):
    with t["motor"].connect() as c:
        return [tuple(f) for f in c.execute(text(sql), p)]


def _buscar(t, q):
    r = t["c"].get("/api/retail/devoluciones/buscar", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()


def _traer(t, siigo_id=FACTURA["id"], caja=None):
    return t["c"].post("/api/retail/devoluciones/traer-de-siigo",
                       json={"siigo_id": siigo_id, "caja_id": caja})


# ── Encontrarla ─────────────────────────────────────────────────────────────

def test_el_numero_impreso_se_traduce_al_codigo_que_siigo_entiende():
    from backend.modules.retail.infrastructure.siigo.facturas_tienda import (
        nombres_a_buscar as n,
    )
    assert n("TARR-11451") == n("tarr 11451") == n("TARR11451") == ["FV-6-11451"]
    assert n("FL-2077") == ["FV-11-2077"] and n("FP-685") == ["FV-12-685"]
    assert n("FV-6-11451") == n("fv 6 11451") == ["FV-6-11451"]
    # Sólo el número: puede ser de cualquiera de los comprobantes…
    assert n("11451") == ["FV-6-11451", "FV-11-11451", "FV-12-11451",
                          "FV-1-11451"]
    # …pero se busca sólo en la tienda que pregunta: tres peticiones a Siigo
    # tardaron un minuto en vivo.
    # tardaron un minuto en vivo. La tienda en línea va siempre, de última.
    assert n("11451", "arrayanes") == ["FV-6-11451", "FV-1-11451"]
    assert n("2077", "florida") == ["FV-11-2077", "FV-12-2077", "FV-1-2077"]
    assert n("TARR-11451", "florida") == ["FV-6-11451"]   # con prefijo, donde sea
    # La tienda en línea, por su prefijo.
    assert n("FE-67700") == n("fe 67700") == n("FV-1-67700") == ["FV-1-67700"]
    # Lo que no es de tienda ni de la página no se busca aquí.
    assert n("ARRT-5") == [] and n("FV-3-10") == []


def test_una_factura_de_antes_del_pos_APARECE_al_buscarla(tienda):
    for como in ("TARR-11451", "11451", "FV-6-11451", "1.037.000.111"):
        [v] = _buscar(tienda, como)
        assert v["siigo_id"] == FACTURA["id"], como
        assert (v["factura"], v["tienda"], v["total_centavos"]) == (
            "TARR-11451", "Arrayanes", 28_582_000)
        assert v["cliente"] == "Laura Gómez Ríos"
        assert v["fecha"] == "2026-10-07"


# ── Traerla ─────────────────────────────────────────────────────────────────

def test_traerla_NO_mueve_inventario_ni_caja(tienda):
    """La plata entró y la prenda salió hace semanas, en otro sistema. Lo que
    entra al POS es el registro."""
    antes = _todas(tienda, "SELECT ubicacion_id, sum(cantidad) FROM "
                           "retail.stock_ubicacion GROUP BY 1 ORDER BY 1")
    r = _traer(tienda)
    assert r.status_code == 200, r.text
    assert r.json()["numero"] == "TARR-11451"

    assert _todas(tienda, "SELECT ubicacion_id, sum(cantidad) FROM "
                          "retail.stock_ubicacion GROUP BY 1 ORDER BY 1") == antes
    assert _uno(tienda, "SELECT count(*) FROM retail.movimientos_inventario "
                        "WHERE motivo = 'venta'") == 0
    assert _uno(tienda, "SELECT count(*) FROM retail.outbox") == 0

    # No es del turno abierto: cuelga de uno histórico, cerrado y en cero.
    [(origen, estado, fiscal, total, sesion)] = _todas(
        tienda, "SELECT origen, estado, estado_fiscal, total, sesion_id "
                "FROM retail.ventas")
    assert (origen, estado, fiscal, total) == ("siigo_pos", "cerrada", "emitido",
                                              28_582_000)
    assert sesion != SESION
    assert _todas(tienda, "SELECT estado, numero_turno, base_inicial FROM "
                          "retail.sesiones_caja WHERE id = :s", s=sesion) == [
        ("cerrada", 0, 0)]


def test_cada_linea_entra_por_lo_que_la_clienta_PAGO(tienda):
    _traer(tienda)
    lineas = _todas(tienda, """
        SELECT sku, cantidad, precio_unitario, descuento_monto, total_linea,
               iva_monto, base_gravable
          FROM retail.venta_lineas ORDER BY orden""")
    assert lineas == [
        ("26602-1T6", 1, 14_990_000, 1_499_000, 13_491_000, 2_154_025, 11_336_975),
        ("95613-1T12", 2, 7_495_000, 0, 14_990_000, 2_393_262, 12_596_738),
        ("101", 1, 101_000, 0, 101_000, 16_126, 84_874)]
    # precio × cantidad − descuento = total, en todas.
    assert all(p * c - d == t for _, c, p, d, t, _, _ in lineas)


def test_guarda_el_numero_el_cufe_y_el_id_de_siigo(tienda):
    """Es lo que después le dice a Postventa qué factura acreditar."""
    _traer(tienda)
    assert _todas(tienda, "SELECT tipo, estado, numero, cufe, documento_externo_id "
                          "FROM retail.documentos_fiscales") == [
        ("factura_electronica", "emitido", "TARR-11451", "f" * 96, FACTURA["id"])]
    assert _uno(tienda, "SELECT c.numero_documento FROM retail.ventas v "
                        "JOIN retail.clientes c ON c.id = v.cliente_id") == "1037000111"


def test_la_prenda_que_el_pos_no_tiene_se_crea_APAGADA(tienda):
    """El genérico entra para poder recibirlo, y no aparece para venderse."""
    _traer(tienda)
    assert _todas(tienda, "SELECT sku, activa FROM retail.variantes "
                          "WHERE sku = '101'") == [("101", False)]
    refs = tienda["c"].get("/api/retail/catalogo/referencias", params={
        "ubicacion_id": "tienda:arrayanes", "q": "101"}).json()["referencias"]
    assert all(r["referencia"] != "101" for r in refs)


def test_buscarla_dos_veces_no_la_duplica(tienda):
    a, b = _traer(tienda).json(), _traer(tienda).json()
    assert a["venta_id"] == b["venta_id"]
    assert _uno(tienda, "SELECT count(*) FROM retail.ventas") == 1
    # Y una vez traída, la búsqueda la devuelve como venta del POS.
    [v] = _buscar(tienda, "TARR-11451")
    assert v["venta_id"] == a["venta_id"] and not v.get("siigo_id")


def test_la_compra_de_la_tienda_en_linea_se_trae_a_la_caja_QUE_ATIENDE(tienda):
    """No es de ninguna caja: queda en la tienda donde la clienta la cambia."""
    r = _traer(tienda, EN_LINEA["id"], caja="florida_caja1")
    assert r.status_code == 200, r.text
    assert r.json()["numero"] == "FE-67700"
    assert r.json()["tienda"] == "Tienda en línea"
    assert _todas(tienda, "SELECT numero, tienda_id, caja_id, origen "
                          "FROM retail.ventas") == [
        ("FE-67700", "florida", "florida_caja1", "siigo_pos")]


def test_sin_decir_la_caja_la_de_la_tienda_en_linea_NO_se_trae(tienda):
    r = _traer(tienda, EN_LINEA["id"])
    assert r.status_code == 400
    assert _uno(tienda, "SELECT count(*) FROM retail.ventas") == 0


def test_la_compra_en_linea_NO_devuelve_efectivo_del_cajon(tienda):
    venta_id = _traer(tienda, EN_LINEA["id"], caja="arrayanes_caja1"
                      ).json()["venta_id"]
    d = tienda["c"].get("/api/retail/devoluciones/ticket/FE-67700",
                        params={"caja_id": "arrayanes_caja1"}).json()
    assert d["puede_efectivo"] is False
    assert "tienda en línea" in d["sin_efectivo_porque"]

    def devolver(reembolso, did):
        return tienda["c"].post("/api/retail/devoluciones", json={
            "devolucion_id": did, "venta_id": venta_id,
            "seleccion": {"26602-1T6": 1}, "motivo": "talla",
            "reembolso": reembolso, "caja_id": "arrayanes_caja1"})

    r = devolver("efectivo", "01JQ8X4T5NDV0F1R8S9V0W1X2Y")
    assert r.status_code == 400 and "tienda en línea" in r.json()["detail"]["mensaje"]
    assert _stock(tienda, "26602-1T6", "tienda:arrayanes") == 2

    # Con crédito sí: y la prenda entra a la tienda que atiende.
    r = devolver("credito_tienda", "01JQ8X4T5NDV0F1R8S9V0W1X2Z")
    assert r.status_code == 200, r.text
    assert _stock(tienda, "26602-1T6", "tienda:arrayanes") == 3
    assert _uno(tienda, "SELECT count(*) FROM retail.movimientos_caja "
                        "WHERE tipo LIKE 'devolucion%'") == 0


# ── Hacerle el cambio ───────────────────────────────────────────────────────

def _devolver(t, seleccion, reembolso="efectivo", caja="arrayanes_caja1",
              devolucion="01JQ8X4T5NDV0F1R8S9V0W1X2Y"):
    venta_id = _traer(t).json()["venta_id"]
    return t["c"].post("/api/retail/devoluciones", json={
        "devolucion_id": devolucion, "venta_id": venta_id,
        "seleccion": seleccion, "motivo": "talla", "reembolso": reembolso,
        "caja_id": caja})


def _stock(t, sku, ubicacion):
    return _uno(t, """SELECT s.cantidad FROM retail.stock_ubicacion s
                        JOIN retail.variantes v ON v.id = s.variante_id
                       WHERE v.sku = :s AND s.ubicacion_id = :u""",
                s=sku, u=ubicacion)


def test_el_ticket_se_abre_con_lo_que_se_puede_devolver(tienda):
    _traer(tienda)
    r = tienda["c"].get("/api/retail/devoluciones/ticket/TARR-11451",
                        params={"caja_id": "arrayanes_caja1"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_centavos"] == 28_582_000 and d["puede_efectivo"] is True
    assert [(l["sku"], l["cantidad_devolvible"],
             l["precio_unitario_con_iva_centavos"]) for l in d["lineas"]] == [
        ("26602-1T6", 1, 13_491_000), ("95613-1T12", 2, 7_495_000),
        ("101", 1, 101_000)]


def test_la_prenda_devuelta_ENTRA_a_la_tienda_que_hace_el_cambio(tienda):
    """Vendida en Arrayanes y devuelta en Arrayanes, en la misma caja. La
    venta traída no tiene asiento de inventario, y la prenda se quedaba sin
    entrar a ninguna parte."""
    r = _devolver(tienda, {"26602-1T6": 1})
    assert r.status_code == 200, r.text
    d = r.json()
    # Se devuelve lo PAGADO ($134.910, con su descuento), no el precio de lista.
    assert d["total_centavos"] == 13_491_000 and d["salio_del_cajon"] is True
    assert _stock(tienda, "26602-1T6", "tienda:arrayanes") == 3     # tenía 2
    assert _stock(tienda, "26602-1T6", "tienda:florida") == 4       # intacta


def test_si_el_cambio_se_hace_en_la_OTRA_tienda_entra_a_esa(tienda):
    """Comprada en Arrayanes, devuelta en Florida: la prenda queda en Florida,
    que es donde está físicamente."""
    r = _devolver(tienda, {"26602-1T6": 1}, reembolso="credito_tienda",
                  caja="florida_caja1")
    assert r.status_code == 200, r.text
    assert _stock(tienda, "26602-1T6", "tienda:florida") == 5       # tenía 4
    assert _stock(tienda, "26602-1T6", "tienda:arrayanes") == 2     # intacta
    assert _uno(tienda, "SELECT tienda_id FROM retail.devoluciones") == "florida"


def test_la_plata_sale_del_cajon_que_atiende_y_el_arqueo_lo_sabe(tienda):
    _devolver(tienda, {"95613-1T12": 2})                # 2 × $74.950
    movimientos = _todas(tienda, "SELECT tipo, monto FROM retail.movimientos_caja "
                                 "WHERE sesion_id = :s AND tipo = 'devolucion'",
                         s=SESION)
    assert movimientos == [("devolucion", -14_990_000)]


def test_no_se_devuelve_mas_de_lo_que_se_compro(tienda):
    assert _devolver(tienda, {"26602-1T6": 1}).status_code == 200
    r = _devolver(tienda, {"26602-1T6": 1},
                  devolucion="01JQ8X4T5NDW0F1R8S9V0W1X2Y")
    assert r.status_code == 400


def test_el_caso_de_postventa_lleva_la_factura_de_siigo(tienda):
    """La nota crédito la hace Postventa, y necesita saber contra qué."""
    _devolver(tienda, {"26602-1T6": 1})
    [(tipo, payload)] = _todas(tienda, "SELECT tipo, payload FROM retail.outbox")
    assert tipo == "abrir_caso_postventa"
    assert payload["numero_venta"] == "TARR-11451"
    assert payload["tienda_id"] == "arrayanes"
