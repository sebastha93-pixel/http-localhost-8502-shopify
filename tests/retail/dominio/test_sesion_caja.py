"""SesionCaja — el turno, y lo que hace que el arqueo mida algo.

La regla que gobierna este archivo es el **cierre ciego**: la cajera no ve
cuánto debería haber hasta que declara lo que contó. Si lo ve, escribe lo que
ve, y el descuadre desaparece de los informes sin desaparecer de la realidad.

La otra regla que importa es INV-C8: una venta offline que llega DESPUÉS de
que su turno cerró. Es el caso que rompe todos los POS mal diseñados —
rechazarla sería perder una venta real, y aceptarla en silencio descuadraría
un cierre ya firmado. Se acepta, se marca y se reporta.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.modules.retail.domain.caja.errores import (
    ArqueoCiego,
    SesionYaCerrada,
)
from backend.modules.retail.domain.caja.estados import EstadoSesion
from backend.modules.retail.domain.caja.sesion_caja import SesionCaja
from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.venta.errores import (
    ReglaDeNegocio,
    RequiereAutorizacion,
)

COP = "COP"
ABIERTA = datetime(2026, 8, 5, 9, 2, tzinfo=timezone.utc)
CERRADA = datetime(2026, 8, 5, 20, 15, tzinfo=timezone.utc)
ULID = "01JQ8X4T5N6P7R8S9V0W1X2Y3Z"

EFECTIVO = "efectivo"
DATAFONO = "datafono_florida"


def pesos(v: str) -> Dinero:
    return Dinero.desde_pesos(v, COP)


def nueva_sesion(**kw) -> SesionCaja:
    base = dict(
        id=ULID,
        tienda_id="florida",
        caja_id="florida_caja1",
        numero_turno=1284,
        base_inicial=pesos("200000"),
        abierta_por="maria",
        abierta_en=ABIERTA,
        moneda=COP,
        cierre_ciego=True,
        umbral_descuadre=pesos("5000"),
    )
    base.update(kw)
    return SesionCaja.abrir(**base)


def vender(s: SesionCaja, medio=EFECTIVO, monto="169900", efectivo=True):
    s.registrar_cobro(medio_pago_id=medio, monto=pesos(monto),
                      es_efectivo=efectivo, venta_id=ULID)


# ── Apertura ────────────────────────────────────────────────────────────────

def test_una_sesion_nace_abierta_con_su_base():
    s = nueva_sesion()
    assert s.estado is EstadoSesion.ABIERTA
    assert s.base_inicial == pesos("200000")


def test_la_base_no_puede_ser_negativa():
    with pytest.raises(ReglaDeNegocio):
        nueva_sesion(base_inicial=pesos("-1000"))


def test_una_base_en_cero_es_valida():
    """Una caja que arranca sin sencillo es raro, pero no es un error."""
    assert nueva_sesion(base_inicial=pesos("0")).base_inicial.es_cero()


# ── Cobros y movimientos ────────────────────────────────────────────────────

def test_el_esperado_en_efectivo_suma_base_y_cobros():
    s = nueva_sesion()
    vender(s, EFECTIVO, "169900")
    vender(s, EFECTIVO, "89900")
    assert s.esperado_de(EFECTIVO, autorizado_a_ver=True) == pesos("459800")


def test_los_medios_que_no_son_efectivo_van_por_separado():
    s = nueva_sesion()
    vender(s, DATAFONO, "500000", efectivo=False)
    assert s.esperado_de(DATAFONO, autorizado_a_ver=True) == pesos("500000")
    # La base es efectivo: no infla el datáfono.
    assert s.esperado_de(EFECTIVO, autorizado_a_ver=True) == pesos("200000")


def test_un_medio_sin_movimientos_no_hereda_la_base():
    """La base es efectivo. No puede aparecer en el esperado del datáfono.

    Si el turno no sabe cuál medio ES el efectivo y lo adivina mirando los
    cobros, un medio sin movimientos todavía se lleva la base entera — y el
    arqueo del datáfono arranca con $200.000 que nunca pasaron por ahí.
    """
    s = nueva_sesion()
    vender(s, EFECTIVO, "100000")
    assert s.esperado_de(DATAFONO, autorizado_a_ver=True) == Dinero.cero(COP)
    assert s.esperado_de(EFECTIVO, autorizado_a_ver=True) == pesos("300000")


def test_retiro_e_ingreso_mueven_el_efectivo():
    s = nueva_sesion()
    vender(s, EFECTIVO, "800000")
    s.registrar_retiro(pesos("500000"), motivo="sangría a caja fuerte",
                       usuario_id="laura", puede_mover_caja=True)
    s.registrar_ingreso(pesos("50000"), motivo="cambio de sencillo",
                        usuario_id="maria")
    assert s.esperado_de(EFECTIVO, autorizado_a_ver=True) == pesos("550000")


def test_un_gasto_de_caja_menor_baja_el_efectivo():
    s = nueva_sesion()
    s.registrar_gasto(pesos("35000"), motivo="domicilio almuerzo",
                      usuario_id="laura", puede_mover_caja=True)
    assert s.esperado_de(EFECTIVO, autorizado_a_ver=True) == pesos("165000")


def test_no_se_puede_sacar_plata_que_no_hay():
    """INV-C6. Un retiro que deja el efectivo en negativo es un error de dedo."""
    s = nueva_sesion()
    with pytest.raises(ReglaDeNegocio, match="no hay"):
        s.registrar_retiro(pesos("300000"), motivo="sangría",
                           usuario_id="laura", puede_mover_caja=True)


def test_retiro_y_gasto_exigen_motivo_y_permiso():
    """El motivo escrito y el permiso son las dos mitades del control: sin
    motivo no se puede revisar después, y sin permiso lo hace cualquiera.

    La firma por PIN de un tercero se quitó con el resto del PIN; ahora el
    permiso lo trae quien tiene la sesión abierta y quien saca la plata es
    quien firma.
    """
    s = nueva_sesion()
    with pytest.raises(ReglaDeNegocio):
        s.registrar_retiro(pesos("1000"), motivo="", usuario_id="laura",
                           puede_mover_caja=True)
    with pytest.raises(RequiereAutorizacion):
        s.registrar_retiro(pesos("1000"), motivo="sangría",
                           usuario_id="maria", puede_mover_caja=False)


def test_quien_saca_la_plata_es_quien_firma():
    """Ya no hay dos nombres. El del movimiento tiene que ser el de verdad."""
    s = nueva_sesion()
    s.registrar_retiro(pesos("50000"), motivo="sangría", usuario_id="laura",
                       puede_mover_caja=True)
    ultimo = s.movimientos[-1]
    assert ultimo.usuario_id == "laura"
    assert ultimo.autorizado_por == "laura"


def test_un_ingreso_no_lleva_firma():
    """`autorizado_por` sólo tiene sentido donde hubo algo que autorizar.
    Llenarlo siempre haría que un informe de movimientos autorizados los
    listara todos."""
    s = nueva_sesion()
    s.registrar_ingreso(pesos("50000"), motivo="sencillo", usuario_id="maria")
    assert s.movimientos[-1].autorizado_por is None


def test_anular_una_venta_devuelve_la_plata_al_esperado():
    s = nueva_sesion()
    vender(s, EFECTIVO, "169900")
    s.registrar_anulacion(medio_pago_id=EFECTIVO, monto=pesos("169900"),
                          es_efectivo=True, venta_id=ULID)
    assert s.esperado_de(EFECTIVO, autorizado_a_ver=True) == pesos("200000")


# ── Cierre ciego · INV-C4 ───────────────────────────────────────────────────

def test_en_cierre_ciego_no_se_puede_ver_el_esperado():
    """Si la cajera ve el esperado, escribe el esperado.

    Es toda la razón de que el arqueo exista.
    """
    s = nueva_sesion()
    vender(s, EFECTIVO, "169900")
    with pytest.raises(ArqueoCiego):
        s.esperado_de(EFECTIVO)


def test_un_supervisor_si_puede_verlo():
    s = nueva_sesion()
    vender(s, EFECTIVO, "169900")
    assert s.esperado_de(EFECTIVO, autorizado_a_ver=True) == pesos("369900")


def test_sin_cierre_ciego_lo_ve_cualquiera():
    """Configurable por tienda: hay operaciones donde estorba."""
    s = nueva_sesion(cierre_ciego=False)
    vender(s, EFECTIVO, "169900")
    assert s.esperado_de(EFECTIVO) == pesos("369900")


def test_despues_de_declarar_el_conteo_ya_se_puede_ver():
    s = nueva_sesion()
    vender(s, EFECTIVO, "169900")
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("369900"), usuario_id="maria")
    assert s.esperado_de(EFECTIVO) == pesos("369900")


# ── Arqueo · INV-C2, C3 ─────────────────────────────────────────────────────

def test_no_se_arquea_con_ventas_en_borrador():
    """INV-C2. Un carrito abierto es plata sin registrar."""
    s = nueva_sesion()
    with pytest.raises(ReglaDeNegocio, match="borrador"):
        s.iniciar_arqueo(ventas_en_borrador=2)


def test_los_documentos_fiscales_pendientes_avisan_pero_no_bloquean():
    """INV-C3. La cajera debe SABER que hay documentos en cola.

    Bloquear el cierre por algo que depende de Siigo dejaría a la tienda sin
    poder cerrar por una caída ajena.
    """
    s = nueva_sesion()
    with pytest.raises(ReglaDeNegocio, match="por emitir"):
        s.iniciar_arqueo(ventas_en_borrador=0, documentos_fiscales_pendientes=1)

    s.iniciar_arqueo(ventas_en_borrador=0, documentos_fiscales_pendientes=1,
                     confirmado=True)
    assert s.estado is EstadoSesion.EN_ARQUEO


def test_el_conteo_declarado_congela_el_esperado():
    """Una venta offline que entre después no puede cambiar un cierre firmado.

    Si el esperado se recalculara al leer, la diferencia que la cajera firmó
    dejaría de ser reproducible.
    """
    s = nueva_sesion()
    vender(s, EFECTIVO, "169900")
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("369900"), usuario_id="maria")

    congelado = s.esperado_de(EFECTIVO)
    vender(s, EFECTIVO, "50000")  # llega tarde
    assert s.esperado_de(EFECTIVO) == congelado


def test_no_se_declara_conteo_antes_de_iniciar_el_arqueo():
    s = nueva_sesion()
    with pytest.raises(ReglaDeNegocio):
        s.declarar_conteo(EFECTIVO, pesos("100"), usuario_id="maria")


# ── Diferencias · INV-C5 ────────────────────────────────────────────────────

def test_cierre_que_cuadra():
    s = nueva_sesion()
    vender(s, EFECTIVO, "169900")
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("369900"), usuario_id="maria")

    evento = s.cerrar(usuario_id="maria", ahora=CERRADA)
    assert s.estado is EstadoSesion.CERRADA
    assert s.diferencia_total() == Dinero.cero(COP)
    assert evento.cuadro is True


def test_una_diferencia_pequena_no_necesita_supervisor():
    s = nueva_sesion()
    vender(s, EFECTIVO, "169900")
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("368900"), usuario_id="maria")  # −$1.000

    s.cerrar(usuario_id="maria", ahora=CERRADA)
    assert s.diferencia_total() == pesos("-1000")


def test_un_descuadre_grande_exige_justificacion_y_permiso():
    """INV-C5. Un faltante sin explicación no se puede cerrar solo.

    Ya no hay firma de un tercero por PIN: el permiso lo trae quien tiene la
    sesión abierta, y quien cierra es quien queda firmando.
    """
    s = nueva_sesion()
    vender(s, EFECTIVO, "800000")
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("985000"), usuario_id="maria")  # −$15.000

    with pytest.raises(ReglaDeNegocio, match="justificación"):
        s.cerrar(usuario_id="maria", ahora=CERRADA)

    with pytest.raises(RequiereAutorizacion):
        s.cerrar(usuario_id="maria", ahora=CERRADA,
                 justificacion="faltante de vuelto en el turno de la tarde")

    evento = s.cerrar(usuario_id="laura", ahora=CERRADA,
                      justificacion="faltante de vuelto en el turno de la tarde",
                      puede_cerrar_con_descuadre=True)
    assert evento.cuadro is False
    assert evento.diferencia == pesos("-15000")
    assert s.autorizada_por == "laura"


def test_un_cierre_cuadrado_no_deja_firma_de_descuadre():
    """`autorizada_por` sólo tiene sentido cuando hubo algo que autorizar.
    Rellenarlo siempre haría que un informe de descuadres los listara todos."""
    s = nueva_sesion()
    vender(s, EFECTIVO, "800000")
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("1000000"), usuario_id="maria")

    evento = s.cerrar(usuario_id="maria", ahora=CERRADA)
    assert evento.cuadro is True
    assert s.autorizada_por is None


def test_un_sobrante_grande_tambien_exige_explicacion():
    """Sobrar plata no es una buena noticia: es plata sin venta que la explique."""
    s = nueva_sesion()
    vender(s, EFECTIVO, "800000")
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("1020000"), usuario_id="maria")  # +$20.000
    with pytest.raises(ReglaDeNegocio, match="justificación"):
        s.cerrar(usuario_id="maria", ahora=CERRADA)


def test_la_diferencia_se_reporta_por_medio_de_pago():
    """Un total que no cuadra sin saber DÓNDE no le sirve a quien cierra."""
    s = nueva_sesion()
    vender(s, EFECTIVO, "100000")
    vender(s, DATAFONO, "500000", efectivo=False)
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("299000"), usuario_id="maria")   # −$1.000
    s.declarar_conteo(DATAFONO, pesos("500000"), usuario_id="maria")   # cuadra

    dif = s.diferencia_por_medio()
    assert dif[EFECTIVO] == pesos("-1000")
    assert dif[DATAFONO] == Dinero.cero(COP)


def test_no_se_cierra_sin_declarar_todos_los_medios_que_se_movieron():
    s = nueva_sesion()
    vender(s, EFECTIVO, "100000")
    vender(s, DATAFONO, "500000", efectivo=False)
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("300000"), usuario_id="maria")
    with pytest.raises(ReglaDeNegocio, match="[Ff]alta declarar.*datafono"):
        s.cerrar(usuario_id="maria", ahora=CERRADA)


# ── Inmutabilidad y ventas tardías · INV-C7, C8 ─────────────────────────────

def test_una_sesion_cerrada_es_inmutable():
    s = nueva_sesion()
    vender(s, EFECTIVO, "169900")
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("369900"), usuario_id="maria")
    s.cerrar(usuario_id="maria", ahora=CERRADA)

    with pytest.raises(SesionYaCerrada):
        s.registrar_ingreso(pesos("1000"), motivo="tarde", usuario_id="maria")
    with pytest.raises(SesionYaCerrada):
        s.cerrar(usuario_id="maria", ahora=CERRADA)


def test_una_venta_offline_que_llega_tarde_no_se_pierde():
    """INV-C8. El caso que rompe todos los POS mal diseñados.

    Rechazarla sería perder una venta real que ya ocurrió y ya se cobró.
    Aceptarla en silencio descuadraría un cierre ya firmado. Se acepta, se
    marca como desfasada y se reporta al supervisor.
    """
    s = nueva_sesion()
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("200000"), usuario_id="maria")
    s.cerrar(usuario_id="maria", ahora=CERRADA)

    tarde = CERRADA + timedelta(minutes=30)
    desfase = s.registrar_venta_desfasada(
        venta_id=ULID, medio_pago_id=EFECTIVO, monto=pesos("169900"),
        es_efectivo=True, ocurrido_en=tarde)

    assert desfase.sesion_id == s.id
    assert desfase.monto == pesos("169900")
    assert s.tiene_ventas_desfasadas()
    # El cierre firmado NO cambia.
    assert s.diferencia_total() == Dinero.cero(COP)


def test_un_cobro_normal_sobre_una_sesion_cerrada_si_es_un_error():
    """Sólo la sincronización de una venta offline puede llegar tarde."""
    s = nueva_sesion()
    s.iniciar_arqueo(ventas_en_borrador=0)
    s.declarar_conteo(EFECTIVO, pesos("200000"), usuario_id="maria")
    s.cerrar(usuario_id="maria", ahora=CERRADA)
    with pytest.raises(SesionYaCerrada):
        vender(s, EFECTIVO, "1000")
