"""Lo que se corrige en Siigo llega al POS.

Florida, 2026-10-16: una clienta entró al POS desde Siigo con el correo
genérico de Siigo POS (`FECLIENTE@…`). Contabilidad lo corrigió en Siigo y el
POS lo siguió mostrando. La importación (`importar_clientes`) sólo rellena
campos VACÍOS —para no pisar lo que una cajera acaba de dictar—, y la caja no
tiene cómo editar una clienta: una corrección hecha en Siigo se quedaba allá
para siempre.

GANA LO MÁS NUEVO. Si Siigo cambió a la clienta DESPUÉS de la última vez que el
POS la tocó, lo de Siigo manda; si no, no se toca nada. Un campo vacío en Siigo
nunca borra el del POS, y ni el tipo ni el número de documento se cambian por
aquí: son la llave con que se la busca y se la factura.

Sólo pone al día a las clientas YA ENLAZADAS (`siigo_customer_id`). Crear es de
la búsqueda en caja y de la importación.

Corre con el inventario, cada 10 minutos: una petición a Siigo por las clientas
modificadas en los dos últimos días.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

from sqlalchemy import create_engine, text

from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
    normalizar_url,
)

log = logging.getLogger("retail.inventario")

__all__ = ["traer", "cambios", "modificadas_en_siigo"]

_CAMPOS = ("nombre", "apellido", "telefono", "correo", "direccion", "ciudad", "dv")
_DIAS = 2


def _limpio(campo: str, valor) -> str:
    v = (str(valor) if valor is not None else "").strip()
    return v.lower() if campo == "correo" else v


def cambios(fila: dict, clienta: dict) -> dict:
    """Los campos del POS que hay que cambiar por los de Siigo. Puro."""
    en_siigo: Optional[datetime] = clienta.get("actualizado_en_siigo")
    if en_siigo is None or fila["actualizado_en"] >= en_siigo:
        return {}
    salida = {}
    for campo in _CAMPOS:
        nuevo = _limpio(campo, clienta.get(campo))
        if nuevo and nuevo != _limpio(campo, fila.get(campo)):
            salida[campo] = nuevo
    return salida


def modificadas_en_siigo() -> list:
    """Las clientas que Siigo dice haber modificado en los últimos días."""
    from backend.services import siigo
    from backend.modules.retail.infrastructure.siigo.clientes_siigo import a_cliente

    if not siigo.siigo_configurado():
        return []
    desde = (datetime.now(timezone.utc) - timedelta(days=_DIAS)).date().isoformat()
    salida, pagina = [], 1
    while pagina <= 20:
        r = siigo.siigo_get("/customers", {"updated_start": desde,
                                           "page": pagina, "page_size": 100})
        filas = (r.get("results") or []) if isinstance(r, dict) else []
        salida.extend(a_cliente(c) for c in filas)
        total = ((r.get("pagination") or {}).get("total_results") or 0
                 if isinstance(r, dict) else 0)
        if not filas or pagina * 100 >= total:
            break
        pagina += 1
    return salida


def traer(url: str, *, leer: Optional[Callable[[], Iterable[dict]]] = None) -> int:
    """Pone al día las clientas corregidas en Siigo. Devuelve cuántas cambió."""
    clientas = [c for c in (leer or modificadas_en_siigo)()
                if c.get("siigo_customer_id")]
    if not clientas:
        return 0
    motor = create_engine(normalizar_url(url), future=True)
    n = 0
    try:
        with motor.begin() as c:
            for clienta in clientas:
                fila = c.execute(text(f"""
                    SELECT id, actualizado_en, {', '.join(_CAMPOS)}
                      FROM retail.clientes WHERE siigo_customer_id = :s
                """), {"s": clienta["siigo_customer_id"]}).mappings().first()
                if fila is None:
                    continue
                nuevos = cambios(dict(fila), clienta)
                if not nuevos:
                    continue
                sets = ", ".join(f"{k} = :{k}" for k in nuevos)
                c.execute(text(f"""
                    UPDATE retail.clientes SET {sets}, actualizado_en = now()
                     WHERE id = :id
                """), {**nuevos, "id": fila["id"]})
                n += 1
                log.info("[retail-clientes] %s corregida en Siigo: %s",
                         fila["id"], ", ".join(sorted(nuevos)))
    finally:
        motor.dispose()
    return n
