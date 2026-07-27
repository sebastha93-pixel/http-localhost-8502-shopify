"""
Reglas laborales configurables.

Lo que estos tests protegen: que las reglas se resuelvan por especificidad y
que las tres reglas peligrosas (descuento automático, banco positivo, revisión
humana) tengan el default correcto. Invertir una de ellas por accidente
cambiaría cómo se trata el tiempo —y el sueldo— de la gente.
"""
import pytest

from backend.services import personal_base as base
from backend.services import personal_reglas as svc


def setup_function():
    base.cache_invalidar()


def _filas(*specs):
    """Helper: construye filas de personal_reglas."""
    return [{"clave": c, "valor": v, "ambito": a, "ambito_id": i, "activa": True}
            for c, v, a, i in specs]


# ── Defaults ─────────────────────────────────────────────────────────────────

def test_sin_tabla_caen_los_defaults(monkeypatch):
    """Si la migración no corrió, el motor NO debe quedarse sin reglas."""
    monkeypatch.setattr(svc, "_sb", lambda: None)
    r = svc.resolver()
    assert r["tolerancia_ingreso_min"] == 5
    assert r.origen_de("tolerancia_ingreso_min") == "default"


def test_las_tres_reglas_peligrosas_tienen_el_default_correcto():
    """Estos tres valores son los que impiden que el sistema actúe solo.

    Si algún día alguien los cambia en REGLAS_DEFECTO, este test debe fallar
    y obligar a una conversación explícita.
    """
    assert svc.REGLAS_DEFECTO["conversion_automatica_a_descuento"] is False
    assert svc.REGLAS_DEFECTO["banco_positivo_automatico"] is False
    assert svc.REGLAS_DEFECTO["requiere_revision_humana_nomina"] is True


def test_reglas_sensibles_estan_marcadas():
    for clave in ("conversion_automatica_a_descuento", "banco_positivo_automatico",
                  "requiere_revision_humana_nomina", "bloquear_compensacion_vencida"):
        assert clave in svc.REGLAS_SENSIBLES


def test_todo_default_tiene_descripcion():
    """La pantalla de configuración muestra la descripción; sin ella el
    administrador no sabe qué está cambiando."""
    faltantes = [k for k in svc.REGLAS_DEFECTO if k not in svc.DESCRIPCIONES]
    assert faltantes == [], f"reglas sin descripción: {faltantes}"


# ── Cascada de especificidad ─────────────────────────────────────────────────

def test_sede_gana_sobre_default(monkeypatch):
    monkeypatch.setattr(svc, "_leer_filas",
                        lambda: _filas(("tolerancia_ingreso_min", 15, "sede", "S1")))
    r = svc.resolver(sede_id="S1")
    assert r["tolerancia_ingreso_min"] == 15
    assert r.origen_de("tolerancia_ingreso_min") == "sede"


def test_empleado_gana_sobre_sede(monkeypatch):
    monkeypatch.setattr(svc, "_leer_filas", lambda: _filas(
        ("tolerancia_ingreso_min", 15, "sede", "S1"),
        ("tolerancia_ingreso_min", 30, "empleado", "E1"),
    ))
    r = svc.resolver(sede_id="S1", empleado_id="E1")
    assert r["tolerancia_ingreso_min"] == 30
    assert r.origen_de("tolerancia_ingreso_min") == "empleado"


def test_orden_completo_de_precedencia(monkeypatch):
    """empleado > horario > tipo_contrato > area > sede > empresa > default"""
    monkeypatch.setattr(svc, "_leer_filas", lambda: _filas(
        ("tolerancia_ingreso_min", 1, "empresa", None),
        ("tolerancia_ingreso_min", 2, "sede", "S1"),
        ("tolerancia_ingreso_min", 3, "area", "A1"),
        ("tolerancia_ingreso_min", 4, "tipo_contrato", "termino_fijo"),
        ("tolerancia_ingreso_min", 5, "horario", "H1"),
        ("tolerancia_ingreso_min", 6, "empleado", "E1"),
    ))
    ctx = dict(sede_id="S1", area_id="A1", tipo_contrato="termino_fijo",
               horario_id="H1", empleado_id="E1")

    assert svc.resolver(**ctx)["tolerancia_ingreso_min"] == 6
    ctx.pop("empleado_id");     assert svc.resolver(**ctx)["tolerancia_ingreso_min"] == 5
    ctx.pop("horario_id");      assert svc.resolver(**ctx)["tolerancia_ingreso_min"] == 4
    ctx.pop("tipo_contrato");   assert svc.resolver(**ctx)["tolerancia_ingreso_min"] == 3
    ctx.pop("area_id");         assert svc.resolver(**ctx)["tolerancia_ingreso_min"] == 2
    ctx.pop("sede_id");         assert svc.resolver(**ctx)["tolerancia_ingreso_min"] == 1


def test_regla_de_otra_sede_no_aplica(monkeypatch):
    monkeypatch.setattr(svc, "_leer_filas",
                        lambda: _filas(("tolerancia_ingreso_min", 99, "sede", "OTRA")))
    r = svc.resolver(sede_id="S1")
    assert r["tolerancia_ingreso_min"] == 5      # el default, no el de la otra sede


def test_solo_sobrescribe_la_clave_configurada(monkeypatch):
    """Configurar una regla no debe borrar el resto."""
    monkeypatch.setattr(svc, "_leer_filas",
                        lambda: _filas(("tolerancia_ingreso_min", 20, "empresa", None)))
    r = svc.resolver()
    assert r["tolerancia_ingreso_min"] == 20
    assert r["max_minutos_compensables"] == 480
    assert r["requiere_revision_humana_nomina"] is True


def test_desempaqueta_jsonb_envuelto(monkeypatch):
    """La columna es JSONB: puede llegar escalar o como {"valor": x}."""
    monkeypatch.setattr(svc, "_leer_filas",
                        lambda: _filas(("tolerancia_ingreso_min", {"valor": 12},
                                        "empresa", None)))
    assert svc.resolver()["tolerancia_ingreso_min"] == 12


# ── Validación al escribir ───────────────────────────────────────────────────

def test_rechaza_regla_desconocida():
    with pytest.raises(ValueError, match="regla_desconocida"):
        svc.establecer(clave="regla_inventada", valor=1)


def test_rechaza_ambito_invalido():
    with pytest.raises(ValueError, match="ambito_invalido"):
        svc.establecer(clave="tolerancia_ingreso_min", valor=5, ambito="galaxia")


def test_ambito_no_empresa_exige_id():
    with pytest.raises(ValueError, match="ambito_id_requerido"):
        svc.establecer(clave="tolerancia_ingreso_min", valor=5, ambito="sede")


def test_excepcion_individual_exige_motivo():
    """Una regla a nivel empleado es una excepción y debe quedar justificada.

    La base de datos también lo obliga con un CHECK; aquí se valida antes para
    dar un error legible en vez de un 500 de Postgres.
    """
    with pytest.raises(ValueError, match="motivo_requerido"):
        svc.establecer(clave="tolerancia_ingreso_min", valor=30,
                       ambito="empleado", ambito_id="E1")


def test_valida_tipo_booleano():
    with pytest.raises(ValueError, match="espera_booleano"):
        svc.establecer(clave="banco_positivo_automatico", valor="si")


def test_valida_tipo_entero():
    with pytest.raises(ValueError, match="espera_entero"):
        svc.establecer(clave="tolerancia_ingreso_min", valor="cinco")


def test_booleano_no_pasa_como_entero():
    """En Python True == 1. Sin el chequeo explícito, `valor=True` colaría
    como tolerancia de 1 minuto."""
    with pytest.raises(ValueError, match="espera_entero"):
        svc.establecer(clave="tolerancia_ingreso_min", valor=True)


# ── Listado para la UI ───────────────────────────────────────────────────────

def test_listado_incluye_defaults_no_configurados(monkeypatch):
    monkeypatch.setattr(svc, "_leer_filas", lambda: [])
    filas = svc.listar()
    claves = {f["clave"] for f in filas}
    assert claves == set(svc.REGLAS_DEFECTO)
    assert all(f["es_default"] for f in filas)


def test_listado_marca_lo_configurado(monkeypatch):
    monkeypatch.setattr(svc, "_leer_filas",
                        lambda: _filas(("tolerancia_ingreso_min", 20, "empresa", None)))
    filas = {f["clave"]: f for f in svc.listar()}
    assert filas["tolerancia_ingreso_min"]["es_default"] is False
    assert filas["tolerancia_ingreso_min"]["valor"] == 20
    assert filas["max_minutos_compensables"]["es_default"] is True
