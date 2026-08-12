"""El cierre de caja, de punta a punta.

Es el momento del día en que el sistema deja de creerle a la cajera y compara.
Tres cosas tienen que ser ciertas o el arqueo no mide nada:

1. **El esperado no se muestra antes de contar** (INV-C4). Si la pantalla dice
   «deberían ser $1.240.000», eso es lo que se teclea, y la diferencia siempre
   da cero.
2. **Una diferencia grande no se cierra sola** (INV-C5). Necesita justificación
   escrita, y que quien cierra tenga permiso para hacerlo. La firma por PIN de
   un tercero se quitó: una sola credencial, correo y contraseña.
3. **Cerrado es cerrado.** Después no se toca.

Y una cuarta que no es una regla sino la razón de todo: el turno tiene que
poder cerrarse, porque `ux_sesion_abierta` sólo admite uno abierto por caja.
Un cierre roto deja la tienda sin poder vender al día siguiente.
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
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y42"
UBICACION = "tienda:florida"
BASE = 20000000          # $200.000 de base
UMBRAL = 500000          # $5.000: por encima hay que justificar


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
        ("INSERT INTO retail.tiendas (id,nombre,base_caja,umbral_descuadre) "
         "VALUES ('florida','Florida',:b,:u)", {"b": BASE, "u": UMBRAL}),
        ("INSERT INTO retail.cajas (id,tienda_id,nombre) "
         "VALUES ('florida_caja1','florida','Caja 1')", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": UBICACION}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id,orden) "
         "VALUES ('efectivo','Efectivo','efectivo',12243,1)", {}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id,orden) "
         "VALUES ('tarjeta','Tarjeta','tarjeta',12244,2)", {}),
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,precio_con_iva) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean',16990000)",
         {"v": VARIANTE}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:u,:v,50)", {"u": UBICACION, "v": VARIANTE}),
        # Laura puede cerrar con descuadre y ver el esperado. María no.
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,tope_descuento_pct,"
         " puede_cerrar_con_descuadre,puede_ver_esperado) "
         "VALUES ('laura','Laura M.','{florida}',35,true,true)", {}),
        ("INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas) "
         "VALUES ('maria','María R.','{florida}')", {}),
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
        # El turno se abre por el endpoint real: así la base queda anotada
        # como movimiento, que es de donde sale el esperado.
        r = c.post("/api/retail/caja/turno",
                   json={"sesion_id": SESION, "tienda_id": "florida",
                         "caja_id": "florida_caja1"})
        assert r.status_code == 200, r.text
        yield c, motor

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


# Los ULID se diferencian EN MEDIO, no al final: el id de cada línea se
# deriva de los primeros 22 caracteres del ULID de la venta (es lo que hace
# idempotente el reintento). Con ULIDs reales esos 22 caracteres llevan 12 de
# azar y no chocan jamás; con dos constantes de prueba que sólo cambian al
# final, chocan siempre.
_ULID = "01JQ8X4T5N6P%03dR8S9V0W1X2Y"


def _vender(c, n: int, *, medio: str, monto: int, unidades: int = 1):
    """Una venta cerrada de verdad, no un INSERT a mano: lo que se arquea es
    el movimiento de caja que produce el cierre de la venta."""
    r = c.post("/api/retail/ventas/cerrar", json={
        "venta_id": _ULID % n, "numero": f"FV-20-{1300 + n}",
        "tienda_id": "florida", "caja_id": "florida_caja1",
        "sesion_id": SESION, "ubicacion_id": UBICACION,
        "lineas": [{"sku": "92611-1T10", "cantidad": unidades,
                    "precio_unitario_centavos": monto // unidades,
                    "descripcion": "Jean · 10"}],
        "pagos": [{"medio_pago_id": medio, "monto_centavos": monto,
                   "es_efectivo": medio == "efectivo"}],
    })
    assert r.status_code == 200, r.text
    return r.json()


def _resumen(c):
    r = c.get("/api/retail/caja/cierre/resumen", params={"sesion_id": SESION})
    assert r.status_code == 200, r.text
    return r.json()


# ── INV-C4: el conteo es a ciegas ───────────────────────────────────────────

def test_la_cajera_no_ve_cuanto_deberia_haber(cliente):
    """Lo único que impide que el arqueo sea un trámite."""
    c, _ = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)

    d = _resumen(c)
    assert d["cierre_ciego"] is True
    assert d["esperado_por_medio"] is None, (
        "se le está diciendo a la cajera el número que tiene que escribir"
    )
    # Lo que SÍ ve: cuántas transacciones hizo y por cuánto vendió. Eso no
    # le dice cuánto hay en el cajón, porque no incluye la base.
    assert d["transacciones"] == 1
    assert d["ventas_brutas_centavos"] == 16990000
    assert d["base_inicial_centavos"] == BASE


def test_un_supervisor_si_puede_verlo(cliente):
    """Laura tiene `puede_ver_esperado`: para revisar una caja ajena hay que
    poder ver el esperado sin declarar nada."""
    c, motor = cliente
    from backend.core.security import CurrentUser, get_current_user
    c.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="laura", email="l@male.com", nombre="Laura", rol="admin",
        permisos={"retail": ["ver", "modificar"]})

    _vender(c, 1, medio="efectivo", monto=16990000)
    d = _resumen(c)
    assert d["esperado_por_medio"]["efectivo"] == BASE + 16990000


# ── El camino normal: cuadra ────────────────────────────────────────────────

def test_cerrar_cuadrado_deja_el_turno_cerrado_y_la_caja_libre(cliente):
    """La prueba que justifica toda la vista: sin esto, `ux_sesion_abierta`
    deja la caja bloqueada para siempre después del primer turno."""
    c, motor = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)
    _vender(c, 2, medio="tarjeta", monto=25000000)

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [
            {"medio_pago_id": "efectivo", "contado_centavos": BASE + 16990000},
            {"medio_pago_id": "tarjeta", "contado_centavos": 25000000},
        ],
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["diferencia_centavos"] == 0
    assert d["cuadro"] is True

    # Y ahora la caja admite un turno nuevo.
    r2 = c.post("/api/retail/caja/turno",
                # Igual que arriba: distinto EN MEDIO. El id del movimiento de
                # la base se deriva de sesion_id[:20].
                json={"sesion_id": "01JQ8X4T5N77R8S9V0W1X2Y3ZQ",
                      "tienda_id": "florida", "caja_id": "florida_caja1"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["numero_turno"] == 2


def test_al_cerrar_queda_registrado_el_esperado_contra_lo_contado(cliente):
    """El arqueo tiene que ser auditable después. Guardar sólo la diferencia
    haría imposible saber cuál de los dos números estaba mal."""
    c, motor = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)
    contado = BASE + 16990000 - 300000        # faltan $3.000, bajo el umbral

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo", "contado_centavos": contado}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["diferencia_centavos"] == -300000
    assert r.json()["cuadro"] is False

    import asyncio

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT medio_pago_id, declarado, esperado
                  FROM retail.arqueo_conteos WHERE sesion_id = :s
            """), {"s": SESION})).mappings().all()

    filas = asyncio.get_event_loop().run_until_complete(leer())
    assert len(filas) == 1
    assert filas[0]["declarado"] == contado
    assert filas[0]["esperado"] == BASE + 16990000


# ── INV-C5: un descuadre grande no se cierra solo ───────────────────────────

def test_un_faltante_grande_exige_justificacion(cliente):
    c, _ = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo",
                     "contado_centavos": BASE + 16990000 - 8000000}],
    })
    assert r.status_code == 400
    assert "justificación" in r.json()["detail"]["mensaje"].lower()


def test_un_sobrante_grande_tambien(cliente):
    """Plata de más es plata sin venta que la explique. No es buena noticia."""
    c, _ = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo",
                     "contado_centavos": BASE + 16990000 + 8000000}],
    })
    assert r.status_code == 400


def test_con_justificacion_pero_sin_permiso_tampoco_cierra(cliente):
    """Escribir «me equivoqué» no es un control.

    María cuenta, pero no tiene `puede_cerrar_con_descuadre`. Antes esto se
    resolvía con el PIN de un supervisor en el mostrador; ahora la salida es
    que ese supervisor entre con su correo. Es más lento a propósito: la
    alternativa era que la cajera firmara su propio faltante.
    """
    c, _ = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "justificacion": "se me cayó un billete y no lo encontré",
        "conteos": [{"medio_pago_id": "efectivo",
                     "contado_centavos": BASE + 16990000 - 8000000}],
    })
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["error"] == "sin_permiso_descuadre"
    assert d["accion_sugerida"] == "entrar_con_otro_usuario"


def test_con_permiso_y_justificacion_cierra_y_queda_como_critico(cliente):
    """Laura entra con SU sesión y cierra. Quien cierra es quien firma."""
    c, motor = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)

    from backend.core.security import CurrentUser, get_current_user
    c.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="laura", email="l@male.com", nombre="Laura", rol="admin",
        permisos={"retail": ["ver", "modificar"]})

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "justificacion": "faltante detectado, se descuenta de nómina",
        "conteos": [{"medio_pago_id": "efectivo",
                     "contado_centavos": BASE + 16990000 - 8000000}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["autorizado_por"] == "laura"
    # La pantalla muestra el NOMBRE; el id sólo sirve para la auditoría.
    assert r.json()["autorizado_por_nombre"] == "Laura M."
    assert r.json()["diferencia_centavos"] == -8000000

    import asyncio

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT evento, severidad, payload FROM retail.auditoria
                 WHERE evento = 'caja.cerrada'
            """))).mappings().all()

    filas = asyncio.get_event_loop().run_until_complete(leer())
    assert len(filas) == 1
    assert filas[0]["severidad"] == "critico", (
        "un cierre descuadrado que no sale como crítico no lo revisa nadie"
    )
    assert filas[0]["payload"]["cerrada_por"] == "laura"
    assert filas[0]["payload"]["justificacion"]



# ── INV-C2: no se arquea con ventas a medias ────────────────────────────────

def test_no_se_puede_cerrar_con_una_venta_en_borrador(cliente):
    """Un carrito abierto es plata cobrada que el arqueo no ve."""
    c, motor = cliente
    import asyncio

    async def borrador():
        async with motor.begin() as cn:
            await cn.execute(text("""
                INSERT INTO retail.ventas
                    (id,numero,prefijo,consecutivo,tienda_id,caja_id,sesion_id,
                     cajera_id,estado,moneda,subtotal,descuento_total,
                     total,pagado)
                VALUES (:i,'FV-20-9999','FV-20',9999,'florida','florida_caja1',
                        :s,'maria','borrador','COP',0,0,0,0)
            """), {"i": _ULID % 99, "s": SESION})

    asyncio.get_event_loop().run_until_complete(borrador())

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo", "contado_centavos": BASE}],
    })
    assert r.status_code == 400
    assert "borrador" in r.json()["detail"]["mensaje"].lower()


# ── Cerrado es cerrado ──────────────────────────────────────────────────────

def test_no_se_puede_cerrar_dos_veces(cliente):
    c, _ = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)
    cuerpo = {"sesion_id": SESION,
              "conteos": [{"medio_pago_id": "efectivo",
                           "contado_centavos": BASE + 16990000}]}

    assert c.post("/api/retail/caja/cierre", json=cuerpo).status_code == 200
    r = c.post("/api/retail/caja/cierre", json=cuerpo)
    assert r.status_code == 400
    assert "cerr" in r.json()["detail"]["mensaje"].lower()


def test_falta_declarar_un_medio_y_no_cierra(cliente):
    """Se vendió con tarjeta pero sólo se contó el efectivo. Cerrar así
    dejaría el datáfono sin conciliar y nadie se enteraría."""
    c, _ = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)
    _vender(c, 2, medio="tarjeta", monto=25000000)

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo",
                     "contado_centavos": BASE + 16990000}],
    })
    assert r.status_code == 400
    assert "tarjeta" in r.json()["detail"]["mensaje"].lower()


def test_el_efectivo_hay_que_contarlo_aunque_no_se_haya_vendido_nada(cliente):
    """Turno sin ventas: la base sigue estando en el cajón."""
    c, _ = cliente
    d = _resumen(c)
    assert d["transacciones"] == 0

    r = c.post("/api/retail/caja/cierre",
               json={"sesion_id": SESION, "conteos": []})
    assert r.status_code == 400
    assert "efectivo" in r.json()["detail"]["mensaje"].lower()

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo", "contado_centavos": BASE}]})
    assert r.status_code == 200, r.text
    assert r.json()["cuadro"] is True


def test_un_descuadre_pequeno_es_aviso_y_no_critico(cliente):
    """El umbral no sólo decide quién puede cerrar: decide qué merece que
    alguien lo mire. Si $3.000 de vuelto mal dado entra como crítico, el log
    de críticos tiene entradas todos los días y deja de ser una señal."""
    c, motor = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo",
                     "contado_centavos": BASE + 16990000 - 300000}],
    })
    assert r.status_code == 200, r.text

    import asyncio

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT severidad FROM retail.auditoria
                 WHERE evento = 'caja.cerrada'
            """))).scalar()

    assert asyncio.get_event_loop().run_until_complete(leer()) == "aviso"


def test_un_cierre_cuadrado_no_ensucia_el_log(cliente):
    c, motor = cliente
    _vender(c, 1, medio="efectivo", monto=16990000)

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo",
                     "contado_centavos": BASE + 16990000}],
    })
    assert r.status_code == 200, r.text

    import asyncio

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT severidad FROM retail.auditoria
                 WHERE evento = 'caja.cerrada'
            """))).scalar()

    assert asyncio.get_event_loop().run_until_complete(leer()) == "info"
