"""El «tercero» que se le crea a Siigo para una clienta nueva del POS.

Las reglas no salen de la documentación: las midió el Portal Mayoristas contra
`POST /customers` de esta cuenta. Aquí se fija que el POS las respete.
"""
import pytest

from backend.modules.retail.infrastructure.siigo.tercero_siigo import (
    ClienteIncompleto,
    ciudad_para_siigo,
    cuerpo_de_cliente,
    telefono_para_siigo,
)

LAURA = {"tipo_documento": "CC", "numero_documento": "1037000111",
         "nombre": "Laura", "apellido": "Gómez", "telefono": "3001112233",
         "correo": "l@c.com", "ciudad": "Medellín", "direccion": "CL 1 # 2-3"}


def test_una_persona_lleva_EXACTAMENTE_dos_nombres():
    c = cuerpo_de_cliente(LAURA)
    assert c["person_type"] == "Person" and c["name"] == ["Laura", "Gómez"]
    assert c["type"] == "Customer" and c["id_type"] == "13"


def test_si_todo_quedo_en_el_nombre_se_parte_por_el_primer_espacio():
    c = cuerpo_de_cliente({**LAURA, "nombre": "Laura Gómez Ríos", "apellido": ""})
    assert c["name"] == ["Laura", "Gómez Ríos"]


def test_un_solo_nombre_NO_se_duplica_ni_se_rellena():
    with pytest.raises(ClienteIncompleto, match="nombre y apellido"):
        cuerpo_de_cliente({**LAURA, "apellido": ""})


def test_una_empresa_lleva_UN_solo_nombre_y_su_tipo():
    c = cuerpo_de_cliente({**LAURA, "tipo_documento": "NIT",
                           "numero_documento": "900123456",
                           "nombre": "Moda Sur S.A.S.", "apellido": ""})
    assert c["person_type"] == "Company" and c["id_type"] == "31"
    assert c["name"] == ["Moda Sur S.A.S."]


def test_sin_documento_no_hay_a_quien_facturar():
    with pytest.raises(ClienteIncompleto):
        cuerpo_de_cliente({**LAURA, "numero_documento": " "})


@pytest.mark.parametrize("crudo, limpio", [
    ("+573001112233", "3001112233"), ("300 111 2233", "3001112233"),
    ("573001112233", "3001112233"), ("6044441122", "6044441122"),
    ("4441122", None), ("", None), (None, None)])
def test_el_telefono_son_diez_digitos_o_no_va(crudo, limpio):
    """Con «+57» Siigo rechaza al cliente entero, y con él la factura."""
    assert telefono_para_siigo(crudo) == limpio


def test_sin_telefono_valido_el_campo_se_omite():
    assert "phones" not in cuerpo_de_cliente({**LAURA, "telefono": "444"})


@pytest.mark.parametrize("texto, codigo", [
    ("Medellín", "05001"), ("ITAGUI", "05360"), ("itagüí, antioquia", "05360"),
    ("Bogotá D.C.", "11001"), ("Envigado", "05266")])
def test_la_ciudad_se_BUSCA_en_codigos_que_siigo_ya_acepto(texto, codigo):
    assert ciudad_para_siigo(texto)["city_code"] == codigo


@pytest.mark.parametrize("texto", ["Armenia", "Ciudad Gótica", "", None])
def test_la_ciudad_ambigua_o_desconocida_se_omite(texto):
    """«Armenia» es la de Quindío o la de Antioquia. Elegir es poner una
    ciudad falsa; un código inventado tumba la creación entera."""
    assert ciudad_para_siigo(texto) is None


def test_sin_ciudad_reconocida_va_la_calle_sola():
    c = cuerpo_de_cliente({**LAURA, "ciudad": "Armenia"})
    assert c["address"] == {"address": "CL 1 # 2-3"}


def test_sin_direccion_no_se_manda_el_bloque():
    assert "address" not in cuerpo_de_cliente({**LAURA, "direccion": None})
