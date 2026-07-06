# Postventa Core (Sub-proyecto #1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el motor de casos de postventa + panel interno de MALE POSTVENTA IA: crear/gestionar casos vinculados a pedidos Shopify, máquina de estados, items, evidencias, timeline automático, notificaciones WhatsApp y dashboard básico. **Sin la parte fiscal** (esa es el plan #2).

**Architecture:** Módulo nuevo `postventa` que sigue el patrón exacto de los módulos existentes (Producción, Conciliación): lógica pura testeable en `postventa_logic.py`, orquestación + acceso Supabase en `postventa.py`, router FastAPI en `api/postventa.py`, y frontend Next.js en `app/postventa/`. Un solo servicio `crear_caso(...)` agnóstico a la puerta de entrada (interno/portal).

**Tech Stack:** Python 3.9 (local) / 3.14 (Railway), FastAPI, Supabase (postgres via `supabase-py`), Pydantic v2, httpx, pytest (nuevo), Next.js App Router + react-query + shadcn/ui + Tailwind.

## Global Constraints

- **Montos en COP** `numeric(12,2)`, **sin IVA** en items (el IVA lo calcula el motor fiscal del plan #2).
- **`status` es texto** validado en el servicio contra un enum en código (no un enum de postgres) — agregar estados futuros debe ser solo lógica, no migración.
- **`source`** de cada caso es `'interno'` o `'portal'` — el servicio `crear_caso` NO debe ramificar según la puerta de entrada.
- **`case_number`** consecutivo propio con formato exacto `PV-<AÑO>-<4 dígitos>` (ej. `PV-2026-0001`).
- **Reutilizar** servicios existentes: `whatsapp_cloud.enviar_texto`, `clientes.clasificar` (Shopify), `core.security.require_permission`, patrón `_sb()` de Supabase. NO reimplementar.
- **Módulo de permisos** = `"postventa"`; acciones `"ver"` y `"modificar"`.
- **Nombres en español** para funciones de dominio (coherente con el resto del backend: `crear_caso`, `cambiar_estado`, etc.).
- Ejecutar `pytest` **desde la raíz del repo** (`~/male_denim_logistics`); `backend` es un paquete con `__init__.py`.

---

## File Structure

**Backend (crear):**
- `backend/services/postventa_logic.py` — constantes + funciones puras (estados, transiciones, motivos, tipos, cálculo de diferencia, formato de consecutivo). Cero I/O. 100% testeable.
- `backend/services/postventa.py` — orquestación: acceso Supabase (`_sb()`), CRUD de casos/items/evidencias/timeline, notificaciones, dashboard. Usa `postventa_logic`.
- `backend/api/postventa.py` — router FastAPI (`/api/postventa/...`).
- `SUPABASE_MIGRATION_POSTVENTA.sql` — DDL de las 5 tablas (convención del repo: migraciones como `.sql` en la raíz).

**Backend (modificar):**
- `backend/main.py` — importar y registrar `postventa.router`.
- `requirements.txt` — agregar `pytest>=8.0`.

**Tests (crear):**
- `tests/conftest.py` — asegura raíz en `sys.path`.
- `tests/test_postventa_logic.py` — pruebas de lógica pura.
- `tests/test_postventa_service.py` — pruebas de servicio con Supabase mockeado.
- `tests/test_postventa_api.py` — pruebas del router con `TestClient` + servicios mockeados.

**Frontend (crear):**
- `frontend/lib/postventa.ts` — cliente de API + tipos TS del módulo.
- `frontend/app/postventa/page.tsx` — bandeja de casos.
- `frontend/app/postventa/[caseId]/page.tsx` — detalle del caso + acciones.

---

## Task 1: Setup de pytest + máquina de estados (lógica pura)

**Files:**
- Modify: `requirements.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_postventa_logic.py`
- Create: `backend/services/postventa_logic.py`

**Interfaces:**
- Produces: `ESTADOS: set[str]`, `ESTADOS_TERMINALES: set[str]`, `TRANSICIONES: dict[str, set[str]]`, `transicion_valida(actual: str, nuevo: str) -> bool`

- [ ] **Step 1: Agregar pytest a requirements**

En `requirements.txt`, al final del archivo, agrega:
```
# Tests
pytest>=8.0
```
Instala: `pip install pytest>=8.0`

- [ ] **Step 2: Crear conftest para el path**

Crea `tests/conftest.py`:
```python
"""Asegura que la raíz del repo esté en sys.path para importar `backend`."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
```

- [ ] **Step 3: Escribir el test que falla**

Crea `tests/test_postventa_logic.py`:
```python
from backend.services import postventa_logic as L


def test_transicion_valida_flujo_feliz():
    assert L.transicion_valida("creado", "pendiente_validacion") is True
    assert L.transicion_valida("pendiente_validacion", "aprobado") is True
    assert L.transicion_valida("aprobado", "nota_credito_emitida") is True


def test_transicion_invalida_salta_pasos():
    assert L.transicion_valida("creado", "cerrado") is True  # cierre manual permitido
    assert L.transicion_valida("creado", "factura_emitida") is False


def test_no_se_puede_salir_de_estado_terminal():
    assert L.transicion_valida("rechazado", "aprobado") is False
    assert L.transicion_valida("cerrado", "creado") is False


def test_cualquiera_puede_ir_a_cerrado():
    assert L.transicion_valida("escalado", "cerrado") is True
    assert L.transicion_valida("aprobado", "cerrado") is True
```

- [ ] **Step 4: Correr el test y verificar que falla**

Run: `pytest tests/test_postventa_logic.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'backend.services.postventa_logic'`

- [ ] **Step 5: Implementar la máquina de estados**

Crea `backend/services/postventa_logic.py`:
```python
"""
backend.services.postventa_logic — Lógica pura del módulo Postventa.

Sin I/O, sin dependencias externas: constantes del dominio, máquina de
estados, validaciones y cálculos. 100% testeable con pytest.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

# ── Estados ──────────────────────────────────────────────────────────
ESTADOS: set[str] = {
    "creado",
    "pendiente_validacion",
    "aprobado",
    "rechazado",
    "nota_credito_emitida",
    "factura_emitida",
    "cerrado",
    "escalado",
}

ESTADOS_TERMINALES: set[str] = {"rechazado", "cerrado"}

# Transiciones válidas (además de "cualquiera -> cerrado", ver transicion_valida)
TRANSICIONES: dict[str, set[str]] = {
    "creado":                {"pendiente_validacion"},
    "pendiente_validacion":  {"aprobado", "rechazado", "escalado"},
    "aprobado":              {"nota_credito_emitida"},
    "nota_credito_emitida":  {"factura_emitida"},
    "factura_emitida":       set(),
    "escalado":              {"aprobado", "rechazado"},
    "rechazado":             set(),
    "cerrado":               set(),
}


def transicion_valida(actual: str, nuevo: str) -> bool:
    """True si se puede pasar de `actual` a `nuevo`.

    Reglas:
      - No se sale de un estado terminal (rechazado, cerrado).
      - Cualquier estado NO terminal puede ir a 'cerrado' (cierre manual).
      - El resto según el grafo TRANSICIONES.
    """
    if actual not in ESTADOS or nuevo not in ESTADOS:
        return False
    if actual in ESTADOS_TERMINALES:
        return False
    if nuevo == "cerrado":
        return True
    return nuevo in TRANSICIONES.get(actual, set())
```

- [ ] **Step 6: Correr el test y verificar que pasa**

Run: `pytest tests/test_postventa_logic.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt tests/conftest.py tests/test_postventa_logic.py backend/services/postventa_logic.py
git commit -m "feat(postventa): maquina de estados + setup pytest"
```

---

## Task 2: Catálogos (tipos, motivos, prioridades) + validadores

**Files:**
- Modify: `backend/services/postventa_logic.py`
- Modify: `tests/test_postventa_logic.py`

**Interfaces:**
- Produces: `TIPOS: set[str]`, `MOTIVOS: list[str]`, `PRIORIDADES: set[str]`, `validar_tipo(t) -> bool`, `validar_motivo(m) -> bool`, `validar_prioridad(p) -> bool`

- [ ] **Step 1: Escribir el test que falla**

Agrega a `tests/test_postventa_logic.py`:
```python
def test_validar_tipo():
    assert L.validar_tipo("cambio_talla") is True
    assert L.validar_tipo("garantia") is True
    assert L.validar_tipo("inexistente") is False


def test_validar_motivo():
    assert L.validar_motivo("talla_pequena") is True
    assert L.validar_motivo("error_asesoria") is True
    assert L.validar_motivo("no_existe") is False


def test_validar_prioridad():
    assert L.validar_prioridad("alta") is True
    assert L.validar_prioridad("urgentisima") is False
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_postventa_logic.py -v`
Expected: FAIL con `AttributeError: module ... has no attribute 'validar_tipo'`

- [ ] **Step 3: Implementar catálogos + validadores**

Agrega a `backend/services/postventa_logic.py` (después de `transicion_valida`):
```python
# ── Catálogos ────────────────────────────────────────────────────────
TIPOS: set[str] = {
    "cambio_talla", "cambio_ref", "reembolso", "bono", "garantia",
}

MOTIVOS: list[str] = [
    "talla_pequena", "talla_grande", "no_le_gusto_como_quedo",
    "color_diferente", "producto_defectuoso", "producto_equivocado",
    "pedido_incompleto", "demora_entrega", "arrepentimiento",
    "calidad_percibida", "error_asesoria", "error_logistico",
    "cambio_por_otro", "garantia", "otro",
]

PRIORIDADES: set[str] = {"baja", "media", "alta"}


def validar_tipo(t: str) -> bool:
    return t in TIPOS


def validar_motivo(m: str) -> bool:
    return m in MOTIVOS


def validar_prioridad(p: str) -> bool:
    return p in PRIORIDADES
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_postventa_logic.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa_logic.py tests/test_postventa_logic.py
git commit -m "feat(postventa): catalogos tipos/motivos/prioridades + validadores"
```

---

## Task 3: Cálculo de diferencia de precio + formato de consecutivo

**Files:**
- Modify: `backend/services/postventa_logic.py`
- Modify: `tests/test_postventa_logic.py`

**Interfaces:**
- Produces: `calcular_diferencia(original: float, requested: Optional[float]) -> float`, `formato_case_number(anio: int, consecutivo: int) -> str`

- [ ] **Step 1: Escribir el test que falla**

Agrega a `tests/test_postventa_logic.py`:
```python
def test_calcular_diferencia_reemplazo_mas_caro():
    # nueva ref cuesta más -> cobra (positivo)
    assert L.calcular_diferencia(100000.0, 130000.0) == 30000.0


def test_calcular_diferencia_reemplazo_mas_barato():
    # nueva ref cuesta menos -> devuelve (negativo)
    assert L.calcular_diferencia(100000.0, 80000.0) == -20000.0


def test_calcular_diferencia_reembolso_devuelve_todo():
    # sin reemplazo (reembolso/bono) -> devuelve todo el original
    assert L.calcular_diferencia(100000.0, None) == -100000.0


def test_formato_case_number():
    assert L.formato_case_number(2026, 1) == "PV-2026-0001"
    assert L.formato_case_number(2026, 45) == "PV-2026-0045"
    assert L.formato_case_number(2026, 1234) == "PV-2026-1234"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_postventa_logic.py -v`
Expected: FAIL con `AttributeError: ... 'calcular_diferencia'`

- [ ] **Step 3: Implementar**

Agrega a `backend/services/postventa_logic.py`:
```python
# ── Cálculos ─────────────────────────────────────────────────────────
def calcular_diferencia(original: float, requested: Optional[float]) -> float:
    """Diferencia de precio del item. Convención: + cobra, - devuelve.

    - requested None (reembolso/bono) -> se devuelve todo el original.
    - requested con valor -> requested - original.
    Se usa Decimal para no arrastrar error de punto flotante y se
    devuelve float con 2 decimales (COP).
    """
    o = Decimal(str(original))
    if requested is None:
        return float(-o)
    r = Decimal(str(requested))
    return float(r - o)


def formato_case_number(anio: int, consecutivo: int) -> str:
    """Consecutivo legible: PV-2026-0001 (mínimo 4 dígitos, crece si hace falta)."""
    return f"PV-{anio}-{consecutivo:04d}"
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_postventa_logic.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa_logic.py tests/test_postventa_logic.py
git commit -m "feat(postventa): calculo de diferencia de precio + formato consecutivo"
```

---

## Task 4: Migración Supabase (5 tablas)

**Files:**
- Create: `SUPABASE_MIGRATION_POSTVENTA.sql`

**Interfaces:**
- Produces: tablas `postventa_cases`, `postventa_items`, `postventa_evidence`, `postventa_timeline`, `postventa_fiscal` en Supabase.

> Nota: este repo aplica las migraciones **manualmente** en el SQL Editor de Supabase (convención de los otros `SUPABASE_MIGRATION_*.sql`). El "test" de esta tarea es la revisión del DDL + su aplicación manual.

- [ ] **Step 1: Escribir el DDL**

Crea `SUPABASE_MIGRATION_POSTVENTA.sql`:
```sql
-- ═══════════════════════════════════════════════════════════════════
-- MALE POSTVENTA IA — Migración base (Sub-proyecto #1: Postventa Core)
-- Aplicar en Supabase SQL Editor. Idempotente (IF NOT EXISTS).
-- ═══════════════════════════════════════════════════════════════════

create extension if not exists "pgcrypto";

-- 1. Casos ───────────────────────────────────────────────────────────
create table if not exists postventa_cases (
  id                  uuid primary key default gen_random_uuid(),
  case_number         text unique not null,
  shopify_order_id    text,
  shopify_order_name  text,
  customer_email      text,
  customer_phone      text,
  customer_name       text,
  status              text not null default 'creado',
  type                text not null,
  reason              text not null,
  subreason           text,
  priority            text not null default 'media',
  source              text not null default 'interno',
  assigned_to         uuid,
  notes_internas      text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  closed_at           timestamptz
);
create index if not exists idx_postventa_cases_status on postventa_cases(status);
create index if not exists idx_postventa_cases_created on postventa_cases(created_at desc);

-- 2. Items ───────────────────────────────────────────────────────────
create table if not exists postventa_items (
  id                 uuid primary key default gen_random_uuid(),
  case_id            uuid not null references postventa_cases(id) on delete cascade,
  original_sku       text,
  original_variant   text,
  original_price     numeric(12,2),
  requested_sku      text,
  requested_variant  text,
  requested_price    numeric(12,2),
  price_difference   numeric(12,2),
  item_status        text not null default 'pendiente'
);
create index if not exists idx_postventa_items_case on postventa_items(case_id);

-- 3. Evidencias ──────────────────────────────────────────────────────
create table if not exists postventa_evidence (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references postventa_cases(id) on delete cascade,
  file_url     text not null,
  file_type    text,
  uploaded_by  uuid,
  created_at   timestamptz not null default now()
);
create index if not exists idx_postventa_evidence_case on postventa_evidence(case_id);

-- 4. Timeline ────────────────────────────────────────────────────────
create table if not exists postventa_timeline (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references postventa_cases(id) on delete cascade,
  event_type   text not null,
  description  text,
  created_by   text,            -- uuid del usuario o 'sistema'
  created_at   timestamptz not null default now()
);
create index if not exists idx_postventa_timeline_case on postventa_timeline(case_id, created_at);

-- 5. Fiscal (usado por el plan #2, se crea desde ya) ──────────────────
create table if not exists postventa_fiscal (
  id                     uuid primary key default gen_random_uuid(),
  case_id                uuid not null references postventa_cases(id) on delete cascade,
  doc_kind               text not null,     -- 'nota_credito' | 'factura'
  siigo_invoice_ref      text,
  siigo_document_id      text,
  siigo_document_number  text,
  amount                 numeric(12,2),
  status                 text not null default 'pendiente',
  error_detail           text,
  payload_snapshot       jsonb,
  created_at             timestamptz not null default now()
);
create index if not exists idx_postventa_fiscal_case on postventa_fiscal(case_id);
```

- [ ] **Step 2: Revisar el DDL**

Verifica: 5 tablas, FKs con `on delete cascade`, índices por `case_id` y por `status`/`created_at`, `case_number` único, defaults coherentes con el enum de estados (`'creado'`).

- [ ] **Step 3: Aplicar en Supabase**

Manual: abrir Supabase SQL Editor del proyecto de MALE DENIM OS → pegar el archivo → Run. Confirmar que aparecen las 5 tablas.

- [ ] **Step 4: Commit**

```bash
git add SUPABASE_MIGRATION_POSTVENTA.sql
git commit -m "feat(postventa): migracion supabase 5 tablas del modulo"
```

---

## Task 5: Servicio — crear_caso + obtener_caso + listar_casos

**Files:**
- Create: `backend/services/postventa.py`
- Create: `tests/test_postventa_service.py`

**Interfaces:**
- Consumes: `postventa_logic.validar_tipo/validar_motivo/validar_prioridad/formato_case_number`
- Produces:
  - `crear_caso(*, tipo: str, reason: str, customer_email: str = "", customer_phone: str = "", customer_name: str = "", shopify_order_id: str = "", shopify_order_name: str = "", subreason: str = "", priority: str = "media", source: str = "interno", assigned_to: str | None = None) -> dict`
  - `obtener_caso(case_id: str) -> Optional[dict]`
  - `listar_casos(status: str | None = None) -> list[dict]`

- [ ] **Step 1: Escribir el test que falla (Supabase mockeado)**

Crea `tests/test_postventa_service.py`:
```python
import pytest
from unittest.mock import MagicMock
from backend.services import postventa as svc


class FakeSupabase:
    """Mock mínimo del cliente supabase: encadena table().insert().execute() etc."""
    def __init__(self):
        self.inserted = []
        self._count_resp = 3  # ya existen 3 casos este año

    def table(self, name):
        self._table = name
        return self

    def insert(self, data):
        self.inserted.append((self._table, data))
        self._payload = data
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        resp = MagicMock()
        resp.data = [self._payload] if getattr(self, "_payload", None) else []
        resp.count = self._count_resp
        return resp


def test_crear_caso_valida_tipo(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    monkeypatch.setattr(svc, "_siguiente_consecutivo", lambda anio: 4)
    caso = svc.crear_caso(tipo="cambio_talla", reason="talla_pequena",
                          customer_email="a@b.com")
    assert caso["case_number"].startswith("PV-")
    assert caso["case_number"].endswith("0004")
    assert caso["status"] == "creado"
    assert caso["source"] == "interno"


def test_crear_caso_tipo_invalido(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    with pytest.raises(ValueError, match="tipo_invalido"):
        svc.crear_caso(tipo="xxx", reason="talla_pequena")
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_postventa_service.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'backend.services.postventa'`

- [ ] **Step 3: Implementar el servicio (base + crear/obtener/listar)**

Crea `backend/services/postventa.py`:
```python
"""
backend.services.postventa — Orquestación del módulo Postventa.

Acceso Supabase + reglas de negocio que combinan postventa_logic con I/O.
Sigue el patrón _sb() de los otros servicios (revenue_db, clientes).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

from backend.services import postventa_logic as L

log = logging.getLogger("postventa")
_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    _client = create_client(url, key)
    return _client


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _siguiente_consecutivo(anio: int) -> int:
    """Cuenta cuántos casos existen del año y devuelve el siguiente número.

    Simple y suficiente para el volumen de MALE Denim. Si en el futuro hay
    concurrencia alta, se migra a una secuencia postgres.
    """
    sb = _sb()
    if sb is None:
        return 1
    inicio = f"{anio}-01-01T00:00:00+00:00"
    r = (sb.table("postventa_cases")
           .select("id", count="exact")
           .gte("created_at", inicio)
           .execute())
    return (getattr(r, "count", None) or 0) + 1


def crear_caso(*, tipo: str, reason: str, customer_email: str = "",
               customer_phone: str = "", customer_name: str = "",
               shopify_order_id: str = "", shopify_order_name: str = "",
               subreason: str = "", priority: str = "media",
               source: str = "interno",
               assigned_to: Optional[str] = None) -> dict:
    """Crea un caso de postventa. Agnóstico a la puerta de entrada (source)."""
    if not L.validar_tipo(tipo):
        raise ValueError("tipo_invalido")
    if not L.validar_motivo(reason):
        raise ValueError("motivo_invalido")
    if not L.validar_prioridad(priority):
        raise ValueError("prioridad_invalida")

    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")

    anio = datetime.now(timezone.utc).year
    case_number = L.formato_case_number(anio, _siguiente_consecutivo(anio))

    data = {
        "case_number": case_number,
        "shopify_order_id": shopify_order_id or None,
        "shopify_order_name": shopify_order_name or None,
        "customer_email": customer_email or None,
        "customer_phone": customer_phone or None,
        "customer_name": customer_name or None,
        "status": "creado",
        "type": tipo,
        "reason": reason,
        "subreason": subreason or None,
        "priority": priority,
        "source": source,
        "assigned_to": assigned_to,
    }
    r = sb.table("postventa_cases").insert(data).execute()
    caso = (r.data or [data])[0]
    return caso


def obtener_caso(case_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    r = sb.table("postventa_cases").select("*").eq("id", case_id).limit(1).execute()
    filas = r.data or []
    return filas[0] if filas else None


def listar_casos(status: Optional[str] = None) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    q = sb.table("postventa_cases").select("*")
    if status:
        q = q.eq("status", status)
    r = q.order("created_at", desc=True).execute()
    return r.data or []
```

> Nota para el implementador: en `_siguiente_consecutivo` el fake test no encadena `.gte(...)`; agrega `gte` al fake si tu mock lo requiere, o el monkeypatch de `_siguiente_consecutivo` en el test ya lo evita (el test 1 lo mockea). El test 2 falla antes de tocar la DB (tipo inválido).

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_postventa_service.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa.py tests/test_postventa_service.py
git commit -m "feat(postventa): servicio crear_caso/obtener_caso/listar_casos"
```

---

## Task 6: Servicio — timeline automático + cambiar_estado

**Files:**
- Modify: `backend/services/postventa.py`
- Modify: `tests/test_postventa_service.py`

**Interfaces:**
- Consumes: `postventa_logic.transicion_valida`, `obtener_caso`
- Produces:
  - `registrar_evento(case_id: str, event_type: str, description: str = "", created_by: str = "sistema") -> dict`
  - `cambiar_estado(case_id: str, nuevo_estado: str, *, actor: str = "sistema", motivo: str = "") -> dict`

- [ ] **Step 1: Escribir el test que falla**

Agrega a `tests/test_postventa_service.py`:
```python
def test_cambiar_estado_valido(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(svc, "_sb", lambda: fake)
    monkeypatch.setattr(svc, "obtener_caso",
                        lambda cid: {"id": cid, "status": "pendiente_validacion"})
    monkeypatch.setattr(svc, "_notificar_estado", lambda caso, estado: None)
    caso = svc.cambiar_estado("c1", "aprobado", actor="u1")
    assert caso["status"] == "aprobado"
    # se registró el evento en timeline
    assert any(t[0] == "postventa_timeline" for t in fake.inserted)


def test_cambiar_estado_invalido(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    monkeypatch.setattr(svc, "obtener_caso",
                        lambda cid: {"id": cid, "status": "creado"})
    with pytest.raises(ValueError, match="transicion_invalida"):
        svc.cambiar_estado("c1", "factura_emitida", actor="u1")
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_postventa_service.py -v`
Expected: FAIL con `AttributeError: ... 'cambiar_estado'`

- [ ] **Step 3: Implementar**

Agrega a `backend/services/postventa.py`:
```python
def registrar_evento(case_id: str, event_type: str, description: str = "",
                     created_by: str = "sistema") -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    data = {
        "case_id": case_id,
        "event_type": event_type,
        "description": description,
        "created_by": created_by,
    }
    r = sb.table("postventa_timeline").insert(data).execute()
    return (r.data or [data])[0]


def cambiar_estado(case_id: str, nuevo_estado: str, *, actor: str = "sistema",
                   motivo: str = "") -> dict:
    """Cambia el estado validando la transición y registra timeline + notifica."""
    caso = obtener_caso(case_id)
    if caso is None:
        raise ValueError("caso_no_encontrado")
    actual = caso.get("status", "")
    if not L.transicion_valida(actual, nuevo_estado):
        raise ValueError("transicion_invalida")

    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")

    campos = {"status": nuevo_estado, "updated_at": _ahora()}
    if nuevo_estado in L.ESTADOS_TERMINALES:
        campos["closed_at"] = _ahora()
    r = sb.table("postventa_cases").update(campos).eq("id", case_id).execute()

    desc = f"{actual} → {nuevo_estado}" + (f" · {motivo}" if motivo else "")
    registrar_evento(case_id, "cambio_estado", desc, created_by=actor)

    caso_actualizado = {**caso, **campos}
    _notificar_estado(caso_actualizado, nuevo_estado)
    return caso_actualizado


def _notificar_estado(caso: dict, estado: str) -> None:
    """Placeholder — se implementa en la tarea de notificaciones (Task 7)."""
    return None
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_postventa_service.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa.py tests/test_postventa_service.py
git commit -m "feat(postventa): cambiar_estado con validacion + timeline automatico"
```

---

## Task 7: Notificaciones WhatsApp por estado

**Files:**
- Modify: `backend/services/postventa.py`
- Modify: `tests/test_postventa_service.py`

**Interfaces:**
- Consumes: `whatsapp_cloud.enviar_texto(telefono, mensaje) -> dict`, `registrar_evento`
- Produces: `_notificar_estado(caso: dict, estado: str) -> None` (reemplaza el placeholder), `PLANTILLAS_WA: dict[str, str]`

- [ ] **Step 1: Escribir el test que falla**

Agrega a `tests/test_postventa_service.py`:
```python
def test_notificar_estado_envia_wa(monkeypatch):
    enviados = []
    monkeypatch.setattr(svc.whatsapp_cloud, "enviar_texto",
                        lambda tel, msg: enviados.append((tel, msg)) or {"enviado": True})
    monkeypatch.setattr(svc, "registrar_evento", lambda *a, **k: {})
    caso = {"id": "c1", "customer_phone": "3001234567", "case_number": "PV-2026-0004"}
    svc._notificar_estado(caso, "aprobado")
    assert len(enviados) == 1
    assert "PV-2026-0004" in enviados[0][1]


def test_notificar_estado_sin_plantilla_no_envia(monkeypatch):
    enviados = []
    monkeypatch.setattr(svc.whatsapp_cloud, "enviar_texto",
                        lambda tel, msg: enviados.append((tel, msg)))
    caso = {"id": "c1", "customer_phone": "3001234567", "case_number": "PV-2026-0004"}
    svc._notificar_estado(caso, "pendiente_validacion")  # sin plantilla
    assert enviados == []
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_postventa_service.py -v`
Expected: FAIL (`enviados` vacío en el primer test; `_notificar_estado` aún es placeholder)

- [ ] **Step 3: Implementar**

En `backend/services/postventa.py`, agrega el import arriba (junto a los otros):
```python
from backend.services import whatsapp_cloud
```
Y reemplaza el `_notificar_estado` placeholder por:
```python
PLANTILLAS_WA: dict[str, str] = {
    "aprobado": "¡Hola! 💛 Tu solicitud {case_number} en MALE Denim fue APROBADA. "
                "Pronto te contamos los siguientes pasos.",
    "nota_credito_emitida": "Generamos tu nota crédito para la solicitud {case_number}. "
                            "Ya quedó en el sistema ✅.",
    "factura_emitida": "¡Listo! Tu cambio de la solicitud {case_number} va en camino. "
                       "Gracias por confiar en MALE Denim 💛.",
    "rechazado": "Sobre tu solicitud {case_number}: no fue posible aprobarla. "
                 "Escríbenos y con gusto te explicamos.",
}


def _notificar_estado(caso: dict, estado: str) -> None:
    """Envía WhatsApp en los momentos clave. Nunca bloquea el flujo del caso."""
    plantilla = PLANTILLAS_WA.get(estado)
    telefono = (caso.get("customer_phone") or "").strip()
    if not plantilla or not telefono:
        return None
    mensaje = plantilla.format(case_number=caso.get("case_number", ""))
    try:
        res = whatsapp_cloud.enviar_texto(telefono, mensaje)
        ok = bool(res.get("enviado")) if isinstance(res, dict) else False
        registrar_evento(
            caso["id"], "notificacion_wa",
            f"WhatsApp '{estado}' {'enviado' if ok else 'no entregado'}",
            created_by="sistema",
        )
    except Exception as e:  # notificación es secundaria: no romper el caso
        log.warning(f"[postventa] fallo notificacion wa: {e}")
    return None
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_postventa_service.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa.py tests/test_postventa_service.py
git commit -m "feat(postventa): notificaciones WhatsApp por estado clave"
```

---

## Task 8: Items, evidencias y vínculo Shopify

**Files:**
- Modify: `backend/services/postventa.py`
- Modify: `tests/test_postventa_service.py`

**Interfaces:**
- Consumes: `postventa_logic.calcular_diferencia`, `clientes.clasificar(email, telefono) -> dict`
- Produces:
  - `agregar_item(case_id: str, *, original_sku: str = "", original_variant: str = "", original_price: float = 0, requested_sku: str = "", requested_variant: str = "", requested_price: float | None = None) -> dict`
  - `agregar_evidencia(case_id: str, file_url: str, file_type: str = "", uploaded_by: str | None = None) -> dict`
  - `pedido_shopify(email: str = "", telefono: str = "") -> dict`

- [ ] **Step 1: Escribir el test que falla**

Agrega a `tests/test_postventa_service.py`:
```python
def test_agregar_item_calcula_diferencia(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(svc, "_sb", lambda: fake)
    item = svc.agregar_item("c1", original_sku="A-M", original_price=100000.0,
                            requested_sku="A-L", requested_price=130000.0)
    assert item["price_difference"] == 30000.0
    assert item["item_status"] == "pendiente"


def test_agregar_item_reembolso(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    item = svc.agregar_item("c1", original_sku="A-M", original_price=100000.0)
    assert item["price_difference"] == -100000.0


def test_pedido_shopify_reusa_clientes(monkeypatch):
    monkeypatch.setattr(svc.clientes, "clasificar",
                        lambda email="", telefono="": {"tier": "vip", "pedidos": []})
    r = svc.pedido_shopify(email="a@b.com")
    assert r["tier"] == "vip"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_postventa_service.py -v`
Expected: FAIL con `AttributeError: ... 'agregar_item'`

- [ ] **Step 3: Implementar**

En `backend/services/postventa.py` agrega el import (junto a los otros):
```python
from backend.services import clientes
```
Y agrega las funciones:
```python
def agregar_item(case_id: str, *, original_sku: str = "", original_variant: str = "",
                 original_price: float = 0, requested_sku: str = "",
                 requested_variant: str = "",
                 requested_price: Optional[float] = None) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    diferencia = L.calcular_diferencia(original_price, requested_price)
    data = {
        "case_id": case_id,
        "original_sku": original_sku or None,
        "original_variant": original_variant or None,
        "original_price": original_price,
        "requested_sku": requested_sku or None,
        "requested_variant": requested_variant or None,
        "requested_price": requested_price,
        "price_difference": diferencia,
        "item_status": "pendiente",
    }
    r = sb.table("postventa_items").insert(data).execute()
    return (r.data or [data])[0]


def agregar_evidencia(case_id: str, file_url: str, file_type: str = "",
                      uploaded_by: Optional[str] = None) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    data = {
        "case_id": case_id,
        "file_url": file_url,
        "file_type": file_type or None,
        "uploaded_by": uploaded_by,
    }
    r = sb.table("postventa_evidence").insert(data).execute()
    return (r.data or [data])[0]


def pedido_shopify(email: str = "", telefono: str = "") -> dict:
    """Trae historial Shopify del cliente reutilizando el servicio existente."""
    return clientes.clasificar(email=email, telefono=telefono)
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_postventa_service.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa.py tests/test_postventa_service.py
git commit -m "feat(postventa): items con diferencia, evidencias y vinculo Shopify"
```

---

## Task 9: Dashboard (contadores)

**Files:**
- Modify: `backend/services/postventa.py`
- Modify: `tests/test_postventa_service.py`

**Interfaces:**
- Produces: `contadores_dashboard() -> dict` con claves `por_estado: dict[str,int]`, `abiertos: int`, `cerrados: int`, `top_motivos: list[dict]`

- [ ] **Step 1: Escribir el test que falla**

Agrega a `tests/test_postventa_service.py`:
```python
def test_contadores_dashboard(monkeypatch):
    casos = [
        {"status": "creado", "reason": "talla_pequena"},
        {"status": "creado", "reason": "talla_pequena"},
        {"status": "cerrado", "reason": "color_diferente"},
        {"status": "aprobado", "reason": "talla_grande"},
    ]
    monkeypatch.setattr(svc, "listar_casos", lambda status=None: casos)
    d = svc.contadores_dashboard()
    assert d["por_estado"]["creado"] == 2
    assert d["cerrados"] == 1
    assert d["abiertos"] == 3
    assert d["top_motivos"][0]["motivo"] == "talla_pequena"
    assert d["top_motivos"][0]["total"] == 2
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_postventa_service.py -v`
Expected: FAIL con `AttributeError: ... 'contadores_dashboard'`

- [ ] **Step 3: Implementar**

Agrega a `backend/services/postventa.py`:
```python
from collections import Counter


def contadores_dashboard() -> dict:
    """Contadores para el dashboard básico. Los KPIs profundos son Fase 6."""
    casos = listar_casos()
    por_estado = Counter(c.get("status", "?") for c in casos)
    motivos = Counter(c.get("reason", "?") for c in casos)
    cerrados = por_estado.get("cerrado", 0) + por_estado.get("rechazado", 0)
    abiertos = len(casos) - cerrados
    top = [{"motivo": m, "total": n} for m, n in motivos.most_common(5)]
    return {
        "por_estado": dict(por_estado),
        "abiertos": abiertos,
        "cerrados": cerrados,
        "top_motivos": top,
        "total": len(casos),
    }
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_postventa_service.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa.py tests/test_postventa_service.py
git commit -m "feat(postventa): contadores del dashboard basico"
```

---

## Task 10: Router FastAPI + registro en main.py

**Files:**
- Create: `backend/api/postventa.py`
- Modify: `backend/main.py:24` (línea de import de `backend.api`) y zona de `include_router` (~línea 234)
- Create: `tests/test_postventa_api.py`

**Interfaces:**
- Consumes: todas las funciones de `backend.services.postventa`, `require_permission("postventa", "ver"/"modificar")`
- Produces: rutas REST bajo `/api/postventa`

- [ ] **Step 1: Escribir el test que falla**

Crea `tests/test_postventa_api.py`:
```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.api import postventa as api_postventa
from backend.core.security import get_current_user, CurrentUser


def _app(monkeypatch):
    app = FastAPI()
    app.include_router(api_postventa.router)
    # Bypass auth: usuario admin de prueba
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="u1", email="t@t.com", nombre="Test", rol="admin", activo=True, permisos={}
    )
    return app


def test_listar_casos_endpoint(monkeypatch):
    monkeypatch.setattr(api_postventa.svc, "listar_casos",
                        lambda status=None: [{"id": "c1", "status": "creado"}])
    client = TestClient(_app(monkeypatch))
    r = client.get("/api/postventa/casos")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "c1"


def test_crear_caso_endpoint(monkeypatch):
    monkeypatch.setattr(api_postventa.svc, "crear_caso",
                        lambda **k: {"id": "c9", "case_number": "PV-2026-0009", **k})
    client = TestClient(_app(monkeypatch))
    r = client.post("/api/postventa/casos",
                    json={"tipo": "cambio_talla", "reason": "talla_pequena",
                          "customer_email": "a@b.com"})
    assert r.status_code == 200
    assert r.json()["case_number"] == "PV-2026-0009"
```

> Nota: verifica los campos reales de `CurrentUser` en `backend/core/security.py:20` y ajusta el constructor del override si difieren.

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_postventa_api.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'backend.api.postventa'`

- [ ] **Step 3: Implementar el router**

Crea `backend/api/postventa.py`:
```python
"""
backend.api.postventa — Router del módulo MALE POSTVENTA IA (panel interno).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.security import CurrentUser, require_permission
from backend.services import postventa as svc

router = APIRouter(prefix="/api/postventa", tags=["postventa"])


# ── Modelos ──────────────────────────────────────────────────────────
class CrearCasoIn(BaseModel):
    tipo: str
    reason: str
    customer_email: str = ""
    customer_phone: str = ""
    customer_name: str = ""
    shopify_order_id: str = ""
    shopify_order_name: str = ""
    subreason: str = ""
    priority: str = "media"
    source: str = "interno"
    assigned_to: Optional[str] = None


class ItemIn(BaseModel):
    original_sku: str = ""
    original_variant: str = ""
    original_price: float = 0
    requested_sku: str = ""
    requested_variant: str = ""
    requested_price: Optional[float] = None


class EvidenciaIn(BaseModel):
    file_url: str
    file_type: str = ""


class CambioEstadoIn(BaseModel):
    nuevo_estado: str
    motivo: str = ""


# ── Endpoints ────────────────────────────────────────────────────────
@router.get("/casos")
def listar(status: Optional[str] = None,
           _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    return svc.listar_casos(status=status)


@router.post("/casos")
def crear(body: CrearCasoIn,
          user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    try:
        caso = svc.crear_caso(**body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    svc.registrar_evento(caso["id"], "creado", f"Caso creado por {user.email}",
                         created_by=user.id)
    return caso


@router.get("/casos/{case_id}")
def detalle(case_id: str,
            _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    caso = svc.obtener_caso(case_id)
    if caso is None:
        raise HTTPException(404, "caso_no_encontrado")
    return caso


@router.patch("/casos/{case_id}/estado")
def cambiar_estado(case_id: str, body: CambioEstadoIn,
                   user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    try:
        return svc.cambiar_estado(case_id, body.nuevo_estado, actor=user.id,
                                  motivo=body.motivo)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/items")
def agregar_item(case_id: str, body: ItemIn,
                 _: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    return svc.agregar_item(case_id, **body.model_dump())


@router.post("/casos/{case_id}/evidencia")
def agregar_evidencia(case_id: str, body: EvidenciaIn,
                      user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    return svc.agregar_evidencia(case_id, body.file_url, body.file_type,
                                 uploaded_by=user.id)


@router.get("/shopify")
def buscar_shopify(email: str = "", telefono: str = "",
                   _: CurrentUser = Depends(require_permission("postventa", "ver"))):
    return svc.pedido_shopify(email=email, telefono=telefono)


@router.get("/dashboard")
def dashboard(_: CurrentUser = Depends(require_permission("postventa", "ver"))):
    return svc.contadores_dashboard()
```

- [ ] **Step 4: Registrar el router en main.py**

En `backend/main.py`, agrega `postventa` a la línea de import de `backend.api` (línea ~24):
```python
from backend.api import auditoria, auth, bot, clientes, cod_acciones, comercial, conciliacion, dashboard, finanzas, health, historico, inventario, melonn, meta, metricas, pedidos, postventa, produccion, revenue
```
Y agrega el include (junto a los otros `include_router`, ~línea 234):
```python
app.include_router(postventa.router)
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `pytest tests/test_postventa_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Verificar que toda la suite pasa y el API arranca**

Run: `pytest -v`
Expected: PASS (todos)
Run: `python -c "from backend.main import app; print('ok', len(app.routes))"`
Expected: imprime `ok <n>` sin error de import.

- [ ] **Step 7: Commit**

```bash
git add backend/api/postventa.py backend/main.py tests/test_postventa_api.py
git commit -m "feat(postventa): router FastAPI + registro en main"
```

---

## Task 11: Frontend — cliente de API + tipos

**Files:**
- Create: `frontend/lib/postventa.ts`

**Interfaces:**
- Consumes: `api` de `@/lib/api`
- Produces: tipos `CasoPostventa`, `CasoDetalle`, y funciones `listarCasos`, `crearCaso`, `obtenerCaso`, `cambiarEstado`, `agregarItem`, `dashboardPostventa`

- [ ] **Step 1: Crear el cliente**

Crea `frontend/lib/postventa.ts`:
```typescript
import { api } from "@/lib/api";

export type EstadoPostventa =
  | "creado" | "pendiente_validacion" | "aprobado" | "rechazado"
  | "nota_credito_emitida" | "factura_emitida" | "cerrado" | "escalado";

export interface CasoPostventa {
  id: string;
  case_number: string;
  status: EstadoPostventa;
  type: string;
  reason: string;
  priority: string;
  customer_name?: string | null;
  customer_email?: string | null;
  customer_phone?: string | null;
  shopify_order_name?: string | null;
  created_at: string;
}

export interface DashboardPostventa {
  por_estado: Record<string, number>;
  abiertos: number;
  cerrados: number;
  total: number;
  top_motivos: { motivo: string; total: number }[];
}

export const ESTADOS_LABEL: Record<EstadoPostventa, string> = {
  creado: "Creado",
  pendiente_validacion: "Pendiente validación",
  aprobado: "Aprobado",
  rechazado: "Rechazado",
  nota_credito_emitida: "Nota crédito emitida",
  factura_emitida: "Factura emitida",
  cerrado: "Cerrado",
  escalado: "Escalado",
};

export const listarCasos = (status?: string) =>
  api.get<CasoPostventa[]>(`/api/postventa/casos${status ? `?status=${status}` : ""}`);

export const obtenerCaso = (id: string) =>
  api.get<CasoPostventa>(`/api/postventa/casos/${id}`);

export const crearCaso = (body: Record<string, unknown>) =>
  api.post<CasoPostventa>(`/api/postventa/casos`, body);

export const cambiarEstado = (id: string, nuevo_estado: string, motivo = "") =>
  api.patch<CasoPostventa>(`/api/postventa/casos/${id}/estado`, { nuevo_estado, motivo });

export const agregarItem = (id: string, body: Record<string, unknown>) =>
  api.post(`/api/postventa/casos/${id}/items`, body);

export const dashboardPostventa = () =>
  api.get<DashboardPostventa>(`/api/postventa/dashboard`);
```

- [ ] **Step 2: Verificar que compila (typecheck)**

Run: `cd frontend && npx tsc --noEmit`
Expected: sin errores nuevos en `lib/postventa.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/postventa.ts
git commit -m "feat(postventa): cliente de API y tipos en frontend"
```

---

## Task 12: Frontend — bandeja de casos

**Files:**
- Create: `frontend/app/postventa/page.tsx`

**Interfaces:**
- Consumes: `listarCasos`, `dashboardPostventa`, `ESTADOS_LABEL` de `@/lib/postventa`; patrón de `frontend/app/conciliacion/page.tsx` (react-query, `PageShell`, `KpiStrip`, `Card`, `Badge`).

- [ ] **Step 1: Crear la página de bandeja**

Crea `frontend/app/postventa/page.tsx`:
```typescript
"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtDateTime } from "@/lib/utils";
import {
  listarCasos, dashboardPostventa, ESTADOS_LABEL, type EstadoPostventa,
} from "@/lib/postventa";

export default function PostventaPage() {
  const [filtro, setFiltro] = useState<string>("");
  const casos = useQuery({
    queryKey: ["postventa-casos", filtro],
    queryFn: () => listarCasos(filtro || undefined),
  });
  const dash = useQuery({ queryKey: ["postventa-dash"], queryFn: dashboardPostventa });

  return (
    <PageShell title="Postventa" subtitle="Cambios, devoluciones y garantías">
      {dash.data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <KpiBox label="Abiertos" value={dash.data.abiertos} />
          <KpiBox label="Cerrados" value={dash.data.cerrados} />
          <KpiBox label="Total" value={dash.data.total} />
          <KpiBox label="En error fiscal"
                  value={dash.data.por_estado["error"] ?? 0} />
        </div>
      )}

      <div className="flex gap-2 mb-4 flex-wrap">
        <FiltroChip label="Todos" activo={filtro === ""} onClick={() => setFiltro("")} />
        {(Object.keys(ESTADOS_LABEL) as EstadoPostventa[]).map((e) => (
          <FiltroChip key={e} label={ESTADOS_LABEL[e]} activo={filtro === e}
                      onClick={() => setFiltro(e)} />
        ))}
      </div>

      {casos.isLoading && <LoadingState />}
      {casos.isError && <ErrorState message="No se pudieron cargar los casos" />}
      {casos.data && (
        <div className="space-y-2">
          {casos.data.length === 0 && (
            <p className="text-sm text-muted-foreground">No hay casos para este filtro.</p>
          )}
          {casos.data.map((c) => (
            <Link key={c.id} href={`/postventa/${c.id}`}>
              <Card className="hover:bg-accent/40 transition-colors">
                <CardContent className="flex items-center justify-between py-3">
                  <div>
                    <div className="font-medium">{c.case_number}
                      <span className="text-muted-foreground font-normal"> · {c.type}</span>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {c.customer_name || c.customer_email || "Sin cliente"}
                      {c.shopify_order_name ? ` · ${c.shopify_order_name}` : ""}
                    </div>
                  </div>
                  <div className="text-right">
                    <Badge>{ESTADOS_LABEL[c.status] ?? c.status}</Badge>
                    <div className="text-xs text-muted-foreground mt-1">
                      {fmtDateTime(c.created_at)}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </PageShell>
  );
}

function KpiBox({ label, value }: { label: string; value: number }) {
  return (
    <Card><CardContent className="py-3">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </CardContent></Card>
  );
}

function FiltroChip({ label, activo, onClick }:
  { label: string; activo: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`px-3 py-1 rounded-full text-sm border ${
        activo ? "bg-primary text-primary-foreground" : "bg-background"}`}>
      {label}
    </button>
  );
}
```

> Nota: verifica las props reales de `PageShell` en `frontend/components/page-shell.tsx` (¿`title`/`subtitle`?) y el nombre exacto de `fmtDateTime` en `frontend/lib/utils.ts`. Ajusta si difieren — el patrón viene de `app/conciliacion/page.tsx`.

- [ ] **Step 2: Verificar typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: sin errores nuevos.

- [ ] **Step 3: Verificar en el navegador (preview)**

Levanta el frontend y navega a `/postventa`. Confirma que la bandeja carga (aunque esté vacía) y los filtros no rompen.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/postventa/page.tsx
git commit -m "feat(postventa): bandeja de casos (frontend)"
```

---

## Task 13: Frontend — detalle del caso + acciones de estado

**Files:**
- Create: `frontend/app/postventa/[caseId]/page.tsx`

**Interfaces:**
- Consumes: `obtenerCaso`, `cambiarEstado`, `ESTADOS_LABEL` de `@/lib/postventa`; react-query `useMutation` + `useQueryClient`.

- [ ] **Step 1: Crear la página de detalle**

Crea `frontend/app/postventa/[caseId]/page.tsx`:
```typescript
"use client";

import { use } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { obtenerCaso, cambiarEstado, ESTADOS_LABEL } from "@/lib/postventa";

// Transiciones ofrecidas en UI (espejo del backend postventa_logic.TRANSICIONES).
const ACCIONES: Record<string, string[]> = {
  creado: ["pendiente_validacion"],
  pendiente_validacion: ["aprobado", "rechazado", "escalado"],
  aprobado: ["nota_credito_emitida", "cerrado"],
  escalado: ["aprobado", "rechazado"],
  nota_credito_emitida: ["factura_emitida", "cerrado"],
  factura_emitida: ["cerrado"],
};

export default function CasoDetallePage({ params }:
  { params: Promise<{ caseId: string }> }) {
  const { caseId } = use(params);
  const qc = useQueryClient();
  const caso = useQuery({ queryKey: ["postventa-caso", caseId],
                          queryFn: () => obtenerCaso(caseId) });

  const mut = useMutation({
    mutationFn: (estado: string) => cambiarEstado(caseId, estado),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["postventa-caso", caseId] });
      qc.invalidateQueries({ queryKey: ["postventa-casos"] });
    },
  });

  if (caso.isLoading) return <PageShell title="Caso"><LoadingState /></PageShell>;
  if (caso.isError || !caso.data)
    return <PageShell title="Caso"><ErrorState message="No se encontró el caso" /></PageShell>;

  const c = caso.data;
  const acciones = ACCIONES[c.status] ?? [];

  return (
    <PageShell title={c.case_number} subtitle={`${c.type} · ${c.reason}`}>
      <Card className="mb-4"><CardContent className="py-4 space-y-1">
        <div className="flex items-center gap-2">
          <Badge>{ESTADOS_LABEL[c.status] ?? c.status}</Badge>
          <span className="text-sm text-muted-foreground">
            Prioridad: {c.priority}
          </span>
        </div>
        <div className="text-sm">Cliente: {c.customer_name || c.customer_email || "—"}</div>
        <div className="text-sm">Teléfono: {c.customer_phone || "—"}</div>
        <div className="text-sm">Pedido Shopify: {c.shopify_order_name || "—"}</div>
      </CardContent></Card>

      <div className="flex gap-2 flex-wrap">
        {acciones.map((a) => (
          <Button key={a} variant="outline" disabled={mut.isPending}
                  onClick={() => mut.mutate(a)}>
            {ESTADOS_LABEL[a as keyof typeof ESTADOS_LABEL] ?? a}
          </Button>
        ))}
        {acciones.length === 0 && (
          <p className="text-sm text-muted-foreground">Caso en estado final.</p>
        )}
      </div>
      {mut.isError && (
        <p className="text-sm text-destructive mt-2">
          No se pudo cambiar el estado (transición inválida).
        </p>
      )}
    </PageShell>
  );
}
```

> Nota: verifica que `@/components/ui/button` exporta `Button` (existe en el repo por el uso de shadcn). Si la versión de Next no soporta `params` como Promise, usa `params.caseId` directo.

- [ ] **Step 2: Verificar typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: sin errores nuevos.

- [ ] **Step 3: Verificar en el navegador (preview)**

Navega a un caso `/postventa/<id>`. Confirma que se ven los datos y que los botones de acción avanzan el estado (crea un caso de prueba vía API o UI primero).

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/postventa/[caseId]/page.tsx"
git commit -m "feat(postventa): detalle del caso + acciones de estado (frontend)"
```

---

## Task 14: Enlace en navegación + verificación end-to-end

**Files:**
- Modify: `frontend/lib/nav.ts` (o el componente de navegación que liste los módulos)

**Interfaces:**
- Consumes: estructura de navegación existente.

- [ ] **Step 1: Ubicar el registro de navegación**

Run: `grep -n "conciliacion\|/inventario\|label" frontend/lib/nav.ts`
Identifica la forma de cada entrada (label, href, icono, permiso).

- [ ] **Step 2: Agregar la entrada de Postventa**

Agrega una entrada siguiendo el formato exacto que viste, por ejemplo:
```typescript
{ label: "Postventa", href: "/postventa", modulo: "postventa" },
```
(usa el mismo shape que las demás entradas — icono de lucide si aplica, ej. `RotateCcw`).

- [ ] **Step 3: Verificación end-to-end manual**

1. `pytest -v` → toda la suite en verde.
2. Levantar backend + frontend.
3. En la UI: crear un caso (tipo `cambio_talla`, motivo `talla_pequena`, con teléfono de prueba).
4. Avanzar: creado → pendiente_validacion → aprobado. Confirmar en Supabase que `postventa_timeline` tiene los eventos y que (si WhatsApp está configurado en modo prueba) llegó el mensaje de "aprobado".
5. Verificar que el dashboard muestra contadores.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/nav.ts
git commit -m "feat(postventa): enlace en navegacion del panel interno"
```

---

## Self-Review

**Spec coverage (contra `2026-07-06-postventa-ia-mvp-design.md`):**
- §3 arquitectura/ubicación → Tasks 5–14 (paths exactos, patrón de módulos). ✔
- §4 modelo de datos (5 tablas) → Task 4. ✔
- §5.1 estados + transiciones → Task 1. §5.2 motivos → Task 2. ✔
- §7.1 notificaciones WhatsApp (4 momentos) → Task 7. ✔
- §7.2 manejo de errores (WA no bloquea, Shopify opcional) → Task 7 (`_notificar_estado` try/except), Task 5 (campos opcionales). ✔
- §7.3 dashboard básico → Task 9 + Task 12. ✔
- §8 APIs → Task 10. ✔
- §9 pruebas → pytest en Tasks 1–10. ✔
- **Fuera de alcance de este plan (van al plan #2 / fases siguientes):** motor fiscal Siigo (`postventa_fiscal` se crea en Task 4 pero NO se llena aquí), preview/emit NC, reserva/despacho, portal, IA. Correcto por diseño.

**Placeholder scan:** `_notificar_estado` aparece como placeholder explícito en Task 6 y se implementa en Task 7 (intencional y señalado). No hay TODOs sin resolver.

**Type consistency:** `crear_caso(tipo=, reason=, ...)` usado igual en service (Task 5), API (Task 10) y frontend (Task 11). `cambiar_estado(case_id, nuevo_estado, actor=, motivo=)` consistente entre Task 6, 10 y `cambiarEstado` del frontend. `contadores_dashboard()` → claves `por_estado/abiertos/cerrados/top_motivos/total` iguales en Task 9 y el tipo `DashboardPostventa` (Task 11).

---

## Nota sobre el plan #2 (Motor fiscal Siigo)

Este plan deja lista la tabla `postventa_fiscal` y los estados `nota_credito_emitida`/`factura_emitida`. El **plan #2** construirá encima: `siigo_post`, spike de descubrimiento de IDs de configuración Siigo, localizar factura original, preview + emit con confirmación humana, idempotencia, reintento, modo prueba, y el gate de **20 casos de prueba** antes del switch a producción.
