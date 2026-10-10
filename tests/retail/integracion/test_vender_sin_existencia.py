"""Vender lo que el sistema tiene en cero, y avisarle a contabilidad.

Decisión de Sebastián (2026-10-09): la prenda que la cajera tiene en la mano
se vende aunque Siigo diga cero, y contabilidad recibe la lista cada día.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

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
BOGOTA = timezone(timedelta(hours=-5))


def _p(code, arrayanes=0, florida=0):
    return {"code": code, "name": f"{code} JEAN FLARE", "stock_control": True,
            "tax_included": True, "account_group": {"name": "SKINNY"},
            "prices": [{"price_list": [{"value": 149900}]}],
            "warehouses": [{"id": 37, "name": "Arrayanes", "quantity": arrayanes},
                           {"id": 48, "name": "Florida", "quantity": florida}],
            "additional_fields": {"barcode": code}}


@pytest_asyncio.fixture()
async def tienda(monkeypatch):
    from backend.core.security import CurrentUser, get_current_user
    from backend.modules.retail.interfaces.http import dependencias
    from backend.modules.retail.interfaces.http.router import router
    from backend.modules.retail.migraciones.runner import aplicar, revertir
    from backend.modules.retail.sembrar_tiendas import sembrar
    from backend.modules.retail.sincronizar_inventario import sincronizar

    revertir(URL)
    aplicar(URL)
    sembrar(URL, aplicar=True)
    # Una con existencia, una que sólo tiene FLORIDA (Arrayanes no tiene ni
    # la fila de saldo) y una con una sola unidad.
    sincronizar(URL, aplicar=True, precios_de_lista=lambda c: {}, productos=[
        _p("10001-1T6", arrayanes=5), _p("20002-1T8", florida=3),
        _p("30003-1T10", arrayanes=1)])
    os.environ["RETAIL_DATABASE_URL"] = URL
    dependencias.reiniciar()
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "apagado")
    monkeypatch.setenv("RETAIL_ALERTA_INVENTARIO_PARA", "contabilidad@male.test")

    motor = create_engine(URL, future=True)
    with motor.begin() as c:
        c.execute(text(
            "INSERT INTO retail.permisos_pos "
            "(usuario_id,nombre,tiendas,puede_anular_venta) "
            "VALUES ('maria','María R.','{arrayanes}',true)"))

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="maria", email="m@male.com", nombre="María R.", rol="user",
        permisos={"retail": ["ver", "modificar"]})
    with TestClient(app) as c:
        t = c.post("/api/retail/caja/turno", json={
            "sesion_id": SESION, "tienda_id": "arrayanes",
            "caja_id": "arrayanes_caja1"}).json()
        yield {"c": c, "motor": motor, "prefijo": t["prefijo"],
               "n": [t["consecutivo_siguiente"]]}
    motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _vender(t, sku, cantidad=1, venta_id=None):
    n = t["n"][0]
    t["n"][0] += 1
    # Distintos desde el principio: el id de la línea sale del arranque del
    # id de la venta.
    vid = venta_id or f"01JQ8X4T5N{n % 100:02d}V0F1R8S9V0W1X2"
    r = t["c"].post("/api/retail/ventas/cerrar", json={
        "venta_id": vid, "numero": f"{t['prefijo']}-{n}",
        "tienda_id": "arrayanes", "caja_id": "arrayanes_caja1",
        "sesion_id": SESION, "ubicacion_id": "tienda:arrayanes",
        "lineas": [{"sku": sku, "cantidad": cantidad,
                    "precio_unitario_centavos": 14_990_000,
                    "descripcion": f"Jean · {sku}"}],
        "pagos": [{"medio_pago_id": "datafono_arrayanes",
                   "monto_centavos": 14_990_000 * cantidad,
                   "referencia": "004512"}]})
    return vid, r


def _saldo(t, sku):
    with t["motor"].connect() as c:
        return c.execute(text("""
            SELECT s.cantidad FROM retail.stock_ubicacion s
              JOIN retail.variantes v ON v.id = s.variante_id
             WHERE s.ubicacion_id = 'tienda:arrayanes' AND v.sku = :s
        """), {"s": sku}).scalar()


def test_se_vende_una_prenda_que_la_tienda_NUNCA_tuvo_registrada(tienda):
    """No hay ni fila de saldo para ella en Arrayanes. Antes la venta
    reventaba con la clienta pagando; ahora el saldo nace en −1."""
    assert _saldo(tienda, "20002-1T8") is None
    _, r = _vender(tienda, "20002-1T8")
    assert r.status_code == 200, r.text
    assert _saldo(tienda, "20002-1T8") == -1


def test_se_vende_mas_de_lo_que_hay_y_el_saldo_queda_negativo(tienda):
    _, r = _vender(tienda, "30003-1T10", cantidad=2)
    assert r.status_code == 200, r.text
    assert _saldo(tienda, "30003-1T10") == -1


# ── El aviso a contabilidad ─────────────────────────────────────────────────

def _manana_a_las(hora):
    return (datetime.now(BOGOTA) + timedelta(days=1)).replace(
        hour=hora, minute=5, second=0, microsecond=0)


def _alerta(ahora, enviados, ok=True):
    from backend.modules.retail.alerta_inventario import enviar_la_de_ayer

    def enviar(**kw):
        enviados.append(kw)
        return {"ok": ok, "id": "x" if ok else None,
                "error": "" if ok else "resend_caido"}
    return enviar_la_de_ayer(URL, ahora=ahora, enviar=enviar)


def test_contabilidad_recibe_lo_vendido_sin_existencia_y_SOLO_eso(tienda):
    _vender(tienda, "10001-1T6")                 # había 5: no es un caso
    _vender(tienda, "20002-1T8")                 # no había: 1 sin existencia
    _vender(tienda, "30003-1T10", cantidad=2)    # había 1: 1 sin existencia

    enviados = []
    r = _alerta(_manana_a_las(7), enviados)
    assert r["enviado"] is True and r["casos"] == 2

    [correo] = enviados
    assert correo["para"] == "contabilidad@male.test"
    assert "2 prendas vendidas sin existencia" in correo["asunto"]
    assert "20002-1T8" in correo["html"] and "30003-1T10" in correo["html"]
    assert "10001-1T6" not in correo["html"]
    assert "Arrayanes" in correo["html"] and "María R." in correo["html"]
    assert "inventario de Siigo" in correo["html"]


def test_el_aviso_sale_UNA_vez_aunque_el_servidor_se_reinicie(tienda):
    _vender(tienda, "20002-1T8")
    enviados = []
    assert _alerta(_manana_a_las(7), enviados)["enviado"] is True
    assert _alerta(_manana_a_las(8), enviados) == {
        "enviado": False, "motivo": "ya se había enviado"}
    assert len(enviados) == 1


def test_antes_de_la_hora_no_sale(tienda):
    _vender(tienda, "20002-1T8")
    enviados = []
    assert _alerta(_manana_a_las(5), enviados)["enviado"] is False
    assert enviados == []
    assert _alerta(_manana_a_las(7), enviados)["enviado"] is True


def test_un_dia_sin_casos_no_manda_nada(tienda):
    _vender(tienda, "10001-1T6")
    enviados = []
    assert _alerta(_manana_a_las(7), enviados)["motivo"] == "sin casos"
    assert enviados == []


def test_una_venta_que_despues_se_anulo_no_es_un_caso(tienda):
    """La prenda volvió: no hay diferencia que revisar."""
    vid, _ = _vender(tienda, "20002-1T8")
    r = tienda["c"].post(f"/api/retail/ventas/{vid}/anular",
                         json={"motivo": "se cobró dos veces"})
    assert r.status_code == 200, r.text
    enviados = []
    assert _alerta(_manana_a_las(7), enviados)["motivo"] == "sin casos"


def test_si_el_correo_no_sale_se_REINTENTA_no_se_da_por_enviado(tienda):
    _vender(tienda, "20002-1T8")
    enviados = []
    with pytest.raises(RuntimeError, match="no salió"):
        _alerta(_manana_a_las(7), enviados, ok=False)
    assert _alerta(_manana_a_las(8), enviados)["enviado"] is True
    assert len(enviados) == 2


def test_sin_destinatarios_no_se_envia_ni_se_marca(tienda, monkeypatch):
    _vender(tienda, "20002-1T8")
    monkeypatch.setenv("RETAIL_ALERTA_INVENTARIO_PARA", "")
    enviados = []
    r = _alerta(_manana_a_las(7), enviados)
    assert r["motivo"] == "sin destinatarios configurados"
    # El día que se configure, el de ayer todavía puede salir.
    monkeypatch.setenv("RETAIL_ALERTA_INVENTARIO_PARA", "a@male.test, b@male.test")
    assert _alerta(_manana_a_las(8), enviados)["destinatarios"] == 2


def test_el_datafono_no_se_cobra_sin_el_numero_del_comprobante(tienda):
    """Es lo que cuadra el cierre contra el informe del datáfono. Sin él, un
    cobro de más o de menos no se puede rastrear a su venta."""
    r = tienda["c"].post("/api/retail/ventas/cerrar", json={
        "venta_id": "01JQ8X4T5N77V0F1R8S9V0W1X2", "numero":
            f"{tienda['prefijo']}-{tienda['n'][0]}",
        "tienda_id": "arrayanes", "caja_id": "arrayanes_caja1",
        "sesion_id": SESION, "ubicacion_id": "tienda:arrayanes",
        "lineas": [{"sku": "10001-1T6", "cantidad": 1,
                    "precio_unitario_centavos": 14_990_000,
                    "descripcion": "Jean"}],
        "pagos": [{"medio_pago_id": "datafono_arrayanes",
                   "monto_centavos": 14_990_000}]})
    assert r.status_code == 400
    assert "Datáfono" in r.json()["detail"]["mensaje"]
