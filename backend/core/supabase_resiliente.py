"""Reintento sistémico de LECTURAS contra Supabase/PostgREST.

Problema (visto en producción varias veces, sostenido el 2026-09-11): el pooler
de Supabase cierra una conexión keep-alive HTTP/2 reusada (envía GOAWAY), y la
siguiente petición que reusa esa conexión revienta con
`httpx.RemoteProtocolError: <ConnectionTerminated ...>`. Como es un corte
mid-stream, httpx NO lo reintenta solo (sus transport-retries cubren la apertura
de conexión, no un corte a mitad). Cada endpoint sin blindaje devolvía 500.

Se venía tapando función por función con `_safe_exec` (precosteo, remisión,
orden de corte…). Esto lo resuelve de RAÍZ en un solo punto:
`postgrest._sync.request_builder.send_with_retry` — la función por la que pasan
TODAS las queries (`.execute()` la llama). Ya reintenta GET/HEAD ante errores
Cloudflare 503/520 por código de respuesta; acá se le añade reintentar cuando
`req.send()` LANZA el corte transitorio.

SEGURIDAD: se reintenta EXCLUSIVAMENTE para métodos idempotentes (GET/HEAD).
Una escritura (POST/PATCH/DELETE, y las RPC que son POST) que se corta a mitad
NO se reintenta — pudo haberse aplicado en el servidor y un reintento la
duplicaría. Ese es justo el riesgo que este módulo evita.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

# Familia de cortes de conexión transitorios (por tipo de excepción o mensaje).
# NO se incluyen timeouts a propósito: el objetivo es el corte de conexión
# reusada, no una consulta lenta.
_TRANSITORIO = (
    "remoteprotocol",
    "connectionterminated",
    "server disconnected",
    "disconnected",
    "connection reset",
    "connectionclosed",
    "connecterror",
    "readerror",
)

_MAX_INTENTOS_LECTURA = 3          # 1 original + 2 reintentos
_BACKOFF_BASE = 0.4                # 0.4s, 0.8s


def _es_corte_transitorio(exc: Exception) -> bool:
    blob = (type(exc).__name__ + " " + str(exc)).lower()
    return any(t in blob for t in _TRANSITORIO)


def exec_idempotente(query, intentos: int = 3):
    """Ejecuta `query.execute()` reintentando ante el corte transitorio del pool.

    ⚠️ SOLO para operaciones IDEMPOTENTES: un UPSERT con on_conflict (re-aplicar
    la misma fila no duplica) o un DELETE con WHERE determinista (borra el mismo
    conjunto, o nada). NUNCA para un `.insert()` que acumula ni una RPC con
    efectos: un write cortado a mitad pudo aplicarse en el servidor y reintentarlo
    lo duplicaría. El reintento sistémico de postgrest solo cubre GET; esto es
    para las escrituras seguras que igual se caían con el pool inestable
    (overrides por orden, inventario por brand_id/code/bodega, etc.).
    """
    ultimo = None
    for i in range(intentos):
        try:
            return query.execute()
        except Exception as e:
            ultimo = e
            if _es_corte_transitorio(e) and i < intentos - 1:
                time.sleep(_BACKOFF_BASE * (2 ** i))
                continue
            raise
    if ultimo is not None:
        raise ultimo


def forzar_http1_postgrest() -> bool:
    """Fuerza HTTP/1.1 en el cliente httpx de PostgREST — el ARREGLO DE RAÍZ del
    corte de conexión.

    postgrest crea su cliente con `Client(http2=True, ...)` hardcodeado. Ese
    HTTP/2 es la CAUSA del `ConnectionTerminated`: el pooler de Supabase manda un
    GOAWAY sobre una conexión keep-alive reusada y la siguiente petición que la
    toma revienta. En días malos eso pasa en ráfagas de varios segundos y ni los
    reintentos alcanzan. En HTTP/1.1 no existe el GOAWAY: una keep-alive cerrada
    simplemente se reabre. Elimina el problema en vez de reintentarlo.

    Se parcha el símbolo `Client` del módulo de postgrest con una subclase que
    nace en http2=False (preserva isinstance). DEBE correr ANTES de crear el
    primer cliente — en el lifespan, antes de la primera query. Todos los
    create_client de la app son perezosos (dentro de _sb()), así que quedan
    cubiertos. Idempotente y a prueba de fallos: si la versión de postgrest no
    calza, no hace nada y quedan los reintentos como red."""
    try:
        import postgrest._sync.client as pc
    except Exception as e:
        log.warning(f"[supabase-http1] no se pudo importar postgrest: {e}")
        return False
    orig = getattr(pc, "Client", None)
    if orig is None:
        log.warning("[supabase-http1] postgrest no expone Client en esta versión")
        return False
    if getattr(orig, "_http1_forzado", False):
        return True  # ya instalado

    class ClientHTTP1(orig):
        _http1_forzado = True

        def __init__(self, *args, **kwargs):
            kwargs["http2"] = False
            super().__init__(*args, **kwargs)

    pc.Client = ClientHTTP1
    log.info("[supabase-http1] PostgREST forzado a HTTP/1.1 (evita GOAWAY/ConnectionTerminated)")
    return True


def instalar_retry_lecturas_supabase() -> bool:
    """Parcha `postgrest._sync.request_builder.send_with_retry` para reintentar
    las LECTURAS ante un corte transitorio del pool. Idempotente y a prueba de
    fallos: si la versión de postgrest no calza, no hace nada (se queda el
    comportamiento actual + los `_safe_exec` puntuales como red). Devuelve True
    si quedó instalado."""
    try:
        import postgrest._sync.request_builder as rb
    except Exception as e:  # postgrest no disponible / API cambió
        log.warning(f"[supabase-retry] no se pudo importar postgrest: {e}")
        return False

    orig = getattr(rb, "send_with_retry", None)
    if orig is None:
        log.warning("[supabase-retry] send_with_retry no existe en esta versión de postgrest")
        return False
    if getattr(orig, "_retry_lecturas", False):
        return True  # ya instalado

    def send_with_retry(req):
        # Solo las LECTURAS son seguras de reintentar. Todo lo demás (writes,
        # RPC=POST) pasa una sola vez.
        metodo = str(getattr(req, "http_method", "") or "").upper()
        idempotente = metodo in ("GET", "HEAD")
        if not idempotente:
            return orig(req)
        ultimo = None
        for intento in range(_MAX_INTENTOS_LECTURA):
            try:
                return orig(req)
            except Exception as e:
                ultimo = e
                if _es_corte_transitorio(e) and intento < _MAX_INTENTOS_LECTURA - 1:
                    time.sleep(_BACKOFF_BASE * (2 ** intento))
                    continue
                raise
        if ultimo is not None:
            raise ultimo

    send_with_retry._retry_lecturas = True  # type: ignore[attr-defined]
    rb.send_with_retry = send_with_retry
    log.info("[supabase-retry] reintento de LECTURAS instalado en postgrest.send_with_retry")
    return True
