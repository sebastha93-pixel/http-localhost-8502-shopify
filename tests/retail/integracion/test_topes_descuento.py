"""El tope de descuento, que ahora es EL control.

Antes había dos capas: el tope del rol y, por encima, el PIN de un supervisor
que firmaba. El PIN se quitó por decisión del negocio —a la plataforma se entra
con correo y contraseña, y no va a haber una segunda credencial—, así que sólo
queda una capa. Cuando sólo queda una, esa tiene que sostenerse sola.

De ahí la prueba que más importa de este archivo: **el tope se lee de la base,
no de la petición**. Viajaba en el cuerpo (`tope_descuento`) porque la pantalla
lo conocía; con el PIN eso no bastaba para colarse —hacía falta la firma
igual—, pero sin PIN un cliente modificado que mande su propio tope se aprueba
los descuentos solo.
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
VENTA = "01JQ8X4T5N6P001R8S9V0W1X2Y"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y42"
UBICACION = "tienda:florida"
PRECIO = 16990000          # $169.900


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
        ("INSERT INTO retail.cajas (id,tienda_id,nombre,prefijo_factura) "
         "VALUES ('florida_caja1','florida','Caja 1','FV-20')", {}),
        # Bloque de consecutivos: en produccion lo arrienda la apertura de
        # turno. Sin el, ninguna venta pasa la validacion de numeracion.
        ("INSERT INTO retail.bloques_consecutivo "
         "(caja_id,prefijo,desde,hasta,siguiente) "
         "VALUES ('florida_caja1','FV-20',1,99999,1)", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": UBICACION}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
         "VALUES ('efectivo','Efectivo','efectivo',12243)", {}),
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,precio_con_iva) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean',:p)",
         {"v": VARIANTE, "p": PRECIO}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:u,:v,50)", {"u": UBICACION, "v": VARIANTE}),
        ("INSERT INTO retail.sesiones_caja "
         "(id,tienda_id,caja_id,numero_turno,base_inicial,abierta_por) "
         "VALUES (:s,'florida','florida_caja1',1,20000000,'maria')",
         {"s": SESION}),
        # María vende con tope 10 %. Laura, supervisora, con 35 %.
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,tope_descuento_pct) "
         "VALUES ('maria','María R.','{florida}',10)", {}),
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,tope_descuento_pct,"
         " puede_cerrar_con_descuadre) "
         "VALUES ('laura','Laura M.','{florida}',35,true)", {}),
        # Y alguien que ni siquiera tiene fila: no puede descontar nada.
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)

    app = FastAPI()
    app.include_router(router)

    def entrar_como(usuario_id: str, nombre: str):
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=usuario_id, email=f"{usuario_id}@male.com", nombre=nombre,
            rol="user", permisos={"retail": ["ver", "modificar"]})

    entrar_como("maria", "María R.")

    with TestClient(app) as c:
        yield c, motor, entrar_como

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _venta(pct: str, *, sufijo: int = 1, extra: dict | None = None) -> dict:
    linea = {"sku": "92611-1T10", "cantidad": 2,
             "precio_unitario_centavos": PRECIO,
             "descripcion": "Jean · 10",
             "descuento_porcentaje": pct,
             "descuento_motivo": "clienta insistió"}
    linea.update(extra or {})
    return {
        "venta_id": "01JQ8X4T5N6P%03dR8S9V0W1X2Y" % sufijo,
        "numero": f"FV-20-{1300 + sufijo}",
        "tienda_id": "florida", "caja_id": "florida_caja1",
        "sesion_id": SESION, "ubicacion_id": UBICACION,
        "lineas": [linea],
        "pagos": [{"medio_pago_id": "efectivo", "monto_centavos": 40000000,
                   "es_efectivo": True}],
    }


# ── Lo que se sostiene solo ─────────────────────────────────────────────────

def test_dentro_del_tope_pasa(entorno):
    c, _, _ = entorno
    r = c.post("/api/retail/ventas/cerrar", json=_venta("10"))
    assert r.status_code == 200, r.text
    assert r.json()["descuento_centavos"] == 3398000


def test_por_encima_del_tope_no_pasa(entorno):
    """Y NO es un «pide autorización»: es un no. La única salida es que entre
    alguien con más tope, con su correo y su contraseña."""
    c, _, _ = entorno
    r = c.post("/api/retail/ventas/cerrar", json=_venta("30"))
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["error"] == "sobre_el_tope"
    assert d["accion_sugerida"] == "entrar_con_otro_usuario"


def test_el_mismo_descuento_pasa_si_lo_hace_quien_tiene_el_tope(entorno):
    """Esta es la vía de escape completa: no un PIN, una sesión distinta."""
    c, _, entrar_como = entorno
    assert c.post("/api/retail/ventas/cerrar",
                  json=_venta("30", sufijo=2)).status_code == 403

    entrar_como("laura", "Laura M.")
    r = c.post("/api/retail/ventas/cerrar", json=_venta("30", sufijo=3))
    assert r.status_code == 200, r.text


def test_ni_la_supervisora_se_pasa_de_SU_tope(entorno):
    """Nadie tiene tope infinito. Laura firma hasta 35 %."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    r = c.post("/api/retail/ventas/cerrar", json=_venta("50", sufijo=4))
    assert r.status_code == 403


def test_quien_no_tiene_fila_de_permisos_no_descuenta_nada(entorno):
    """Sin fila, el tope es 0 — no «sin límite». Un usuario nuevo del ERP no
    puede empezar regalando mercancía porque nadie lo configuró todavía."""
    c, _, entrar_como = entorno
    entrar_como("nadie", "Sin configurar")
    assert c.post("/api/retail/ventas/cerrar",
                  json=_venta("5", sufijo=5)).status_code == 403
    # Sin descuento sí puede vender: el tope limita el descuento, no la venta.
    sin_descuento = _venta("0", sufijo=6)
    sin_descuento["lineas"][0].pop("descuento_porcentaje")
    sin_descuento["lineas"][0].pop("descuento_motivo")
    assert c.post("/api/retail/ventas/cerrar",
                  json=sin_descuento).status_code == 200


def test_un_usuario_desactivado_pierde_su_tope(entorno):
    c, motor, entrar_como = entorno
    import asyncio

    async def desactivar():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.permisos_pos SET activo = false "
                " WHERE usuario_id = 'laura'"))

    asyncio.get_event_loop().run_until_complete(desactivar())
    entrar_como("laura", "Laura M.")
    assert c.post("/api/retail/ventas/cerrar",
                  json=_venta("30", sufijo=7)).status_code == 403


# ── LA PRUEBA QUE IMPORTA ───────────────────────────────────────────────────

def test_el_tope_NO_se_puede_mandar_en_la_peticion(entorno):
    """El agujero que dejó al descubierto quitar el PIN.

    El tope viajaba en el cuerpo porque la pantalla ya lo conocía. Mientras
    hubo PIN eso no alcanzaba para colarse: por encima del tope hacía falta la
    firma igual. Sin PIN, el tope ES el control — y un control que el cliente
    se autoasigna no controla nada.

    Se manda un `tope_descuento` de 100 junto a un descuento del 90 %. El
    servidor tiene que ignorarlo y usar el 10 % de María.
    """
    c, _, _ = entorno
    cuerpo = _venta("90", sufijo=8)
    cuerpo["tope_descuento"] = "100"

    r = c.post("/api/retail/ventas/cerrar", json=cuerpo)
    assert r.status_code == 403, (
        "el servidor le creyó al cliente el tope que se asignó a sí mismo"
    )


def test_tampoco_colandolo_en_la_linea(entorno):
    """La otra puerta: `autorizado_por` en la línea. Era el campo donde
    viajaba la firma del PIN; si el agregado todavía lo respetara, bastaría
    con inventarse un nombre."""
    c, _, _ = entorno
    r = c.post("/api/retail/ventas/cerrar",
               json=_venta("90", sufijo=9, extra={"autorizado_por": "laura"}))
    assert r.status_code == 403


# ── El rastro ───────────────────────────────────────────────────────────────

def test_el_descuento_queda_a_nombre_de_quien_lo_aplico(entorno):
    """Dentro del tope o no, un descuento sin rastro sigue siendo la vía para
    sacar mercancía. Ya no hay dos nombres —quien aplica y quien firma—, pero
    el que queda tiene que ser el de verdad."""
    c, motor, _ = entorno
    assert c.post("/api/retail/ventas/cerrar",
                  json=_venta("10", sufijo=10)).status_code == 200

    import asyncio

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT l.autorizado_por, l.descuento_motivo, v.cajera_id
                  FROM retail.venta_lineas l
                  JOIN retail.ventas v ON v.id = l.venta_id
                 WHERE l.descuento_monto > 0
            """))).mappings().all()

    filas = asyncio.get_event_loop().run_until_complete(leer())
    assert len(filas) == 1
    assert filas[0]["autorizado_por"] == "maria"
    assert filas[0]["cajera_id"] == "maria", (
        "la venta no quedó a nombre de quien la hizo"
    )
    assert filas[0]["descuento_motivo"] == "clienta insistió"


def test_ya_no_existe_el_endpoint_del_pin(entorno):
    """Un endpoint de autenticación que se queda a medio borrar es peor que
    uno vivo: nadie lo mantiene y sigue aceptando credenciales."""
    c, _, _ = entorno
    r = c.post("/api/retail/autorizacion",
               json={"pin": "4821", "tienda_id": "florida"})
    assert r.status_code == 404


def test_la_tabla_de_permisos_ya_no_guarda_pines(entorno):
    """Un hash de PIN olvidado en una columna es una credencial que nadie
    rota y que sigue estando en cada respaldo."""
    c, motor, _ = entorno
    import asyncio

    async def columnas():
        async with motor.connect() as cn:
            return {f[0] for f in (await cn.execute(text("""
                SELECT column_name FROM information_schema.columns
                 WHERE table_schema = 'retail' AND table_name = 'permisos_pos'
            """))).all()}

    cols = asyncio.get_event_loop().run_until_complete(columnas())
    assert "pin_hash" not in cols
    assert "intentos_fallidos" not in cols
    assert "bloqueado_hasta" not in cols
    # Y el permiso que sólo servía para teclear la firma de un tercero.
    assert "puede_autorizar_descuento" not in cols
    # Los que SÍ siguen mandando, atados al usuario que entra con su correo:
    assert {"tope_descuento_pct", "puede_cerrar_con_descuadre"} <= cols
