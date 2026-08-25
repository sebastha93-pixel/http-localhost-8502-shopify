"""El reloj que drena la cola. Hilo demonio dentro del mismo proceso FastAPI.

CAMBIÉ DE OPINIÓN SOBRE ESTO, y conviene decir por qué. Al escribir el
drenador dejé sólo el endpoint, argumentando que un hilo de fondo que se muere
en silencio deja la cola parada sin que nadie se entere. Sigue siendo verdad,
pero la conclusión estaba mal: este backend YA corre cuatro schedulers así
(`backend/core/scheduler.py` y compañía), con elección de líder por file lock
y en producción desde hace meses. Montar aquí un mecanismo distinto —un cron
externo con su propia credencial— sería una segunda forma de hacer lo mismo en
el mismo proceso, y la segunda forma es la que nadie recuerda mantener.

Lo que sí se conserva del argumento: **el hilo publica su estado**. `ultimo`
dice cuándo corrió, qué hizo y con qué error murió, y sale por
`GET /api/retail/admin/outbox`. Un hilo mudo es el problema; un hilo que
reporta, no.

DOS PROTECCIONES QUE NO SOBRAN AUNQUE HAYA LÍDER:

* El drenador ya es seguro con varios procesos (`FOR UPDATE SKIP LOCKED`), así
  que si el lock de líder fallara y arrancaran cuatro, el resultado sería
  correcto — sólo desperdiciaría conexiones. La corrección no depende de que
  la elección de líder funcione.

* Si `RETAIL_DATABASE_URL` no está configurada, esto NO arranca. El módulo
  retail hoy no está montado en producción, y un hilo intentando conectarse a
  una base que no existe llenaría los logs cada minuto.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("retail.outbox")

__all__ = ["start", "stop", "ultimo", "INTERVALO_SEGUNDOS"]

#  Cada dos minutos. No es un número redondo por gusto: lo que espera en la
#  cola es una factura electrónica, y el margen entre «la clienta se va con su
#  tirilla» y «el documento existe ante la DIAN» conviene que se mida en
#  minutos. Bajarlo más no gana nada —Siigo no va más rápido— y multiplica
#  conexiones a Postgres.
INTERVALO_SEGUNDOS = int(os.environ.get("RETAIL_OUTBOX_SEC", 120))

#  Cuántos trabajos por pasada. Con 20 y dos minutos son 600/hora, muy por
#  encima de lo que una tienda genera en un día.
LOTE = int(os.environ.get("RETAIL_OUTBOX_LOTE", 20))

#  Arranca con retraso: durante el arranque el proceso está compilando
#  plantillas, abriendo pools y sirviendo las primeras peticiones. La cola
#  puede esperar treinta segundos.
RETRASO_INICIAL = 30

_hilo: Optional[threading.Thread] = None
_parar = threading.Event()

#  Estado para el health-check. Es lo que convierte un hilo mudo en uno que se
#  puede vigilar — ver la cabecera.
ultimo: dict = {
    "corrio_en": None,
    "ok": None,
    "tomados": 0,
    "procesados": 0,
    "reintentos": 0,
    "fallidos": 0,
    "sin_manejador": 0,
    "rescatados": 0,
    "error": None,
}


async def _una_pasada() -> None:
    from backend.modules.retail.application.comandos.drenar_outbox import DrenarOutbox
    from backend.modules.retail.infrastructure.postventa import MANEJADORES
    from backend.modules.retail.interfaces.http import dependencias

    uow = await dependencias.unidad_de_trabajo()
    r = await DrenarOutbox(uow, MANEJADORES).ejecutar(
        ahora=datetime.now(timezone.utc), limite=LOTE)

    ultimo.update({
        "corrio_en": datetime.now(timezone.utc).isoformat(),
        "ok": True, "tomados": r.tomados, "procesados": r.procesados,
        "reintentos": r.reintentos, "fallidos": r.fallidos,
        "sin_manejador": r.sin_manejador, "rescatados": r.rescatados,
        "error": None,
    })

    # Sólo se escribe en el log cuando PASÓ algo. Una línea cada dos minutos
    # diciendo «0 trabajos» entierra las que importan.
    if r.tomados or r.rescatados:
        log.info("[retail-outbox] tomados=%d procesados=%d reintentos=%d "
                 "fallidos=%d sin_manejador=%d rescatados=%d",
                 r.tomados, r.procesados, r.reintentos, r.fallidos,
                 r.sin_manejador, r.rescatados)
    for e in r.errores:
        log.warning("[retail-outbox] %s", e)


def _bucle() -> None:
    if _parar.wait(RETRASO_INICIAL):
        return
    while not _parar.is_set():
        try:
            asyncio.run(_una_pasada())
        except Exception as e:  # noqa: BLE001
            # NUNCA se deja morir el hilo por un fallo de una pasada. Un
            # Postgres que se reinicia no puede dejar la cola parada hasta el
            # siguiente despliegue — que es lo que pasaría si esta excepción
            # subiera y matara el thread.
            ultimo.update({
                "corrio_en": datetime.now(timezone.utc).isoformat(),
                "ok": False, "error": f"{type(e).__name__}: {e}"[:300],
            })
            log.error("[retail-outbox] pasada fallida: %s", e)
        _parar.wait(INTERVALO_SEGUNDOS)


def start() -> bool:
    """Arranca el hilo. Idempotente. `False` si no había con qué."""
    global _hilo

    from backend.modules.retail.interfaces.http import dependencias
    if not dependencias.configurado():
        return False

    if _hilo is not None and _hilo.is_alive():
        return True

    _parar.clear()
    _hilo = threading.Thread(target=_bucle, daemon=True, name="retail-outbox")
    _hilo.start()
    return True


def stop() -> None:
    _parar.set()
