# Barrido de Melonn por tramos con cursor — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que un barrido completo del listado de Melonn se arme entre varios ticks con un cursor persistido, para que un fallo de página cueste esa página y no el barrido entero.

**Architecture:** El cursor vive en una fila propia (Supabase `melonn_cache` id=3, espejo en SQLite `melonn_barrido`). Cada tick trae un TRAMO de páginas, lo fusiona sobre el caché vivo y avanza el cursor. Al llegar al final se reconcilian las bajas y se sella el reloj de "barrido COMPLETO", que es el único que dice si el tablero es auditable.

**Tech Stack:** Python 3.11, pytest, SQLite (stdlib), Supabase (`supabase-py`), `requests`.

**Spec:** `docs/superpowers/specs/2026-08-06-melonn-barrido-por-tramos-design.md`

## Global Constraints

- **Todo el código y los comentarios van en español.** Es la convención del módulo.
- **Nunca romper el candado anti-vaciado** de `_cache_guardar` (`_CAIDA_MAXIMA = 0.40`, `_MINIMO_ABSOLUTO = 50`). No usar `forzar=True` en ninguna ruta nueva.
- **Nunca guardar un barrido incompleto como si fuera completo.** El reloj `_marcar_fetch_api()` se sella SOLO al cerrar un barrido.
- **El corte por fecha de `4ca695d` se conserva tal cual.** Su contador (`paginas_fuera_ventana`) pasa a persistirse; su lógica no cambia.
- **El orden importa en la fusión:** `_marcar_despacho_observado(p, prev)` se llama **ANTES** de heredar `_CAMPOS_ENRIQUECIDOS`. Heredar primero copiaría la fecha vieja y el estado anterior dejaría de ser visible. Está documentado en `_heredar_enriquecidos` y es la causa de una pérdida de datos irrecuperable si se invierte.
- **No asumir el orden del listado de Melonn.** No está documentado que devuelva del más nuevo al más viejo.
- **Cuota Melonn:** 10.000 peticiones/día, 1 req/s. `_MAX_RPS = 0.5` (2 s entre GETs). Ninguna prueba debe pegarle a la API real.
- **Constantes que NO se tocan:** `_PAGE_SIZE = 100`, `_MAX_PAGES = 60`, `_CACHE_TTL = 7200`, `FETCH_AMARILLO_MIN = 180`, `FETCH_ROJO_MIN = 360`.

---

## Estructura de archivos

| Archivo | Responsabilidad | Tareas |
|---|---|---|
| `tests/conftest.py` | Añadir `src/` a `sys.path` (hoy solo añade la raíz) | 1 |
| `tests/test_melonn_barrido.py` | **Nuevo.** Todo el arnés y las pruebas del barrido | 1-7 |
| `src/melonn_client.py` | Cursor, tramo, fusión, reconciliación, relojes | 2-8 |
| `backend/core/scheduler.py` | Llamar al tick en modo tramo | 8 |
| `backend/services/salud_logistica.py` | Que "a mitad de barrido" no sea rojo; hallazgo `barrido_atascado` | 9 |
| `.gitignore` | Ignorar `.venv/` | 1 |

`src/melonn_client.py` ya tiene ~2.800 líneas. Este plan **no** lo parte: la otra tarea (partir el caché de 6,5 MB) es la que va a moverlo, y hacer dos reestructuraciones a la vez sobre un módulo en producción es cómo se pierde la trazabilidad de qué rompió qué. Todo lo nuevo va agrupado bajo un encabezado `── Barrido por tramos ──` para que ese corte futuro sea mecánico.

---

## Task 1: Entorno de pruebas y caracterización del bug

Antes de cambiar nada hay que poder ejecutar pruebas, y hay que **dejar escrito en un test el comportamiento de hoy** — incluido el bug. Esos tests son la red que dice si el refactor de la Tarea 3 cambió algo sin querer.

**Files:**
- Modify: `tests/conftest.py`
- Modify: `.gitignore`
- Create: `tests/test_melonn_barrido.py`

**Interfaces:**
- Consumes: nada.
- Produces: helper `_pedido(n, dias_atras=1, code=7)` y el patrón de monkeypatch de `mc._get` / `mc._DB_PATH` que usan todas las tareas siguientes.

- [ ] **Step 1: Crear el entorno**

En la raíz del repo. `requirements.txt` completo trae streamlit, playwright y pandas y tarda mucho; para este módulo bastan dos paquetes (verificado: `melonn_client` solo importa `requests` a nivel de módulo, el resto es stdlib, y `supabase` está dentro de un `try`).

```bash
python3 -m venv .venv && ./.venv/bin/pip install -q requests pytest && ./.venv/bin/python -c "import sys; sys.path[:0]=['.','src']; import melonn_client; print('IMPORT OK')"
```

Esperado: `IMPORT OK`

> Sin credenciales de Supabase `_sb_ok()` es `False` y todo el camino de Supabase se salta solo — las pruebas corren contra SQLite. Es lo que queremos. Producción usa Python 3.11 (`.python-version`); un intérprete más nuevo también sirve para estas pruebas, solo emite un `DeprecationWarning` por `datetime.utcnow()`.

- [ ] **Step 2: Ignorar el venv**

Añadir al final de `.gitignore`:

```
# Entorno virtual local
.venv/
```

- [ ] **Step 3: Que las pruebas puedan importar `melonn_client`**

`tests/conftest.py` hoy solo añade la raíz del repo. `melonn_client` vive en `src/`, fuera del paquete `backend`. Reemplazar el archivo completo por:

```python
"""Asegura que la raíz del repo y `src/` estén en sys.path.

La raíz, para importar `backend`. Y `src/`, porque `melonn_client` vive fuera
del paquete `backend` y en producción lo carga `salud_logistica._mc()`
insertando esa misma ruta a mano.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for ruta in (RAIZ, RAIZ / "src"):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))
```

- [ ] **Step 4: Escribir las pruebas de caracterización**

Crear `tests/test_melonn_barrido.py`:

```python
"""Barrido del listado de Melonn por tramos con cursor.

Las dos primeras pruebas describen el comportamiento de ANTES del cursor, y la
segunda es el bug que este trabajo viene a arreglar: si falla una página, se
pierde todo lo que ya se había traído. Se conservan porque son la red que dice
si el refactor cambió algo sin querer.
"""
from datetime import date, timedelta

import melonn_client as mc


def _pedido(n: int, dias_atras: int = 1, code: int = 7) -> dict:
    """Un pedido crudo del listado, como lo devuelve GET /sell-orders.

    code=7 es "Shipped - in transit": operativo y dentro de la whitelist, así
    que sobrevive todos los filtros y llega al tablero.
    """
    return {
        "internal_order_number": f"{n}",
        "external_order_number": f"T{n}",
        "creation_date": (date.today() - timedelta(days=dias_atras)).isoformat(),
        "sell_order_state": {"code": code, "name": "Shipped - in transit"},
        "payment_on_delivery_amount": "100000",
        "shipping_method": {"code": "SM", "name": "Envia"},
        "warehouse": {"code": "MED-2", "name": "Medellin"},
    }


def _paginas_falsas(monkeypatch, paginas: dict, fallan: set = ()):
    """Sustituye mc._get por un listado simulado. `fallan` son números de
    página que devuelven None, como haría un 429 o un timeout."""
    pedidas = []

    def fake_get(path, params=None):
        p = params["page"]
        pedidas.append(p)
        if p in fallan:
            return None
        return {"data": paginas.get(p, [])}

    monkeypatch.setattr(mc, "_get", fake_get)
    return pedidas


def _aislar_disco(monkeypatch, tmp_path):
    """El caché SQLite por defecto apunta a data/db/ del repo. Las pruebas no
    pueden depender del estado de la máquina."""
    monkeypatch.setattr(mc, "_DB_PATH", tmp_path / "melonn.db")


def test_barrido_completo_trae_todas_las_paginas(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [_pedido(100 + i) for i in range(100)],
        2: [_pedido(200 + i) for i in range(10)],   # incompleta = última
    }
    pedidas = _paginas_falsas(monkeypatch, paginas)

    res = mc._fetch_api_filtrado()

    assert pedidas == [0, 1, 2]
    assert len(res) == 210
    assert mc.ultimo_fetch()["motivo_fin"] == "ultima_pagina"
    assert mc.ultimo_fetch()["completo"] is True


def test_una_pagina_fallida_pierde_el_barrido_entero(tmp_path, monkeypatch):
    """EL BUG. 200 pedidos ya traídos se descartan porque falló la página 2.

    Descartarlos es lo correcto —mejor viejo que mutilado— pero el costo de un
    solo fallo no debería ser el barrido completo. Eso es lo que arregla el
    cursor: a partir de la Tarea 6 esas 2 páginas quedan fusionadas y el tick
    siguiente reintenta solo la 2.
    """
    _aislar_disco(monkeypatch, tmp_path)
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [_pedido(100 + i) for i in range(100)],
    }
    _paginas_falsas(monkeypatch, paginas, fallan={2})

    res = mc._fetch_api_filtrado()

    assert res == []
    assert mc.ultimo_fetch()["completo"] is False
    assert mc.ultimo_fetch()["motivo_fin"].startswith("fallo_get_pagina_2")


def test_corte_por_fecha_para_al_salir_de_la_ventana(tmp_path, monkeypatch):
    """El corte de 4ca695d: DOS páginas llenas seguidas sin nada en ventana."""
    _aislar_disco(monkeypatch, tmp_path)
    viejo = lambda n: _pedido(n, dias_atras=200, code=8)   # entregado y viejo
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [viejo(100 + i) for i in range(100)],
        2: [viejo(200 + i) for i in range(100)],
        3: [viejo(300 + i) for i in range(100)],
    }
    pedidas = _paginas_falsas(monkeypatch, paginas)

    res = mc._fetch_api_filtrado()

    assert pedidas == [0, 1, 2]          # no pide la 3
    assert len(res) == 100
    assert mc.ultimo_fetch()["motivo_fin"] == "fuera_de_ventana"
    assert mc.ultimo_fetch()["completo"] is True
```

- [ ] **Step 5: Correr las pruebas**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v
```

Esperado: `3 passed`. Las tres describen el código tal como está hoy — si alguna falla, el árbol no está en `origin/main @ a49e0f2`, hay que parar y revisar antes de seguir.

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_melonn_barrido.py .gitignore
git commit -m "test(logistica): arnes del barrido de Melonn y el bug que cuesta el barrido entero"
```

---

## Task 2: El almacén del cursor

Guardar y leer el estado del barrido, con lease para que dos réplicas de Railway no avancen el cursor a la vez.

**Files:**
- Modify: `src/melonn_client.py` (encabezado nuevo después de `_edad_fetch_api_sq`, alrededor de la línea 987)
- Modify: `tests/test_melonn_barrido.py`

**Interfaces:**
- Consumes: `_sb()`, `_SB_TABLA`, `_conn()`, `_parse_iso_naive` (ya existen).
- Produces:
  - `_SB_FILA_BARRIDO: int = 3`
  - `_BARRIDO_VACIO: dict`
  - `_barrido_leer() -> dict`
  - `_barrido_guardar(estado: dict) -> None`
  - `_barrido_tomar_lease(estado: dict, worker: str) -> bool`

- [ ] **Step 1: Escribir las pruebas que fallan**

Añadir a `tests/test_melonn_barrido.py`:

```python
def test_cursor_arranca_vacio(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    assert e["generacion"] == 0
    assert e["pagina"] == 0
    assert e["vistas"] == []
    assert e["ultimo_completo_en"] is None


def test_cursor_guarda_y_lee(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e.update({"generacion": 7, "pagina": 22, "vistas": ["M1", "M2"],
              "paginas_fuera_ventana": 1})
    mc._barrido_guardar(e)

    leido = mc._barrido_leer()
    assert leido["generacion"] == 7
    assert leido["pagina"] == 22
    assert leido["vistas"] == ["M1", "M2"]
    assert leido["paginas_fuera_ventana"] == 1


def test_el_lease_bloquea_a_otro_worker(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    assert mc._barrido_tomar_lease(e, "worker-A") is True

    e2 = mc._barrido_leer()
    assert mc._barrido_tomar_lease(e2, "worker-B") is False


def test_el_mismo_worker_puede_renovar_su_lease(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    assert mc._barrido_tomar_lease(e, "worker-A") is True
    assert mc._barrido_tomar_lease(mc._barrido_leer(), "worker-A") is True


def test_un_lease_vencido_no_bloquea(tmp_path, monkeypatch):
    """Si un worker muere a mitad de tramo, el cursor no puede quedar tomado
    para siempre."""
    from datetime import datetime, timedelta
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e["lease_worker"] = "worker-muerto"
    e["lease_hasta"] = (datetime.utcnow() - timedelta(seconds=10)).isoformat()
    mc._barrido_guardar(e)

    assert mc._barrido_tomar_lease(mc._barrido_leer(), "worker-B") is True
```

- [ ] **Step 2: Correr y ver que fallan**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v -k cursor or lease
```

Esperado: FAIL con `AttributeError: module 'melonn_client' has no attribute '_barrido_leer'`

- [ ] **Step 3: Implementar**

En `src/melonn_client.py`, justo después de `_edad_fetch_api_sq()` y antes del encabezado `── SQLite (caché local / fallback) ──`:

```python
# ── Barrido por tramos: el cursor ─────────────────────────────────────────────
#
# POR QUÉ EXISTE: el barrido son ~44 páginas seguidas (~88 s, porque el limitador
# deja 2 s entre GETs). Si UNA falla, `_fetch_api_filtrado` marca el fetch
# incompleto y descarta todo lo traído. Descartarlo es correcto —mejor un tablero
# viejo que uno mutilado— pero depender de 44 peticiones seguidas sin un fallo no
# se puede garantizar. Con cursor, un fallo cuesta esa página.
#
# Fila propia (id=3) y no un campo del caché: el blob de pedidos son ~6,5 MB y
# esto se lee y escribe en cada tick.
_SB_FILA_BARRIDO = 3

_BARRIDO_VACIO: dict = {
    "v": 1,
    "generacion": 0,
    "pagina": 0,
    # Contador del corte por fecha. TIENE que persistir entre tramos: exige DOS
    # páginas llenas seguidas sin pedidos en ventana, y si un tramo termina justo
    # entre esas dos y el contador se reinicia, el barrido NO CORTA NUNCA. Eso es
    # el `tope_paginas` que dejó el tablero pegado el 2026-08-01.
    "paginas_fuera_ventana": 0,
    "iniciado_en": None,
    "vistas": [],           # claves vistas en la generación en curso
    "ausencias": {},        # clave -> barridos consecutivos sin verla
    "paginas_barrido_previo": 0,
    "motivo_ultimo_tramo": "nunca_corrio",
    "ultimo_tramo_en": None,
    "ultimo_completo_en": None,
    "lease_worker": "",
    "lease_hasta": None,
}

# Un tramo de 22 páginas son ~44 s. 90 da margen sin dejar el cursor tomado
# demasiado tiempo si el worker muere a mitad.
_LEASE_SEG = 90


def _barrido_leer() -> dict:
    """Estado del barrido. Supabase manda, SQLite es el respaldo.

    Siempre devuelve un dict completo: las claves que falten se rellenan con
    _BARRIDO_VACIO, para que añadir un campo nuevo no rompa un cursor ya escrito.
    """
    for leer in (_barrido_leer_sb, _barrido_leer_sq):
        try:
            v = leer()
            if v is not None:
                return {**_BARRIDO_VACIO, **v}
        except Exception as e:
            log.debug(f"[barrido] no pude leer el cursor ({leer.__name__}): {e}")
    return dict(_BARRIDO_VACIO)


def _barrido_leer_sb() -> Optional[dict]:
    sb = _sb()
    if not sb:
        return None
    rows = (sb.table(_SB_TABLA).select("pedidos_json")
              .eq("id", _SB_FILA_BARRIDO).execute()).data
    if not rows:
        return None
    e = json.loads(rows[0]["pedidos_json"])
    return e if isinstance(e, dict) else None


def _barrido_leer_sq() -> Optional[dict]:
    with _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS melonn_barrido ("
                  "id INTEGER PRIMARY KEY CHECK (id = 1), estado_json TEXT NOT NULL)")
        row = c.execute("SELECT estado_json FROM melonn_barrido WHERE id=1").fetchone()
    if not row:
        return None
    e = json.loads(row["estado_json"])
    return e if isinstance(e, dict) else None


def _barrido_guardar(estado: dict) -> None:
    """Escribe el cursor en Supabase Y en SQLite. Si Supabase falla, SQLite
    conserva el avance dentro del contenedor: peor que nada es volver a barrer
    desde la página 0."""
    blob = json.dumps(estado, default=str)
    try:
        sb = _sb()
        if sb:
            sb.table(_SB_TABLA).upsert({
                "id":           _SB_FILA_BARRIDO,
                "fetched_at":   datetime.utcnow().isoformat(),
                "pedidos_json": blob,
                "total":        len(estado.get("vistas") or []),
            }).execute()
    except Exception as e:
        log.warning(f"[barrido] no pude guardar el cursor en Supabase: {e}")
    try:
        with _conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS melonn_barrido ("
                      "id INTEGER PRIMARY KEY CHECK (id = 1), estado_json TEXT NOT NULL)")
            c.execute("INSERT OR REPLACE INTO melonn_barrido (id, estado_json) "
                      "VALUES (1, ?)", (blob,))
            c.commit()
    except Exception as e:
        log.debug(f"[barrido] SQLite cursor: {e}")


def _barrido_tomar_lease(estado: dict, worker: str) -> bool:
    """True si este worker puede avanzar el cursor. Muta `estado` con el lease.

    LÍMITE CONOCIDO: es leer-y-escribir, no un compare-and-set atómico. Dos
    workers que lean en el mismo instante pueden creer los dos que lo tomaron.
    Se acepta porque la consecuencia es benigna: barrerían el mismo tramo dos
    veces (fusión idempotente — ver _fusionar_tramo) y se gastarían ~22
    peticiones de más sobre una cuota de 10.000. Lo que esto sí evita, que es lo
    que importa, es que dos workers avancen el cursor a rangos DISTINTOS y entre
    los dos se salten páginas.
    """
    hasta = estado.get("lease_hasta")
    if hasta and estado.get("lease_worker") != worker:
        try:
            if _parse_iso_naive(hasta) > datetime.utcnow():
                return False
        except Exception:
            pass          # lease ilegible → tratarlo como libre
    from datetime import timedelta
    estado["lease_worker"] = worker
    estado["lease_hasta"] = (datetime.utcnow()
                             + timedelta(seconds=_LEASE_SEG)).isoformat()
    _barrido_guardar(estado)
    return True
```

- [ ] **Step 4: Correr las pruebas**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v
```

Esperado: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/melonn_client.py tests/test_melonn_barrido.py
git commit -m "feat(logistica): cursor persistido del barrido, con lease entre workers"
```

---

## Task 3: Separar el barrido de una página del recorrido

`_fetch_api_filtrado` mezcla tres cosas: recorrer páginas, filtrar por ventana y normalizar. El tramo necesita las dos últimas sin la primera. Este refactor **no cambia comportamiento** — las pruebas de la Tarea 1 son la prueba de eso.

**Files:**
- Modify: `src/melonn_client.py` (`_fetch_api_filtrado`, ~línea 1904)
- Modify: `tests/test_melonn_barrido.py`

**Interfaces:**
- Consumes: `_parsear_fecha`, `CODIGOS_ACTIVOS_OPERATIVO`, `ESTADOS_NOVEDAD_EXTERNA`, `CODIGOS_ACTIVOS`, `ESTADOS_EXCLUIR`, `ESTADOS_PROCESO_INTERNO`, `_normalizar` (ya existen).
- Produces:
  - `_filtrar_ventana(items: list, corte: date) -> list` — items crudos dentro de la ventana de 90 días (o abiertos, sin importar la edad).
  - `_normalizar_lote(crudos: list) -> list` — aplica whitelist, normaliza, descarta B2B y deja solo los sub-estados que van al tablero.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_filtrar_ventana_deja_pasar_lo_reciente(tmp_path, monkeypatch):
    corte = mc._fecha_corte()
    items = [_pedido(1, dias_atras=5), _pedido(2, dias_atras=200, code=8)]
    assert len(mc._filtrar_ventana(items, corte)) == 1


def test_filtrar_ventana_conserva_un_abierto_viejo():
    """Un pedido de hace 200 días que sigue EN TRÁNSITO no se descarta: sigue
    siendo trabajo pendiente."""
    corte = mc._fecha_corte()
    items = [_pedido(1, dias_atras=200, code=7)]   # 7 = en tránsito = abierto
    assert len(mc._filtrar_ventana(items, corte)) == 1


def test_normalizar_lote_descarta_b2b():
    crudo = _pedido(1)
    crudo["is_b2b"] = True
    assert mc._normalizar_lote([crudo]) == []


def test_normalizar_lote_descarta_estado_fuera_de_whitelist():
    assert mc._normalizar_lote([_pedido(1, code=15)]) == []   # 15 = Canceled


def test_normalizar_lote_normaliza_lo_valido():
    out = mc._normalizar_lote([_pedido(1, code=7)])
    assert len(out) == 1
    assert out[0]["orden_tienda"] == "T1"
    assert out[0]["sub_estado_logistico"] == "en_transito"
```

- [ ] **Step 2: Correr y ver que fallan**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v -k "filtrar or normalizar_lote"
```

Esperado: FAIL con `AttributeError: module 'melonn_client' has no attribute '_filtrar_ventana'`

- [ ] **Step 3: Extraer las dos funciones**

Añadir en `src/melonn_client.py` justo antes de `def _fetch_api_filtrado()`:

```python
def _filtrar_ventana(items: list, corte: date) -> list:
    """Los items crudos de una página que entran en la ventana de 90 días.

    Un pedido viejo que sigue ABIERTO cuenta como dentro de ventana: es trabajo
    pendiente, por antiguo que sea. La excepción NO puede ser `es_activo`, que
    incluye entregado (6 y 8): con eso la ventana no cortaba ni un entregado y el
    tablero se llenó con toda la historia de entregas (2.126 pedidos, 1.709 ya
    entregados, contra los ~1.150 que debía tener).
    """
    dentro = []
    for item in items:
        fc       = _parsear_fecha(item.get("creation_date"))
        estado_c = int((item.get("sell_order_state") or {}).get("code") or 0)
        estado_n = str((item.get("sell_order_state") or {}).get("name") or "")
        sigue_abierto = (estado_c in CODIGOS_ACTIVOS_OPERATIVO
                         or estado_n in ESTADOS_NOVEDAD_EXTERNA)
        if fc and fc < corte and not sigue_abierto:
            continue
        dentro.append(item)
    return dentro


def _normalizar_lote(crudos: list) -> list:
    """Whitelist + normalización + descarte de B2B, sobre items ya en ventana."""
    salida = []
    for item in crudos:
        estado_obj    = item.get("sell_order_state") or {}
        estado_nombre = str(estado_obj.get("name") or "")
        estado_codigo = int(estado_obj.get("code") or 0)

        # Whitelist: código en CODIGOS_ACTIVOS O nombre en ESTADOS_NOVEDAD_EXTERNA.
        # Las novedades externas no tienen código documentado → se ven por nombre.
        if (estado_codigo not in CODIGOS_ACTIVOS
                and estado_nombre not in ESTADOS_NOVEDAD_EXTERNA):
            log.debug(f"Excluido código {estado_codigo} ({estado_nombre})")
            continue
        if estado_nombre in ESTADOS_EXCLUIR or estado_nombre in ESTADOS_PROCESO_INTERNO:
            log.debug(f"Excluido por nombre: {estado_nombre}")
            continue

        try:
            p = _normalizar(item)
        except Exception:
            continue

        if p.get("es_b2b"):
            log.debug(f"Excluido B2B: {p.get('orden_tienda')}")
            continue

        # OJO: si falta un estado acá, esos pedidos DESAPARECEN del tablero.
        # Al separar "en_preparacion" de "en_transito" habrían quedado fuera 96.
        if p["sub_estado_logistico"] in ("pendiente_despacho", "en_preparacion",
                                         "en_transito", "novedad", "entregado"):
            salida.append(p)
    return salida
```

- [ ] **Step 4: Usarlas desde `_fetch_api_filtrado`**

Dentro del `while` de `_fetch_api_filtrado`, reemplazar el bloque que va desde `activos_en_pagina = 0` hasta el cierre del `for item in items:` (justo antes del comentario `# ── Cortar cuando ya pasamos la ventana ──`) por:

```python
        en_ventana = _filtrar_ventana(items, corte)
        pedidos_raw.extend(en_ventana)
        en_ventana_en_pagina = len(en_ventana)
```

Y reemplazar todo el bucle de normalización posterior (desde `resultado = []` hasta justo antes de `resultado = _heredar_enriquecidos(resultado)`) por:

```python
    resultado = _normalizar_lote(pedidos_raw)
```

`activos_en_pagina` queda sin uso: borrar sus dos asignaciones y la del `for`.

- [ ] **Step 5: Correr TODAS las pruebas**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v
```

Esperado: `13 passed`. Las tres de la Tarea 1 **tienen que seguir pasando sin tocarlas** — es lo que demuestra que el refactor no cambió comportamiento.

- [ ] **Step 6: Commit**

```bash
git add src/melonn_client.py tests/test_melonn_barrido.py
git commit -m "refactor(logistica): separar filtrar-por-ventana y normalizar del recorrido de paginas"
```

---

## Task 4: Fusionar un tramo sobre el caché vivo

**Files:**
- Modify: `src/melonn_client.py` (después de `_normalizar_lote`)
- Modify: `tests/test_melonn_barrido.py`

**Interfaces:**
- Consumes: `_clave_pedido`, `_campo_vacio`, `_CAMPOS_ENRIQUECIDOS`, `_marcar_despacho_observado`.
- Produces: `_fusionar_tramo(vivos: list, frescos: list) -> tuple[list, int]` — devuelve `(lista_fusionada, cuantos_nuevos)`. Nunca quita nada.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_fusionar_agrega_los_nuevos():
    vivos = [{"orden_melonn": "M1", "orden_tienda": "T1"}]
    frescos = [{"orden_melonn": "M2", "orden_tienda": "T2"}]
    out, nuevos = mc._fusionar_tramo(vivos, frescos)
    assert len(out) == 2
    assert nuevos == 1


def test_fusionar_conserva_lo_enriquecido():
    """El listado de Melonn NO trae cliente ni ciudad. Si el fresco los pisa con
    vacío, se pierde el dato de Shopify y no vuelve hasta el próximo enrich."""
    vivos = [{"orden_melonn": "M1", "nombre_comprador": "Ana",
              "ciudad_destino": "Medellin", "guia_real": "GUIA-9"}]
    frescos = [{"orden_melonn": "M1", "nombre_comprador": "",
                "ciudad_destino": "", "guia_real": "",
                "estado_melonn_code": 7}]
    out, _ = mc._fusionar_tramo(vivos, frescos)
    assert out[0]["nombre_comprador"] == "Ana"
    assert out[0]["ciudad_destino"] == "Medellin"
    assert out[0]["guia_real"] == "GUIA-9"
    assert out[0]["estado_melonn_code"] == 7      # el fresco SÍ manda en estado


def test_fusionar_detecta_el_despacho():
    vivos = [{"orden_melonn": "M1", "sub_estado_logistico": "pendiente_despacho"}]
    frescos = [{"orden_melonn": "M1", "sub_estado_logistico": "en_transito"}]
    out, _ = mc._fusionar_tramo(vivos, frescos)
    assert out[0]["fecha_despacho_observada"]
    assert out[0]["fecha_despacho_confiable"] is True


def test_fusionar_no_reanota_un_despacho_ya_visto():
    """Idempotencia: un pedido puede venir en dos tramos por el traslape."""
    vivos = [{"orden_melonn": "M1", "sub_estado_logistico": "pendiente_despacho"}]
    frescos = [{"orden_melonn": "M1", "sub_estado_logistico": "en_transito"}]
    out, _ = mc._fusionar_tramo(vivos, frescos)
    fecha = out[0]["fecha_despacho_observada"]

    out2, _ = mc._fusionar_tramo(out, [{"orden_melonn": "M1",
                                        "sub_estado_logistico": "en_transito"}])
    assert out2[0]["fecha_despacho_observada"] == fecha
    assert len(out2) == 1


def test_fusionar_nunca_quita():
    vivos = [{"orden_melonn": f"M{i}"} for i in range(10)]
    out, _ = mc._fusionar_tramo(vivos, [{"orden_melonn": "M3"}])
    assert len(out) == 10
```

- [ ] **Step 2: Correr y ver que fallan**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v -k fusionar
```

Esperado: FAIL con `AttributeError: module 'melonn_client' has no attribute '_fusionar_tramo'`

- [ ] **Step 3: Implementar**

```python
def _fusionar_tramo(vivos: list, frescos: list) -> tuple[list, int]:
    """Fusiona los pedidos de UN TRAMO sobre el caché vivo.

    Misma regla que _heredar_enriquecidos: el fresco manda en estado y logística,
    y los campos enriquecidos solo se pisan si el fresco trae valor. NUNCA quita
    nada — las bajas solo se deciden al cerrar un barrido completo, porque que un
    pedido no esté en las páginas de ESTE tramo no significa que no esté en
    Melonn. Ver _reconciliar_bajas.

    Es idempotente a propósito: por el traslape entre tramos un pedido puede
    llegar dos veces, y dos workers pueden barrer el mismo tramo si se cruzan los
    leases.

    Devuelve (lista_fusionada, cuantos_nuevos).
    """
    idx = {_clave_pedido(p): i for i, p in enumerate(vivos)}
    out = list(vivos)
    nuevos = 0
    despachos = 0

    for f in frescos:
        k = _clave_pedido(f)
        i = idx.get(k)
        if i is None:
            out.append(f)
            idx[k] = len(out) - 1
            nuevos += 1
            continue

        prev = out[i]
        # OJO EL ORDEN, igual que en _heredar_enriquecidos: la transición se
        # evalúa ANTES de heredar. Heredar primero copiaría la fecha vieja y el
        # estado anterior dejaría de ser visible — y una fecha de despacho
        # observada que se pierde NO SE PUEDE RECALCULAR.
        if _marcar_despacho_observado(f, prev):
            despachos += 1
        for c in _CAMPOS_ENRIQUECIDOS:
            if _campo_vacio(f.get(c)) and not _campo_vacio(prev.get(c)):
                f[c] = prev[c]
        out[i] = f

    if despachos:
        log.info(f"[despacho] {despachos} pedido(s) pasaron a despachado en este "
                 f"tramo — fecha anotada por observación propia")
    return out, nuevos
```

- [ ] **Step 4: Correr las pruebas**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v
```

Esperado: `18 passed`

- [ ] **Step 5: Commit**

```bash
git add src/melonn_client.py tests/test_melonn_barrido.py
git commit -m "feat(logistica): fusion de un tramo sobre el cache, preservando lo enriquecido"
```

---

## Task 5: Reconciliar las bajas

**Files:**
- Modify: `src/melonn_client.py` (después de `_fusionar_tramo`)
- Modify: `tests/test_melonn_barrido.py`

**Interfaces:**
- Consumes: `_clave_pedido`.
- Produces: `_reconciliar_bajas(vivos: list, vistas: set, ausencias: dict) -> tuple[list, dict, int]` — devuelve `(lista_sin_las_bajas, ausencias_actualizadas, cuantas_bajas)`. Constante `_AUSENCIAS_PARA_BAJA = 2`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_una_sola_ausencia_no_da_de_baja():
    """Puede ser un corrimiento del listado, no una baja real."""
    vivos = [{"orden_melonn": "M1"}, {"orden_melonn": "M2"}]
    out, aus, bajas = mc._reconciliar_bajas(vivos, {"M1"}, {})
    assert len(out) == 2
    assert bajas == 0
    assert aus["M2"] == 1


def test_dos_ausencias_seguidas_dan_de_baja():
    vivos = [{"orden_melonn": "M1"}, {"orden_melonn": "M2"}]
    _, aus, _ = mc._reconciliar_bajas(vivos, {"M1"}, {})
    out, aus2, bajas = mc._reconciliar_bajas(vivos, {"M1"}, aus)
    assert [p["orden_melonn"] for p in out] == ["M1"]
    assert bajas == 1
    assert "M2" not in aus2


def test_reaparecer_limpia_el_contador():
    vivos = [{"orden_melonn": "M1"}, {"orden_melonn": "M2"}]
    _, aus, _ = mc._reconciliar_bajas(vivos, {"M1"}, {})
    assert aus["M2"] == 1
    _, aus2, bajas = mc._reconciliar_bajas(vivos, {"M1", "M2"}, aus)
    assert "M2" not in aus2
    assert bajas == 0


def test_el_candado_bloquea_una_reconciliacion_que_vacia(tmp_path, monkeypatch):
    """Si un barrido trae casi nada, la reconciliación NO puede vaciar el tablero."""
    _aislar_disco(monkeypatch, tmp_path)
    vivos = [{"orden_melonn": f"M{i}"} for i in range(200)]
    mc._cache_guardar(vivos)
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 200

    aus = {f"M{i}": 1 for i in range(200)}
    out, _, bajas = mc._reconciliar_bajas(vivos, set(), aus)
    assert bajas == 200
    mc._cache_guardar(out)                       # el candado tiene que rechazarlo
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 200
```

- [ ] **Step 2: Correr y ver que fallan**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v -k "ausencia or reaparecer or candado_bloquea"
```

Esperado: FAIL (el stub devuelve `bajas == 0` y no toca `ausencias`)

- [ ] **Step 3: Arreglar el candado, que hoy solo protege si Supabase responde**

`test_el_candado_bloquea_una_reconciliacion_que_vacia` falla por una razón que **no** es el stub, y es un hallazgo aparte: `_total_en_cache()` consulta únicamente Supabase y devuelve `0` en cualquier otro caso. Con `antes = 0`, la condición `antes >= _MINIMO_ABSOLUTO` es falsa y **el candado deja pasar cualquier vaciado**.

En producción Supabase está y el candado funciona. Pero si Supabase se cae, si las credenciales fallan o si la consulta lanza, el candado se apaga **sin decir nada** — y el guardado que borre el tablero se ve exactamente igual que uno normal. Es el mismo patrón que dejó 37 semáforos verdes con una pregunta sin hacer.

La reconciliación es la primera ruta nueva que puede encoger el caché legítimamente, así que el candado tiene que ser real antes de encenderla. Reemplazar `_total_en_cache` por:

```python
def _total_en_cache() -> int:
    """Cuántos pedidos tiene el caché HOY. Lee solo el contador, no el blob.

    Cae a SQLite si Supabase no responde. ANTES devolvía 0 en ese caso, y un 0
    apaga el candado anti-vaciado entero: `antes >= _MINIMO_ABSOLUTO` es falso y
    cualquier guardado pasa. O sea que el candado protegía solo mientras Supabase
    estuviera bien — justo al revés de lo que uno querría de un candado.
    """
    try:
        sb = _sb()
        if sb:
            rows = (sb.table(_SB_TABLA).select("total").eq("id", 1).execute()).data
            if rows:
                return int(rows[0].get("total") or 0)
    except Exception as e:
        log.warning(f"[candado] no pude leer el total desde Supabase: {e}")
    try:
        _init_tabla()
        with _conn() as c:
            row = c.execute(
                "SELECT total FROM melonn_pedidos_cache WHERE id=1").fetchone()
        if row:
            return int(row["total"] or 0)
    except Exception as e:
        log.warning(f"[candado] no pude leer el total desde SQLite: {e}")
    return 0
```

- [ ] **Step 4: Implementar la reconciliación**

Reemplazar el stub por:

```python
# Cuántos barridos COMPLETOS seguidos sin ver un pedido antes de sacarlo.
#
# Dos, y no uno, porque paginar por offset sobre una lista que se mueve puede
# saltarse un pedido (ver el traslape en _barrido_tick). Una ausencia puede ser un
# corrimiento; dos seguidas es que de verdad no está. El costo es que un cancelado
# tarda hasta 4 h en salir del tablero — y de eso normalmente se encarga el
# webhook, no el barrido.
_AUSENCIAS_PARA_BAJA = 2


def _reconciliar_bajas(vivos: list, vistas: set, ausencias: dict) -> tuple[list, dict, int]:
    """Saca del caché lo que el barrido COMPLETO no vio dos veces seguidas.

    Solo se llama al cerrar un barrido: que un pedido no esté en las páginas de un
    tramo no significa que no esté en Melonn.

    `vistas` son las claves de los pedidos que PASARON EL FILTRO, no las de todos
    los items crudos. Así un pedido que Melonn devuelve pero que el tablero
    descarta (cancelado, B2B, estado fuera de la whitelist, viejo y ya cerrado)
    cuenta como ausente y termina saliendo — igual que hacía el reemplazo completo
    del caché.

    Un pedido creado por un webhook durante el barrido tampoco está en `vistas`,
    pero suma solo 1 ausencia y no se cae: el barrido siguiente ya lo verá.

    Devuelve (lista_sin_las_bajas, ausencias_actualizadas, cuantas_bajas).
    """
    nuevas: dict = {}
    salida: list = []
    bajas = 0

    for p in vivos:
        k = _clave_pedido(p)
        if k in vistas:
            continue_count = 0
        else:
            continue_count = int(ausencias.get(k, 0)) + 1
        if continue_count >= _AUSENCIAS_PARA_BAJA:
            bajas += 1
            continue
        if continue_count:
            nuevas[k] = continue_count
        salida.append(p)

    if bajas:
        log.info(f"[barrido] {bajas} pedido(s) dados de baja tras "
                 f"{_AUSENCIAS_PARA_BAJA} barridos sin verlos")
    return salida, nuevas, bajas
```

- [ ] **Step 5: Correr las pruebas**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v
```

Esperado: `22 passed`

- [ ] **Step 6: Commit**

```bash
git add src/melonn_client.py tests/test_melonn_barrido.py
git commit -m "feat(logistica): bajas tras dos barridos sin ver el pedido + el candado ya no depende de Supabase"
```

---

## Task 6: El tick del barrido

El corazón del cambio: traer un tramo, fusionarlo, avanzar el cursor y no perder nada si una página falla.

**Files:**
- Modify: `src/melonn_client.py` (después de `_fusionar_tramo`)
- Modify: `tests/test_melonn_barrido.py`

**Interfaces:**
- Consumes: `_barrido_leer`, `_barrido_guardar`, `_barrido_tomar_lease`, `_filtrar_ventana`, `_normalizar_lote`, `_fusionar_tramo`, `_cache_leer`, `_cache_guardar`, `_marcar_fetch_api`, `_get`, `_clave_pedido`, `_fecha_corte`.
- Produces:
  - `_tam_tramo(estado: dict) -> int`
  - `_barrido_tick(worker: str = "") -> dict` — devuelve `{"ok", "motivo", "generacion", "pagina", "completo", "paginas_traidas"}`
  - Constantes: `_TRAMO_DEFECTO = 22`, `_TRAMO_MIN = 4`, `_TRAMO_MAX = 30`, `_GENERACION_MAX_SEG = 21600`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_tam_tramo_parte_el_barrido_anterior_en_dos():
    assert mc._tam_tramo({"paginas_barrido_previo": 44}) == 22
    assert mc._tam_tramo({"paginas_barrido_previo": 0}) == mc._TRAMO_DEFECTO
    assert mc._tam_tramo({"paginas_barrido_previo": 2}) == mc._TRAMO_MIN
    assert mc._tam_tramo({"paginas_barrido_previo": 500}) == mc._TRAMO_MAX


def test_el_tick_avanza_por_tramos_y_cierra(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [_pedido(100 + i) for i in range(100)],
        2: [_pedido(200 + i) for i in range(100)],
        3: [_pedido(300 + i) for i in range(10)],     # última
    }
    pedidas = _paginas_falsas(monkeypatch, paginas)

    r1 = mc._barrido_tick(worker="w1")
    assert pedidas == [0, 1]
    assert r1["completo"] is False
    assert mc._barrido_leer()["pagina"] == 2

    r2 = mc._barrido_tick(worker="w1")
    assert r2["completo"] is True
    assert mc._barrido_leer()["pagina"] == 0          # listo para la siguiente
    assert mc._barrido_leer()["generacion"] == 1
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 310


def test_una_pagina_fallida_NO_pierde_las_anteriores(tmp_path, monkeypatch):
    """El arreglo. Comparar con test_una_pagina_fallida_pierde_el_barrido_entero."""
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 5)
    paginas = {i: [_pedido(100 * i + j) for j in range(100)] for i in range(4)}
    _paginas_falsas(monkeypatch, paginas, fallan={2})

    mc._barrido_tick(worker="w1")

    assert mc._barrido_leer()["pagina"] == 2          # reintenta ESA
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 200   # las 2 primeras, salvadas


def test_el_tramo_siguiente_reintenta_la_pagina_que_fallo(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 5)
    paginas = {0: [_pedido(j) for j in range(100)],
               1: [_pedido(100 + j) for j in range(100)],
               2: [_pedido(200 + j) for j in range(10)]}
    fallan = {2}
    pedidas = _paginas_falsas(monkeypatch, paginas, fallan=fallan)

    mc._barrido_tick(worker="w1")
    fallan.clear()                                   # Melonn se recupera
    r2 = mc._barrido_tick(worker="w1")

    assert pedidas[-1] == 2
    assert r2["completo"] is True
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 210


def test_el_contador_fuera_de_ventana_sobrevive_al_borde_del_tramo(tmp_path, monkeypatch):
    """Si el contador se reiniciara acá, el barrido no cortaría NUNCA y volvería
    el tope_paginas que dejó el tablero pegado el 2026-08-01."""
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    viejo = lambda n: _pedido(n, dias_atras=200, code=8)
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [viejo(100 + i) for i in range(100)],      # 1a fuera de ventana
        2: [viejo(200 + i) for i in range(100)],      # 2a → corta acá
        3: [viejo(300 + i) for i in range(100)],
    }
    pedidas = _paginas_falsas(monkeypatch, paginas)

    mc._barrido_tick(worker="w1")
    assert mc._barrido_leer()["paginas_fuera_ventana"] == 1

    r2 = mc._barrido_tick(worker="w1")
    assert r2["completo"] is True
    assert r2["motivo"] == "fuera_de_ventana"
    assert 3 not in pedidas


def test_el_tick_no_arranca_si_el_barrido_anterior_es_reciente(tmp_path, monkeypatch):
    from datetime import datetime
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e["ultimo_completo_en"] = datetime.utcnow().isoformat()
    mc._barrido_guardar(e)
    pedidas = _paginas_falsas(monkeypatch, {0: []})

    r = mc._barrido_tick(worker="w1")

    assert r["motivo"] == "al_dia"
    assert pedidas == []              # ni una petición a Melonn


def test_una_generacion_atascada_se_abandona(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e.update({"generacion": 5, "pagina": 30, "vistas": ["M1"],
              "iniciado_en": (datetime.utcnow() - timedelta(hours=7)).isoformat()})
    mc._barrido_guardar(e)
    # La página 1 falla a propósito: así el barrido NO cierra en este mismo tick
    # y se puede ver que la generación subió por el abandono, no por el cierre.
    _paginas_falsas(monkeypatch, {0: [_pedido(i) for i in range(10)]}, fallan={1})

    mc._barrido_tick(worker="w1")

    nuevo = mc._barrido_leer()
    assert nuevo["generacion"] == 6
    assert nuevo["vistas"] != ["M1"]        # la foto vieja se descartó
    assert nuevo["pagina"] <= 1             # volvió a empezar, no siguió en la 30
```

- [ ] **Step 2: Correr y ver que fallan**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v -k "tam_tramo or tick or fallida_NO or reintenta or fuera_de_ventana_sobrevive or atascada"
```

Esperado: FAIL con `AttributeError: module 'melonn_client' has no attribute '_tam_tramo'`

- [ ] **Step 3: Implementar**

```python
# Páginas por tramo. Se autocalibra: parte el barrido anterior en dos, así el
# barrido completo cierra en 2 ticks y —con el tick horario del scheduler— cada
# 2 h. Si el listado crece, el tramo crece solo; si la ventana se recorta, baja
# solo. _TRAMO_DEFECTO es el arranque en frío (~44 páginas hoy).
_TRAMO_DEFECTO = 22
_TRAMO_MIN     = 4
_TRAMO_MAX     = 30     # ~60 s de ráfaga, el techo que no queremos pasar

# Un barrido que no cierra en 6 h lleva varios tramos fallando. Seguir acumulando
# `vistas` de hace horas hace que la reconciliación mida contra una foto vieja, y
# para entonces el centinela ya está en rojo (FETCH_ROJO_MIN = 360 min).
_GENERACION_MAX_SEG = 6 * 3600


def _tam_tramo(estado: dict) -> int:
    previo = int(estado.get("paginas_barrido_previo") or 0)
    if previo <= 0:
        return _TRAMO_DEFECTO
    return max(_TRAMO_MIN, min(_TRAMO_MAX, -(-previo // 2)))   # ceil(previo/2)


def _barrido_tick(worker: str = "") -> dict:
    """Avanza UN TRAMO del barrido. Es lo que llama el scheduler en cada tick.

    Devuelve {ok, motivo, generacion, pagina, completo, paginas_traidas}.
    """
    import os
    worker = worker or f"{os.getpid()}"
    estado = _barrido_leer()

    if not _barrido_tomar_lease(estado, worker):
        log.info(f"[barrido] otro worker tiene el cursor hasta {estado.get('lease_hasta')}")
        return {"ok": False, "motivo": "lease_ajeno", "completo": False,
                "generacion": estado["generacion"], "pagina": estado["pagina"],
                "paginas_traidas": 0}

    ahora = datetime.utcnow()
    en_curso = bool(estado.get("iniciado_en"))

    # ¿Hay que abandonar una generación atascada?
    if en_curso:
        try:
            edad = (ahora - _parse_iso_naive(estado["iniciado_en"])).total_seconds()
        except Exception:
            edad = _GENERACION_MAX_SEG + 1
        if edad > _GENERACION_MAX_SEG:
            log.error(f"[barrido] generación {estado['generacion']} lleva "
                      f"{edad / 3600:.1f} h sin cerrar — se abandona y empieza otra")
            en_curso = False
            estado["generacion"] = int(estado["generacion"]) + 1

    # ¿Arrancar una generación nueva?
    if not en_curso:
        ultimo = estado.get("ultimo_completo_en")
        if ultimo:
            try:
                if (ahora - _parse_iso_naive(ultimo)).total_seconds() < _CACHE_TTL:
                    estado["lease_hasta"] = None
                    _barrido_guardar(estado)
                    return {"ok": True, "motivo": "al_dia", "completo": False,
                            "generacion": estado["generacion"],
                            "pagina": 0, "paginas_traidas": 0}
            except Exception:
                pass      # reloj ilegible → barrer, que es el lado seguro
        estado.update({"pagina": 0, "vistas": [], "paginas_fuera_ventana": 0,
                       "iniciado_en": ahora.isoformat()})

    # ── Traer el tramo ────────────────────────────────────────────────────────
    corte      = _fecha_corte()
    tam        = _tam_tramo(estado)
    pagina     = int(estado["pagina"])
    # Traslape: se re-lee la última página ya barrida. Paginar por offset sobre
    # una lista que se mueve puede SALTARSE un pedido —si se borran ítems por
    # encima, todo sube de índice y un pedido pasa del rango no barrido al ya
    # barrido, y desaparece sin dejar rastro. Una página (100 pedidos) cubre
    # cualquier corrimiento realista en una hora. Cuesta 1 petición por tramo.
    inicio     = max(0, pagina - 1) if pagina > 0 else 0
    solo_fusion = pagina - inicio          # 1 si hay traslape, 0 si no

    crudos: list = []
    motivo = "tramo_ok"
    completo = False
    traidas = 0
    tam_pagina = estado.get("tam_pagina")

    p = inicio
    while p < min(inicio + tam + solo_fusion, _MAX_PAGES):
        resp = _get("sell-orders", params={"per_page": _PAGE_SIZE, "page": p})
        if resp is None:
            causa = (ultimo_fallo_get().get("motivo") or "sin_causa_registrada")
            motivo = f"fallo_get_pagina_{p}:{causa}"
            break
        items = resp.get("data") or []
        if not items:
            motivo, completo = "sin_mas_datos", True
            break
        if tam_pagina is None:
            tam_pagina = len(items)
            estado["tam_pagina"] = tam_pagina

        en_ventana = _filtrar_ventana(items, corte)
        crudos.extend(en_ventana)
        traidas += 1

        # La página de traslape ya se contó en su tramo: no toca el contador ni
        # el cursor. Solo se re-lee para fusionar lo que haya cambiado.
        if p >= pagina:
            if len(items) >= tam_pagina and not en_ventana:
                estado["paginas_fuera_ventana"] = int(estado["paginas_fuera_ventana"]) + 1
                if estado["paginas_fuera_ventana"] >= 2:
                    motivo, completo = "fuera_de_ventana", True
                    p += 1
                    break
            else:
                estado["paginas_fuera_ventana"] = 0

            if len(items) < tam_pagina:
                motivo, completo = "ultima_pagina", True
                p += 1
                break
        p += 1

    if not completo and motivo == "tramo_ok" and p >= _MAX_PAGES:
        motivo = "tope_paginas"

    # ── Fusionar ──────────────────────────────────────────────────────────────
    frescos = _normalizar_lote(crudos)
    hit     = _cache_leer(ignorar_ttl=True)
    vivos   = (hit[0] if hit else []) or []
    fusionado, nuevos = _fusionar_tramo(vivos, frescos)

    vistas = set(estado.get("vistas") or [])
    vistas.update(_clave_pedido(f) for f in frescos)
    estado["vistas"] = sorted(vistas)
    estado["pagina"] = p
    estado["motivo_ultimo_tramo"] = motivo
    estado["ultimo_tramo_en"] = ahora.isoformat()

    # ── ¿Cerró el barrido? ────────────────────────────────────────────────────
    if completo:
        fusionado, estado["ausencias"], bajas = _reconciliar_bajas(
            fusionado, vistas, estado.get("ausencias") or {})
        estado.update({
            "paginas_barrido_previo": p,
            "generacion": int(estado["generacion"]) + 1,
            "pagina": 0, "vistas": [], "paginas_fuera_ventana": 0,
            "iniciado_en": None,
            "ultimo_completo_en": ahora.isoformat(),
        })
        log.info(f"[barrido] COMPLETO · {p} páginas · {len(fusionado)} pedidos "
                 f"· {nuevos} nuevos · {bajas} bajas · fin={motivo}")
    else:
        log.info(f"[barrido] tramo {inicio}-{p - 1} · {nuevos} nuevos · fin={motivo}")

    _cache_guardar(fusionado)

    # Solo se sella el reloj del barrido COMPLETO cuando de verdad cerró Y trajo
    # algo. Si la cuota está agotada, `frescos` viene vacío y NO se sella: así el
    # próximo tick vuelve a intentar en vez de esperar otras 2 h.
    if completo and fusionado:
        _marcar_fetch_api()

    estado["lease_hasta"] = None          # soltar el lease
    _barrido_guardar(estado)

    return {"ok": motivo in ("tramo_ok", "ultima_pagina", "sin_mas_datos",
                             "fuera_de_ventana"),
            "motivo": motivo, "completo": completo,
            "generacion": estado["generacion"], "pagina": estado["pagina"],
            "paginas_traidas": traidas}
```


- [ ] **Step 4: Correr las pruebas**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v
```

Esperado: `29 passed`

- [ ] **Step 5: Commit**

```bash
git add src/melonn_client.py tests/test_melonn_barrido.py
git commit -m "feat(logistica): tick del barrido por tramos — un fallo de pagina ya no cuesta el barrido"
```

---

## Task 7: Los dos relojes

**Files:**
- Modify: `src/melonn_client.py` (`ultimo_fetch`, ~línea 1899)
- Modify: `tests/test_melonn_barrido.py`

**Interfaces:**
- Consumes: `_barrido_leer`, `_parse_iso_naive`.
- Produces:
  - `_edad_tramo() -> Optional[float]` — segundos desde el último tramo, completo o no.
  - `ultimo_fetch() -> dict` con forma nueva: `{generacion, pagina, paginas_estimadas, en_curso, motivo_fin, completo, ultimo_completo_en, ultimo_tramo_en}`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_ultimo_fetch_lee_del_cursor(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    paginas = {0: [_pedido(i) for i in range(100)],
               1: [_pedido(100 + i) for i in range(100)],
               2: [_pedido(200 + i) for i in range(5)]}
    _paginas_falsas(monkeypatch, paginas)

    mc._barrido_tick(worker="w1")
    uf = mc.ultimo_fetch()
    assert uf["en_curso"] is True
    assert uf["pagina"] == 2
    assert uf["completo"] is False

    mc._barrido_tick(worker="w1")
    uf = mc.ultimo_fetch()
    assert uf["en_curso"] is False
    assert uf["completo"] is True
    assert uf["ultimo_completo_en"]


def test_edad_tramo_es_none_si_nunca_corrio(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    assert mc._edad_tramo() is None


def test_edad_tramo_cuenta_desde_el_ultimo_tramo(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e["ultimo_tramo_en"] = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
    mc._barrido_guardar(e)
    assert 1700 < mc._edad_tramo() < 1900       # ~1800 s
```

- [ ] **Step 2: Correr y ver que fallan**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v -k "ultimo_fetch_lee or edad_tramo"
```

Esperado: FAIL — `ultimo_fetch()` todavía devuelve el dict de proceso, sin `en_curso`.

- [ ] **Step 3: Implementar**

Reemplazar `_ULTIMO_FETCH` y `ultimo_fetch()` por:

```python
# Radiografía del barrido, para el chequeo de salud.
#
# ANTES era un dict de proceso (`_ULTIMO_FETCH`), así que se perdía en cada
# reinicio y cada réplica de Railway veía la suya. Ahora sale del cursor, que es
# compartido y persistente.
#
# DOS RELOJES, y la diferencia es el punto de todo esto:
#   ultimo_tramo_en    → cuándo avanzamos algo. Dice si el barrido está vivo.
#   ultimo_completo_en → cuándo cerró un barrido ENTERO. Es el único que dice si
#                        el tablero es auditable, y el que sella _marcar_fetch_api.
def ultimo_fetch() -> dict:
    """Cómo va el barrido del listado, para el chequeo de salud."""
    e = _barrido_leer()
    return {
        "generacion":         e.get("generacion", 0),
        "pagina":             e.get("pagina", 0),
        "paginas_estimadas":  e.get("paginas_barrido_previo", 0),
        "en_curso":           bool(e.get("iniciado_en")),
        "motivo_fin":         e.get("motivo_ultimo_tramo", "nunca_corrio"),
        "completo":           (not e.get("iniciado_en")
                               and bool(e.get("ultimo_completo_en"))),
        "ultimo_completo_en": e.get("ultimo_completo_en"),
        "ultimo_tramo_en":    e.get("ultimo_tramo_en"),
    }


def _edad_tramo() -> Optional[float]:
    """Segundos desde el último tramo, completo o no. None si nunca corrió.

    Complementa a _edad_fetch_api(): un barrido puede llevar horas atascado a
    mitad y el reloj del último COMPLETO seguir viéndose reciente.
    """
    e = _barrido_leer()
    ts = e.get("ultimo_tramo_en")
    if not ts:
        return None
    try:
        return (datetime.utcnow() - _parse_iso_naive(ts)).total_seconds()
    except Exception:
        return None
```

Borrar el bloque `_ULTIMO_FETCH: dict = {...}` y la asignación `_ULTIMO_FETCH.update({...})` dentro de `_fetch_api_filtrado` (esa función ya no alimenta la radiografía; el cursor sí).

- [ ] **Step 4: Correr las pruebas**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v
```

Esperado: `32 passed`. **Las tres pruebas de la Tarea 1 que llaman a `mc.ultimo_fetch()` ahora fallarían**, porque esa función ya no describe a `_fetch_api_filtrado`. Ajustarlas para que lean el motivo desde el valor de retorno en vez de la radiografía: reemplazar en `test_barrido_completo_trae_todas_las_paginas` las dos aserciones sobre `ultimo_fetch()` por `assert len(res) == 210`, y en `test_una_pagina_fallida_pierde_el_barrido_entero` y `test_corte_por_fecha_para_al_salir_de_la_ventana` por `assert res == []` y `assert len(res) == 100` respectivamente. Añadir en cada una un comentario `# ultimo_fetch() describe el barrido por tramos desde la Tarea 7`.

- [ ] **Step 5: Commit**

```bash
git add src/melonn_client.py tests/test_melonn_barrido.py
git commit -m "feat(logistica): dos relojes — ultimo tramo y ultimo barrido COMPLETO"
```

---

## Task 8: Cablear el scheduler

**Files:**
- Modify: `src/melonn_client.py` (`obtener_pedidos_activos`, ~línea 2641)
- Modify: `backend/core/scheduler.py:135-140`
- Modify: `tests/test_melonn_barrido.py`

**Interfaces:**
- Consumes: `_barrido_tick`, `_cache_leer`, `_enriquecer_y_filtrar`.
- Produces: `obtener_pedidos_activos(dias: int = 30, forzar_refresh: bool = False, modo: str = "completo") -> tuple`.

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_modo_tramo_avanza_el_cursor_sin_barrer_todo(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    paginas = {i: [_pedido(100 * i + j) for j in range(100)] for i in range(6)}
    pedidas = _paginas_falsas(monkeypatch, paginas)

    _pedidos, _om, meta = mc.obtener_pedidos_activos(forzar_refresh=True, modo="tramo")

    assert pedidas == [0, 1]                  # UN tramo, no el barrido entero
    assert meta["modo"] == "tramo"
    assert meta["barrido"]["paginas_traidas"] == 2
    # Se mide sobre el caché y no sobre lo devuelto: _enriquecer_y_filtrar
    # deduplica por orden_tienda y re-deriva estados, así que su salida depende
    # de reglas que no son las que esta prueba quiere fijar.
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 200
```

- [ ] **Step 2: Correr y ver que falla**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v -k modo_tramo
```

Esperado: FAIL con `TypeError: obtener_pedidos_activos() got an unexpected keyword argument 'modo'`

- [ ] **Step 3: Añadir el modo tramo**

En `obtener_pedidos_activos`, cambiar la firma y añadir la rama al principio del bloque `if forzar_refresh:`:

```python
def obtener_pedidos_activos(dias: int = 30, forzar_refresh: bool = False,
                            modo: str = "completo") -> tuple:
```

Justo después de `omitidos = {"resuelto": 0, "sin_datos": 0}`:

```python
    # modo="tramo": el scheduler. Avanza UN tramo del barrido y devuelve el caché.
    #
    # No pasa por el guard de _MIN_REFRESH_SECS a propósito: la cadencia la fija
    # el cursor (_barrido_tick no arranca una generación nueva si el último
    # barrido completo tiene menos de _CACHE_TTL). Ese guard de 60 s era lo único
    # que frenaba el camino de forzar_refresh, y con tick horario NUNCA frenaba
    # nada: se barría entero cada hora, ~1.056 peticiones/día contra las ~516 que
    # se creían. Con el cursor son ~540.
    if forzar_refresh and modo == "tramo":
        r = _barrido_tick()
        hit = _cache_leer(ignorar_ttl=True)
        pedidos = _enriquecer_y_filtrar((hit[0] if hit else []) or [])
        return pedidos, omitidos, {
            "fuente": "api_live", "stale": False,
            "fetched_at": (hit[1] if hit else datetime.now()),
            "modo": "tramo", "barrido": r,
        }
```

- [ ] **Step 4: Correr las pruebas**

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py -v
```

Esperado: `33 passed`

- [ ] **Step 5: Que el scheduler use el modo tramo**

En `backend/core/scheduler.py`, reemplazar la línea 138:

```python
        mc.obtener_pedidos_activos(forzar_refresh=True)
```

por:

```python
        # modo="tramo": avanza un tramo del barrido en vez de barrer las ~44
        # páginas de un tirón. Un fallo de página cuesta esa página, no el
        # barrido. El botón "Sincronizar datos" sigue usando el barrido completo.
        mc.obtener_pedidos_activos(forzar_refresh=True, modo="tramo")
```

- [ ] **Step 6: Verificar que nada más llama con el modo por defecto equivocado**

```bash
grep -rn "obtener_pedidos_activos" --include="*.py" . | grep -v "def obtener_pedidos_activos"
```

Esperado: solo `backend/core/scheduler.py` pasa `modo="tramo"`. Todo lo demás (el botón manual, `salud_logistica`, `backend/services/melonn.py`) queda en `modo="completo"`, que es el comportamiento de hoy.

- [ ] **Step 7: Commit**

```bash
git add src/melonn_client.py backend/core/scheduler.py tests/test_melonn_barrido.py
git commit -m "feat(logistica): el scheduler avanza por tramos; el boton manual sigue barriendo entero"
```

---

## Task 9: Que el centinela entienda los tramos

Sin esto el centinela queda **rojo permanente**: hoy marca rojo ante cualquier `completo = False`, y con tramos estar a mitad de barrido es lo normal. Un semáforo siempre rojo es un semáforo que se deja de mirar.

**Files:**
- Modify: `backend/services/salud_logistica.py` (`_revisar_fetch`, líneas 106-143)
- Create: `tests/test_salud_barrido.py`

**Interfaces:**
- Consumes: `mc.ultimo_fetch()` (forma nueva de la Tarea 7), `mc._edad_tramo()`, `mc.ultimo_fallo_get()`, `mc.ultimo_guardado_bloqueado()`.
- Produces: hallazgo nuevo `barrido_atascado`; constante `TRAMO_ROJO_MIN = 180`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_salud_barrido.py`:

```python
"""El centinela tiene que entender que estar a mitad de barrido es NORMAL.

Antes de los tramos, `completo = False` significaba que el barrido se rompió. Con
tramos significa "va por la página 22 de 44". Si esto no cambia, el semáforo queda
rojo permanente — y un semáforo siempre rojo enseña a no mirarlo, que es justo lo
contrario de para qué existe el centinela.
"""
from backend.services import salud_logistica as S


class _McFalso:
    def __init__(self, uf, edad_tramo=60.0):
        self._uf = uf
        self._edad = edad_tramo

    def ultimo_fetch(self):
        return self._uf

    def _edad_tramo(self):
        return self._edad

    def ultimo_fallo_get(self):
        return {"motivo": "", "path": "", "ts": None}

    def ultimo_guardado_bloqueado(self):
        return {"ts": None, "antes": 0, "intento": 0, "fuente": ""}


def _correr(mc):
    hallazgos, medidas = [], {}
    def marcar(nivel, clave, mensaje, **datos):
        hallazgos.append({"nivel": nivel, "clave": clave, "mensaje": mensaje})
    S._revisar_fetch(mc, marcar, medidas)
    return hallazgos, medidas


def test_a_mitad_de_barrido_no_es_rojo():
    mc = _McFalso({"generacion": 7, "pagina": 22, "paginas_estimadas": 44,
                   "en_curso": True, "motivo_fin": "tramo_ok", "completo": False,
                   "ultimo_completo_en": "2026-08-06T12:00:00",
                   "ultimo_tramo_en": "2026-08-06T13:00:00"})
    hallazgos, medidas = _correr(mc)
    assert [h for h in hallazgos if h["nivel"] == "rojo"] == []
    assert medidas["ultimo_fetch"]["pagina"] == 22


def test_barrido_atascado_es_rojo():
    """El último barrido COMPLETO puede verse reciente y aun así el barrido en
    curso llevar horas sin avanzar ni una página. Antes no tenía alarma."""
    mc = _McFalso({"generacion": 7, "pagina": 22, "paginas_estimadas": 44,
                   "en_curso": True, "motivo_fin": "tramo_ok", "completo": False,
                   "ultimo_completo_en": "2026-08-06T12:00:00",
                   "ultimo_tramo_en": "2026-08-06T09:00:00"},
                  edad_tramo=4 * 3600)
    hallazgos, _ = _correr(mc)
    assert [h["clave"] for h in hallazgos if h["nivel"] == "rojo"] == ["barrido_atascado"]


def test_tope_paginas_sigue_siendo_rojo():
    mc = _McFalso({"generacion": 7, "pagina": 60, "paginas_estimadas": 44,
                   "en_curso": True, "motivo_fin": "tope_paginas", "completo": False,
                   "ultimo_completo_en": "2026-08-06T12:00:00",
                   "ultimo_tramo_en": "2026-08-06T13:00:00"})
    hallazgos, _ = _correr(mc)
    assert "tope_paginas" in [h["clave"] for h in hallazgos if h["nivel"] == "rojo"]


def test_un_fallo_de_pagina_es_ambar_no_rojo():
    """Con cursor, una página que falla se reintenta en el tramo siguiente: es
    ruido operativo, no una caída. Rojo lo pone el reloj si deja de cerrar."""
    mc = _McFalso({"generacion": 7, "pagina": 22, "paginas_estimadas": 44,
                   "en_curso": True, "motivo_fin": "fallo_get_pagina_22:http_429",
                   "completo": False,
                   "ultimo_completo_en": "2026-08-06T12:00:00",
                   "ultimo_tramo_en": "2026-08-06T13:00:00"})
    hallazgos, _ = _correr(mc)
    niveles = {h["clave"]: h["nivel"] for h in hallazgos}
    assert niveles.get("tramo_fallido") == "amarillo"


def test_barrido_cerrado_y_al_dia_no_tiene_hallazgos():
    mc = _McFalso({"generacion": 8, "pagina": 0, "paginas_estimadas": 44,
                   "en_curso": False, "motivo_fin": "ultima_pagina", "completo": True,
                   "ultimo_completo_en": "2026-08-06T13:00:00",
                   "ultimo_tramo_en": "2026-08-06T13:00:00"})
    hallazgos, _ = _correr(mc)
    assert hallazgos == []
```

- [ ] **Step 2: Correr y ver que fallan**

```bash
./.venv/bin/python -m pytest tests/test_salud_barrido.py -v
```

Esperado: FAIL — el `_revisar_fetch` de hoy marca rojo `fetch_incompleto` en los cuatro primeros casos.

- [ ] **Step 3: Reescribir `_revisar_fetch`**

En `backend/services/salud_logistica.py`, añadir junto a los otros umbrales (después de `HORA_ESPERA_PEDIDOS = 11`):

```python
# Cuánto puede pasar sin que el barrido avance NI UNA página antes de ser rojo.
# El scheduler tiene tick horario, así que 3 h son tres ticks perdidos seguidos.
# Es distinto de FETCH_ROJO_MIN, que mide desde el último barrido COMPLETO: el
# barrido puede llevar horas atascado a mitad con ese reloj todavía en verde.
TRAMO_ROJO_MIN = 180
```

Y reemplazar el cuerpo de `_revisar_fetch` (líneas 106-143) por:

```python
def _revisar_fetch(mc, marcar, medidas: dict) -> None:
    """¿El barrido avanza? ¿Se bloqueó algún guardado?

    Aparte de chequear() y no dentro, porque hay que llamarlo DESPUÉS de leer el
    tablero (leer puede disparar un refresh) y también en el camino de error.

    OJO CON LO QUE ES ROJO. El barrido se arma por tramos entre varios ticks, así
    que `completo = False` es lo NORMAL a mitad de camino: significa "va por la
    página 22 de 44", no "se rompió". Marcar eso en rojo dejaría el semáforo rojo
    permanente, y un semáforo siempre rojo enseña a no mirarlo — que es justo lo
    contrario de para qué existe este módulo. Lo que sí es rojo:
      · el barrido no avanza ni una página (barrido_atascado)
      · topamos nuestro propio techo de páginas (tope_paginas)
      · se bloqueó un guardado
    Que no cierre a tiempo lo cubre el reloj de chequear(), vía _edad_fetch_api.
    """
    try:
        uf = mc.ultimo_fetch()
        medidas["ultimo_fetch"] = uf
        motivo = uf.get("motivo_fin") or ""

        if motivo == "nunca_corrio":
            pass          # este worker no ha barrido todavía; no es un hallazgo
        elif motivo == "tope_paginas":
            marcar("rojo", "tope_paginas",
                   f"El barrido llegó a nuestro techo de páginas sin salir de la "
                   f"ventana (página {uf.get('pagina')}). El listado no se está "
                   f"cortando por fecha y el tablero no puede quedar completo.",
                   pagina=uf.get("pagina"))
        elif motivo.startswith("fallo_get_pagina"):
            # Con cursor esto se reintenta solo en el tramo siguiente.
            marcar("amarillo", "tramo_fallido",
                   f"Un tramo se cortó en la página {uf.get('pagina')} "
                   f"({motivo}). Se reintenta en el próximo tick sin perder lo "
                   f"ya barrido.",
                   motivo=motivo)

        if uf.get("en_curso"):
            edad_tramo = None
            try:
                edad_tramo = mc._edad_tramo()
            except Exception as e:
                marcar("amarillo", "reloj_tramo_ilegible",
                       f"No pude leer cuándo avanzó el barrido: {str(e)[:120]}")
            medidas["minutos_desde_tramo"] = (
                round(edad_tramo / 60, 1) if edad_tramo is not None else None)
            if edad_tramo is not None and edad_tramo / 60 > TRAMO_ROJO_MIN:
                marcar("rojo", "barrido_atascado",
                       f"El barrido va por la página {uf.get('pagina')} de "
                       f"~{uf.get('paginas_estimadas')} y lleva "
                       f"{edad_tramo / 60:.0f} minutos sin avanzar ni una. El "
                       f"reloj del último barrido completo puede verse bien y el "
                       f"tablero estarse quedando viejo igual.",
                       minutos=round(edad_tramo / 60, 1))

        try:
            medidas["ultimo_fallo_get"] = mc.ultimo_fallo_get()
        except Exception as e:
            marcar("amarillo", "chequeo_roto",
                   f"No pude leer el último fallo de GET: {str(e)[:120]}")
    except Exception as e:
        # Un sub-chequeo que no corre es un hallazgo, no un silencio. Ver el
        # comentario del chequeo 8: 37 semáforos verdes tenían una pregunta sin
        # hacer porque un TypeError caía en un except mudo.
        marcar("amarillo", "chequeo_roto",
               f"No pude leer la radiografía del barrido: {str(e)[:150]}")

    try:
        bloq = mc.ultimo_guardado_bloqueado()
        if bloq.get("ts"):
            medidas["guardado_bloqueado"] = bloq
            marcar("rojo", "guardado_bloqueado",
                   f"Se bloqueó un guardado que dejaba el caché en "
                   f"{bloq.get('intento')} pedidos (tenía {bloq.get('antes')}), "
                   f"fuente '{bloq.get('fuente')}'. El candado hizo su trabajo, "
                   f"pero hay que ver por qué llegó una lista tan corta.")
    except Exception as e:
        marcar("amarillo", "chequeo_roto",
               f"No pude leer el candado de guardado: {str(e)[:120]}")
```

- [ ] **Step 4: Correr las pruebas**

```bash
./.venv/bin/python -m pytest tests/ -v -k "barrido or salud"
```

Esperado: `38 passed`

- [ ] **Step 5: Actualizar el comentario de umbrales**

En el bloque de umbrales de `salud_logistica.py`, el comentario dice "El barrido completo del listado corre cada 2 h... y el scheduler tiene tick horario". Sigue siendo cierto pero ahora por otra razón. Reemplazar esas líneas por:

```python
# El barrido completo se arma por TRAMOS entre varios ticks y cierra cada ~2 h
# (_CACHE_TTL en melonn_client; el cursor no arranca una generación nueva antes).
# Con eso, 3 h sin CERRAR un barrido significa que uno se saltó, y 6 h que llevan
# varios fallando.
#
# OJO si se cambia _CACHE_TTL: estos dos números tienen que moverse con él, o el
# semáforo empieza a mentir. Un centinela mal calibrado es peor que ninguno,
# porque da verde sobre un tablero viejo.
```

- [ ] **Step 6: Commit**

```bash
git add backend/services/salud_logistica.py tests/test_salud_barrido.py
git commit -m "fix(salud): estar a mitad de barrido no es rojo; un barrido atascado si"
```

---

## Verificación final

- [ ] **Toda la batería**

```bash
./.venv/bin/python -m pytest tests/ -v
```

Esperado: todo verde. Las pruebas que ya existían (`test_postventa_*`, `test_fiscal_*`, etc.) necesitan más dependencias; si fallan por `ModuleNotFoundError`, correr solo las de este trabajo:

```bash
./.venv/bin/python -m pytest tests/test_melonn_barrido.py tests/test_salud_barrido.py -v
```

- [ ] **Comprobar que ninguna ruta perdió el candado**

```bash
grep -n "forzar=True" src/melonn_client.py
```

Esperado: solo dos, las de antes — `cargar_desde_csv` y `limpiar_cache`. Ninguna de las funciones nuevas.

- [ ] **En producción, después de desplegar** (la API de Melonn solo responde desde la IP de Railway)

1. `/api/melonn/status` — confirmar `SCHEDULER_LIGHT_SEC`.
2. `/api/melonn/salud` — semáforo **verde**, con `ultimo_fetch` mostrando `generacion` y `pagina`.
3. Esperar **dos barridos completos** (≈4 h) y confirmar que `minutos_desde_fetch` se resetea al cerrar cada uno, **no** en cada tramo.
4. `/api/melonn/diagnostico-filtros` — el total del tablero no debe moverse más de lo normal.
5. Tabla `logistica_salud` — ningún rojo nuevo.
6. Cuota: el gasto diario debe **bajar** de ~1.056 a ~540 peticiones.

> Si el paso 3 muestra que `minutos_desde_fetch` se resetea en cada tramo, el reloj de "barrido COMPLETO" está mal cableado y el centinela estaría dando verde sobre un tablero a medio barrer. Es el fallo más peligroso de este cambio, porque se ve exactamente igual que el éxito.
