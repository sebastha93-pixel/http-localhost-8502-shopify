# Cierre de bodega — Fase 2: cadena completa + conteo final · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Que cada lote se cierre contando por talla lo que llega a bodega, comparado contra lo cortado, con la cadena completa a la vista (corte → confección → lavandería → terminación → bodega) y el faltante marcado en el paso donde se perdió.

**Architecture:** Se extiende el cuadre de la Fase 1 (`cuadre_lote_proceso`, `cruzar_proceso`, gate "por confirmar") al paso `bodega` y pasa a ser **por lote** (corte + referencia), no por orden. Una función pura arma la cadena de un lote con lo que ya existe (cortado por talla, confección por talla, totales de lavandería y terminación, bodega por talla). Nueva pantalla "Cierre de bodega" en Producción para el conteo final; "Marcar ingreso a bodega" ya no se puede sin ese conteo.

**Tech Stack:** FastAPI + supabase-py, Next.js (React Query), Supabase.

**Spec:** `docs/superpowers/specs/2026-10-23-cierre-bodega-trazabilidad-design.md` (sección "Fase 2").

## Global Constraints

- Conteo final = pantalla en el OS (decisión de Sebastián 2026-10-29). Lo digita quien recibe en bodega (insumos) desde la remisión de terminación.
- El lote NO pasa a `despachado` ("en bodega") sin conteo de bodega confirmado o justificado — también bloqueado en el backend (fallar cerrado).
- Gate de la Fase 1 se mantiene: conteo entra `por_confirmar`; alerta solo al confirmar y solo si falta.
- Base del cruce = lo CORTADO de ESE lote: `orden_corte_referencias.unidades_cortadas` → si el corte tiene una sola referencia, `ordenes_corte.unidades_cortadas` → último recurso `curva_trazo` marcado "programado".
- Filas de cuadre siempre con `referencia_id` del lote (nunca NULL). Hoy hay 0 filas: no hay migración de datos.
- Lavandería y terminación siguen en totales (sin trabajo extra para los talleres); por talla en confección (inicio) y bodega (final).
- Verificación: py_compile, prueba de las funciones puras, guardián, `lint:hooks` + `tsc` + `next build`, despliegue + health + endpoints registrados, y **volver a barrer** remisiones y lotes cuando termine el despliegue.

## Review Focus

- Lote sin corte cerrado (base "programado" o vacía) → no se declara "cerrado limpio"; se avisa que la base es lo programado.
- Bodega cuenta una talla que no estaba en el corte → sale como sobrante de esa talla, sin romper.
- Confirmar bodega con faltante → el lote pasa a "en bodega" pero queda ABIERTO como "faltante" hasta justificarse.
- "Marcar ingreso a bodega" directo sin conteo → 400 con mensaje claro.
- Corte combinado → cada lote compara contra SU referencia, no la suma del corte.

---

### Task 1: Base por lote y referencia normalizada (backend)
- Modify `backend/services/produccion.py` (sección CUADRE):
  - `_base_desde(oc_row: dict, hijos: list[dict], referencia_id: str|None) -> tuple[dict, str]` (pura; fuente ∈ cortado/programado/"").
  - `_oc_e_hijos(oc_id) -> tuple[dict, list[dict]]` (lectura liviana).
  - `_ref_del_lote(oc_id, referencia_id) -> str|None` (si viene None y el corte tiene una sola referencia, esa).
  - `cruzar_proceso` usa `_base_desde`; agrega `base_fuente`. `guardar/confirmar/justificar` normalizan la referencia.
  - `_unidades_de_referencia(rr, oc=None)`: en corte de una sola referencia cae a lo cortado del padre antes que a la curva (stickers con lo cortado, no lo programado).
- Verificar: py_compile + prueba pura de `_base_desde`.

### Task 2: Cadena del lote y lista de cierre (backend)
- `_cadena_desde(ruta, oc_row, hijos, filas_cuadre) -> dict` (pura): pasos con total, por talla si hay, estado, `faltan_vs_anterior`, `se_perdio_aqui`; `cierre` ∈ sin_conteo_final / por_confirmar / cerrado_limpio / faltante / justificado / revisar.
- `cadena_lote(oc_id, referencia_id)`; `listar_cierre_bodega(estado=None)` en lote (pocas consultas, sin N+1).
- Verificar: prueba pura de `_cadena_desde` (cuadra, faltante en confección, faltante en terminación por totales, sin conteo final, justificado).

### Task 3: Flujo de bodega, alertas y API (backend)
- `confirmar_conteo_proceso(paso='bodega')` mueve el lote a `despachado`.
- `avisos_produccion.avisar_faltante_bodega(oc, cruce, referencia)` → módulo `produccion_remisiones` + creador.
- `POST /rutas/{id}/etapa` con `despachado` exige bodega confirmado/justificado.
- API cuadre: `referencia_id` en GET/confirmar (query) y cuerpos; permisos incluyen `produccion_remisiones`. Nuevos `GET /cierre-bodega?estado=` y `GET /cierre-bodega/lote/{oc_id}?referencia_id=`.
- OCR de confección guarda con la referencia del lote.

### Task 4: Corte (frontend)
- `CuadreConfeccion` por lote (una por referencia del corte, con `referencia_id`).
- "Marcar ingreso a bodega" → enlace a `/produccion/cierre-bodega?lote=…&ref=…`.

### Task 5: Pantalla Cierre de bodega (frontend) + menú
- `frontend/app/produccion/cierre-bodega/page.tsx`: pestañas Abiertos/Cerrados; lote → cadena con el faltante en rojo donde se perdió + grilla de conteo final (Cortado | Llegó) → Guardar → Confirmar → Justificar.
- `frontend/lib/nav.ts`: "Cierre de bodega" después de Lavandería.
- Verificar: lint:hooks + tsc + next build.

### Task 6: Desplegar y verificar
- Commit, push, esperar despliegue, health, endpoints 401 (registrados), barrido de remisiones y de lotes.
