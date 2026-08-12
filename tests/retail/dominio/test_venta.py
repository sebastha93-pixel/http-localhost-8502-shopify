"""Venta — el agregado donde viven las reglas que protegen la plata.

Cada una de estas pruebas corresponde a una invariante del diseño
(docs/retail-pos/02-DOMINIO-DDD.md §3). No están aquí para subir la cobertura:
están porque cada una evita una forma concreta de perder dinero o de emitir un
documento que no dice lo que se cobró.

Todo corre sin base de datos, sin red y sin FastAPI.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.modules.retail.domain.shared.dinero import Dinero, MonedaDistinta
from backend.modules.retail.domain.shared.sku import Sku
from backend.modules.retail.domain.venta.descuento import Descuento
from backend.modules.retail.domain.venta.errores import (
    RequiereAutorizacion,
    ReglaDeNegocio,
    VentaNoModificable,
)
from backend.modules.retail.domain.venta.estados import EstadoVenta
from backend.modules.retail.domain.venta.eventos import VentaAnulada, VentaCerrada
from backend.modules.retail.domain.venta.venta import Venta

COP = "COP"
AHORA = datetime(2026, 8, 5, 19, 42, tzinfo=timezone.utc)
ULID = "01JQ8X4T5N6P7R8S9V0W1X2Y3Z"

# Tope de descuento de cada rol, como lo trae la fila del usuario.
TOPE_CAJERA = Decimal("10")
TOPE_SUPERVISOR = Decimal("35")


def pesos(v: str) -> Dinero:
    return Dinero.desde_pesos(v, COP)


def nueva_venta(**kw) -> Venta:
    base = dict(
        id=ULID,
        numero="FV-11-1334",
        tienda_id="florida",
        caja_id="florida_caja1",
        sesion_id="01JQ8X4T5N6P7R8S9V0W1X2Y40",
        cajera_id="maria",
        moneda=COP,
    )
    base.update(kw)
    return Venta.abrir(**base)


def con_una_linea(venta: Venta, precio="169900", cantidad=1, iva="19"):
    """Una prenda de $169.900 — el precio de la etiqueta, CON IVA.

    Ya no hace falta escribir 142.773,11 y confiar en que al multiplicar
    regrese: el precio ES el de vitrina y el impuesto se lee de él.
    """
    return venta.agregar_linea(
        sku=Sku.parsear("92611-1T10"),
        descripcion="Jean Skinny Azul · 10",
        cantidad=cantidad,
        precio_unitario=pesos(precio),
        tasa_iva=Decimal(iva),
    )


# ── Construcción y estado inicial ───────────────────────────────────────────

def test_una_venta_nace_en_borrador_y_vacia():
    v = nueva_venta()
    assert v.estado is EstadoVenta.BORRADOR
    assert v.lineas == []
    assert v.total() == Dinero.cero(COP)
    assert v.cliente_id is None  # consumidor final, no un cliente inventado


def test_el_id_debe_ser_un_ulid_valido():
    """El id lo genera el DISPOSITIVO y es la llave de idempotencia (ADR-005).

    Si se acepta cualquier cosa, dos ventas offline distintas pueden colisionar
    —o la misma venta reintentada entrar dos veces.
    """
    for malo in ["", "abc", "01JQ8X4T5N6P7R8S9V0W1X2Y3", "01JQ8X4T5N6P7R8S9V0W1X2Y3!"]:
        with pytest.raises(ReglaDeNegocio):
            nueva_venta(id=malo)


def test_el_id_acepta_minusculas_y_las_normaliza():
    assert nueva_venta(id=ULID.lower()).id == ULID


# ── Líneas · INV-V9 ─────────────────────────────────────────────────────────

def test_agregar_una_linea():
    v = nueva_venta()
    linea = con_una_linea(v)
    assert len(v.lineas) == 1
    assert linea.numero == 1
    assert linea.cantidad == 1


def test_las_lineas_se_numeran_y_el_numero_no_se_reutiliza():
    """Eliminar la línea 2 no renumera la 3.

    Si se renumerara, un comando en vuelo que apunta a la línea 3 terminaría
    modificando otra prenda.
    """
    v = nueva_venta()
    con_una_linea(v)
    con_una_linea(v)
    con_una_linea(v)
    v.eliminar_linea(2)
    assert [l.numero for l in v.lineas] == [1, 3]
    con_una_linea(v)
    assert [l.numero for l in v.lineas] == [1, 3, 4]


def test_cantidad_debe_ser_positiva():
    v = nueva_venta()
    for mala in [0, -1]:
        with pytest.raises(ReglaDeNegocio):
            con_una_linea(v, cantidad=mala)


def test_modificar_cantidad_a_cero_elimina_la_linea():
    """INV-V9: una línea en cero no es una línea, es ruido en la factura."""
    v = nueva_venta()
    con_una_linea(v)
    v.modificar_cantidad(1, 0)
    assert v.lineas == []


def test_no_se_puede_tocar_una_linea_que_no_existe():
    v = nueva_venta()
    with pytest.raises(ReglaDeNegocio):
        v.modificar_cantidad(99, 2)


def test_precio_cero_solo_si_es_obsequio_autorizado():
    """INV-V7. Un precio en cero es la forma clásica de sacar mercancía."""
    v = nueva_venta()
    with pytest.raises(ReglaDeNegocio):
        con_una_linea(v, precio="0")


def test_marcar_obsequio_exige_autorizacion():
    v = nueva_venta()
    con_una_linea(v)
    with pytest.raises(RequiereAutorizacion):
        v.marcar_obsequio(1, autorizado_por=None)

    v.marcar_obsequio(1, autorizado_por="laura")
    assert v.lineas[0].obsequio is True
    assert v.lineas[0].autorizado_por == "laura"
    assert v.total() == Dinero.cero(COP)


# ── Cálculo · INV-V12: el IVA se calcula POR LÍNEA ─────────────────────────

def test_el_total_es_el_precio_de_la_etiqueta_y_el_iva_se_lee_de_ahi():
    """El total NO se calcula: es el precio de vitrina, exacto por definición.

    Base e IVA son una lectura de ese número, y siempre suman de vuelta. Con
    el modelo anterior —guardando la base— había precios que no regresaban y
    la pantalla mostraba centavos que no existen.
    """
    v = nueva_venta()
    con_una_linea(v)
    assert v.total() == pesos("169900")
    assert v.total().formateado() == "$169.900"
    assert v.base_gravable() == pesos("142773.11")
    assert v.iva_total() == pesos("27126.89")
    # Lo que hace que el modelo cierre: siempre suman el total.
    assert v.base_gravable() + v.iva_total() == v.total()


def test_ningun_precio_produce_centavos_fantasma():
    """El caso que destapó el error: $139.900 en la etiqueta.

    Con el modelo anterior salía $139.900,01 porque ninguna base daba ese
    total. Ahora el total ES la etiqueta, así que no hay nada que redondear.
    """
    for etiqueta in ["139900", "169900", "189900", "109900", "79900", "249900"]:
        v = nueva_venta()
        con_una_linea(v, precio=etiqueta)
        assert v.total() == pesos(etiqueta)
        assert v.total().centavos % 100 == 0, f"{etiqueta} dejó centavos"
        assert v.base_gravable() + v.iva_total() == v.total()


def test_el_iva_se_calcula_por_linea_y_no_sobre_el_total():
    """INV-V12. Con tarifas distintas, calcular sobre el total da otro número."""
    v = nueva_venta()
    con_una_linea(v, precio="100000", iva="19")
    con_una_linea(v, precio="100000", iva="0")   # exenta
    assert v.total() == pesos("200000")
    # La gravada aporta IVA; la exenta no. Si se derivara del total de la
    # venta, la exenta también pagaría.
    assert v.iva_total() == pesos("15966.39")
    assert v.base_gravable() + v.iva_total() == v.total()


def test_multiplica_por_cantidad():
    v = nueva_venta()
    con_una_linea(v, cantidad=3)
    assert v.total() == pesos("509700")   # 3 × $169.900, exacto


def test_no_se_pueden_mezclar_monedas():
    """INV-V5. Sumar dólares con pesos produce un número. Ese es el problema."""
    v = nueva_venta()
    with pytest.raises(MonedaDistinta):
        v.agregar_linea(
            sku=Sku.parsear("92611-1T10"), descripcion="x", cantidad=1,
            precio_unitario=Dinero.desde_pesos("100", "USD"), tasa_iva=Decimal("19"),
        )


# ── Descuentos · INV-V6 ─────────────────────────────────────────────────────

def test_descuento_dentro_del_tope_se_aplica_sin_autorizacion():
    v = nueva_venta()
    con_una_linea(v, precio="100000")
    v.aplicar_descuento_linea(
        1, Descuento.porcentaje(10, motivo="prenda con defecto menor"),
        tope_de_quien_aplica=TOPE_CAJERA,
    )
    assert v.descuento_total() == pesos("10000")
    assert v.total() == pesos("90000")


def test_el_tope_de_quien_aplica_es_el_limite():
    """El control anti-fraude más rentable de un POS.

    Ya no admite firma de un tercero: el PIN se quitó porque el negocio
    decidió que sólo haya una credencial. Por encima del tope el descuento no
    entra, y la vía es que lo haga alguien con más tope desde su propia sesión.
    """
    v = nueva_venta()
    con_una_linea(v, precio="100000")
    d = Descuento.porcentaje(30, motivo="clienta insistió")

    with pytest.raises(RequiereAutorizacion) as e:
        v.aplicar_descuento_linea(1, d, tope_de_quien_aplica=TOPE_CAJERA)
    assert "30" in str(e.value) and "10" in str(e.value)
    assert v.descuento_total() == Dinero.cero(COP)  # no quedó a medias

    # Con el tope del supervisor —o sea, cuando lo aplica el supervisor— pasa.
    v.aplicar_descuento_linea(1, d, tope_de_quien_aplica=TOPE_SUPERVISOR,
                              aplicado_por="laura")
    assert v.lineas[0].autorizado_por == "laura"
    assert v.descuento_total() == pesos("30000")


def test_ya_no_hay_forma_de_firmar_por_encima_del_tope():
    """La puerta que cerró quitar el PIN.

    Mientras `autorizado_por` desbloqueaba el descuento, bastaba con que ese
    nombre llegara desde fuera —y llegaba en el cuerpo de la petición—. Ahora
    quien aplica sólo puede hasta lo suyo, y el nombre es rastro, no llave.
    """
    v = nueva_venta()
    con_una_linea(v, precio="100000")
    with pytest.raises(RequiereAutorizacion):
        v.aplicar_descuento_linea(
            1, Descuento.porcentaje(30, motivo="clienta insistió"),
            tope_de_quien_aplica=TOPE_CAJERA, aplicado_por="laura")
    assert v.descuento_total() == Dinero.cero(COP)


def test_nadie_tiene_tope_infinito():
    """Ni el supervisor. Un 50 % no lo aplica nadie con tope de 35 %."""
    v = nueva_venta()
    con_una_linea(v, precio="100000")
    with pytest.raises(RequiereAutorizacion):
        v.aplicar_descuento_linea(
            1, Descuento.porcentaje(50, motivo="fuera de todo tope"),
            tope_de_quien_aplica=TOPE_SUPERVISOR, aplicado_por="laura")
    assert v.descuento_total() == Dinero.cero(COP)  # no quedó aplicado a medias


def test_un_descuento_en_valor_se_evalua_como_porcentaje_efectivo():
    """$30.000 sobre $100.000 es un 30%: pasa el mismo control.

    Sin esto, el tope se esquiva escribiendo el descuento en pesos.
    """
    v = nueva_venta()
    con_una_linea(v, precio="100000")
    with pytest.raises(RequiereAutorizacion):
        v.aplicar_descuento_linea(
            1, Descuento.valor(pesos("30000"), motivo="rodeo del tope"),
            tope_de_quien_aplica=TOPE_CAJERA,
        )


def test_el_descuento_baja_el_total_y_por_lo_tanto_el_iva():
    v = nueva_venta()
    con_una_linea(v, precio="100000")
    v.aplicar_descuento_linea(
        1, Descuento.porcentaje(10, motivo="defecto menor"),
        tope_de_quien_aplica=TOPE_CAJERA)
    assert v.total() == pesos("90000")
    assert v.base_gravable() == pesos("75630.25")
    assert v.iva_total() == pesos("14369.75")
    assert v.base_gravable() + v.iva_total() == v.total()


# ── Pagos · INV-V3 ──────────────────────────────────────────────────────────

def test_saldo_y_vuelto():
    v = nueva_venta()
    con_una_linea(v)  # $169.900
    assert v.saldo() == pesos("169900")

    v.registrar_pago("efectivo", pesos("200000"), es_efectivo=True)
    assert v.saldo() == Dinero.cero(COP)
    assert v.vuelto() == pesos("30100")


def test_pago_mixto():
    v = nueva_venta()
    con_una_linea(v)
    v.registrar_pago("datafono_florida", pesos("100000"), es_efectivo=False)
    assert v.saldo() == pesos("69900")
    v.registrar_pago("efectivo", pesos("69900"), es_efectivo=True)
    assert v.saldo() == Dinero.cero(COP)
    assert v.vuelto() == Dinero.cero(COP)


def test_no_se_cierra_con_menos_plata_de_la_debida():
    """INV-V3. Cerrar con un faltante es un faltante garantizado en el arqueo."""
    v = nueva_venta()
    con_una_linea(v)
    v.registrar_pago("efectivo", pesos("100000"), es_efectivo=True)
    with pytest.raises(ReglaDeNegocio, match="falta"):
        v.cerrar(AHORA)


def test_el_excedente_solo_puede_venir_de_efectivo():
    """Un datáfono no da vuelto: si se cobró de más, se cobró de más.

    Aceptarlo en silencio esconde un error de digitación que después aparece
    como sobrante en el arqueo, sin saber de qué venta salió.
    """
    v = nueva_venta()
    con_una_linea(v)
    v.registrar_pago("datafono_florida", pesos("200000"), es_efectivo=False)
    with pytest.raises(ReglaDeNegocio, match="vuelto"):
        v.cerrar(AHORA)


def test_no_se_registra_un_pago_de_cero_o_negativo():
    v = nueva_venta()
    con_una_linea(v)
    for malo in ["0", "-1000"]:
        with pytest.raises(ReglaDeNegocio):
            v.registrar_pago("efectivo", pesos(malo), es_efectivo=True)


def test_eliminar_un_pago():
    v = nueva_venta()
    con_una_linea(v)
    p = v.registrar_pago("efectivo", pesos("169900"), es_efectivo=True)
    v.eliminar_pago(p.numero)
    assert v.pagado() == Dinero.cero(COP)


# ── Cierre · INV-V1, V2 ─────────────────────────────────────────────────────

def test_no_se_cierra_una_venta_vacia():
    v = nueva_venta()
    with pytest.raises(ReglaDeNegocio, match="sin prendas"):
        v.cerrar(AHORA)


def test_cerrar_congela_los_totales_y_emite_el_evento():
    v = nueva_venta()
    con_una_linea(v)
    v.registrar_pago("efectivo", pesos("200000"), es_efectivo=True)

    evento = v.cerrar(AHORA)

    assert isinstance(evento, VentaCerrada)
    assert v.estado is EstadoVenta.CERRADA
    assert v.cerrada_en == AHORA
    assert evento.total == pesos("169900")
    assert evento.vuelto == pesos("30100")
    assert evento.venta_id == ULID
    assert evento.tienda_id == "florida"


def test_una_venta_cerrada_es_inmutable():
    """INV-V1. Se emitió un documento fiscal sobre ese contenido.

    Corregir una venta cerrada es un documento nuevo, no una edición.
    """
    v = nueva_venta()
    con_una_linea(v)
    v.registrar_pago("efectivo", pesos("169900"), es_efectivo=True)
    v.cerrar(AHORA)

    with pytest.raises(VentaNoModificable):
        con_una_linea(v)
    with pytest.raises(VentaNoModificable):
        v.modificar_cantidad(1, 5)
    with pytest.raises(VentaNoModificable):
        v.eliminar_linea(1)
    with pytest.raises(VentaNoModificable):
        v.registrar_pago("efectivo", pesos("1000"), es_efectivo=True)
    with pytest.raises(VentaNoModificable):
        v.asignar_cliente("alguien")
    with pytest.raises(VentaNoModificable):
        v.aplicar_descuento_linea(
            1, Descuento.porcentaje(5, motivo="tarde para esto"),
            tope_de_quien_aplica=TOPE_CAJERA)


def test_no_se_cierra_dos_veces():
    v = nueva_venta()
    con_una_linea(v)
    v.registrar_pago("efectivo", pesos("169900"), es_efectivo=True)
    v.cerrar(AHORA)
    with pytest.raises(VentaNoModificable):
        v.cerrar(AHORA)


# ── Anulación · INV-V11 ─────────────────────────────────────────────────────

def test_anular_exige_motivo_y_autorizacion():
    v = nueva_venta()
    con_una_linea(v)
    v.registrar_pago("efectivo", pesos("169900"), es_efectivo=True)
    v.cerrar(AHORA)

    with pytest.raises(ReglaDeNegocio):
        v.anular(motivo="", autorizado_por="laura", ahora=AHORA)
    with pytest.raises(RequiereAutorizacion):
        v.anular(motivo="la clienta cambió de opinión", autorizado_por=None,
                 ahora=AHORA)

    evento = v.anular(motivo="la clienta cambió de opinión",
                      autorizado_por="laura", ahora=AHORA)
    assert isinstance(evento, VentaAnulada)
    assert v.estado is EstadoVenta.ANULADA


def test_no_se_anula_algo_que_nunca_se_cerro():
    """Un borrador se descarta; no se anula. Anular deja rastro contable."""
    v = nueva_venta()
    con_una_linea(v)
    with pytest.raises(ReglaDeNegocio):
        v.anular(motivo="me equivoqué", autorizado_por="laura", ahora=AHORA)


# ── Cliente ─────────────────────────────────────────────────────────────────

def test_asignar_y_quitar_cliente():
    v = nueva_venta()
    v.asignar_cliente("01JQ8X4T5N6P7R8S9V0W1X2Y41")
    assert v.cliente_id == "01JQ8X4T5N6P7R8S9V0W1X2Y41"
    v.asignar_cliente(None)  # vuelve a consumidor final
    assert v.cliente_id is None
