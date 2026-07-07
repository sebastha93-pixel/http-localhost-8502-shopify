import pytest
from unittest.mock import MagicMock
from backend.services import postventa as svc


class FakeSupabase:
    """Mock mínimo del cliente supabase: encadena table().insert().execute() etc."""
    def __init__(self):
        self.inserted = []
        self._count_resp = 3  # ya existen 3 casos este año

    def table(self, name):
        self._table = name
        return self

    def insert(self, data):
        self.inserted.append((self._table, data))
        self._payload = data
        return self

    def update(self, data):
        self._payload = data
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        resp = MagicMock()
        resp.data = [self._payload] if getattr(self, "_payload", None) else []
        resp.count = self._count_resp
        return resp


def test_crear_caso_valida_tipo(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    monkeypatch.setattr(svc, "_siguiente_consecutivo", lambda anio: 4)
    caso = svc.crear_caso(tipo="cambio_talla", reason="talla_pequena",
                          customer_email="a@b.com")
    assert caso["case_number"].startswith("PV-")
    assert caso["case_number"].endswith("0004")
    assert caso["status"] == "creado"
    assert caso["source"] == "interno"


def test_crear_caso_tipo_invalido(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    with pytest.raises(ValueError, match="tipo_invalido"):
        svc.crear_caso(tipo="xxx", reason="talla_pequena")


def test_cambiar_estado_valido(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(svc, "_sb", lambda: fake)
    monkeypatch.setattr(svc, "obtener_caso",
                        lambda cid: {"id": cid, "status": "pendiente_validacion"})
    monkeypatch.setattr(svc, "_notificar_estado", lambda caso, estado: None)
    caso = svc.cambiar_estado("c1", "aprobado", actor="u1")
    assert caso["status"] == "aprobado"
    # se registró el evento en timeline
    assert any(t[0] == "postventa_timeline" for t in fake.inserted)


def test_cambiar_estado_invalido(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    monkeypatch.setattr(svc, "obtener_caso",
                        lambda cid: {"id": cid, "status": "creado"})
    with pytest.raises(ValueError, match="transicion_invalida"):
        svc.cambiar_estado("c1", "factura_emitida", actor="u1")


def test_notificar_estado_envia_wa(monkeypatch):
    enviados = []
    monkeypatch.setattr(svc.whatsapp_cloud, "enviar_texto",
                        lambda tel, msg: enviados.append((tel, msg)) or {"enviado": True})
    monkeypatch.setattr(svc, "registrar_evento", lambda *a, **k: {})
    caso = {"id": "c1", "customer_phone": "3001234567", "case_number": "PV-2026-0004"}
    svc._notificar_estado(caso, "aprobado")
    assert len(enviados) == 1
    assert "PV-2026-0004" in enviados[0][1]


def test_notificar_estado_sin_plantilla_no_envia(monkeypatch):
    enviados = []
    monkeypatch.setattr(svc.whatsapp_cloud, "enviar_texto",
                        lambda tel, msg: enviados.append((tel, msg)))
    caso = {"id": "c1", "customer_phone": "3001234567", "case_number": "PV-2026-0004"}
    svc._notificar_estado(caso, "pendiente_validacion")  # sin plantilla
    assert enviados == []


def test_notificar_estado_excepcion_registra_timeline(monkeypatch):
    # Spec §7.2: si el envío WhatsApp lanza excepción, el caso NO se rompe
    # y queda un evento de timeline "no entregado".
    def _raise(tel, msg):
        raise RuntimeError("wa caido")
    eventos = []
    monkeypatch.setattr(svc.whatsapp_cloud, "enviar_texto", _raise)
    monkeypatch.setattr(svc, "registrar_evento",
                        lambda *a, **k: eventos.append(a))
    caso = {"id": "c1", "customer_phone": "3001234567", "case_number": "PV-2026-0004"}
    svc._notificar_estado(caso, "aprobado")  # no debe lanzar
    assert len(eventos) == 1
    assert "no entregado" in eventos[0][2]


def test_agregar_item_calcula_diferencia(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(svc, "_sb", lambda: fake)
    item = svc.agregar_item("c1", original_sku="A-M", original_price=100000.0,
                            requested_sku="A-L", requested_price=130000.0)
    assert item["price_difference"] == 30000.0
    assert item["item_status"] == "pendiente"


def test_agregar_item_reembolso(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    item = svc.agregar_item("c1", original_sku="A-M", original_price=100000.0)
    assert item["price_difference"] == -100000.0


def test_pedido_shopify_reusa_clientes(monkeypatch):
    monkeypatch.setattr(svc.clientes, "clasificar",
                        lambda email="", telefono="": {"tier": "vip", "pedidos": []})
    r = svc.pedido_shopify(email="a@b.com")
    assert r["tier"] == "vip"


def test_contadores_dashboard(monkeypatch):
    casos = [
        {"status": "creado", "reason": "talla_pequena"},
        {"status": "creado", "reason": "talla_pequena"},
        {"status": "cerrado", "reason": "color_diferente"},
        {"status": "aprobado", "reason": "talla_grande"},
    ]
    monkeypatch.setattr(svc, "listar_casos", lambda status=None: casos)
    d = svc.contadores_dashboard()
    assert d["por_estado"]["creado"] == 2
    assert d["cerrados"] == 1
    assert d["abiertos"] == 3
    assert d["top_motivos"][0]["motivo"] == "talla_pequena"
    assert d["top_motivos"][0]["total"] == 2
