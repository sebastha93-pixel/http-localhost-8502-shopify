"""Cargar un catálogo real desde un CSV.

Hasta ahora la única forma de meter productos era `semilla.py`, que es de
desarrollo: siete prendas inventadas, `TRUNCATE` de media base y negativa a
correr fuera de `localhost`. O sea que el POS se podía desplegar y quedarse
sin nada que vender.

Lo que se prueba aquí es sobre todo lo que el cargador RECHAZA. Un cargador
que acepta cualquier cosa mueve el problema al mostrador, y allá se descubre
vendiendo a $899 lo que vale $89.900.
"""
from __future__ import annotations

import os
import textwrap

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402

from backend.modules.retail.cargar_catalogo import (  # noqa: E402
    ProblemaCatalogo, cargar, leer_csv,
)

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
UBICACION = "tienda:florida"


def _csv(tmp_path, contenido: str) -> str:
    ruta = tmp_path / "catalogo.csv"
    ruta.write_text(textwrap.dedent(contenido).lstrip(), encoding="utf-8")
    return str(ruta)


CABECERA = "referencia,nombre,color,categoria,talla,precio,cantidad\n"


# ── Lo que rechaza ──────────────────────────────────────────────────────────

def test_un_precio_en_centavos_por_error_se_rechaza(tmp_path):
    """LA GUARDA QUE MÁS IMPORTA. `precio` va en pesos; si alguien lo escribe
    en centavos o en miles no revienta nada — se descubre al cerrar la caja,
    cuando la mercancía ya salió."""
    _, problemas = leer_csv(_csv(tmp_path, CABECERA + "92611-1,Jean,Azul,Jeans,10,899,4\n"))
    assert any("EN PESOS" in p for p in problemas)


def test_un_precio_desorbitado_tambien(tmp_path):
    _, problemas = leer_csv(_csv(tmp_path, CABECERA + "92611-1,Jean,Azul,Jeans,10,8990000000,4\n"))
    assert any("tope" in p for p in problemas)


def test_dos_filas_del_mismo_sku_se_rechazan(tmp_path):
    """No se suman: se pisarían. Y la segunda gana en silencio, que es peor
    que un error — el stock queda con la cantidad equivocada."""
    _, problemas = leer_csv(_csv(tmp_path, CABECERA +
                                 "92611-1,Jean,Azul,Jeans,10,89900,4\n"
                                 "92611-1,Jean,Azul,Jeans,10,89900,3\n"))
    assert any("ya venía en la línea" in p for p in problemas)


def test_una_cantidad_negativa_se_rechaza(tmp_path):
    _, problemas = leer_csv(_csv(tmp_path, CABECERA + "92611-1,Jean,Azul,Jeans,10,89900,-1\n"))
    assert any("negativa" in p for p in problemas)


def test_se_devuelven_TODOS_los_problemas_no_el_primero(tmp_path):
    """Fallar en el primero obliga a corregir de uno en uno un archivo de 200
    líneas, y eso acaba en alguien cargando a medias."""
    _, problemas = leer_csv(_csv(tmp_path, CABECERA +
                                 "92611-1,Jean,Azul,Jeans,10,899,4\n"
                                 "93634-1,,Azul,Jeans,8,109900,1\n"
                                 "94120-1,Short,Claro,Shorts,6,59900,-2\n"))
    assert len(problemas) == 3


def test_faltar_una_columna_se_dice_claro(tmp_path):
    with pytest.raises(ProblemaCatalogo, match="faltan columnas"):
        leer_csv(_csv(tmp_path, "referencia,nombre\n92611-1,Jean\n"))


def test_un_archivo_vacio_no_pasa_por_bueno(tmp_path):
    _, problemas = leer_csv(_csv(tmp_path, CABECERA))
    assert problemas


# ── Lo que acepta, y cómo lo convierte ──────────────────────────────────────

def test_el_precio_se_guarda_en_centavos(tmp_path):
    filas, problemas = leer_csv(_csv(tmp_path, CABECERA + "92611-1,Jean,Azul,Jeans,10,89900,4\n"))
    assert not problemas
    assert filas[0]["precio_con_iva"] == 8_990_000
    assert filas[0]["sku"] == "92611-1T10"


def test_admite_el_precio_con_puntos_de_miles(tmp_path):
    """Nadie escribe 89900 en una hoja de cálculo; escribe 89.900."""
    filas, problemas = leer_csv(_csv(tmp_path, CABECERA + "92611-1,Jean,Azul,Jeans,10,89.900,4\n"))
    assert not problemas
    assert filas[0]["precio_con_iva"] == 8_990_000


def test_el_id_es_ESTABLE_entre_corridas():
    """`semilla.py` llama «ULID determinista» a `abs(hash(...))`, y el hash de
    strings de Python va salteado por proceso: cambia en cada arranque. Aquí
    tiene que ser estable de verdad o recargar el mismo CSV duplicaría."""
    from backend.modules.retail.cargar_catalogo import _id_de
    assert _id_de("92611-1T10") == _id_de("92611-1T10")
    assert len(_id_de("92611-1T10")) == 26
    assert not (set(_id_de("92611-1T10")) & set("ILOU"))


# ── Contra la base ──────────────────────────────────────────────────────────

@pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")
def test_el_ensayo_es_el_modo_por_defecto(tmp_path):
    """Esto escribe precios y existencias: la dirección segura del error es no
    hacer nada."""
    from backend.modules.retail.semilla import sembrar
    sembrar(URL)

    ruta = _csv(tmp_path, CABECERA + "99999-1,Prenda Nueva,Rojo,Otros,10,50000,3\n")
    r = cargar(URL, ruta, ubicacion_id=UBICACION)      # sin `aplicar`
    assert r["aplicado"] is False

    motor = create_engine(URL)
    with motor.begin() as c:
        assert c.execute(text(
            "SELECT count(*) FROM retail.variantes WHERE sku='99999-1T10'"
        )).scalar() == 0
    motor.dispose()


@pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")
def test_aplicar_escribe_producto_stock_y_su_asiento(tmp_path):
    from backend.modules.retail.semilla import sembrar
    sembrar(URL)

    ruta = _csv(tmp_path, CABECERA + "99999-1,Prenda Nueva,Rojo,Otros,10,50000,3\n")
    r = cargar(URL, ruta, ubicacion_id=UBICACION, aplicar=True)
    assert r["nuevos"] == 1

    motor = create_engine(URL)
    with motor.begin() as c:
        v = c.execute(text("""
            SELECT v.id, v.precio_con_iva, s.cantidad
              FROM retail.variantes v
              JOIN retail.stock_ubicacion s ON s.variante_id = v.id
             WHERE v.sku = '99999-1T10'
        """)).mappings().one()
        assert v["precio_con_iva"] == 5_000_000
        assert v["cantidad"] == 3

        # El libro mayor tiene que cuadrar con el saldo desde el primer día:
        # escribir el saldo sin su asiento deja los dos desalineados y después
        # no hay forma de explicar una diferencia.
        mov = c.execute(text("""
            SELECT delta, saldo_despues, motivo FROM retail.movimientos_inventario
             WHERE variante_id = :v
        """), {"v": v["id"]}).mappings().one()
        assert (mov["delta"], mov["saldo_despues"]) == (3, 3)
        assert mov["motivo"] == "sincronizacion_inicial"

        # Y el buscador lo encuentra: existir sin ser buscable es, desde el
        # mostrador, idéntico a no existir.
        assert c.execute(text("""
            SELECT count(*) FROM retail.catalogo_busqueda
             WHERE texto_busqueda LIKE '%' || retail.norm('Prenda Nueva') || '%'
        """)).scalar() == 1
    motor.dispose()


@pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")
def test_recargar_el_mismo_csv_no_duplica_ni_mueve_el_stock(tmp_path):
    """Idempotente: se corre diez veces y el resultado es el mismo. Hace falta
    para poder corregir un precio sin miedo la mañana del evento."""
    from backend.modules.retail.semilla import sembrar
    sembrar(URL)

    ruta = _csv(tmp_path, CABECERA + "99999-1,Prenda Nueva,Rojo,Otros,10,50000,3\n")
    cargar(URL, ruta, ubicacion_id=UBICACION, aplicar=True)
    r2 = cargar(URL, ruta, ubicacion_id=UBICACION, aplicar=True)

    assert r2["nuevos"] == 0
    assert r2["ajustes_stock"] == 0          # el saldo ya estaba en 3

    motor = create_engine(URL)
    with motor.begin() as c:
        assert c.execute(text(
            "SELECT count(*) FROM retail.variantes WHERE referencia='99999-1'"
        )).scalar() == 1
    motor.dispose()


@pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")
def test_recargar_con_otro_precio_lo_corrige(tmp_path):
    from backend.modules.retail.semilla import sembrar
    sembrar(URL)

    cargar(URL, _csv(tmp_path, CABECERA + "99999-1,Prenda,Rojo,Otros,10,50000,3\n"),
           ubicacion_id=UBICACION, aplicar=True)
    cargar(URL, _csv(tmp_path, CABECERA + "99999-1,Prenda,Rojo,Otros,10,45000,3\n"),
           ubicacion_id=UBICACION, aplicar=True)

    motor = create_engine(URL)
    with motor.begin() as c:
        # En las DOS tablas: la variante y el índice de búsqueda. Si sólo se
        # corrige una, la rejilla enseña un precio y el cobro usa otro.
        assert c.execute(text(
            "SELECT precio_con_iva FROM retail.variantes WHERE sku='99999-1T10'"
        )).scalar() == 4_500_000
        assert c.execute(text("""
            SELECT b.precio_con_iva FROM retail.catalogo_busqueda b
              JOIN retail.variantes v ON v.id = b.variante_id
             WHERE v.sku = '99999-1T10'
        """)).scalar() == 4_500_000
    motor.dispose()


@pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")
def test_una_ubicacion_que_no_existe_se_dice_antes_de_escribir(tmp_path):
    from backend.modules.retail.semilla import sembrar
    sembrar(URL)
    ruta = _csv(tmp_path, CABECERA + "99999-1,Prenda,Rojo,Otros,10,50000,3\n")
    with pytest.raises(ProblemaCatalogo, match="No existe la ubicación"):
        cargar(URL, ruta, ubicacion_id="tienda:inventada", aplicar=True)


@pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")
def test_un_csv_sin_color_se_carga_igual(tmp_path):
    """EL CATÁLOGO DE SIIGO NO TRAE COLOR: va dentro del nombre de la prenda.

    La columna vacía se guardaba como NULL y `variantes.color` es NOT NULL, así
    que la carga entera reventaba en la PRIMERA fila —con la base de producción
    ya abierta y 681 prendas esperando—. Vacío no es desconocido: es vacío.
    """
    from backend.modules.retail.semilla import sembrar
    sembrar(URL)

    ruta = _csv(tmp_path, CABECERA + "99999-1,JEAN FLARE GRIS HUMO,,Campana,10,149900,2\n")
    r = cargar(URL, ruta, ubicacion_id=UBICACION, aplicar=True)
    assert r["nuevos"] == 1

    motor = create_engine(URL)
    with motor.begin() as c:
        color = c.execute(text(
            "SELECT color FROM retail.variantes WHERE sku='99999-1T10'")).scalar()
    motor.dispose()
    assert color == ""


@pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")
def test_el_codigo_de_la_etiqueta_se_guarda_cuando_no_es_el_sku(tmp_path):
    """EN SIIGO HAY ETIQUETAS QUE NO LLEVAN EL SKU: a `42606-1T10` le falta la
    «T» (`42606-110`) y a toda la referencia `13625-2` le pusieron el código de
    la `13625-1`. Son 11 de 687 en Arrayanes. Sin guardar ese código, la
    pistola escanea esas prendas y no pasa nada — y la cajera las busca a mano
    con la clienta enfrente."""
    from backend.modules.retail.semilla import sembrar
    sembrar(URL)

    ruta = _csv(tmp_path,
                "referencia,nombre,color,categoria,talla,precio,cantidad,codigo_barras\n"
                "42606-1,Jean Flare,Azul,Jeans,10,149900,2,42606-110\n")
    assert cargar(URL, ruta, ubicacion_id=UBICACION, aplicar=True)["nuevos"] == 1

    motor = create_engine(URL)
    with motor.begin() as c:
        barras = c.execute(text(
            "SELECT codigo_barras FROM retail.variantes WHERE sku='42606-1T10'"
        )).scalar()
        # Y entra en el texto de búsqueda: escanear eso tiene que ENCONTRARLO.
        busca = c.execute(text(
            "SELECT texto_busqueda LIKE '%42606-110%' FROM retail.catalogo_busqueda cb "
            " JOIN retail.variantes v ON v.id = cb.variante_id WHERE v.sku='42606-1T10'"
        )).scalar()
    motor.dispose()
    assert barras == "42606-110"
    assert busca is True


@pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")
def test_recargar_sin_esa_columna_no_borra_el_codigo(tmp_path):
    """El CSV de un día sin la columna no puede dejar mudas las etiquetas que
    ya se habían corregido."""
    from backend.modules.retail.semilla import sembrar
    sembrar(URL)

    cargar(URL, _csv(tmp_path,
                     "referencia,nombre,color,categoria,talla,precio,cantidad,codigo_barras\n"
                     "42606-1,Jean Flare,Azul,Jeans,10,149900,2,42606-110\n"),
           ubicacion_id=UBICACION, aplicar=True)
    cargar(URL, _csv(tmp_path, CABECERA + "42606-1,Jean Flare,Azul,Jeans,10,149900,3\n"),
           ubicacion_id=UBICACION, aplicar=True)

    motor = create_engine(URL)
    with motor.begin() as c:
        barras = c.execute(text(
            "SELECT codigo_barras FROM retail.variantes WHERE sku='42606-1T10'")).scalar()
    motor.dispose()
    assert barras == "42606-110"
