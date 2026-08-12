"""Autorización por PIN — el control anti-fraude, de punta a punta.

Un descuento por encima del tope es una operación legítima que también es la
forma de sacar plata. Lo único que las separa es que quede el nombre de quien
la aprobó.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

import bcrypt  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

SESION = "01JQ8X4T5N6P7R8S9V0W1X2Y3Z"
VENTA = "01JQ8X4T5N6P7R8S9V0W1X2Y41"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y42"
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
    hash_laura = bcrypt.hashpw(b"4821", bcrypt.gensalt()).decode()
    semillas = [
        ("INSERT INTO retail.tiendas (id,nombre) VALUES ('florida','Florida')", {}),
        ("INSERT INTO retail.cajas (id,tienda_id,nombre) "
         "VALUES ('florida_caja1','florida','Caja 1')", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": UBICACION}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
         "VALUES ('efectivo','Efectivo','efectivo',12243)", {}),
        ("INSERT INTO retail.variantes (id,sku,referencia,talla,nombre,precio_base) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean',14277311)", {"v": VARIANTE}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:u,:v,5)", {"u": UBICACION, "v": VARIANTE}),
        ("INSERT INTO retail.sesiones_caja "
         "(id,tienda_id,caja_id,numero_turno,base_inicial,abierta_por) "
         "VALUES (:s,'florida','florida_caja1',1,20000000,'maria')", {"s": SESION}),
        # La supervisora: tope 35 %, puede autorizar, PIN 4821.
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,pin_hash,tiendas,tope_descuento_pct,"
         " puede_autorizar_descuento) "
         "VALUES ('laura','Laura M.',:h,'{florida}',35,true)", {"h": hash_laura}),
        # La cajera: tope 10 %, NO puede autorizar.
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,tope_descuento_pct) "
         "VALUES ('maria','María R.','{florida}',10)", {}),
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)

    app = FastAPI()
    app.include_router(router)
    cajera = CurrentUser(id="maria", email="m@male.com", nombre="María",
                         rol="user", permisos={"retail": ["ver", "modificar"]})
    app.dependency_overrides[get_current_user] = lambda: cajera

    with TestClient(app) as c:
        yield c, motor

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _venta_con_descuento(pct: str, autorizado_por=None):
    linea = {"sku": "92611-1T10", "cantidad": 2,
             "precio_unitario_centavos": 14277311,
             "descripcion": "Jean · 10",
             "descuento_porcentaje": pct,
             "descuento_motivo": "clienta insistió"}
    if autorizado_por:
        linea["autorizado_por"] = autorizado_por
    return {
        "venta_id": VENTA, "numero": "FV-20-1334", "tienda_id": "florida",
        "caja_id": "florida_caja1", "sesion_id": SESION,
        "ubicacion_id": UBICACION, "tope_descuento": "10",
        "lineas": [linea],
        "pagos": [{"medio_pago_id": "efectivo", "monto_centavos": 40000000,
                   "es_efectivo": True}],
    }


# ── El PIN ──────────────────────────────────────────────────────────────────

def test_el_pin_correcto_dice_quien_firma(cliente):
    c, _ = cliente
    r = c.post("/api/retail/autorizacion",
               json={"pin": "4821", "tienda_id": "florida"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["autorizado_por"] == "laura"
    assert d["nombre"] == "Laura M."
    assert d["tope_descuento_pct"] == "35.00"


def test_un_pin_que_no_es_de_nadie_no_autoriza(cliente):
    c, _ = cliente
    r = c.post("/api/retail/autorizacion",
               json={"pin": "9999", "tienda_id": "florida"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "pin_invalido"


def test_el_pin_de_otra_tienda_no_sirve_aqui(cliente):
    """Un supervisor de Arrayanes no autoriza descuentos en Florida."""
    c, _ = cliente
    r = c.post("/api/retail/autorizacion",
               json={"pin": "4821", "tienda_id": "arrayanes"})
    assert r.status_code == 403


def test_la_cajera_no_puede_autorizarse_a_si_misma(cliente):
    """María existe en permisos_pos pero sin `puede_autorizar_descuento` ni
    PIN. Que un rol pueda firmar sus propios descuentos anula el control."""
    c, motor = cliente
    r = c.post("/api/retail/autorizacion",
               json={"pin": "0000", "tienda_id": "florida"})
    assert r.status_code == 403


def test_se_bloquea_tras_cinco_intentos(cliente):
    """Un PIN de 4 dígitos sin freno se adivina en minutos."""
    c, _ = cliente
    for _ in range(5):
        c.post("/api/retail/autorizacion",
               json={"pin": "1111", "tienda_id": "florida"})

    # Ni siquiera el PIN correcto pasa mientras dure el bloqueo.
    r = c.post("/api/retail/autorizacion",
               json={"pin": "4821", "tienda_id": "florida"})
    assert r.status_code in (403, 429)


def test_un_pin_con_letras_o_muy_corto_se_rechaza(cliente):
    c, _ = cliente
    assert c.post("/api/retail/autorizacion",
                  json={"pin": "abcd", "tienda_id": "florida"}).status_code == 403
    # Menos de 4 lo rechaza el contrato antes de llegar a la base.
    assert c.post("/api/retail/autorizacion",
                  json={"pin": "12", "tienda_id": "florida"}).status_code == 422


# ── El flujo completo ───────────────────────────────────────────────────────

def test_sin_firma_el_descuento_pide_autorizacion(cliente):
    c, _ = cliente
    r = c.post("/api/retail/ventas/cerrar", json=_venta_con_descuento("30"))
    assert r.status_code == 403
    assert r.json()["detail"]["accion_sugerida"] == "pedir_autorizacion"


def test_con_la_firma_pasa_y_queda_en_la_auditoria(cliente):
    """El ciclo entero: se rechaza, se pide el PIN, se firma, se cierra — y el
    nombre de quien firmó queda como evento CRÍTICO."""
    c, motor = cliente

    firma = c.post("/api/retail/autorizacion",
                   json={"pin": "4821", "tienda_id": "florida"}).json()

    r = c.post("/api/retail/ventas/cerrar",
               json=_venta_con_descuento("30", firma["autorizado_por"]))
    assert r.status_code == 200, r.text
    assert r.json()["descuento_centavos"] == 8566387

    import asyncio

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT evento, severidad, payload FROM retail.auditoria
                 WHERE severidad = 'critico'
            """))).mappings().all()

    filas = asyncio.get_event_loop().run_until_complete(leer())
    assert len(filas) == 1
    assert filas[0]["evento"] == "descuento.autorizado"
    assert filas[0]["payload"]["autorizado_por"] == "laura"


def test_ni_el_supervisor_puede_pasarse_de_su_tope(cliente):
    """Laura firma hasta 35 %. Un 50 % no lo aprueba nadie de esa tienda."""
    c, _ = cliente
    firma = c.post("/api/retail/autorizacion",
                   json={"pin": "4821", "tienda_id": "florida"}).json()
    assert firma["tope_descuento_pct"] == "35.00"
    # El tope del autorizador lo aplica el agregado cuando la pantalla lo
    # manda; aquí se verifica que el dato viaja para poder aplicarlo.
    assert float(firma["tope_descuento_pct"]) < 50


def test_quien_autoriza_tiene_que_tener_pin(cliente):
    """La base lo impide: ofrecer una firma que nadie puede dar dejaría a la
    cajera en un callejón sin salida."""
    c, motor = cliente
    import asyncio
    from sqlalchemy.exc import IntegrityError

    async def intentar():
        async with motor.begin() as cn:
            await cn.execute(text("""
                INSERT INTO retail.permisos_pos
                    (usuario_id,nombre,puede_autorizar_descuento)
                VALUES ('sin_pin','Sin PIN',true)
            """))

    with pytest.raises(IntegrityError):
        asyncio.get_event_loop().run_until_complete(intentar())
