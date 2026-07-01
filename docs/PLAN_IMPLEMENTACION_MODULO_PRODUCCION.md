# MALE'DENIM OS — Plan de implementación del módulo `producción`

**Objetivo:** llevar el prototipo validado en Google Sheets a un módulo profesional dentro de MALE'DENIM OS.
**Stack:** FastAPI (backend) · Supabase/Postgres (datos) · Next.js (frontend) — el que ya usas.
**Uso:** móvil-first en el taller (escáner) + escritorio para admin/diseñador.
**Alcance MVP:** flujo completo (ingreso → precosteo → orden de corte → informe → insumos/remisión).
**Referencia funcional:** `docs/MODULO_PRODUCCION_FASE1.md` (define reglas y campos) + `sheets/Produccion_Sheet_Plantilla.xlsx` (prototipo).

---

## 1. Principios de diseño (profesional y fácil de usar)

- **Un solo lugar de captura.** Supabase es la fuente única de verdad. Nada de doble digitación.
- **Escáner primero.** En el taller, el flujo arranca escaneando; el sistema autocompleta el resto. Mínimos toques, campos grandes, teclado numérico donde aplica.
- **Estados claros.** Cada documento muestra su estado (borrador / autorizado / cortado…) con color y etiqueta. El usuario siempre sabe qué sigue.
- **Validaciones que evitan errores.** No se puede cortar una referencia sin precosteo autorizado; no se descuenta más tela de la disponible; los formatos avisan antes de guardar.
- **Roles = vistas distintas.** Bodega ve ingreso e inventario; cortador ve órdenes de corte; diseñador precostea y autoriza; admin ve todo + informes.
- **Trazabilidad total.** Todo documento firmado queda congelado con sus ítems (ya definido en el Sheet).
- **Marca aplicada.** Paleta y tipografía Male Denim (DEEP INK, STEEL BLUE, Montserrat) y logo, como en la plantilla.

---

## 2. Arquitectura (cómo encaja en MALE'DENIM OS)

```
backend/
  api/produccion.py          # rutas /api/produccion/* (router registrado en main.py)
  services/produccion.py     # lógica + acceso Supabase (patrón de services/clientes.py)
  services/produccion_ocr.py # OCR de orden de despacho (visión IA)
  core/security.py           # reutiliza require_role / CurrentUser (ya existe)
frontend/app/produccion/
  page.tsx                   # panel/inicio del módulo
  ingreso/  inventario/  precosteo/  corte/  informe/  insumos/  remisiones/
  components/                # escáner, tarjetas de estado, tablas
SUPABASE_PRODUCCION.sql      # esquema (estilo SUPABASE_USUARIOS.sql)
```

- Se **reutiliza la autenticación y los roles** existentes (login, JWT, `require_role`).
- El backend expone una API REST; el frontend la consume (igual que tus módulos actuales).
- Despliegue en Railway (backend) + Vercel (frontend), como ya tienes.

---

## 3. Modelo de datos (Supabase)

> Detalle de campos en `MODULO_PRODUCCION_FASE1.md`. Resumen de tablas:

**Inventario de tela**
- `ordenes_ingreso` — cabecera de la entrega de la textilera.
- `rollos_tela` — unidad de inventario (código interno, barcode, lote, tono, metros, estado).
- `movimientos_inventario` — libro mayor (ingreso / corte / ajuste) por rollo.

**Precosteo**
- `referencias_precosteo` — cabecera + totales + estado/autorización (inmutable al firmar).
- `precosteo_items` — líneas (categoría, item, valor, cantidad, IVA, totales) → trazabilidad.

**Corte**
- `ordenes_corte` — planeación (consecutivo, tela, responsable, estado). No descuenta inventario.
- `orden_corte_referencias` — referencia + curva por talla + cantidad + rend. teórico + consumo teórico.
- `cierres_corte` — consumo real capturado al cerrar (alimenta el cruce del informe).

**Insumos**
- `insumos` — catálogo + stock (mínimo, disponible, alerta).
- `remisiones_insumos` + `remision_insumo_items` — entregas a confeccionista/terminación (descuentan stock).

**Confección**
- `confeccionistas`, `remisiones` (entrega de corte al confeccionista).

**Usuarios** (tabla existente) — flags `puede_autorizar_precosteo`, `puede_autorizar_corte`.

Todas las tablas: `id` uuid, `created_at`, `created_by`, `updated_at`. Índices por `estado`, `referencia`, `tela`, fechas.

---

## 4. Endpoints API (`/api/produccion`)

**Ingreso / inventario**
- `POST /ingreso` — crea orden de ingreso + rollos (o `POST /ingreso/ocr` con foto → OCR).
- `GET /rollos?tela=&estado=` · `GET /inventario/resumen` (unificado por nombre + disponible).
- `POST /rollos/{id}/etiqueta` — genera barcode/etiqueta (PDF/ZPL).
- `POST /movimientos` — ajuste manual.

**Precosteo**
- `POST /precosteo` (borrador) · `GET /precosteo/{id}` · `POST /precosteo/{id}/firmar` (rol requerido → congela + notifica).
- `GET /precosteo/historico` · `GET /precosteo/{id}/detalle`.

**Corte**
- `POST /corte` (planeación) · `GET /corte/rollos?tela=` (autolistado) · `POST /corte/{id}/autorizar` (rol → archiva plan, no descuenta).
- `POST /corte/{id}/cierre` — captura consumo real → descuenta inventario + alimenta informe.
- `GET /informe/corte?por=referencia|cortador` — teórico vs real + diferencia.

**Insumos**
- `GET /insumos` · `POST /insumos/remision` (destino confeccionista/terminación → descuenta stock + notifica).

Cada acción de firma dispara **notificación** (correo + WhatsApp) vía un servicio común.

---

## 5. Pantallas y flujos (por rol)

**Bodega (móvil, taller)**
- *Ingreso de tela*: escanear/foto de la orden de despacho → OCR precarga los rollos → confirmar → imprime etiquetas. Botón grande "Nuevo ingreso".
- *Inventario*: buscar tela por nombre → ver rollos y metros disponibles; escanear un rollo muestra su ficha.

**Cortador (móvil/tablet, taller)**
- *Órdenes de corte asignadas*: lista con estado. Abrir una → ve referencia, curva por talla, rollos de la tela e indicaciones.
- *Cerrar corte*: captura el **consumo real** → confirma → el sistema calcula la diferencia.

**Diseñador (escritorio)**
- *Precosteo*: formato por líneas (igual al Sheet) → guardar borrador → **firmar** (solo con permiso) → queda inmutable.
- *Autorizar orden de corte*: revisa la planeación y da luz verde.

**Admin (escritorio)**
- *Informe de corte* (teórico vs real por referencia/cortador), *valor de inventario*, *alertas de stock*, *históricos*.
- Gestión de confeccionistas, insumos, permisos.

**Transversal:** buscador global, estados con color de marca, exportar a PDF/Sheet, modo oscuro opcional.

---

## 6. Roles y permisos

| Acción | Rol |
|---|---|
| Ingreso de tela / etiquetas | bodega, admin |
| Ver inventario | todos |
| Crear/editar precosteo | diseñador, admin |
| **Firmar precosteo** | `puede_autorizar_precosteo` (Sebastián, Alejandra) |
| Planear orden de corte | diseñador, admin |
| **Autorizar orden de corte** | `puede_autorizar_corte` (diseñador) |
| Cerrar corte (consumo real) | cortador, admin |
| Remisión de insumos | bodega, admin |
| Informes y configuración | admin |

Se valida en el backend (no solo en la UI) con `require_role` + flags.

---

## 7. Integraciones

- **Código de barras:** generación server-side (Code 128) → etiqueta PDF/ZPL para Zebra 10×10; escaneo = input del lector en móvil/USB.
- **OCR de orden de despacho:** `produccion_ocr.py` envía la foto a un modelo de visión (Claude/Gemini/Document AI) → extrae rollos (número, metros, lote, tono, referencia) → precarga el ingreso. Maneja los formatos heterogéneos (Primatela, Contacto, Stilotex, Megatex).
- **Correo:** notificación al firmar (SMTP/Resend — ya tienes Resend a mano).
- **WhatsApp:** WhatsApp Business Cloud API (recomendado) para avisos de firma; plantilla "utility".
- **Slack:** opcional, reutilizando tu `slack_notifier`.

---

## 8. Migración y Sheet de reporte

1. **Migración única:** script que lee el Sheet/Excel actual y carga Supabase (rollos, insumos, precosteos firmados). Una sola vez, al cortar sobre el módulo.
2. **Sheet de reporte (opcional):** el backend puede **empujar** datos a un Google Sheet de solo lectura (una vía) para conservar las vistas que te gustan, sin que nadie capture ahí. La captura vive 100% en el módulo.

---

## 9. Plan de construcción por fases (aunque el MVP es el flujo completo)

Para reducir riesgo, se construye en este orden y se prueba cada bloque:

1. **Cimientos:** esquema Supabase (`SUPABASE_PRODUCCION.sql`) + router `produccion` vacío + auth/roles.
2. **Ingreso + inventario** (con barcode) — base de todo.
3. **Precosteo + firma + trazabilidad de líneas.**
4. **Orden de corte (curva) + autorización + cierre de corte.**
5. **Informe de corte** (teórico vs real).
6. **Insumos + remisión.**
7. **Integraciones:** OCR, correo, WhatsApp.
8. **Frontend móvil pulido** + marca + estados.
9. **Migración** desde el Sheet + (opcional) Sheet de reporte.
10. **QA:** pruebas de cada endpoint, casos borde (stock insuficiente, doble firma), y prueba en dispositivo real del taller.

---

## 10. Handoff a Claude Code

Prompt sugerido para arrancar en Claude Code:

```
Lee docs/PLAN_IMPLEMENTACION_MODULO_PRODUCCION.md y docs/MODULO_PRODUCCION_FASE1.md.
Construye el módulo `producción` en MALE'DENIM OS siguiendo mi stack actual.
Empieza por: (1) SUPABASE_PRODUCCION.sql con todas las tablas e índices,
(2) backend/services/produccion.py + backend/api/produccion.py (registrado en main.py),
siguiendo el patrón de services/clientes.py y core/security.py (roles).
Luego el frontend en frontend/app/produccion (móvil-first para taller).
Haz commits por bloque y deja pruebas de cada endpoint.
```

---

## 11. Checklist de calidad

- [ ] Permisos validados en backend (no solo UI).
- [ ] Inventario nunca queda negativo; movimientos auditables.
- [ ] Precosteo y corte inmutables tras firma; detalle archivado.
- [ ] Informe cuadra teórico vs real contra los datos crudos.
- [ ] Escáner probado en móvil real del taller.
- [ ] Notificaciones (correo/WhatsApp) con plantillas correctas.
- [ ] Migración validada contra el Sheet actual (totales coinciden).
