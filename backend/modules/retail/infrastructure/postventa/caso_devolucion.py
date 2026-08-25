"""El manejador que convierte una devolución del POS en un caso de Postventa.

Es el puente entre dos módulos que hablan idiomas distintos, y lo único que
tiene que hacer bien es NO INVENTAR DATOS al traducir.

EL VOCABULARIO NO COINCIDE, y no es un descuido de ninguno de los dos:

  · El POS pregunta lo que la cajera puede saber de un vistazo en el
    mostrador: cuatro motivos (`motivo.py` explica por qué esos cuatro).
  · Postventa tiene quince motivos porque atiende también el canal online,
    donde hay demora de entrega, error logístico y pedido incompleto — cosas
    que no existen cuando la clienta está delante con la prenda en la mano.

⚠️ **`talla` NO SE MAPEA A `talla_pequena`.** Postventa separa pequeña de
grande y el POS no lo pregunta, así que elegir una sería inventarse la mitad
de los casos. Y justo ése es el dato que sirve para algo: si una referencia
acumula «pequeña», el patrón está mal escalado. Un 50 % de ruido lo vuelve
inservible. Va como `otro` con el motivo del POS en `subreason`, así que la
información que SÍ tenemos no se pierde.

(La solución de fondo es que el POS pregunte pequeña o grande. Son dos chips
en vez de uno y la cajera lo sabe porque la clienta se lo acaba de decir.)

EL `tipo` SALE DEL REEMBOLSO, NO DEL MOTIVO, y esto sí es importante:
`cambio_talla` y `cambio_ref` están en `TIPOS_SIN_APROBACION`, o sea que nacen
APROBADOS y ponen en marcha un reemplazo. En esta pantalla la clienta no se
lleva otra prenda: se le devuelve la plata. Marcarlo como cambio dispararía el
despacho de un reemplazo que nadie va a mandar.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

log = logging.getLogger("retail.postventa")

__all__ = ["abrir_caso_postventa", "TIPO", "motivo_postventa", "tipo_postventa"]

#  El `tipo` del trabajo en el outbox. Vive aquí, junto a su manejador, para
#  que registrarlo sea imposible de olvidar al leer este archivo.
TIPO = "abrir_caso_postventa"

_MOTIVOS = {
    "defecto": "producto_defectuoso",
    "no_le_gusto": "no_le_gusto_como_quedo",
    "cambio_modelo": "cambio_por_otro",
    # `talla` va a `otro` a propósito. Ver la cabecera.
    "talla": "otro",
}

_TIPOS = {
    "efectivo": "reembolso",
    "metodo_original": "reembolso",
    "credito_tienda": "bono",
}


def motivo_postventa(motivo_pos: str) -> str:
    return _MOTIVOS.get(motivo_pos, "otro")


def tipo_postventa(reembolso_pos: str) -> str:
    return _TIPOS.get(reembolso_pos, "reembolso")


async def abrir_caso_postventa(t, payload: dict) -> Optional[str]:
    """Abre el caso y guarda su número en la devolución.

    IDEMPOTENTE, y no por elegancia: si el caso se creó pero la fila del outbox
    no se alcanzó a marcar —el proceso se muere justo ahí—, el reintento
    abriría un SEGUNDO caso sobre la misma devolución, y con él una segunda
    nota crédito sobre la misma factura. Por eso lo primero es mirar si esta
    devolución ya tiene caso.
    """
    devolucion_id = payload["devolucion_id"]

    ya = (await t.sesion.execute(text("""
        SELECT caso_postventa FROM retail.devoluciones WHERE id = :i
    """), {"i": devolucion_id})).scalar()
    if ya:
        return f"ya tenía el caso {ya}"

    # Import local: `backend.services.postventa` habla con Supabase al
    # importarse, y el módulo retail tiene que poder cargarse sin él —es lo
    # que permite que las pruebas de dominio corran sin red.
    from backend.services import postventa as svc

    caso = svc.crear_caso(
        tipo=tipo_postventa(payload["reembolso"]),
        reason=motivo_postventa(payload["motivo"]),
        # El motivo del POS viaja literal. Es lo que rescata el caso de
        # `talla`: el `reason` dice «otro», pero aquí queda escrito qué fue.
        subreason=f"POS · {payload['motivo']}",
        tienda=payload.get("tienda_id", ""),
        # `source` distingue esta puerta de entrada de las demás. Sin él, en
        # el tablero de Postventa un caso nacido en la caja se ve igual que
        # uno que abrió una asesora por WhatsApp.
        source="pos",
    )

    numero = caso.get("case_number") or caso.get("id") or ""

    # Se escribe en la MISMA transacción que marca el trabajo como procesado
    # (la abre `DrenarOutbox`), así que o quedan las dos cosas o ninguna.
    await t.sesion.execute(text("""
        UPDATE retail.devoluciones SET caso_postventa = :c WHERE id = :i
    """), {"c": numero, "i": devolucion_id})

    log.info("[retail] devolución %s → caso postventa %s", devolucion_id, numero)
    return f"caso {numero}"
