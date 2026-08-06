# 03 · Casos de uso y contratos de API

---

## 1. CQRS: dónde sí y dónde no

**No** se implementa CQRS completo (bases separadas, event sourcing). Se separa **comando de
consulta dentro de la misma base**, que es donde está el 90 % del beneficio y el 10 % del
costo.

| Lado | Cómo | Por qué |
|---|---|---|
| **Comandos** | Cargan el agregado completo, ejecutan reglas, guardan en una transacción, publican eventos | Consistencia fuerte donde hay dinero |
| **Consultas** | SQL directo a vistas/tablas de lectura, sin cargar agregados, sin ORM pesado | Velocidad. El buscador de productos jamás debe instanciar un agregado. |

**Dónde sí hay separación real de modelo:**
- `retail.catalogo_busqueda` — tabla de lectura desnormalizada, con el índice trigram y el
  stock por tienda ya resuelto. Se alimenta por eventos.
- `retail.venta_resumen` — vista materializada para el tablero e informes.

---

## 2. Catálogo de comandos

Formato: `Comando(entrada) → resultado · invariantes · eventos · errores`

### Caja

#### `AbrirSesionCaja`
```
entrada:   tienda_id, caja_id, base_inicial: Dinero, pin_cajera
salida:    SesionCajaId, numero_turno
verifica:  INV-C1 (una sola abierta por caja)
           el usuario tiene permiso retail.abrir_caja en esa tienda
           el dispositivo está registrado y activo
           hay bloque de consecutivos disponible (arrienda uno si no)
eventos:   SesionCajaAbierta
errores:   SesionYaAbierta · PinInvalido · DispositivoNoAutorizado · SinConsecutivos
```

#### `RegistrarMovimientoCaja`
```
entrada:   sesion_id, tipo (retiro|ingreso|gasto), monto, motivo, autorizacion?
verifica:  INV-C6 (retiro no deja efectivo negativo)
           retiro y gasto exigen permiso retail.movimiento_caja
eventos:   MovimientoCajaRegistrado
```

#### `IniciarArqueo` / `DeclararConteo` / `CerrarSesionCaja`
```
IniciarArqueo    → verifica INV-C2 (sin borradores) e INV-C3 (avisa fiscal pendiente)
DeclararConteo   → entrada: medio_pago_id, monto_contado.  En cierre ciego no devuelve esperado.
CerrarSesionCaja → calcula diferencias; INV-C5 exige justificación + autorización si excede
                   el umbral. Devuelve el informe completo y lo manda a imprimir.
eventos:         SesionCajaCerrada, DescuadreDetectado?
```

### Venta

#### `CrearVenta`
```
entrada:   venta_id (ULID del DISPOSITIVO), sesion_id, dispositivo_id
salida:    Venta en Borrador con NumeroTicket ya asignado
nota:      el id lo genera el cliente ⇒ idempotencia (ADR-005).
           Si el id ya existe, devuelve la venta existente. No es error.
```

#### `AgregarLinea`
```
entrada:   venta_id, variante_id | codigo_barras | sku, cantidad
salida:    línea creada + totales recalculados
hace:      1. resuelve la variante (búsqueda local ya la tiene)
           2. toma precio_base y tasa_iva del catálogo → los CONGELA en la línea
           3. reserva stock (INV-I1) — si no hay, devuelve advertencia pero NO bloquea:
              la cajera decide (la prenda está en la mano)
verifica:  INV-V9 (cantidad > 0) · venta en Borrador (INV-V1)
```

> **Decisión de producto:** falta de stock **advierte**, no bloquea. En moda física la prenda
> que la clienta tiene en la mano existe aunque el sistema diga que no. Bloquear la venta
> pierde plata real para proteger un dato. El negativo queda registrado y alertado.

#### `ModificarCantidad` · `EliminarLinea`
```
Ajustan la reserva de stock en consecuencia. Cantidad 0 ⇒ elimina (INV-V9).
```

#### `AplicarDescuento`
```
entrada:   venta_id, linea_id?, tipo (porcentaje|valor), valor, motivo, token_autorizacion?
hace:      PoliticaDescuento(rol_usuario, tipo, valor) → PERMITIDO | REQUIERE_AUTORIZACION | PROHIBIDO
           REQUIERE_AUTORIZACION sin token ⇒ error 403 con `requiere_autorizacion: true`
           (el frontend abre el diálogo de PIN de supervisor)
verifica:  INV-V6
eventos:   DescuentoAutorizado (⚠️ auditoría prioritaria)
errores:   RequiereAutorizacion · DescuentoProhibido · AutorizacionInvalida
```

#### `AsignarCliente` · `RegistrarPago` · `EliminarPago`
```
RegistrarPago  entrada: venta_id, medio_pago_id, monto, referencia? (últimos 4 del voucher)
               verifica: el medio pertenece a ESA tienda — precedente exacto en
                         tiendas.pagos_ajenos(): cobrar en el datáfono de Florida
                         un pago de Arrayanes descuadra las dos cajas a la vez.
```

#### `CerrarVenta` ⭐ — el caso de uso central

```
entrada:   venta_id, imprimir: bool, enviar_a (whatsapp|correo|ninguno)
salida:    { numero_ticket, total, vuelto, estado_fiscal, contenido_ticket }

TODO ESTO EN UNA SOLA TRANSACCIÓN:
  1. cargar la venta con FOR UPDATE
  2. venta.cerrar(reloj)  ─ evalúa INV-V2, V3, V5, V8
  3. convertir reservas en descargas de stock (asientos del libro mayor)
  4. registrar el ingreso en la sesión de caja
  5. escribir la auditoría encadenada (ADR-010)
  6. INSERT en outbox: emitir_documento_fiscal + publicar_stock_shopify
  COMMIT

DESPUÉS del commit (nunca antes):
  7. publicar eventos en Redis → WebSocket
  8. enviar el ticket a la impresora (fire-and-forget: si falla, se reimprime)

verifica:  INV-V1..V12
eventos:   VentaCerrada
errores:   PagoIncompleto · VentaVacia · SesionCerrada · VentaYaCerrada
tiempo:    ≤ 800 ms p95 — NO incluye Siigo (ADR-002)
```

#### `AnularVenta`
```
entrada:   venta_id, motivo, token_autorizacion
verifica:  INV-V11 — sólo ventas del turno en curso, con autorización
hace:      reingresa stock · resta de caja · si ya hay documento fiscal emitido,
           marca el caso para nota crédito (Fase 2) en vez de emitirla
eventos:   VentaAnulada
```

### Clientes

```
CrearCliente        valida DocumentoIdentidad (DV del NIT) ANTES de aceptar.
                    No crea en Siigo todavía: eso ocurre perezosamente al emitir
                    el primer documento fiscal. Así crear un cliente funciona offline.
ActualizarCliente   si tiene siigo_customer_id, encola actualización en Siigo
```

### Sincronización

#### `SincronizarVentaOffline` ⭐
```
entrada:   lote de ventas completas (con líneas, pagos y timestamps del dispositivo)
salida:    por cada venta: aceptada | duplicada | rechazada(motivo)

hace, por venta:
  1. INSERT ... ON CONFLICT (venta_id) DO NOTHING  →  0 filas = duplicada, se responde OK
  2. valida que la sesión de caja siga abierta
     └─ si está cerrada ⇒ INV-C8: se acepta la venta, se marca `sesion_desfasada`
        y se notifica al supervisor. NUNCA se rechaza una venta real.
  3. aplica los mismos asientos de stock (puede quedar negativo ⇒ INV-I2 + alerta)
  4. encola documento fiscal con la FECHA ORIGINAL de la venta
  5. registra el desfase de reloj del dispositivo (R7)

garantía:  ejecutar el mismo lote 100 veces produce el mismo resultado que ejecutarlo 1 vez
```

---

## 3. Catálogo de consultas

| Consulta | Origen | Objetivo de latencia |
|---|---|---|
| `BuscarProducto(texto, tienda)` | **IndexedDB local** (servidor sólo como respaldo) | ≤ 50 ms |
| `StockMultitienda(variante_id)` | `stock_ubicacion` | ≤ 200 ms |
| `BuscarCliente(texto)` | `retail.clientes` + trigram | ≤ 150 ms |
| `HistorialCliente(cliente_id)` | `venta_resumen` | ≤ 300 ms |
| `VentasDelTurno(sesion_id)` | `venta_resumen` | ≤ 200 ms |
| `ArqueoEsperado(sesion_id)` | agregación de pagos | ≤ 200 ms |
| `TableroTiempoReal(tienda?)` | vista materializada + WS | ≤ 500 ms |
| `EstadoSincronizacion(tienda)` | outbox + documentos fiscales | ≤ 200 ms |
| `Auditoria(filtros)` | `retail.auditoria` particionada | ≤ 1 s |

### El buscador (es la consulta que define el producto)

La cajera escribe `93634 azul 30` y tiene que ver la prenda **antes de terminar de escribir**.

```
Estrategia:
  · el catálogo completo vive en IndexedDB (ADR-009)
  · índice invertido en memoria construido al arrancar la app: token → Set<varianteId>
  · normalización: minúsculas + sin tildes + sin guiones
  · tokens indexados: referencia, sku, nombre, color, talla, código de barras
  · consulta multi-token = intersección de conjuntos
  · orden: coincidencia exacta de código de barras > SKU exacto > referencia > texto
  · el stock se pinta desde el snapshot local y se refresca por WebSocket

El servidor expone /catalogo/buscar sólo para el primer arranque del dispositivo
y como respaldo si IndexedDB no está listo.
```

**Escaneo de código de barras:** el lector es un teclado HID. Se detecta por velocidad de
tecleo (< 30 ms entre caracteres) + Enter final. Coincidencia exacta ⇒ **la línea se agrega
sola**, sin un solo clic. Ese es el camino de los 30 segundos.

---

## 4. API HTTP

Prefijo `/api/retail`. Autenticación: el JWT existente (`security.py`) + cabeceras
`X-Dispositivo-Id` y `X-Idempotency-Key`.

### Ventas
```
POST   /ventas                          CrearVenta (idempotente por venta_id)
GET    /ventas/{id}
POST   /ventas/{id}/lineas              AgregarLinea
PATCH  /ventas/{id}/lineas/{lid}        ModificarCantidad
DELETE /ventas/{id}/lineas/{lid}        EliminarLinea
POST   /ventas/{id}/descuento           AplicarDescuento
POST   /ventas/{id}/cliente             AsignarCliente
POST   /ventas/{id}/pagos               RegistrarPago
DELETE /ventas/{id}/pagos/{pid}         EliminarPago
POST   /ventas/{id}/cerrar          ⭐  CerrarVenta
POST   /ventas/{id}/anular              AnularVenta
POST   /ventas/{id}/reimprimir          (auditado — INV de auditoría)
GET    /ventas/{id}/documento           estado fiscal, CUFE, PDF, XML
```

### Caja
```
POST   /caja/sesiones                   AbrirSesionCaja
GET    /caja/sesiones/actual
POST   /caja/sesiones/{id}/movimientos  RegistrarMovimientoCaja
POST   /caja/sesiones/{id}/arqueo       IniciarArqueo
POST   /caja/sesiones/{id}/conteo       DeclararConteo
POST   /caja/sesiones/{id}/cerrar       CerrarSesionCaja
GET    /caja/sesiones/{id}/informe
GET    /caja/historial?tienda&desde&hasta
```

### Catálogo · Inventario · Clientes
```
GET    /catalogo/sincronizar?desde=     ⭐ delta incremental para IndexedDB
GET    /catalogo/buscar?q=&tienda=      respaldo
GET    /catalogo/variantes/{id}
GET    /inventario/stock?variante&tienda
GET    /inventario/multitienda/{variante_id}
POST   /inventario/ajuste               (requiere permiso; genera asiento)
GET    /clientes/buscar?q=
POST   /clientes
PATCH  /clientes/{id}
GET    /clientes/{id}/historial
```

### Sincronización · Admin
```
POST   /sync/ventas                 ⭐ lote offline
GET    /sync/estado
POST   /sync/consecutivos/arrendar      pide un bloque nuevo
GET    /admin/tiendas · /admin/cajas · /admin/dispositivos
POST   /admin/dispositivos              registrar (credenciales de administradora)
DELETE /admin/dispositivos/{id}         revocar (robo/pérdida)
GET    /admin/medios-pago
GET    /admin/auditoria
GET    /admin/fiscal/pendientes         cola de documentos
POST   /admin/fiscal/{id}/reintentar
```

### WebSocket
```
WS /ws/retail/{tienda_id}     ← requiere JWT en el query o en el primer frame

servidor → cliente:
  stock.actualizado          { variante_id, ubicacion_id, disponible }
  venta.cerrada              { venta_id, numero, total, cajera }   (tablero)
  documento.emitido          { venta_id, numero, cufe }            (adjunta el CUFE al ticket)
  documento.fallido          { venta_id, error }
  caja.abierta / caja.cerrada
  autorizacion.solicitada    { venta_id, tipo, monto }             (al supervisor)
  sistema.aviso              { nivel, mensaje }

cliente → servidor:
  ping                       cada 20 s
  suscribir                  { canales: [...] }
```

---

## 5. Errores: contrato único

Un POS no puede mostrar un stack trace a la cajera con una clienta enfrente.

```json
{
  "error": "requiere_autorizacion",
  "mensaje": "Un descuento del 30% necesita aprobación de un supervisor.",
  "accion_sugerida": "pedir_autorizacion",
  "detalle": { "tope_del_rol": 10, "solicitado": 30 },
  "traza_id": "01JQ8X..."
}
```

| Campo | Para quién |
|---|---|
| `error` | Código estable para el frontend |
| `mensaje` | **La cajera.** En español, sin jerga, y dice qué hacer. |
| `accion_sugerida` | El frontend decide qué diálogo abrir |
| `detalle` | Diagnóstico |
| `traza_id` | Soporte: correlaciona con logs y auditoría |

> Precedente del repo que aplica aquí: los "errores de CORS" que en realidad eran un 500 sin
> cabeceras. Todo error del módulo retail sale por un manejador único que **siempre** emite
> las cabeceras de CORS, incluso en un 500.

---

## 6. Permisos

Se extiende `MODULOS_GRUPOS` (`usuarios.py:57`) con el grupo `retail`. No se inventa un RBAC
paralelo.

```python
MODULOS_GRUPOS = {
    ...,
    "retail": ["retail_venta", "retail_caja", "retail_inventario", "retail_admin"],
}
```

Y permisos finos, en la fila del usuario:

| Permiso | Cajera | Admin. tienda | Supervisor | Gerencia | Admin. sistema |
|---|:---:|:---:|:---:|:---:|:---:|
| Vender | ✅ | ✅ | ✅ | — | ✅ |
| Abrir/cerrar su caja | ✅ | ✅ | ✅ | — | ✅ |
| Descuento hasta | **10 %** | **20 %** | **35 %** | 100 % | 100 % |
| Autorizar descuento ajeno | — | ✅ | ✅ | ✅ | ✅ |
| Marcar obsequio | — | — | ✅ | ✅ | ✅ |
| Anular venta | — | ✅ | ✅ | ✅ | ✅ |
| Retiro / gasto de caja | — | ✅ | ✅ | ✅ | ✅ |
| Ver esperado antes del conteo | — | — | ✅ | ✅ | ✅ |
| Cerrar con descuadre | — | — | ✅ | ✅ | ✅ |
| Ajuste de inventario | — | — | ✅ | ✅ | ✅ |
| Ver todas las tiendas | — | — | ✅ | ✅ | ✅ |
| Reimprimir ticket | ✅* | ✅ | ✅ | ✅ | ✅ |
| Registrar/revocar dispositivo | — | ✅ | ✅ | — | ✅ |
| Ver auditoría | — | — | ✅ | ✅ | ✅ |

\* La reimpresión de la cajera se **audita siempre** (es una vía clásica de fraude: imprimir
dos veces y quedarse con una copia).

Los topes de descuento son **configurables por rol y por tienda** en base de datos, no
constantes en el código. Una campaña de fin de temporada no debería requerir un deploy.

---

## 7. Reglas transversales

| Regla | Aplicación |
|---|---|
| **Toda escritura es idempotente** | `X-Idempotency-Key` obligatoria en POST/PATCH. Repetir = misma respuesta, no un duplicado. |
| **La hora la pone el servidor** | El dispositivo manda su hora sólo como dato informativo. El desfase se registra (R7). |
| **Toda lectura de lista pagina y lo declara** | La respuesta trae `{ datos, total, pagina, completo: bool }`. Nunca un corte silencioso (H10). |
| **Todo comando escribe auditoría** | En la misma transacción. Si la auditoría falla, el comando falla. |
| **Ningún comando llama a un tercero** | Siigo y Shopify **sólo** desde el outbox worker. |
| **Las fechas se parsean con un helper** | Nunca `datetime.fromisoformat` directo: Python 3.10 en Railway revienta con las fracciones de segundo de Postgres (H11). |
