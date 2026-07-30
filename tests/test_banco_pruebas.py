from backend.services import postventa_banco_pruebas as B


# Lo que devuelve facturas_aceptadas(): ya filtradas por DIAN y con pedido.
FACTURAS_APTAS = [
    {"name": "FV-1-63043", "id": "f1",
     "observations": "Orden Nº: 60112 - Medio de Pago: Wompi",
     "stamp": {"status": "Accepted"}},
]

# Facturas hechas EN TIENDA: sin 'Orden Nº', con el document_id del punto.
FACTURAS_TIENDA = [
    {"name": "FV-11-1202", "id": "t1", "document": {"id": 31433},
     "observations": "", "stamp": {"status": "Accepted"}},
    {"name": "FV-12-330", "id": "t2", "document": {"id": 31434},
     "observations": "", "stamp": {"status": "Accepted"}},
    {"name": "FV-6-880", "id": "t3", "document": {"id": 29192},
     "observations": "", "stamp": {"status": "Accepted"}},
]

ITEMS_FACTURA = {"factura": {"id": "f1", "name": "FV-1-63043"},
                 "items": [
                     {"code": "A-10", "description": "Jean", "price": 100000.0},
                     {"code": "B-12", "description": "Blusa", "price": 50000.0}]}


BODEGAS_SIIGO = [{"id": 32, "name": "MELONN", "active": True},
                 {"id": 37, "name": "Arrayanes", "active": True},
                 {"id": 48, "name": "Florida", "active": True}]


def _mock_base(monkeypatch, *, preview_total=119000.0,
               facturas_tienda=FACTURAS_TIENDA, bodega_nc=None):
    # bodega_nc=None ⇒ se usa la que corresponde al punto (caso feliz).
    monkeypatch.setattr(B.descubrir, "facturas_aceptadas",
                        lambda minimo=5, **k: FACTURAS_APTAS)
    # La guarda de bodegas corre antes que todo: sin esto el banco ni arranca.
    monkeypatch.setattr(B.siigo_svc, "listar_bodegas", lambda: BODEGAS_SIIGO)
    # El motor real arma la NC con la bodega del punto del caso; el mock hace
    # lo mismo para que la verificación tenga algo real que mirar.
    from backend.services import tiendas as _T
    ultimo = {"tienda": ""}

    def _crear(**k):
        ultimo["tienda"] = k.get("tienda") or ""
        return {"id": "c1", "case_number": "PV-2026-9001", **k}

    def _preview(cid):
        if bodega_nc is not None:
            bod = bodega_nc                       # forzada, para probar el fallo
        elif ultimo["tienda"]:
            bod = (_T.obtener(ultimo["tienda"]) or {}).get("bodega_id")
        else:
            bod = 32                              # MELONN, la venta online
        return {"factura_original": {"name": "FV-1-63043"},
                "payload": {"items": [{"code": "A-10", "warehouse": {"id": bod}}]},
                "totales": {"subtotal": 100000.0, "iva": 19000.0,
                            "total": preview_total}}

    monkeypatch.setattr(B.pv, "crear_caso", _crear)
    monkeypatch.setattr(B.pv, "cambiar_estado", lambda *a, **k: {})
    monkeypatch.setattr(B.pv, "agregar_item", lambda cid, **k: {"id": "i1", **k})
    monkeypatch.setattr(B.fiscal, "items_factura_del_caso", lambda cid: ITEMS_FACTURA)
    monkeypatch.setattr(B.fiscal, "preview_nota_credito", _preview)
    monkeypatch.setattr(B.descubrir, "facturas_recientes",
                        lambda **k: facturas_tienda)
    monkeypatch.setattr(B.fiscal_siigo, "modo_actual", lambda: "prueba")
    # El banco valida la factura del reemplazo: necesita los items en DB.
    monkeypatch.setattr(B.pv, "items_caso", lambda cid: [{
        "original_sku": "A-10", "original_variant": "Jean",
        "original_price": 100000.0, "requested_sku": ""}])
    from backend.services import fiscal_shopify as _FS
    monkeypatch.setattr(_FS, "variante_mas_cara_que",
                        lambda base, excluir_sku="": None)
    monkeypatch.setattr(_FS, "precio_base_variante", lambda sku: 100000.0)


def test_dry_run_no_emite(monkeypatch):
    _mock_base(monkeypatch)
    emitidos = []
    monkeypatch.setattr(B.fiscal, "emitir_nota_credito",
                        lambda cid, **k: emitidos.append(cid))
    r = B.correr(total=3, dry_run=True)
    # 3 online del plan + los 5 de tienda que ahora tambien se prueban.
    assert r["total"] == 8
    assert r["cobertura"]["tienda"] == 5
    assert r["exitosos"] == 8        # los 3 online y los 5 de tienda
    assert emitidos == []            # NO se emitió nada


def test_detecta_montos_que_no_cuadran(monkeypatch):
    # Si el total no es subtotal+19%, el caso debe fallar (no pasar callado).
    _mock_base(monkeypatch, preview_total=150000.0)
    r = B.correr(total=2, dry_run=True)
    assert r["exitosos"] == 0
    assert r["fallidos"] == 7          # 2 online + 5 de tienda
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
    # Los de tienda suman encima del plan online (PLAN_TIENDA_DEFAULT).
    assert r["por_tipo"]["cambio_talla"]["total"] == 8 + 2
    assert r["por_tipo"]["cambio_ref"]["total"] == 7 + 2
    assert r["por_tipo"]["reembolso"]["total"] == 5 + 1


def test_gate_verde_con_20_ok(monkeypatch):
    _mock_base(monkeypatch)
    r = B.correr(total=20, dry_run=True)
    assert r["gate_verde"] is True
    assert r["por_que_no_verde"] == []


def test_el_gate_NO_da_verde_si_no_probo_tienda(monkeypatch):
    """La falla que dejo salir el bug: 20/20 en verde con el flujo presencial
    nunca ejercitado. Un gate que no probo un canal no puede decir que paso."""
    _mock_base(monkeypatch, facturas_tienda=[])
    r = B.correr(total=20, dry_run=True)
    assert r["fallidos"] == 0          # todo lo que corrio, paso...
    assert r["gate_verde"] is False    # ...pero no alcanza para dar verde
    assert any("tienda" in m for m in r["por_que_no_verde"])
    assert r["cobertura"]["tienda"] == 0


def test_detecta_la_nc_que_entra_a_la_bodega_equivocada(monkeypatch):
    """Si la prenda del cambio presencial entra a MELONN en vez de a la tienda,
    el banco tiene que verlo: es el descuadre de inventario que nadie nota."""
    _mock_base(monkeypatch, bodega_nc=32)          # 32 = MELONN (online)
    r = B.correr(total=1, dry_run=True)
    de_tienda = [x for x in r["resultados"] if x["canal"] != "online"]
    assert de_tienda and all(not x["ok"] for x in de_tienda)
    pasos = [p for x in de_tienda for p in x["pasos"]
             if p["paso"] == "nc_entra_a_la_bodega_del_punto"]
    assert pasos and all(not p["ok"] for p in pasos)


def test_no_emite_en_modo_produccion(monkeypatch):
    _mock_base(monkeypatch)
    monkeypatch.setattr(B.fiscal_siigo, "modo_actual", lambda: "produccion")
    r = B.correr(total=5, dry_run=False)
    assert r["_error"] == "modo_produccion"   # protección: no toca la DIAN


def test_sin_facturas_lo_dice(monkeypatch):
    monkeypatch.setattr(B.siigo_svc, "listar_bodegas", lambda: BODEGAS_SIIGO)
    monkeypatch.setattr(B.descubrir, "facturas_aceptadas",
                        lambda minimo=5, **k: [])
    r = B.correr(total=5)
    assert r["_error"] == "sin_pedidos_facturados"


def test_limpiar_exige_confirmacion():
    r = B.limpiar()
    assert r["_error"] == "requiere_confirmacion"


def _mock_con_shopify(monkeypatch, *, hay_mas_cara=True):
    _mock_base(monkeypatch)
    monkeypatch.setattr(B.pv, "items_caso", lambda cid: [{
        "original_sku": "A-10", "original_variant": "Jean",
        "original_price": 100000.0,
        "requested_sku": "CARA-1" if hay_mas_cara else ""}])
    from backend.services import fiscal_shopify as FS
    if hay_mas_cara:
        monkeypatch.setattr(FS, "variante_mas_cara_que",
                            lambda base, excluir_sku="": {
                                "sku": "CARA-1", "precio_con_iva": 200000.0,
                                "precio_base": 168067.23})
        monkeypatch.setattr(FS, "precio_base_variante", lambda sku: 168067.23)
    else:
        monkeypatch.setattr(FS, "variante_mas_cara_que",
                            lambda base, excluir_sku="": None)
        monkeypatch.setattr(FS, "precio_base_variante", lambda sku: None)


def test_cambio_ref_busca_prenda_mas_cara(monkeypatch):
    _mock_con_shopify(monkeypatch)
    r = B.correr(total=8, dry_run=True)   # llega a los cambio_ref
    ref = [x for x in r["resultados"] if x["tipo"] == "cambio_ref"]
    if ref:
        pasos = [p["paso"] for p in ref[0]["pasos"]]
        assert "buscar_reemplazo_mas_caro" in pasos


def test_valida_reparto_anticipo_excedente(monkeypatch):
    _mock_con_shopify(monkeypatch)
    r = B.correr(total=20, dry_run=True)
    con_factura = [x for x in r["resultados"]
                   if x.get("resumen_factura")]
    assert con_factura, "ningún caso validó la factura de reemplazo"
    res = con_factura[0]["resumen_factura"]
    # El total debe repartirse exactamente entre anticipo y excedente
    assert abs((res["anticipo"] + res["excedente"]) - res["total"]) < 1.0


def test_prenda_mas_cara_genera_excedente(monkeypatch):
    _mock_con_shopify(monkeypatch)
    r = B.correr(total=20, dry_run=True)
    refs = [x for x in r["resultados"]
            if x["tipo"] == "cambio_ref" and x.get("resumen_factura")]
    assert refs, "cambio_ref no validó factura"
    # 168067.23 * 1.19 = 199_999.x  vs crédito 119000 → excedente > 0
    assert refs[0]["resumen_factura"]["excedente"] > 0


def test_reembolso_no_valida_factura(monkeypatch):
    _mock_con_shopify(monkeypatch)
    r = B.correr(total=20, dry_run=True)
    reemb = [x for x in r["resultados"] if x["tipo"] == "reembolso"]
    assert all("resumen_factura" not in x for x in reemb)
