from backend.services import postventa_banco_pruebas as B


FACTURAS = {"facturas": [
    {"name": "FV-1-63043", "id": "f1",
     "observations": "Orden Nº: 60112 - Medio de Pago: Wompi"},
    {"name": "FV-11-1121", "id": "f2", "observations": ""},   # tienda física
]}

ITEMS_FACTURA = {"factura": {"id": "f1", "name": "FV-1-63043"},
                 "items": [
                     {"code": "A-10", "description": "Jean", "price": 100000.0},
                     {"code": "B-12", "description": "Blusa", "price": 50000.0}]}


def _mock_base(monkeypatch, *, preview_total=119000.0):
    monkeypatch.setattr(B.descubrir, "inspeccionar_facturas", lambda n: FACTURAS)
    monkeypatch.setattr(B.pv, "crear_caso",
                        lambda **k: {"id": "c1", "case_number": "PV-2026-9001", **k})
    monkeypatch.setattr(B.pv, "cambiar_estado", lambda *a, **k: {})
    monkeypatch.setattr(B.pv, "agregar_item", lambda cid, **k: {"id": "i1", **k})
    monkeypatch.setattr(B.fiscal, "items_factura_del_caso", lambda cid: ITEMS_FACTURA)
    monkeypatch.setattr(B.fiscal, "preview_nota_credito", lambda cid: {
        "factura_original": {"name": "FV-1-63043"},
        "totales": {"subtotal": 100000.0, "iva": 19000.0, "total": preview_total}})
    monkeypatch.setattr(B.fiscal_siigo, "modo_actual", lambda: "prueba")


def test_dry_run_no_emite(monkeypatch):
    _mock_base(monkeypatch)
    emitidos = []
    monkeypatch.setattr(B.fiscal, "emitir_nota_credito",
                        lambda cid, **k: emitidos.append(cid))
    r = B.correr(total=3, dry_run=True)
    assert r["total"] == 3
    assert r["exitosos"] == 3
    assert emitidos == []            # NO se emitió nada


def test_detecta_montos_que_no_cuadran(monkeypatch):
    # Si el total no es subtotal+19%, el caso debe fallar (no pasar callado).
    _mock_base(monkeypatch, preview_total=150000.0)
    r = B.correr(total=2, dry_run=True)
    assert r["exitosos"] == 0
    assert r["fallidos"] == 2
    assert r["gate_verde"] is False


def test_solo_usa_pedidos_con_factura_online(monkeypatch):
    # La factura de tienda física (sin 'Orden Nº') se descarta.
    _mock_base(monkeypatch)
    r = B.correr(total=2, dry_run=True)
    assert r["pedidos_usados"] == 1


def test_cubre_los_tres_escenarios(monkeypatch):
    _mock_base(monkeypatch)
    r = B.correr(total=20, dry_run=True)
    assert set(r["por_tipo"].keys()) == {"cambio_talla", "cambio_ref", "reembolso"}
    assert r["por_tipo"]["cambio_talla"]["total"] == 8
    assert r["por_tipo"]["cambio_ref"]["total"] == 7
    assert r["por_tipo"]["reembolso"]["total"] == 5


def test_gate_verde_con_20_ok(monkeypatch):
    _mock_base(monkeypatch)
    r = B.correr(total=20, dry_run=True)
    assert r["gate_verde"] is True


def test_no_emite_en_modo_produccion(monkeypatch):
    _mock_base(monkeypatch)
    monkeypatch.setattr(B.fiscal_siigo, "modo_actual", lambda: "produccion")
    r = B.correr(total=5, dry_run=False)
    assert r["_error"] == "modo_produccion"   # protección: no toca la DIAN


def test_sin_facturas_lo_dice(monkeypatch):
    monkeypatch.setattr(B.descubrir, "inspeccionar_facturas",
                        lambda n: {"facturas": []})
    r = B.correr(total=5)
    assert r["_error"] == "sin_pedidos_facturados"


def test_limpiar_exige_confirmacion():
    r = B.limpiar()
    assert r["_error"] == "requiere_confirmacion"
