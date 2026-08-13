"""La tirilla — el papel que se lleva la clienta.

Dos cosas tienen que ser ciertas o el papel hace daño:

1. **Dice lo que quedó REGISTRADO**, no lo que la pantalla creía. Se arma
   leyendo la base; si el servidor guardó otra cosa, el papel lo delata en vez
   de taparlo.
2. **No se hace pasar por una factura.** Sin resolución DIAN y sin documento
   emitido, esto es un comprobante interno y va impreso diciéndolo. Un papel
   con pinta de documento fiscal que no lo es convierte un problema de software
   en un problema con la DIAN.
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
        ("INSERT INTO retail.tiendas "
         "(id,nombre,razon_social,nit,direccion,telefono,mensaje_tirilla) "
         "VALUES ('florida','Florida','Dirty Jeans S.A.S.','900123456-7',"
         "'Cra 43A #1-50, Medellín','(604) 444 5566',"
         "'Cambios dentro de 30 días con esta tirilla.')", {}),
        ("INSERT INTO retail.cajas (id,tienda_id,nombre,prefijo_factura) "
         "VALUES ('florida_caja1','florida','Caja 01','FV-20')", {}),
        # Bloque de consecutivos: en produccion lo arrienda la apertura de
        # turno. Sin el, ninguna venta pasa la validacion de numeracion.
        ("INSERT INTO retail.bloques_consecutivo "
         "(caja_id,prefijo,desde,hasta,siguiente) "
         "VALUES ('florida_caja1','FV-20',1,99999,1)", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": UBICACION}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
         "VALUES ('efectivo','Efectivo','efectivo',12243)", {}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
         "VALUES ('datafono','Tarjeta','tarjeta',12244)", {}),
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,precio_con_iva) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean Skinny',:p)",
         {"v": VARIANTE, "p": PRECIO}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:u,:v,50)", {"u": UBICACION, "v": VARIANTE}),
        ("INSERT INTO retail.sesiones_caja "
         "(id,tienda_id,caja_id,numero_turno,base_inicial,abierta_por) "
         "VALUES (:s,'florida','florida_caja1',1,20000000,'maria')",
         {"s": SESION}),
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,tope_descuento_pct) "
         "VALUES ('maria','María Restrepo','{florida}',10)", {}),
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="maria", email="m@male.com", nombre="María", rol="user",
        permisos={"retail": ["ver", "modificar"]})

    with TestClient(app) as c:
        yield c, motor

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _vender(c, *, descuento=None, pagos=None, cliente_id=None):
    linea = {"sku": "92611-1T10", "cantidad": 2,
             "precio_unitario_centavos": PRECIO, "descripcion": "Jean Skinny · 10"}
    if descuento:
        linea["descuento_porcentaje"] = descuento
        linea["descuento_motivo"] = "prenda con defecto menor"
    cuerpo = {
        "venta_id": VENTA, "numero": "FV-20-1334", "tienda_id": "florida",
        "caja_id": "florida_caja1", "sesion_id": SESION,
        "ubicacion_id": UBICACION, "lineas": [linea],
        "pagos": pagos or [{"medio_pago_id": "efectivo",
                            "monto_centavos": 40000000, "es_efectivo": True}],
    }
    if cliente_id:
        cuerpo["cliente_id"] = cliente_id
    r = c.post("/api/retail/ventas/cerrar", json=cuerpo)
    assert r.status_code == 200, r.text
    return r.json()


def _tirilla(c, venta_id=VENTA):
    r = c.get(f"/api/retail/ventas/{venta_id}/tirilla")
    assert r.status_code == 200, r.text
    return r.json()


# ── LO QUE NO PUEDE FALLAR: el papel no miente sobre lo que es ──────────────

def test_sin_resolucion_dian_NO_se_llama_factura(cliente):
    """Fase 3 no está hecha: no hay resolución ni documento emitido.

    Si esto devolviera `es_documento_fiscal: true`, la pantalla imprimiría un
    papel encabezado «FACTURA ELECTRÓNICA DE VENTA» que no ampara nada. Eso no
    es un error de redacción: es un problema con la DIAN.
    """
    c, _ = cliente
    _vender(c)
    d = _tirilla(c)
    assert d["es_documento_fiscal"] is False
    assert d["resolucion_dian"] is None
    assert d["cufe"] is None
    assert d["estado_fiscal"] in ("pendiente", "enviando")


def test_con_resolucion_pero_sin_emitir_TAMPOCO(cliente):
    """Tener resolución no basta: mientras el documento no salga, el papel
    todavía no ampara nada."""
    c, motor = cliente
    _vender(c)
    import asyncio

    async def con_resolucion():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.tiendas SET resolucion_dian = "
                "'Res. DIAN 18764... vigente hasta 2027' WHERE id='florida'"))

    asyncio.get_event_loop().run_until_complete(con_resolucion())
    assert _tirilla(c)["es_documento_fiscal"] is False


def test_con_resolucion_Y_documento_emitido_si_es_factura(cliente):
    c, motor = cliente
    _vender(c)
    import asyncio

    async def emitir():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.tiendas SET resolucion_dian = 'Res. DIAN 18764' "
                " WHERE id='florida'"))
            await cn.execute(text(
                "UPDATE retail.ventas SET estado_fiscal='emitido' WHERE id=:i"),
                {"i": VENTA})
            await cn.execute(text("""
                INSERT INTO retail.documentos_fiscales
                    (id, venta_id, tipo, proveedor, estado, numero, cufe,
                     payload_snapshot, emitido_en)
                VALUES (:d, :v, 'factura_electronica', 'siigo', 'emitido',
                        'FV-20-1334', :cufe, '{}'::jsonb, now())
            """), {"d": "01JQ8X4T5N6P900R8S9V0W1X2Y", "v": VENTA,
                   "cufe": "a" * 96})

    asyncio.get_event_loop().run_until_complete(emitir())
    d = _tirilla(c)
    assert d["es_documento_fiscal"] is True
    assert d["documento_fiscal"] == "FV-20-1334"
    assert len(d["cufe"]) == 96


# ── El emisor ───────────────────────────────────────────────────────────────

def test_lleva_los_datos_que_van_impresos_por_ley(cliente):
    """Razón social, NIT y dirección. Sin eso el papel no es soporte de nada,
    ni para la clienta que quiere cambiar la prenda ni para la DIAN."""
    c, _ = cliente
    _vender(c)
    d = _tirilla(c)
    assert d["razon_social"] == "Dirty Jeans S.A.S."
    assert d["nit"] == "900123456-7"
    assert d["direccion"] == "Cra 43A #1-50, Medellín"
    assert d["telefono"] == "(604) 444 5566"
    assert d["mensaje"].startswith("Cambios dentro de 30 días")


def test_nombra_a_la_caja_y_a_la_cajera_como_las_conoce_la_gente(cliente):
    """`florida_caja1` y `maria` son identificadores. En el papel van «Caja 01»
    y «María Restrepo», que es lo que sirve cuando alguien reclama."""
    c, _ = cliente
    _vender(c)
    d = _tirilla(c)
    assert d["caja_nombre"] == "Caja 01"
    assert d["cajera_nombre"] == "María Restrepo"


# ── Los números ─────────────────────────────────────────────────────────────

def test_los_totales_son_los_que_quedaron_guardados(cliente):
    c, _ = cliente
    t = _vender(c)
    d = _tirilla(c)
    assert d["total_centavos"] == t["total_centavos"] == 33980000
    assert d["unidades"] == 2
    assert d["vuelto_centavos"] == 40000000 - 33980000


def test_el_iva_va_INCLUIDO_no_sumado(cliente):
    """El precio de la etiqueta ES el total. Imprimir el IVA como una línea que
    suma daría un total distinto al que la clienta vio en la vitrina — que es
    exactamente el error que costó una migración entera."""
    c, _ = cliente
    _vender(c)
    d = _tirilla(c)
    assert d["base_gravable_centavos"] + d["iva_centavos"] == d["total_centavos"]
    assert d["total_centavos"] == 33980000


def test_el_descuento_lleva_su_motivo_impreso(cliente):
    """Es lo que permite revisar un descuento después sin abrir la auditoría —
    y lo que la clienta puede mostrar si le cobran distinto en un cambio."""
    c, _ = cliente
    _vender(c, descuento="10")
    d = _tirilla(c)
    linea = d["lineas"][0]
    assert linea["descuento_centavos"] == 3398000
    assert linea["descuento_motivo"] == "prenda con defecto menor"
    assert d["descuento_centavos"] == 3398000


def test_el_pago_mixto_sale_desglosado(cliente):
    """Con dos medios, la clienta tiene que poder ver cuánto fue con tarjeta:
    es lo que reclama el banco si el datáfono cobró de más."""
    c, _ = cliente
    _vender(c, pagos=[
        {"medio_pago_id": "efectivo", "monto_centavos": 10000000,
         "es_efectivo": True},
        {"medio_pago_id": "datafono", "monto_centavos": 23980000,
         "es_efectivo": False, "referencia": "APROB 004512"},
    ])
    d = _tirilla(c)
    assert len(d["pagos"]) == 2
    nombres = {p["nombre"]: p for p in d["pagos"]}
    assert nombres["Efectivo"]["monto_centavos"] == 10000000
    assert nombres["Tarjeta"]["monto_centavos"] == 23980000
    assert nombres["Tarjeta"]["referencia"] == "APROB 004512"


def test_la_fecha_va_en_hora_de_la_tienda(cliente):
    """En UTC−5, una venta de las 8 p.m. impresa en UTC saldría con la fecha
    del día siguiente. La clienta llega a cambiar con un papel que dice otro
    día que el del sistema."""
    c, _ = cliente
    _vender(c)
    d = _tirilla(c)
    assert len(d["fecha"]) == 16          # DD/MM/YYYY HH:MM
    assert d["fecha"][2] == "/" and d["fecha"][5] == "/"


# ── La clienta ──────────────────────────────────────────────────────────────

def test_sin_clienta_asignada_la_tirilla_sale_igual(cliente):
    """En el mostrador la mayoría no da sus datos. Exigirlos para imprimir
    frenaría la venta por un campo opcional."""
    c, _ = cliente
    _vender(c)
    d = _tirilla(c)
    assert d["cliente_nombre"] is None
    assert d["cliente_documento"] is None


def test_con_clienta_asignada_sale_su_nombre_completo(cliente):
    c, motor = cliente
    import asyncio
    cid = "01JQ8X4T5N6P800R8S9V0W1X2Y"

    async def crear():
        async with motor.begin() as cn:
            await cn.execute(text("""
                INSERT INTO retail.clientes
                    (id,tipo_documento,numero_documento,nombre,apellido)
                VALUES (:i,'CC','43567890','Ana','Gómez')
            """), {"i": cid})

    asyncio.get_event_loop().run_until_complete(crear())
    _vender(c, cliente_id=cid)
    d = _tirilla(c)
    assert d["cliente_nombre"] == "Ana Gómez"
    assert d["cliente_documento"] == "CC 43567890"


# ── Reimprimir, que es cuando se usa de verdad ──────────────────────────────

def test_se_puede_reimprimir_despues(cliente):
    """La clienta vuelve tres días después a cambiar la prenda. La tirilla se
    arma de la base, así que no depende de que la pantalla siga abierta."""
    c, _ = cliente
    _vender(c)
    primera = _tirilla(c)
    segunda = _tirilla(c)
    assert primera == segunda


def test_una_venta_que_no_existe_da_404_no_un_papel_en_blanco(cliente):
    c, _ = cliente
    r = c.get("/api/retail/ventas/01JQ8X4T5N6P999R8S9V0W1X2Y/tirilla")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "no_encontrada"


def test_una_venta_en_borrador_no_se_imprime(cliente):
    """Un carrito a medias no es un comprobante de nada. Imprimirlo daría a la
    clienta un papel por una venta que todavía no se cobró."""
    c, motor = cliente
    import asyncio
    borrador = "01JQ8X4T5N6P700R8S9V0W1X2Y"

    async def crear():
        async with motor.begin() as cn:
            await cn.execute(text("""
                INSERT INTO retail.ventas
                    (id,numero,prefijo,consecutivo,tienda_id,caja_id,sesion_id,
                     cajera_id,estado,moneda,subtotal,descuento_total,total,pagado)
                VALUES (:i,'FV-20-9999','FV-20',9999,'florida','florida_caja1',
                        :s,'maria','borrador','COP',0,0,0,0)
            """), {"i": borrador, "s": SESION})

    asyncio.get_event_loop().run_until_complete(crear())
    r = c.get(f"/api/retail/ventas/{borrador}/tirilla")
    assert r.status_code == 404
    assert "cerrado" in r.json()["detail"]["mensaje"].lower()


def test_una_venta_anulada_se_imprime_PERO_marcada(cliente):
    """Reimprimir una anulada tiene que poder hacerse —alguien la va a pedir—
    pero el papel no puede parecerse al de una venta viva."""
    c, motor = cliente
    _vender(c)
    import asyncio

    async def anular():
        async with motor.begin() as cn:
            await cn.execute(text("""
                UPDATE retail.ventas
                   SET estado='anulada', motivo_anulacion='cobrada dos veces',
                       anulada_en=now()
                 WHERE id=:i
            """), {"i": VENTA})

    asyncio.get_event_loop().run_until_complete(anular())
    d = _tirilla(c)
    assert d["anulada"] is True
    assert d["total_centavos"] == 33980000   # los números siguen siendo los que fueron


# ── El QR ───────────────────────────────────────────────────────────────────

def _emitir(motor, *, qr_datos=None, cufe="a" * 96):
    """Deja la venta con documento fiscal emitido y resolución en la tienda."""
    import asyncio

    async def hacer():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.tiendas SET resolucion_dian='Res. DIAN 18764' "
                " WHERE id='florida'"))
            await cn.execute(text(
                "UPDATE retail.ventas SET estado_fiscal='emitido' WHERE id=:i"),
                {"i": VENTA})
            await cn.execute(text("""
                INSERT INTO retail.documentos_fiscales
                    (id, venta_id, tipo, proveedor, estado, numero, cufe,
                     qr_datos, payload_snapshot, emitido_en)
                VALUES (:d, :v, 'factura_electronica', 'siigo', 'emitido',
                        'FV-20-1334', :cufe, :qr, '{}'::jsonb, now())
            """), {"d": "01JQ8X4T5N6P900R8S9V0W1X2Y", "v": VENTA,
                   "cufe": cufe, "qr": qr_datos})

    asyncio.get_event_loop().run_until_complete(hacer())


def test_sin_documento_emitido_NO_hay_qr(cliente):
    """Un QR en un papel que todavía no ampara nada lo haría parecer fiscal a
    simple vista — que es justo lo que esta tirilla evita mientras no lo sea.
    Y llevaría a una página de error de la DIAN."""
    c, _ = cliente
    _vender(c)
    d = _tirilla(c)
    assert d["qr_ruta"] is None
    assert d["qr_contenido"] is None
    assert d["qr_modulos"] == 0


def test_con_documento_emitido_el_qr_apunta_al_catalogo_de_la_dian(cliente):
    """El respaldo: mientras Siigo no mande su cadena, se arma la URL estándar
    del catálogo con el CUFE. Es lo que llevan casi todas las facturas
    electrónicas del país."""
    c, motor = cliente
    _vender(c)
    _emitir(motor)
    d = _tirilla(c)
    assert d["qr_contenido"] == (
        "https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey="
        + "a" * 96)
    assert d["qr_modulos"] > 0
    assert d["qr_ruta"].startswith("M")


def test_si_siigo_manda_su_cadena_MANDA_LA_SUYA(cliente):
    """La DIAN define el formato y el proveedor lo construye. Si lo tuviéramos
    escrito a mano y cambiara, el QR seguiría imprimiéndose, seguiría pareciendo
    correcto, y llevaría a ninguna parte. Nadie lo descubre hasta que alguien
    lo escanea."""
    c, motor = cliente
    _vender(c)
    _emitir(motor, qr_datos="NumFac=FV1334&FecFac=2026-08-12&ValFac=339800")
    d = _tirilla(c)
    assert d["qr_contenido"] == "NumFac=FV1334&FecFac=2026-08-12&ValFac=339800"
    assert "catalogo-vpfe" not in d["qr_contenido"]


def test_el_qr_es_una_ruta_svg_no_marcado(cliente):
    """Se manda el atributo `d` de un <path>, no un <svg> armado. Así la
    pantalla no tiene que inyectar HTML crudo para pintarlo."""
    c, motor = cliente
    _vender(c)
    _emitir(motor)
    d = _tirilla(c)
    ruta = d["qr_ruta"]
    assert "<" not in ruta and ">" not in ruta

    # Rachas horizontales, no un rectángulo por módulo. Se compara contra los
    # módulos encendidos de verdad en vez de contra un número inventado: la
    # afirmación es «agrupar comprime», no «pesa menos de tanto».
    import segno
    encendidos = sum(sum(f) for f in segno.make(d["qr_contenido"], error="m").matrix)
    assert ruta.count("M") < encendidos, "no está agrupando: un tramo por módulo"
    assert ruta.count("M") <= encendidos * 0.7


def test_un_documento_emitido_sin_cufe_ni_qr_no_inventa_nada(cliente):
    """Dato incompleto del proveedor. Un QR armado con un CUFE vacío apuntaría
    al catálogo sin documento: peor que no imprimirlo."""
    c, motor = cliente
    _vender(c)
    _emitir(motor, cufe=None)
    d = _tirilla(c)
    assert d["qr_ruta"] is None


def test_el_cufe_en_texto_sigue_estando(cliente):
    """El papel térmico se borra con el calor y el roce del bolsillo. Cuando el
    QR deje de leerse, el CUFE escrito es lo único que queda."""
    c, motor = cliente
    _vender(c)
    _emitir(motor)
    d = _tirilla(c)
    assert d["cufe"] == "a" * 96
    assert d["qr_ruta"] is not None


def test_la_ruta_svg_reproduce_EXACTAMENTE_la_matriz_del_qr(cliente):
    """La prueba que impide un QR bonito e ilegible.

    Convertir la matriz a una ruta SVG puede salir transpuesta, desplazada un
    módulo o con las rachas mal cerradas, y el resultado SIGUE PARECIENDO un
    código QR: cuadrado, con sus tres esquinas, con su ruido. Nadie lo nota
    mirándolo. Se descubre cuando una clienta intenta verificar su factura y no
    pasa nada.

    Así que se deshace: se parsea la ruta de vuelta a una matriz y se compara
    módulo por módulo con la que produjo la librería.
    """
    import re
    import segno

    c, motor = cliente
    _vender(c)
    _emitir(motor)
    d = _tirilla(c)

    esperada = [list(f) for f in segno.make(d["qr_contenido"], error="m").matrix]
    n = len(esperada)
    assert d["qr_modulos"] == n

    reconstruida = [[0] * n for _ in range(n)]
    tramos = re.findall(r"M(\d+) (\d+)h(\d+)v1h-\d+z", d["qr_ruta"])
    assert tramos, "la ruta no tiene el formato esperado"
    for x0, y, ancho in tramos:
        x0, y, ancho = int(x0), int(y), int(ancho)
        for x in range(x0, x0 + ancho):
            reconstruida[y][x] = 1

    for y in range(n):
        assert reconstruida[y] == list(esperada[y]), (
            f"la fila {y} no coincide: el QR se imprimiría ilegible"
        )
