"""Una venta real por HTTP, de punta a punta.

Sube una app FastAPI con el router del módulo, le pega una petición con una
venta completa, y verifica que quedó todo en PostgreSQL.

Es el primer punto donde el módulo se comporta como un sistema y no como un
conjunto de piezas.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

SESION = "01JQ8X4T5N6P7R8S9V0W1X2Y3Z"
VENTA = "01JQ8X4T5N6P7R8S9V0W1X2Y41"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y42"
VARIANTE_2 = "01JQ8X4T5N6P7R8S9V0W1X2Y43"
UBICACION = "tienda:florida"


@pytest_asyncio.fixture()
async def cliente():
    from backend.core.security import CurrentUser, get_current_user
    from backend.modules.retail.interfaces.http import dependencias
    from backend.modules.retail.interfaces.http.router import router
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)
    os.environ["RETAIL_DATABASE_URL"] = URL
    dependencias.reiniciar()

    motor = create_async_engine(URL)
    semillas = [
        ("INSERT INTO retail.tiendas (id,nombre) VALUES ('florida','Florida')", {}),
        ("INSERT INTO retail.cajas (id,tienda_id,nombre) "
         "VALUES ('florida_caja1','florida','Caja 1')", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": UBICACION}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
         "VALUES ('efectivo','Efectivo','efectivo',12243)", {}),
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,color,precio_base,codigo_barras) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean Skinny','Azul',"
         "14277311,'7701234567890')", {"v": VARIANTE}),
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,color,precio_base) "
         "VALUES (:v,'92611-1T4','92611-1','4','Jean Skinny','Azul',14277311)",
         {"v": VARIANTE_2}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:u,:v,5)", {"u": UBICACION, "v": VARIANTE}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:u,:v,2)", {"u": UBICACION, "v": VARIANTE_2}),
        ("INSERT INTO retail.sesiones_caja "
         "(id,tienda_id,caja_id,numero_turno,base_inicial,abierta_por) "
         "VALUES (:s,'florida','florida_caja1',1,20000000,'maria')", {"s": SESION}),
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)
        # Alimentar el read model del buscador.
        await c.execute(text("""
            INSERT INTO retail.catalogo_busqueda
                (variante_id, texto_busqueda, referencia, talla, color, precio_base)
            SELECT v.id,
                   retail.norm(concat_ws(' ', v.sku, v.referencia, v.nombre,
                                         v.color, v.talla, v.codigo_barras)),
                   v.referencia, v.talla, v.color, v.precio_base
              FROM retail.variantes v
        """))

    app = FastAPI()
    app.include_router(router)

    # Se sustituye el LOGIN (que es del ERP y ya tiene sus pruebas), no el
    # chequeo de permisos: la cajera entra con rol `user` y permiso explícito
    # sobre el grupo `retail`, así que el RBAC real sí se ejerce. Poner un
    # admin aquí habría dejado sin probar que el grupo esté bien cableado.
    cajera = CurrentUser(id="maria", email="m@male.com", nombre="María",
                         rol="user", cargo="Asesora de ventas",
                         permisos={"retail": ["ver", "modificar"]})
    app.dependency_overrides[get_current_user] = lambda: cajera

    with TestClient(app) as c:
        yield c

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _venta(venta_id=VENTA, cantidad=2, pago=400000_00):
    return {
        "venta_id": venta_id, "numero": "FV-20-1334", "tienda_id": "florida",
        "caja_id": "florida_caja1", "sesion_id": SESION,
        "ubicacion_id": UBICACION, "tope_descuento": "10",
        "lineas": [{"sku": "92611-1T10", "cantidad": cantidad,
                    "precio_unitario_centavos": 14277311,
                    "descripcion": "Jean Skinny Azul · 10"}],
        "pagos": [{"medio_pago_id": "efectivo", "monto_centavos": pago,
                   "es_efectivo": True}],
    }


# ── La venta ────────────────────────────────────────────────────────────────

def test_una_venta_completa_por_http(cliente):
    r = cliente.post("/api/retail/ventas/cerrar", json=_venta())
    assert r.status_code == 200, r.text
    t = r.json()

    assert t["numero"] == "FV-20-1334"
    assert t["total_centavos"] == 33980000     # $339.800 — el precio de vitrina
    assert t["vuelto_centavos"] == 6020000     # $60.200
    assert t["estado_fiscal"] == "pendiente"   # encolado, no emitido
    assert t["duplicada"] is False


def test_reintentar_la_misma_venta_devuelve_el_mismo_ticket(cliente):
    """El dispositivo no puede distinguir «no llegó» de «llegó y se perdió la
    respuesta». Reintentar tiene que devolver el ticket, no un error."""
    primero = cliente.post("/api/retail/ventas/cerrar", json=_venta()).json()
    segundo = cliente.post("/api/retail/ventas/cerrar", json=_venta()).json()

    assert segundo["duplicada"] is True
    assert segundo["total_centavos"] == primero["total_centavos"]
    assert segundo["numero"] == primero["numero"]


def test_una_venta_a_la_que_le_falta_plata_se_rechaza_con_un_mensaje_util(cliente):
    r = cliente.post("/api/retail/ventas/cerrar",
                     json=_venta(pago=100000_00))
    assert r.status_code == 400
    detalle = r.json()["detail"]
    assert detalle["error"] == "regla_de_negocio"
    # El mensaje es para la CAJERA: dice cuánto falta, no un código.
    assert "falta cobrar" in detalle["mensaje"]
    assert "$239.800" in detalle["mensaje"]


def test_un_descuento_sobre_el_tope_pide_autorizacion_no_da_error(cliente):
    """403 con `accion_sugerida` para que la pantalla abra el diálogo del PIN
    en vez de mostrar un error rojo: la operación es posible, falta firma."""
    cuerpo = _venta()
    cuerpo["lineas"][0].update({"descuento_porcentaje": "30",
                                "descuento_motivo": "clienta insistió"})
    r = cliente.post("/api/retail/ventas/cerrar", json=cuerpo)

    assert r.status_code == 403
    detalle = r.json()["detail"]
    assert detalle["error"] == "requiere_autorizacion"
    assert detalle["accion_sugerida"] == "pedir_autorizacion"
    assert "30" in detalle["mensaje"] and "10" in detalle["mensaje"]


def test_con_la_firma_del_supervisor_el_descuento_pasa(cliente):
    cuerpo = _venta()
    cuerpo["lineas"][0].update({"descuento_porcentaje": "30",
                                "descuento_motivo": "clienta insistió",
                                "autorizado_por": "laura"})
    r = cliente.post("/api/retail/ventas/cerrar", json=cuerpo)
    assert r.status_code == 200, r.text
    assert r.json()["descuento_centavos"] == 8566387


def test_un_sku_que_no_existe_lo_dice_claro(cliente):
    cuerpo = _venta()
    cuerpo["lineas"][0]["sku"] = "00000-9T99"
    r = cliente.post("/api/retail/ventas/cerrar", json=cuerpo)
    assert r.status_code == 400
    assert "00000-9T99" in r.json()["detail"]["mensaje"]


# ── El buscador ─────────────────────────────────────────────────────────────

def test_buscar_por_referencia_devuelve_las_tallas_ordenadas(cliente):
    """La talla 4 antes que la 10. Como texto saldría al revés, y la cajera
    tendría que buscar la talla en un desorden con la clienta enfrente."""
    r = cliente.get("/api/retail/catalogo/buscar",
                    params={"q": "92611", "ubicacion_id": UBICACION})
    assert r.status_code == 200, r.text
    tallas = [x["talla"] for x in r.json()]
    assert tallas == ["4", "10"]


def test_escanear_un_codigo_de_barras_devuelve_una_sola_prenda(cliente):
    """Un escaneo no es una búsqueda: mostrar «resultados» obligaría a un clic
    que arruina los 30 segundos."""
    r = cliente.get("/api/retail/catalogo/buscar",
                    params={"q": "7701234567890", "ubicacion_id": UBICACION})
    datos = r.json()
    assert len(datos) == 1
    assert datos[0]["sku"] == "92611-1T10"
    assert datos[0]["es_escaneo"] is True


def test_buscar_por_varias_palabras_las_exige_todas(cliente):
    """`92611 azul 10` son tres condiciones, no un texto literal."""
    r = cliente.get("/api/retail/catalogo/buscar",
                    params={"q": "92611 azul 10", "ubicacion_id": UBICACION})
    datos = r.json()
    assert len(datos) == 1
    assert datos[0]["talla"] == "10"


def test_el_buscador_muestra_el_precio_de_vitrina(cliente):
    """El catálogo guarda SIN IVA; la clienta reconoce el precio CON IVA."""
    r = cliente.get("/api/retail/catalogo/buscar",
                    params={"q": "7701234567890", "ubicacion_id": UBICACION})
    d = r.json()[0]
    assert d["precio_base_centavos"] == 14277311     # $142.773,11 sin IVA
    assert d["precio_con_iva_centavos"] == 16990000  # $169.900 clavados


def test_el_buscador_dice_cuanto_hay_en_ESA_tienda(cliente):
    r = cliente.get("/api/retail/catalogo/buscar",
                    params={"q": "92611", "ubicacion_id": UBICACION})
    por_talla = {x["talla"]: x["disponible"] for x in r.json()}
    assert por_talla == {"4": 2, "10": 5}


def test_lo_que_no_existe_devuelve_vacio_no_un_error(cliente):
    r = cliente.get("/api/retail/catalogo/buscar",
                    params={"q": "zzzzz", "ubicacion_id": UBICACION})
    assert r.status_code == 200
    assert r.json() == []
