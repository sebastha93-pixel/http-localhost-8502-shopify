from backend.services import postventa_cliente as C


FACTURAS = {"results": [
    # Compra online, ya aceptada por la DIAN
    {"id": "f1", "name": "FV-1-64151", "date": "2026-07-20", "total": 149900,
     "document": {"id": 11810}, "customer": {"identification": "30384838"},
     "observations": "Orden Nº: 61208 - Medio de Pago: Wompi",
     "stamp": {"status": "Accepted"},
     "items": [{"code": "A-10", "description": "Jean flare", "price": 125966.39}]},
    # Compra en Florida Caja 1
    {"id": "f2", "name": "FV-11-1333", "date": "2026-07-25", "total": 189900,
     "document": {"id": 31433}, "customer": {"identification": "30384838"},
     "observations": "", "stamp": {"status": "Accepted"},
     "items": [{"code": "B-12", "description": "Jean recto", "price": 159579.83}]},
    # Compra de hoy: la DIAN aún no la acepta
    {"id": "f3", "name": "FV-1-64300", "date": "2026-07-28", "total": 159900,
     "document": {"id": 11810}, "customer": {"identification": "30384838"},
     "observations": "Orden Nº: 61300", "stamp": {"status": "InProcess"},
     "items": [{"code": "C-8", "description": "Jean skinny", "price": 134369.75}]},
]}


def _mock(monkeypatch):
    monkeypatch.setattr(C.siigo, "siigo_configurado", lambda: True)
    monkeypatch.setattr(C.siigo, "siigo_get", lambda p, params=None: FACTURAS)


def test_trae_las_compras_de_la_cedula(monkeypatch):
    _mock(monkeypatch)
    r = C.compras_por_cedula("30384838")
    assert r["total"] == 3
    assert r["cedula"] == "30384838"


def test_distingue_online_de_tienda(monkeypatch):
    _mock(monkeypatch)
    compras = {c["factura"]: c for c in C.compras_por_cedula("30384838")["compras"]}
    assert compras["FV-1-64151"]["canal"] == "online"
    assert compras["FV-1-64151"]["donde"] == "Tienda online"
    assert compras["FV-11-1333"]["canal"] == "florida_caja1"
    assert "Florida" in compras["FV-11-1333"]["donde"]


def test_solo_las_online_traen_numero_de_pedido(monkeypatch):
    _mock(monkeypatch)
    compras = {c["factura"]: c for c in C.compras_por_cedula("30384838")["compras"]}
    assert compras["FV-1-64151"]["pedido"] == "#61208"
    assert compras["FV-11-1333"]["pedido"] is None      # venta de mostrador


def test_marca_las_que_aun_no_se_pueden_acreditar(monkeypatch):
    _mock(monkeypatch)
    r = C.compras_por_cedula("30384838")
    assert r["acreditables"] == 2                        # la de hoy no
    hoy = [c for c in r["compras"] if c["factura"] == "FV-1-64300"][0]
    assert hoy["acreditable"] is False
    assert "DIAN" in hoy["motivo_no_acreditable"]


def test_ordena_de_la_mas_reciente(monkeypatch):
    _mock(monkeypatch)
    fechas = [c["fecha"] for c in C.compras_por_cedula("30384838")["compras"]]
    assert fechas == sorted(fechas, reverse=True)


def test_trae_las_prendas_de_cada_compra(monkeypatch):
    _mock(monkeypatch)
    c = C.compras_por_cedula("30384838")["compras"][0]
    assert c["prendas"][0]["sku"]
    assert c["prendas"][0]["precio"]


def test_sin_cedula():
    assert C.compras_por_cedula("  ")["_error"] == "sin_cedula"


def test_error_de_siigo_no_lanza(monkeypatch):
    monkeypatch.setattr(C.siigo, "siigo_configurado", lambda: True)
    def explota(p, params=None):
        raise RuntimeError("siigo caido")
    monkeypatch.setattr(C.siigo, "siigo_get", explota)
    r = C.compras_por_cedula("123")
    assert r["_error"] == "siigo_error"
