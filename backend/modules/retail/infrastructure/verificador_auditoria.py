"""El job diario que comprueba la cadena de auditoría.

ESTE ARCHIVO CIERRA UNA PROMESA QUE EL CÓDIGO LLEVABA MESES HACIENDO. El
docstring de `verificar_cadena` decía «lo corre el job diario» y el comentario
de la migración 0013 lo decía con todas las letras: *«`verificar_cadena` está
escrito y sólo lo llama una prueba»*. O sea que la única verificación real
ocurría si a alguien se le ocurría abrir la pantalla de auditoría.

Y eso convierte la cadena en decoración. Una auditoría encadenada con SHA-256
no sirve porque el hash exista: sirve porque alguien lo COMPRUEBA y se entera
pronto. Sin comprobación periódica, una fila alterada en marzo se descubre en
la revisión de fin de año, cuando ya no hay forma de reconstruir qué pasó.

QUÉ HACE CUANDO ENCUENTRA UNA ROTURA, que es la parte que importa:

  1. `log.critical`, con el id del eslabón roto y el motivo.
  2. Lo deja en `ultimo`, que sale por `GET /api/retail/auditoria` — así la
     pantalla puede decirlo aunque nadie mire los logs.
  3. **No** escribe un evento de auditoría anunciándolo. Es tentador y sería
     un error: añadir un eslabón a una cadena que ya se sabe rota la alarga
     sin arreglarla, y encima mueve el `ultimo_hash`, que es justo la
     referencia que hace falta para investigar dónde se cortó.

La cadena tampoco se «repara» automáticamente. Reparar significaría reescribir
hashes, o sea hacer que el rastro vuelva a cuadrar — exactamente lo que un
libro append-only existe para impedir. Si se rompió, se investiga.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("retail.auditoria")

__all__ = ["start", "stop", "ultimo", "INTERVALO_SEGUNDOS", "verificar_ahora"]

#  Cada seis horas, no una vez al día. Es una operación de sólo lectura y
#  barata (recorre por lotes, memoria plana), y el valor de esto está en
#  ENTERARSE PRONTO: entre una alteración y su detección, cuanto menos tiempo
#  pase, más gente se acuerda de lo que hizo esa tarde.
INTERVALO_SEGUNDOS = int(os.environ.get("RETAIL_AUDITORIA_SEC", 6 * 60 * 60))

#  Al arrancar espera un poco más que el outbox: el arranque ya tiene bastante
#  trabajo y esto no es urgente al segundo.
RETRASO_INICIAL = 120

_hilo: Optional[threading.Thread] = None
_parar = threading.Event()

ultimo: dict = {
    "corrio_en": None,
    "integra": None,
    "eventos": 0,
    "roto_en": None,
    "motivo": None,
    "evento": None,
    "error": None,
}


async def verificar_ahora() -> dict:
    """Verifica TODAS las cadenas, una por tienda. Sin hilo: la usan el job y
    las pruebas.

    ⚠️ HAY UNA CADENA POR TIENDA, NO UNA SOLA. `verificar_cadena` filtra por
    `tienda_id IS NOT DISTINCT FROM :tienda`, así que llamarla sin argumento
    —que es como estaba escrito este job al principio— comprueba únicamente
    los eventos SIN tienda. Y casi todos los eventos llevan tienda.

    O sea que el job habría dicho «íntegra» todos los días mirando al vacío,
    que es el peor resultado posible: una verificación que siempre pasa da
    confianza sin darla. Lo encontró una prueba, no la revisión.
    """
    from sqlalchemy import text as _t
    from backend.modules.retail.interfaces.http import dependencias

    uow = await dependencias.unidad_de_trabajo()
    async with uow as t:
        tiendas = [f[0] for f in (await t.sesion.execute(_t(
            "SELECT DISTINCT tienda_id FROM retail.auditoria"))).all()]

        cadenas = {}
        rota = None
        total = 0
        for tienda in tiendas:
            v = await t.auditoria.verificar_cadena(tienda_id=tienda)
            cadenas[tienda or "(sin tienda)"] = v
            total += int(v.get("eventos", 0))
            if not v["integra"] and rota is None:
                rota = (tienda, v)

    integra = rota is None
    ultimo.update({
        "corrio_en": datetime.now(timezone.utc).isoformat(),
        "integra": integra,
        "eventos": total,
        "cadenas": len(tiendas),
        "roto_en": None if integra else rota[1].get("roto_en"),
        "motivo": None if integra else rota[1].get("motivo"),
        "evento": None if integra else rota[1].get("evento"),
        "tienda_rota": None if integra else rota[0],
        "error": None,
    })

    if integra:
        log.info("[retail-auditoria] %d cadena(s) íntegras · %d eventos",
                 len(tiendas), total)
    else:
        # CRITICAL y no ERROR: esto no es «algo falló», es «el rastro que
        # usamos para saber quién movió la plata no cuadra».
        log.critical(
            "[retail-auditoria] CADENA ROTA en la tienda %s, evento %s "
            "(%s · %s). NO se repara sola: hay que investigar qué alteró esa "
            "fila.", rota[0], rota[1].get("roto_en"), rota[1].get("evento"),
            rota[1].get("motivo"))

    return {"integra": integra, "eventos": total, "cadenas": cadenas}


def _bucle() -> None:
    import asyncio

    if _parar.wait(RETRASO_INICIAL):
        return
    while not _parar.is_set():
        try:
            asyncio.run(verificar_ahora())
        except Exception as e:  # noqa: BLE001
            # El hilo no se muere por una pasada fallida: si Postgres se
            # reinicia, la verificación tiene que volver a intentarlo dentro de
            # seis horas, no quedarse muerta hasta el siguiente despliegue.
            ultimo.update({
                "corrio_en": datetime.now(timezone.utc).isoformat(),
                "integra": None,
                "error": f"{type(e).__name__}: {e}"[:300],
            })
            log.error("[retail-auditoria] no se pudo verificar: %s", e)
        _parar.wait(INTERVALO_SEGUNDOS)


def start() -> bool:
    global _hilo

    from backend.modules.retail.interfaces.http import dependencias
    if not dependencias.configurado():
        return False
    if _hilo is not None and _hilo.is_alive():
        return True

    _parar.clear()
    _hilo = threading.Thread(target=_bucle, daemon=True, name="retail-auditoria")
    _hilo.start()
    return True


def stop() -> None:
    _parar.set()
