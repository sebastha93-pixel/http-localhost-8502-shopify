# 07 · Riesgos técnicos

Ordenados por **exposición** = probabilidad × impacto. Cada uno trae una **prueba de
verificación**: la forma concreta de saber si la mitigación funciona, no de suponerlo.

---

## 🔴 Críticos — pueden detener el proyecto o la operación

### R1 · Siigo no permite emitir con el prefijo DIAN de la caja

**Probabilidad: alta (ya está confirmado) · Impacto: bloqueante**
**Estado: 🟢 con camino de salida decidido (2026-08-05)** — se crean comprobantes nuevos por
tienda, emitibles por API. Procedimiento en [09-HABILITACION-FISCAL.md](09-HABILITACION-FISCAL.md).
El riesgo **no se cierra** hasta que la prueba de verificación de abajo esté en verde.

No es una hipótesis. `tiendas.py:57-73` lo documenta con el error textual de Siigo:
`"The id cannot be used, you must verify the document settings"` para FV-6, FV-11 y FV-12.
Y `/document-types` ni siquiera los devuelve — *"esa ausencia era la señal, no un descuido"*.
Son rangos DIAN cuyo consecutivo lo lleva el POS físico.

Si esto no se resuelve, el POS factura con el prefijo de la venta online y **descuadra la
numeración DIAN de las tiendas**.

**Mitigación**
1. Comprobante nuevo por tienda con su propia resolución DIAN, habilitado para API.
2. `retail.cajas.siigo_documento_id` es NULL hasta confirmarse por API, y el sistema **se
   niega a facturar** con un id no confirmado (mismo criterio que ya aplica `tiendas.py:83`).
3. Los prefijos nuevos son **aditivos**: no tocan FV-6/11/12, así que un fallo no afecta la
   operación actual de las tiendas.

**Prueba de verificación, en dos pasos:**
1. **El barato y decisivo** — `GET /document-types` devuelve el prefijo nuevo. Si no aparece,
   la API no lo va a aceptar, y ninguna cantidad de código lo arregla. Un segundo de consulta
   contra semanas de desarrollo mal invertido.
2. Emitir una factura de prueba por API con ese prefijo y **releerla**, confirmando prefijo,
   total, pagos, bodega y centro de costo.

Sin los dos en verde, la Fase 3 no arranca.

---

### R2 · Cuota y velocidad de la API de Siigo

**Probabilidad: alta · Impacto: alto**

Siigo va a ~1 petición/segundo. Un sábado a las 6 p.m., tres cajas facturando + creación de
clientes + relectura de verificación = 3 peticiones por venta. Un pico de 15 ventas en 10
minutos son 45 peticiones. Cabe, pero sin margen — y hay precedente en el proyecto de agotar
la cuota diaria de una API (Melonn, 10.000/día).

**Mitigación**
- Token bucket **compartido en Redis**, no por réplica.
- Prioridad: emisión fiscal > cliente > catálogo. El catálogo se pausa si hay cola fiscal.
- Agrupación de la sincronización de catálogo fuera del horario comercial.
- Métrica y alerta: profundidad de cola > 20 o antigüedad > 10 min.

**Prueba:** simulacro de 200 ventas en 30 minutos contra el ambiente de pruebas de Siigo,
midiendo la antigüedad máxima de la cola. Objetivo: ningún documento espera más de 5 minutos.

---

### R3 · PostgREST no da transacciones

**Probabilidad: certeza · Impacto: alto**

Todo el ERP habla con la base por `supabase-py`. Una venta necesita escribir venta + líneas +
pagos + asientos de inventario + movimiento de caja + auditoría + outbox **atómicamente**. Sin
transacción, un fallo a mitad de camino deja stock descargado sin venta, o venta sin plata en
la caja.

**Mitigación:** ADR-004 — SQLAlchemy 2.0 async + Alembic sólo en el módulo retail.
**Prueba:** test de integración que mata la conexión a la mitad de `CerrarVenta` y verifica
que **nada** quedó escrito.

---

### R4 · La elección de líder por `/tmp` se rompe con varias réplicas

**Probabilidad: alta al escalar · Impacto: crítico**

`backend/main.py:73` elige líder creando un archivo en `/tmp`. Con dos réplicas de Railway
hay dos sistemas de archivos y **dos líderes**. Para los schedulers actuales es una molestia;
para la emisión fiscal es un documento duplicado ante la DIAN.

**Mitigación**
- El worker de outbox es un servicio Railway **aparte con una réplica**.
- Además toma `pg_advisory_lock` por `venta_id`.
- Además el outbox se consume con `FOR UPDATE SKIP LOCKED`.
- Además `ux_doc_emitido` (índice único parcial) hace **imposible** un segundo documento
  emitido para la misma venta.

Cuatro capas, porque el costo del fallo es un problema tributario.

**Prueba:** levantar 3 workers a propósito contra la misma cola y verificar que se emite
exactamente un documento por venta.

---

## 🟠 Altos

### R5 · Sobreventa por stock desactualizado

**Probabilidad: media · Impacto: medio-alto**
Hoy el stock se lee de Siigo con hasta 1 h de antigüedad (`postventa_inventario.py:31`).

**Mitigación:** ADR-003 (fuente de verdad propia) + reserva atómica en una sola sentencia
`UPDATE ... WHERE cantidad - reservado >= n` + difusión por WebSocket a las demás cajas +
conciliación diaria.
**Prueba:** dos dispositivos venden simultáneamente la última unidad; exactamente uno lo logra
en línea, el saldo nunca queda negativo.

### R6 · Ventas duplicadas al sincronizar

**Probabilidad: media · Impacto: alto** (factura duplicada = nota crédito + clienta molesta)
**Mitigación:** ULID del dispositivo como PK + `ON CONFLICT DO NOTHING` + `X-Idempotency-Key`.
**Prueba:** enviar el mismo lote de 50 ventas 100 veces. Resultado esperado: 50 ventas.

### R7 · Reloj del dispositivo desfasado

**Probabilidad: media · Impacto: medio**
Una tablet con la hora corrida 3 horas manda ventas offline con fecha equivocada: caen en el
turno que no es y en el día contable que no es.

**Mitigación:** la hora la pone **siempre** el servidor. La hora del dispositivo se guarda
como dato informativo en `creada_en_dispositivo` y el desfase se registra en
`dispositivos.ultimo_desfase_ms`. Desfase > 5 min ⇒ advertencia; > 1 h ⇒ bloqueo hasta
sincronizar.
**Prueba:** correr el reloj del dispositivo 3 h y verificar que la venta queda con hora de
servidor y genera alerta.

### R8 · Aritmética de dinero con float

**Probabilidad: media · Impacto: alto**
Ya hay precedente en el repo: un precio que salió 169.900 → 67.960
(`postventa_inventario.py:44`), y la trampa de `tax_included` que duplica o parte el precio
sin avisar.

**Mitigación:** ADR-008 (entero en centavos, en backend y frontend) + lint que prohíbe
`float(` en `domain/` y `application/` + normalización del IVA en un solo lugar.
**Prueba:** venta de 3 ítems con descuentos del 7 %, 13 % y 22 %; el total debe coincidir al
peso con el cálculo manual, y con lo que devuelve Siigo al releer.

### R9 · Impresión térmica desde el navegador

**Probabilidad: alta · Impacto: medio** (una venta sin ticket es una discusión con la clienta)
WebUSB/WebSerial son frágiles, dependen del navegador y piden permisos.

**Mitigación:** **reutilizar el agente local de impresión** que ya está en producción
(`~/Proyectos/AGENTE-IMPRESION`, corriendo como tarea SYSTEM y probado con SAT/Honeywell/
RICOH). El navegador hace un POST a la IP local; el agente habla ESC/POS. Sin permisos, sin
drivers en el navegador, y **funciona offline** porque es la red de la tienda.
**Prueba:** imprimir 100 tickets seguidos con el backend caído.

---

## 🟡 Medios

### R10 · Datáfono no integrado

**Impacto: medio, permanente hasta integrarlo.** Lo digitado puede no ser lo cobrado. Es la
fuente clásica de descuadre y de fraude.
**Mitigación Fase 1:** campo de referencia (últimos 4 del voucher) obligatorio, y el arqueo
compara contra el cierre del datáfono. **Fase 2:** integración con el adquiriente (decisión D3).

### R11 · Corte de energía en la tienda

**Mitigación:** UPS para el equipo de caja, el router y la impresora (30 min alcanzan). La PWA
sobrevive al reinicio porque el carrito vive en IndexedDB, no en memoria.
**Prueba:** desconectar la corriente a mitad de una venta y verificar que el carrito se
recupera al volver.

### R12 · Robo o pérdida del dispositivo

**Mitigación:** token de dispositivo revocable (ADR-006), PIN con bloqueo a los 5 intentos,
IndexedDB sin datos de tarjetas (nunca se almacenan), y la revocación invalida el token en la
siguiente petición.

### R13 · Corte silencioso a 1.000 filas de Supabase

**Probabilidad: alta si no se corrige · Impacto: medio**
Precedente documentado en el proyecto: `cargar_map` leía 1.000 de 2.875 filas sin avisar.
**Mitigación:** SQLAlchemy directo (ADR-004) elimina el límite de PostgREST; además toda
respuesta de lista declara `{ total, pagina, completo }`. Una función que mide tiene que
reportar **cómo terminó**.

### R14 · Python 3.10 en Railway y `fromisoformat`

**Mitigación:** helper único de parseo de fechas en el módulo; lint que prohíbe
`datetime.fromisoformat` directo en `modules/retail/`.

### R15 · Token de Shopify que expira cada 24 h

Después de enero 2026 el token se obtiene por `client_credentials` y dura 24 h.
**Mitigación:** renovación automática con margen, y alerta si falla. Un token vencido a las
3 a.m. no puede descubrirse a las 10 a.m. con la tienda abierta.

### R16 · Adopción — la cajera prefiere el sistema viejo

**Probabilidad: media · Impacto: alto.** Es el riesgo que más POS mata, y no es técnico.
**Mitigación:** el POS tiene que ser **medible y visiblemente más rápido** que Siigo POS
(objetivo: 30 s vs. lo que toma hoy — medirlo antes de empezar). Piloto en una sola caja,
capacitación con las cajeras presentes en el diseño de la pantalla de venta, y un canal
directo para reportar fricción durante las primeras dos semanas.

---

## Resumen

| Riesgo | Exposición | Cuándo se resuelve |
|---|---|---|
| R1 Prefijo fiscal | 🔴 Crítico | **Fase 0 — bloquea todo lo demás** |
| R2 Cuota Siigo | 🔴 Crítico | Fase 0 (medir) → Fase 3 (mitigar) |
| R3 Sin transacciones | 🔴 Crítico | Fase 1 |
| R4 Líder duplicado | 🔴 Crítico | Fase 3 |
| R5 Sobreventa | 🟠 Alto | Fase 2 |
| R6 Duplicados | 🟠 Alto | Fase 4 |
| R7 Reloj | 🟠 Alto | Fase 4 |
| R8 Float | 🟠 Alto | Fase 1 |
| R9 Impresión | 🟠 Alto | Fase 3 |
| R10 Datáfono | 🟡 Medio | Fase 2 (posterior) |
| R11–R15 | 🟡 Medio | Fase 5 |
| R16 Adopción | 🟠 Alto | Fase 6 — piloto |

**La regla:** ningún riesgo 🔴 se lleva a producción sin su prueba de verificación en verde.
