# Motor fiscal Siigo (Sub-proyecto #2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emitir en Siigo la **nota crédito** que anula el ítem devuelto y la **factura del reemplazo**, desde un caso de postventa, con previsualización + confirmación humana y modo prueba.

**Architecture:** Lógica pura de armado de payloads en `fiscal_logic.py` (sin I/O, 100% testeable); implementación Siigo en `fiscal_siigo.py` detrás de un protocolo `EmisorFiscal` (para que otra marca use Alegra/World Office); orquestación (preview/emitir/reintento, idempotencia, timeline) en `postventa_fiscal.py`; endpoints en el router existente.

**Tech Stack:** Python 3.11+/3.14 (Railway), FastAPI, Supabase, httpx. Reusa `siigo.py` (auth + backoff) y `postventa.py` (casos, timeline, estados).

## Global Constraints

- **Regla de negocio:** ciclo DIAN completo SIEMPRE — NC del ítem original + factura del reemplazo. `reembolso` y `bono` → solo NC.
- La NC acredita **solo los ítems del caso**, nunca la factura completa.
- **Nada se emite sin confirmación humana.** Preview y emisión son endpoints separados.
- **Nunca reintentar automáticamente** un documento fiscal. El reintento es explícito y manual.
- **Idempotencia:** imposible emitir 2 NC para el mismo caso.
- Precios en `postventa_items` están **sin IVA** (COP). El IVA (19%, id `6352`) lo aplica el emisor.
- **Modo:** `SIIGO_POSTVENTA_MODO` = `prueba` (NC Proforma `27141`, NO va a DIAN) | `produccion` (NC electrónica `11817`). Default `prueba`.
- IDs verificados de la cuenta MALE: NC elec `11817`, NC proforma `27141`, FV online `11810`, IVA `6352`, vendedor `658`.
- Enlace Shopify: `observations` de la factura contiene `"Orden Nº: <numero>"`.
- Multi-tenant: todo lo persistido lleva `brand_id` (patrón ya existente).
- Nombres de dominio en español. Correr `pytest` desde la raíz del worktree.

---

## File Structure

**Crear:**
- `backend/services/fiscal_logic.py` — puro: extraer nº de pedido, cálculo de montos/IVA, armado de payloads NC y FV.
- `backend/services/fiscal_siigo.py` — `EmisorSiigo`: buscar factura original, emitir (POST). Implementa el protocolo.
- `backend/services/postventa_fiscal.py` — orquestación: preview, emitir, reintentar, idempotencia, timeline.
- `tests/test_fiscal_logic.py`, `tests/test_fiscal_siigo.py`, `tests/test_postventa_fiscal.py`

**Modificar:**
- `backend/services/siigo.py` — agregar `siigo_post(path, body)` con el mismo backoff que `siigo_get`.
- `backend/services/postventa_siigo.py` — agregar muestra de nota crédito real al discovery (Task 1).
- `backend/api/postventa.py` — endpoints preview / emitir / reintentar.

---

## Task 1: Discovery de una nota crédito real (cerrar el último riesgo)

Antes de construir el payload hay que ver la **forma exacta** de una NC en esta cuenta, en vez de asumirla.

**Files:**
- Modify: `backend/services/postventa_siigo.py`
- Modify: `tests/test_postventa_siigo.py`

**Interfaces:**
- Produces: `inspeccionar_notas_credito(limite: int = 2) -> dict`

- [ ] **Step 1: Test que falla**

Agrega a `tests/test_postventa_siigo.py`:
```python
def test_inspeccionar_notas_credito_extrae_estructura(monkeypatch):
    nc = {
        "id": "nc-1", "name": "NC-1-6984", "number": 6984, "date": "2026-07-01",
        "document": {"id": 11817}, "customer": {"identification": "30384838"},
        "invoice": "3ed6b96c-38bc-4334-87fa-e33e60298637",
        "items": [{"code": "REF-1", "quantity": 1, "price": 100000}],
        "payments": [{"id": 8276, "value": 119000}],
    }
    monkeypatch.setattr(pv.siigo, "siigo_configurado", lambda: True)
    monkeypatch.setattr(pv.siigo, "siigo_get",
                        lambda path, params=None: {"results": [nc]})
    r = pv.inspeccionar_notas_credito(2)
    assert r["total_en_muestra"] == 1
    m = r["notas"][0]
    assert m["document_id"] == 11817
    assert m["invoice_ref"] == "3ed6b96c-38bc-4334-87fa-e33e60298637"
    assert "items" in m["llaves_disponibles"]
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_postventa_siigo.py -v`
Expected: FAIL `AttributeError: ... 'inspeccionar_notas_credito'`

- [ ] **Step 3: Implementar**

Agrega a `backend/services/postventa_siigo.py`:
```python
def inspeccionar_notas_credito(limite: int = 2) -> dict:
    """Trae notas crédito ya emitidas para copiar su estructura exacta
    (qué campos manda Siigo, cómo referencia la factura original).
    Solo lectura."""
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    limite = max(1, min(limite, 10))
    data = _get_seguro("/credit-notes", {"page_size": limite, "page": 1})
    if isinstance(data, dict) and data.get("_error"):
        return data

    resultados = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(resultados, list):
        return {"_error": "formato_inesperado", "crudo": str(resultados)[:500]}

    notas = []
    for nc in resultados[:limite]:
        if not isinstance(nc, dict):
            continue
        notas.append({
            "id": nc.get("id"),
            "name": nc.get("name"),
            "number": nc.get("number"),
            "date": nc.get("date"),
            "document_id": (nc.get("document") or {}).get("id"),
            "customer_identification": (nc.get("customer") or {}).get("identification"),
            # Cómo referencia la factura original (clave para armar el POST)
            "invoice_ref": nc.get("invoice"),
            "items": nc.get("items"),
            "payments": nc.get("payments"),
            "llaves_disponibles": sorted(nc.keys()),
        })
    return {"total_en_muestra": len(notas), "notas": notas}
```

Y agrégala al `diagnostico()` existente:
```python
        "muestra_notas_credito": inspeccionar_notas_credito(2),
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest tests/test_postventa_siigo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa_siigo.py tests/test_postventa_siigo.py
git commit -m "feat(fiscal): discovery de notas credito reales para copiar su estructura"
```

- [ ] **Step 6: PAUSA — correr contra Siigo real**

Desplegar y llamar `GET /api/postventa/siigo/discovery`. Con la salida de `muestra_notas_credito` se confirma el nombre exacto del campo que referencia la factura original (`invoice` u otro) **antes de escribir el POST**. Ajustar las Tasks 5-7 si difiere.

---

## Task 2: `siigo_post` (escritura con backoff)

**Files:**
- Modify: `backend/services/siigo.py`
- Create: `tests/test_siigo_post.py`

**Interfaces:**
- Produces: `siigo_post(path: str, body: dict) -> dict`

- [ ] **Step 1: Test que falla**

Crea `tests/test_siigo_post.py`:
```python
import pytest
from backend.services import siigo


class FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload


def test_siigo_post_exitoso(monkeypatch):
    monkeypatch.setattr(siigo, "_get_token", lambda: "tok")
    monkeypatch.setattr(siigo.httpx, "post",
                        lambda url, **k: FakeResp(201, {"id": "nc-1"}))
    r = siigo.siigo_post("/credit-notes", {"a": 1})
    assert r["id"] == "nc-1"


def test_siigo_post_error_lanza(monkeypatch):
    monkeypatch.setattr(siigo, "_get_token", lambda: "tok")
    monkeypatch.setattr(siigo.httpx, "post",
                        lambda url, **k: FakeResp(400, text="payload malo"))
    with pytest.raises(RuntimeError, match="siigo_post"):
        siigo.siigo_post("/credit-notes", {"a": 1})
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_siigo_post.py -v`
Expected: FAIL `AttributeError: ... 'siigo_post'`

- [ ] **Step 3: Implementar**

Agrega a `backend/services/siigo.py` después de `siigo_get`:
```python
def siigo_post(path: str, body: dict) -> dict:
    """POST con retry/backoff para el rate limit de Siigo.

    OJO: crea documentos. Solo lo usa el motor fiscal de postventa, y solo
    tras confirmación humana. Un 4xx NO se reintenta (es error de payload).
    """
    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Partner-Id": os.getenv("SIIGO_PARTNER_ID", ""),
        "Content-Type": "application/json",
    }
    last = ""
    for intento in range(3):
        r = httpx.post(SIIGO_BASE + path, json=body, headers=headers, timeout=60)
        if r.status_code in (200, 201):
            return r.json()
        # 4xx = payload inválido: no tiene sentido reintentar.
        if 400 <= r.status_code < 500 and r.status_code != 429:
            raise RuntimeError(f"siigo_post {path} HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code in (429, 502, 503, 504):
            espera = min(2 ** intento, 8)
            retry_after = r.headers.get("Retry-After")
            if retry_after and str(retry_after).isdigit():
                espera = int(retry_after)
            time.sleep(espera)
            last = f"{r.status_code} intento {intento + 1}"
            continue
        raise RuntimeError(f"siigo_post {path} HTTP {r.status_code}: {r.text[:300]}")
    raise RuntimeError(f"siigo_post {path} rate-limited tras reintentos ({last})")
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest tests/test_siigo_post.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/siigo.py tests/test_siigo_post.py
git commit -m "feat(fiscal): siigo_post con backoff; 4xx no se reintenta"
```

---

## Task 3: Lógica pura — extraer nº de pedido y config por modo

**Files:**
- Create: `backend/services/fiscal_logic.py`
- Create: `tests/test_fiscal_logic.py`

**Interfaces:**
- Produces: `ORDEN_RE`, `extraer_numero_pedido(observations: str) -> Optional[str]`, `normalizar_numero_pedido(order_name: str) -> str`, `config_documentos(modo: str) -> dict`

- [ ] **Step 1: Test que falla**

Crea `tests/test_fiscal_logic.py`:
```python
from backend.services import fiscal_logic as F


def test_extraer_numero_pedido():
    obs = "Orden Nº: 60112 - Medio de Pago: Mercado Pago Tarjetas"
    assert F.extraer_numero_pedido(obs) == "60112"


def test_extraer_numero_pedido_variantes():
    assert F.extraer_numero_pedido("Orden No: 999") == "999"
    assert F.extraer_numero_pedido("orden n: 1") == "1"
    assert F.extraer_numero_pedido("") is None
    assert F.extraer_numero_pedido("sin numero") is None


def test_normalizar_numero_pedido_quita_almohadilla():
    assert F.normalizar_numero_pedido("#60112") == "60112"
    assert F.normalizar_numero_pedido(" 60112 ") == "60112"
    assert F.normalizar_numero_pedido("60112") == "60112"


def test_config_documentos_modo_prueba_no_es_electronico():
    c = F.config_documentos("prueba")
    assert c["nota_credito_id"] == 27141   # Proforma, NO va a DIAN
    assert c["electronico"] is False


def test_config_documentos_modo_produccion():
    c = F.config_documentos("produccion")
    assert c["nota_credito_id"] == 11817
    assert c["electronico"] is True
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_fiscal_logic.py -v`
Expected: FAIL `ModuleNotFoundError: ... fiscal_logic`

- [ ] **Step 3: Implementar**

Crea `backend/services/fiscal_logic.py`:
```python
"""
backend.services.fiscal_logic — Lógica PURA del motor fiscal.

Sin I/O: extracción del nº de pedido, configuración por modo y armado de
los payloads de nota crédito / factura. Todo testeable sin red ni DB.

IDs verificados contra la cuenta Siigo de MALE (ver spec del motor fiscal).
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Optional

# ── IDs de la cuenta (overridables por env en fiscal_siigo) ──────────
NC_ELECTRONICA_ID = 11817     # Nota Crédito Electrónica (va a DIAN)
NC_PROFORMA_ID = 27141        # Nota Crédito Proforma (NoElectronic, modo prueba)
FV_ONLINE_ID = 11810          # Factura de venta online ("Domicilios")
IVA_19_ID = 6352
VENDEDOR_ONLINE_ID = 658

IVA_PORCENTAJE = Decimal("19")

# "Orden Nº: 60112 - Medio de Pago: ..."  → 60112
ORDEN_RE = re.compile(r"orden\s*n[ºo°]?\s*:?\s*(\d+)", re.IGNORECASE)


def extraer_numero_pedido(observations: str) -> Optional[str]:
    """Saca el nº de pedido Shopify del campo observations de la factura."""
    if not observations:
        return None
    m = ORDEN_RE.search(observations)
    return m.group(1) if m else None


def normalizar_numero_pedido(order_name: str) -> str:
    """'#60112' → '60112'. Lo que guarda el caso vs lo que trae Siigo."""
    return (order_name or "").strip().lstrip("#").strip()


def config_documentos(modo: str) -> dict:
    """Config de documentos según el modo de operación.

    'prueba' usa la NC Proforma (NoElectronic): ejercita todo el flujo
    contra la cuenta real SIN emitir ante la DIAN.
    """
    if modo == "produccion":
        return {"nota_credito_id": NC_ELECTRONICA_ID, "factura_id": FV_ONLINE_ID,
                "electronico": True}
    return {"nota_credito_id": NC_PROFORMA_ID, "factura_id": FV_ONLINE_ID,
            "electronico": False}
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest tests/test_fiscal_logic.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/fiscal_logic.py tests/test_fiscal_logic.py
git commit -m "feat(fiscal): logica pura de nº de pedido y config por modo"
```

---

## Task 4: Lógica pura — cálculo de montos con IVA

**Files:**
- Modify: `backend/services/fiscal_logic.py`
- Modify: `tests/test_fiscal_logic.py`

**Interfaces:**
- Produces: `calcular_iva(valor_sin_iva: float) -> float`, `total_con_iva(valor_sin_iva: float) -> float`, `total_items(items: list[dict]) -> dict`

- [ ] **Step 1: Test que falla**

Agrega a `tests/test_fiscal_logic.py`:
```python
def test_calcular_iva_19():
    assert F.calcular_iva(100000.0) == 19000.0


def test_total_con_iva():
    assert F.total_con_iva(100000.0) == 119000.0


def test_total_items_suma_sin_y_con_iva():
    items = [
        {"original_price": 100000.0, "cantidad": 1},
        {"original_price": 50000.0, "cantidad": 2},
    ]
    r = F.total_items(items, campo_precio="original_price")
    assert r["subtotal"] == 200000.0
    assert r["iva"] == 38000.0
    assert r["total"] == 238000.0


def test_total_items_vacio():
    r = F.total_items([], campo_precio="original_price")
    assert r == {"subtotal": 0.0, "iva": 0.0, "total": 0.0}
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_fiscal_logic.py -v`
Expected: FAIL `AttributeError: ... 'calcular_iva'`

- [ ] **Step 3: Implementar**

Agrega a `backend/services/fiscal_logic.py`:
```python
def calcular_iva(valor_sin_iva: float) -> float:
    """IVA 19% sobre un valor SIN iva. Decimal para no arrastrar error float."""
    v = Decimal(str(valor_sin_iva))
    return float((v * IVA_PORCENTAJE / Decimal("100")).quantize(Decimal("0.01")))


def total_con_iva(valor_sin_iva: float) -> float:
    return float(
        (Decimal(str(valor_sin_iva)) + Decimal(str(calcular_iva(valor_sin_iva))))
        .quantize(Decimal("0.01"))
    )


def total_items(items: list[dict], *, campo_precio: str) -> dict:
    """Suma de una lista de ítems: subtotal (sin IVA), IVA y total."""
    subtotal = Decimal("0")
    for it in items:
        precio = Decimal(str(it.get(campo_precio) or 0))
        cantidad = Decimal(str(it.get("cantidad") or 1))
        subtotal += precio * cantidad
    subtotal = subtotal.quantize(Decimal("0.01"))
    iva = Decimal(str(calcular_iva(float(subtotal))))
    return {"subtotal": float(subtotal), "iva": float(iva),
            "total": float((subtotal + iva).quantize(Decimal("0.01")))}
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest tests/test_fiscal_logic.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/fiscal_logic.py tests/test_fiscal_logic.py
git commit -m "feat(fiscal): calculo de IVA y totales con Decimal"
```

---

## Task 5: Lógica pura — armar payload de la nota crédito

> ⚠️ Ajustar los nombres de campo según la salida real de `muestra_notas_credito` (Task 1, Step 6) antes de implementar.

**Files:**
- Modify: `backend/services/fiscal_logic.py`
- Modify: `tests/test_fiscal_logic.py`

**Interfaces:**
- Produces: `construir_payload_nota_credito(*, factura: dict, items: list[dict], modo: str, fecha: str) -> dict`

- [ ] **Step 1: Test que falla**

Agrega a `tests/test_fiscal_logic.py`:
```python
FACTURA = {
    "id": "3ed6b96c-38bc-4334-87fa-e33e60298637",
    "name": "FV-1-63043",
    "customer": {"identification": "30384838", "branch_office": 0},
    "seller": 658,
    "payments": [{"id": 8276, "value": 119000}],
}


def test_payload_nc_modo_prueba_usa_proforma():
    items = [{"codigo": "REF-1", "descripcion": "Jean", "cantidad": 1,
              "precio_sin_iva": 100000.0}]
    p = F.construir_payload_nota_credito(factura=FACTURA, items=items,
                                         modo="prueba", fecha="2026-07-07")
    assert p["document"]["id"] == 27141          # Proforma, NO DIAN
    assert p["invoice"] == FACTURA["id"]         # referencia la factura original
    assert p["customer"]["identification"] == "30384838"
    assert p["seller"] == 658
    assert p["date"] == "2026-07-07"
    assert p["items"][0]["code"] == "REF-1"
    assert p["items"][0]["price"] == 100000.0
    assert p["items"][0]["taxes"] == [{"id": 6352}]
    # el pago de la NC cuadra con el total CON iva del ítem acreditado
    assert p["payments"][0]["value"] == 119000.0


def test_payload_nc_modo_produccion_usa_electronica():
    items = [{"codigo": "REF-1", "descripcion": "Jean", "cantidad": 1,
              "precio_sin_iva": 100000.0}]
    p = F.construir_payload_nota_credito(factura=FACTURA, items=items,
                                         modo="produccion", fecha="2026-07-07")
    assert p["document"]["id"] == 11817


def test_payload_nc_sin_items_falla():
    import pytest
    with pytest.raises(ValueError, match="sin_items"):
        F.construir_payload_nota_credito(factura=FACTURA, items=[],
                                         modo="prueba", fecha="2026-07-07")
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_fiscal_logic.py -v`
Expected: FAIL `AttributeError: ... 'construir_payload_nota_credito'`

- [ ] **Step 3: Implementar**

Agrega a `backend/services/fiscal_logic.py`:
```python
def construir_payload_nota_credito(*, factura: dict, items: list[dict],
                                   modo: str, fecha: str) -> dict:
    """Arma el cuerpo del POST de la nota crédito. NO emite nada.

    `items` son los ítems del CASO (los que se devuelven), con precios
    SIN IVA. La NC acredita solo esos, no la factura completa.
    """
    if not items:
        raise ValueError("sin_items")
    if not factura or not factura.get("id"):
        raise ValueError("sin_factura_original")

    cfg = config_documentos(modo)
    cliente = factura.get("customer") or {}

    lineas = []
    for it in items:
        lineas.append({
            "code": it.get("codigo"),
            "description": it.get("descripcion") or "",
            "quantity": it.get("cantidad") or 1,
            "price": float(it.get("precio_sin_iva") or 0),
            "taxes": [{"id": IVA_19_ID}],
        })

    totales = total_items(
        [{"original_price": it.get("precio_sin_iva"),
          "cantidad": it.get("cantidad") or 1} for it in items],
        campo_precio="original_price",
    )

    # Se refleja la forma de pago de la factura original para que la
    # devolución quede en la misma cuenta contable.
    pagos_orig = factura.get("payments") or []
    pago_id = (pagos_orig[0].get("id") if pagos_orig else None)

    return {
        "document": {"id": cfg["nota_credito_id"]},
        "date": fecha,
        "invoice": factura["id"],
        "customer": {
            "identification": cliente.get("identification"),
            "branch_office": cliente.get("branch_office", 0),
        },
        "seller": factura.get("seller") or VENDEDOR_ONLINE_ID,
        "items": lineas,
        "payments": ([{"id": pago_id, "value": totales["total"]}]
                     if pago_id else []),
        "observations": f"Postventa — anula ítems de {factura.get('name', '')}",
    }
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest tests/test_fiscal_logic.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/fiscal_logic.py tests/test_fiscal_logic.py
git commit -m "feat(fiscal): payload de nota credito (puro, sin emitir)"
```

---

## Task 6: `EmisorSiigo` — buscar la factura original

**Files:**
- Create: `backend/services/fiscal_siigo.py`
- Create: `tests/test_fiscal_siigo.py`

**Interfaces:**
- Consumes: `siigo.siigo_get`, `fiscal_logic.extraer_numero_pedido`, `normalizar_numero_pedido`
- Produces: `EmisorSiigo.buscar_factura_original(*, numero_pedido: str, desde: str = "", hasta: str = "") -> Optional[dict]`

- [ ] **Step 1: Test que falla**

Crea `tests/test_fiscal_siigo.py`:
```python
from backend.services import fiscal_siigo as FS


FACTURAS = {"results": [
    {"id": "f1", "name": "FV-1-63041",
     "observations": "Orden Nº: 60110 - Medio de Pago: Wompi"},
    {"id": "f2", "name": "FV-1-63043",
     "observations": "Orden Nº: 60112 - Medio de Pago: Mercado Pago"},
]}


def test_busca_factura_por_numero_de_pedido(monkeypatch):
    monkeypatch.setattr(FS.siigo, "siigo_get", lambda p, params=None: FACTURAS)
    e = FS.EmisorSiigo()
    f = e.buscar_factura_original(numero_pedido="#60112")
    assert f["id"] == "f2"


def test_no_encuentra_devuelve_none(monkeypatch):
    monkeypatch.setattr(FS.siigo, "siigo_get", lambda p, params=None: FACTURAS)
    e = FS.EmisorSiigo()
    assert e.buscar_factura_original(numero_pedido="#99999") is None
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_fiscal_siigo.py -v`
Expected: FAIL `ModuleNotFoundError: ... fiscal_siigo`

- [ ] **Step 3: Implementar**

Crea `backend/services/fiscal_siigo.py`:
```python
"""
backend.services.fiscal_siigo — Implementación Siigo del EmisorFiscal.

Hace el I/O contra Siigo (buscar la factura original, emitir documentos).
El armado de payloads vive en fiscal_logic (puro).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from backend.services import siigo
from backend.services import fiscal_logic as F

log = logging.getLogger("fiscal_siigo")

_MAX_PAGINAS = 20


def modo_actual() -> str:
    """'prueba' (default, no toca DIAN) | 'produccion'."""
    m = os.environ.get("SIIGO_POSTVENTA_MODO", "prueba").strip().lower()
    return "produccion" if m == "produccion" else "prueba"


class EmisorSiigo:
    """Emisor fiscal para Siigo. Implementa el protocolo EmisorFiscal."""

    nombre = "siigo"

    def buscar_factura_original(self, *, numero_pedido: str,
                                desde: str = "", hasta: str = "") -> Optional[dict]:
        """Encuentra la factura de venta online cuyo `observations` contiene
        'Orden Nº: <numero_pedido>'. Devuelve None si no existe."""
        objetivo = F.normalizar_numero_pedido(numero_pedido)
        if not objetivo:
            return None

        params = {"page_size": 100, "document_id": F.FV_ONLINE_ID}
        if desde:
            params["date_start"] = desde
        if hasta:
            params["date_end"] = hasta

        for pagina in range(1, _MAX_PAGINAS + 1):
            params["page"] = pagina
            data = siigo.siigo_get("/invoices", params)
            resultados = data.get("results", []) if isinstance(data, dict) else []
            if not resultados:
                return None
            for inv in resultados:
                encontrado = F.extraer_numero_pedido(inv.get("observations") or "")
                if encontrado == objetivo:
                    return inv
        return None
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest tests/test_fiscal_siigo.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/fiscal_siigo.py tests/test_fiscal_siigo.py
git commit -m "feat(fiscal): EmisorSiigo busca la factura original por nº de pedido"
```

---

## Task 7: `EmisorSiigo.emitir` (el POST real)

**Files:**
- Modify: `backend/services/fiscal_siigo.py`
- Modify: `tests/test_fiscal_siigo.py`

**Interfaces:**
- Produces: `EmisorSiigo.emitir(*, payload: dict, doc_kind: str) -> dict` → `{siigo_document_id, siigo_document_number, crudo}`

- [ ] **Step 1: Test que falla**

Agrega a `tests/test_fiscal_siigo.py`:
```python
def test_emitir_nota_credito_devuelve_ids(monkeypatch):
    llamadas = []

    def fake_post(path, body):
        llamadas.append((path, body))
        return {"id": "nc-99", "name": "NC-1-6985", "number": 6985}

    monkeypatch.setattr(FS.siigo, "siigo_post", fake_post)
    e = FS.EmisorSiigo()
    r = e.emitir(payload={"document": {"id": 27141}}, doc_kind="nota_credito")
    assert r["siigo_document_id"] == "nc-99"
    assert r["siigo_document_number"] == "NC-1-6985"
    assert llamadas[0][0] == "/credit-notes"


def test_emitir_factura_usa_endpoint_invoices(monkeypatch):
    llamadas = []
    monkeypatch.setattr(FS.siigo, "siigo_post",
                        lambda p, b: llamadas.append((p, b)) or {"id": "fv-1"})
    e = FS.EmisorSiigo()
    e.emitir(payload={}, doc_kind="factura")
    assert llamadas[0][0] == "/invoices"


def test_emitir_doc_kind_invalido():
    import pytest
    e = FS.EmisorSiigo()
    with pytest.raises(ValueError, match="doc_kind_invalido"):
        e.emitir(payload={}, doc_kind="recibo")
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_fiscal_siigo.py -v`
Expected: FAIL (`emitir` no existe)

- [ ] **Step 3: Implementar**

Agrega dentro de `class EmisorSiigo` en `backend/services/fiscal_siigo.py`:
```python
    _ENDPOINTS = {"nota_credito": "/credit-notes", "factura": "/invoices"}

    def emitir(self, *, payload: dict, doc_kind: str) -> dict:
        """Crea el documento en Siigo. SOLO se llama tras confirmación humana."""
        endpoint = self._ENDPOINTS.get(doc_kind)
        if endpoint is None:
            raise ValueError("doc_kind_invalido")
        data = siigo.siigo_post(endpoint, payload)
        return {
            "siigo_document_id": data.get("id"),
            "siigo_document_number": data.get("name") or str(data.get("number") or ""),
            "crudo": data,
        }
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest tests/test_fiscal_siigo.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/fiscal_siigo.py tests/test_fiscal_siigo.py
git commit -m "feat(fiscal): EmisorSiigo.emitir (POST a credit-notes / invoices)"
```

---

## Task 8: Orquestación — preview de la nota crédito

**Files:**
- Create: `backend/services/postventa_fiscal.py`
- Create: `tests/test_postventa_fiscal.py`

**Interfaces:**
- Consumes: `postventa.obtener_caso`, `postventa._sb`, `postventa._brand_id`, `EmisorSiigo`
- Produces: `preview_nota_credito(case_id: str) -> dict`

- [ ] **Step 1: Test que falla**

Crea `tests/test_postventa_fiscal.py`:
```python
import pytest
from backend.services import postventa_fiscal as PF


CASO = {"id": "c1", "case_number": "PV-2026-0001", "type": "cambio_talla",
        "shopify_order_name": "#60112", "status": "aprobado"}

FACTURA = {"id": "f2", "name": "FV-1-63043",
           "customer": {"identification": "30384838", "branch_office": 0},
           "seller": 658, "payments": [{"id": 8276, "value": 119000}]}

ITEMS = [{"original_sku": "REF-1", "original_variant": "M",
          "original_price": 100000.0}]


def _mock_todo(monkeypatch, *, fiscal_existente=None):
    monkeypatch.setattr(PF, "_caso", lambda cid: CASO)
    monkeypatch.setattr(PF, "_items_caso", lambda cid: ITEMS)
    monkeypatch.setattr(PF, "_fiscal_existente",
                        lambda cid, dk: fiscal_existente)
    monkeypatch.setattr(PF, "_guardar_fiscal", lambda **k: {"id": "fx", **k})

    class E:
        def buscar_factura_original(self, **k):
            return FACTURA
    monkeypatch.setattr(PF, "obtener_emisor", lambda: E())


def test_preview_arma_payload_y_no_emite(monkeypatch):
    _mock_todo(monkeypatch)
    r = PF.preview_nota_credito("c1")
    assert r["factura_original"]["name"] == "FV-1-63043"
    assert r["payload"]["invoice"] == "f2"
    assert r["totales"]["total"] == 119000.0
    assert r["emitido"] is False


def test_preview_bloquea_si_ya_se_emitio(monkeypatch):
    _mock_todo(monkeypatch, fiscal_existente={"status": "emitido"})
    with pytest.raises(ValueError, match="nota_credito_ya_emitida"):
        PF.preview_nota_credito("c1")


def test_preview_sin_factura_original(monkeypatch):
    _mock_todo(monkeypatch)

    class E:
        def buscar_factura_original(self, **k):
            return None
    monkeypatch.setattr(PF, "obtener_emisor", lambda: E())
    with pytest.raises(ValueError, match="factura_original_no_encontrada"):
        PF.preview_nota_credito("c1")
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_postventa_fiscal.py -v`
Expected: FAIL `ModuleNotFoundError: ... postventa_fiscal`

- [ ] **Step 3: Implementar**

Crea `backend/services/postventa_fiscal.py`:
```python
"""
backend.services.postventa_fiscal — Orquestación del motor fiscal.

preview (arma y guarda, NO emite) → confirmar → emitir → persistir.
Idempotente: nunca dos notas crédito para el mismo caso.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from backend.services import postventa as pv
from backend.services import fiscal_logic as F
from backend.services import fiscal_siigo

log = logging.getLogger("postventa_fiscal")


def obtener_emisor():
    """Emisor fiscal de la marca. Hoy Siigo; el protocolo permite otros."""
    return fiscal_siigo.EmisorSiigo()


def _hoy() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _caso(case_id: str) -> Optional[dict]:
    return pv.obtener_caso(case_id)


def _items_caso(case_id: str) -> list[dict]:
    sb = pv._sb()
    if sb is None:
        return []
    r = sb.table("postventa_items").select("*").eq("case_id", case_id).execute()
    return r.data or []


def _fiscal_existente(case_id: str, doc_kind: str) -> Optional[dict]:
    """Fila de postventa_fiscal ya emitida para ese caso y tipo de doc."""
    sb = pv._sb()
    if sb is None:
        return None
    r = (sb.table("postventa_fiscal").select("*")
           .eq("case_id", case_id).eq("doc_kind", doc_kind)
           .eq("status", "emitido").limit(1).execute())
    filas = r.data or []
    return filas[0] if filas else None


def _guardar_fiscal(**campos) -> dict:
    sb = pv._sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    campos["brand_id"] = pv._brand_id()
    r = sb.table("postventa_fiscal").insert(campos).execute()
    return (r.data or [campos])[0]


def _items_para_fiscal(items: list[dict]) -> list[dict]:
    """postventa_items → forma que espera fiscal_logic."""
    return [{
        "codigo": it.get("original_sku"),
        "descripcion": f"{it.get('original_sku') or ''} {it.get('original_variant') or ''}".strip(),
        "cantidad": 1,
        "precio_sin_iva": float(it.get("original_price") or 0),
    } for it in items]


def preview_nota_credito(case_id: str) -> dict:
    """Arma la nota crédito y la guarda como 'pendiente'. NO emite nada."""
    if _fiscal_existente(case_id, "nota_credito"):
        raise ValueError("nota_credito_ya_emitida")

    caso = _caso(case_id)
    if caso is None:
        raise ValueError("caso_no_encontrado")

    items = _items_caso(case_id)
    if not items:
        raise ValueError("caso_sin_items")

    emisor = obtener_emisor()
    factura = emisor.buscar_factura_original(
        numero_pedido=caso.get("shopify_order_name") or "")
    if factura is None:
        raise ValueError("factura_original_no_encontrada")

    items_fiscal = _items_para_fiscal(items)
    modo = fiscal_siigo.modo_actual()
    payload = F.construir_payload_nota_credito(
        factura=factura, items=items_fiscal, modo=modo, fecha=_hoy())
    totales = F.total_items(
        [{"p": i["precio_sin_iva"], "cantidad": i["cantidad"]} for i in items_fiscal],
        campo_precio="p")

    _guardar_fiscal(case_id=case_id, doc_kind="nota_credito",
                    siigo_invoice_ref=factura.get("id"),
                    amount=totales["total"], status="pendiente",
                    payload_snapshot=payload)

    return {"factura_original": factura, "payload": payload,
            "totales": totales, "modo": modo, "emitido": False}
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest tests/test_postventa_fiscal.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa_fiscal.py tests/test_postventa_fiscal.py
git commit -m "feat(fiscal): preview de nota credito (arma y guarda, no emite)"
```

---

## Task 9: Orquestación — emitir la nota crédito (confirmado)

**Files:**
- Modify: `backend/services/postventa_fiscal.py`
- Modify: `tests/test_postventa_fiscal.py`

**Interfaces:**
- Produces: `emitir_nota_credito(case_id: str, *, actor: str = "sistema") -> dict`

- [ ] **Step 1: Test que falla**

Agrega a `tests/test_postventa_fiscal.py`:
```python
def test_emitir_persiste_y_avanza_estado(monkeypatch):
    _mock_todo(monkeypatch)
    guardado = {}
    monkeypatch.setattr(PF, "_pendiente", lambda cid, dk: {
        "id": "fx", "payload_snapshot": {"document": {"id": 27141}},
        "siigo_invoice_ref": "f2", "amount": 119000.0})
    monkeypatch.setattr(PF, "_marcar_emitido",
                        lambda **k: guardado.update(k) or k)
    estados = []
    monkeypatch.setattr(PF.pv, "cambiar_estado",
                        lambda cid, e, **k: estados.append(e))

    class E:
        def emitir(self, *, payload, doc_kind):
            return {"siigo_document_id": "nc-99",
                    "siigo_document_number": "NC-1-6985"}
    monkeypatch.setattr(PF, "obtener_emisor", lambda: E())

    r = PF.emitir_nota_credito("c1", actor="u1")
    assert r["siigo_document_number"] == "NC-1-6985"
    assert guardado["siigo_document_id"] == "nc-99"
    assert estados == ["nota_credito_emitida"]


def test_emitir_sin_preview_falla(monkeypatch):
    _mock_todo(monkeypatch)
    monkeypatch.setattr(PF, "_pendiente", lambda cid, dk: None)
    with pytest.raises(ValueError, match="sin_preview"):
        PF.emitir_nota_credito("c1")
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_postventa_fiscal.py -v`
Expected: FAIL (`emitir_nota_credito` no existe)

- [ ] **Step 3: Implementar**

Agrega a `backend/services/postventa_fiscal.py`:
```python
def _pendiente(case_id: str, doc_kind: str) -> Optional[dict]:
    """El preview guardado, listo para emitir."""
    sb = pv._sb()
    if sb is None:
        return None
    r = (sb.table("postventa_fiscal").select("*")
           .eq("case_id", case_id).eq("doc_kind", doc_kind)
           .eq("status", "pendiente")
           .order("created_at", desc=True).limit(1).execute())
    filas = r.data or []
    return filas[0] if filas else None


def _marcar_emitido(*, fiscal_id: str, siigo_document_id: str,
                    siigo_document_number: str) -> dict:
    sb = pv._sb()
    if sb is None:
        raise RuntimeError("supabase_no_configurado")
    campos = {"status": "emitido", "siigo_document_id": siigo_document_id,
              "siigo_document_number": siigo_document_number}
    sb.table("postventa_fiscal").update(campos).eq("id", fiscal_id).execute()
    return campos


def _marcar_error(*, fiscal_id: str, detalle: str) -> None:
    sb = pv._sb()
    if sb is None:
        return
    sb.table("postventa_fiscal").update(
        {"status": "error", "error_detail": detalle[:500]}
    ).eq("id", fiscal_id).execute()


def emitir_nota_credito(case_id: str, *, actor: str = "sistema") -> dict:
    """Emite en Siigo la NC previamente previsualizada. Irreversible en modo
    producción — por eso exige un preview guardado y confirmación explícita."""
    if _fiscal_existente(case_id, "nota_credito"):
        raise ValueError("nota_credito_ya_emitida")

    fila = _pendiente(case_id, "nota_credito")
    if fila is None:
        raise ValueError("sin_preview")

    emisor = obtener_emisor()
    try:
        res = emisor.emitir(payload=fila["payload_snapshot"],
                            doc_kind="nota_credito")
    except Exception as e:
        _marcar_error(fiscal_id=fila["id"], detalle=str(e))
        pv.registrar_evento(case_id, "fiscal_error",
                            f"Nota crédito rechazada: {str(e)[:200]}",
                            created_by=actor)
        raise

    _marcar_emitido(fiscal_id=fila["id"],
                    siigo_document_id=res["siigo_document_id"],
                    siigo_document_number=res["siigo_document_number"])
    pv.registrar_evento(case_id, "nota_credito_emitida",
                        f"NC {res['siigo_document_number']} emitida "
                        f"(modo {fiscal_siigo.modo_actual()})",
                        created_by=actor)
    pv.cambiar_estado(case_id, "nota_credito_emitida", actor=actor)
    return res
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest tests/test_postventa_fiscal.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/postventa_fiscal.py tests/test_postventa_fiscal.py
git commit -m "feat(fiscal): emitir nota credito tras confirmacion + timeline + estado"
```

---

## Task 10: Endpoints (preview / emitir)

**Files:**
- Modify: `backend/api/postventa.py`
- Modify: `tests/test_postventa_api.py`

**Interfaces:**
- Produces: `POST /api/postventa/casos/{case_id}/fiscal/preview`, `POST /api/postventa/casos/{case_id}/fiscal/emitir`

- [ ] **Step 1: Test que falla**

Agrega a `tests/test_postventa_api.py`:
```python
def test_preview_fiscal_endpoint(monkeypatch):
    monkeypatch.setattr(api_postventa.fiscal_svc, "preview_nota_credito",
                        lambda cid: {"emitido": False, "totales": {"total": 119000.0}})
    client = TestClient(_app(monkeypatch))
    r = client.post("/api/postventa/casos/c1/fiscal/preview")
    assert r.status_code == 200
    assert r.json()["totales"]["total"] == 119000.0


def test_emitir_fiscal_endpoint_error_400(monkeypatch):
    def _raise(cid, actor=""):
        raise ValueError("sin_preview")
    monkeypatch.setattr(api_postventa.fiscal_svc, "emitir_nota_credito", _raise)
    client = TestClient(_app(monkeypatch))
    r = client.post("/api/postventa/casos/c1/fiscal/emitir")
    assert r.status_code == 400
    assert "sin_preview" in r.json()["detail"]
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python3 -m pytest tests/test_postventa_api.py -v`
Expected: FAIL (`fiscal_svc` no existe en el módulo)

- [ ] **Step 3: Implementar**

En `backend/api/postventa.py`, agrega el import:
```python
from backend.services import postventa_fiscal as fiscal_svc
```
Y los endpoints al final:
```python
@router.post("/casos/{case_id}/fiscal/preview")
def fiscal_preview(case_id: str,
                   _: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Arma la nota crédito y la muestra. NO emite nada en Siigo."""
    try:
        return fiscal_svc.preview_nota_credito(case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/casos/{case_id}/fiscal/emitir")
def fiscal_emitir(case_id: str,
                  user: CurrentUser = Depends(require_permission("postventa", "modificar"))):
    """Emite en Siigo la NC previsualizada. Requiere confirmación del equipo."""
    try:
        return fiscal_svc.emitir_nota_credito(case_id, actor=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"siigo: {str(e)[:300]}")
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python3 -m pytest -q`
Expected: toda la suite en verde.

- [ ] **Step 5: Commit**

```bash
git add backend/api/postventa.py tests/test_postventa_api.py
git commit -m "feat(fiscal): endpoints de preview y emision de nota credito"
```

---

## Task 11: Frontend — panel fiscal en el detalle del caso

**Files:**
- Modify: `frontend/lib/postventa.ts`
- Modify: `frontend/app/postventa/[caseId]/page.tsx`

**Interfaces:**
- Produces: `previewFiscal(id)`, `emitirFiscal(id)`; sección "Fiscal" en el detalle.

- [ ] **Step 1: Cliente de API**

Agrega a `frontend/lib/postventa.ts`:
```typescript
export interface PreviewFiscal {
  factura_original: { id: string; name: string };
  totales: { subtotal: number; iva: number; total: number };
  modo: string;
  emitido: boolean;
}

export const previewFiscal = (id: string) =>
  api.post<PreviewFiscal>(`/api/postventa/casos/${id}/fiscal/preview`);

export const emitirFiscal = (id: string) =>
  api.post<{ siigo_document_number: string }>(`/api/postventa/casos/${id}/fiscal/emitir`);
```

- [ ] **Step 2: Sección Fiscal en el detalle**

En `frontend/app/postventa/[caseId]/page.tsx`, dentro del componente y bajo la tarjeta de datos, agrega un bloque que:
1. Muestre un botón **"Previsualizar nota crédito"** (visible cuando `c.status === "aprobado"`).
2. Al recibir el preview, muestre: factura original, subtotal, IVA, total y **un aviso del modo** (`prueba` → "no se envía a la DIAN").
3. Muestre entonces un botón **"Emitir nota crédito"** que llama `emitirFiscal` y refresca el caso.

```typescript
const [preview, setPreview] = useState<PreviewFiscal | null>(null);
const prevMut = useMutation({
  mutationFn: () => previewFiscal(caseId),
  onSuccess: setPreview,
});
const emitMut = useMutation({
  mutationFn: () => emitirFiscal(caseId),
  onSuccess: () => {
    setPreview(null);
    qc.invalidateQueries({ queryKey: ["postventa-caso", caseId] });
  },
});
```

- [ ] **Step 3: Verificar**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errores.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/postventa.ts "frontend/app/postventa/[caseId]/page.tsx"
git commit -m "feat(fiscal): panel de preview y emision de nota credito en el detalle"
```

---

## Criterios de salida (gate a producción)

```
[ ] 20 casos completos en modo prueba (NC Proforma 27141), sin error fiscal
[ ] Cubiertos cambio_talla, cambio_ref (con diferencia de precio) y reembolso/bono
[ ] Montos e IVA cuadran contra la factura original en cada caso
[ ] Idempotencia verificada (imposible emitir 2 NC al mismo caso)
[ ] Cada caso deja payload_snapshot + timeline completo
[ ] Switch documentado y reversible (SIIGO_POSTVENTA_MODO=produccion)
```

## Fuera de alcance de este plan

- Factura del reemplazo (Tasks siguientes, una vez validada la NC).
- Reintento desde el snapshot corregido (fase siguiente).
- Emisores Alegra / World Office (la interfaz queda lista).
- Bonos/gift cards reales y devolución de dinero a la pasarela.
