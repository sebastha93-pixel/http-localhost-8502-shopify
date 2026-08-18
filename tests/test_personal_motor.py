"""
Motor de asistencia — los 36 casos de la especificación + los invariantes.

Corre SIN base de datos: el motor es una función pura. Esa es justamente la
razón de haberlo diseñado así.

Los casos que dependen de servicios (cierres de periodo, correcciones,
conector offline) viven en las Fases 4 y 6 y están marcados abajo.
"""
from datetime import date, datetime, time, timedelta

import pytest

from backend.services.personal_motor import (
    Compensacion, Empleado, Evento, Extra, HorarioDia, Permiso,
    calcular_jornada,
)

DIA = date(2026, 7, 27)          # lunes
DOMINGO = date(2026, 8, 2)
FESTIVO = date(2026, 8, 7)       # Batalla de Boyacá (viernes)


# ── Constructores de conveniencia ────────────────────────────────────────────

def emp(**kw):
    return Empleado(id="E1", **kw)


def horario(inicio="08:00", fin="18:00", descanso=("13:00", "14:00"),
            esperados=540, laboral=True, cruza=False):
    hi, hf = _t(inicio), _t(fin)
    d0 = _t(descanso[0]) if descanso else None
    d1 = _t(descanso[1]) if descanso else None
    return HorarioDia(inicio=hi, fin=hf, descanso_inicio=d0, descanso_fin=d1,
                      minutos_esperados=esperados, es_dia_laboral=laboral,
                      cruza_medianoche=cruza, horario_id="H1")


def _t(s):
    h, m = s.split(":")
    return time(int(h), int(m))


def ev(hhmm, direccion="entrada", dia=DIA, eid=None, seg=0, **kw):
    h, m = hhmm.split(":")
    ts = datetime.combine(dia, time(int(h), int(m), seg))
    return Evento(id=eid or f"{direccion[0]}{hhmm}{seg}", timestamp=ts,
                  direccion=direccion, **kw)


def jornada_normal(eventos=None, **kw):
    """El caso base: 8-18 con almuerzo, 9h esperadas."""
    return calcular_jornada(
        empleado=kw.pop("empleado", emp()),
        work_date=kw.pop("work_date", DIA),
        horario=kw.pop("horario", horario()),
        eventos=eventos if eventos is not None else [ev("08:00"), ev("18:00", "salida")],
        **kw,
    )


# ═══════════════════════════════════════════════════════════════════════
# CASOS 1-4 · Jornada básica
# ═══════════════════════════════════════════════════════════════════════

def test_01_entrada_y_salida_normales():
    r = jornada_normal([ev("08:00"), ev("13:00", "salida"),
                        ev("14:00"), ev("18:00", "salida")])
    assert r.jornada.minutos_trabajados == 540        # 9h netas
    assert r.jornada.minutos_tarde == 0
    assert r.jornada.estado_asistencia == "completa"
    assert not r.incidencias


def test_02_entrada_anticipada_no_es_credito():
    """Llegar 40 min antes NO genera nada a favor."""
    r = jornada_normal([ev("07:20"), ev("18:00", "salida")])
    assert r.jornada.minutos_tarde == 0
    assert r.jornada.minutos_extra_aprobada == 0      # ← lo que importa


def test_03_llegada_tarde():
    r = jornada_normal([ev("08:20"), ev("18:00", "salida")])
    assert r.jornada.minutos_tarde == 15              # 20 menos 5 de tolerancia
    assert r.jornada.estado_asistencia == "tarde"


def test_03b_dentro_de_la_tolerancia_no_es_tarde():
    r = jornada_normal([ev("08:04"), ev("18:00", "salida")])
    assert r.jornada.minutos_tarde == 0


def test_04_salida_anticipada():
    r = jornada_normal([ev("08:00"), ev("17:30", "salida")])
    assert r.jornada.minutos_salida_anticipada == 25  # 30 menos 5
    assert r.jornada.estado_asistencia == "salida_anticipada"


# ═══════════════════════════════════════════════════════════════════════
# CASOS 5-12 · Anomalías de marcación
# ═══════════════════════════════════════════════════════════════════════

def test_05_doble_marcacion_se_colapsa():
    r = jornada_normal([ev("08:00", seg=0), ev("08:00", seg=12),
                        ev("18:00", "salida")])
    assert "evento_duplicado" in r.tipos_incidencia()
    assert r.jornada.minutos_trabajados == 540        # sin efecto en el cálculo


def test_06_falta_entrada():
    r = jornada_normal([ev("18:00", "salida")])
    assert "falta_entrada" in r.tipos_incidencia()
    assert r.jornada.minutos_trabajados == 0          # no se inventa la hora


def test_07_falta_salida():
    r = jornada_normal([ev("08:00")])
    assert "falta_salida" in r.tipos_incidencia()
    assert r.jornada.minutos_trabajados == 0
    assert r.jornada.estado_asistencia == "incompleta"


def test_08_almuerzo_marcado():
    r = jornada_normal([ev("08:00"), ev("13:00", "salida"),
                        ev("14:00"), ev("18:00", "salida")])
    assert r.jornada.minutos_trabajados == 540
    assert r.jornada.minutos_exceso_descanso == 0


def test_08b_almuerzo_no_marcado_se_descuenta_igual():
    """Sin esto, todo el que almuerza sin marcar acumularía 1h de extra diaria."""
    r = jornada_normal([ev("08:00"), ev("18:00", "salida")])
    assert r.jornada.minutos_trabajados == 540        # 10h brutas menos 1h
    assert r.jornada.minutos_posible_extra == 0


def test_08c_exceso_de_descanso():
    r = jornada_normal([ev("08:00"), ev("13:00", "salida"),
                        ev("14:30"), ev("18:00", "salida")])
    assert r.jornada.minutos_exceso_descanso == 30
    assert "descanso_excedido" in r.tipos_incidencia()


def test_09_multiples_salidas():
    r = jornada_normal([ev("08:00"), ev("10:00", "salida"),
                        ev("10:30"), ev("13:00", "salida"),
                        ev("14:00"), ev("18:00", "salida")])
    assert len([s for s in r.segmentos if s.estado == "cerrado"]) == 3
    assert r.jornada.minutos_trabajados == 510        # 8.5h efectivas


def test_11_evento_duplicado_no_altera_resultado():
    base = jornada_normal([ev("08:00"), ev("18:00", "salida")])
    con_dup = jornada_normal([ev("08:00", seg=0), ev("08:00", seg=5),
                              ev("18:00", "salida", seg=0),
                              ev("18:00", "salida", seg=9)])
    assert con_dup.jornada.minutos_trabajados == base.jornada.minutos_trabajados


def test_12_evento_fuera_de_orden_se_ordena():
    """El conector puede entregar eventos desordenados; el motor los ordena."""
    desordenados = jornada_normal([ev("18:00", "salida"), ev("08:00")])
    ordenados = jornada_normal([ev("08:00"), ev("18:00", "salida")])
    assert desordenados.jornada.minutos_trabajados == ordenados.jornada.minutos_trabajados


def test_12b_dos_entradas_seguidas_es_secuencia_imposible():
    r = jornada_normal([ev("08:00"), ev("10:00"), ev("18:00", "salida")])
    assert "secuencia_imposible" in r.tipos_incidencia()


def test_12c_marcacion_denegada_no_cuenta():
    """El Dahua registra intentos denegados; no son marcaciones."""
    r = jornada_normal([
        Evento("x", datetime.combine(DIA, time(7, 55)), "entrada", resultado="denegado"),
        ev("08:00"), ev("18:00", "salida"),
    ])
    assert r.jornada.primera_entrada_at.hour == 8


# ═══════════════════════════════════════════════════════════════════════
# CASOS 15-17 · Permisos
# ═══════════════════════════════════════════════════════════════════════

def _permiso(desde, hasta, categoria="personal_compensable", dia=DIA):
    h0, m0 = desde.split(":")
    h1, m1 = hasta.split(":")
    ini = datetime.combine(dia, time(int(h0), int(m0)))
    fin = datetime.combine(dia, time(int(h1), int(m1)))
    return Permiso("P1", ini, fin, int((fin - ini).total_seconds() // 60), categoria)


def test_15_permiso_reduce_lo_esperado():
    """Un permiso NO suma trabajo: baja lo que se espera."""
    r = jornada_normal([ev("08:00"), ev("16:00", "salida")],
                       permisos=[_permiso("16:00", "18:00")])
    assert r.jornada.minutos_permiso_autorizado == 120
    assert r.jornada.minutos_esperados == 420         # 540 menos 120
    assert r.jornada.minutos_salida_anticipada == 0   # el permiso lo justifica


def test_15b_permiso_de_dia_completo_sin_marcaciones():
    r = jornada_normal([], permisos=[_permiso("08:00", "18:00")])
    assert r.jornada.estado_asistencia == "permiso"
    assert "falta_entrada" not in r.tipos_incidencia()


def test_15c_permiso_al_inicio_justifica_el_retraso():
    r = jornada_normal([ev("10:00"), ev("18:00", "salida")],
                       permisos=[_permiso("08:00", "10:00")])
    assert r.jornada.minutos_tarde == 0


def test_16_permiso_compensable_no_regala_tiempo():
    """El permiso baja lo esperado, pero la deuda la lleva el libro de tiempo
    (Fase 4). El motor no crea ni salda saldos."""
    r = jornada_normal([ev("08:00"), ev("16:00", "salida")],
                       permisos=[_permiso("16:00", "18:00")])
    assert r.jornada.minutos_posible_extra == 0
    assert r.jornada.minutos_extra_aprobada == 0


def test_17_sin_permiso_la_salida_temprano_si_cuenta():
    r = jornada_normal([ev("08:00"), ev("16:00", "salida")])
    assert r.jornada.minutos_salida_anticipada == 115  # 120 menos 5


# ═══════════════════════════════════════════════════════════════════════
# CASOS 18-19 · Compensaciones
# ═══════════════════════════════════════════════════════════════════════

def _comp(desde, hasta, dia=DIA):
    h0, m0 = desde.split(":")
    h1, m1 = hasta.split(":")
    ini = datetime.combine(dia, time(int(h0), int(m0)))
    fin = datetime.combine(dia, time(int(h1), int(m1)))
    return Compensacion("C1", ini, fin, int((fin - ini).total_seconds() // 60))


def test_18_compensacion_parcial_solo_cuenta_lo_trabajado():
    """Programó reponer 2h, trabajó 1h → se reconoce 1h. Programar no compensa."""
    r = jornada_normal([ev("08:00"), ev("19:00", "salida")],
                       compensaciones=[_comp("18:00", "20:00")])
    assert r.jornada.minutos_compensacion_aprob == 60


def test_19_compensacion_completa():
    r = jornada_normal([ev("08:00"), ev("20:00", "salida")],
                       compensaciones=[_comp("18:00", "20:00")])
    assert r.jornada.minutos_compensacion_aprob == 120


def test_19b_compensacion_programada_sin_marcar_no_cuenta():
    r = jornada_normal([ev("08:00"), ev("18:00", "salida")],
                       compensaciones=[_comp("18:00", "20:00")])
    assert r.jornada.minutos_compensacion_aprob == 0


def test_19c_compensacion_no_se_cuenta_ademas_como_extra():
    """El tiempo repuesto no puede pagarse dos veces."""
    r = jornada_normal([ev("08:00"), ev("20:00", "salida")],
                       compensaciones=[_comp("18:00", "20:00")])
    assert r.jornada.minutos_posible_extra == 0


# ═══════════════════════════════════════════════════════════════════════
# CASOS 21-22 · Horas extras — el corazón del módulo
# ═══════════════════════════════════════════════════════════════════════

def _extra(desde, hasta, minutos=None, dia=DIA):
    h0, m0 = desde.split(":")
    h1, m1 = hasta.split(":")
    ini = datetime.combine(dia, time(int(h0), int(m0)))
    fin = datetime.combine(dia, time(int(h1), int(m1)))
    return Extra("X1", ini, fin, minutos if minutos is not None
                 else int((fin - ini).total_seconds() // 60))


def test_21_hora_extra_autorizada_se_reconoce():
    r = jornada_normal([ev("08:00"), ev("20:00", "salida")],
                       extras=[_extra("18:00", "20:00")])
    assert r.jornada.minutos_posible_extra == 120
    assert r.jornada.minutos_extra_aprobada == 120


def test_22_permanencia_no_autorizada_no_es_extra():
    """LA prueba del módulo. Se quedó 2h más sin autorización: 0 reconocidas."""
    r = jornada_normal([ev("08:00"), ev("20:00", "salida")])
    assert r.jornada.minutos_posible_extra == 120     # el HECHO se registra
    assert r.jornada.minutos_extra_aprobada == 0      # la DECISIÓN no existe
    assert "posible_hora_extra" in r.tipos_incidencia()


def test_22b_se_reconoce_el_minimo_entre_autorizado_y_trabajado():
    """Autorizaron 3h, trabajó 1h → se paga 1h."""
    r = jornada_normal([ev("08:00"), ev("19:00", "salida")],
                       extras=[_extra("18:00", "21:00")])
    assert r.jornada.minutos_extra_aprobada == 60


def test_22c_trabajar_mas_de_lo_autorizado_no_amplia_la_extra():
    """Autorizaron 1h, trabajó 3h → se paga 1h; el resto es incidencia."""
    r = jornada_normal([ev("08:00"), ev("21:00", "salida")],
                       extras=[_extra("18:00", "19:00")])
    assert r.jornada.minutos_posible_extra == 180
    assert r.jornada.minutos_extra_aprobada == 60


def test_22d_excedente_pequeno_no_levanta_incidencia():
    """Quedarse 10 min no debe generar ruido todos los días."""
    r = jornada_normal([ev("08:00"), ev("18:10", "salida")])
    assert "posible_hora_extra" not in r.tipos_incidencia()


# ═══════════════════════════════════════════════════════════════════════
# CASOS 32-36 · Casos de borde
# ═══════════════════════════════════════════════════════════════════════

def test_33_dia_festivo():
    r = calcular_jornada(empleado=emp(), work_date=FESTIVO, horario=horario(),
                         eventos=[], festivos={FESTIVO})
    assert r.jornada.estado_asistencia == "festivo"
    assert r.jornada.minutos_esperados == 0


def test_33b_trabajar_en_festivo_sin_autorizacion():
    r = calcular_jornada(empleado=emp(), work_date=FESTIVO, horario=horario(),
                         eventos=[ev("08:00", dia=FESTIVO),
                                  ev("14:00", "salida", dia=FESTIVO)],
                         festivos={FESTIVO})
    assert r.jornada.minutos_dominical_festivo == 360
    assert r.jornada.minutos_extra_aprobada == 0
    assert "posible_hora_extra" in r.tipos_incidencia()


def test_33c_trabajar_en_festivo_con_autorizacion():
    r = calcular_jornada(empleado=emp(), work_date=FESTIVO, horario=horario(),
                         eventos=[ev("08:00", dia=FESTIVO),
                                  ev("14:00", "salida", dia=FESTIVO)],
                         extras=[_extra("08:00", "14:00", dia=FESTIVO)],
                         festivos={FESTIVO})
    assert r.jornada.minutos_extra_aprobada == 360


def test_33d_domingo_trabajado_se_marca():
    r = calcular_jornada(empleado=emp(), work_date=DOMINGO,
                         horario=horario(esperados=480),
                         eventos=[ev("08:00", dia=DOMINGO),
                                  ev("17:00", "salida", dia=DOMINGO)])
    assert r.jornada.minutos_dominical_festivo > 0


def test_34_turno_que_cruza_medianoche():
    """Entra el lunes 22:00, sale el martes 06:00. La jornada es del LUNES."""
    h = HorarioDia(inicio=time(22, 0), fin=time(6, 0), cruza_medianoche=True,
                   minutos_esperados=480, horario_id="H-NOC")
    r = calcular_jornada(
        empleado=emp(), work_date=DIA, horario=h,
        eventos=[ev("22:00", dia=DIA),
                 ev("06:00", "salida", dia=DIA + timedelta(days=1))])
    assert r.jornada.work_date == DIA                 # ancla a la fecha de INICIO
    assert r.jornada.minutos_trabajados == 480
    assert r.jornada.minutos_tarde == 0


def test_34b_turno_nocturno_acumula_recargo():
    h = HorarioDia(inicio=time(22, 0), fin=time(6, 0), cruza_medianoche=True,
                   minutos_esperados=480, horario_id="H-NOC")
    r = calcular_jornada(
        empleado=emp(), work_date=DIA, horario=h,
        eventos=[ev("22:00", dia=DIA),
                 ev("06:00", "salida", dia=DIA + timedelta(days=1))])
    assert r.jornada.minutos_recargo_nocturno == 480  # toda la jornada es nocturna


def test_35_empleado_retirado():
    e = emp(fecha_retiro=date(2026, 7, 20))
    r = calcular_jornada(empleado=e, work_date=DIA, horario=horario(), eventos=[])
    assert r.jornada.estado_asistencia == "sin_datos"
    assert r.jornada.minutos_esperados == 0


def test_35b_marcacion_de_retirado_levanta_incidencia():
    e = emp(fecha_retiro=date(2026, 7, 20))
    r = calcular_jornada(empleado=e, work_date=DIA, horario=horario(),
                         eventos=[ev("08:00")])
    assert "marcacion_sin_jornada" in r.tipos_incidencia()


def test_35c_antes_de_ingresar_no_se_calcula():
    e = emp(fecha_ingreso=date(2026, 8, 1))
    r = calcular_jornada(empleado=e, work_date=DIA, horario=horario(), eventos=[])
    assert r.jornada.estado_asistencia == "sin_datos"


def test_36_empleado_sin_horario():
    """Nunca se asume un horario. Es un problema de configuración que alguien
    debe ver, no un cálculo que inventar."""
    r = calcular_jornada(empleado=emp(), work_date=DIA, horario=None, eventos=[])
    assert "horario_no_encontrado" in r.tipos_incidencia()
    assert r.jornada.estado_asistencia == "sin_datos"
    assert r.jornada.minutos_esperados == 0


def test_36b_marcacion_sin_horario():
    r = calcular_jornada(empleado=emp(), work_date=DIA, horario=None,
                         eventos=[ev("08:00"), ev("18:00", "salida")])
    assert "marcacion_sin_jornada" in r.tipos_incidencia()
    assert r.jornada.minutos_trabajados == 0


def test_dia_de_descanso_sin_marcaciones():
    r = calcular_jornada(empleado=emp(), work_date=DIA,
                         horario=horario(laboral=False), eventos=[])
    assert r.jornada.estado_asistencia == "descanso"


def test_ausente_en_dia_laboral():
    r = jornada_normal([])
    assert r.jornada.estado_asistencia == "ausente"
    assert "falta_entrada" in r.tipos_incidencia()


# ═══════════════════════════════════════════════════════════════════════
# CST Art. 162 — cargos no sujetos a jornada
# ═══════════════════════════════════════════════════════════════════════

def test_no_sujeto_a_jornada_no_acumula_tarde_ni_extra():
    """Dirección, confianza y manejo están excluidos de la jornada máxima."""
    e = emp(sujeto_a_jornada=False)
    r = jornada_normal([ev("10:00"), ev("21:00", "salida")], empleado=e)
    assert r.jornada.minutos_tarde == 0
    assert r.jornada.minutos_posible_extra == 0
    assert r.jornada.minutos_extra_aprobada == 0


# ═══════════════════════════════════════════════════════════════════════
# Multi-sede — el caso Sandra
# ═══════════════════════════════════════════════════════════════════════

def test_sede_se_toma_del_dispositivo_para_quien_rota():
    e = emp(rota_entre_sedes=True, sede_id="SEDE-BASE")
    r = jornada_normal([ev("08:00", sede_id="SEDE-FLORIDA"),
                        ev("18:00", "salida", sede_id="SEDE-FLORIDA")],
                       empleado=e)
    assert r.jornada.sede_id == "SEDE-FLORIDA"


def test_quien_no_rota_conserva_su_sede():
    e = emp(rota_entre_sedes=False, sede_id="SEDE-BASE")
    r = jornada_normal([ev("08:00", sede_id="SEDE-OTRA"),
                        ev("18:00", "salida")], empleado=e)
    assert r.jornada.sede_id == "SEDE-BASE"


# ═══════════════════════════════════════════════════════════════════════
# CASO 26 + INVARIANTES · Lo que blinda el módulo
# ═══════════════════════════════════════════════════════════════════════

EVENTOS_TIPICOS = [ev("08:07"), ev("13:02", "salida"), ev("14:05"), ev("18:20", "salida")]


def test_26_reprocesamiento_idempotente():
    """Mismos insumos → mismo resultado. Base de todo el recálculo."""
    a = jornada_normal(list(EVENTOS_TIPICOS))
    b = jornada_normal(list(EVENTOS_TIPICOS))
    assert a.jornada == b.jornada
    assert len(a.segmentos) == len(b.segmentos)
    assert a.tipos_incidencia() == b.tipos_incidencia()


def test_26b_reprocesar_diez_veces_no_acumula():
    resultados = [jornada_normal(list(EVENTOS_TIPICOS)) for _ in range(10)]
    minutos = {r.jornada.minutos_trabajados for r in resultados}
    incidencias = {len(r.incidencias) for r in resultados}
    assert len(minutos) == 1
    assert len(incidencias) == 1


def test_26c_el_orden_de_llegada_no_altera_el_resultado():
    normal = jornada_normal(list(EVENTOS_TIPICOS))
    revuelto = jornada_normal(list(reversed(EVENTOS_TIPICOS)))
    assert normal.jornada.minutos_trabajados == revuelto.jornada.minutos_trabajados
    assert normal.jornada.minutos_tarde == revuelto.jornada.minutos_tarde


def test_invariante_llegar_antes_no_genera_credito():
    temprano = jornada_normal([ev("06:00"), ev("18:00", "salida")])
    puntual = jornada_normal([ev("08:00"), ev("18:00", "salida")])
    assert temprano.jornada.minutos_extra_aprobada == 0
    assert puntual.jornada.minutos_extra_aprobada == 0


def test_invariante_salir_tarde_no_genera_credito():
    tarde = jornada_normal([ev("08:00"), ev("22:00", "salida")])
    assert tarde.jornada.minutos_extra_aprobada == 0
    assert tarde.jornada.minutos_posible_extra > 0     # se registra como hecho


def test_invariante_permanecer_no_genera_credito():
    """Ni llegando antes Y saliendo después a la vez."""
    r = jornada_normal([ev("06:00"), ev("22:00", "salida")])
    assert r.jornada.minutos_extra_aprobada == 0


def test_invariante_la_extra_exige_autorizacion_previa():
    sin_auth = jornada_normal([ev("08:00"), ev("21:00", "salida")])
    con_auth = jornada_normal([ev("08:00"), ev("21:00", "salida")],
                              extras=[_extra("18:00", "21:00")])
    assert sin_auth.jornada.minutos_extra_aprobada == 0
    assert con_auth.jornada.minutos_extra_aprobada == 180


def test_invariante_el_motor_no_muta_sus_entradas():
    """Función pura: los eventos que entran salen intactos."""
    eventos = [ev("08:00"), ev("18:00", "salida")]
    copia = [(e.id, e.timestamp, e.direccion) for e in eventos]
    jornada_normal(eventos)
    assert [(e.id, e.timestamp, e.direccion) for e in eventos] == copia


def test_invariante_los_parametros_quedan_registrados():
    """Una cifra vieja debe seguir siendo explicable aunque cambien las reglas."""
    r = jornada_normal()
    assert r.jornada.parametros_usados["tolerancia_ingreso_min"] == 5
    assert r.jornada.version_calculo == "v1"


def test_invariante_toda_jornada_trae_explicacion():
    for eventos in ([], [ev("08:00")], [ev("08:20"), ev("18:00", "salida")]):
        r = jornada_normal(eventos)
        assert r.jornada.explicacion, f"sin explicación para {eventos}"


def test_explicacion_es_legible_y_cita_los_numeros():
    r = jornada_normal([ev("08:20"), ev("18:00", "salida")])
    txt = r.jornada.explicacion
    assert "08:20" in txt and "08:00" in txt and "15 min tarde" in txt


# ═══════════════════════════════════════════════════════════════════════
# CASO 23 · Cambio retroactivo de horario
# ═══════════════════════════════════════════════════════════════════════

def test_23_cambio_retroactivo_de_horario_recalcula_distinto():
    """El mismo día con otro horario da otro resultado — y eso está bien.
    Por eso las asignaciones de horario tienen vigencia y no se editan."""
    eventos = [ev("09:00"), ev("18:00", "salida")]
    con_8 = jornada_normal(list(eventos), horario=horario("08:00", "18:00"))
    con_9 = jornada_normal(list(eventos), horario=horario("09:00", "18:00"))
    assert con_8.jornada.minutos_tarde == 55
    assert con_9.jornada.minutos_tarde == 0


# ═══════════════════════════════════════════════════════════════════════
# Casos que pertenecen a fases posteriores
# ═══════════════════════════════════════════════════════════════════════

def test_el_motor_sigue_siendo_puro():
    """Guarda de arquitectura, no de comportamiento.

    Todo el diseño del módulo se apoya en que el motor sea una función pura:
    es lo que hace demostrable la idempotencia y lo que permite probar los 36
    casos sin base de datos. Si alguien le mete un `import supabase` o un
    `datetime.now()`, este test lo atrapa antes que producción.
    """
    import ast
    import pathlib

    ruta = pathlib.Path(__file__).parent.parent / "backend/services/personal_motor.py"
    arbol = ast.parse(ruta.read_text())

    importados = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            importados |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            importados.add((n.module or "").split(".")[0])

    prohibidos = {"supabase", "httpx", "requests", "os", "backend", "fastapi", "random"}
    assert not (importados & prohibidos), \
        f"el motor dejó de ser puro: importa {sorted(importados & prohibidos)}"

    reloj = [n for n in ast.walk(arbol)
             if isinstance(n, ast.Attribute) and n.attr in ("now", "today", "utcnow")]
    assert not reloj, "el motor usa el reloj del sistema: pierde el determinismo"


@pytest.mark.parametrize("caso,fase", [
    ("10 · evento de empleado desconocido",   "3 · ingesta"),
    ("13 · dispositivo desconectado",          "6 · conector"),
    ("14 · evento recibido tarde",             "3 · ingesta"),
    ("20 · compensación vencida",              "4 · servicios"),
    ("24 · corrección aprobada",               "4 · servicios"),
    ("25 · corrección rechazada",              "4 · servicios"),
    ("27 · cierre de periodo",                 "7 · nómina"),
    ("28 · reapertura de periodo",             "7 · nómina"),
    ("30 · conector sin internet",             "6 · conector"),
    ("31 · reintento de sincronización",       "6 · conector"),
    ("32 · dos sedes con zonas horarias",      "3 · ingesta"),
])
def test_casos_de_fases_posteriores(caso, fase):
    """Marcador vivo: estos casos NO los cubre el motor puro.

    Están aquí para que la lista de 36 quede completa y visible, y para que
    nadie los dé por probados. Cada uno se implementa en la fase indicada.
    """
    pytest.skip(f"Caso {caso} → se prueba en Fase {fase}")


# ═══════════════════════════════════════════════════════════════════════
# Sedes sin dispositivo de control de acceso
# ═══════════════════════════════════════════════════════════════════════

def test_sin_dispositivo_no_marca_ausente():
    """Las tiendas aún no tienen lector. Esa gente SÍ trabaja.

    Sin este corte, cada día suyo saldría 'ausente' —una alerta falsa diaria
    por persona— y el tablero mostraría un ausentismo que no existe.
    """
    e = emp(controla_asistencia=False)
    r = jornada_normal([], empleado=e)
    assert r.jornada.estado_asistencia == "sin_datos"
    assert "falta_entrada" not in r.tipos_incidencia()
    assert r.jornada.minutos_esperados == 0


def test_sin_dispositivo_lo_dice_en_la_explicacion():
    """Quien lea el detalle debe entender por qué no hay datos."""
    r = jornada_normal([], empleado=emp(controla_asistencia=False))
    assert "control de acceso" in r.jornada.explicacion.lower()
    assert "no significa ausencia" in r.jornada.explicacion.lower()


def test_marcacion_inesperada_sin_dispositivo_avisa():
    """Si llegan marcaciones de alguien 'sin control', la config quedó vieja:
    probablemente ya instalaron el lector y nadie cambió la bandera."""
    e = emp(controla_asistencia=False)
    r = jornada_normal([ev("08:00"), ev("18:00", "salida")], empleado=e)
    assert "ajuste_manual_requerido" in r.tipos_incidencia()


def test_con_dispositivo_si_marca_ausente():
    """El caso normal no cambia: sin marcaciones y con lector, es ausencia."""
    r = jornada_normal([], empleado=emp(controla_asistencia=True))
    assert r.jornada.estado_asistencia == "ausente"


def test_sin_control_no_es_lo_mismo_que_no_sujeto_a_jornada():
    """Son dos conceptos distintos y deben comportarse distinto.

    · sujeto_a_jornada=False  → exclusión LEGAL (CST 162). Trabaja y marca,
      pero no se le calculan tarde ni extras.
    · controla_asistencia=False → limitación OPERATIVA. Sí tiene jornada,
      pero no hay dispositivo que la registre.
    """
    legal = jornada_normal([ev("10:00"), ev("21:00", "salida")],
                           empleado=emp(sujeto_a_jornada=False))
    operativo = jornada_normal([], empleado=emp(controla_asistencia=False))

    # El excluido legal SÍ acumula tiempo trabajado; solo no se le cobra tarde
    assert legal.jornada.minutos_trabajados > 0
    assert legal.jornada.minutos_tarde == 0
    # El que no tiene lector no acumula nada, porque no hay qué medir
    assert operativo.jornada.minutos_trabajados == 0
    assert operativo.jornada.estado_asistencia == "sin_datos"


# ── Alcance de la jornada: no contar los días vecinos ────────────────────────
#
# El bug real, encontrado con datos de producción el 2026-08-18.
#
# La consulta trae una ventana amplia (día anterior + siguiente) porque un turno
# nocturno puede desbordar por cualquiera de los dos extremos. El motor se los
# tragaba TODOS: la jornada del 11 de agosto de una persona quedó con
# `primera_entrada_at` del día 10 y 850 minutos trabajados contra 480 esperados
# — la entrada del lunes emparejada con la salida del martes.
#
# No hubo excepción ni log. Solo un banco de horas con el doble de lo real.

from backend.services.personal_motor import _REGLAS_BASE, eventos_de_la_jornada

ADMIN = horario(inicio="08:30", fin="17:00", descanso=("12:30", "13:00"),
                esperados=480)


def ev_ago(dia, hh, mm):
    """Marcación de agosto, sin dirección — como las manda el Dahua real."""
    return Evento(id=f"{dia}-{hh:02d}{mm:02d}",
                  timestamp=datetime(2026, 8, dia, hh, mm),
                  direccion="desconocida", resultado="concedido")


def test_no_cuenta_las_marcaciones_del_dia_anterior():
    """El caso exacto que se coló a producción."""
    r = calcular_jornada(
        empleado=emp(), work_date=date(2026, 8, 11), horario=ADMIN,
        eventos=[ev_ago(10, 8, 12), ev_ago(10, 17, 2),   # lunes: NO son de aquí
                 ev_ago(11, 8, 19), ev_ago(11, 17, 2)])  # martes: estas sí
    assert r.jornada.primera_entrada_at == datetime(2026, 8, 11, 8, 19)
    assert r.jornada.ultima_salida_at == datetime(2026, 8, 11, 17, 2)
    # 8h43 entre marcas − 30 min de descanso no marcado
    assert r.jornada.minutos_trabajados == 493
    assert r.jornada.minutos_trabajados < 600, "se tragó el día vecino"


def test_no_cuenta_las_marcaciones_del_dia_siguiente():
    r = calcular_jornada(
        empleado=emp(), work_date=date(2026, 8, 11), horario=ADMIN,
        eventos=[ev_ago(11, 8, 30), ev_ago(11, 17, 0),
                 ev_ago(12, 8, 25), ev_ago(12, 17, 5)])
    assert r.jornada.ultima_salida_at == datetime(2026, 8, 11, 17, 0)


def test_el_descarte_queda_dicho_en_la_explicacion():
    """Descartar en silencio es cómo se cuela el error de vuelta."""
    r = calcular_jornada(
        empleado=emp(), work_date=date(2026, 8, 11), horario=ADMIN,
        eventos=[ev_ago(10, 8, 12), ev_ago(11, 8, 19), ev_ago(11, 17, 2)])
    assert "otros días" in (r.jornada.explicacion or "")


def test_un_turno_nocturno_SI_reclama_la_madrugada_siguiente():
    """El filtro no puede romper el caso para el que existe la ventana amplia."""
    noche = horario(inicio="22:00", fin="06:00", descanso=None,
                    esperados=480, cruza=True)
    r = calcular_jornada(
        empleado=emp(), work_date=date(2026, 8, 11), horario=noche,
        eventos=[ev_ago(11, 21, 55), ev_ago(12, 6, 3)])
    assert r.jornada.primera_entrada_at == datetime(2026, 8, 11, 21, 55)
    assert r.jornada.ultima_salida_at == datetime(2026, 8, 12, 6, 3)
    assert r.jornada.minutos_trabajados == 488


def test_sin_horario_tambien_se_acota_al_dia():
    """`sin_datos` no puede ser una puerta trasera para contar de más."""
    r = calcular_jornada(
        empleado=emp(), work_date=date(2026, 8, 11), horario=None,
        eventos=[ev_ago(10, 8, 12), ev_ago(11, 8, 19), ev_ago(12, 9, 0)])
    assert r.jornada.primera_entrada_at == datetime(2026, 8, 11, 8, 19)
    assert r.jornada.ultima_salida_at == datetime(2026, 8, 11, 8, 19)


def test_eventos_de_la_jornada_no_muta_lo_que_recibe():
    eventos = [ev_ago(10, 8, 12), ev_ago(11, 8, 19)]
    copia = list(eventos)
    eventos_de_la_jornada(eventos, date(2026, 8, 11), ADMIN, dict(_REGLAS_BASE))
    assert eventos == copia
