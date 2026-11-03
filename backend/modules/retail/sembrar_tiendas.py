"""Las tiendas reales del POS: Florida (dos cajas), Arrayanes (una) y la
Feria (una, desde un iPad; 2026-11-03).

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

__all__ = ["sembrar", "enlazar_feria", "TIENDAS", "CAJAS", "UBICACIONES",
           "MEDIOS"]

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
        # «Nota Crédito Electrónica», el que usa Postventa. Ver migración 0026.
        "siigo_nc_documento_id": 11817,
        "direccion": "CALLE 71 65 150 SEGUNDA ETAPA LC 221",
        "telefono": "3122851520",
        # «prefijo FL desde el número 1 al 10000», aprobada el 2026-04-10.
        "autorizacion_numero": "18764108303738", "autorizacion_prefijo": "FL",
        "autorizacion_desde": 1, "autorizacion_hasta": 10000,
        "autorizacion_aprobada": date(2026, 4, 10), "autorizacion_meses": 24,
        # La tirilla de la foto era la FL-1536: el POS arranca en la 1537.
        "consecutivo_externo": 1536,
    },
    {
        **_EMPRESA,
        "id": "arrayanes", "nombre": "Arrayanes",
        "siigo_bodega_id": 37, "siigo_centro_costo_id": 677,
        # «Nota Crédito Electrónica», el que usa Postventa. Ver migración 0026.
        "siigo_nc_documento_id": 11817,
        "direccion": "CR 50A 36 90 LC 231, Itagüí",
        "telefono": "3005654971",
        # De la factura TARR-11389 del 30/09/2026. OJO: aprobada el
        # 2024-11-20 con vigencia 24 meses, o sea que VENCE EL 2026-11-20.
        "autorizacion_numero": "18764083761292", "autorizacion_prefijo": "TARR",
        "autorizacion_desde": 1, "autorizacion_hasta": 1000000,
        "autorizacion_aprobada": date(2024, 11, 20), "autorizacion_meses": 24,
        # El último número que Siigo POS ya emitió en Arrayanes.
        "consecutivo_externo": 11389,
    },
    {
        # LA FERIA (Sebastián, 2026-11-03): un punto de venta propio, atendido
        # desde un iPad. Su inventario es la bodega «Feria» de Siigo, que crea
        # contabilidad: mientras no exista, `siigo_bodega_id` va vacío y la
        # caja apagada (`enlazar_feria`). Centro de costo PRINCIPAL y el
        # vendedor de Florida hasta que contabilidad diga otra cosa.
        **_EMPRESA,
        "id": "feria", "nombre": "Feria",
        "siigo_bodega_id": None, "siigo_centro_costo_id": 237,
        "siigo_vendedor_id": 937,
        "siigo_nc_documento_id": 11817,
        "direccion": "Feria", "telefono": "3122851520",
        # En una feria no se para una venta por un conteo atrasado.
        "permite_stock_negativo": True,
    },
]

#  Un prefijo POR TIENDA: las dos cajas de Florida numeran del mismo rango
#  (`repo_consecutivos` bloquea por prefijo, no por caja).
#
#  EL NÚMERO DEL POS ES UNA REFERENCIA INTERNA, Y SE QUEDA ASÍ. Va con un
#  prefijo propio —`FLPOS`, `ARRPOS`— y NUNCA con el de la resolución (`FL`,
#  `TARR`). El número de la factura lo asigna Siigo al emitirla, bajo la
#  resolución de la tienda, y es el único que vale ante la DIAN. Si el POS
#  numerara con `TARR`, habría dos «TARR-11400» distintos: el que la caja
#  imprimió y el que Siigo le puso a otra venta.
#
#  Por eso NO hay que cambiar este prefijo el día que el POS emita. La tirilla
#  muestra el número de Siigo como «Factura No.» y éste como referencia.
CAJAS = [
    {"id": "florida_caja1", "tienda_id": "florida", "nombre": "Caja 1",
     "prefijo_factura": "FLPOS",
     "autorizacion_prefijo": "TFL",
     # Resolución DIAN del 2026-10-08, vigente 24 meses (pantalla de Siigo).
     "autorizacion_numero": "18764116899253", "autorizacion_desde": 1,
     "autorizacion_hasta": 1000000,
     "autorizacion_aprobada": date(2026, 10, 8), "autorizacion_meses": 24},
    {"id": "florida_caja2", "tienda_id": "florida", "nombre": "Caja 2",
     "prefijo_factura": "FLPOS",
     "autorizacion_prefijo": "TFP",
     # Resolución DIAN del 2026-10-08, vigente 24 meses (pantalla de Siigo).
     "autorizacion_numero": "18764116899665", "autorizacion_desde": 1,
     "autorizacion_hasta": 1000000,
     "autorizacion_aprobada": date(2026, 10, 8), "autorizacion_meses": 24},
    {"id": "arrayanes_caja1", "tienda_id": "arrayanes", "nombre": "Caja 1",
     "prefijo_factura": "ARRPOS",
     "autorizacion_prefijo": "ARRT",
     # Resolución DIAN del 2026-10-08, vigente 24 meses (pantalla de Siigo).
     "autorizacion_numero": "18764116899001", "autorizacion_desde": 1,
     "autorizacion_hasta": 1000000,
     "autorizacion_aprobada": date(2026, 10, 8), "autorizacion_meses": 24},
    # Factura con el comprobante de la caja 2 de Florida (TFP, 80109): su
    # resolución está vigente hasta 2028 y una nueva tarda días en la DIAN.
    # Siigo numera; dos cajas en el mismo comprobante no se pisan.
    # APAGADA hasta que exista la bodega: sin ella la factura saldría sin
    # bodega y Siigo descontaría de cualquiera.
    {"id": "feria_caja1", "tienda_id": "feria", "nombre": "Caja Feria",
     "prefijo_factura": "FERPOS", "siigo_documento_id": 80109,
     "activa": False,
     "autorizacion_prefijo": "TFP",
     "autorizacion_numero": "18764116899665", "autorizacion_desde": 1,
     "autorizacion_hasta": 1000000,
     "autorizacion_aprobada": date(2026, 10, 8), "autorizacion_meses": 24},
]

UBICACIONES = [
    {"id": "tienda:florida", "tipo": "tienda", "nombre": "Florida",
     "tienda_id": "florida", "siigo_bodega_id": 48},
    {"id": "tienda:arrayanes", "tipo": "tienda", "nombre": "Arrayanes",
     "tienda_id": "arrayanes", "siigo_bodega_id": 37},
    {"id": "tienda:feria", "tipo": "tienda", "nombre": "Feria",
     "tienda_id": "feria", "siigo_bodega_id": None},
]

#  El efectivo y el datáfono son DE CADA TIENDA: en Siigo son cuentas
#  distintas. NO HAY TRANSFERENCIA: las tiendas no la reciben (Sebastián,
#  2026-10-08). Addi, Sumas y el QR de Wompi los siembra la migración 0015 y
#  son uno solo para todas las tiendas.
MEDIOS = [
    {"id": "efectivo_florida", "nombre": "Efectivo", "tipo": "efectivo",
     "tienda_id": "florida", "siigo_forma_pago_id": 12243,
     "permite_vuelto": True, "orden": 0, "exige_referencia": False},
    {"id": "datafono_florida", "nombre": "Datáfono", "tipo": "tarjeta",
     "tienda_id": "florida", "siigo_forma_pago_id": 12244,
     "permite_vuelto": False, "orden": 1,
     # El número del voucher: es lo que cuadra el cierre contra el informe
     # del datáfono. Obligatorio desde el 2026-10-10.
     "exige_referencia": True},
    {"id": "efectivo_arrayanes", "nombre": "Efectivo", "tipo": "efectivo",
     "tienda_id": "arrayanes", "siigo_forma_pago_id": 8282,
     "permite_vuelto": True, "orden": 0, "exige_referencia": False},
    {"id": "datafono_arrayanes", "nombre": "Datáfono", "tipo": "tarjeta",
     "tienda_id": "arrayanes", "siigo_forma_pago_id": 8987,
     "permite_vuelto": False, "orden": 1,
     # El número del voucher: es lo que cuadra el cierre contra el informe
     # del datáfono. Obligatorio desde el 2026-10-10.
     "exige_referencia": True},
    # La feria: el efectivo vuelve a la oficina; el datáfono es el de
    # «Plaza de Wein» (12143), que contabilidad reactiva en Siigo.
    {"id": "efectivo_feria", "nombre": "Efectivo", "tipo": "efectivo",
     "tienda_id": "feria", "siigo_forma_pago_id": 44998,
     "permite_vuelto": True, "orden": 0, "exige_referencia": False},
    {"id": "datafono_feria", "nombre": "Datáfono", "tipo": "tarjeta",
     "tienda_id": "feria", "siigo_forma_pago_id": 12143,
     "permite_vuelto": False, "orden": 1, "exige_referencia": True},
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


def enlazar_feria(url: str, bodegas: List[dict], *, aplicar: bool = False) -> dict:
    """Cuando contabilidad crea la bodega «Feria» en Siigo: la enlaza a la
    tienda y a su ubicación, y prende la caja. `bodegas` es `GET /warehouses`.

    Sin bodega no hace nada: la caja sigue apagada.
    """
    feria = [b for b in bodegas
             if (b.get("name") or "").strip().lower() == "feria"
             and b.get("active", True)]
    if len(feria) != 1:
        return {"enlazada": False,
                "motivo": f"{len(feria)} bodegas activas llamadas «Feria» en Siigo"}
    bodega = int(feria[0]["id"])
    motor = create_engine(normalizar_url(url), future=True)
    try:
        with motor.connect() as c:
            tx = c.begin()
            c.execute(text("UPDATE retail.tiendas SET siigo_bodega_id = :b "
                           "WHERE id = 'feria'"), {"b": bodega})
            c.execute(text("UPDATE retail.ubicaciones SET siigo_bodega_id = :b "
                           "WHERE id = 'tienda:feria'"), {"b": bodega})
            c.execute(text("UPDATE retail.cajas SET activa = true "
                           "WHERE id = 'feria_caja1'"))
            if aplicar:
                tx.commit()
            else:
                tx.rollback()
    finally:
        motor.dispose()
    return {"enlazada": aplicar, "bodega": bodega}


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
