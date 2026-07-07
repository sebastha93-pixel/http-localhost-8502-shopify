from backend.services import postventa_logic as L


def test_transicion_valida_flujo_feliz():
    assert L.transicion_valida("creado", "pendiente_validacion") is True
    assert L.transicion_valida("pendiente_validacion", "aprobado") is True
    assert L.transicion_valida("aprobado", "nota_credito_emitida") is True


def test_transicion_invalida_salta_pasos():
    assert L.transicion_valida("creado", "cerrado") is True  # cierre manual permitido
    assert L.transicion_valida("creado", "factura_emitida") is False


def test_no_se_puede_salir_de_estado_terminal():
    assert L.transicion_valida("rechazado", "aprobado") is False
    assert L.transicion_valida("cerrado", "creado") is False


def test_cualquiera_puede_ir_a_cerrado():
    assert L.transicion_valida("escalado", "cerrado") is True
    assert L.transicion_valida("aprobado", "cerrado") is True


def test_validar_tipo():
    assert L.validar_tipo("cambio_talla") is True
    assert L.validar_tipo("garantia") is True
    assert L.validar_tipo("inexistente") is False


def test_validar_motivo():
    assert L.validar_motivo("talla_pequena") is True
    assert L.validar_motivo("error_asesoria") is True
    assert L.validar_motivo("no_existe") is False


def test_validar_prioridad():
    assert L.validar_prioridad("alta") is True
    assert L.validar_prioridad("urgentisima") is False


def test_calcular_diferencia_reemplazo_mas_caro():
    # nueva ref cuesta más -> cobra (positivo)
    assert L.calcular_diferencia(100000.0, 130000.0) == 30000.0


def test_calcular_diferencia_reemplazo_mas_barato():
    # nueva ref cuesta menos -> devuelve (negativo)
    assert L.calcular_diferencia(100000.0, 80000.0) == -20000.0


def test_calcular_diferencia_reembolso_devuelve_todo():
    # sin reemplazo (reembolso/bono) -> devuelve todo el original
    assert L.calcular_diferencia(100000.0, None) == -100000.0


def test_formato_case_number():
    assert L.formato_case_number(2026, 1) == "PV-2026-0001"
    assert L.formato_case_number(2026, 45) == "PV-2026-0045"
    assert L.formato_case_number(2026, 1234) == "PV-2026-1234"
