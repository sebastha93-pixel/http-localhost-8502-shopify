"""Poder LEER la auditoría, que hasta ahora no se podía.

La cadena de hash existe desde la migración 0001 y ya tiene eventos críticos
dentro. `verificar_cadena` estaba escrito y sólo lo llamaba una prueba: no
había endpoint ni pantalla.

O sea que se estaba registrando todo con mucho cuidado, encadenado con SHA-256
para que una modificación a mano se note, y nadie podía mirarlo. **Un control
que no se puede consultar no es un control; es un archivo.**
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

SESION = "01JQ8X4T5N6P001R8S9V0W1X2Y"
VENTA = "01JQ8X4T5N7V001R8S9V0W1X2Y"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y42"
UBICACION = "tienda:florida"
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
        ("INSERT INTO retail.cajas (id,tienda_id,nombre,prefijo_factura) "
         "VALUES ('florida_caja1','florida','Caja 01','FV-20')", {}),
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
        # Laura ve la auditoría; María no.
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,puede_ver_auditoria,puede_anular_venta,"
         " puede_mover_caja) "
         "VALUES ('laura','Laura M.','{florida}',true,true,true)", {}),
        ("INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas) "
         "VALUES ('maria','María R.','{florida}')", {}),
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)

    app = FastAPI()
    app.include_router(router)

    def entrar_como(uid: str, nombre: str):
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=uid, email=f"{uid}@male.com", nombre=nombre, rol="user",
            permisos={"retail": ["ver", "modificar"]})

    entrar_como("maria", "María R.")

    with TestClient(app) as c:
        t = c.post("/api/retail/caja/turno", json={
            "sesion_id": SESION, "tienda_id": "florida",
            "caja_id": "florida_caja1"}).json()
        r = c.post("/api/retail/ventas/cerrar", json={
            "venta_id": VENTA,
            "numero": f"FV-20-{t['consecutivo_siguiente']}",
            "tienda_id": "florida", "caja_id": "florida_caja1",
            "sesion_id": SESION, "ubicacion_id": UBICACION,
            "lineas": [{"sku": "92611-1T10", "cantidad": 2,
                        "precio_unitario_centavos": PRECIO,
                        "descripcion": "Jean · 10"}],
            "pagos": [{"medio_pago_id": "efectivo",
                       "monto_centavos": PRECIO * 2, "es_efectivo": True}]})
        assert r.status_code == 200, r.text
        yield c, motor, entrar_como

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _leer(c, **extra):
    p = {"tienda_id": "florida", **extra}
    return c.get("/api/retail/auditoria", params=p)


# ── El permiso ──────────────────────────────────────────────────────────────

def test_sin_permiso_no_se_lee_la_auditoria(entorno):
    """Dice quién descontó, quién anuló y quién sacó plata: es exactamente la
    información con la que se supervisa a un equipo."""
    c, _, _ = entorno
    r = _leer(c)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "sin_permiso_auditoria"


def test_con_permiso_si(entorno):
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    assert _leer(c).status_code == 200


# ── Lo que se ve ────────────────────────────────────────────────────────────

def test_trae_los_eventos_con_nombre_y_caja_legibles(entorno):
    """`maria` y `florida_caja1` son identificadores. En la pantalla van
    «María R.» y «Caja 01», que es lo que sirve cuando alguien revisa."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    d = _leer(c).json()

    eventos = {e["evento"]: e for e in d["eventos"]}
    assert "venta.cerrada" in eventos
    assert eventos["venta.cerrada"]["quien"] == "María R."
    assert eventos["venta.cerrada"]["caja"] == "Caja 01"
    assert len(eventos["venta.cerrada"]["cuando"]) == 11   # DD/MM HH:MM


def test_cada_evento_trae_una_linea_en_español(entorno):
    """El resumen se arma en el SERVIDOR. Dejarlo a la pantalla obliga a un
    `switch` por tipo de evento que se desincroniza en cuanto alguien agrega
    uno nuevo — y entonces el evento nuevo sale como un volcado de JSON."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    d = _leer(c).json()

    venta = next(e for e in d["eventos"] if e["evento"] == "venta.cerrada")
    assert "$339.800" in venta["resumen"]
    assert "2 u" in venta["resumen"]

    abierta = next(e for e in d["eventos"] if e["evento"] == "caja.abierta")
    assert "turno #1" in abierta["resumen"]


def test_se_puede_filtrar_por_severidad(entorno):
    """Lo que mira la administradora un lunes: sólo lo crítico."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    c.post(f"/api/retail/ventas/{VENTA}/anular",
           json={"motivo": "prueba de anulación para auditoría"})

    todos = _leer(c).json()
    criticos = _leer(c, severidad="critico").json()

    assert criticos["total"] < todos["total"]
    assert {e["evento"] for e in criticos["eventos"]} == {"venta.anulada"}
    assert all(e["severidad"] == "critico" for e in criticos["eventos"])


def test_el_mas_reciente_va_primero(entorno):
    """Se lee de arriba: lo que acaba de pasar es lo que se está buscando."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    c.post(f"/api/retail/ventas/{VENTA}/anular",
           json={"motivo": "prueba de orden en la auditoría"})
    d = _leer(c).json()
    assert d["eventos"][0]["evento"] == "venta.anulada"


# ── LA CADENA, que es el punto ──────────────────────────────────────────────

def test_dice_si_la_cadena_esta_INTEGRA(entorno):
    """El veredicto viaja JUNTO a los eventos, no en otra pantalla. Una lista
    sin decir si la cadena aguanta invita a creérsela, y son justo los eventos
    que alguien querría alterar."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    d = _leer(c).json()
    assert d["integra"] is True
    assert d["eventos_verificados"] >= 2
    assert d["motivo_ruptura"] is None


def test_alterar_la_tabla_A_MANO_se_nota_y_dice_DONDE(entorno):
    """ADR-010. No impide editar la base: hace que se note.

    Y señala el evento: «la auditoría no cuadra» sin decir cuál no le sirve a
    nadie que tenga que investigarlo.
    """
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")

    async def alterar():
        async with motor.begin() as cn:
            await cn.execute(text("""
                UPDATE retail.auditoria
                   SET payload = jsonb_set(payload, '{total}', '1')
                 WHERE evento = 'venta.cerrada'
            """))

    asyncio.get_event_loop().run_until_complete(alterar())

    d = _leer(c).json()
    assert d["integra"] is False
    assert d["motivo_ruptura"] == "payload_alterado"
    assert d["evento_roto"] == "venta.cerrada"


def test_borrar_un_eslabon_tambien_rompe_la_cadena(entorno):
    """Editar deja rastro; borrar también tiene que dejarlo, o la forma de
    tapar algo sería simplemente quitarlo."""
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")

    async def borrar():
        async with motor.begin() as cn:
            # La tabla tiene REVOKE DELETE para el rol de la app; aquí se
            # borra como dueño, que es justo el escenario a detectar.
            await cn.execute(text(
                "DELETE FROM retail.auditoria WHERE evento='caja.abierta'"))

    asyncio.get_event_loop().run_until_complete(borrar())
    d = _leer(c).json()
    assert d["integra"] is False


def test_un_evento_nuevo_no_rompe_nada(entorno):
    """La cadena tiene que seguir cuadrando al escribir encima: si cada evento
    nuevo la rompiera, el verificador sería inútil desde el primer día."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    assert _leer(c).json()["integra"] is True

    c.post("/api/retail/caja/movimientos", json={
        "movimiento_id": "01JQ8X4T5N7M001R8S9V0W1X2Y", "sesion_id": SESION,
        "tipo": "retiro", "monto_centavos": 100000,
        "motivo": "sangría de prueba"})

    d = _leer(c).json()
    assert d["integra"] is True
    assert any(e["evento"] == "caja.retiro" for e in d["eventos"])
