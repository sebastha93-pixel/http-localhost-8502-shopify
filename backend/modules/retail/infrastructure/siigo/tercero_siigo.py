"""Armar el «tercero» de Siigo para una clienta que el POS registró. Puro.

Sin esto, la venta a una clienta nueva se quedaba esperando: Siigo no factura
a una identificación que no conoce, y facturarla a nombre de otra persona
—consumidor final incluido— sería un documento fiscal con el comprador
equivocado.

LAS REGLAS NO SON DE LA DOCUMENTACIÓN: SON DE SONDAS REALES. Salen del Portal
Mayoristas (`lib/siigo/clientes.ts`), que las midió contra `POST /customers`
de esta misma cuenta el 2026-08-02 y el 2026-08-18:

  · Obligatorios: `person_type`, `id_type`, `identification`, `name`.
  · `name` es una lista atada al tipo de persona: una PERSONA lleva
    EXACTAMENTE dos elementos, ninguno vacío; una EMPRESA, exactamente uno.
  · El teléfono son los 10 dígitos locales. Con «+57» Siigo rechaza al
    cliente entero (`invalid_type`), y con él la factura.
  · La ciudad va por CÓDIGOS, y un código que no exista tumba la creación.
    Por eso se BUSCA en una tabla de códigos que Siigo ya aceptó
    (`ciudades_dane.py`) y, si no aparece o es ambigua, SE OMITE: la calle
    sola es un cuerpo válido.

NUNCA SE ACTUALIZA un cliente que ya existe en Siigo. Esos datos los puso
contabilidad; pisarlos con lo que se escribió de afán en un mostrador es
cambiar el dato bueno por el malo.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from backend.modules.retail.infrastructure.siigo.ciudades_dane import CIUDADES_SIIGO

__all__ = ["cuerpo_de_cliente", "ClienteIncompleto", "telefono_para_siigo",
           "ciudad_para_siigo"]

#  El código de tipo de documento que usa Siigo (catálogo DIAN).
_ID_TYPE = {"CC": "13", "NIT": "31", "CE": "22", "PP": "41", "TI": "12"}

#  «No responsable de IVA»: lo que llevan los clientes de la cuenta.
_RESPONSABILIDAD = "R-99-PN"


class ClienteIncompleto(Exception):
    """A la clienta le falta algo que no se puede inventar en una factura."""


def _norm(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


_ALIAS = {"BOGOTA D C": "BOGOTA", "BOGOTA DC": "BOGOTA",
          "SANTA FE DE BOGOTA": "BOGOTA"}

#  El POS guarda la ciudad como texto y SIN departamento. Sólo sirve el nombre
#  cuando hay UN municipio que se llame así: «Armenia» puede ser la de Quindío
#  o la de Antioquia, y elegir es poner una ciudad falsa en la factura.
_POR_NOMBRE: dict = {}
for _clave, _cod in CIUDADES_SIIGO.items():
    _POR_NOMBRE.setdefault(_clave.split("|", 1)[1], []).append(_cod)


def ciudad_para_siigo(ciudad: Optional[str]) -> Optional[dict]:
    """`None` si no se reconoce o si el nombre lo comparten dos municipios."""
    nombre = _norm(ciudad)
    # «Itagüí, Antioquia» → se mira primero lo de antes de la coma.
    if not nombre:
        return None
    candidatos = [nombre]
    if ciudad and "," in ciudad:
        candidatos.insert(0, _norm(ciudad.split(",", 1)[0]))
    for c in candidatos:
        c = _ALIAS.get(c, c)
        codigos = _POR_NOMBRE.get(c) or []
        if len(codigos) == 1:
            return {"country_code": "Co", "state_code": codigos[0][0],
                    "city_code": codigos[0][1]}
    return None


def telefono_para_siigo(telefono: Optional[str]) -> Optional[str]:
    digitos = re.sub(r"\D", "", telefono or "")
    if len(digitos) == 12 and digitos.startswith("57"):
        digitos = digitos[2:]
    return digitos if len(digitos) == 10 else None


def cuerpo_de_cliente(c: dict) -> dict:
    """El cuerpo de `POST /customers`. `c` son las columnas de `clientes`."""
    tipo = (c.get("tipo_documento") or "CC").strip().upper()
    if tipo not in _ID_TYPE:
        raise ClienteIncompleto(f"tipo de documento «{tipo}» sin código en Siigo")
    # TAL CUAL está guardada: es la misma cadena con la que la factura la va
    # a buscar. Limpiarla aquí crearía en Siigo a alguien que luego no aparece.
    identificacion = (c.get("numero_documento") or "").strip()
    if not identificacion:
        raise ClienteIncompleto("la clienta no tiene número de documento")

    nombre = (c.get("nombre") or "").strip()
    apellido = (c.get("apellido") or "").strip()

    cuerpo: dict = {
        "type": "Customer",
        "id_type": _ID_TYPE[tipo],
        "identification": identificacion,
        "branch_office": 0,
        "active": True,
        "vat_responsible": False,
        "fiscal_responsibilities": [{"code": _RESPONSABILIDAD}],
    }

    calle = (c.get("direccion") or "").strip()
    if calle:
        direccion = {"address": calle[:256]}
        ciudad = ciudad_para_siigo(c.get("ciudad"))
        if ciudad:
            direccion["city"] = ciudad
        cuerpo["address"] = direccion

    telefono = telefono_para_siigo(c.get("telefono"))
    if telefono:
        cuerpo["phones"] = [{"number": telefono}]

    correo = (c.get("correo") or "").strip()

    if tipo == "NIT":
        razon = " ".join(p for p in (nombre, apellido) if p)
        if not razon:
            raise ClienteIncompleto("la empresa no tiene razón social")
        cuerpo["person_type"] = "Company"
        cuerpo["name"] = [razon]
        # El dígito de verificación NO se manda: Siigo lo calcula, y el cuerpo
        # verificado contra la cuenta es sin él.
        if correo:
            # El contacto es por donde llega la factura electrónica.
            cuerpo["contacts"] = [{"first_name": razon[:50],
                                   "last_name": razon[:50], "email": correo}]
        return cuerpo

    if not apellido:
        # Guardada con todo en «nombre»: se parte por el primer espacio.
        partes = nombre.split()
        if len(partes) >= 2:
            nombre, apellido = partes[0], " ".join(partes[1:])
    if not nombre or not apellido:
        # NO se duplica ni se rellena con un punto. Una factura lleva el
        # nombre real de quien compra, y «Juana Juana» no lo es. Completarlo
        # son diez segundos; una factura a un nombre inventado no se arregla.
        raise ClienteIncompleto(
            "la clienta está guardada con un solo nombre: Siigo exige nombre "
            "y apellido. Hay que completarlo en su ficha.")

    cuerpo["person_type"] = "Person"
    cuerpo["name"] = [nombre, apellido]
    contacto = {"first_name": nombre, "last_name": apellido}
    if correo:
        contacto["email"] = correo
    cuerpo["contacts"] = [contacto]
    return cuerpo
