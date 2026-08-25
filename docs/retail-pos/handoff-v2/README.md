# Handoff: POS MALE DENIM

## Overview
Punto de venta (POS) para las tiendas físicas de MALE DENIM (Dirty Jeans S.A.S., Medellín/Itagüí). Cubre el flujo completo de tienda: apertura de turno con PIN, venta con búsqueda de productos y tallas, asignación/creación de clienta (con datos para factura electrónica DIAN), cobro multi-método (incluye pago mixto), devoluciones y cambios, consulta de inventario por talla, cierre/arqueo de caja y un panel de ventas del día.

## Versión vigente: v2 "Apple-grade"
**Implementar la v2** (`POS Male Denim v2.dc.html` + `styles-v2.css`). La v1 Industry (`POS Male Denim.dc.html` + `styles.css`) se incluye solo como historial. Todo lo que sigue describe la v2; las secciones de flujo, estado y reglas de negocio aplican igual a ambas.

## About the Design Files
Los archivos de este paquete son **referencias de diseño creadas en HTML** — prototipos que muestran el look y el comportamiento esperado, no código de producción para copiar directamente. La tarea es **recrear estas vistas en el entorno del codebase destino** (React, Vue, etc.) usando sus patrones y librerías establecidas; si aún no existe un entorno, elegir el framework más apropiado e implementar ahí.

- `POS Male Denim v2.dc.html` — prototipo completo VIGENTE (las 7 vistas + diálogos). El markup de las vistas está dentro de `<x-dc>`; la lógica de estado está en la clase `Component` al final del archivo (React-like: `state` + `renderVals()`).
- `styles-v2.css` — hoja de tokens y clases de la v2. Fuente de verdad para colores, tipografía, espaciado, radios, sombras y componentes base (btn, tag, input, table, dialog, card ".blueprint").
- `POS Male Denim.dc.html` + `styles.css` — versión anterior (estética wireframe Industry), solo referencia histórica.

## Fidelity
**High-fidelity.** Colores, tipografía, espaciados y estados son finales. Recrear pixel-perfect con las librerías del codebase. Los datos (catálogo, clientas, cifras del panel) son mock y deben venir del backend real.

## Design System v2 (obligatorio)
Estética "Apple-grade": minimalista, cards blancas redondeadas con sombras suaves sobre fondo gris claro, botones pill, tipografía de sistema, mucho aire. Un solo color de marca: negro-denim. Sin gradientes ni color decorativo.

### Design Tokens (de `styles-v2.css` — fuente de verdad; no hardcodear)
Colores:
- Fondo `--color-bg: #f5f5f7` · Superficie/cards `--color-surface: #ffffff` · Texto `--color-text: #1d1d1f`
- Acento (negro MALE DENIM) `--color-accent: #1d1d1f`
- Rampa gris: 100 `#f5f5f7` · 200 `#e8e8ed` · 300 `#d2d2d7` · 400 `#aeaeb4` · 500 `#86868b` · 600 `#6e6e73` · 700 `#515154` · 800 `#333336` · 900 `#161617`
- Divisor: `rgba(0,0,0,0.08)`
- Uso: tintes/hover = 100–300; texto secundario = 500–700; pressed/hover del primario = 800.

Tipografía (sistema, sin webfonts):
- Stack: `-apple-system, BlinkMacSystemFont, "SF Pro Display/Text", "Segoe UI", Helvetica, Arial, sans-serif` (`--font-heading` / `--font-body`)
- Headings 600, letter-spacing −0.02em · Body 15px, line-height 1.5, antialiased
- Labels/kickers: 10–11px, uppercase, letter-spacing 0.04–0.06em, color gris 600

Espaciado: 4 / 8 / 12 / 16 / 20 / 24 / 28 / 36 px (`--space-1..8`)
Radios: sm 8px · md 12px · lg 18px · botones y chips pill (980px) · diálogos 22px
Sombras: `--shadow-sm` (cards) · `--shadow-md` · `--shadow-lg` (diálogos) — suaves, doble capa
Componentes clave (clases en styles-v2.css):
- `.blueprint` = card: fondo blanco, radio 18px, shadow-sm, sin borde (los `<i class="corner">` del markup están ocultos con `display:none` — no implementarlos)
- `.btn` pill 40px · `.btn-primary` negro sólido (hover #333336, active scale 0.98) · `.btn-secondary` gris 200 · `.btn-ghost` transparente
- `.tag` pill 24px · `.tag-accent` negro/blanco · `.tag-neutral` gris
- `.input`: fondo blanco, borde divisor, radio 12px, focus = borde gris 500 + ring `0 0 0 3px rgba(0,0,0,0.06)`
- `.table`: contenedor blanco redondeado con sombra, header 11px uppercase gris, hover de fila gris 100
- `.dialog-backdrop`: `rgba(0,0,0,0.35)` + `backdrop-filter: blur(14px) saturate(1.2)` · `.dialog`: blanco, radio 22px, shadow-lg
Iconos: Lucide, stroke-width 1.5
Focus visible: `outline: 2px solid var(--color-accent-500); outline-offset: 2px`
Moneda: COP formateada `$189.900` (`toLocaleString('es-CO')`)
Targets táctiles: mínimo 44px (corre en tablet/desktop/pantalla táctil).

## Screens / Views

### 1. Login / apertura de turno
- Card centrada 420px (blanca, radio 18px, shadow-sm), logo "MALE'DENIM" (700, 30px, letter-spacing −0.02em) y kicker "Punto de venta · Tienda Principal".
- Paso 1: grid 3 columnas de usuarias (avatar cuadrado 44px con inicial sobre tinte accent-100, nombre 13px, rol 10px uppercase). Hover: borde acento + fondo accent-100.
- Paso 2: PIN — 4 dots (12px, rellenos con acento según dígitos), keypad 3×4 de botones 72×56px (1-9, C, 0, ⌫), 20px semibold, radio 12px. 4 dígitos cualquiera → entra a Venta (validación real va en backend).

### 2. Venta (vista principal)
Layout: nav rail izquierda 92px + columna principal + panel carrito derecha 360px.
- **Nav rail**: fondo blanco (sin borde), logo "M'D", 5 items verticales (icono 22px + label 10px uppercase): Venta, Cambios, Stock, Cierre, Panel. Activo: fondo accent-100, texto accent-800. Abajo: avatar de la cajera + botón logout 44px.
- **Header**: título de la vista (Barlow Condensed 20px); derecha: "Tienda Principal · Caja 01 · {cajera} · {fecha}" en 12px al 60%.
- **Búsqueda y filtros**: input 44px con icono lupa (busca por nombre o referencia), chips de categoría 44px PILL (Todo/Jeans/Shorts/Faldas/Chaquetas/Tops), peso 500. Chip activo: fondo accent-100, texto accent-800, borde acento. La fila hace wrap en pantallas angostas.
- **Grid de productos**: `repeat(auto-fill, minmax(210px, 1fr))`, gap 10px. Tarjeta SIN foto: fondo blanco, radio 18px, shadow-sm, SIN borde, padding 16px; nombre (600, 15px), ref en monospace 11px, precio 13px 600; fila de 5 chips de talla (24/26/28/30/32) de 40px de alto, flex 1, radio 8px, borde divisor. Talla agotada: disabled, opacidad 0.35, tooltip "Agotada"; con stock: tooltip "N en stock". Tap en talla agrega al carrito.
- **Carrito** (aside card blanca, radio 18px, shadow-sm): header "Venta actual" + tag con conteo; sección clienta (botón dashed "+ Asignar clienta" 44px, o fila con nombre/teléfono y link "quitar"); lista de items (nombre truncado 13px, "Talla X · precio" 11px, stepper −/+ de 32px, total por línea); footer con Subtotal, Descuento (botones 0%/10%/20%), línea IVA incluido 19% (informativa, calculada como total − total/1.19), Total (700, 26px) y botón **Cobrar {total}**: pill negro sólido de 56px, texto blanco 17px. Deshabilitado si el carrito está vacío. Carrito vacío: mensaje "Toca una talla para agregar artículos a la venta".

### 3. Diálogo de cobro (modal sobre backdrop 50% neutral-900)
Dialog 520px blanco, radio 22px, shadow-lg, sobre backdrop oscuro con blur(14px). Cuatro pasos:
1. **Métodos**: grid 2×, botones 64px con icono: Efectivo, Tarjeta, Transferencia / QR, Giftcard, Pago mixto. Tarjeta/QR/Giftcard confirman directo (el datáfono real va aquí).
2. **Efectivo**: chips rápidos (Exacto, $50.000, $100.000, $200.000 — solo los ≥ total), input "Recibido" 52px numérico, línea Cambio (Barlow Condensed 22px). Confirmar deshabilitado si recibido < total.
3. **Pago mixto**: lista de pagos parciales agregados (método + monto + "quitar"), selector de método (Efectivo/Tarjeta/QR/Giftcard) + input monto + "Agregar" (el monto se recorta al restante), línea Restante. Confirmar habilitado solo con restante $0.
4. **Éxito**: check sobre cuadrado de acento 56px, "Venta registrada", ticket + total + método, "Cambio a entregar" si aplica, botones "Imprimir ticket" y "Nueva venta" (limpia carrito, clienta y descuento). Tickets consecutivos T-NNNNN.

### 4. Diálogo de clienta
- **Buscar**: input numérico "Buscar por número de identificación" (filtra solo por dígitos del documento), lista de resultados 48px (nombre + "CC 1.037.601.884 · N compras"). Sin resultados: aviso "Sin resultados para esa identificación. Crea la clienta abajo."
- **Crear** (botón "+ Crear clienta"; oculta buscador y lista): tipo de documento en `<select>` (Cédula de ciudadanía / Pasaporte / Cédula de extranjería) + número de identificación en la misma fila (180px + 1fr); nombre completo; teléfono; correo electrónico con helper "A este correo llega la factura electrónica". Todos obligatorios. "Guardar y asignar" crea y asigna a la venta. Link "Volver a la lista". Acción secundaria siempre visible: "Venta sin registrar".

### 5. Devoluciones y cambios
- Input "Número de ticket, ej. T-10471" + botón "Buscar ticket". Estado vacío con hint.
- Card blanca del ticket: número, fecha, cajera; lista de artículos seleccionables (checkbox cuadrado 20px, ✓ en accent-800 sobre tinte; seleccionado: borde acento + fondo accent-100); chips de Motivo (Talla / Defecto / No le gustó / Cambio de modelo) y Reembolso (Efectivo / Método original / Crédito tienda), 40px.
- Footer: "Total a devolver" + botón primario "Procesar devolución" (deshabilitado sin artículos, motivo o método). Éxito: card con check, resumen y "Nueva devolución".

### 6. Inventario
- Input filtro 44px + tags "{N} referencias" y "{N} con stock bajo".
- Tabla `.table` (contenedor blanco redondeado con sombra, hover de fila): Ref (monospace) / Producto / Categoría / Precio / T24 / T26 / T28 / T30 / T32 / Total / Estado. Estado como tag: OK (neutral), "Stock bajo" ≤8 uds o "Agotado" (accent). Umbral configurable.

### 7. Cierre de caja
Grid 2 columnas (máx 900px):
- **Resumen del turno** (card blanca): transacciones, ventas brutas, devoluciones (negativo, accent-700), ventas netas (separador + 18px), desglose por método de pago.
- **Arqueo de efectivo** (card blanca): base de caja + efectivo en ventas = efectivo esperado; input "Efectivo contado" 48px numérico; línea Diferencia (+/−; negativa en accent-900; cero en accent-700); botón primario pill "Cerrar caja" 52px. Éxito: "Caja cerrada" con resumen y nota de envío del reporte Z.

### 8. Panel de ventas (dashboard)
- 4 KPI cards blancas: Ventas hoy, Transacciones (+ ticket promedio), Unidades, Devoluciones. Kicker 10px uppercase gris, valor 700 28px con tracking −0.02em.
- **Ventas por hora**: barras CSS 10h–20h, alto proporcional, accent-200 (pico en accent-400), radio superior 8px, labels 10px.
- **Más vendidos hoy**: top 5 con posición 01-05 (Condensed, accent-700), nombre, unidades y valor. Posición 01-05 en gris 700.

## Interactions & Behavior
- Navegación por estado (sin router): `screen: 'login' | 'venta' | 'dev' | 'inv' | 'cierre' | 'dash'`. Logout vuelve a login y limpia cajera/PIN.
- Agregar al carrito: si ya existe misma ref+talla, incrementa qty; stepper − a 0 elimina la línea.
- Hovers: tinte accent-100 y/o borde en todo elemento interactivo; pressed accent-200; primario hover #333336 + active scale(0.98); focus-visible ring 2px gris 500. Disabled al 40% de opacidad (viene del stylesheet). Transiciones 150ms ease en background/border.
- Modales cierran con Cancelar/acciones, no hay cierre por click en backdrop en el prototipo (decisión abierta).
- PIN: al cuarto dígito entra con ~180ms de delay para feedback visual.

## State Management (variables del prototipo)
`screen, cajera, pin` · `query, cat, cart[{ref,name,size,price,qty}], discount, cliente` · `clienteOpen, cliQuery, nuevaClienta, ncTipoDoc, ncDoc, ncNombre, ncTel, ncEmail, clientasExtra` · `payStep('method'|'cash'|'mix'|'success'), cashInput, mixPays[{method,amt}], mixMethod, mixInput, last{ticket,total,method,cambio}, ticketN` · `devQuery, devSale, devSel, devMotivo, devRefund, devDone` · `invQuery` · `cxContado, closed`.

Datos que deben venir del backend real: catálogo con stock por talla, clientas (búsqueda por documento), tickets para devolución, cifras de cierre y dashboard, consecutivo de tickets, validación de PIN por usuaria.

## Requisitos de negocio a respetar
- Clienta para factura electrónica: tipo de documento (CC/PA/CE), número, nombre completo, teléfono y correo (la factura electrónica llega al correo). Búsqueda de clientas SOLO por número de identificación.
- Métodos de pago: efectivo (con cambio), tarjeta datáfono, transferencia/QR, giftcard/crédito tienda y pago mixto (combinación con restante exacto).
- Tallas denim: 24–32. Precios COP.
- Tweaks existentes en el prototipo (parametrizables): mostrar línea de IVA (bool), base de caja (COP).

## Assets
Sin imágenes ni assets binarios. Iconos: Lucide (stroke 1.5) — en el prototipo están como paths SVG inline; en producción usar el paquete lucide del framework. Fuentes: stack de sistema (sin webfonts que cargar).

## Screenshots (v2 — referencia visual obligatoria)
En `screenshots/`: 01-login, 02-login-pin, 03-venta, 04-venta-carrito, 05-cobro-metodos, 06-cobro-efectivo, 07-cobro-efectivo-exacto, 08-venta-exitosa, 09-devoluciones, 09b-devolucion-exitosa, 10-inventario, 11-cierre-caja, 11b-caja-cerrada, 12-panel-ventas, 13-cliente-buscar, 14-cliente-crear, 15-pago-mixto. Renderizadas de la v2.

## Checklist de vistas (ninguna puede faltar)
1. Login: selección de usuaria → PIN keypad
2. Venta: búsqueda + chips categoría + grid productos con tallas + carrito (clienta, descuento, IVA, total)
3. Diálogo cobro: métodos → efectivo (chips rápidos + cambio) / mixto (parciales + restante) → éxito con ticket
4. Diálogo clienta: buscar por nº de identificación / crear (tipo doc CC-PA-CE, nº, nombre, teléfono, correo factura electrónica)
5. Devoluciones: buscar ticket → seleccionar artículos + motivo + reembolso → éxito
6. Inventario: filtro + tabla stock por talla con estados
7. Cierre de caja: resumen turno + arqueo con diferencia → caja cerrada
8. Panel de ventas: 4 KPIs + barras por hora + top 5

## Files
- `POS Male Denim v2.dc.html` — VIGENTE: todas las vistas y la lógica de referencia
- `styles-v2.css` — VIGENTE: tokens y clases base (fuente de verdad del estilo)
- `POS Male Denim.dc.html` + `styles.css` — versión v1 Industry (solo historial)
- `screenshots/` — capturas de la v2, una por vista/estado
