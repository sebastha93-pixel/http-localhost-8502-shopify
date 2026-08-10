# MALE'DENIM OS — Módulo `retail` (POS) · FASE 1: Diseño

> Estado: **propuesta de diseño**. Ninguna línea de código escrita.
> Fecha: 2026-08-05 · Alcance: diseño completo previo a implementación.

---

## Los documentos

| # | Documento | Contiene |
|---|-----------|----------|
| 00 | Este archivo | Resumen ejecutivo, hallazgos, decisiones que dependen de ti |
| 01 | [Arquitectura](01-ARQUITECTURA.md) | Vista C4, decisiones de arquitectura (ADR), estructura de carpetas |
| 02 | [Dominio DDD](02-DOMINIO-DDD.md) | Bounded contexts, agregados, entidades, value objects, invariantes, eventos |
| 03 | [Casos de uso](03-CASOS-DE-USO.md) | Capa de aplicación: comandos, queries, CQRS, contratos de API |
| 04 | [Modelo de datos](04-MODELO-DATOS.md) | DDL completo de PostgreSQL, índices, constraints, migraciones |
| 05 | [Flujos](05-FLUJOS.md) | Venta paso a paso, Siigo, Shopify, offline/sync, caja |
| 06 | [Diseño UX](06-UX.md) | Sistema de diseño, wireframes de las 15 pantallas, presupuesto de latencia |
| 07 | [Riesgos](07-RIESGOS.md) | 16 riesgos técnicos priorizados, con mitigación y prueba de verificación |
| 08 | [Roadmap](08-ROADMAP.md) | 7 fases, criterios de salida, estimación, orden de construcción |
| 09 | [Habilitación fiscal](09-HABILITACION-FISCAL.md) | Runbook para crear los comprobantes nuevos en Siigo y **verificarlos** |

---

## 0. Cómo correr las pruebas

La primera vez, para dejar el entorno listo:

```bash
cd ~/Proyectos/MALE-DENIM-OS/codigo
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
createdb retail_pos_test
```

Y de ahí en adelante:

```bash
RETAIL_TEST_DATABASE_URL="postgresql+psycopg://localhost/retail_pos_test" .venv/bin/pytest tests/retail -q
```

**Sin la variable, las pruebas de integración se saltan enteras** y sólo corren las de
dominio. Es deliberado: no hay valor por defecto para la base, porque un default apuntando a
la equivocada es la clase de error que se descubre después de haber borrado algo.

| | Cuántas | Necesita | Tarda |
|---|---|---|---|
| Dominio (`tests/retail/dominio`) | 135 | nada — ni base, ni red, ni FastAPI | 0,1 s |
| Integración (`tests/retail/integracion`) | 16 | PostgreSQL | 0,9 s |

Que las 135 del dominio corran sin base de datos no es una curiosidad: es la razón entera
de la arquitectura hexagonal en este módulo (ADR-001).

---

## 1. Resumen ejecutivo

El POS de MALE'DENIM **no es una app de punto de venta**. Es el módulo que convierte a
MALE'DENIM OS en el sistema operativo de la venta física: el lugar donde nacen los
movimientos de inventario, el dinero y los documentos fiscales de las tiendas.

Hoy esos tres hechos nacen en **Siigo POS**, un sistema cerrado que no tiene API. Eso ya
está costando dinero visible: `backend/services/postventa_caja.py` existe únicamente
porque *"no hay forma de escribirle al POS (Siigo POS no tiene API)"* y la cajera termina
el día con más plata de la que su cierre dice, sin saber de dónde salió.

**Construir este módulo no agrega una función: elimina una clase entera de problemas.**

### Las tres tesis del diseño

**Tesis 1 · Siigo no puede estar en la ruta crítica de la venta.**
Siigo va a ~1 petición por segundo, con latencia variable y caídas. Una venta que espera
la respuesta de Siigo para cerrarse jamás va a garantizar 30 segundos. → La venta se cierra
**localmente** contra nuestro propio libro mayor; el documento fiscal se emite en segundo
plano con máquina de estados y reintentos. El ticket se imprime al instante; el CUFE llega
segundos después (normalmente antes de que la clienta salga) y se adjunta.

**Tesis 2 · La fuente de verdad del inventario de tienda pasa a MALE OS.**
Hoy el inventario vive en Siigo y lo leemos cacheado con hasta 1 hora de antigüedad
(`postventa_inventario.py:31`). Un POS que vende contra un espejo de una hora sobrevende.
→ **Libro mayor de movimientos (append-only) + saldo materializado con reserva atómica.**
Siigo pasa a ser el espejo contable, reconciliado por un job diario que reporta diferencias.
Es el mismo patrón que ya usa Producción (`movimientos_inventario`).

**Tesis 3 · Offline-first es un log local con outbox idempotente, no "sincronizar la base".**
Cada venta nace con un ULID generado **en el dispositivo**, que es su llave de idempotencia.
El servidor la acepta con `ON CONFLICT DO NOTHING`. Consecuencia: una venta nunca se pierde
y nunca se duplica, aunque el dispositivo reintente 40 veces. Los consecutivos de ticket se
entregan en **bloques arrendados** por caja, así que sin internet se sigue numerando sin
colisión.

### Cómo encaja en el ERP

El POS **no es una aplicación aparte**. Es `backend/modules/retail/` dentro del mismo repo,
detrás del mismo JWT, con el mismo sistema de permisos, sirviendo `frontend/app/pos/` en el
mismo Next.js. Lo único nuevo en infraestructura es Redis (locks + pub/sub de WebSockets) y
una tabla de outbox.

Reutiliza, sin reescribir: el emisor fiscal (`EmisorSiigo` ya implementa un protocolo
`EmisorFiscal`), la configuración de tiendas (`tiendas.py` ya tiene bodegas, centros de
costo y medios de pago por punto **verificados contra la API**), el agente local de
impresión (`~/Proyectos/AGENTE-IMPRESION`), y el código de barras Code128 que Producción ya
imprime en las etiquetas Zebra de cada prenda.

---

## 2. Hallazgos del código actual que condicionan el diseño

Esto no es teoría. Salió de leer el repositorio.

| # | Hallazgo | Dónde | Consecuencia en el diseño |
|---|----------|-------|---------------------------|
| H1 | **Siigo rechaza emitir con los prefijos DIAN de las cajas** (FV-6 / FV-11 / FV-12). Error: `"The id cannot be used, you must verify the document settings"`. Hoy se emite con FV-1 (online) como paliativo. | `backend/services/tiendas.py:57-73` | **Riesgo bloqueante R1.** El POS necesita facturar con el prefijo del punto. Requiere gestión con Siigo/DIAN antes de codificar. Ver §3. |
| H2 | Siigo POS no tiene API; `postventa_caja` existe para compensarlo | `backend/services/postventa_caja.py:9` | El POS nuevo **reemplaza** a Siigo POS. `postventa_caja` se vuelve innecesario cuando el módulo esté vivo. |
| H3 | El acceso a datos es `supabase-py` (PostgREST). **No hay ORM, ni transacciones, ni `SELECT … FOR UPDATE`.** | Todo `backend/services/` | Un POS necesita atomicidad (venta + stock + caja + auditoría en una transacción). → **ADR-004**: SQLAlchemy 2.0 async + Alembic **sólo** en el módulo retail. Convive con lo existente. |
| H4 | Los ids de Siigo visibles en pantalla **no son** los de la API (bodega 5 ≠ id 5). Ya reventó una nota crédito. | `tiendas.py:28-35` | Toda configuración de tienda se descubre por API y se valida al arrancar. Nunca se adivina un id. |
| H5 | Siigo **descarta en silencio** campos opcionales mal formados (pasó con `warehouse`: el inventario no se movía y no había error) | `tiendas.py:211-221` | Toda emisión fiscal se **verifica releyendo el documento** en Siigo. Ya hay precedente: `postventa_caja.comparar_pagos`. |
| H6 | Elección de líder por lock en `/tmp` para los schedulers | `backend/main.py:73-88` | Funciona con varios workers en **una** máquina; se rompe con múltiples réplicas en Railway. → **ADR-007**: lock en Redis o en Postgres (`pg_advisory_lock`). Riesgo R4. |
| H7 | El inventario de tienda se cachea de Siigo y puede tener hasta 1 h de antigüedad | `postventa_inventario.py:31` | No sirve como fuente de verdad para vender. → Tesis 2. |
| H8 | JWT HS256 con **sesión deslizante**, sin refresh token. Revalida contra BD cada 30 s. | `backend/core/security.py:76-110` | Se conserva el mecanismo, pero el POS necesita sesión larga en dispositivo confiable + **PIN de cajera** para el turno. Ver ADR-006. |
| H9 | Permisos por **grupo** (`MODULOS_GRUPOS`) con acciones `ver/modificar/borrar` | `backend/services/usuarios.py:57-80` | Se extiende con el grupo `retail` y permisos finos (tope de descuento, anular, arqueo). No se inventa un RBAC paralelo. |
| H10 | `SELECT` sin paginar corta en 1.000 filas en Supabase, **en silencio** | Memoria del proyecto | Toda lectura de catálogo/ventas pagina explícitamente y **reporta cómo terminó**. |
| H11 | Railway corre Python **3.10**; `datetime.fromisoformat` revienta con fracciones de segundo de Postgres | Memoria del proyecto | Parser de fechas centralizado en el módulo. Nunca `fromisoformat` directo. |
| H12 | Ya existe agente local de impresión por IP, corriendo como tarea SYSTEM | `~/Proyectos/AGENTE-IMPRESION` | La impresión térmica del ticket reutiliza ese agente. No se inventa WebUSB. |
| H13 | El SKU real tiene forma `93634-1T12` (referencia + talla) y ya se imprime en Code128 | Memoria + módulo Producción | El escaneo del POS funciona **desde el día uno** con las etiquetas que ya se imprimen. |

---

## 3. Decisiones que necesito de ti antes de la Fase 2

Estas tres no las puedo resolver leyendo código. Cambian lo que se construye.

### ~~D1 · ¿Con qué documento fiscal factura el POS?~~ — ✅ **RESUELTA** (2026-08-05)

**Decisión: comprobantes nuevos, uno por tienda, emitibles por API.**

Se descarta habilitar FV-6/11/12 (los prefijos de las cajas actuales) y se crean prefijos
propios del POS con su resolución DIAN, uno por punto de venta.

📄 **Procedimiento y verificación: [09-HABILITACION-FISCAL.md](09-HABILITACION-FISCAL.md)**

Lo esencial: crear el comprobante en Siigo **no basta**. La prueba decisiva —de un segundo,
y antes de escribir una línea de código— es que el prefijo nuevo **aparezca en
`GET /document-types`**. Esa ausencia es exactamente lo que delata a FV-6/11/12 hoy.

**Consecuencia importante sobre D2:** los prefijos nuevos son **aditivos**. No tocan la
numeración actual, así que el POS puede facturar en paralelo durante el piloto sin poner en
riesgo la operación de las tiendas.

### D2 · ¿El POS reemplaza a Siigo POS, o convive con él?

Con D1 resuelta por la vía de prefijos nuevos, esta decisión **deja de ser de fondo y pasa a
ser de calendario**: se convive durante el piloto (Fase 6) porque no cuesta nada, y se
reemplaza cuando las métricas lo justifiquen.

- **Reemplazo al final** (recomendado): una sola fuente de verdad, se acaba el descuadre de
  `postventa_caja`, el arqueo es real.
- **Convivencia permanente**: dos sistemas facturando en la misma tienda, dos consecutivos,
  arqueo partido. Multiplica el trabajo de conciliación; sólo tiene sentido como estado
  transitorio.

Lo único que hay que decidir ahora: **si la convivencia va a durar más allá del piloto**, el
roadmap necesita una fase extra de conciliación diaria entre ambos sistemas.

### D3 · ¿Se integra el datáfono?

Hoy el cobro con tarjeta se hace en el datáfono y se digita en el POS. Eso deja un hueco:
nada garantiza que lo digitado sea lo cobrado (fuente clásica de descuadre y de fraude).

- **Sin integrar** (Fase 1): la cajera digita el valor y los 4 últimos dígitos del voucher.
  El arqueo compara contra el cierre del datáfono manualmente. Funciona, es lo que hay hoy.
- **Integrado** (Fase 2+): Redeban / Credibanco / Wompi POS exponen integración. Elimina el
  hueco por completo.

**Recomiendo empezar sin integrar** y dejar el puerto (`PasarelaPagoPort`) listo en el
diseño, que es lo que hace el documento 02. Pero si ya hay contrato con algún adquiriente,
dímelo y lo meto en el roadmap de Fase 1.

---

## 4. Lo que este diseño NO incluye (por instrucción tuya)

Cambios · devoluciones · notas crédito · bonos · fidelización · apartados · traslados entre
tiendas.

**Pero el modelo de dominio los deja entrar sin rediseño.** Concretamente:

- El libro mayor de inventario acepta movimientos de cualquier `motivo` — un traslado son dos
  asientos, no un modelo nuevo.
- `DocumentoFiscal.tipo` ya contempla `nota_credito` (el emisor Siigo ya la emite hoy en
  postventa).
- La `Venta` tiene `documento_origen_id` reservado para el día que una venta nazca de un
  cambio.
- `MedioDePago` es una tabla, no un enum: un bono es un medio de pago más.

Eso es la diferencia entre "no lo construimos todavía" y "va a tocar rehacer todo".

---

## 5. Métrica de éxito de la Fase 1 de implementación

No "funciona". Esto:

| Métrica | Objetivo | Cómo se mide |
|---------|----------|--------------|
| Venta de 3 prendas, cliente conocido, un medio de pago | **≤ 30 s** de escaneo a ticket impreso | Instrumentación en el cliente, percentil 95 |
| Búsqueda de producto | **≤ 50 ms** para pintar resultados | Local en IndexedDB, no viaja a red |
| Cierre de venta (clic "Cobrar" → ticket) | **≤ 800 ms** percentil 95 | Sin esperar a Siigo |
| Ventas perdidas por caída de internet | **0** | Prueba: modo avión durante 2 h de operación |
| Ventas duplicadas tras reintentos | **0** | Prueba: 50 reintentos forzados del outbox |
| Descuadre de caja no explicado | **$0** | Arqueo vs. suma de pagos del turno |
| Diferencia inventario MALE OS vs. Siigo | **< 0,5 %** de unidades | Job de conciliación diario |
