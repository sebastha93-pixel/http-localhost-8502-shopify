# MALE'DENIM OS — Módulo `producción` · Fase 1

**Estado:** Diseño en revisión (sin implementar)
**Última actualización:** 2026-06-26
**Alcance Fase 1:** Inventario de tela por lote + trazabilidad corte → confección, con control de precosteo/autorización por referencia.

---

## 1. Resumen

Módulo nuevo para gestionar el inventario de insumos (tela) y los procesos productivos de corte y confección. Se alimenta de Google Sheets (órdenes de despacho de la textilera y precosteo de referencias), permite captura por lector de código de barras, y mantiene el inventario al día descontando metros cortados.

**Fuente de verdad:** Supabase (Postgres), igual que el resto del OS.
**Google Sheets** alimenta dos cosas: las órdenes de despacho y el precosteo de referencias.

---

## 2. Decisiones cerradas

| Tema | Decisión |
|---|---|
| Atributos de tela | metros, tono*, ancho, fecha ingreso, fecha de corte |
| Unidad de inventario | Un lote por orden de despacho |
| Etiqueta | Térmica Zebra, 10×10 cm, código de barras Code128 |
| Modelo de corte | Trazo + capas (completo) |
| Curva de tallas | 4-6-8-10-12-14-16 |
| Rendimiento teórico | largo del trazo ÷ prendas del trazo |
| Consumo real | lo ingresa el cortador; el sistema calcula la **diferencia %** |
| Merma | % o metros (ambos disponibles) |
| Remisión | consecutivo + fecha de recogida; agrupa varios cortes |
| Consecutivos | `TELA-2026-0001`, `CORTE-2026-0001`, `REM-2026-0001` |
| Costo de tela | viene en el Sheet de despacho (COP) |
| Conciliación | registra lo real, marca diferencia, permite parciales **con autorización (admin)** |
| Roles | admin + operador; autorización de precosteo solo con permiso especial |
| Precosteo | todos los componentes + foto; inmutable tras firma; una vez por referencia |
| Corte sin autorización | advierte + correo al responsable |

\* *El campo tono se guarda pero sin lógica ni validaciones en Fase 1.*

---

## 3. Modelo de datos (Supabase)

### `ordenes_despacho` — sincronizada desde el Sheet
`numero_orden`, `fecha_despacho`, `textilera`, `tipo_tela`, `tono`, `ancho`,
`metros_despachados`, `costo_metro` (COP), `doc_textilera`, `observaciones`,
`estado` (pendiente / recibida_parcial / recibida_completa / conciliada), `sheet_row`.

### `lotes_tela` — unidad de inventario
`codigo` (TELA-2026-0001), `nombre` (manual), `orden_despacho_id`,
`tipo_tela`, `tono`, `ancho`, `costo_metro`,
`metros_recibidos`, `metros_disponible`,
`fecha_ingreso`, `fecha_ultimo_corte`,
`estado` (disponible / en_corte / agotado / con_novedad).

### `referencias_precosteo` — sincronizada del Sheet + autorizada en el módulo
`codigo_referencia`, `nombre`, `foto_url`,
`consumo_tela_prenda` (m), `costo_tela`,
`insumos` (JSON: lista de insumo + costo),
`costo_confeccion`, `costo_lavanderia`,
`costo_total_prenda`, `precio_venta`, `margen`,
`estado` (borrador / autorizada),
`autorizada_por`, `fecha_autorizacion`, `bloqueada` (bool).
**Regla:** al autorizar → `bloqueada = true` y ningún campo se puede modificar.

### `confeccionistas`
`nombre`, `telefono`, `direccion`, `activo`.

### `cortes`
`codigo` (CORTE-2026-0001), `lote_tela_id`, `referencia_id`,
`largo_trazo`, `prendas_por_trazo`, `curva_trazo` (JSON por talla),
`num_capas`, `metros_consumidos` (= largo_trazo × capas),
`merma_tipo` (% / metros), `merma_valor`,
`prendas_estimadas` (= prendas_por_trazo × capas),
`rendimiento_teorico` (= largo_trazo ÷ prendas_por_trazo),
`consumo_real_cortador`, `diferencia_pct` (calculada),
`autorizada_al_cortar` (bool, snapshot del estado de la referencia),
`confeccionista_id`, `fecha`, `usuario`.

### `remisiones` + `remision_items`
**remisiones:** `consecutivo` (REM-2026-0001), `confeccionista_id`,
`fecha_recogida`, `estado` (generada / recogida), `pdf_url`.
**remision_items:** `remision_id`, `corte_id`.

### `movimientos_inventario` — libro mayor auditable
`lote_tela_id`, `tipo` (ingreso / corte / ajuste), `metros` (±),
`doc_ref`, `usuario`, `fecha`, `nota`.

### `usuarios` (existente) — nuevo permiso
`puede_autorizar_precosteo` (flag) — habilita la firma de autorización.

---

## 4. Flujo operativo

### A. Sincronizar despachos
Lee la hoja "Órdenes de Despacho" → llena/actualiza `ordenes_despacho`.

### B. Ingreso de tela
1. Seleccionas la orden de despacho.
2. Pones el nombre del lote, registras los **metros reales recibidos**.
3. Si difieren del despacho → se marca la **diferencia** y el lote queda `con_novedad`.
4. Si es **entrega parcial** → la orden queda `recibida_parcial`; cerrarla requiere **autorización de admin**.
5. Se genera el `codigo` + **etiqueta Zebra 10×10** imprimible.
6. Movimiento `ingreso` (+metros).

### C. Precosteo y autorización de referencia
1. La hoja "Precosteo" alimenta `referencias_precosteo` como `borrador`.
2. Un usuario con `puede_autorizar_precosteo` revisa (incluida la **foto**) y **autoriza**.
3. Al autorizar → queda **bloqueada** (inmutable) y registra quién y cuándo.
4. Una vez autorizada, el módulo **congela** ese precosteo (los cambios posteriores del Sheet no la tocan).

### D. Corte
1. Escaneas el código del lote (lector → input con autofocus + Enter).
2. Eliges la **referencia**.
   - Si la referencia **no está autorizada** → **advierte** y **envía correo al responsable** (permite continuar marcado como sin autorización).
3. Ingresas largo de trazo, curva de tallas y nº de capas.
4. El sistema calcula: prendas estimadas, metros consumidos, rendimiento teórico.
5. El cortador ingresa su **consumo real** → **diferencia % (eficiencia)**.
6. Registras merma (% o metros).
7. Descuenta metros del lote (movimiento `corte`).

### E. Remisión al confeccionista
1. Agrupas uno o varios cortes del mismo confeccionista.
2. Asignas consecutivo y **fecha de recogida**.
3. Genera documento imprimible / PDF.

### F. Inventario
Los metros disponibles siempre cuadran vía `movimientos_inventario` (ingreso − corte ± ajuste).

---

## 5. Tablero (KPIs y alertas)

- **Stock mínimo por tipo/tono** — alerta cuando los metros bajan de un mínimo configurable.
- **Eficiencia de corte** — diferencia % teórico vs real por corte / referencia / cortador.
- **Telas paradas / antigüedad** — lotes con muchos días sin movimiento.
- **Valor del inventario** — metros disponibles × costo/metro, total y por tipo.

---

## 6. Estructura propuesta del Google Sheet

### Hoja "Órdenes de Despacho"
`numero_orden · fecha_despacho · textilera · tipo_tela · tono · ancho · metros_despachados · costo_metro · doc_textilera · observaciones`

### Hoja "Precosteo Referencias"
`codigo_referencia · nombre · foto (link Drive) · consumo_tela_prenda · costo_tela · insumos · costo_confeccion · costo_lavanderia · costo_total_prenda · precio_venta · margen`

---

## 7. Arquitectura técnica

- **Backend:** `backend/services/produccion.py` + `backend/api/produccion.py` (prefijo `/api/produccion`), registrado en `backend/main.py`.
- **Sincronización Sheets:** cuenta de servicio de Google (compartir ambas hojas con el correo de servicio).
- **Fotos:** Supabase Storage o link de Drive (a definir).
- **Correo:** canal de notificaciones (SMTP / Resend / etc., a definir).
- **Frontend:** `frontend/app/produccion` con pestañas:
  **Inventario · Ingreso · Precosteo · Corte · Remisiones · Confeccionistas · Tablero**.
- **Código de barras:** Code128 generado en el navegador (JsBarcode) para etiqueta Zebra; layout ZPL o PDF 10×10.
- **Esquema SQL** en `SUPABASE_PRODUCCION.sql` (estilo `SUPABASE_USUARIOS.sql`).

---

## 8. Fase 2 (más adelante)

- **Devolución del confeccionista** — recibir prendas terminadas, cerrar la remisión, cuadrar prendas cortadas vs entregadas.
- Enlazar `referencia` con el catálogo de Shopify (desplegable real).
- Otros insumos (botones, cremalleras, hilos) como inventario propio.
- Integración del costo de confección con el módulo de finanzas.

---

## 9. Pendientes por confirmar

1. **Foto de la referencia:** ¿se sube dentro del módulo o llega como link de Drive en el Sheet?
2. **Canal de correo** para las notificaciones: ¿ya tienes uno (SMTP / Resend) o lo configuramos?
3. **Permiso de autorización:** ¿flag por usuario (`puede_autorizar_precosteo`) o lo restringimos a admin?
4. **Inmutabilidad vs Sheet:** tras autorizar, el módulo congela la referencia e ignora cambios posteriores del Sheet. ¿Correcto?
