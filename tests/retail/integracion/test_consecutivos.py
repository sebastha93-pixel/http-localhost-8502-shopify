"""Bloques de consecutivos — lo que hace posible vender sin internet.

EL BUG QUE ESTO ARREGLA. La pantalla numeraba con `Date.now() % 100000`. Eso se
repite **exactamente cada 100 segundos**, y como la base tiene
`ux_venta_numero UNIQUE (caja_id, prefijo, consecutivo)`, dos ventas separadas
por ese intervalo chocan: la segunda falla en el mostrador con la clienta
esperando. Con cien ventas al día, la probabilidad de que le pase a alguna caja
ronda el 5 % diario — semanas, no años.

Lo que se prueba aquí: que dos cajas nunca comparten números, que reanudar no
gasta un bloque, y que un número inventado no entra.
"""
from __future__ import annotations

import asyncio
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

UBICACION = "tienda:florida"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y42"
PRECIO = 16990000


@pytest_asyncio.fixture()
async def entorno():
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
        # Dos cajas en la misma tienda: el caso que el bug rompía.
        ("INSERT INTO retail.cajas (id,tienda_id,nombre,prefijo_factura) "
         "VALUES ('florida_caja1','florida','Caja 1','FV-20')", {}),
        ("INSERT INTO retail.cajas (id,tienda_id,nombre,prefijo_factura) "
         "VALUES ('florida_caja2','florida','Caja 2','FV-20')", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": UBICACION}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
         "VALUES ('efectivo','Efectivo','efectivo',12243)", {}),
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,precio_con_iva) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean',:p)",
         {"v": VARIANTE, "p": PRECIO}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:u,:v,500)", {"u": UBICACION, "v": VARIANTE}),
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,tope_descuento_pct) "
         "VALUES ('maria','María R.','{florida}',10)", {}),
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="maria", email="m@male.com", nombre="María R.", rol="user",
        permisos={"retail": ["ver", "modificar"]})

    with TestClient(app) as c:
        yield c, motor

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _abrir(c, caja: str, sufijo: str) -> dict:
    r = c.post("/api/retail/caja/turno", json={
        "sesion_id": f"01JQ8X4T5N6P{sufijo}R8S9V0W1X2Y",
        "tienda_id": "florida", "caja_id": caja})
    assert r.status_code == 200, r.text
    return r.json()


def _vender(c, *, caja: str, sesion: str, numero: str, n: int):
    return c.post("/api/retail/ventas/cerrar", json={
        "venta_id": "01JQ8X4T5N7P%03dR8S9V0W1X2Y" % n, "numero": numero,
        "tienda_id": "florida", "caja_id": caja, "sesion_id": sesion,
        "ubicacion_id": UBICACION,
        "lineas": [{"sku": "92611-1T10", "cantidad": 1,
                    "precio_unitario_centavos": PRECIO, "descripcion": "Jean"}],
        "pagos": [{"medio_pago_id": "efectivo", "monto_centavos": PRECIO,
                   "es_efectivo": True}],
    })


# ── El turno reparte numeración ─────────────────────────────────────────────

def test_abrir_turno_entrega_un_bloque(entorno):
    """Un turno abierto sin bloque es una caja que no puede numerar, y una caja
    que no puede numerar no puede vender. Nacen juntos, en la misma
    transacción."""
    c, _ = entorno
    t = _abrir(c, "florida_caja1", "001")
    assert t["prefijo"] == "FV-20"
    assert t["consecutivo_desde"] >= 1
    assert t["consecutivo_hasta"] > t["consecutivo_desde"]
    assert t["consecutivo_siguiente"] == t["consecutivo_desde"]


def test_dos_cajas_NUNCA_comparten_numeros(entorno):
    """El corazón del asunto. Con `Date.now() % 100000` las dos cajas de una
    tienda podían generar el mismo número al mismo tiempo."""
    c, _ = entorno
    uno = _abrir(c, "florida_caja1", "001")
    dos = _abrir(c, "florida_caja2", "002")

    rango1 = set(range(uno["consecutivo_desde"], uno["consecutivo_hasta"] + 1))
    rango2 = set(range(dos["consecutivo_desde"], dos["consecutivo_hasta"] + 1))
    assert not (rango1 & rango2), "las dos cajas pueden emitir el mismo número"


def test_reanudar_NO_gasta_un_bloque_nuevo(entorno):
    """Recargar la pantalla a media mañana dejaría un hueco de 500 números cada
    vez. Y la cajera recarga."""
    c, _ = entorno
    primero = _abrir(c, "florida_caja1", "001")
    for _ in range(3):
        otra = c.get("/api/retail/caja/turno-actual",
                     params={"caja_id": "florida_caja1"}).json()
        assert otra["consecutivo_desde"] == primero["consecutivo_desde"]
        assert otra["consecutivo_hasta"] == primero["consecutivo_hasta"]


def test_pedir_bloque_nuevo_continua_donde_termino_el_anterior(entorno):
    c, _ = entorno
    primero = _abrir(c, "florida_caja1", "001")
    r = c.post("/api/retail/caja/consecutivos", params={"caja_id": "florida_caja1"})
    assert r.status_code == 200, r.text
    segundo = r.json()
    assert segundo["desde"] == primero["consecutivo_hasta"] + 1
    assert segundo["siguiente"] == segundo["desde"]


def test_solo_hay_un_bloque_vigente_por_caja(entorno):
    """Lo garantiza `ux_bloque_vigente`. Dos vigentes significarían dos
    dispositivos numerando en rangos distintos y creyendo ambos que el suyo es
    el bueno."""
    c, motor = entorno
    _abrir(c, "florida_caja1", "001")
    for _ in range(3):
        c.post("/api/retail/caja/consecutivos", params={"caja_id": "florida_caja1"})

    async def contar():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT count(*) FROM retail.bloques_consecutivo
                 WHERE caja_id = 'florida_caja1' AND NOT agotado
            """))).scalar()

    assert asyncio.get_event_loop().run_until_complete(contar()) == 1


# ── La venta ────────────────────────────────────────────────────────────────

def test_una_venta_con_numero_del_bloque_pasa(entorno):
    c, _ = entorno
    t = _abrir(c, "florida_caja1", "001")
    n = t["consecutivo_siguiente"]
    r = _vender(c, caja="florida_caja1", sesion=t["sesion_id"],
                numero=f"FV-20-{n}", n=1)
    assert r.status_code == 200, r.text


def test_un_numero_INVENTADO_no_entra(entorno):
    """El número llega en la petición porque el dispositivo lo asigna sin red.
    Sin comprobar de dónde salió, un cliente con un error —o modificado— numera
    encima de la otra caja, y eso no se descubre hasta que alguien cuadra la
    numeración meses después."""
    c, _ = entorno
    t = _abrir(c, "florida_caja1", "001")
    r = _vender(c, caja="florida_caja1", sesion=t["sesion_id"],
                numero="FV-20-987654", n=2)
    assert r.status_code == 400
    assert "bloque" in r.json()["detail"]["mensaje"].lower()


def test_una_caja_no_puede_usar_el_numero_de_LA_OTRA(entorno):
    c, _ = entorno
    uno = _abrir(c, "florida_caja1", "001")
    dos = _abrir(c, "florida_caja2", "002")
    # La caja 1 intenta emitir con un número del rango de la caja 2.
    r = _vender(c, caja="florida_caja1", sesion=uno["sesion_id"],
                numero=f"FV-20-{dos['consecutivo_desde']}", n=3)
    assert r.status_code == 400


def test_una_venta_OFFLINE_que_llega_tarde_se_acepta(entorno):
    """Un número del bloque ANTERIOR, ya reemplazado. Es exactamente lo que
    pasa cuando el dispositivo estuvo sin red: rechazarlo sería perder la venta
    que todo el diseño offline existe para no perder."""
    c, _ = entorno
    t = _abrir(c, "florida_caja1", "001")
    viejo = t["consecutivo_siguiente"]
    # La caja renueva mientras el dispositivo seguía sin señal.
    c.post("/api/retail/caja/consecutivos", params={"caja_id": "florida_caja1"})

    r = _vender(c, caja="florida_caja1", sesion=t["sesion_id"],
                numero=f"FV-20-{viejo}", n=4)
    assert r.status_code == 200, r.text


def test_el_numero_repetido_lo_frena_la_base(entorno):
    """La última red. Aunque el número venga de un bloque válido, dos ventas
    distintas con el mismo número no pueden coexistir."""
    c, _ = entorno
    t = _abrir(c, "florida_caja1", "001")
    n = t["consecutivo_siguiente"]
    assert _vender(c, caja="florida_caja1", sesion=t["sesion_id"],
                   numero=f"FV-20-{n}", n=5).status_code == 200
    r = _vender(c, caja="florida_caja1", sesion=t["sesion_id"],
                numero=f"FV-20-{n}", n=6)
    assert r.status_code >= 400, (
        "dos ventas distintas quedaron con el mismo número"
    )


# ── Lo que arreglaba el bug de origen ───────────────────────────────────────

def test_un_bloque_nuevo_nunca_pisa_lo_YA_VENDIDO(entorno):
    """Las ventas que existen hoy se numeraron con `Date.now() % 100000`, o sea
    en cualquier punto del rango. Arrendar desde cero produciría choques contra
    lo ya escrito."""
    c, motor = entorno
    t = _abrir(c, "florida_caja1", "001")

    async def venta_antigua():
        async with motor.begin() as cn:
            await cn.execute(text("""
                INSERT INTO retail.ventas
                    (id,numero,prefijo,consecutivo,tienda_id,caja_id,sesion_id,
                     cajera_id,estado,moneda,subtotal,descuento_total,total,
                     pagado,cerrada_en)
                VALUES (:i,'FV-20-88888','FV-20',88888,'florida','florida_caja1',
                        :s,'maria','cerrada','COP',1000,0,1000,1000,now())
            """), {"i": "01JQ8X4T5N7P888R8S9V0W1X2Y", "s": t["sesion_id"]})

    asyncio.get_event_loop().run_until_complete(venta_antigua())

    nuevo = c.post("/api/retail/caja/consecutivos",
                   params={"caja_id": "florida_caja1"}).json()
    assert nuevo["desde"] > 88888, (
        "el bloque nuevo pisa un número que ya se le entregó a una clienta"
    )


def test_el_prefijo_se_parte_por_el_ULTIMO_guion(entorno):
    """`FV-20-1334` es prefijo `FV-20` y consecutivo `1334`. Partir por el
    primero daría `FV` y `20-1334`, que no es un entero y revienta al guardar —
    y los prefijos de Siigo llevan guion dentro."""
    from backend.modules.retail.domain.venta.venta import Venta

    v = Venta.abrir(id="01JQ8X4T5N7P777R8S9V0W1X2Y", numero="FV-20-1334",
                    tienda_id="florida", caja_id="florida_caja1",
                    sesion_id="01JQ8X4T5N6P001R8S9V0W1X2Y", cajera_id="maria",
                    moneda="COP")
    assert v.prefijo == "FV-20"
    assert v.consecutivo == 1334


# ── El contador del servidor tiene que AVANZAR ──────────────────────────────

def test_vender_adelanta_el_contador_del_bloque(entorno):
    """El bug que se me escapó y encontré verificando en el navegador.

    Escribí `marcar_consumido` y nunca lo llamé. El contador del servidor se
    quedaba en el primer número del bloque, así que **cada recarga de la
    pantalla reiniciaba la numeración**: la venta siguiente chocaba con una ya
    hecha. La cola lo atrapaba y la marcaba rechazada —no se perdía en
    silencio— pero la clienta ya se había ido con un papel impreso de algo que
    nunca se registró, que es el peor final posible para un POS.
    """
    c, motor = entorno
    t = _abrir(c, "florida_caja1", "001")
    n = t["consecutivo_siguiente"]
    assert _vender(c, caja="florida_caja1", sesion=t["sesion_id"],
                   numero=f"FV-20-{n}", n=20).status_code == 200

    async def contador():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT siguiente FROM retail.bloques_consecutivo
                 WHERE caja_id = 'florida_caja1' AND NOT agotado
            """))).scalar()

    assert asyncio.get_event_loop().run_until_complete(contador()) == n + 1


def test_recargar_la_pantalla_NO_reinicia_la_numeracion(entorno):
    """Reanudar tiene que devolver el número SIGUIENTE, no el primero del
    bloque. La cajera recarga; si eso reinicia la cuenta, la segunda venta del
    día choca con la primera."""
    c, _ = entorno
    t = _abrir(c, "florida_caja1", "001")
    n = t["consecutivo_siguiente"]
    _vender(c, caja="florida_caja1", sesion=t["sesion_id"],
            numero=f"FV-20-{n}", n=21)

    reanudado = c.get("/api/retail/caja/turno-actual",
                      params={"caja_id": "florida_caja1"}).json()
    assert reanudado["consecutivo_siguiente"] == n + 1, (
        "recargar la pantalla devuelve un número ya usado"
    )


def test_una_venta_que_llega_TARDE_no_retrocede_el_contador(entorno):
    """Sincronizar una venta offline vieja no puede devolver el contador atrás:
    los números que se repartieron mientras tanto ya están en tiquetes."""
    c, motor = entorno
    t = _abrir(c, "florida_caja1", "001")
    base = t["consecutivo_siguiente"]

    _vender(c, caja="florida_caja1", sesion=t["sesion_id"],
            numero=f"FV-20-{base + 5}", n=22)      # una moderna
    _vender(c, caja="florida_caja1", sesion=t["sesion_id"],
            numero=f"FV-20-{base}", n=23)          # la que venía sin red

    async def contador():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT siguiente FROM retail.bloques_consecutivo
                 WHERE caja_id = 'florida_caja1' AND NOT agotado
            """))).scalar()

    assert asyncio.get_event_loop().run_until_complete(contador()) == base + 6
