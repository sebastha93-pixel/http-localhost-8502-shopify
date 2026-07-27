"""
backend.services.personal_motor — Motor de interpretación de asistencia.

FUNCIÓN PURA. Este módulo no importa Supabase, no lee el reloj del sistema y
no escribe nada. Recibe datos, devuelve datos.

Tres consecuencias de eso:
  1. Los 36 casos de prueba corren sin base de datos.
  2. La idempotencia es demostrable, no una aspiración.
  3. El recálculo masivo es barato: se cargan los insumos una vez y se itera.

La regla que gobierna todo
──────────────────────────
El Dahua sabe que alguien cruzó una puerta. NO sabe si trabajó, si esperaba
que dejara de llover, o si estaba haciendo un turno extra autorizado.

Por eso `minutos_posible_extra` (hecho observado) y `minutos_extra_aprobada`
(decisión previa) son campos SEPARADOS, y este motor nunca copia el primero
en el segundo. Llegar antes o quedarse después no genera crédito. Nunca.

Ver TIME_MANAGEMENT_DOMAIN_RULES.md §2 y §4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

VERSION_CALCULO = "v1"


# ═══════════════════════════════════════════════════════════════════════
# ENTRADAS
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Evento:
    """Un hecho del dispositivo. Inmutable, como su tabla."""
    id: str
    timestamp: datetime
    direccion: str = "desconocida"        # entrada | salida | desconocida
    dispositivo_id: Optional[str] = None
    sede_id: Optional[str] = None
    resultado: str = "concedido"          # los denegados no cuentan como marcación


@dataclass(frozen=True)
class HorarioDia:
    """El horario que rige ESE día. Puede venir de plantilla o de turno."""
    inicio: time
    fin: time
    cruza_medianoche: bool = False
    descanso_inicio: Optional[time] = None
    descanso_fin: Optional[time] = None
    minutos_esperados: int = 0
    es_dia_laboral: bool = True
    sede_id: Optional[str] = None
    horario_id: Optional[str] = None
    turno_id: Optional[str] = None


@dataclass(frozen=True)
class Permiso:
    """Permiso YA APROBADO que toca este día."""
    id: str
    inicio: datetime
    fin: datetime
    minutos: int
    categoria: str = "personal_compensable"
    es_remunerado: bool = True


@dataclass(frozen=True)
class Compensacion:
    """Bloque de reposición programado y aprobado para este día."""
    id: str
    inicio: datetime
    fin: datetime
    minutos_planeados: int


@dataclass(frozen=True)
class Extra:
    """Hora extra AUTORIZADA para este día. Sin esto no hay extra que valga."""
    id: str
    inicio: datetime
    fin: datetime
    minutos_autorizados: int


@dataclass(frozen=True)
class Empleado:
    id: str
    sujeto_a_jornada: bool = True
    rota_entre_sedes: bool = False
    sede_id: Optional[str] = None
    estado_laboral: str = "activo"
    fecha_ingreso: Optional[date] = None
    fecha_retiro: Optional[date] = None


# ═══════════════════════════════════════════════════════════════════════
# SALIDAS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Segmento:
    entrada_at: Optional[datetime]
    salida_at: Optional[datetime]
    minutos: int
    tipo: str = "trabajo"                 # trabajo | descanso | permiso | compensacion | extra
    estado: str = "cerrado"               # cerrado | abierto | inferido
    evento_entrada_id: Optional[str] = None
    evento_salida_id: Optional[str] = None


@dataclass
class Incidencia:
    tipo: str
    severidad: str = "media"
    descripcion: str = ""
    evento_id: Optional[str] = None


@dataclass
class Jornada:
    empleado_id: str
    work_date: date

    horario_id: Optional[str] = None
    turno_planificado_id: Optional[str] = None
    sede_id: Optional[str] = None
    inicio_programado: Optional[datetime] = None
    fin_programado: Optional[datetime] = None

    primera_entrada_at: Optional[datetime] = None
    ultima_salida_at: Optional[datetime] = None

    minutos_esperados: int = 0
    minutos_trabajados: int = 0
    minutos_permiso_autorizado: int = 0
    minutos_tarde: int = 0
    minutos_salida_anticipada: int = 0
    minutos_exceso_descanso: int = 0
    minutos_compensacion_aprob: int = 0

    # HECHO observado — nunca es crédito por sí solo
    minutos_posible_extra: int = 0
    # DECISIÓN previa — esto sí cuenta
    minutos_extra_aprobada: int = 0

    minutos_recargo_nocturno: int = 0
    minutos_dominical_festivo: int = 0

    estado_asistencia: str = "sin_datos"
    version_calculo: str = VERSION_CALCULO
    parametros_usados: dict = field(default_factory=dict)
    explicacion: str = ""


@dataclass
class Resultado:
    jornada: Jornada
    segmentos: list[Segmento] = field(default_factory=list)
    incidencias: list[Incidencia] = field(default_factory=list)

    def tipos_incidencia(self) -> set[str]:
        return {i.tipo for i in self.incidencias}


# ═══════════════════════════════════════════════════════════════════════
# MOTOR
# ═══════════════════════════════════════════════════════════════════════

def calcular_jornada(
    *,
    empleado: Empleado,
    work_date: date,
    horario: Optional[HorarioDia],
    eventos: Iterable[Evento] = (),
    permisos: Iterable[Permiso] = (),
    compensaciones: Iterable[Compensacion] = (),
    extras: Iterable[Extra] = (),
    festivos: Optional[set] = None,
    reglas: Optional[dict] = None,
) -> Resultado:
    """Interpreta un día de un empleado.

    Determinista: mismos insumos → mismo resultado, siempre.
    Idempotente: llamarla N veces no acumula nada.

    No recibe `ahora` a propósito: nada de lo que calcula depende del instante
    en que se ejecuta. Un día de marzo se recalcula igual hoy que en diciembre.
    """
    R = dict(_REGLAS_BASE)
    R.update(reglas or {})
    festivos = festivos or set()

    j = Jornada(empleado_id=empleado.id, work_date=work_date)
    incidencias: list[Incidencia] = []
    pasos: list[str] = []

    eventos = _preparar_eventos(eventos, work_date, R, incidencias, pasos)

    # ── Caso: sin horario ──────────────────────────────────────────────
    # Nunca se asume un horario por defecto. Un empleado sin horario es un
    # problema de configuración que alguien debe ver, no un cálculo que
    # inventar sobre datos que no tenemos.
    if horario is None:
        incidencias.append(Incidencia(
            "horario_no_encontrado", "alta",
            f"No hay horario ni turno asignado para {work_date}."))
        j.estado_asistencia = "sin_datos"
        if eventos:
            incidencias.append(Incidencia(
                "marcacion_sin_jornada", "media",
                f"{len(eventos)} marcación(es) sin horario contra el cual interpretarlas."))
            j.primera_entrada_at = eventos[0].timestamp
            j.ultima_salida_at = eventos[-1].timestamp
        pasos.append("Sin horario asignado: no se calcula tiempo esperado ni retrasos.")
        j.explicacion = " ".join(pasos)
        j.parametros_usados = _parametros(R)
        return Resultado(j, [], incidencias)

    j.horario_id = horario.horario_id
    j.turno_planificado_id = horario.turno_id
    j.sede_id = horario.sede_id or empleado.sede_id

    inicio_prog, fin_prog = _ventana_programada(work_date, horario)
    j.inicio_programado, j.fin_programado = inicio_prog, fin_prog

    es_festivo = work_date in festivos
    es_domingo = work_date.weekday() == 6

    # ── Caso: día no laboral ───────────────────────────────────────────
    if not horario.es_dia_laboral or es_festivo:
        j.estado_asistencia = "festivo" if es_festivo else "descanso"
        j.minutos_esperados = 0
        if eventos:
            segs, incs = _emparejar(eventos, R)
            incidencias.extend(incs)
            trabajados = sum(s.minutos for s in segs if s.estado == "cerrado")
            j.minutos_trabajados = trabajados
            j.primera_entrada_at = segs[0].entrada_at if segs else None
            j.ultima_salida_at = _ultima_salida(segs)
            if trabajados:
                j.minutos_dominical_festivo = trabajados
                j.minutos_recargo_nocturno = _minutos_nocturnos(segs, R)
                # Trabajar en descanso NO genera crédito por sí solo.
                j.minutos_posible_extra = trabajados
                j.minutos_extra_aprobada = _extra_reconocida(extras, trabajados, R)
                if not j.minutos_extra_aprobada:
                    incidencias.append(Incidencia(
                        "posible_hora_extra", "alta",
                        f"Trabajó {trabajados} min en {'festivo' if es_festivo else 'día de descanso'} "
                        f"sin autorización previa."))
                pasos.append(
                    f"Día no laboral: {trabajados} min registrados como posible extra, "
                    f"{j.minutos_extra_aprobada} min reconocidos por autorización.")
            j.explicacion = " ".join(pasos) or "Día no laboral sin marcaciones."
            j.parametros_usados = _parametros(R)
            return Resultado(j, segs, incidencias)
        pasos.append("Festivo." if es_festivo else "Día de descanso.")
        j.explicacion = " ".join(pasos)
        j.parametros_usados = _parametros(R)
        return Resultado(j, [], incidencias)

    # ── Caso: fuera de vínculo laboral ─────────────────────────────────
    if _fuera_de_vinculo(empleado, work_date):
        j.estado_asistencia = "sin_datos"
        j.minutos_esperados = 0
        pasos.append("Fuera del periodo de vinculación del empleado.")
        if eventos:
            incidencias.append(Incidencia(
                "marcacion_sin_jornada", "alta",
                "Marcación de un empleado retirado o aún no vinculado."))
        j.explicacion = " ".join(pasos)
        j.parametros_usados = _parametros(R)
        return Resultado(j, [], incidencias)

    # ── Día laboral normal ─────────────────────────────────────────────
    esperados_base = horario.minutos_esperados or _minutos_ventana(inicio_prog, fin_prog, horario)
    minutos_permiso = _minutos_permiso(permisos, inicio_prog, fin_prog)
    j.minutos_permiso_autorizado = minutos_permiso

    # Un permiso aprobado REDUCE lo que se espera. No suma trabajo.
    j.minutos_esperados = max(0, esperados_base - minutos_permiso)

    segmentos, incs = _emparejar(eventos, R)
    incidencias.extend(incs)

    if not eventos:
        # Sin marcaciones: ausente, salvo que el permiso cubra el día entero.
        if minutos_permiso >= esperados_base and esperados_base > 0:
            j.estado_asistencia = "permiso"
            pasos.append(f"Permiso aprobado cubre la jornada completa ({minutos_permiso} min).")
        else:
            j.estado_asistencia = "ausente"
            incidencias.append(Incidencia(
                "falta_entrada", "alta",
                f"Sin marcaciones en un día laboral (esperados {esperados_base} min)."))
            pasos.append("Sin marcaciones en día laboral.")
        j.explicacion = " ".join(pasos)
        j.parametros_usados = _parametros(R)
        return Resultado(j, [], incidencias)

    j.primera_entrada_at = segmentos[0].entrada_at if segmentos else None
    j.ultima_salida_at = _ultima_salida(segmentos)
    if empleado.rota_entre_sedes:
        sede_real = next((e.sede_id for e in eventos if e.sede_id), None)
        if sede_real:
            j.sede_id = sede_real

    brutos = sum(s.minutos for s in segmentos if s.estado == "cerrado")

    # Descanso: si no lo marcaron, se descuenta igual. Sin esto, todo el que
    # almuerza sin marcar acumularía una hora de "posible extra" cada día.
    descanso_marcado, exceso = _analizar_descanso(segmentos, horario, R)
    j.minutos_exceso_descanso = exceso
    descontado = 0
    if not descanso_marcado and R["descontar_descanso_no_marcado"]:
        descanso_prog = _minutos_descanso_programado(horario)
        if descanso_prog and brutos > descanso_prog:
            descontado = descanso_prog
            pasos.append(f"No marcó el descanso: se descuentan {descanso_prog} min programados.")

    j.minutos_trabajados = max(0, brutos - descontado)

    # ── Retraso y salida anticipada ────────────────────────────────────
    if empleado.sujeto_a_jornada:
        if j.primera_entrada_at:
            tarde = _minutos(inicio_prog, j.primera_entrada_at) - R["tolerancia_ingreso_min"]
            j.minutos_tarde = max(0, tarde)
            if j.minutos_tarde:
                pasos.append(
                    f"Entró {j.primera_entrada_at:%H:%M} contra {inicio_prog:%H:%M} programado "
                    f"y {R['tolerancia_ingreso_min']} min de tolerancia: {j.minutos_tarde} min tarde.")
        if j.ultima_salida_at:
            antes = _minutos(j.ultima_salida_at, fin_prog) - R["tolerancia_salida_min"]
            j.minutos_salida_anticipada = max(0, antes)
            if j.minutos_salida_anticipada:
                pasos.append(
                    f"Salió {j.ultima_salida_at:%H:%M} contra {fin_prog:%H:%M}: "
                    f"{j.minutos_salida_anticipada} min de salida anticipada.")
    else:
        # CST Art. 162: dirección, confianza y manejo no están sujetos a la
        # jornada máxima. No se les calcula tarde ni extra.
        pasos.append("Cargo no sujeto a jornada: no se calculan retrasos ni extras.")

    # ── Permiso que justifica el retraso o la salida ───────────────────
    if minutos_permiso:
        cubierto_inicio = _permiso_cubre(permisos, inicio_prog)
        cubierto_fin = _permiso_cubre(permisos, fin_prog - timedelta(minutes=1))
        if cubierto_inicio and j.minutos_tarde:
            pasos.append(f"El retraso de {j.minutos_tarde} min está cubierto por permiso aprobado.")
            j.minutos_tarde = 0
        if cubierto_fin and j.minutos_salida_anticipada:
            pasos.append(
                f"La salida anticipada de {j.minutos_salida_anticipada} min "
                f"está cubierta por permiso aprobado.")
            j.minutos_salida_anticipada = 0

    # ── Compensación ───────────────────────────────────────────────────
    # Programar no es compensar: solo cuenta el tiempo efectivamente trabajado
    # dentro del bloque aprobado.
    j.minutos_compensacion_aprob = _minutos_compensados(compensaciones, segmentos)
    if j.minutos_compensacion_aprob:
        pasos.append(f"Compensación validada contra marcaciones: {j.minutos_compensacion_aprob} min.")

    # ── Posible extra vs extra reconocida ──────────────────────────────
    if empleado.sujeto_a_jornada:
        excedente = max(0, j.minutos_trabajados - j.minutos_esperados - j.minutos_compensacion_aprob)
        j.minutos_posible_extra = excedente
        j.minutos_extra_aprobada = _extra_reconocida(extras, excedente, R)

        if excedente >= R["umbral_posible_extra_min"] and not j.minutos_extra_aprobada:
            incidencias.append(Incidencia(
                "posible_hora_extra", "media",
                f"Permaneció {excedente} min más allá de su jornada sin autorización previa. "
                f"La permanencia no constituye hora extra."))
            pasos.append(
                f"{excedente} min de permanencia adicional SIN autorización: "
                f"no se reconocen como extra.")
        elif j.minutos_extra_aprobada:
            pasos.append(
                f"Extra autorizada: se reconocen {j.minutos_extra_aprobada} min "
                f"(mínimo entre autorizado y trabajado).")

        j.minutos_recargo_nocturno = _minutos_nocturnos(segmentos, R)
        if es_domingo:
            j.minutos_dominical_festivo = j.minutos_trabajados

    # ── Incidencias de completitud ─────────────────────────────────────
    abiertos = [s for s in segmentos if s.estado == "abierto"]
    if abiertos and R["generar_incidencia_salida_faltante"]:
        incidencias.append(Incidencia(
            "falta_salida", "alta",
            f"Entrada {abiertos[-1].entrada_at:%H:%M} sin salida correspondiente."))

    if j.minutos_exceso_descanso:
        incidencias.append(Incidencia(
            "descanso_excedido", "baja",
            f"Descanso excedido en {j.minutos_exceso_descanso} min."))

    j.estado_asistencia = _estado(j, abiertos, minutos_permiso, esperados_base)

    pasos.insert(0, f"Trabajó {j.minutos_trabajados} min de {j.minutos_esperados} esperados.")
    j.explicacion = " ".join(pasos)
    j.parametros_usados = _parametros(R)
    return Resultado(j, segmentos, incidencias)


# ═══════════════════════════════════════════════════════════════════════
# INTERNOS
# ═══════════════════════════════════════════════════════════════════════

_REGLAS_BASE = {
    "tolerancia_ingreso_min": 5,
    "tolerancia_salida_min": 5,
    "tolerancia_duplicado_seg": 30,
    "salida_intermedia_significativa_min": 10,
    "umbral_posible_extra_min": 30,
    "generar_incidencia_salida_faltante": True,
    "descontar_descanso_no_marcado": True,
    "hora_inicio_nocturno": "21:00",
    "hora_fin_nocturno": "06:00",
}


def _parametros(R: dict) -> dict:
    """Los parámetros con los que se calculó. Se persisten con la jornada para
    que una cifra vieja siga siendo explicable aunque las reglas cambien."""
    return dict(R)


def _minutos(a: datetime, b: datetime) -> int:
    """Minutos de a → b. Trunca, nunca redondea, nunca negativo."""
    if a is None or b is None:
        return 0
    return max(0, int((b - a).total_seconds() // 60))


def _preparar_eventos(eventos, work_date, R, incidencias, pasos) -> list[Evento]:
    """Ordena, descarta denegados y colapsa duplicados."""
    ordenados = sorted(
        [e for e in eventos if e.resultado == "concedido"],
        key=lambda e: (e.timestamp, e.id),      # id desempata → orden estable
    )
    if not ordenados:
        return []

    limpios: list[Evento] = [ordenados[0]]
    for e in ordenados[1:]:
        prev = limpios[-1]
        delta = (e.timestamp - prev.timestamp).total_seconds()
        # Duplicado: misma dirección dentro de la ventana de tolerancia.
        if delta <= R["tolerancia_duplicado_seg"] and e.direccion == prev.direccion:
            incidencias.append(Incidencia(
                "evento_duplicado", "baja",
                f"Marcación repetida a {e.timestamp:%H:%M:%S} ({int(delta)}s de la anterior).",
                evento_id=e.id))
            continue
        limpios.append(e)
    if len(limpios) < len(ordenados):
        pasos.append(f"Se descartaron {len(ordenados) - len(limpios)} marcación(es) duplicada(s).")
    return limpios


def _emparejar(eventos: list[Evento], R: dict) -> tuple[list[Segmento], list[Incidencia]]:
    """Empareja entradas con salidas. NUNCA inventa una hora.

    Un segmento sin cierre queda 'abierto' y no aporta minutos trabajados.
    La corrección la hace una persona, con soporte y auditoría.
    """
    segmentos: list[Segmento] = []
    incidencias: list[Incidencia] = []
    abierto: Optional[Evento] = None

    for e in eventos:
        direccion = e.direccion
        if direccion == "desconocida":
            # Sin dirección del dispositivo, se alterna: la 1ª es entrada.
            direccion = "salida" if abierto else "entrada"

        if direccion == "entrada":
            if abierto is not None:
                incidencias.append(Incidencia(
                    "secuencia_imposible", "media",
                    f"Dos entradas seguidas ({abierto.timestamp:%H:%M} y {e.timestamp:%H:%M}) "
                    f"sin salida entre ellas.", evento_id=e.id))
                segmentos.append(Segmento(abierto.timestamp, None, 0, estado="abierto",
                                          evento_entrada_id=abierto.id))
            abierto = e
        else:
            if abierto is None:
                incidencias.append(Incidencia(
                    "falta_entrada", "alta",
                    f"Salida a las {e.timestamp:%H:%M} sin entrada previa.", evento_id=e.id))
                segmentos.append(Segmento(None, e.timestamp, 0, estado="inferido",
                                          evento_salida_id=e.id))
                continue
            segmentos.append(Segmento(
                abierto.timestamp, e.timestamp,
                _minutos(abierto.timestamp, e.timestamp),
                evento_entrada_id=abierto.id, evento_salida_id=e.id))
            abierto = None

    if abierto is not None:
        segmentos.append(Segmento(abierto.timestamp, None, 0, estado="abierto",
                                  evento_entrada_id=abierto.id))
    return segmentos, incidencias


def _ventana_programada(work_date: date, h: HorarioDia) -> tuple[datetime, datetime]:
    """Inicio y fin programados como instantes.

    Si el turno cruza medianoche, el fin cae al día siguiente. La jornada
    pertenece siempre a la fecha en que EMPIEZA.
    """
    inicio = datetime.combine(work_date, h.inicio)
    fin_dia = work_date + timedelta(days=1) if h.cruza_medianoche else work_date
    fin = datetime.combine(fin_dia, h.fin)
    if fin <= inicio:                       # defensa por si falta la bandera
        fin += timedelta(days=1)
    return inicio, fin


def _minutos_ventana(inicio: datetime, fin: datetime, h: HorarioDia) -> int:
    total = _minutos(inicio, fin)
    return max(0, total - _minutos_descanso_programado(h))


def _minutos_descanso_programado(h: HorarioDia) -> int:
    if h.descanso_inicio and h.descanso_fin:
        d0 = datetime.combine(date(2000, 1, 1), h.descanso_inicio)
        d1 = datetime.combine(date(2000, 1, 1), h.descanso_fin)
        if d1 < d0:
            d1 += timedelta(days=1)
        return _minutos(d0, d1)
    return 0


def _analizar_descanso(segmentos, h: HorarioDia, R: dict) -> tuple[bool, int]:
    """¿Marcaron el descanso? ¿Se pasaron?

    Un hueco entre segmentos más largo que `salida_intermedia_significativa_min`
    cuenta como descanso marcado.
    """
    cerrados = [s for s in segmentos if s.estado == "cerrado"]
    if len(cerrados) < 2:
        return False, 0

    huecos = []
    for a, b in zip(cerrados, cerrados[1:]):
        if a.salida_at and b.entrada_at:
            hueco = _minutos(a.salida_at, b.entrada_at)
            if hueco >= R["salida_intermedia_significativa_min"]:
                huecos.append(hueco)
    if not huecos:
        return False, 0

    programado = _minutos_descanso_programado(h)
    return True, max(0, sum(huecos) - programado) if programado else 0


def _minutos_permiso(permisos, inicio_prog: datetime, fin_prog: datetime) -> int:
    """Minutos de permiso que se solapan con la jornada programada."""
    total = 0
    for p in permisos:
        ini = max(p.inicio, inicio_prog)
        fin = min(p.fin, fin_prog)
        total += _minutos(ini, fin)
    return total


def _permiso_cubre(permisos, momento: datetime) -> bool:
    return any(p.inicio <= momento < p.fin for p in permisos)


def _minutos_compensados(compensaciones, segmentos) -> int:
    """Solo cuenta el tiempo REALMENTE trabajado dentro del bloque aprobado.

    Programar una compensación no compensa nada: si no marcó, no repuso.
    """
    total = 0
    for c in compensaciones:
        for s in segmentos:
            if s.estado != "cerrado" or not s.entrada_at or not s.salida_at:
                continue
            ini = max(s.entrada_at, c.inicio)
            fin = min(s.salida_at, c.fin)
            total += _minutos(ini, fin)
    return min(total, sum(c.minutos_planeados for c in compensaciones))


def _extra_reconocida(extras, excedente: int, R: dict) -> int:
    """Se reconoce el MÍNIMO entre lo autorizado y lo efectivamente trabajado.

    Autorizar 2 h y trabajar 1 paga 1. Trabajar 3 con 2 autorizadas paga 2, y
    la hora sobrante queda como incidencia para revisión humana.
    """
    autorizado = sum(x.minutos_autorizados for x in extras)
    if not autorizado or excedente <= 0:
        return 0
    return min(autorizado, excedente)


def _minutos_nocturnos(segmentos, R: dict) -> int:
    """Minutos trabajados dentro de la franja nocturna (CST)."""
    ini_noc = _hora(R["hora_inicio_nocturno"])
    fin_noc = _hora(R["hora_fin_nocturno"])
    total = 0
    for s in segmentos:
        if s.estado != "cerrado" or not s.entrada_at or not s.salida_at:
            continue
        cursor = s.entrada_at.replace(second=0, microsecond=0)
        while cursor < s.salida_at:
            t = cursor.time()
            # La franja cruza medianoche: es nocturno si t >= 21:00 O t < 06:00
            if t >= ini_noc or t < fin_noc:
                total += 1
            cursor += timedelta(minutes=1)
    return total


def _hora(txt: str) -> time:
    h, m = txt.split(":")[:2]
    return time(int(h), int(m))


def _ultima_salida(segmentos) -> Optional[datetime]:
    salidas = [s.salida_at for s in segmentos if s.salida_at]
    return max(salidas) if salidas else None


def _fuera_de_vinculo(e: Empleado, d: date) -> bool:
    if e.fecha_ingreso and d < e.fecha_ingreso:
        return True
    if e.fecha_retiro and d > e.fecha_retiro:
        return True
    return False


def _estado(j: Jornada, abiertos, minutos_permiso: int, esperados_base: int) -> str:
    if abiertos:
        return "incompleta"
    if j.minutos_trabajados == 0:
        if minutos_permiso >= esperados_base and esperados_base > 0:
            return "permiso"
        return "ausente"
    if j.minutos_tarde:
        return "tarde"
    if j.minutos_salida_anticipada:
        return "salida_anticipada"
    return "completa"
