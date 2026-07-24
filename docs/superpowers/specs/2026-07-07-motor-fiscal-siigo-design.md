# MALE POSTVENTA IA — Motor fiscal (Sub-proyecto #2) · Spec de diseño

- **Fecha:** 2026-07-07
- **Depende de:** Sub-proyecto #1 (Postventa Core) — ya en `main`
- **Estado:** borrador para aprobación

---

## 1. Objetivo

Automatizar el **dolor #1** de MALE Denim: emitir la **nota crédito** y la **factura de reemplazo** en Siigo cuando se procesa un caso de postventa, cerrando el ciclo DIAN sin digitación manual.

## 2. Regla de negocio (confirmada con el fundador)

> **Se hace el mismo proceso en todos los casos:** nota crédito que anula el ítem original **+** factura nueva por el reemplazo.

Aplicado por tipo de caso:

| Tipo de caso | Nota crédito | Factura nueva |
|---|---|---|
| `cambio_talla` | ✅ del ítem original | ✅ del reemplazo |
| `cambio_ref` | ✅ del ítem original | ✅ del reemplazo (puede diferir el valor) |
| `garantia` | ✅ del ítem original | ✅ del reemplazo |
| `reembolso` | ✅ del ítem original | ❌ (no hay reemplazo que facturar) |
| `bono` | ✅ del ítem original | ❌ (el bono no es factura de venta) |

La NC acredita **solo el/los ítem(s) del caso**, no la factura completa (un pedido puede traer varias prendas y solo se devuelve una).

## 3. Configuración Siigo verificada (cuenta real de MALE)

Descubierta con el endpoint `/api/postventa/siigo/discovery` (Fase 0, ya en `main`):

| Concepto | ID | Notas |
|---|---|---|
| **Nota Crédito electrónica** | `11817` | activa, `ElectronicCreditNote`, `automatic_number: true` → Siigo asigna consecutivo |
| **Nota Crédito Proforma** | `27141` | `NoElectronic` → **NO va a la DIAN**. Se usa como MODO PRUEBA |
| **Factura de venta online** | `11810` | "Domicilios", activa, `ElectronicInvoice`. Es con la que se facturan las ventas Shopify |
| **Factura de venta "Cambios"** | `27154` | existe pero **inactiva**. Opción futura para numerar aparte las facturas de reemplazo |
| **IVA 19%** | `6352` | impuesto de producto |
| **Vendedor online** | `658` | "Dirty Jeans S.A.S" — el que Siigo pone en las facturas de domicilios |

`11817` tiene `cost_center: true` pero `cost_center_mandatory: false` → **no** es obligatorio enviarlo.

## 4. Enlace Shopify ↔ Siigo (Riesgo #1, CERRADO)

Confirmado con datos reales: las facturas online (`document.id == 11810`) guardan el pedido en **`observations`** con el formato:

```
"Orden Nº: 60112 - Medio de Pago: Mercado Pago Tarjetas"
```

Y el `60112` **es exactamente el número de pedido de Shopify** (`#60112`), verificado por el fundador.

**Algoritmo de búsqueda de la factura original:**
1. Tomar `shopify_order_name` del caso, extraer el número (quitar `#`).
2. Consultar `/v1/invoices` filtrando por `document_id=11810` y rango de fechas (fecha del pedido ± margen).
3. Match por regex sobre `observations`: `Orden\s*N[ºo°]?\s*:?\s*(\d+)` == número del pedido.
4. Devolver `id`, `name`, `customer.identification`, `items`, `total`.

Si no hay match → el caso NO avanza a emisión; se muestra el error al equipo (nunca se inventa una factura).

## 5. Arquitectura: conector `EmisorFiscal` pluggable

Requisito del objetivo comercial (vender a otras marcas): **Siigo no puede estar cableado**. Otras marcas usan Alegra, World Office, etc.

```
postventa (motor de casos)
        │
        ▼
  EmisorFiscal  ← interfaz (protocolo)
        │
        ├── EmisorSiigo      ← 1ª implementación (esta fase)
        ├── EmisorAlegra     ← futuro
        └── EmisorNulo       ← marcas sin facturación electrónica
```

**Interfaz mínima:**
```python
class EmisorFiscal(Protocol):
    def buscar_factura_original(self, *, numero_pedido: str,
                                fecha_ref: str) -> Optional[dict]: ...
    def construir_nota_credito(self, *, factura: dict, items: list[dict],
                               modo: str) -> dict: ...   # payload, NO emite
    def emitir(self, *, payload: dict, doc_kind: str) -> dict: ...
```

La selección del emisor se resuelve por marca (`BRAND_ID` → emisor), coherente con el multi-tenant ya montado.

## 6. Flujo de emisión (preview → confirmar → emitir)

Regla de oro ya aprobada: **nada se emite sin que un humano lo revise.**

```
1. Equipo aprueba el caso (estado 'aprobado')
2. [PREVIEW]  Sistema busca la factura original y ARMA el payload de la NC.
              Lo muestra en pantalla: cliente, ítems, IVA calculado, total.
              Se guarda en postventa_fiscal.payload_snapshot con status='pendiente'.
              → NO se envía nada a Siigo todavía.
3. [CONFIRMAR] El equipo revisa y presiona "Emitir nota crédito".
4. [EMITIR]   POST a Siigo. Se guardan siigo_document_id, siigo_document_number,
              status='emitido'. Timeline + WhatsApp automáticos.
              Estado del caso → 'nota_credito_emitida'.
5. Si hay reemplazo → se repite preview/confirmar/emitir para la FACTURA.
              Estado del caso → 'factura_emitida'.
6. Si Siigo rechaza → status='error' + error_detail. El caso NO avanza.
              El equipo corrige y reintenta desde el payload_snapshot.
              NUNCA se reintenta automático un documento fiscal.
```

## 7. Modo prueba (gate de 20 casos)

En vez de un sandbox aparte, se usa la propia cuenta con un **tipo de documento no electrónico**:

| Modo | NC que se usa | ¿Va a la DIAN? |
|---|---|---|
| `prueba` (default inicial) | `27141` Proforma | ❌ No |
| `produccion` | `11817` Electrónica | ✅ Sí |

Controlado por env var `SIIGO_POSTVENTA_MODO` (`prueba` | `produccion`), reversible.

**Criterio de salida (acordado con el fundador):**
```
[ ] 20 casos completos en modo prueba, sin error fiscal
[ ] Cubiertos los 3 flujos: cambio_talla, cambio_ref (con dif. de precio), reembolso/bono
[ ] Montos e IVA cuadran contra la factura original en cada caso
[ ] Idempotencia verificada (imposible emitir 2 NC al mismo caso)
[ ] Cada caso deja payload_snapshot + timeline completo
```
Solo con todo verde se cambia la env var a `produccion`.

## 8. Persistencia

Se reutiliza la tabla `postventa_fiscal` (ya creada en el Sub-proyecto #1):
`case_id, doc_kind ('nota_credito'|'factura'), siigo_invoice_ref, siigo_document_id, siigo_document_number, amount, status ('pendiente'|'emitido'|'error'), error_detail, payload_snapshot (jsonb), brand_id`.

**Idempotencia:** si ya existe una fila con `doc_kind='nota_credito'` y `status='emitido'` para el caso → se bloquea una segunda emisión.

## 9. Cálculo de montos

- Los precios de `postventa_items` están **sin IVA** (COP, `numeric(12,2)`).
- El IVA (19%, id `6352`) lo aplica el emisor al construir el payload.
- La NC acredita el valor del ítem original; la factura nueva cobra el reemplazo.
- La **diferencia de precio** (`price_difference`, ya calculada en el core) se refleja en la factura nueva, no en la NC.

## 10. Fuera de alcance de esta fase

- Emisión de **gift cards / bonos** reales (solo se registra el valor; la emisión del bono es Fase 5).
- Reembolso de dinero real a la pasarela (Wompi/MercadoPago) — solo se emite la NC.
- Reactivar el tipo "Factura de venta Cambios" (`27154`) — se evalúa después.
- Otros emisores (Alegra, World Office) — la interfaz queda lista, la implementación no.

## 11. Riesgos

| # | Riesgo | Mitigación |
|---|---|---|
| 1 | Emisión DIAN irreversible | Preview + confirmación humana + modo prueba + gate de 20 casos |
| 2 | Factura original no encontrada | El caso no avanza; error explícito. Nunca se inventa |
| 3 | Rechazo de validación DIAN (IVA, NIT, códigos de producto) | `error_detail` + `payload_snapshot` + reintento manual |
| 4 | Rate limit Siigo (429) | Backoff existente en `siigo_get`; se replica en el POST |
| 5 | Productos del caso sin código en Siigo | Validar en el preview; bloquear antes de emitir |
| 6 | Doble emisión | Guard de idempotencia sobre `postventa_fiscal` |
