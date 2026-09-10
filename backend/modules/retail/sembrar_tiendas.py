"""Las tiendas reales del POS: Florida (dos cajas) y Arrayanes (una).

POR QUÉ EXISTE. La base de producción se migró el 2026-08-29 y quedó sin
tienda, sin caja, sin ubicación y sin efectivo. Las migraciones 0016 y 0018
traen los datos reales de Florida, pero como UPDATE: sobre una base nueva no
tocan ninguna fila (ver `docs/retail-pos/despliegue.md`). Y `semilla.py` hace
`TRUNCATE` y sólo corre en local. Faltaba esto.

    python -m backend.modules.retail.sembrar_tiendas            # ensayo
    python -m backend.modules.retail.sembrar_tiendas --aplicar  # escribe

NO PISA NADA. Cada fila entra con `ON CONFLICT DO NOTHING`: si ya existe, se
deja como está. Alguien pudo haberla corregido a mano —subir el
`consecutivo_externo` antes de una jornada es justo eso— y volver a correr
esto no puede deshacerlo.

DE DÓNDE SALE CADA DATO
  · Florida: la tirilla física de Siigo del 14/08/2026 (migraciones 0016 y
    0018, `docs/retail-pos/tirilla-real-siigo.md`).
  · Bodegas, centros de costo y formas de pago: los ids de la API de Siigo que
    ya usa Postventa (`backend/services/tiendas.py`).
  · Arrayanes: sólo lo que se sabe. Sin dirección ni teléfono —la tirilla sale
    sin ellos, que es mejor que salir con los de Florida— y sin resolución.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from typing import List

from sqlalchemy import create_engine, text

from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
    normalizar_url,
)

__all__ = ["sembrar", "TIENDAS", "CAJAS", "UBICACIONES", "MEDIOS"]

_EMPRESA = {
    "razon_social": "DIRTY JEANS S.A.S.",
    "nit": "901680460-1",
    "actividad_economica": "4782",
    "regimen_iva": "Responsable de IVA",
}

TIENDAS = [
    {
        **_EMPRESA,
        "id": "florida", "nombre": "Florida",
        "siigo_bodega_id": 48, "siigo_centro_costo_id": 774,
        "direccion": "CALLE 71 65 150 SEGUNDA ETAPA LC 221",
        "telefono": "3122851520",
        # «prefijo FL desde el número 1 al 10000», aprobada el 2026-04-10.
        "autorizacion_numero": "18764108303738",
        "autorizacion_desde": 1, "autorizacion_hasta": 10000,
        "autorizacion_aprobada": date(2026, 4, 10), "autorizacion_meses": 24,
        # La tirilla de la foto era la FL-1536: el POS arranca en la 1537.
        "consecutivo_externo": 1536,
    },
    {
        **_EMPRESA,
        "id": "arrayanes", "nombre": "Arrayanes",
        "siigo_bodega_id": 37, "siigo_centro_costo_id": 677,
        "direccion": None, "telefono": None,
        "autorizacion_numero": None,
        "autorizacion_desde": None, "autorizacion_hasta": None,
        "autorizacion_aprobada": None, "autorizacion_meses": None,
        # FV-6-10703 es una factura real de Arrayanes: de ahí para abajo, los
        # números ya están gastados. Es un PISO seguro, no el número actual —
        # hay que subirlo con el de la última tirilla antes de la primera venta.
        "consecutivo_externo": 10703,
    },
]

#  Un prefijo POR TIENDA: las dos cajas de Florida numeran del mismo rango
#  (`repo_consecutivos` bloquea por prefijo, no por caja).
CAJAS = [
    {"id": "florida_caja1", "tienda_id": "florida", "nombre": "Caja 1",
     "prefijo_factura": "FL"},
    {"id": "florida_caja2", "tienda_id": "florida", "nombre": "Caja 2",
     "prefijo_factura": "FL"},
    {"id": "arrayanes_caja1", "tienda_id": "arrayanes", "nombre": "Caja 1",
     "prefijo_factura": "FV-6"},
]

UBICACIONES = [
    {"id": "tienda:florida", "tipo": "tienda", "nombre": "Florida",
     "tienda_id": "florida", "siigo_bodega_id": 48},
    {"id": "tienda:arrayanes", "tipo": "tienda", "nombre": "Arrayanes",
     "tienda_id": "arrayanes", "siigo_bodega_id": 37},
]

#  El efectivo y el datáfono son DE CADA TIENDA: en Siigo son cuentas
#  distintas. La transferencia no tiene forma de pago a propósito (0019: el
#  único candidato es la cuenta bancaria, no un medio de cobro) — se cobra
#  igual y su factura queda pendiente.
MEDIOS = [
    {"id": "efectivo_florida", "nombre": "Efectivo", "tipo": "efectivo",
     "tienda_id": "florida", "siigo_forma_pago_id": 12243,
     "permite_vuelto": True, "orden": 0},
    {"id": "datafono_florida", "nombre": "Datáfono", "tipo": "tarjeta",
     "tienda_id": "florida", "siigo_forma_pago_id": 12244,
     "permite_vuelto": False, "orden": 1},
    {"id": "efectivo_arrayanes", "nombre": "Efectivo", "tipo": "efectivo",
     "tienda_id": "arrayanes", "siigo_forma_pago_id": 8282,
     "permite_vuelto": True, "orden": 0},
    {"id": "datafono_arrayanes", "nombre": "Datáfono", "tipo": "tarjeta",
     "tienda_id": "arrayanes", "siigo_forma_pago_id": 8987,
     "permite_vuelto": False, "orden": 1},
    {"id": "transferencia", "nombre": "Transferencia", "tipo": "transferencia",
     "tienda_id": None, "siigo_forma_pago_id": None,
     "permite_vuelto": False, "orden": 2},
]


def _insertar(c, tabla: str, filas: List[dict]) -> List[str]:
    """Inserta lo que falta y devuelve los ids que SÍ entraron."""
    nuevos = []
    for f in filas:
        cols = ", ".join(f)
        vals = ", ".join(f":{k}" for k in f)
        r = c.execute(text(
            f"INSERT INTO retail.{tabla} ({cols}) VALUES ({vals}) "
            f"ON CONFLICT (id) DO NOTHING RETURNING id"), f).scalar()
        if r is not None:
            nuevos.append(r)
    return nuevos


def sembrar(url: str, *, aplicar: bool = False) -> dict:
    """Crea lo que falte. En ensayo corre TODO y al final deshace.

    El ensayo no es una simulación: los INSERT se ejecutan de verdad dentro de
    una transacción que se revierte. Así un error de columnas o de llaves sale
    en el ensayo y no a mitad de la aplicación.
    """
    motor = create_engine(normalizar_url(url), future=True)
    try:
        with motor.connect() as c:
            tx = c.begin()
            r = {
                "tiendas": _insertar(c, "tiendas", TIENDAS),
                "cajas": _insertar(c, "cajas", CAJAS),
                "ubicaciones": _insertar(c, "ubicaciones", UBICACIONES),
                "medios_pago": _insertar(c, "medios_pago", MEDIOS),
            }
            if aplicar:
                tx.commit()
            else:
                tx.rollback()
    finally:
        motor.dispose()
    r["aplicado"] = aplicar
    return r


def main(argv: List[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    url = os.environ.get("RETAIL_DATABASE_URL", "").strip()
    if not url:
        print("Falta RETAIL_DATABASE_URL.", file=sys.stderr)
        return 2
    aplicar = "--aplicar" in argv

    r = sembrar(url, aplicar=aplicar)
    for tabla in ("tiendas", "cajas", "ubicaciones", "medios_pago"):
        nuevos = r[tabla]
        print(f"  {tabla:<12} {len(nuevos)} nuevas"
              + (f": {', '.join(nuevos)}" if nuevos else " (ya estaban)"))
    if r["aplicado"]:
        print("\n  APLICADO.\n")
    else:
        print("\n  ENSAYO — no se escribió nada. Vuelve a correrlo con "
              "--aplicar.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
