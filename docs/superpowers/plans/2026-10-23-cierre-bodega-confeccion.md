# Cierre de bodega — Fase 1: eslabón de confección · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cazar la pérdida de prendas en confección en el momento del handoff: capturar por talla cuánto entregó confección, cruzarlo contra lo cortado, y si falta algo disparar una alerta de campanita que diga qué tallas y cuántas faltan.

**Architecture:** Se reutiliza el motor que ya existe en la pata de lavandería (OCR de remisión por visión + cruce + alerta de campanita) y se le añade el eslabón de confección. El conteo de salida de confección entra como `conf_unidades` (jsonb por talla) en una tabla nueva `cuadre_lote_proceso`, siempre en estado **"por confirmar"** (sea leído por foto o tecleado a mano); solo al confirmarlo se hace el cruce en firme y, si hay faltante, se alerta. Nada dispara alerta sobre un dato sin confirmar → cero alertas falsas.

**Tech Stack:** FastAPI (backend/services + backend/api), Supabase/Postgres (migraciones por MCP), Next.js (frontend/app), Claude Haiku 4.5 visión (remision_ocr), sistema de notificaciones existente (notificaciones.py + avisos_produccion.py).

**Spec:** `docs/superpowers/specs/2026-10-23-cierre-bodega-trazabilidad-design.md` (leer junto con este plan; los defaults fijados y el estado actual del código están ahí).

## Global Constraints

- **Toda tabla NUEVA lleva GRANT en la MISMA migración** (regla 30-oct-2026, CLAUDE.md): `grant select, insert, update, delete on public.<tabla> to service_role;` + `grant usage, select on sequence ...` si usa serial. Nada a `anon`/`authenticated` salvo lectura directa del navegador (no aplica aquí).
- **Migraciones idempotentes** (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`), aplicadas en Supabase por MCP (proyecto `vmuopwdswrpimkijosyb`) y versionadas en `supabase/migrations/`.
- **Conteos por talla** = jsonb `{ "T12": 10, "T14": 8, ... }`, tallas en MAYÚSCULA y sin ceros, igual que `unidades_cortadas` (ver `produccion.py` sanitizado ~2535). Total = `sum(int(v or 0) for v in d.values())`.
- **Nada de `.limit(N>1000)` ni `fromisoformat` directo** (guardián). Fechas con `backend.core.fechas.parse_iso_utc`.
- **Gate anti-alertas-falsas:** un conteo solo cruza/alerta en firme cuando `estado='confirmado'`. OCR y entrada manual entran `por_confirmar`.
- **Verificación (cómo se blinda este repo, no TDD):** backend `python3 -m py_compile`; front `npm run lint:hooks` + `npx tsc --noEmit` + `npm run build`; guardián en push; prueba de humo contra la base por MCP; al desplegar, confirmar arranque limpio en logs (1 LÍDER + seguidores, sin tracebacks).

## Review Focus

- **Talla que existe en corte pero no llega en confección** → debe salir como faltante de ESA talla en rojo, no como "cuadra". (Task 2)
- **Conteo OCR mal leído** (una talla errada) → entra `por_confirmar`, editable, y NO dispara alerta hasta confirmar. (Tasks 3, 5)
- **Lote sin `unidades_cortadas`** (corte sin informe cerrado) → el cruce no revienta: devuelve "sin base de corte", no faltante. (Task 2)
- **Confirmar un cuadre que YA cuadra** → no dispara alerta; solo marca confirmado. (Task 4)
- **Foto de confección cuando el lote aún no tiene hoja de ruta / no es de confección** → se ignora o entra como pendiente sin tocar otros pasos (no pisa el conteo de lavandería). (Task 5)

---

### Task 1: Migración — tabla `cuadre_lote_proceso` + versionar columnas huérfanas

**Files:**
- Create: `supabase/migrations/2026YYMMDDHHMMSS_cuadre_lote_proceso.sql`
- Aplicar por MCP `apply_migration` (name `cuadre_lote_proceso`).

**Interfaces:**
- Produces: tabla `cuadre_lote_proceso(id uuid pk, orden_corte_id uuid, referencia_id uuid null, paso text check in ('confeccion','lavanderia','terminacion','bodega'), unidades jsonb default '{}', total int generated/derived-in-app, estado text check in ('por_confirmar','confirmado','justificado') default 'por_confirmar', fuente text check in ('ocr','manual') , remision_foto_url text null, confirmado_por text, confirmado_at timestamptz, justificado_por text, justificado_motivo text, justificado_at timestamptz, creado_por text, creado_at timestamptz default now(), actualizado_at timestamptz default now(), unique(orden_corte_id, paso, referencia_id))`. Para Fase 1 solo se escribe `paso='confeccion'`.

- [ ] **Step 1: Escribir la migración** con `CREATE TABLE IF NOT EXISTS cuadre_lote_proceso (...)`, índices por `(orden_corte_id, paso)` y `(estado)`, y los GRANT a `service_role` (regla 30-oct). Incluir en el MISMO archivo el `ADD COLUMN IF NOT EXISTS` que **versiona las columnas huérfanas** ya aplicadas a mano en `hoja_ruta_lote`: `lav_cantidad_remision`, `lav_cantidad_remision_origen`, `term_cantidad_recibida`, `term_cantidad_terminada` (comentario: "ya existían en prod, se versionan").
- [ ] **Step 2: Aplicar por MCP** `apply_migration(project_id="vmuopwdswrpimkijosyb", name="cuadre_lote_proceso", query=...)`.
- [ ] **Step 3: Verificar** por MCP `execute_sql`: `SELECT column_name FROM information_schema.columns WHERE table_name='cuadre_lote_proceso'` devuelve las columnas, y un `insert`/`select`/`delete` de prueba como service_role no da `permission denied` (42501).
- [ ] **Step 4: Commit** `supabase/migrations/...` con mensaje `feat(cuadre): tabla cuadre_lote_proceso + versiona columnas huérfanas de hoja_ruta_lote`.

### Task 2: Backend — cruce de confección por talla

**Files:**
- Modify: `backend/services/produccion.py` (añadir helper cerca del cruce de lavandería o en una sección nueva "CUADRE POR PROCESO").

**Interfaces:**
- Consumes: `obtener_orden_corte` / lectura de `ordenes_corte.unidades_cortadas` (jsonb por talla); fila de `cuadre_lote_proceso` del paso.
- Produces:
  - `_unidades_cortadas_por_talla(oc_id) -> dict[str,int]` (reusa el sanitizado existente).
  - `cruzar_proceso(oc_id, paso) -> dict` → `{ "base": {talla:int}, "recibido": {talla:int}, "faltan": {talla:int>0}, "sobran": {talla:int>0}, "estado": "cuadra|faltan|sobran|mixto|sin_base|sin_dato", "total_base": int, "total_recibido": int }`. Para Fase 1 `paso='confeccion'`, base = unidades_cortadas. Sin `unidades_cortadas` → `estado="sin_base"`. Sin fila de cuadre → `estado="sin_dato"`.

- [ ] **Step 1: Implementar** `_unidades_cortadas_por_talla` y `cruzar_proceso` en `produccion.py`. Diferencia por talla: `faltan[t] = max(base[t]-recibido.get(t,0),0)`; una talla en base ausente del recibido cuenta como faltante completo de esa talla.
- [ ] **Step 2: Prueba de humo** (script en scratchpad o `python -c`) contra un lote real con forro/curva conocida (p. ej. corte `2609-0015`, ref `16633-1`): llamar `cruzar_proceso(oc_id,'confeccion')` sin fila → `sin_dato`; tras insertar un `conf_unidades` con una talla de menos → `faltan` con esa talla.
- [ ] **Step 3: `py_compile`** del servicio. 
- [ ] **Step 4: Commit** `feat(cuadre): cruce de confección por talla (cruzar_proceso)`.

### Task 3: Backend — capturar/confirmar el conteo de confección (manual) + API

**Files:**
- Modify: `backend/services/produccion.py` (fns de escritura de `cuadre_lote_proceso`).
- Modify: `backend/api/produccion.py` (endpoints + Pydantic).

**Interfaces:**
- Consumes: Task 2 (`cruzar_proceso`).
- Produces:
  - `guardar_conteo_proceso(oc_id, paso, unidades: dict, *, fuente, foto_url=None, creado_por) -> dict` → upsert en `cuadre_lote_proceso` estado `por_confirmar`.
  - `confirmar_conteo_proceso(oc_id, paso, *, usuario) -> dict` → estado `confirmado`, corre `cruzar_proceso`, y si hay faltantes dispara la alerta (Task 4). Devuelve el cruce.
  - Endpoints: `POST /api/produccion/cuadre/{oc_id}/{paso}` (body `{unidades: {talla:int}, foto_url?}`) y `POST /api/produccion/cuadre/{oc_id}/{paso}/confirmar`. Permiso: `produccion` modificar.

- [ ] **Step 1: Implementar** las dos fns de servicio y los dos endpoints con sus modelos (`ConteoProcesoIn`).
- [ ] **Step 2: Prueba de humo** por HTTP local o llamando el servicio: guardar un conteo manual con un faltante, confirmar, y verificar que `cruzar_proceso` queda `faltan` y la fila `confirmado`.
- [ ] **Step 3: `py_compile`.**
- [ ] **Step 4: Commit** `feat(cuadre): capturar y confirmar conteo de confección + API`.

### Task 4: Backend — alerta de faltante en confección

**Files:**
- Modify: `backend/services/avisos_produccion.py` (nueva política).
- Usa: `backend/services/notificaciones.py` (`crear` / `crear_para_modulo`).

**Interfaces:**
- Consumes: resultado de `cruzar_proceso` (faltantes por talla), datos del lote (creador, consecutivo).
- Produces: `avisar_faltante_confeccion(oc: dict, cruce: dict) -> None` — no lanza. `tipo="faltante_confeccion"`. Destinatarios: módulo `produccion_cortador` + creador del lote; `meta` con tallas faltantes; `enlace` al detalle del lote. Escalamiento a Sebastián reutiliza el patrón de email existente si está activo (apagado por defecto).

- [ ] **Step 1: Implementar** `avisar_faltante_confeccion` siguiendo el patrón de `avisar_corte_cerrado` (créditos a `created_by`) + `crear_para_modulo`. Mensaje en claro: "Faltan N en confección del lote {consecutivo}: T12 −2, T16 −1…".
- [ ] **Step 2: Enganchar** la llamada en `confirmar_conteo_proceso` (Task 3) solo cuando `estado=='faltan'|'mixto'` y hay faltantes>0; nunca si cuadra.
- [ ] **Step 3: Prueba de humo:** confirmar un conteo con faltante y verificar que aparece una fila en `notificaciones` (por MCP) para el creador y para un cortador.
- [ ] **Step 4: `py_compile`** + **Commit** `feat(cuadre): alerta de campanita por faltante en confección`.

### Task 5: Backend — leer la remisión de confección por foto (OCR por talla, prefill por_confirmar)

**Files:**
- Modify: `backend/services/remision_ocr.py` (lector por talla).
- Modify: `backend/api/meta.py` (clasificar al remitente y rutear a confección).

**Interfaces:**
- Consumes: hoja de ruta del lote (`confeccionista_id`, `etapa`), bytes de la foto.
- Produces:
  - `remision_ocr.leer_remision_proceso(bytes, mime) -> {"por_talla": {talla:int}|None, "total": int|None, "paso_sugerido": str|None, "consecutivo": str|None}` (prompt de visión para remisión de taller con tabla de tallas; si no hay tallas devuelve `total`).
  - En `meta.py`: cuando el remitente es un proveedor, resolver su rol en el lote vigente; si es el **confeccionista** del lote y el lote está `en_confeccion`/`aceptado`, llamar `guardar_conteo_proceso(oc_id,'confeccion', unidades, fuente='ocr', foto_url=...)` (estado `por_confirmar`). Si es ambiguo o es la remisión de lavandería → comportamiento actual (no pisar).

- [ ] **Step 1: Implementar** `leer_remision_proceso` (reusa helpers de imagen/pdf de `extraer_remision`).
- [ ] **Step 2: Clasificación en `meta.py`** por remitente+etapa; defensivo: ante duda, dejar el flujo de lavandería actual intacto.
- [ ] **Step 3: Prueba de humo** con una foto real de remisión de confección (si se consigue) o un fixture: verifica que crea la fila `por_confirmar` sin disparar alerta.
- [ ] **Step 4: `py_compile`** + **Commit** `feat(cuadre): OCR por talla de la remisión de confección + ruteo por remitente`.

### Task 6: Frontend — panel "Cuadre de confección" en el detalle del lote

**Files:**
- Modify: `frontend/app/produccion/corte/[id]/page.tsx` (o `frontend/app/produccion/rutas/` si es el hogar natural del seguimiento) — añadir un panel.
- Posible helper: `frontend/lib/` para el fetch del cuadre.

**Interfaces:**
- Consumes: `GET` del cuadre (añadir a `obtener_orden_corte` el bloque `cuadre` del paso confección, o un endpoint `GET /api/produccion/cuadre/{oc_id}`).
- Produces: panel que muestra, por talla, **cortado vs recibido** con el faltante en rojo; botón **Confirmar conteo** (si `por_confirmar`); campo para **teclear el conteo** por talla (respaldo manual); botón **Justificar** (Task 7). Estado visible: por confirmar / cuadra / faltan / justificado.

- [ ] **Step 1: Exponer** el cuadre en el backend (añadir al detalle o endpoint GET).
- [ ] **Step 2: Implementar** el panel en el detalle del lote, reutilizando el estilo de tarjetas existente (ver panel "Telas adicionales" ya añadido). Sin hooks condicionales.
- [ ] **Step 3: Verificar** `npm run lint:hooks` + `npx tsc --noEmit` + `npm run build`.
- [ ] **Step 4: Commit** `feat(cuadre): panel de cuadre de confección por talla en el detalle del lote`.

### Task 7: Justificar un faltante (cerrar el eslabón)

**Files:**
- Modify: `backend/services/produccion.py` + `backend/api/produccion.py` (endpoint justificar).
- Modify: el panel del Task 6 (acción justificar con motivo).

**Interfaces:**
- Produces: `justificar_proceso(oc_id, paso, *, motivo, usuario) -> dict` → estado `justificado` (permiso admin/autorización de producción). Endpoint `POST /api/produccion/cuadre/{oc_id}/{paso}/justificar`.

- [ ] **Step 1: Implementar** servicio + endpoint con gate de permiso (admin / autorizado).
- [ ] **Step 2: UI** del botón Justificar con motivo (dañadas/2das/re-conteo/otro).
- [ ] **Step 3: Verificar** compile + lint:hooks + tsc + build.
- [ ] **Step 4: Commit** `feat(cuadre): justificar faltante de confección para cerrar el eslabón`.

---

## Notas de ejecución

- **Orden:** Task 1 → 2 → 3 → 4 habilitan ya el cuadre manual + alerta (shippable). Task 5 añade el prefill por foto. Tasks 6–7 son la cara visible. Se puede desplegar tras Task 4 (manual + alerta) y de nuevo tras 6.
- **Despliegue:** push a `main` despliega backend y frontend en Railway (`vivacious-perception`). Confirmar arranque limpio en logs tras cada push.
- **Fases siguientes (fuera de este plan):** vista completa "Cierre de bodega" con toda la cadena corte→confección→lavandería→terminación→bodega; terminación por talla; cierre limpio del lote contra el conteo final (= cierre de terminación).
