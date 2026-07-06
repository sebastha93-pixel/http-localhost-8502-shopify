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
