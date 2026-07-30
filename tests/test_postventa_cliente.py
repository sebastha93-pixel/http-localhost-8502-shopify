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


# ── Datos de la clienta ────────────────────────────────────────────────────
# La factura de Siigo solo trae la cédula del cliente, no su nombre. Para
# rellenar el caso hay que pedirlos aparte a /customers.

CLIENTE = {"results": [{
    "identification": "30384838",
    "person_type": "Person",
    "name": ["Laura", "Restrepo"],
    "commercial_name": "",
    "contacts": [{"first_name": "Laura", "last_name": "Restrepo",
                  "email": "laura@correo.com",
                  "phone": {"indicative": "57", "number": "3105558899"}}],
    "phones": [{"indicative": "57", "number": "6015551122"}],
}]}


def _mock2(monkeypatch, cliente=CLIENTE, facturas=FACTURAS):
    """Mock que distingue /invoices de /customers."""
    monkeypatch.setattr(C.siigo, "siigo_configurado", lambda: True)

    def _get(path, params=None):
        if path.startswith("/customers"):
            if isinstance(cliente, Exception):
                raise cliente
            return cliente
        return facturas
    monkeypatch.setattr(C.siigo, "siigo_get", _get)


def test_trae_nombre_email_y_telefono_de_la_clienta(monkeypatch):
    _mock2(monkeypatch)
    cli = C.compras_por_cedula("30384838")["cliente"]
    assert cli["nombre"] == "Laura Restrepo"
    assert cli["email"] == "laura@correo.com"
    assert cli["telefono"] == "3105558899"


def test_si_no_se_puede_traer_el_cliente_las_compras_igual_sirven(monkeypatch):
    """Regla de oro: un dato secundario que falla NO rompe el caso."""
    _mock2(monkeypatch, cliente=RuntimeError("siigo 429"))
    r = C.compras_por_cedula("30384838")
    assert r["total"] == 3
    assert r["cliente"]["nombre"] == ""


def test_nombre_de_empresa_viene_en_un_solo_elemento():
    d = C.datos_de_cliente({"name": ["COMERCIALIZADORA SAS"], "person_type": "Company"})
    assert d["nombre"] == "COMERCIALIZADORA SAS"


def test_nombre_se_arma_del_contacto_si_falta_el_del_cliente():
    d = C.datos_de_cliente({"name": [], "contacts": [
        {"first_name": "Ana", "last_name": "Gómez", "email": "a@b.co"}]})
    assert d["nombre"] == "Ana Gómez"
    assert d["email"] == "a@b.co"


def test_telefono_cae_al_de_la_empresa_si_el_contacto_no_tiene():
    d = C.datos_de_cliente({"name": ["X"], "contacts": [{"email": "a@b.co"}],
                            "phones": [{"number": "6015551122"}]})
    assert d["telefono"] == "6015551122"


def test_cliente_vacio_no_revienta():
    d = C.datos_de_cliente({})
    assert d == {"nombre": "", "email": "", "telefono": ""}


# ── Fecha de la compra ─────────────────────────────────────────────────────
# Sin fecha la asesora no puede distinguir entre varias compras de la misma
# clienta. Si el listado no trae `date`, se cae a metadata.created.

def test_usa_metadata_created_si_la_factura_no_trae_date(monkeypatch):
    sin_fecha = {"results": [dict(FACTURAS["results"][0], date=None,
                                  metadata={"created": "2026-07-20T14:03:00Z"})]}
    _mock2(monkeypatch, facturas=sin_fecha)
    assert C.compras_por_cedula("30384838")["compras"][0]["fecha"] == "2026-07-20T14:03:00Z"


def test_prefiere_date_sobre_metadata(monkeypatch):
    con_ambas = {"results": [dict(FACTURAS["results"][0],
                                  metadata={"created": "2026-01-01T00:00:00Z"})]}
    _mock2(monkeypatch, facturas=con_ambas)
    assert C.compras_por_cedula("30384838")["compras"][0]["fecha"] == "2026-07-20"


# ── Ventana de 30 dias ─────────────────────────────────────────────────────
# Una compra vieja no se puede cambiar. Se marca en la lista para que la
# asesora lo vea ANTES de abrir el caso, no despues de emitir la NC.

def test_marca_las_compras_fuera_del_plazo(monkeypatch):
    viejas = {"results": [dict(FACTURAS["results"][0], date="2026-01-15",
                               id="vieja")]}
    _mock2(monkeypatch, facturas=viejas)
    c = C.compras_por_cedula("30384838")["compras"][0]
    assert c["acreditable"] is False
    assert "plazo" in (c["motivo_no_acreditable"] or "").lower()


def test_una_compra_reciente_sigue_sirviendo(monkeypatch):
    from datetime import date, timedelta
    ayer = (date.today() - timedelta(days=1)).isoformat()
    recientes = {"results": [dict(FACTURAS["results"][0], date=ayer)]}
    _mock2(monkeypatch, facturas=recientes)
    assert C.compras_por_cedula("30384838")["compras"][0]["acreditable"] is True


def test_la_ventana_manda_aunque_la_dian_haya_aceptado(monkeypatch):
    """Que la DIAN la acepto no significa que este en plazo."""
    viejas = {"results": [dict(FACTURAS["results"][0], date="2025-01-15",
                               stamp={"status": "Accepted"})]}
    _mock2(monkeypatch, facturas=viejas)
    assert C.compras_por_cedula("30384838")["compras"][0]["acreditable"] is False
