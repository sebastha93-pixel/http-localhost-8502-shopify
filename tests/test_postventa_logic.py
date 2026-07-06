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
