# 05 · Flujos

---

## 1. Flujo completo de una venta

### 1.1 Presupuesto de los 30 segundos

El objetivo no es "rápido". Es este reparto, medido en el dispositivo, percentil 95:

| Paso | Tiempo | Quién manda |
|---|---|---|
| Escanear 3 prendas (3 × 1,5 s) | 4,5 s | La cajera |
| Buscar/asignar cliente (opcional) | 4 s | La cajera |
| Clic en **Cobrar** | 0,2 s | Sistema |
| Elegir medio de pago y digitar monto | 6 s | La cajera |
| Cobro en el datáfono | 8 s | El banco |
| **`CerrarVenta` → ticket en la impresora** | **0,8 s** | **Sistema** |
| Entregar bolsa y ticket | 4 s | La cajera |
| **Total** | **~27,5 s** | |

**El sistema sólo controla 1 segundo de los 30.** Por eso ADR-002 (no esperar a Siigo) no es
una optimización: es la única forma de que el número cierre. Si `CerrarVenta` esperara a
Siigo, ese 0,8 s se volvería 2–6 s en un día bueno y 30 s en uno malo.

### 1.2 Secuencia

```mermaid
sequenceDiagram
    autonumber
    actor C as Cajera
    participant UI as PWA (dispositivo)
    participant IDB as IndexedDB
    participant API as FastAPI
    participant DOM as Dominio
    participant PG as PostgreSQL
    participant OBX as Outbox Worker
    participant SG as Siigo
    participant IMP as Impresora
    participant WS as WebSocket

    Note over C,IDB: ── Armado del carrito · todo LOCAL ──
    C->>UI: escanea 93634-1T12
    UI->>IDB: buscar por código de barras
    IDB-->>UI: variante (< 10 ms)
    UI->>UI: agrega línea, recalcula totales
    UI-->>C: pinta la línea (< 50 ms)
    UI-)API: POST /ventas/{id}/lineas (en segundo plano)
    API->>PG: reserva stock (UPDATE atómico)

    Note over C,UI: ── Cobro ──
    C->>UI: Cobrar → Efectivo $180.000
    UI->>UI: calcula vuelto
    C->>UI: confirma

    Note over UI,PG: ── CerrarVenta · UNA transacción ──
    UI->>API: POST /ventas/{id}/cerrar
    API->>DOM: venta.cerrar(reloj)
    DOM->>DOM: ✅ INV-V2,V3,V5,V8
    DOM-->>API: evento VentaCerrada
    API->>PG: BEGIN
    API->>PG: UPDATE venta → cerrada + totales
    API->>PG: asientos de inventario (reserva → descarga)
    API->>PG: movimiento de caja
    API->>PG: auditoría encadenada
    API->>PG: INSERT outbox × 2
    API->>PG: COMMIT
    API-->>UI: 200 { numero, total, vuelto, ticket } (~800 ms)

    par Impresión inmediata
        UI->>IMP: ticket (agente local)
        IMP-->>C: papel 🧾
    and Difusión
        API-)WS: venta.cerrada · stock.actualizado
    and Fiscal en segundo plano
        OBX->>PG: toma outbox (SKIP LOCKED)
        OBX->>SG: POST /invoices
        SG-->>OBX: { id, name, cufe }
        OBX->>SG: GET /invoices/{id}  ← relectura (H5)
        OBX->>OBX: compara total, pagos, bodega
        OBX->>PG: documento → emitido
        OBX-)WS: documento.emitido
        WS-->>UI: CUFE listo
        UI-->>C: "Factura FV-11-1334 ✅"
    end
```

**Lo que la clienta ve:** la cajera escanea, cobra, y el papel sale. El resto ocurre después
de que se fue.

### 1.3 Qué pasa si algo falla en cada punto

| Falla | Consecuencia | Recuperación |
|---|---|---|
| No hay stock al agregar la línea | **Advertencia**, no bloqueo. La prenda está en la mano. | Se registra el negativo y se alerta |
| Se cae internet armando el carrito | El carrito ya vive en IndexedDB. Sigue igual. | Al volver, el outbox descarga |
| Se cae internet al cerrar | La venta se cierra **local**, entra al outbox, se imprime | Sincroniza al volver, sin duplicar (ULID) |
| Falla la impresora | La venta **ya está cerrada y es válida** | Botón de reimprimir (auditado) |
| Siigo devuelve 429 | El documento queda en cola | Reintento exponencial |
| Siigo devuelve 4xx de negocio | Estado `rechazado` + alerta | Corrección manual y reintento desde el panel |
| La relectura no coincide (H5) | Estado `discrepante` 🚨 | **Alerta crítica.** La factura existe pero no dice lo que mandamos. |
| Se cae Postgres al cerrar | La transacción no se confirma; la PWA reintenta | Idempotencia: la venta entra una sola vez |

---

## 2. Flujo fiscal con Siigo

```mermaid
flowchart TD
    A[VentaCerrada] --> B[outbox: emitir_documento]
    B --> C{Worker toma el trabajo<br/>FOR UPDATE SKIP LOCKED}
    C --> D{¿El cliente existe<br/>en Siigo?}
    D -->|No y hay cliente| E[POST /customers<br/>guarda siigo_customer_id]
    D -->|Consumidor final| F[usa el cliente genérico<br/>configurado]
    E --> G[Mapeador: Venta → payload Siigo]
    F --> G
    G --> H{Rate limiter<br/>token bucket compartido}
    H -->|espera| H
    H -->|permiso| I[POST /invoices]
    I --> J{Respuesta}
    J -->|2xx| K[GET /invoices/id<br/>⭐ RELECTURA]
    J -->|429 / 5xx / red| L[backoff exponencial<br/>1,2,4,8,16,32,64,128 s]
    J -->|4xx negocio| M[estado: rechazado<br/>🚨 alerta]
    L --> N{¿8 intentos?}
    N -->|no| C
    N -->|sí| O[estado: fallido<br/>🚨 alerta a gerencia]
    K --> P{¿total, pagos y bodega<br/>coinciden?}
    P -->|sí| Q[✅ emitido<br/>guarda número, CUFE, PDF, XML]
    P -->|no| R[⚠️ discrepante<br/>🚨 alerta crítica]
    Q --> S[WS: documento.emitido]
    S --> T[Adjunta CUFE al ticket<br/>+ envía por WhatsApp/correo]

    style K fill:#8A6A22,color:#fff
    style R fill:#C8412B,color:#fff
    style Q fill:#4F6B4C,color:#fff
```

### Por qué la relectura es obligatoria

`tiendas.py:211-221` lo documenta con precisión: *"mientras el campo iba mal formado, Siigo lo
descartaba en silencio y el error no aparecía nunca —el inventario simplemente no se movía"*.

Un POS que confía en el `200 OK` de Siigo va a producir facturas que no dicen lo que la
cajera cobró, y nadie se entera hasta el cierre contable del mes. La relectura cuesta una
petición más y convierte un error invisible en una alerta.

Ya existe el precedente exacto en el repo: `postventa_caja.comparar_pagos()`.

### Rate limiting

Siigo va a ~1 petición/segundo. Con 3 cajas facturando un sábado son ~3 documentos/minuto en
promedio, pero **con picos**: a las 6 p.m. entran 15 ventas en 10 minutos.

- Token bucket **compartido en Redis** (no por réplica).
- Prioridad: emisión fiscal > consulta de cliente > sincronización de catálogo.
- La sincronización de catálogo se pausa cuando hay cola fiscal.
- El tablero muestra la profundidad de la cola. Cola > 20 o antigüedad > 10 min ⇒ alerta.

### Creación perezosa del cliente en Siigo

El cliente se crea en **nuestra** base al instante (funciona offline) y en Siigo sólo al
emitir su primer documento. Razones: no ensucia Siigo con clientes que nunca compraron, no
bloquea la venta si Siigo está caído, y no gasta cuota de la API en la ruta crítica.

---

## 3. Flujo de sincronización con Shopify

Dos direcciones, ninguna en la ruta crítica de la venta.

```mermaid
flowchart LR
    subgraph Salida["MALE OS → Shopify (evento)"]
        A[StockDescargado] --> B[outbox:<br/>publicar_stock]
        B --> C[Agrupa por variante<br/>ventana de 30 s]
        C --> D[POST inventory_levels/set]
        D --> E{OK?}
        E -->|sí| F[✅]
        E -->|no| G[reintento]
    end

    subgraph Entrada["Shopify → MALE OS (programado)"]
        H[cada 2 h] --> I[GET products delta]
        I --> J[Normaliza:<br/>precio SIN IVA]
        J --> K[UPSERT variantes]
        K --> L[Reconstruye catalogo_busqueda]
        L --> M[WS: catálogo actualizado]
        M --> N[Dispositivos bajan el delta]
    end
```

### Decisiones

| Decisión | Razón |
|---|---|
| **Agrupación de 30 s** antes de publicar stock | Vender 3 prendas de la misma referencia genera 1 llamada, no 3 |
| Shopify es fuente de verdad del **catálogo** (nombre, foto, precio de lista) | Ahí lo edita el equipo comercial |
| MALE OS es fuente de verdad del **stock de tienda** (ADR-003) | Ahí es donde nace el movimiento |
| Se publica sólo el stock de las **ubicaciones mapeadas** | La bodega de Melonn la maneja logística, no el POS |
| Delta incremental por `updated_at` | El catálogo completo son 80 páginas a 1 req/s |
| Se pagina **explícitamente** y se reporta si quedó incompleto | H10 + precedente: una medición truncada se lee como prueba y es falsa |

### El riesgo del token de Shopify

Memoria del proyecto: después de enero 2026 no hay `shpat_` nuevos; el token se obtiene por
`client_credentials` y **dura 24 h**. El adaptador tiene que renovarlo solo y alertar si no
puede — un token vencido a las 3 a.m. no puede descubrirse a las 10 a.m. con la tienda
abierta.

---

## 4. Flujo offline y sincronización

### 4.1 Estados de conexión

```mermaid
stateDiagram-v2
    [*] --> EnLinea
    EnLinea --> Degradado: latencia > 2 s o errores
    Degradado --> EnLinea: 3 respuestas OK seguidas
    Degradado --> FueraDeLinea: sin respuesta 15 s
    EnLinea --> FueraDeLinea: navigator.offline
    FueraDeLinea --> Sincronizando: vuelve la red
    Sincronizando --> EnLinea: outbox vacío
    Sincronizando --> FueraDeLinea: se vuelve a caer

    note right of Degradado
        Banner ámbar.
        Se escribe local primero
        y se envía en segundo plano.
    end note

    note right of FueraDeLinea
        Banner rojo con contador
        de ventas pendientes.
        SE SIGUE VENDIENDO.
    end note
```

### 4.2 Qué funciona sin internet

| Función | Offline | Cómo |
|---|:---:|---|
| Buscar producto | ✅ | Catálogo completo en IndexedDB |
| Ver stock | ⚠️ | Último snapshot, con marca de antigüedad visible |
| Agregar/quitar/modificar líneas | ✅ | Todo local |
| Descuento dentro del tope de la cajera | ✅ | La política se evalúa local |
| Descuento que exige autorización | ❌ | Requiere validar el PIN del supervisor contra el servidor |
| Buscar cliente existente | ✅ | Los clientes de la tienda se replican |
| Crear cliente | ✅ | Se crea local, se sincroniza después |
| Cobrar con cualquier medio | ✅ | — |
| Cerrar venta | ✅ | Consecutivo del bloque arrendado |
| Imprimir ticket | ✅ | Agente local por IP, en la red de la tienda |
| Documento fiscal | ⏳ | Encolado; se emite al volver |
| Stock de **otras** tiendas | ❌ | Requiere red |
| Abrir turno | ⚠️ | Sólo si ya hay bloque de consecutivos arrendado |
| Cerrar turno | ⚠️ | Se puede declarar el conteo; el cierre formal exige sincronizar primero |

### 4.3 Sincronización

```mermaid
sequenceDiagram
    autonumber
    participant UI as PWA
    participant IDB as IndexedDB
    participant API as FastAPI
    participant PG as PostgreSQL

    Note over UI: vuelve la conexión
    UI->>IDB: lee outbox (ventas pendientes)
    IDB-->>UI: [venta A, venta B, venta C]
    UI->>API: POST /sync/ventas (lote de 20)

    loop por cada venta
        API->>PG: INSERT ventas ... ON CONFLICT (id) DO NOTHING
        alt 0 filas — ya existía
            API-->>API: "duplicada" → responde OK
        else insertada
            API->>PG: líneas + pagos
            API->>PG: asientos de inventario (puede quedar negativo → alerta)
            API->>PG: movimiento de caja
            alt la sesión ya cerró
                API->>PG: marca sesion_desfasada = true
                API-)API: 🚨 avisa al supervisor (INV-C8)
            end
            API->>PG: outbox: emitir documento con FECHA ORIGINAL
            API->>PG: auditoría: venta_offline_sincronizada
        end
    end

    API-->>UI: [{id:A, aceptada}, {id:B, duplicada}, {id:C, aceptada}]
    UI->>IDB: borra del outbox las tres
    Note over UI: "duplicada" también se borra:<br/>significa que YA está en el servidor
```

**La garantía:** ejecutar el mismo lote 100 veces produce exactamente el mismo estado que
ejecutarlo una vez. Es lo que permite reintentar sin miedo.

### 4.4 Límites deliberados del modo offline

| Límite | Valor | Por qué |
|---|---|---|
| Máximo tiempo offline antes de advertir | 4 h | Después, el riesgo de descuadre e inconsistencia crece rápido |
| Máximo tiempo offline antes de bloquear ventas nuevas | 24 h (configurable) | Un dispositivo desconectado una semana no debería seguir emitiendo |
| Descuentos que exigen autorización | Bloqueados offline | No se puede validar el PIN del supervisor |
| Ventas offline sin sincronizar antes de cerrar turno | 0 | El arqueo tiene que ser sobre datos completos |

---

## 5. Flujo de caja (turno completo)

```mermaid
flowchart TD
    A[Cajera llega] --> B[PIN en el dispositivo]
    B --> C{¿Turno abierto<br/>en esta caja?}
    C -->|Sí, de otra cajera| D[⚠️ Debe cerrarlo ella<br/>o un supervisor lo fuerza]
    C -->|No| E[Apertura: declara la base]
    E --> F[Arrienda bloque de consecutivos]
    F --> G[🟢 Turno abierto]

    G --> H[Vender · retirar · ingresar · gasto]
    H --> H

    H --> I[Iniciar arqueo]
    I --> J{¿Ventas en borrador?}
    J -->|Sí| K[❌ Bloquea<br/>INV-C2 — muestra cuáles]
    K --> H
    J -->|No| L{¿Documentos fiscales<br/>pendientes?}
    L -->|Sí| M[⚠️ Avisa y pide confirmación<br/>INV-C3]
    L -->|No| N[Conteo]
    M --> N

    N --> O[Cuenta efectivo por denominación]
    O --> P[Declara cierre de datáfono<br/>y transferencias]
    P --> Q{Cierre ciego?}
    Q -->|Sí| R[NO ve el esperado<br/>hasta declarar todo]
    Q -->|No| S[Ve el esperado]
    R --> T[Calcula diferencias]
    S --> T
    T --> U{¿Diferencia ><br/>umbral?}
    U -->|No| V[✅ Cierra]
    U -->|Sí| W[Exige justificación escrita]
    W --> X[Exige autorización de supervisor<br/>INV-C5]
    X --> V
    V --> Y[Imprime informe de cierre]
    Y --> Z[🔴 Turno cerrado · inmutable]

    style R fill:#8A6A22,color:#fff
    style Z fill:#243036,color:#fff
```

### El cierre ciego

Por defecto la cajera **no ve** cuánto debería haber hasta que declara lo que contó. Es la
única forma de que el arqueo mida algo: si ve el esperado, escribe el esperado, y el
descuadre desaparece de los informes sin desaparecer de la realidad.

Configurable por tienda (`tiendas.cierre_ciego`) porque hay operaciones donde estorba, pero
el valor por defecto es `true`.

### Contenido del informe de cierre

```
MALE'DENIM · Florida · Caja 1
Turno #1284 · Cajera: María R.
Abierto  2026-08-05 09:02      Cerrado  2026-08-05 20:15

Base inicial                                    $  200.000
Ventas: 47 tickets · 89 unidades              $ 8.940.000
  Efectivo                                     $ 2.310.000
  Datáfono Florida                             $ 6.630.000
Retiros (2)                                    -$ 1.500.000
Gastos (1)                                     -$    35.000

ESPERADO EN CAJA (efectivo)                    $   975.000
CONTADO                                        $   960.000
DIFERENCIA                                     -$    15.000  ⚠️
  Justificación: faltante de vuelto, turno tarde
  Autorizó: Laura M. (Supervisora)

Datáfono esperado    $ 6.630.000
Datáfono declarado   $ 6.630.000    ✅

Descuentos aplicados: 6 · $312.000
  De los cuales autorizados por supervisor: 2 · $180.000
Anulaciones: 1 (ticket FV-11-1301)
Documentos fiscales pendientes: 0 ✅
Ventas offline sincronizadas: 3
```

---

## 6. Flujo de conciliación de inventario (diario, 3 a.m.)

```mermaid
flowchart LR
    A[Cron 3 a.m.] --> B[Lee stock_ubicacion]
    A --> C[Lee inventario de Siigo<br/>por bodega, paginado]
    B --> D[Compara por variante]
    C --> D
    D --> E{¿Diferencia?}
    E -->|No| F[✅ Registra conciliación OK]
    E -->|Sí| G[Clasifica la causa]
    G --> H[Venta no reflejada en Siigo]
    G --> I[Movimiento en Siigo que el POS no vio]
    G --> J[Negativo por venta offline]
    G --> K[Inexplicada]
    H --> L[Informe a gerencia]
    I --> L
    J --> L
    K --> M[🚨 Alerta: requiere conteo físico]
    L --> N[También verifica INV-I4:<br/>saldo = SUM del libro mayor]
```

Y verifica la cadena de hashes de auditoría (ADR-010). Si un eslabón no cuadra, alguien tocó
la tabla por fuera de la aplicación: alerta crítica inmediata.
