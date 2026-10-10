"""Saber cuándo la nota crédito de una devolución ya salió.

Ese es el momento en que Siigo mete la prenda a la bodega de la tienda. Hasta
entonces la sincronización del inventario la suma por su cuenta; desde
entonces ya viene contada en lo que dice Siigo, y sumarla otra vez la
duplicaría. Aquí se marca el paso de un estado al otro.

Se pregunta a Postventa, que es quien emite: un caso con su `nota_credito` en
`emitido`. Un caso RECHAZADO o CERRADO sin nota crédito también deja de
sumarse: Siigo ya no va a recibir esa prenda por ese camino, y seguir
contándola sería inventario fantasma para siempre.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from sqlalchemy import create_engine, text

from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
    normalizar_url,
)

log = logging.getLogger("retail.inventario")

__all__ = ["marcar", "casos_con_nota_credito"]


def casos_con_nota_credito(numeros: List[str]) -> Dict[str, bool]:
    """`{número de caso: ya tiene la nota crédito emitida}`, leído de Postventa."""
    from backend.services import postventa as svc

    sb = svc._sb()
    if sb is None or not numeros:
        return {}
    casos = (sb.table("postventa_cases").select("id,case_number,status")
               .in_("case_number", numeros).execute()).data or []
    por_id = {c["id"]: c["case_number"] for c in casos}
    terminados = {c["case_number"] for c in casos
                  if c.get("status") in ("rechazado", "cerrado")}
    if not por_id:
        return {}
    emitidas = (sb.table("postventa_fiscal").select("case_id")
                  .in_("case_id", list(por_id)).eq("doc_kind", "nota_credito")
                  .eq("status", "emitido").execute()).data or []
    con = {por_id[f["case_id"]] for f in emitidas if f.get("case_id") in por_id}
    return {n: (n in con or n in terminados) for n in por_id.values()}


def marcar(url: str, *,
           consultar: Optional[Callable[[List[str]], Dict[str, bool]]] = None,
           ) -> int:
    """Marca las devoluciones cuya nota crédito ya salió. Devuelve cuántas."""
    consultar = consultar or casos_con_nota_credito
    motor = create_engine(normalizar_url(url), future=True)
    try:
        with motor.begin() as c:
            pendientes = [r[0] for r in c.execute(text("""
                SELECT DISTINCT caso_postventa FROM retail.devoluciones
                 WHERE entro_a_siigo_en IS NULL AND caso_postventa IS NOT NULL
            """))]
            if not pendientes:
                return 0
            listos = [n for n, ok in consultar(pendientes).items() if ok]
            if not listos:
                return 0
            n = c.execute(text("""
                UPDATE retail.devoluciones SET entro_a_siigo_en = now()
                 WHERE entro_a_siigo_en IS NULL AND caso_postventa = ANY(:c)
            """), {"c": listos}).rowcount
            log.info("[retail-inventario] %d devolución(es) ya acreditadas en "
                     "Siigo: %s", n, ", ".join(listos))
            return int(n or 0)
    finally:
        motor.dispose()
