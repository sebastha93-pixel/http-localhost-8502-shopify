"""
Permisos y libro de tiempo — Fase 4.

Los dos tests que más importan aquí:
  · test_permiso_legal_no_puede_ser_compensable  → protege al trabajador
  · test_no_existe_forma_de_editar_un_asiento    → protege el saldo
"""
from datetime import date, datetime, timedelta

import pytest
from unittest.mock import MagicMock

from backend.services import personal_libro as libro
from backend.services import personal_permisos_logic as L


D = lambda h, m=0, dia=27: datetime(2026, 7, dia, h, m)


# ═══════════════════════════════════════════════════════════════════════
# MÁQUINA DE ESTADOS
# ═══════════════════════════════════════════════════════════════════════

def test_flujo_feliz_compensable():
    camino = ["borrador", "enviada", "pendiente_jefe", "pendiente_th",
              "en_compensacion", "completada"]
    for a, b in zip(camino, camino[1:]):
        assert L.transicion_valida(a, b), f"{a} → {b} debería ser válida"


def test_flujo_feliz_no_compensable():
    camino = ["borrador", "enviada", "pendiente_jefe", "pendiente_th", "aprobada"]
    for a, b in zip(camino, camino[1:]):
        assert L.transicion_valida(a, b)


def test_no_se_puede_saltar_al_jefe():
    """TH no debe poder aprobar algo que el jefe no ha visto."""
    assert not L.transicion_valida("enviada", "pendiente_th")
    assert not L.transicion_valida("borrador", "aprobada")


def test_no_se_revive_un_terminal():
    for terminal in ("rechazada", "cancelada", "completada", "enviada_a_nomina"):
        assert L.es_terminal(terminal)
        for destino in L.ESTADOS:
            assert not L.transicion_valida(terminal, destino), \
                f"{terminal} no debería ir a {destino}"


def test_cancelable_solo_antes_de_decidir():
    for e in ("borrador", "enviada", "pendiente_jefe", "pendiente_th"):
        assert L.puede_cancelar(e)
    for e in ("completada", "rechazada", "enviada_a_nomina"):
        assert not L.puede_cancelar(e)


def test_vencida_no_se_pierde_va_a_nomina():
    """Un plazo vencido NO se descuenta solo: pasa a revisión humana."""
    assert L.transicion_valida("en_compensacion", "vencida")
    assert L.transicion_valida("vencida", "enviada_a_nomina")
    assert L.transicion_valida("vencida", "completada")   # TH puede condonar


def test_toda_transicion_apunta_a_estado_conocido():
    for origen, destinos in L.TRANSICIONES.items():
        assert origen in L.ESTADOS
        for d in destinos:
            assert d in L.ESTADOS, f"{origen} → {d} no es un estado válido"


def test_siguiente_paso_indica_quien_tiene_la_pelota():
    assert L.siguiente_paso("pendiente_jefe") == "jefe"
    assert L.siguiente_paso("pendiente_th") == "talento_humano"
    assert L.siguiente_paso("en_compensacion") == "empleado"
    assert L.siguiente_paso("completada") is None


# ═══════════════════════════════════════════════════════════════════════
# CLASIFICACIÓN — la regla que protege al trabajador
# ═══════════════════════════════════════════════════════════════════════

def test_permiso_legal_no_puede_ser_compensable():
    """Convertir una licencia de luto en horas por reponer sería ilegal."""
    with pytest.raises(ValueError, match="permiso_legal_no_puede_ser_compensable"):
        L.validar_clasificacion("legal_remunerado", es_compensable=True)


def test_permiso_legal_no_compensable_es_valido():
    L.validar_clasificacion("legal_remunerado", es_compensable=False)   # no lanza


def test_incapacidad_no_es_compensable():
    with pytest.raises(ValueError, match="incapacidad_no_puede_ser_compensable"):
        L.validar_clasificacion("incapacidad", es_compensable=True)


def test_personal_si_puede_ser_compensable():
    L.validar_clasificacion("personal_compensable", es_compensable=True)


def test_categoria_invalida():
    with pytest.raises(ValueError, match="categoria_invalida"):
        L.validar_clasificacion("porque_si", es_compensable=False)


@pytest.mark.parametrize("categoria,esperado", [
    ("legal_remunerado",       "sin_efecto"),
    ("empresarial_remunerado", "sin_efecto"),
    ("personal_compensable",   "compensacion"),
    ("no_remunerado",          "licencia_no_remunerada"),
    ("incapacidad",            "sin_efecto"),
    ("vacaciones",             "sin_efecto"),
])
def test_tratamiento_nomina(categoria, esperado):
    assert L.tratamiento_nomina(categoria) == esperado


# ═══════════════════════════════════════════════════════════════════════
# VALIDACIÓN DE LA SOLICITUD
# ═══════════════════════════════════════════════════════════════════════

def test_minutos_se_calculan_del_rango():
    assert L.minutos_solicitados(D(8), D(10)) == 120


def test_rango_invertido_se_rechaza():
    with pytest.raises(ValueError, match="rango_invalido"):
        L.minutos_solicitados(D(10), D(8))


def test_rango_de_cero_se_rechaza():
    with pytest.raises(ValueError, match="rango_invalido"):
        L.minutos_solicitados(D(8), D(8))


def test_motivo_es_obligatorio():
    with pytest.raises(ValueError, match="motivo_requerido"):
        L.validar_solicitud(inicio=D(8), fin=D(10), motivo="   ")


def test_respeta_el_maximo_del_tipo():
    with pytest.raises(ValueError, match="excede_maximo_del_tipo"):
        L.validar_solicitud(inicio=D(8), fin=D(14), motivo="x", minutos_max=240)


def test_soporte_obligatorio_cuando_el_tipo_lo_pide():
    with pytest.raises(ValueError, match="soporte_requerido"):
        L.validar_solicitud(inicio=D(8), fin=D(10), motivo="cita",
                            requiere_soporte=True, tiene_soporte=False)


def test_tope_de_compensable():
    with pytest.raises(ValueError, match="excede_maximo_compensable"):
        L.validar_solicitud(inicio=D(8), fin=D(20), motivo="x",
                            es_compensable=True, max_compensable=480)


def test_solicitud_valida_devuelve_minutos():
    assert L.validar_solicitud(inicio=D(8), fin=D(10), motivo="cita médica") == 120


# ── Cruces ───────────────────────────────────────────────────────────────────

def test_rangos_contiguos_no_cruzan():
    """08:00-10:00 y 10:00-12:00 son contiguos, no solapados."""
    assert not L.hay_cruce(D(8), D(10), D(10), D(12))


def test_rangos_solapados_cruzan():
    assert L.hay_cruce(D(8), D(12), D(10), D(14))


def test_rango_contenido_cruza():
    assert L.hay_cruce(D(8), D(18), D(10), D(12))


def test_rechaza_permiso_que_cruza_con_otro_vigente():
    existentes = [{"id": "P-VIEJO", "estado": "aprobada",
                   "_inicio": D(8), "_fin": D(12)}]
    with pytest.raises(ValueError, match="cruza_con_permiso_existente"):
        L.validar_sin_cruces(D(10), D(14), existentes)


def test_no_cruza_con_uno_rechazado():
    """Un permiso rechazado no bloquea el calendario."""
    existentes = [{"id": "P1", "estado": "rechazada", "_inicio": D(8), "_fin": D(12)}]
    L.validar_sin_cruces(D(10), D(14), existentes)      # no lanza


# ═══════════════════════════════════════════════════════════════════════
# COMPENSACIÓN
# ═══════════════════════════════════════════════════════════════════════

def test_fecha_limite_por_defecto_es_la_semana():
    assert L.fecha_limite_compensacion(date(2026, 7, 27)) == date(2026, 8, 3)


def test_el_dia_del_plazo_todavia_cuenta():
    limite = date(2026, 8, 3)
    assert not L.esta_vencida(limite, date(2026, 8, 3))
    assert L.esta_vencida(limite, date(2026, 8, 4))


@pytest.mark.parametrize("total,hecho,hoy,esperado", [
    (480, 480, date(2026, 7, 30), "completado"),
    (480, 500, date(2026, 7, 30), "completado"),   # repuso de más
    (480, 200, date(2026, 7, 30), "activo"),
    (480, 200, date(2026, 8, 10), "vencido"),
    (480, 480, date(2026, 8, 10), "completado"),   # completó antes de vencer
])
def test_estado_del_plan(total, hecho, hoy, esperado):
    assert L.estado_del_plan(total, hecho, date(2026, 8, 3), hoy) == esperado


def test_pendiente_nunca_es_negativo():
    assert L.minutos_pendientes(480, 600) == 0


# ═══════════════════════════════════════════════════════════════════════
# LIBRO DE TIEMPO — INVARIANTE 3
# ═══════════════════════════════════════════════════════════════════════

class FakeSB:
    def __init__(self, data=None):
        self.inserted, self.updated = [], []
        self._data = data or []

    def table(self, n):
        self._t = n
        return self

    def insert(self, d):
        self.inserted.append((self._t, d))
        self._p = d
        return self

    def update(self, d):
        self.updated.append((self._t, d))
        self._p = d
        return self

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        r = MagicMock()
        p = getattr(self, "_p", None)
        r.data = [p] if p else self._data
        self._p = None
        return r


@pytest.fixture
def sb(monkeypatch):
    f = FakeSB()
    monkeypatch.setattr(libro, "sb_requerido", lambda: f)
    monkeypatch.setattr(libro, "_sb", lambda: f)
    monkeypatch.setattr(libro.aud, "registrar", lambda **k: None)
    return f


def test_no_existe_forma_de_editar_un_asiento():
    """INVARIANTE 3, verificado sobre la superficie del módulo.

    Si mañana alguien agrega un `actualizar_asiento`, este test lo atrapa.
    La única forma de corregir es reversar + registrar.
    """
    publicos = [n for n in dir(libro) if not n.startswith("_")]
    prohibidos = [n for n in publicos
                  if any(v in n.lower() for v in ("actualizar", "editar", "modificar",
                                                  "set_saldo", "ajustar_saldo", "borrar",
                                                  "eliminar"))]
    assert not prohibidos, f"el libro expone mutadores: {prohibidos}"


def test_el_saldo_es_una_suma_no_una_columna():
    movs = [
        {"estado": "vigente", "direccion": "debito",  "minutos": 120},
        {"estado": "vigente", "direccion": "credito", "minutos": 60},
    ]
    s = libro.calcular_saldo(movs)
    assert s["saldo_pendiente"] == 60
    assert s["minutos_debito"] == 120


def test_los_reversados_no_cuentan():
    movs = [
        {"estado": "vigente",   "direccion": "debito", "minutos": 120},
        {"estado": "reversado", "direccion": "debito", "minutos": 500},
    ]
    s = libro.calcular_saldo(movs)
    assert s["saldo_pendiente"] == 120
    assert s["reversados"] == 1


def test_saldo_pendiente_nunca_negativo():
    """Repuso de más: no queda "a favor". El banco positivo está desactivado."""
    movs = [
        {"estado": "vigente", "direccion": "debito",  "minutos": 60},
        {"estado": "vigente", "direccion": "credito", "minutos": 200},
    ]
    s = libro.calcular_saldo(movs)
    assert s["saldo_pendiente"] == 0
    assert s["saldo_neto"] == -140      # el neto sí lo muestra, para auditoría


def test_permiso_siempre_debita(sb):
    a = libro.registrar(empleado_id="E1", tipo_asiento="permiso_debito",
                        minutos=120, tipo_origen="solicitud_permiso",
                        descripcion="Permiso personal")
    assert a["direccion"] == "debito"


def test_compensacion_siempre_acredita(sb):
    a = libro.registrar(empleado_id="E1", tipo_asiento="compensacion_credito",
                        minutos=120, tipo_origen="bloque_compensacion",
                        descripcion="Repuso el jueves")
    assert a["direccion"] == "credito"


def test_no_se_puede_forzar_la_direccion_contraria(sb):
    """Un permiso no puede acreditar tiempo aunque el caller lo pida."""
    with pytest.raises(ValueError, match="direccion_incompatible"):
        libro.registrar(empleado_id="E1", tipo_asiento="permiso_debito",
                        direccion="credito", minutos=120,
                        tipo_origen="solicitud_permiso", descripcion="x")


def test_ajuste_manual_exige_aprobador(sb):
    with pytest.raises(ValueError, match="ajuste_manual_requiere_aprobador"):
        libro.registrar(empleado_id="E1", tipo_asiento="ajuste_manual",
                        direccion="credito", minutos=60,
                        tipo_origen="manual", descripcion="corrección")


def test_ajuste_manual_con_aprobador_pasa(sb):
    a = libro.registrar(empleado_id="E1", tipo_asiento="ajuste_manual",
                        direccion="credito", minutos=60, tipo_origen="manual",
                        descripcion="corrección acordada",
                        aprobado_por="th@maledenim.com")
    assert a["aprobado_por"] == "th@maledenim.com"


@pytest.mark.parametrize("minutos", [0, -30, 1.5, "60", None])
def test_minutos_debe_ser_entero_positivo(sb, minutos):
    """La dirección se declara; no se codifica en el signo."""
    with pytest.raises(ValueError, match="minutos_debe_ser_entero_positivo"):
        libro.registrar(empleado_id="E1", tipo_asiento="permiso_debito",
                        minutos=minutos, tipo_origen="solicitud_permiso",
                        descripcion="x")


def test_descripcion_obligatoria(sb):
    with pytest.raises(ValueError, match="descripcion_requerida"):
        libro.registrar(empleado_id="E1", tipo_asiento="permiso_debito",
                        minutos=60, tipo_origen="solicitud_permiso", descripcion="  ")


def test_reversion_exige_asiento_origen(sb):
    with pytest.raises(ValueError, match="reversion_requiere_asiento_origen"):
        libro.registrar(empleado_id="E1", tipo_asiento="reversion",
                        direccion="credito", minutos=60,
                        tipo_origen="manual", descripcion="x")


def test_reversar_crea_espejo_y_no_edita_el_original(monkeypatch):
    """La corrección es un asiento nuevo, nunca una edición."""
    original = {"id": "A1", "empleado_id": "E1", "direccion": "debito",
                "minutos": 120, "tipo_origen": "solicitud_permiso",
                "tipo_asiento": "permiso_debito", "estado": "vigente"}
    f = FakeSB(data=[original])
    monkeypatch.setattr(libro, "sb_requerido", lambda: f)
    monkeypatch.setattr(libro, "_sb", lambda: f)
    monkeypatch.setattr(libro.aud, "registrar", lambda **k: None)

    espejo = libro.reversar("A1", motivo="se registró dos veces", actor="th@male.com")

    assert espejo["direccion"] == "credito"          # dirección contraria
    assert espejo["minutos"] == 120                  # mismo valor
    assert espejo["reversa_a_id"] == "A1"

    # Al original solo se le tocó el ESTADO. minutos y direccion, intactos.
    tocados = [d for t, d in f.updated if t == "personal_libro_tiempo"]
    assert tocados == [{"estado": "reversado"}]


def test_reversar_exige_motivo(monkeypatch):
    monkeypatch.setattr(libro, "sb_requerido", lambda: FakeSB())
    with pytest.raises(ValueError, match="motivo_requerido_para_reversar"):
        libro.reversar("A1", motivo="", actor="x@male.com")


def test_no_se_reversa_dos_veces(monkeypatch):
    f = FakeSB(data=[{"id": "A1", "estado": "reversado", "direccion": "debito",
                      "minutos": 60, "tipo_asiento": "permiso_debito"}])
    monkeypatch.setattr(libro, "sb_requerido", lambda: f)
    with pytest.raises(ValueError, match="asiento_no_vigente"):
        libro.reversar("A1", motivo="otra vez", actor="x@male.com")


def test_no_se_reversa_una_reversion(monkeypatch):
    f = FakeSB(data=[{"id": "R1", "estado": "vigente", "direccion": "credito",
                      "minutos": 60, "tipo_asiento": "reversion"}])
    monkeypatch.setattr(libro, "sb_requerido", lambda: f)
    with pytest.raises(ValueError, match="no_se_reversa_una_reversion"):
        libro.reversar("R1", motivo="x", actor="x@male.com")


def test_extracto_no_expone_forma_de_editar(monkeypatch):
    movs = [{"id": "A1", "estado": "vigente", "direccion": "debito", "minutos": 120,
             "fecha_efectiva": "2026-07-27", "tipo_asiento": "permiso_debito",
             "descripcion": "Permiso", "tipo_origen": "solicitud_permiso"}]
    monkeypatch.setattr(libro, "asientos", lambda *a, **k: movs)
    e = libro.extracto("E1")
    assert e["resumen"]["saldo_pendiente"] == 120
    assert set(e["movimientos"][0]) == {
        "id", "fecha", "tipo", "direccion", "minutos", "descripcion",
        "origen", "aprobado_por", "estado", "automatico"}
