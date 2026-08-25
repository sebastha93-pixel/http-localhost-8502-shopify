# Acuse de envío y entrega del correo de orden de corte — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el diseñador vea si el correo de la orden de corte salió, llegó o falló, y pueda reenviarlo a otra dirección cuando se equivocó de destinatario.

**Architecture:** Una tabla nueva (`correos_orden_corte`) guarda una fila por intento de envío. El envío por Resend se extrae a una función que **nunca lanza** y devuelve el resultado, en vez del `try/except` que hoy se traga el error y cae a `mailto`. El estado de entrega se consulta a Resend bajo demanda (`GET /emails/{id}` → `last_event`) solo para envíos en curso; los estados definitivos no se reconsultan.

**Tech Stack:** Python 3.10 (Railway), FastAPI, Supabase (postgrest-py), httpx, pytest · Next.js 16 + React Query + TypeScript

**Spec:** `docs/superpowers/specs/2026-08-12-acuse-correo-orden-corte-design.md`

## Global Constraints

- **Rama:** `feat/acuse-correo-orden-corte` (ya creada desde `main`).
- **Python del runtime es 3.10** (Dockerfile jammy, NO el `runtime.txt`). No usar sintaxis de 3.11+.
  **Ojo: el `.venv` local es 3.12.** Una prueba puede pasar en local y el código reventar en
  Railway. Nada de `match`, `ExceptionGroup`, ni genéricos de 3.12 (`type X = ...`).
- **`datetime.fromisoformat` de 3.10 revienta con fracciones de segundo de precisión variable** que Postgres recorta. No parsear timestamps de Supabase con `fromisoformat` sin normalizar; en este plan las fechas se pasan como texto y no se parsean en el backend.
- **`_sb()` devuelve `None` cuando no hay credenciales.** `tests/conftest.py` blanquea `SUPABASE_URL`/`SUPABASE_KEY` en toda prueba, así que ninguna prueba puede tocar Supabase de verdad. Toda lógica nueva que valga la pena probar va en funciones que **no** necesitan Supabase.
- **Nada de `print()` para errores.** El módulo ya tiene `log = logging.getLogger(...)`. Usar `log.warning` / `log.error`.
- **Verificación del frontend: `npm run build`.** `tsc --noEmit` no basta — no detecta imports duplicados. Solo `next build` reproduce lo que hace Vercel.
- **Comitear al final de cada tarea.** Mensajes en español, sin tildes en el asunto del commit.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `SUPABASE_MIGRATION_CORREOS_ORDEN_CORTE.sql` | **Crear.** Tabla e índice. |
| `backend/services/produccion.py` | **Modificar.** Mapeo de estados, envío por Resend sin tragar errores, registro en la tabla, consulta de estado, historial en el detalle. |
| `backend/api/produccion.py` | **Modificar.** Endpoint `reenviar-correo`. |
| `tests/test_correo_orden_corte.py` | **Crear.** Las pruebas de las tareas 1-5. |
| `frontend/app/produccion/corte/[id]/page.tsx` | **Modificar.** Estado, historial, botón reenviar, aviso de destinatario. |
| `frontend/app/produccion/corte/page.tsx` | **Modificar.** Badge de estado por orden en la lista. |

Las funciones nuevas del backend se agrupan en un bloque propio dentro de `produccion.py`, junto a `autorizar_orden_corte`. El archivo ya es grande (5.900 líneas), pero partirlo ahora mezclaría un refactor con un arreglo — se sigue el patrón del archivo.

---

### Task 1: Tabla `correos_orden_corte`

**Files:**
- Create: `SUPABASE_MIGRATION_CORREOS_ORDEN_CORTE.sql`

**Interfaces:**
- Consumes: nada.
- Produces: tabla `correos_orden_corte` con las columnas que usan todas las tareas siguientes.

- [ ] **Step 1: Escribir la migración**

Crear `SUPABASE_MIGRATION_CORREOS_ORDEN_CORTE.sql`:

```sql
-- Un registro por INTENTO de envío del correo de la orden de corte.
--
-- Por qué una tabla y no columnas en ordenes_corte: el reenvío ya existe
-- (actualizar_indicaciones_corte remanda el correo cuando cambian las
-- indicaciones), así que columnas planas se pisarían en el segundo envío y
-- perderían la historia. El caso real que motivó esto —2607-0017 salió a
-- barreto.corte@hotmail.com en vez de johnj2397@hotmail.com— solo se entiende
-- viendo los dos intentos, el equivocado y la corrección.
--
-- estado: enviado | entregado | rebotado | spam | demorado | fallido
--         | suprimido | error_envio
--   error_envio = Resend rechazó la petición y nunca creó el correo.
-- motivo: autorizacion | reenvio_indicaciones | reenvio_manual
CREATE TABLE IF NOT EXISTS correos_orden_corte (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  orden_corte_id        uuid NOT NULL REFERENCES ordenes_corte(id) ON DELETE CASCADE,
  destinatarios         text[] NOT NULL DEFAULT '{}',
  asunto                text,
  motivo                text NOT NULL,
  resend_id             text,
  estado                text NOT NULL,
  error                 text,
  enviado_por           text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  estado_actualizado_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_correos_oc_orden
  ON correos_orden_corte(orden_corte_id, created_at DESC);
```

- [ ] **Step 2: Aplicar la migración en Supabase**

Ejecutar el contenido del archivo en el SQL Editor del proyecto `vmuopwdswrpimkijosyb`
(el mismo `SUPABASE_URL` del `.env`).

- [ ] **Step 3: Verificar que la tabla existe con las columnas correctas**

Ejecutar en el SQL Editor:

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'correos_orden_corte'
ORDER BY ordinal_position;
```

Esperado: 11 filas — `id`, `orden_corte_id`, `destinatarios`, `asunto`, `motivo`,
`resend_id`, `estado`, `error`, `enviado_por`, `created_at`, `estado_actualizado_at`.

- [ ] **Step 4: Commit**

```bash
git add SUPABASE_MIGRATION_CORREOS_ORDEN_CORTE.sql
git commit -m "feat(produccion): tabla correos_orden_corte, una fila por intento de envio"
```

---

### Task 2: Mapeo de los estados de Resend

**Files:**
- Modify: `backend/services/produccion.py` (bloque nuevo antes de `autorizar_orden_corte`, línea ~3081)
- Test: `tests/test_correo_orden_corte.py` (crear)

**Interfaces:**
- Consumes: nada.
- Produces:
  - `_estado_desde_last_event(last_event: Optional[str]) -> str`
  - `_ESTADOS_DEFINITIVOS: frozenset[str]`

- [ ] **Step 1: Escribir la prueba que falla**

Crear `tests/test_correo_orden_corte.py`:

```python
"""El correo de la orden de corte tiene que poder decir si llegó o no.

La orden 2607-0017 salió a barreto.corte@hotmail.com en vez de
johnj2397@hotmail.com y nadie se enteró: el sistema no registraba el envío y
un fallo de Resend se tragaba en un print. Estas pruebas fijan que eso no
vuelva a pasar en silencio.
"""
import pytest

from backend.services import produccion as svc


@pytest.mark.parametrize("evento,esperado", [
    ("sent", "enviado"),
    ("delivered", "entregado"),
    ("bounced", "rebotado"),
    ("complained", "spam"),
    ("delivery_delayed", "demorado"),
    ("failed", "fallido"),
    ("suppressed", "suprimido"),
])
def test_traduce_cada_evento_de_resend(evento, esperado):
    """Los 7 estados de entrega documentados por Resend."""
    assert svc._estado_desde_last_event(evento) == esperado


@pytest.mark.parametrize("evento", ["opened", "clicked"])
def test_abierto_y_clickeado_cuentan_como_entregado(evento):
    """No mostramos apertura, pero si Resend dice `opened` el correo LLEGÓ.

    Tratarlo como 'enviado' dejaría la orden consultando a Resend para
    siempre, porque nunca alcanzaría un estado definitivo.
    """
    assert svc._estado_desde_last_event(evento) == "entregado"


def test_evento_desconocido_queda_en_curso():
    """Un evento que Resend agregue mañana no puede mentir que se entregó."""
    assert svc._estado_desde_last_event("evento_del_futuro") == "enviado"
    assert svc._estado_desde_last_event(None) == "enviado"


def test_los_estados_definitivos_no_incluyen_los_que_siguen_cambiando():
    """'enviado' y 'demorado' todavía pueden moverse: hay que reconsultarlos."""
    assert "enviado" not in svc._ESTADOS_DEFINITIVOS
    assert "demorado" not in svc._ESTADOS_DEFINITIVOS
    assert {"entregado", "rebotado", "error_envio"} <= svc._ESTADOS_DEFINITIVOS
```

- [ ] **Step 2: Correr la prueba para verificar que falla**

Run: `cd ~/Proyectos/MALE-DENIM-OS/codigo && .venv/bin/python -m pytest tests/test_correo_orden_corte.py -v`
Expected: FAIL con `AttributeError: module 'backend.services.produccion' has no attribute '_estado_desde_last_event'`

- [ ] **Step 3: Implementar el mapeo**

En `backend/services/produccion.py`, insertar justo antes de
`# ── Autorizar orden de corte y enviar correo ──` (línea ~3078):

```python
# ═══════════════════════════════════════════════════════════════════════
# CORREO DE LA ORDEN DE CORTE — envío, registro y acuse de entrega
# ═══════════════════════════════════════════════════════════════════════

# `last_event` de Resend → estado interno.
# Fuente: https://resend.com/docs/dashboard/webhooks/event-types
#
# `opened` y `clicked` no se muestran (dependen de que el cliente de correo
# cargue imágenes y no son fiables), pero implican que el correo llegó: se
# tratan como entregado. Mapearlos a 'enviado' dejaría la orden reconsultando
# a Resend para siempre.
_ESTADO_POR_EVENTO = {
    "sent": "enviado",
    "delivered": "entregado",
    "opened": "entregado",
    "clicked": "entregado",
    "bounced": "rebotado",
    "complained": "spam",
    "delivery_delayed": "demorado",
    "failed": "fallido",
    "suppressed": "suprimido",
}

# Estados que ya no cambian: no se vuelve a consultar a Resend.
# 'error_envio' es nuestro, no de Resend: la petición se rechazó y nunca
# llegó a existir un correo que consultar.
_ESTADOS_DEFINITIVOS = frozenset({
    "entregado", "rebotado", "spam", "suprimido", "fallido", "error_envio",
})


def _estado_desde_last_event(last_event: Optional[str]) -> str:
    """Traduce el `last_event` de Resend al estado interno.

    Un evento desconocido queda como 'enviado' (en curso): nunca inventamos
    una entrega que Resend no confirmó.
    """
    return _ESTADO_POR_EVENTO.get((last_event or "").strip().lower(), "enviado")
```

- [ ] **Step 4: Correr la prueba para verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_correo_orden_corte.py -v`
Expected: PASS — 11 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/services/produccion.py tests/test_correo_orden_corte.py
git commit -m "feat(produccion): mapeo de los estados de entrega de Resend"
```

---

### Task 3: Enviar por Resend sin tragarse el error

**Files:**
- Modify: `backend/services/produccion.py` (bloque de la Task 2)
- Test: `tests/test_correo_orden_corte.py`

**Interfaces:**
- Consumes: `_estado_desde_last_event`, `_ESTADOS_DEFINITIVOS` (Task 2).
- Produces: `_enviar_por_resend(dest: list[str], asunto: str, body: str) -> dict`
  devolviendo `{"resend_id": Optional[str], "estado": str, "error": Optional[str]}`.
  **Nunca lanza.**

Esta es la tarea que arregla el Defecto 1. Se extrae el envío a una función propia
porque así se puede probar sin Supabase (`conftest.py` blanquea las credenciales) y
porque el resultado deja de perderse en un `except` que solo imprime.

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `tests/test_correo_orden_corte.py`:

```python
class _RespuestaFalsa:
    def __init__(self, status_code, payload=None, texto=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = texto

    def json(self):
        return self._payload


def test_envio_exitoso_devuelve_el_id_de_resend(monkeypatch):
    import httpx
    monkeypatch.setenv("RESEND_API_KEY", "re_falsa")
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: _RespuestaFalsa(200, {"id": "abc-123"}))

    r = svc._enviar_por_resend(["cortador@ejemplo.com"], "Asunto", "Cuerpo")

    assert r["estado"] == "enviado"
    assert r["resend_id"] == "abc-123"
    assert r["error"] is None


def test_resend_rechaza_y_queda_registrado_como_error(monkeypatch):
    """EL DEFECTO QUE MOTIVÓ TODO: un 403 de Resend NO puede pasar por éxito.

    Antes: se imprimía y se caía a mailto, la pantalla decía 'Orden
    autorizada' y nadie se enteraba de que el correo nunca salió.
    """
    import httpx
    monkeypatch.setenv("RESEND_API_KEY", "re_falsa")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _RespuestaFalsa(
        403, texto='{"message":"The maledenim.com domain is not verified"}'))

    r = svc._enviar_por_resend(["cortador@ejemplo.com"], "Asunto", "Cuerpo")

    assert r["estado"] == "error_envio"
    assert r["resend_id"] is None
    assert "403" in r["error"]
    assert "not verified" in r["error"]


def test_si_resend_se_cae_no_lanza(monkeypatch):
    """Un timeout de red no puede tumbar la autorización de la orden."""
    import httpx

    def _revienta(*a, **k):
        raise httpx.ConnectTimeout("se cayó la red")

    monkeypatch.setenv("RESEND_API_KEY", "re_falsa")
    monkeypatch.setattr(httpx, "post", _revienta)

    r = svc._enviar_por_resend(["cortador@ejemplo.com"], "Asunto", "Cuerpo")

    assert r["estado"] == "error_envio"
    assert "ConnectTimeout" in r["error"]


def test_sin_api_key_es_error_no_silencio(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    r = svc._enviar_por_resend(["cortador@ejemplo.com"], "Asunto", "Cuerpo")
    assert r["estado"] == "error_envio"
    assert r["error"] == "sin_RESEND_API_KEY"


def test_sin_destinatarios_es_error(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_falsa")
    r = svc._enviar_por_resend([], "Asunto", "Cuerpo")
    assert r["estado"] == "error_envio"
    assert r["error"] == "sin_destinatarios"
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_correo_orden_corte.py -v -k "enviar or resend"`
Expected: FAIL con `AttributeError: ... has no attribute '_enviar_por_resend'`

- [ ] **Step 3: Implementar el envío**

Agregar al bloque de la Task 2, después de `_estado_desde_last_event`:

```python
def _enviar_por_resend(dest: list[str], asunto: str, body: str) -> dict:
    """Manda el correo por Resend. NUNCA lanza: devuelve qué pasó.

    Antes esto vivía dentro de `autorizar_orden_corte` en un `try/except` que
    imprimía el error y caía a `mailto`. Como el frontend hacía
    `window.location.href = mailto_url` y en Chrome con Gmail web eso no hace
    nada, un fallo de Resend se veía exactamente igual que un envío exitoso.
    """
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not resend_key:
        return {"resend_id": None, "estado": "error_envio",
                "error": "sin_RESEND_API_KEY"}
    if not dest:
        return {"resend_id": None, "estado": "error_envio",
                "error": "sin_destinatarios"}
    try:
        import httpx
        from_email = os.environ.get("RESEND_FROM", "orden-corte@maledenim.com").strip()
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}",
                     "Content-Type": "application/json"},
            json={"from": from_email, "to": dest, "subject": asunto, "text": body},
            timeout=15.0,
        )
        if r.status_code >= 400:
            return {"resend_id": None, "estado": "error_envio",
                    "error": f"resend {r.status_code}: {r.text[:300]}"}
        return {"resend_id": ((r.json() or {}).get("id")),
                "estado": "enviado", "error": None}
    except Exception as e:
        log.warning(f"[corte.correo] Resend falló: {type(e).__name__}: {str(e)[:200]}")
        return {"resend_id": None, "estado": "error_envio",
                "error": f"{type(e).__name__}: {str(e)[:300]}"}
```

- [ ] **Step 4: Correr las pruebas para verificar que pasan**

Run: `.venv/bin/python -m pytest tests/test_correo_orden_corte.py -v`
Expected: PASS — 16 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/services/produccion.py tests/test_correo_orden_corte.py
git commit -m "feat(produccion): el envio por Resend devuelve el error en vez de tragarselo"
```

---

### Task 4: Registrar el envío y quitar el fallback silencioso

**Files:**
- Modify: `backend/services/produccion.py:3164-3208` (el bloque de envío dentro de `autorizar_orden_corte`)
- Test: `tests/test_correo_orden_corte.py`

**Interfaces:**
- Consumes: `_enviar_por_resend` (Task 3).
- Produces:
  - `_registrar_correo_corte(oc_id, *, destinatarios, asunto, motivo, resultado, usuario) -> Optional[dict]`
  - `autorizar_orden_corte` acepta `motivo: str = "autorizacion"` y su `resultado["correo"]`
    ahora incluye `estado`, `error` y `resend_id`.

- [ ] **Step 1: Escribir la prueba que falla**

Agregar a `tests/test_correo_orden_corte.py`:

```python
def test_autorizar_registra_el_intento_incluso_cuando_falla(monkeypatch):
    """Autorizar SIEMPRE deja rastro: salga o no salga el correo.

    Sin esto no hay forma de auditar. Es el Defecto 2: hoy el resultado del
    envío solo viaja en la respuesta HTTP y se pierde ahí.
    """
    filas = []

    monkeypatch.setattr(svc, "_enviar_por_resend", lambda *a, **k: {
        "resend_id": None, "estado": "error_envio", "error": "resend 403: nope"})
    monkeypatch.setattr(svc, "_registrar_correo_corte",
                        lambda oc_id, **kw: filas.append({"oc_id": oc_id, **kw}))
    monkeypatch.setattr(svc, "_sb", lambda: _SupabaseFalso())
    monkeypatch.setattr(svc, "obtener_orden_corte", lambda _id: {
        "id": "oc-1", "consecutivo": "2608-0009", "estado": "autorizada",
        "destinatarios_correo": ["malo@ejemplo.com"], "indicaciones": "",
        "curva_trazo": {}, "referencia": {"codigo_referencia": "93634"},
    })

    res = svc.autorizar_orden_corte("oc-1", destinatarios=["malo@ejemplo.com"],
                                    usuario="diseno@maledenim.com")

    assert len(filas) == 1, "el intento fallido tiene que quedar registrado"
    assert filas[0]["resultado"]["estado"] == "error_envio"
    assert res["correo"]["estado"] == "error_envio"
    assert res["correo"]["enviado_por"] is None, \
        "un fallo NO puede reportarse como enviado"
```

Y agregar el doble de Supabase, arriba en el mismo archivo (después de `_RespuestaFalsa`):

```python
class _SupabaseFalso:
    """Traga cualquier .table(...).update(...).eq(...).execute() sin hacer nada."""

    def table(self, _nombre):
        return self

    def update(self, *_a, **_k):
        return self

    def insert(self, *_a, **_k):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": []})()
```

- [ ] **Step 2: Correr la prueba para verificar que falla**

Run: `.venv/bin/python -m pytest tests/test_correo_orden_corte.py::test_autorizar_registra_el_intento_incluso_cuando_falla -v`
Expected: FAIL con `AttributeError: ... has no attribute '_registrar_correo_corte'`

- [ ] **Step 3: Implementar el registro**

Agregar al bloque de la Task 2, después de `_enviar_por_resend`:

```python
def _registrar_correo_corte(oc_id: str, *, destinatarios: list[str], asunto: str,
                            motivo: str, resultado: dict,
                            usuario: str) -> Optional[dict]:
    """Deja una fila en `correos_orden_corte` por cada intento de envío.

    No lanza: si el registro falla, el correo ya salió y perder la bitácora no
    puede tumbar la autorización de la orden.
    """
    sb = _sb()
    if sb is None:
        return None
    fila = {
        "orden_corte_id": oc_id,
        "destinatarios": destinatarios,
        "asunto": asunto,
        "motivo": motivo,
        "resend_id": resultado.get("resend_id"),
        "estado": resultado.get("estado") or "error_envio",
        "error": resultado.get("error"),
        "enviado_por": usuario,
        "estado_actualizado_at": _now_iso(),
    }
    try:
        r = (sb.table("correos_orden_corte").insert(fila).execute()).data
        return (r or [None])[0]
    except Exception as e:
        log.warning(f"[corte.correo] no pude registrar el envío de {oc_id}: {str(e)[:200]}")
        return None
```

- [ ] **Step 4: Reemplazar el bloque de envío de `autorizar_orden_corte`**

En `backend/services/produccion.py`, reemplazar desde la línea 3164
(`dest = destinatarios if destinatarios is not None ...`) hasta la 3208
(`return {**obtener_orden_corte(oc_id), "correo": resultado}`) por:

```python
    dest = destinatarios if destinatarios is not None else (oc.get("destinatarios_correo") or [])

    envio = _enviar_por_resend(dest, asunto, body)
    _registrar_correo_corte(oc_id, destinatarios=dest, asunto=asunto,
                            motivo=motivo, resultado=envio, usuario=usuario)

    # El `mailto` deja de ser un redirect automático que aparenta funcionar:
    # ahora es una salida manual que el frontend ofrece SOLO si el envío falló.
    from urllib.parse import quote
    mailto_url = (f"mailto:{','.join(dest) if dest else ''}"
                  f"?subject={quote(asunto)}&body={quote(body)}")

    resultado = {
        "asunto": asunto,
        "body": body,
        "destinatarios": dest,
        "estado": envio["estado"],            # 'enviado' | 'error_envio'
        "error": envio["error"],
        "resend_id": envio["resend_id"],
        "enviado_por": "resend" if envio["estado"] == "enviado" else None,
        "mailto_url": mailto_url,
    }
    return {**obtener_orden_corte(oc_id), "correo": resultado}
```

Y en la firma de `autorizar_orden_corte` (línea ~3081), agregar el parámetro `motivo`:

```python
def autorizar_orden_corte(oc_id: str, *, destinatarios: Optional[list[str]] = None,
                          mensaje_extra: Optional[str] = None,
                          solo_reenviar: bool = False,
                          motivo: str = "autorizacion",
                          usuario: str) -> dict:
```

- [ ] **Step 5: Pasar el motivo correcto en el reenvío por indicaciones**

En `actualizar_indicaciones_corte` (línea ~2174), agregar `motivo` a la llamada:

```python
            res = autorizar_orden_corte(
                oc_id, usuario=usuario or (previo.get("autorizada_por") or ""),
                mensaje_extra="(Indicaciones actualizadas por diseño)",
                motivo="reenvio_indicaciones",
                solo_reenviar=True)
```

Y actualizar la condición de la línea ~2179, que hoy mira `enviado_por == "resend"`:

```python
            reenviado = ((res.get("correo") or {}).get("estado") == "enviado")
```

- [ ] **Step 6: Correr toda la suite**

Run: `.venv/bin/python -m pytest tests/test_correo_orden_corte.py -v`
Expected: PASS — 17 pruebas.

- [ ] **Step 7: Commit**

```bash
git add backend/services/produccion.py tests/test_correo_orden_corte.py
git commit -m "feat(produccion): registrar cada intento de envio y quitar el fallback silencioso"
```

---

### Task 5: Consultar el estado de entrega a Resend

**Files:**
- Modify: `backend/services/produccion.py` (bloque de la Task 2)
- Test: `tests/test_correo_orden_corte.py`

**Interfaces:**
- Consumes: `_estado_desde_last_event`, `_ESTADOS_DEFINITIVOS` (Task 2).
- Produces:
  - `_consultar_estado_resend(resend_id: str) -> Optional[str]` — devuelve `last_event` o `None`.
  - `refrescar_estados_correo(correos: list[dict]) -> list[dict]` — devuelve la lista con
    los estados en curso actualizados y persistidos.

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `tests/test_correo_orden_corte.py`:

```python
def test_no_reconsulta_un_correo_ya_entregado(monkeypatch):
    """Un estado definitivo no cambia: consultarlo otra vez es gasto puro."""
    llamadas = []
    monkeypatch.setattr(svc, "_consultar_estado_resend",
                        lambda rid: llamadas.append(rid))

    correos = [{"id": "c1", "resend_id": "abc", "estado": "entregado"}]
    r = svc.refrescar_estados_correo(correos)

    assert llamadas == [], "no debió llamar a Resend"
    assert r[0]["estado"] == "entregado"


def test_reconsulta_un_correo_en_curso_y_persiste(monkeypatch):
    """'enviado' todavía puede volverse 'rebotado': hay que preguntar."""
    guardado = {}
    monkeypatch.setattr(svc, "_consultar_estado_resend", lambda rid: "bounced")
    monkeypatch.setattr(svc, "_guardar_estado_correo",
                        lambda cid, estado: guardado.update({cid: estado}))

    correos = [{"id": "c1", "resend_id": "abc", "estado": "enviado"}]
    r = svc.refrescar_estados_correo(correos)

    assert r[0]["estado"] == "rebotado"
    assert guardado == {"c1": "rebotado"}


def test_sin_resend_id_no_consulta(monkeypatch):
    """Un error_envio nunca creó un correo en Resend: no hay qué consultar."""
    llamadas = []
    monkeypatch.setattr(svc, "_consultar_estado_resend",
                        lambda rid: llamadas.append(rid))

    correos = [{"id": "c1", "resend_id": None, "estado": "error_envio"}]
    r = svc.refrescar_estados_correo(correos)

    assert llamadas == []
    assert r[0]["estado"] == "error_envio"


def test_si_resend_no_responde_conserva_el_estado(monkeypatch):
    """Que Resend esté caído no puede borrar lo que ya sabíamos."""
    monkeypatch.setattr(svc, "_consultar_estado_resend", lambda rid: None)

    correos = [{"id": "c1", "resend_id": "abc", "estado": "enviado"}]
    r = svc.refrescar_estados_correo(correos)

    assert r[0]["estado"] == "enviado"
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_correo_orden_corte.py -k "refrescar or reconsulta or resend_id" -v`
Expected: FAIL con `AttributeError: ... has no attribute 'refrescar_estados_correo'`

- [ ] **Step 3: Implementar la consulta**

Agregar al bloque de la Task 2, después de `_registrar_correo_corte`:

```python
def _consultar_estado_resend(resend_id: str) -> Optional[str]:
    """`last_event` del correo según Resend, o None si no se pudo saber.

    GET /emails/{id} — https://resend.com/docs/api-reference/emails/retrieve-email
    """
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not resend_key or not resend_id:
        return None
    try:
        import httpx
        r = httpx.get(f"https://api.resend.com/emails/{resend_id}",
                      headers={"Authorization": f"Bearer {resend_key}"},
                      timeout=10.0)
        if r.status_code >= 400:
            return None
        return ((r.json() or {}).get("last_event"))
    except Exception as e:
        log.warning(f"[corte.correo] no pude consultar {resend_id}: {str(e)[:150]}")
        return None


def _guardar_estado_correo(correo_id: str, estado: str) -> None:
    """Persiste el estado nuevo. No lanza: es caché, no es la verdad."""
    sb = _sb()
    if sb is None:
        return
    try:
        (sb.table("correos_orden_corte")
           .update({"estado": estado, "estado_actualizado_at": _now_iso()})
           .eq("id", correo_id).execute())
    except Exception as e:
        log.warning(f"[corte.correo] no pude guardar el estado de {correo_id}: {str(e)[:150]}")


def refrescar_estados_correo(correos: list[dict]) -> list[dict]:
    """Actualiza contra Resend solo los envíos que todavía pueden cambiar.

    Los definitivos no se consultan, y sin `resend_id` no hay nada que
    consultar (un `error_envio` nunca llegó a crear un correo en Resend).
    """
    salida = []
    for c in correos or []:
        c = dict(c)
        estado = c.get("estado") or "enviado"
        rid = c.get("resend_id")
        if rid and estado not in _ESTADOS_DEFINITIVOS:
            evento = _consultar_estado_resend(rid)
            if evento:
                nuevo = _estado_desde_last_event(evento)
                if nuevo != estado:
                    _guardar_estado_correo(c["id"], nuevo)
                    c["estado"] = nuevo
        salida.append(c)
    return salida
```

- [ ] **Step 4: Correr toda la suite**

Run: `.venv/bin/python -m pytest tests/test_correo_orden_corte.py -v`
Expected: PASS — 21 pruebas.

- [ ] **Step 5: Commit**

```bash
git add backend/services/produccion.py tests/test_correo_orden_corte.py
git commit -m "feat(produccion): consultar a Resend el estado de entrega bajo demanda"
```

---

### Task 6: Exponer el historial y el endpoint de reenvío

**Files:**
- Modify: `backend/services/produccion.py` (bloque de la Task 2 + `obtener_orden_corte:2367`)
- Modify: `backend/api/produccion.py` (junto a `autorizar_corte`, línea ~917)
- Test: `tests/test_correo_orden_corte.py`

**Interfaces:**
- Consumes: `refrescar_estados_correo` (Task 5), `autorizar_orden_corte` con `motivo` (Task 4).
- Produces:
  - `listar_correos_corte(oc_id: str) -> list[dict]`
  - `reenviar_correo_corte(oc_id, *, destinatarios, mensaje_extra, usuario) -> dict`
  - `POST /api/produccion/corte/{oc_id}/reenviar-correo`
  - `obtener_orden_corte` devuelve la clave `correos` (lista, más reciente primero).

- [ ] **Step 1: Escribir la prueba que falla**

Agregar a `tests/test_correo_orden_corte.py`:

```python
def test_reenviar_no_toca_la_autorizacion(monkeypatch):
    """Reenviar corrige el destinatario; NO re-autoriza la orden.

    `fecha_autorizacion` costó trabajo arreglarla (antes salía siempre None).
    Un reenvío por dedazo no puede pisar la fecha en que se autorizó de verdad.
    """
    llamada = {}

    def _fake_autorizar(oc_id, **kw):
        llamada.update(kw)
        return {"id": oc_id, "correo": {"estado": "enviado"}}

    monkeypatch.setattr(svc, "autorizar_orden_corte", _fake_autorizar)

    svc.reenviar_correo_corte("oc-1", destinatarios=["bueno@ejemplo.com"],
                              mensaje_extra=None, usuario="diseno@maledenim.com")

    assert llamada["solo_reenviar"] is True
    assert llamada["motivo"] == "reenvio_manual"
    assert llamada["destinatarios"] == ["bueno@ejemplo.com"]
```

- [ ] **Step 2: Correr la prueba para verificar que falla**

Run: `.venv/bin/python -m pytest tests/test_correo_orden_corte.py::test_reenviar_no_toca_la_autorizacion -v`
Expected: FAIL con `AttributeError: ... has no attribute 'reenviar_correo_corte'`

- [ ] **Step 3: Implementar el listado y el reenvío**

Agregar al bloque de la Task 2, después de `refrescar_estados_correo`:

```python
def listar_correos_corte(oc_id: str) -> list[dict]:
    """Historial de envíos de la orden, más reciente primero, ya refrescado."""
    sb = _sb()
    if sb is None:
        return []
    try:
        r = (sb.table("correos_orden_corte")
               .select("*")
               .eq("orden_corte_id", oc_id)
               .order("created_at", desc=True)
               .execute()).data or []
    except Exception as e:
        log.warning(f"[corte.correo] no pude listar los correos de {oc_id}: {str(e)[:150]}")
        return []
    return refrescar_estados_correo(r)


def reenviar_correo_corte(oc_id: str, *, destinatarios: Optional[list[str]],
                          mensaje_extra: Optional[str],
                          usuario: str) -> dict:
    """Reenvía el correo, típicamente a OTRA dirección porque la primera estaba mal.

    Va por `solo_reenviar=True` para no pisar `fecha_autorizacion`, pero sí
    actualiza `destinatarios_correo`: la corrección queda guardada y el
    siguiente reenvío ya sale bien por defecto.
    """
    return autorizar_orden_corte(
        oc_id,
        destinatarios=destinatarios,
        mensaje_extra=mensaje_extra,
        solo_reenviar=True,
        motivo="reenvio_manual",
        usuario=usuario,
    )
```

- [ ] **Step 4: Adjuntar el historial al detalle de la orden**

En `obtener_orden_corte` (línea ~2367), antes del `return` final del diccionario de la
orden, agregar la clave `correos`:

```python
    oc["correos"] = listar_correos_corte(oc_id)
```

(Colocarlo junto a donde se arma `rollos`, siguiendo el patrón del resto de la función.)

- [ ] **Step 5: Agregar el endpoint**

En `backend/api/produccion.py`, después de `autorizar_corte` (línea ~935), agregar:

```python
class ReenviarCorreoBody(BaseModel):
    destinatarios: Optional[list[str]] = None
    mensaje_extra: Optional[str] = None


@router.post("/corte/{oc_id}/reenviar-correo")
def reenviar_correo_corte(
    oc_id: str,
    body: ReenviarCorreoBody,
    user: CurrentUser = Depends(require_permission("produccion_corte", "modificar")),
) -> dict:
    """Reenvía el correo de la orden, normalmente a una dirección corregida.

    No re-autoriza: `fecha_autorizacion` y `autorizada_por` quedan intactas.
    """
    try:
        oc = svc.reenviar_correo_corte(
            oc_id,
            destinatarios=body.destinatarios,
            mensaje_extra=body.mensaje_extra,
            usuario=user.email,
        )
        return {"ok": True, **oc}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"reenviar_correo: {str(e)[:200]}")
```

- [ ] **Step 6: Correr toda la suite del backend**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — la suite completa, sin regresiones.

- [ ] **Step 7: Commit**

```bash
git add backend/services/produccion.py backend/api/produccion.py tests/test_correo_orden_corte.py
git commit -m "feat(produccion): historial de correos en el detalle y endpoint de reenvio"
```

---

### Task 7: Estado, historial y botón de reenviar en el detalle

**Files:**
- Modify: `frontend/app/produccion/corte/[id]/page.tsx:609-628` (el `onSuccess` de `autorizar`) y la zona de destinatarios (línea ~985)

**Interfaces:**
- Consumes: `correo.estado` / `correo.error` de `POST /autorizar` (Task 4), `oc.correos` del
  detalle (Task 6), `POST /corte/{id}/reenviar-correo` (Task 6).
- Produces: nada que consuman otras tareas.

- [ ] **Step 1: Agregar el tipo del historial**

En el tipo de la orden que usa la página, agregar:

```ts
type CorreoEnvio = {
  id: string;
  destinatarios: string[];
  motivo: "autorizacion" | "reenvio_indicaciones" | "reenvio_manual";
  estado: "enviado" | "entregado" | "rebotado" | "spam" | "demorado"
        | "fallido" | "suprimido" | "error_envio";
  error: string | null;
  enviado_por: string | null;
  created_at: string;
};
```

- [ ] **Step 2: Agregar el mapa de presentación**

```tsx
const ESTADO_CORREO: Record<CorreoEnvio["estado"], { icono: string; texto: string; tono: string }> = {
  enviado:     { icono: "🕐", texto: "Enviado, esperando confirmación", tono: "text-muted-foreground" },
  entregado:   { icono: "✅", texto: "Entregado",                        tono: "text-green-600" },
  rebotado:    { icono: "⚠️", texto: "Rebotó — la dirección no existe",  tono: "text-amber-600" },
  spam:        { icono: "⚠️", texto: "Marcado como spam",                tono: "text-amber-600" },
  demorado:    { icono: "🕐", texto: "Demorado, reintentando",           tono: "text-muted-foreground" },
  fallido:     { icono: "❌", texto: "No se entregó",                    tono: "text-red-600" },
  suprimido:   { icono: "❌", texto: "Bloqueado por Resend",             tono: "text-red-600" },
  error_envio: { icono: "❌", texto: "No se pudo enviar",                tono: "text-red-600" },
};
```

- [ ] **Step 3: Cambiar el `onSuccess` para que no mienta**

Reemplazar el bloque de las líneas 617-627 por:

```tsx
    onSuccess: (data) => {
      setErr("");
      const c = data.correo;
      if (c?.estado === "enviado") {
        setMsg(`Orden autorizada. Correo enviado a ${c.destinatarios.join(", ")}.`);
      } else if (c) {
        // Antes esto hacía window.location.href = c.mailto_url, que en Chrome
        // con Gmail web no hace NADA: el correo no salía y la pantalla decía
        // "Orden autorizada" igual. Ahora el fallo se ve.
        setErr(`La orden quedó autorizada, pero el correo NO salió: ${c.error ?? "error desconocido"}`);
      } else {
        setMsg("Orden autorizada.");
      }
      qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
    },
```

- [ ] **Step 4: Mostrar el historial bajo los destinatarios**

Debajo del input de destinatarios (línea ~985), agregar:

```tsx
{(oc.correos ?? []).length > 0 && (
  <div className="mt-2 space-y-1 text-sm">
    {(oc.correos ?? []).map((c) => {
      const e = ESTADO_CORREO[c.estado];
      return (
        <div key={c.id} className={`flex items-center gap-2 ${e.tono}`}>
          <span>{e.icono}</span>
          <span>{e.texto} · {c.destinatarios.join(", ")}</span>
          {c.error && <span className="opacity-70">— {c.error}</span>}
        </div>
      );
    })}
  </div>
)}
{(oc.correos ?? []).length === 0 && oc.estado === "autorizada" && (
  <p className="mt-2 text-sm text-muted-foreground">Sin registro de envío.</p>
)}
```

- [ ] **Step 5: Agregar el botón de reenviar**

```tsx
const reenviar = useMutation({
  mutationFn: (dest: string[]) =>
    api.post<{ correo?: { estado: string; error: string | null; destinatarios: string[] } }>(
      `/api/produccion/corte/${id}/reenviar-correo`,
      { destinatarios: dest, mensaje_extra: null },
    ),
  onSuccess: (data) => {
    const c = data.correo;
    if (c?.estado === "enviado") {
      setErr("");
      setMsg(`Correo reenviado a ${c.destinatarios.join(", ")}.`);
    } else {
      setErr(`No se pudo reenviar: ${c?.error ?? "error desconocido"}`);
    }
    qc.invalidateQueries({ queryKey: ["produccion", "corte", id] });
  },
  onError: (e: Error) => { setErr(e.message); setMsg(""); },
});
```

Con el botón precargado con el correo REGISTRADO del cortador, no con el que falló:

```tsx
<Button
  variant="outline"
  size="sm"
  onClick={() => setDestinatariosEdit(oc.responsable_email ?? "")}
>
  Reenviar
</Button>
```

El botón solo llena el campo; el envío lo dispara `reenviar.mutate(...)` con el
contenido del campo, para que el diseñador vea a dónde va antes de mandarlo.

- [ ] **Step 6: Verificar que compila**

Run: `cd frontend && npm run build`
Expected: build exitoso, sin errores de TypeScript.
(`tsc --noEmit` NO sirve aquí: no detecta imports duplicados. Solo `next build`
reproduce lo que hace Vercel.)

- [ ] **Step 7: Commit**

```bash
git add frontend/app/produccion/corte/\[id\]/page.tsx
git commit -m "feat(produccion): mostrar si el correo salio, llego o fallo, y poder reenviarlo"
```

---

### Task 8: Aviso cuando el destinatario no cuadra

**Files:**
- Modify: `frontend/app/produccion/corte/[id]/page.tsx` (dentro de `autorizar.mutationFn` y `reenviar`)

**Interfaces:**
- Consumes: `/api/produccion/usuarios-correo` (ya existe, línea 574 de la página) y
  `oc.responsable_email`.
- Produces: nada.

Se resuelve solo en el frontend: la página ya carga la lista de usuarios y ya tiene la
orden con `responsable_email`. No requiere backend.

- [ ] **Step 1: Escribir el chequeo**

```tsx
/** Destinatarios que no son ni el cortador de la orden ni un usuario registrado. */
const destinatariosRaros = (dest: string[]): string[] => {
  const conocidos = new Set(
    [
      oc.responsable_email,
      ...((usuarios.data?.usuarios ?? []).map((u) => u.email)),
    ]
      .filter(Boolean)
      .map((e) => (e as string).trim().toLowerCase()),
  );
  return dest.filter((d) => !conocidos.has(d.trim().toLowerCase()));
};
```

- [ ] **Step 2: Pedir confirmación antes de mandar**

Al comienzo de `autorizar.mutationFn` (y en el disparo de `reenviar`), después de
calcular `dest`:

```tsx
const raros = destinatariosRaros(dest);
if (raros.length > 0) {
  const nombre = oc.responsable || "el cortador";
  const correoBueno = oc.responsable_email || "sin correo registrado";
  const ok = window.confirm(
    `Vas a enviar a ${raros.join(", ")}, que no es el correo de ${nombre} (${correoBueno}).\n\n` +
    `Así fue como la orden 2607-0017 salió a la dirección equivocada.\n\n¿Seguro?`,
  );
  if (!ok) throw new Error("cancelado");
}
```

Es aviso, no bloqueo: se puede continuar. Mandar a un correo externo es un caso
legítimo y raro; el objetivo es que sea deliberado.

- [ ] **Step 3: Que "cancelado" no se vea como error**

En el `onError` de ambas mutaciones:

```tsx
onError: (e: Error) => {
  if (e.message === "cancelado") return;
  setErr(e.message);
  setMsg("");
},
```

- [ ] **Step 4: Verificar que compila**

Run: `cd frontend && npm run build`
Expected: build exitoso.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/produccion/corte/\[id\]/page.tsx
git commit -m "feat(produccion): avisar cuando el destinatario no es el correo del cortador"
```

---

### Task 9: Badge de estado en la lista de cortes

**Files:**
- Modify: `frontend/app/produccion/corte/page.tsx`
- Modify: `backend/services/produccion.py` (`listar_ordenes_corte`, línea ~2194)

**Interfaces:**
- Consumes: la tabla `correos_orden_corte` (Task 1).
- Produces: cada orden del listado lleva `correo_estado: string | null`.

- [ ] **Step 1: Agregar el estado al listado del backend**

En `listar_ordenes_corte`, después de traer las órdenes, adjuntar el estado del último
correo de cada una con **una sola consulta** (no N+1):

```python
    ids = [o["id"] for o in ordenes]
    ultimo: dict[str, str] = {}
    if ids:
        try:
            filas = (sb.table("correos_orden_corte")
                       .select("orden_corte_id,estado,created_at")
                       .in_("orden_corte_id", ids)
                       .order("created_at", desc=True)
                       .execute()).data or []
            for f in filas:                      # ordenadas desc: la 1ª es la última
                ultimo.setdefault(f["orden_corte_id"], f["estado"])
        except Exception as e:
            log.warning(f"[corte] no pude traer los estados de correo: {str(e)[:150]}")
    for o in ordenes:
        o["correo_estado"] = ultimo.get(o["id"])
```

En el listado **no** se consulta a Resend — sería una llamada por orden. El estado que
muestra es el último persistido; al abrir la orden se refresca.

- [ ] **Step 2: Verificar que el backend sigue verde**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 3: Mostrar el badge en la lista**

En `frontend/app/produccion/corte/page.tsx`, en la fila de cada orden:

```tsx
{orden.correo_estado && (
  <span
    className={`text-xs ${ESTADO_CORREO[orden.correo_estado]?.tono ?? ""}`}
    title={ESTADO_CORREO[orden.correo_estado]?.texto ?? ""}
  >
    {ESTADO_CORREO[orden.correo_estado]?.icono}
  </span>
)}
```

Mover `ESTADO_CORREO` (Task 7, Step 2) a un archivo compartido —
`frontend/lib/correo-estado.ts`— e importarlo en las dos páginas, en vez de duplicarlo.

- [ ] **Step 4: Verificar que compila**

Run: `cd frontend && npm run build`
Expected: build exitoso.

- [ ] **Step 5: Commit**

```bash
git add frontend/ backend/services/produccion.py
git commit -m "feat(produccion): badge del estado del correo en la lista de cortes"
```

---

## Verificación final

- [ ] `.venv/bin/python -m pytest tests/ -q` — toda la suite en verde.
- [ ] `cd frontend && npm run build` — build limpio.
- [ ] **Prueba de humo en producción:** autorizar una orden de prueba con un destinatario
  inventado (`noexiste@maledenim.com`), confirmar que aparece 🕐 y que a los pocos
  minutos pasa a ⚠️ rebotado. Es el ciclo completo que hoy no existe.
- [ ] Confirmar que las órdenes viejas muestran "Sin registro de envío" y no un estado
  inventado.
