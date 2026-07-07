# MALE POSTVENTA IA — Spec de diseño (MVP)

- **Fecha:** 2026-07-06
- **Módulo:** `postventa` dentro de MALE DENIM OS (repo `male_denim_logistics`)
- **Alcance de este spec:** MVP = Sub-proyecto #1 (Motor + Panel interno) + Sub-proyecto #2 (Motor fiscal Siigo)
- **Estado:** Aprobado en brainstorming, pendiente de plan de implementación (`writing-plans`)

---

## 1. Contexto y problema

Hoy los cambios/devoluciones de MALE Denim se manejan **100% por WhatsApp**, sin registro
estructurado en ningún sistema. Toda la operación es manual: desde reservar el producto de
reemplazo hasta despacharlo. El **dolor #1** declarado por el fundador es la **generación de la
nota crédito y la nueva factura** (documentos electrónicos DIAN vía Siigo).

**Objetivo del MVP:** estructurar el caso de postventa y **orquestar la parte fiscal**
(nota crédito + nueva factura contra la factura original de Shopify que ya existe en Siigo),
reutilizando la infraestructura que el repo ya tiene.

### Infraestructura existente que se reutiliza (NO se rehace)

| Necesidad | Componente existente |
|---|---|
| Historial/pedidos Shopify | `backend/services/clientes.py` + refs Shopify en varios módulos |
| Auth + lectura Siigo | `backend/services/siigo.py` (solo lectura hoy; se le agrega POST) |
| Notificaciones WhatsApp | `backend/services/whatsapp_cloud.py` |
| CRM / conversaciones | `backend/services/kommo.py` (para Fase 5 IA) |
| Logística / transportadora | `backend/services/melonn.py` (para Fase 3) |
| Agente IA | `backend/services/audit_ia.py` (para Fase 5) |
| Alertas internas | `backend/services/slack_notifier.py` |
| Usuarios / roles / seguridad | `backend/services/usuarios.py`, `backend/core/security.py` |
| Patrón de módulos | Producción, Revenue, Conciliación (API + service + página) |

---

## 2. Descomposición del proyecto completo

El brief original describe 6-7 subsistemas. Se descompone así (cada uno = su propio ciclo
spec → plan → build):

| # | Sub-proyecto | Estado |
|---|---|---|
| **1** | Postventa Core (motor + panel interno) | **MVP (este spec)** |
| **2** | Motor fiscal Siigo (nota crédito + factura) | **MVP (este spec)** |
| 3 | Reserva + despacho (logística inversa/directa) | Fase siguiente |
| 4 | Portal de autoservicio para la clienta | Fase siguiente |
| 5 | IA de postventa (clasificación, riesgo, recomendación) | Fase siguiente |
| 6 | Inteligencia avanzada (reportes profundos, predicción, alertas) | Fase siguiente |

**Principio arquitectónico clave:** un solo **motor de casos** con **dos puertas de entrada**
(asesora interna hoy, portal en Fase 4). El servicio `crear_caso(...)` no sabe quién lo llamó,
así el portal se enchufa después sin reescribir el motor.

---

## 3. Arquitectura y ubicación en el repo

```
backend/
  api/postventa.py            ← router FastAPI del módulo
  services/
    postventa.py              ← lógica: casos, estados, timeline, motivos
    postventa_siigo.py        ← motor fiscal: nota crédito + nueva factura
    siigo.py                  ← [EXISTENTE] + helper siigo_post(path, body)
frontend/
  app/postventa/
    page.tsx                  ← bandeja / lista de casos
    [caseId]/page.tsx         ← detalle del caso + acciones
  components/postventa/…      ← UI reutilizable
Supabase:
  postventa_cases, postventa_items, postventa_evidence,
  postventa_timeline, postventa_fiscal
```

### Flujo de alto nivel (MVP)

```
Asesora abre caso  →  vincula pedido Shopify (email / # pedido)
   →  registra items + motivo + evidencia
   →  define solución (cambio_talla / cambio_ref / reembolso / bono)
   →  [motor fiscal] PREVISUALIZA nota crédito contra factura original
   →  confirmación humana  →  emite NC en Siigo
   →  [motor fiscal] emite nueva factura del reemplazo (si aplica)
   →  timeline automático  →  WhatsApp a la clienta
   →  caso avanza hasta 'cerrado'
```

Autenticación y roles: reutiliza `usuarios.py` + `core/security.py`. Los roles del brief
(líder postventa, logística, finanzas, dirección, solo lectura…) se mapean a permisos sobre
el módulo `postventa`.

---

## 4. Modelo de datos (Supabase)

### 4.1 `postventa_cases`
```
id                 uuid PK
case_number        text   -- consecutivo legible: PV-2026-0001
shopify_order_id   text
shopify_order_name text   -- "#1052"
customer_email     text
customer_phone     text
customer_name      text
status             text   -- enum §5.1
type               text   -- cambio_talla | cambio_ref | reembolso | bono | garantia
reason             text   -- catálogo §5.2
subreason          text   -- opcional
priority           text   -- baja | media | alta
source             text   -- 'interno' | 'portal'
assigned_to        uuid   -- FK usuarios
notes_internas     text
created_at         timestamptz
updated_at         timestamptz
closed_at          timestamptz
```

### 4.2 `postventa_items`
```
id                uuid PK
case_id           uuid FK -> postventa_cases
original_sku      text
original_variant  text            -- talla/color original
original_price    numeric(12,2)   -- COP, sin IVA
requested_sku     text            -- null si reembolso/bono
requested_variant text
requested_price   numeric(12,2)
price_difference  numeric(12,2)   -- + cobra, - devuelve
item_status       text            -- pendiente | aprobado | rechazado
```

### 4.3 `postventa_evidence`
```
id, case_id FK, file_url, file_type, uploaded_by (uuid), created_at
-- archivos en Supabase Storage; se guarda la URL (igual que evidencias de producción)
```

### 4.4 `postventa_timeline`
```
id, case_id FK, event_type, description, created_by (uuid | 'sistema'), created_at
-- cada cambio de estado / NC emitida / WhatsApp enviado escribe una fila
```

### 4.5 `postventa_fiscal` (corazón del #2)
```
id                    uuid PK
case_id               uuid FK
doc_kind              text   -- 'nota_credito' | 'factura'
siigo_invoice_ref     text   -- factura ORIGINAL en Siigo (contra la que va la NC)
siigo_document_id     text   -- id del doc creado en Siigo
siigo_document_number text   -- número legible (NC-XXXX / FV-XXXX)
amount                numeric(12,2)
status                text   -- 'pendiente' | 'emitido' | 'error'
error_detail          text   -- motivo si Siigo rechazó
payload_snapshot      jsonb  -- exactamente lo enviado (auditoría DIAN + reintento)
created_at            timestamptz
```

**Decisiones validadas:**
- `payload_snapshot` en jsonb → auditoría DIAN y reintento sin rearmar.
- `case_number` consecutivo propio (PV-2026-0001), independiente de Shopify/Siigo.
- Montos COP `numeric(12,2)` **sin IVA** en items; el IVA lo calcula el motor fiscal
  (coherente con el gotcha ya documentado: `price` en Siigo es sin IVA).

---

## 5. Estados y motivos

### 5.1 Máquina de estados (MVP)

**Estados activos:**
```
1. creado
2. pendiente_validacion
3. aprobado
4. rechazado                (fin)
5. nota_credito_emitida
6. factura_emitida
7. cerrado                  (fin)
8. escalado
```

**Transiciones válidas:**
```
creado -> pendiente_validacion -> aprobado | rechazado | escalado
aprobado -> nota_credito_emitida -> factura_emitida -> cerrado
aprobado -> nota_credito_emitida -> cerrado        (reembolso/bono: sin nueva factura)
escalado -> aprobado | rechazado
cualquiera -> cerrado (con motivo, para cierres manuales)
```

**Estados reservados (inactivos hasta Fase 3 logística):**
`esperando_envio_cliente`, `en_transito_bodega`, `recibido_bodega`,
`en_inspeccion`, `cambio_enviado`.

`status` es texto con enum validado en el servicio → agregar estados futuros es lógica,
no migración.

### 5.2 Catálogo de motivos (constante en `postventa.py`)
```
talla_pequena, talla_grande, no_le_gusto_como_quedo, color_diferente,
producto_defectuoso, producto_equivocado, pedido_incompleto,
demora_entrega, arrepentimiento, calidad_percibida,
error_asesoria, error_logistico, cambio_por_otro, garantia, otro
```
Se migran a tabla editable (`postventa_reasons`) en Fase 6 / pantalla de Configuración.

---

## 6. Motor fiscal Siigo (#2)

Emite documentos electrónicos **reales ante la DIAN** → acción difícil de revertir.
El diseño la trata con ese respeto.

**Servicio:** `services/postventa_siigo.py`. A `siigo.py` se le agrega
`siigo_post(path, body)` con el mismo backoff de rate-limit (429) que ya existe.

### 6.1 Flujo en 4 pasos

1. **Localizar la factura original en Siigo.** Cada venta Shopify ya se factura auto en Siigo;
   se busca esa factura para obtener su `id`.
   ⚠️ **Riesgo #1 (spike técnico inicial):** confirmar el campo de enlace (número de pedido
   Shopify en observaciones de la factura, o NIT/cédula + fecha).
2. **Armar payload y PREVISUALIZAR.** Se arma el borrador de NC (y factura si hay reemplazo),
   se muestra en pantalla (cliente, items, IVA, total) y se guarda en `payload_snapshot`.
   **Nada se envía a la DIAN todavía.**
3. **Confirmación humana explícita → emitir.** El equipo revisa y confirma. Recién ahí
   `siigo_post` crea el documento; se guardan `siigo_document_id`, `siigo_document_number`,
   `status='emitido'`; timeline se actualiza solo.
   - Cambio con reemplazo → repetir para la factura.
   - Reembolso/bono → solo NC; caso pasa a `cerrado` (bono/reembolso operativo es Fase 5).
4. **Manejo de fallo.** Si Siigo rechaza → `status='error'` + `error_detail`; el caso **no
   avanza**; el equipo reintenta desde `payload_snapshot` corregido.
   **Nunca se reintenta automático un documento fiscal.**

### 6.2 Configuración one-time (env/Railway — primer spike)
```
SIIGO_NC_DOCUMENT_TYPE_ID   -- tipo "Nota Crédito" en su Siigo
SIIGO_FV_DOCUMENT_TYPE_ID   -- tipo "Factura de Venta"
SIIGO_TAX_IVA_ID            -- id del IVA 19%
SIIGO_PAYMENT_TYPE_ID       -- forma de pago por defecto
SIIGO_SELLER_ID             -- vendedor por defecto
SIIGO_POSTVENTA_MODO        -- 'prueba' | 'produccion'  (switch reversible)
```
Los IDs son específicos de su cuenta Siigo → se consultan una vez vía `siigo_get`
(`/v1/document-types`, `/v1/taxes`, `/v1/payment-types`, `/v1/users`).

### 6.3 Decisiones validadas
1. **Previsualización + confirmación humana obligatoria** antes de emitir. **No auto-emitir**
   en el MVP (aunque el brief mencione automatización total). La auto-emisión llega cuando
   el motor tenga confianza probada.
2. **Idempotencia:** si ya existe `postventa_fiscal` con `doc_kind='nota_credito'` y
   `status='emitido'` para el caso, se bloquea una segunda emisión.
3. **Modo prueba primero:** arrancar contra tipo de documento de prueba; switch a producción
   por env var (`SIIGO_POSTVENTA_MODO`) **solo tras 20 casos de prueba OK**.

---

## 7. Notificaciones, errores y dashboard

### 7.1 Notificaciones WhatsApp (reutiliza `whatsapp_cloud.py`)
Momentos clave (no en cada micro-cambio):
```
aprobado              -> "Tu cambio fue aprobado ✅…"
nota_credito_emitida  -> "Generamos tu nota crédito Nº…"
factura_emitida       -> "Lista tu nueva factura / tu cambio va en camino"
rechazado             -> mensaje con motivo
```
Plantillas como constantes en el MVP (editables en Fase 6). Cada envío escribe en timeline.

### 7.2 Manejo de errores (transversal)
- **Siigo caído / 429:** backoff existente; si falla, `status='error'`, reintento manual.
  El caso no se pierde ni avanza solo.
- **WhatsApp falla:** se registra en timeline como no entregada; **no bloquea** el caso.
- **Pedido Shopify no encontrado:** el caso se crea en modo "sin vínculo" y se resuelve
  manual; nunca se traba al equipo por un dato faltante.
- Toda acción fiscal deja `payload_snapshot` para auditoría y reintento.

### 7.3 Dashboard básico (reutiliza patrón `dashboard.py` + `metricas.py`)
```
- Casos por estado (bandeja con contadores)
- Abiertos vs cerrados (semana / mes)
- Motivos más frecuentes (top 5)
- Nº de notas crédito emitidas + monto total COP
- Casos en 'error' fiscal (atención inmediata)
```
KPIs profundos (por asesora, transportadora, predicción) → Fase 6.

---

## 8. APIs del módulo (borrador)

Router `backend/api/postventa.py` (nombres finales se afinan en el plan):
```
GET    /postventa/casos                 -- bandeja, con filtros por estado
POST   /postventa/casos                 -- crear caso (crear_caso, agnóstico a la puerta)
GET    /postventa/casos/{id}            -- detalle
PATCH  /postventa/casos/{id}            -- cambiar estado / asignar / notas
POST   /postventa/casos/{id}/items      -- agregar/editar items
POST   /postventa/casos/{id}/evidencia  -- subir evidencia (Storage)
GET    /postventa/casos/{id}/shopify    -- traer pedido original de Shopify
POST   /postventa/casos/{id}/fiscal/preview  -- armar y previsualizar NC/factura (paso 2)
POST   /postventa/casos/{id}/fiscal/emitir   -- emitir en Siigo (paso 3, confirmado)
POST   /postventa/casos/{id}/fiscal/reintentar -- reintento desde payload_snapshot
GET    /postventa/dashboard             -- contadores
```

---

## 9. Estrategia de pruebas

- **Unitarias:** máquina de estados (transiciones válidas/inválidas), cálculo de IVA al armar
  el doc Siigo, guard de idempotencia, cálculo de `price_difference`.
- **Integración Siigo (modo prueba):** localizar factura original, emitir NC, emitir factura,
  manejar rechazo.
- **Mocks** de WhatsApp/Shopify para CI (sin dependencia de servicios externos).

### 9.1 Criterios de salida del MVP (gate a producción real)
```
[ ] 20 casos de prueba completos en modo prueba Siigo, sin error fiscal
[ ] Los 3 tipos cubiertos: cambio_talla, cambio_ref (con dif. precio), reembolso/bono
[ ] Cada caso deja timeline completo + payload_snapshot
[ ] Idempotencia verificada (no se pueden emitir 2 NC al mismo caso)
[ ] Notificaciones WhatsApp llegando en los 4 momentos clave
[ ] Dashboard mostrando contadores reales
[ ] Switch a producción documentado (env var SIIGO_POSTVENTA_MODO, reversible)
```
Solo con todo verde se cambia `SIIGO_POSTVENTA_MODO=produccion` y sale.

---

## 10. Riesgos técnicos

| # | Riesgo | Mitigación |
|---|---|---|
| 1 | Campo de enlace factura original Shopify↔Siigo desconocido | Spike técnico inicial antes de codear el motor fiscal |
| 2 | IDs de configuración Siigo (tipos doc, impuestos, vendedor) específicos de la cuenta | Consultarlos una vez vía `siigo_get`; guardarlos en env |
| 3 | Emisión DIAN irreversible | Previsualización + confirmación humana + modo prueba + 20 casos gate |
| 4 | Rate limit Siigo (429) | Backoff existente reutilizado |
| 5 | Rechazos de validación DIAN (IVA, NIT, códigos) | `error_detail` + `payload_snapshot` + reintento manual |
| 6 | Cálculo de IVA (price sin IVA vs total con IVA) | Cubierto por pruebas unitarias específicas |

---

## 11. Fuera de alcance del MVP (fases siguientes)

- Reserva de inventario y generación de guías/despacho (Fase 3).
- Portal de autoservicio para la clienta (Fase 4).
- IA: clasificación de motivo, riesgo de fraude, recomendación, detección de error de
  asesoría/logística/defecto (Fase 5).
- Reportes profundos, predicción, alertas avanzadas, motor de reglas editable,
  bonos/reembolsos operativos automáticos (Fase 6).
