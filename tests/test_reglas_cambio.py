"""Reglas del negocio que evitan pasos y evitan cambios que no proceden.

1. APROBACION SOLO PARA GARANTIA. Un cambio de talla no necesita que nadie
   lo autorice: la clienta esta ahi con la prenda. Pedir aprobacion en cada
   caso es un paso vacio que solo demora a la asesora.

2. VENTANA DE 30 DIAS. Pasado ese plazo la prenda ya no se cambia. Hoy eso
   se controla "de memoria" y se descubre tarde, cuando ya se emitio la nota
   credito.
"""
import pytest
from backend.services import postventa_logic as L


# ── 1. Que necesita aprobacion ─────────────────────────────────────────────

def test_un_cambio_de_talla_no_necesita_aprobacion():
    assert L.requiere_aprobacion("cambio_talla") is False


def test_un_cambio_de_referencia_tampoco():
    assert L.requiere_aprobacion("cambio_ref") is False


def test_la_garantia_si_necesita_aprobacion():
    """Alguien tiene que mirar la prenda y decidir si el defecto aplica."""
    assert L.requiere_aprobacion("garantia") is True


def test_devolver_plata_necesita_aprobacion():
    """Reembolso y bono sacan plata: no se auto-aprueban."""
    assert L.requiere_aprobacion("reembolso") is True
    assert L.requiere_aprobacion("bono") is True


def test_un_tipo_desconocido_pide_aprobacion():
    """Ante la duda, que lo mire un humano."""
    assert L.requiere_aprobacion("lo_que_sea") is True


def test_el_estado_inicial_depende_del_tipo():
    assert L.estado_inicial("cambio_talla") == "aprobado"
    assert L.estado_inicial("garantia") == "creado"


# ── 2. Ventana de 30 dias ──────────────────────────────────────────────────

def test_una_compra_de_ayer_se_puede_cambiar():
    assert L.dentro_de_ventana("2026-07-29", hoy="2026-07-30") is True


def test_justo_en_el_dia_30_todavia_se_puede():
    assert L.dentro_de_ventana("2026-06-30", hoy="2026-07-30") is True


def test_el_dia_31_ya_no():
    assert L.dentro_de_ventana("2026-06-29", hoy="2026-07-30") is False


def test_dice_cuantos_dias_lleva():
    assert L.dias_desde("2026-06-29", hoy="2026-07-30") == 31


def test_aguanta_la_fecha_con_hora_de_siigo():
    """Siigo a veces manda '2026-07-29T10:30:00Z'."""
    assert L.dentro_de_ventana("2026-07-29T10:30:00Z", hoy="2026-07-30") is True


def test_sin_fecha_no_se_afirma_que_este_en_ventana():
    """Sin fecha no se puede decir que si: se bloquea y se avisa."""
    assert L.dentro_de_ventana(None, hoy="2026-07-30") is False
    assert L.dentro_de_ventana("", hoy="2026-07-30") is False


def test_una_fecha_ilegible_no_pasa():
    assert L.dentro_de_ventana("ayer por la tarde", hoy="2026-07-30") is False


def test_el_plazo_se_cambia_por_entorno(monkeypatch):
    """Otra marca puede tener 15 o 60 dias: es politica, no codigo."""
    monkeypatch.setenv("POSTVENTA_DIAS_CAMBIO", "15")
    assert L.dentro_de_ventana("2026-07-10", hoy="2026-07-30") is False
    assert L.dentro_de_ventana("2026-07-20", hoy="2026-07-30") is True


def test_un_plazo_basura_cae_al_default(monkeypatch):
    monkeypatch.setenv("POSTVENTA_DIAS_CAMBIO", "muchos")
    assert L.dias_de_cambio() == 30


def test_el_motivo_explica_el_plazo():
    m = L.motivo_fuera_de_ventana("2026-06-01", hoy="2026-07-30")
    assert "59" in m and "30" in m


# ── El bloqueo de verdad: antes de emitir la nota credito ──────────────────

def test_no_se_emite_nc_de_una_compra_vencida(monkeypatch):
    """La lista ya lo avisa, pero un caso viejo o creado a mano puede llegar
    igual hasta aqui. Este es el ultimo punto donde se puede parar sin dejar
    un documento fiscal que tocara anular."""
    from backend.services import postventa_fiscal as PF
    monkeypatch.setattr(PF, "_caso", lambda cid: {
        "id": "c1", "tienda": None, "siigo_invoice_id": "f1",
        "shopify_order_name": ""})
    monkeypatch.setattr(PF, "_items_caso", lambda cid: [{"original_sku": "A-1"}])
    monkeypatch.setattr(PF, "_fiscal_existente", lambda cid, k: None)

    class _Emisor:
        def buscar_factura_original(self, **k):
            return {"id": "f1", "name": "FV-1-1", "date": "2026-01-01",
                    "stamp": {"status": "Accepted"}, "items": []}
    monkeypatch.setattr(PF, "obtener_emisor", lambda: _Emisor())

    with pytest.raises(ValueError) as e:
        PF.preview_nota_credito("c1")
    assert "plazo" in str(e.value).lower()
