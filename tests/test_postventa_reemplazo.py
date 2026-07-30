"""Elegir la prenda del reemplazo contra las existencias REALES del punto.

Sin esto se puede facturar un jean que esa tienda no tiene: queda un
documento fiscal emitido y una clienta esperando algo que no existe.

La disponibilidad se mide en la bodega de ESE punto, no en el total de la
marca: que haya 4 en Arrayanes no sirve si la clienta esta en Florida.
"""
from backend.services import postventa_reemplazo as R


INVENTARIO = {"bodegas": ["Arrayanes", "Florida"], "referencias": [
    {"code": "95527-1T10", "referencia": "95527-1", "talla": "10",
     "nombre": "JEAN WIDE LEG CLARO", "stock": {"Florida": 9}, "total": 9},
    {"code": "95527-1T12", "referencia": "95527-1", "talla": "12",
     "nombre": "JEAN WIDE LEG CLARO", "stock": {"Arrayanes": 1, "Florida": 3},
     "total": 4},
    {"code": "95527-1T4", "referencia": "95527-1", "talla": "4",
     "nombre": "JEAN WIDE LEG CLARO", "stock": {"Arrayanes": 2}, "total": 2},
    {"code": "22624-1T8", "referencia": "22624-1", "talla": "8",
     "nombre": "JEAN SKINNY OSCURO", "stock": {"Florida": 2}, "total": 2},
]}


def test_solo_muestra_lo_que_hay_en_la_bodega_de_ese_punto():
    """La talla 4 solo esta en Arrayanes: en Florida no se puede entregar."""
    codes = [o["code"] for o in R.opciones_con_stock(INVENTARIO, "Florida")]
    assert "95527-1T4" not in codes
    assert set(codes) == {"95527-1T10", "95527-1T12", "22624-1T8"}


def test_el_stock_es_el_de_esa_bodega_no_el_total():
    o = {x["code"]: x for x in R.opciones_con_stock(INVENTARIO, "Florida")}
    assert o["95527-1T12"]["stock"] == 3      # total es 4, pero 1 esta en Arrayanes


def test_arrayanes_ve_lo_suyo():
    codes = [o["code"] for o in R.opciones_con_stock(INVENTARIO, "Arrayanes")]
    assert set(codes) == {"95527-1T12", "95527-1T4"}


def test_busca_por_referencia_nombre_o_talla():
    def codes(q):
        return {o["code"] for o in R.opciones_con_stock(INVENTARIO, "Florida", q=q)}
    assert codes("95527") == {"95527-1T10", "95527-1T12"}
    assert codes("skinny") == {"22624-1T8"}
    assert codes("SKINNY") == {"22624-1T8"}      # sin importar mayusculas
    assert codes("") == {"95527-1T10", "95527-1T12", "22624-1T8"}


def test_ordena_por_referencia_y_talla_numerica():
    """Las tallas se leen como numero: 4, 8, 10, 12 — no '10' antes que '4'."""
    ops = R.opciones_con_stock(INVENTARIO, "Florida", q="95527")
    assert [o["talla"] for o in ops] == ["10", "12"]


def test_bodega_desconocida_no_devuelve_nada():
    assert R.opciones_con_stock(INVENTARIO, "Bodega Fantasma") == []


def test_inventario_vacio_no_revienta():
    assert R.opciones_con_stock({}, "Florida") == []


# ── Se puede entregar esta prenda? ─────────────────────────────────────────

def test_hay_existencia_para_el_cambio():
    ok, det = R.verificar_disponible(INVENTARIO, "Florida", "95527-1T12")
    assert ok
    assert "3" in det


def test_no_se_puede_facturar_lo_que_no_esta_en_ese_punto():
    ok, det = R.verificar_disponible(INVENTARIO, "Florida", "95527-1T4")
    assert not ok
    assert "Florida" in det


def test_referencia_inexistente_se_rechaza():
    ok, det = R.verificar_disponible(INVENTARIO, "Florida", "NO-EXISTE")
    assert not ok


def test_sin_inventario_no_afirma_que_haya():
    """Si no se pudo leer Siigo, no se da por bueno: se bloquea y se dice."""
    ok, det = R.verificar_disponible({}, "Florida", "95527-1T10")
    assert not ok
    assert "no se pudo" in det.lower()


# ── Saldo a favor: la clienta no se lleva nada hoy ─────────────────────────
# La nota credito ya dejo el ANTICIPO en Siigo. Si la clienta no elige prenda,
# ese credito queda a su nombre y NO se emite factura de reemplazo. El caso se
# cierra dejando escrito cuanto quedo a favor, que es lo que se le va a
# reclamar despues.

def test_el_saldo_a_favor_no_emite_factura():
    assert R.decide_factura("reemplazo") is True
    assert R.decide_factura("saldo_a_favor") is False


def test_solo_hay_dos_salidas():
    assert R.SALIDAS == ("reemplazo", "saldo_a_favor")


def test_una_salida_inventada_se_rechaza():
    import pytest
    with pytest.raises(ValueError):
        R.decide_factura("regalo")


def test_el_mensaje_del_saldo_dice_el_monto():
    assert "149.900" in R.texto_saldo_a_favor(149900)


# ── El limite de la lista NO puede decidir si algo existe ──────────────────

def _inventario_grande():
    """Mas referencias que el limite de la lista. La buscada queda al final
    del orden a proposito: es exactamente donde el corte la escondia."""
    filas = [{"code": f"1{i:04d}-1T8", "referencia": f"1{i:04d}-1", "talla": "8",
              "nombre": "RELLENO", "stock": {"Florida": 1}, "total": 1}
             for i in range(80)]
    filas.append({"code": "99999-1T10", "referencia": "99999-1", "talla": "10",
                  "nombre": "JEAN FLARE", "stock": {"Florida": 8}, "total": 8})
    return {"referencias": filas}


def test_verifica_contra_TODO_el_inventario_no_solo_la_pagina_mostrada():
    """La lista corta en 60 para no reventar la pantalla. Si la verificacion
    usa esa misma lista, una prenda que SI existe se rechaza por estar fuera
    del corte — que es justo lo que paso con 21603-1T10 (8 en Florida)."""
    inv = _inventario_grande()
    ok, det = R.verificar_disponible(inv, "Florida", "99999-1T10")
    assert ok, det
    assert "8" in det


def test_la_lista_si_puede_truncar():
    """Mostrar 60 esta bien: es una pantalla, no una decision."""
    assert len(R.opciones_con_stock(_inventario_grande(), "Florida")) == 60
