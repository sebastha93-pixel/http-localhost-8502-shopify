"""
backend.services.postventa_cliente — Buscar las compras de una clienta.

La clienta llega a la tienda (o escribe) y casi nunca recuerda el número de
pedido. Pero siempre tiene la cédula. Siigo indexa las facturas por
`customer_identification`, así que con la cédula se traen TODAS sus compras
—online y de tienda— y la asesora solo elige cuál viene a cambiar.

Solo lectura.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.services import siigo
from backend.services import fiscal_logic as F
from backend.services import tiendas
from backend.services import postventa_logic as L

log = logging.getLogger("postventa_cliente")

# Prefijo de factura → dónde se hizo la compra.
_CANAL_POR_DOCUMENTO: dict[int, str] = {
    F.FV_ONLINE_ID: "online",
}


def _canal_de(document_id: Optional[int], nombre: str) -> dict:
    """De qué canal es la factura: online o qué punto de venta."""
    if document_id == F.FV_ONLINE_ID:
        return {"canal": "online", "etiqueta": "Tienda online"}
    for clave, t in ((c, tiendas.obtener(c)) for c in
                     [p["clave"] for p in tiendas.listar()]):
        if t and t.get("documento_factura_id") == document_id:
            return {"canal": clave, "etiqueta": t.get("nombre")}
    # Prefijo desconocido: se muestra igual, sin adivinar el punto.
    prefijo = nombre.rsplit("-", 1)[0] if "-" in nombre else nombre
    return {"canal": None, "etiqueta": f"Otro ({prefijo})"}


def _telefono_de(p) -> str:
    """Siigo guarda el teléfono como {indicative, number, extension} o plano."""
    if isinstance(p, dict):
        return str(p.get("number") or "").strip()
    return str(p or "").strip()


def datos_de_cliente(c: dict) -> dict:
    """Nombre, email y teléfono de un cliente de Siigo.

    `name` es una LISTA: [nombre, apellido] si es persona, [razón social] si es
    empresa. Si viene vacía se arma del primer contacto, que es lo que pasa con
    los clientes creados desde la caja de la tienda.
    """
    c = c if isinstance(c, dict) else {}
    crudo = c.get("name")
    partes = crudo if isinstance(crudo, list) else [crudo]
    nombre = " ".join(str(p).strip() for p in partes if p).strip()

    contactos = [x for x in (c.get("contacts") or []) if isinstance(x, dict)]
    contacto = contactos[0] if contactos else {}
    if not nombre:
        nombre = " ".join(str(contacto.get(k) or "").strip()
                          for k in ("first_name", "last_name")).strip()

    telefonos = [x for x in (c.get("phones") or []) if x]
    return {
        "nombre": nombre,
        "email": str(contacto.get("email") or "").strip(),
        "telefono": (_telefono_de(contacto.get("phone"))
                     or _telefono_de(telefonos[0] if telefonos else None)),
    }


def _traer_cliente(cedula: str) -> dict:
    """Datos de contacto de la clienta. Secundario: si falla, se sigue sin
    ellos — las compras son lo que de verdad importa."""
    try:
        r = siigo.siigo_get("/customers", {"identification": cedula})
    except Exception as e:  # noqa: BLE001
        log.warning("no se pudo traer el cliente %s: %s", cedula, e)
        return {"nombre": "", "email": "", "telefono": ""}
    filas = r.get("results", []) if isinstance(r, dict) else []
    return datos_de_cliente(filas[0] if filas else {})


def _fecha_de(inv: dict) -> Optional[str]:
    """Fecha de la compra. El listado de Siigo no siempre trae `date`; cuando
    falta, la de creación sirve para que la asesora pueda distinguir entre
    varias compras de la misma clienta."""
    for v in (inv.get("date"), (inv.get("metadata") or {}).get("created"),
              inv.get("created")):
        if v:
            return str(v)
    return None


def compras_por_cedula(cedula: str, *, limite: int = 12) -> dict:
    """Compras de la clienta, de la más reciente a la más antigua.

    Cada una trae sus prendas y si ya se le puede hacer nota crédito (la DIAN
    debe haber aceptado la factura).
    """
    cedula = (cedula or "").strip()
    if not cedula:
        return {"_error": "sin_cedula"}
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    try:
        data = siigo.siigo_get("/invoices", {"customer_identification": cedula,
                                             "page_size": max(1, min(limite, 50)),
                                             "page": 1})
    except Exception as e:  # noqa: BLE001
        return {"_error": "siigo_error", "detalle": str(e)[:250]}

    filas = data.get("results", []) if isinstance(data, dict) else []
    compras = []
    for inv in filas:
        if not isinstance(inv, dict):
            continue
        nombre = str(inv.get("name") or "")
        doc_id = (inv.get("document") or {}).get("id")
        canal = _canal_de(doc_id, nombre)
        # Dos condiciones distintas y ambas obligatorias: que la DIAN haya
        # aceptado la factura (si no, Siigo rechaza la NC) y que la compra
        # siga en plazo de cambio. Que la DIAN la acepte no la vuelve eterna.
        fecha = _fecha_de(inv)
        en_plazo = L.dentro_de_ventana(fecha)
        aceptada = F.factura_aceptada_dian(inv) and en_plazo
        compras.append({
            "factura_id": inv.get("id"),
            "factura": nombre,
            "fecha": _fecha_de(inv),
            "total": inv.get("total"),
            "canal": canal["canal"],
            "donde": canal["etiqueta"],
            # El nº de pedido solo existe en las ventas online.
            "pedido": (lambda n: f"#{n}" if n else None)(
                F.extraer_numero_pedido(inv.get("observations") or "")),
            "acreditable": aceptada,
            "motivo_no_acreditable": (
                None if aceptada
                else (L.motivo_fuera_de_ventana(fecha) if not en_plazo
                      else F.motivo_factura_no_apta(inv))),
            "dias": L.dias_desde(fecha),
            "prendas": [{"sku": it.get("code"),
                         "descripcion": it.get("description"),
                         "precio": it.get("price")}
                        for it in (inv.get("items") or [])],
        })

    compras.sort(key=lambda c: c.get("fecha") or "", reverse=True)
    ref = ((filas[0].get("customer") or {}) if filas else {})
    return {
        "cedula": cedula,
        # La factura solo trae la cédula; nombre/email/teléfono se piden aparte
        # para que la asesora no tenga que digitarlos.
        "cliente": {**_traer_cliente(cedula),
                    "identification": ref.get("identification") or cedula,
                    "branch_office": ref.get("branch_office", 0)},
        "total": len(compras),
        "acreditables": sum(1 for c in compras if c["acreditable"]),
        "compras": compras,
    }
