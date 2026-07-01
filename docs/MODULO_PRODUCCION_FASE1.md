# MALE'DENIM OS — Módulo `producción` · Fase 1

**Estado:** Diseño en revisión (sin implementar)
**Última actualización:** 2026-06-26
**Alcance Fase 1:** Inventario de tela **por rollo** + Orden de Corte (formato) + trazabilidad corte → confección, con control de precosteo/autorización por referencia.

---

## 1. Resumen

Módulo nuevo para gestionar el inventario de insumos (tela) y los procesos productivos de corte y confección. Se alimenta de las hojas de entrega de las textileras (transcripción en el módulo) y del precosteo de referencias (Google Sheet), permite captura por lector de código de barras, y mantiene el inventario al día descontando metros cortados **por rollo**.

**Fuente de verdad:** Supabase (Postgres), igual que el resto del OS.
**Razón social cliente:** Dirty Jeans S.A.S.

### Realidad de las hojas de las textileras (revisadas)
Cada entrega trae **muchos rollos**, listados rollo por rollo: número de rollo/serial, metros, lote de fábrica, tono y referencia/descripción de la tela. Formatos vistos:
- **Primatela** — hoja de entrega: 15 rollos, ITEM/REFERENCIA/Nro Rollo/LOTE/metros.
- **Contacto** — lista de empaque: 34 seriales, con columna **TONO** (A/B) y referencia/descripción.
- **Stilotex** — consulta por serial: lote por serial, tonos 653/999 (verde/negro).
- **Megatex** — factura electrónica: **solo total en metros**, sin desglose por rollo (caso especial).

Por eso la **unidad de inventario es el rollo**, cada uno con su propio código de barras.

---

## 2. Decisiones cerradas

| Tema | Decisión |
|---|---|
| Unidad de inventario | **El rollo individual** (cada uno con código de barras propio) |
| Atributos por rollo | nº rollo/serial, metros, lote de fábrica, tono, referencia/descripción de tela, ancho, fecha ingreso |
| Tono | **Se controla por rollo** (las hojas lo traen) |
| Captura del ingreso | Transcripción manual fila por fila; cada rollo genera su código + etiqueta |
| Etiqueta | Térmica Zebra, 10×10 cm, código de barras Code128, **una por rollo** |
| Caso Megatex (sin rollos) | Se registra como un rollo único con el total de metros |
| Orden de Corte | **Documento en modo formato** con indicaciones; luz verde al cortador |
| Modelo de corte | Trazo + capas (completo) |
| Curva de tallas | 4-6-8-10-12-14-16 |
| Rendimiento teórico | largo del trazo ÷ prendas del trazo |
| Consumo real | lo ingresa el cortador; el sistema calcula la **diferencia %** |
| Merma | % o metros (ambos disponibles) |
| Remisión | consecutivo + fecha de recogida; agrupa varias órdenes de corte |
| Consecutivos | `ING-2026-0001`, `ROLLO-2026-000001`, `OC-2026-0001`, `REM-2026-0001` |
| Costo de tela | viene en el documento de la textilera (COP) |
| Conciliación | registra lo real, marca diferencia, permite parciales **con autorización (admin)** |
| Roles | admin + operador; autorización de precosteo y de orden de corte solo con permiso |
| Precosteo | todos los componentes + foto (subida en el módulo); inmutable tras firma; una vez por referencia |
| Autorización ↔ Sheet | se autoriza en la app y se escribe de vuelta en el Sheet (sync bidireccional) |
| Corte sin autorización | advierte; correo al responsable en fase posterior |

---

## 3. Modelo de datos (Supabase)

### `ordenes_ingreso` — cabecera de la entrega de la textilera
`numero_ingreso` (ING-2026-0001), `textilera`, `nit_textilera`,
`numero_documento` (remisión/factura/lista empaque de la textilera),
`tipo_documento` (remision / factura / lista_empaque / consulta),
`fecha`, `orden_compra`, `total_rollos`, `total_metros`,
`estado` (pendiente / recibida_parcial / recibida_completa / conciliada), `observaciones`.

### `rollos_tela` — **unidad de inventario**
`codigo_interno` (ROLLO-2026-000001), `barcode`, `orden_ingreso_id`,
`numero_rollo` (el de la textilera), `serial`, `lote_fabrica`, `tono`,
`referencia_tela` (código de la textilera), `descripcion_tela` (ej. SANDDENIM, FUNKY),
`ancho`, `costo_metro`,
`metros_inicial`, `metros_disponible`,
`fecha_ingreso`, `fecha_ultimo_corte`,
`estado` (disponible / en_corte / agotado / con_novedad).

### `referencias_precosteo` — cabecera del precosteo (formato)
`codigo_referencia` (ej. 14500-1), `nombre` (ej. SKINNY OSCURO), `tela`, `color`, `foto_url`,
`iva_pct` (19), `costo_total_sin_iva`, `costo_total_con_iva`,
`precio_sugerido_venta`, `margen`,
`estado` (borrador / autorizada), `autorizada_por`, `fecha_autorizacion`, `bloqueada` (bool).
**Regla:** al autorizar → `bloqueada = true`; cabecera e ítems quedan inmutables.

### `precosteo_items` — líneas del precosteo (una por concepto)
`referencia_id`, `categoria` (DIRTY JEANS / MP / PROCESO EN MP / PROCESO / INSUMO CONFECCION / INSUMO EMPAQUE / INSUMO TERMINACION / GASTOS FIJOS),
`item` (ej. PRECIO TELA, FORRO, CONFECCION, CIERRE, BOTON, REMACHE…),
`valor_unitario`, `cantidad`, `iva`,
`total_sin_iva` (= valor_unitario × cantidad), `total_con_iva` (= total_sin_iva + iva).
*Modelado a partir del formato real 14500-1.*

### `ordenes_corte` — **el formato que da luz verde al cortador**
`consecutivo` (OC-2026-0001), `referencia_id`, `tono`,
`largo_trazo`, `prendas_por_trazo`, `curva_trazo` (JSON por talla 4-16), `num_capas`,
`prendas_estimadas` (= prendas_por_trazo × capas),
`metros_consumidos` (= largo_trazo × capas),
`rendimiento_teorico` (= largo_trazo ÷ prendas_por_trazo),
`consumo_real_cortador`, `diferencia_pct` (calculada),
`merma_tipo` (% / metros), `merma_valor`,
`indicaciones` (texto libre para el cortador),
`responsable`, `fecha_limite`,
`estado` (borrador / autorizada / en_proceso / cortada),
`autorizada_por`, `fecha_autorizacion`,
`confeccionista_id`, `usuario`, `fecha`.

### `orden_corte_rollos` — rollos asignados a la orden de corte
`orden_corte_id`, `rollo_id`, `metros_usados`.
(De aquí sale el descuento de inventario por rollo.)

### `confeccionistas`
`nombre`, `telefono`, `direccion`, `activo`.

### `remisiones` + `remision_items`
**remisiones:** `consecutivo` (REM-2026-0001), `confeccionista_id`, `fecha_recogida`,
`estado` (generada / recogida), `pdf_url`.
**remision_items:** `remision_id`, `orden_corte_id`.

### `movimientos_inventario` — libro mayor auditable (por rollo)
`rollo_id`, `tipo` (ingreso / corte / ajuste), `metros` (±),
`doc_ref`, `usuario`, `fecha`, `nota`.

### `usuarios` (existente) — nuevos permisos
`puede_autorizar_precosteo`, `puede_autorizar_corte` (flags).

---

## 4. Flujo operativo

### A. Ingreso de tela (copiar la orden de la textilera)
1. Creas la **orden de ingreso** (cabecera): textilera, número de documento, fecha, orden de compra.
2. Transcribes **rollo por rollo** la hoja de entrega: nº de rollo, serial, lote de fábrica, tono, referencia/descripción, ancho, metros, costo/metro.
3. Al guardar cada rollo, el sistema genera su `codigo_interno` + `barcode` y habilita **imprimir la etiqueta Zebra 10×10** (botón "imprimir" por rollo o impresión masiva de todos los rollos del ingreso).
4. **Conciliación:** compara el total de metros transcritos vs el documento; si hay diferencia, marca el ingreso/rollo `con_novedad`. Entregas **parciales** se permiten contra la misma orden **con autorización (admin)**.
5. Megatex (sin rollos) → se registra como un rollo único con el total.
6. Movimiento `ingreso` (+metros) por cada rollo.

### B. Precosteo y autorización de referencia
1. La hoja "Precosteo" alimenta `referencias_precosteo` como `borrador`.
2. La **foto** de la referencia se sube dentro del módulo (Supabase Storage).
3. Un usuario con `puede_autorizar_precosteo` revisa la foto y el costeo y **autoriza** desde la app.
4. Al autorizar → queda **bloqueada** (inmutable), registra quién y cuándo, y **escribe la autorización de vuelta en el Sheet**.
5. Una vez autorizada, el módulo **congela** ese precosteo (cambios posteriores del Sheet no la tocan).

### C. Orden de Corte (formato — luz verde al cortador)
1. Creas la orden de corte: eliges la **referencia** (debe estar autorizada; si no, advierte) y el **tono**.
2. **Asignas los rollos** (escaneando su código de barras) de los que saldrá la tela.
3. Defines el **trazo** (largo), la **curva de tallas** y el **nº de capas** → el sistema calcula prendas estimadas, metros a consumir y rendimiento teórico.
4. Escribes las **indicaciones** para el cortador (sentido de tela, defectos a evitar, notas de calidad), el **responsable** y la **fecha límite**.
5. Un usuario con `puede_autorizar_corte` **firma/autoriza** → estado `autorizada` = **luz verde**. Se imprime el **formato de Orden de Corte**.
6. El cortador ejecuta y reporta el **consumo real** → el sistema calcula la **diferencia % (eficiencia)** y la **merma**; estado `cortada`.
7. Descuenta los metros de los **rollos asignados** (movimiento `corte` por rollo).

### D. Remisión al confeccionista
1. Agrupas una o varias órdenes de corte del mismo confeccionista.
2. Asignas consecutivo y **fecha de recogida**.
3. Genera documento imprimible / PDF.

### E. Inventario (vista unificada por nombre)
- El inventario se **unifica por nombre de tela** (descripción): por cada tela muestra el **nº de rollos**, los metros recibidos, cortados y **disponibles**.
- Un **desplegable** permite seleccionar una tela por nombre y ver su cantidad de rollos y metros disponibles; al expandir, se ven los rollos individuales con su código de barras.
- En la **Orden de Corte** se **elige la tela por nombre** (desplegable), se ven los metros disponibles y luego se asignan los rollos específicos.
- Al cortar, el **descuento es automático** sobre los rollos asignados; los metros disponibles por rollo y el resumen por nombre siempre cuadran vía `movimientos_inventario` (ingreso − corte ± ajuste).

---

## 5. Tablero (KPIs y alertas)

- **Stock mínimo por tipo/tono** — alerta cuando los metros disponibles de un tipo o tono bajan de un mínimo configurable.
- **Eficiencia de corte** — diferencia % teórico vs real por orden de corte / referencia / cortador.
- **Telas paradas / antigüedad** — rollos con muchos días sin movimiento.
- **Valor del inventario** — metros disponibles × costo/metro, total y por tipo/tono.

---

## 6. Documentos imprimibles

- **Etiqueta de rollo** (Zebra 10×10): código de barras Code128 + código interno, descripción/tono, ancho, metros, lote de fábrica, fecha.
- **Orden de Corte** (formato): referencia + foto, tono, rollos asignados, trazo/curva/capas, prendas estimadas, indicaciones, responsable, fecha límite, firma de autorización.
- **Remisión** (al confeccionista): confeccionista, órdenes de corte incluidas, prendas, fecha de recogida, consecutivo.

---

## 6b. Formatos y almacenamiento (reset a 0)

Tres documentos funcionan como **formato** (pantalla de captura): **Orden de Ingreso**, **Precosteo** y **Orden de Corte**. El patrón es el mismo en los tres:

1. Llenas el formato.
2. Al **firmar / dar luz verde / guardar**, el sistema:
   - **Guarda un registro permanente** en su tabla de Supabase (con consecutivo, quién firmó y la fecha; inmutable).
   - **Limpia el formato y lo deja en 0**, listo para el siguiente.
3. Lo firmado queda en el **histórico** y nunca se pierde; el formato vacío es solo la "hoja en blanco" del próximo.

| Formato | Se guarda en (histórico) | Qué lo dispara |
|---|---|---|
| Orden de Ingreso | `ordenes_ingreso` + `rollos_tela` | Guardar el ingreso |
| Precosteo | `referencias_precosteo` | Firma de autorización |
| Orden de Corte | `ordenes_corte` + `orden_corte_rollos` | Luz verde (autorización) |

**En el módulo (app):** automático — el botón guarda en la base de datos y resetea el formato.
**En el Google Sheet:** se replica con un botón + Apps Script que copia el formato a una hoja **"Histórico"** y limpia los campos (las fórmulas solas no pueden archivar ni limpiar).

---

## 6c. Informe de Corte e Inventario de Insumos

**Informe de Corte** (`Informe de Corte`) — alimentado por `Histórico Cortes` (ampliado con prendas, rendimiento teórico, consumo real, metros teóricos/reales). Resume promedios **por referencia** y **por cortador**: rendimiento teórico vs real, diferencia %, y la **diferencia de gasto en metros** (metros reales − teóricos). Sirve para afinar la precisión del manejo de tela y detectar quién/qué referencia desperdicia.

La **Orden de Corte** calcula solo: prendas estimadas (= prendas/trazo × capas), rendimiento teórico (= largo trazo ÷ prendas/trazo) y diferencia % (real vs teórico). Al firmar, archiva todo en `Histórico Cortes` y descuenta el consumo real del inventario.

**Inventario de Insumos** (`Inventario de Insumos`) — insumos del precosteo (cierre, marquilla, botón, remache, garra, cremallera, hilo, etiqueta, pretinera, etc.) con stock inicial, entradas, salidas (= SUMIF de remisiones), stock disponible y alerta de stock mínimo.

**Remisión de Insumos** (`Remisión de Insumos` + log `Remisiones Insumos`) — formato para entregar insumos a **confeccionista** o **terminación** (destino seleccionable). Al generarla, archiva cada línea y **descuenta del stock**.

---

## 7. Estructura del Google Sheet

> El ingreso/rollos se capturan **en el módulo** (transcripción). El Sheet se usa para el **Precosteo**; la hoja de ingreso queda como plantilla de apoyo/pegado.

### Hoja "Órdenes de Ingreso" (nivel rollo)
`textilera · numero_documento · tipo_documento · fecha · orden_compra · numero_rollo · serial · lote_fabrica · tono · referencia_tela · descripcion_tela · ancho_cm · metros · costo_metro_cop · codigo_interno (sistema) · barcode (sistema)`

### Hoja "Precosteo (formato)"
Espejo del formato real 14500-1: cabecera (REF, nombre, tela, color, foto) + tabla de líneas
`categoria · item · valor_unitario · cantidad · iva · total_sin_iva (fórmula) · total_con_iva (fórmula)`,
y al pie `COSTO TOTAL (sin/con IVA)` y `PRECIO SUGERIDO DE VENTA` (por margen).
Al firmar, la fila resumen se archiva en **Histórico Precosteo** y el formato se limpia.

---

## 8. Arquitectura técnica

- **Backend:** `backend/services/produccion.py` + `backend/api/produccion.py` (prefijo `/api/produccion`), registrado en `backend/main.py`.
- **Sincronización Sheets:** cuenta de servicio de Google. Bidireccional en la autorización de precosteo.
- **Fotos:** se suben en el módulo → Supabase Storage.
- **Correo:** se configura en una fase posterior; por ahora el corte sin autorización solo advierte en pantalla.
- **Frontend:** `frontend/app/produccion` con pestañas:
  **Inventario (rollos) · Órdenes de Ingreso · Precosteo · Órdenes de Corte · Remisiones · Confeccionistas · Tablero**.
- **Código de barras:** Code128 generado en el navegador (JsBarcode); etiqueta Zebra 10×10 (ZPL o PDF) por rollo.
- **Esquema SQL** en `SUPABASE_PRODUCCION.sql` (estilo `SUPABASE_USUARIOS.sql`).

---

## 9. Fase 2 (más adelante)

- **Devolución del confeccionista** — recibir prendas terminadas, cerrar la remisión, cuadrar cortadas vs entregadas.
- Enlazar `referencia_tela` y `referencia` de prenda con el catálogo de Shopify.
- **OCR con visión IA** de las hojas de las textileras (Claude/Gemini/Document AI) para leer la orden de despacho por foto y **auto-cargar los rollos** — construir en el backend por la heterogeneidad de formatos (Primatela, Contacto, Stilotex, Megatex).
- **Notificaciones al firmar**: correo (activo vía Apps Script) y **WhatsApp** (requiere proveedor: Meta Cloud API / Twilio / Wati).
- Otros insumos (botones, cremalleras, hilos) como inventario propio.
- Integración del costo de confección con el módulo de finanzas.

---

## 10. Decisiones resueltas (pendientes anteriores)

1. **Foto de la referencia** → se sube en el módulo (Supabase Storage). ✅
2. **Canal de correo** → fase posterior; por ahora solo advertencia en pantalla. ✅
3. **Permiso de autorización** → flags `puede_autorizar_precosteo` / `puede_autorizar_corte` gestionados en la app; el resultado del precosteo se marca de vuelta en el Sheet. ✅
4. **Inmutabilidad vs Sheet** → tras autorizar, se congela la referencia. ✅
5. **Unidad de inventario** → el rollo individual, con código de barras propio. ✅
6. **Tono** → se controla por rollo. ✅
