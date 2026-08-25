# Handoff: POS MALE DENIM

## Overview
Punto de venta (POS) para las tiendas físicas de MALE DENIM (Dirty Jeans S.A.S., Medellín/Itagüí). Cubre el flujo completo de tienda: apertura de turno con PIN, venta con búsqueda de productos y tallas, asignación/creación de clienta (con datos para factura electrónica DIAN), cobro multi-método (incluye pago mixto), devoluciones y cambios, consulta de inventario por talla, cierre/arqueo de caja y un panel de ventas del día.

## About the Design Files
Los archivos de este paquete son **referencias de diseño creadas en HTML** — prototipos que muestran el look y el comportamiento esperado, no código de producción para copiar directamente. La tarea es **recrear estas vistas en el entorno del codebase destino** (React, Vue, etc.) usando sus patrones y librerías establecidas; si aún no existe un entorno, elegir el framework más apropiado e implementar ahí.

- `POS Male Denim.dc.html` — prototipo completo (las 7 vistas + diálogos). El markup de las vistas está dentro de `<x-dc>`; la lógica de estado está en la clase `Component` al final del archivo (React-like: `state` + `renderVals()`).
- `styles.css` — hoja de tokens y clases del design system "Industry", ya retemado a los colores de MALE DENIM. Fuente de verdad para colores, tipografía, espaciado y componentes base.

## Fidelity
**High-fidelity.** Colores, tipografía, espaciados y estados son finales. Recrear pixel-perfect con las librerías del codebase. Los datos (catálogo, clientas, cifras del panel) son mock y deben venir del backend real.

## Design System (obligatorio)
Sistema "Industry" retemado: estética wireframe/blueprint — esquinas rectas, bordes hairline, marcas de registro "+" en las esquinas de los paneles principales (clase `.blueprint` + 4 `<i class="corner tl/tr/bl/br">`). El único objeto sólido es el botón primario (acento). Nada de esquinas redondeadas grandes ni rellenos de color decorativos.

### Design Tokens (de `styles.css`)
Colores:
- Fondo `--color-bg: #f7f7f8` · Superficie `--color-surface: #ededee` · Texto `--color-text: #1a1c1f`
- Acento (negro-denim MALE DENIM) `--color-accent: #23262b`
- Rampa acento: 100 `#f1f2f5` · 200 `#e3e5ea` · 300 `#ccd0d8` · 400 `#a9afbb` · 500 `#7f8794` · 600 `#5e6571` · 700 `#444a54` · 800 `#2e333b` · 900 `#1b1e24`
- Divisor: `color-mix(in srgb, #1d1f20 16%, transparent)`
- Uso: tintes/hover = 100–300; texto sobre tinte y estados presionados = 700–900. Sin más colores (esquema mono).

Tipografía:
- Headings: Barlow Condensed 600 (`--font-heading`), line-height 1.12, letter-spacing −0.015em
- Body: Barlow 400/500 (`--font-body`), 15px base, line-height 1.55
- Labels/kickers: 10–11px, uppercase, letter-spacing 0.1–0.18em

Espaciado (escala 0.85×): 3.4 / 6.8 / 10.2 / 13.6 / 20.4 / 27.2 px (`--space-1..8`)
Radios: sm 2px · md 4px · lg 7px (nunca más redondo)
Sombras: `--shadow-sm/md/lg` definidas en styles.css
Iconos: Lucide, stroke-width 1.5
Focus visible: `outline: 2px solid var(--color-accent); outline-offset: 2px`
Moneda: COP formateada `$189.900` (`toLocaleString('es-CO')`)
Targets táctiles: mínimo 44px (corre en tablet/pantalla táctil).

## Screens / Views

### 1. Login / apertura de turno
- Card centrada 420px `.blueprint` con marcas de esquina, logo "MALE'DENIM" (Barlow Condensed 700, 30px) y kicker "Punto de venta · Tienda Principal".
- Paso 1: grid 3 columnas de usuarias (avatar cuadrado 44px con inicial sobre tinte accent-100, nombre 13px, rol 10px uppercase). Hover: borde acento + fondo accent-100.
- Paso 2: PIN — 4 dots (12px, rellenos con acento según dígitos), keypad 3×4 de botones 72×56px (1-9, C, 0, ⌫), Barlow Condensed 20px. 4 dígitos cualquiera → entra a Venta (validación real va en backend).

### 2. Venta (vista principal)
Layout: nav rail izquierda 92px + columna principal + panel carrito derecha 360px.
- **Nav rail**: logo "M'D", 5 items verticales (icono 22px + label 10px uppercase): Venta, Cambios, Stock, Cierre, Panel. Activo: fondo accent-100, texto accent-800. Abajo: avatar de la cajera + botón logout 44px.
- **Header**: título de la vista (Barlow Condensed 20px); derecha: "Tienda Principal · Caja 01 · {cajera} · {fecha}" en 12px al 60%.
- **Búsqueda y filtros**: input 44px con icono lupa (busca por nombre o referencia), chips de categoría 44px (Todo/Jeans/Shorts/Faldas/Chaquetas/Tops). Chip activo: fondo accent-100, texto accent-800, borde acento. La fila hace wrap en pantallas angostas.
- **Grid de productos**: `repeat(auto-fill, minmax(210px, 1fr))`, gap 10px. Tarjeta SIN foto: borde 1px al 10% del texto, radio 4px, padding 13.6px; nombre (Barlow Condensed 600, 15px), ref en monospace 11px, precio 13px 600; fila de 5 chips de talla (24/26/28/30/32) de 40px de alto, flex 1. Talla agotada: disabled, opacidad 0.35, tooltip "Agotada"; con stock: tooltip "N en stock". Tap en talla agrega al carrito.
- **Carrito** (aside `.blueprint` con fondo surface): header "Venta actual" + tag con conteo; sección clienta (botón dashed "+ Asignar clienta" 44px, o fila con nombre/teléfono y link "quitar"); lista de items (nombre truncado 13px, "Talla X · precio" 11px, stepper −/+ de 32px, total por línea); footer con Subtotal, Descuento (botones 0%/10%/20%), línea IVA incluido 19% (informativa, calculada como total − total/1.19), Total (Barlow Condensed 700, 26px) y botón **COBRAR {total}** primario sólido 56px `.blueprint` con marcas. Deshabilitado si el carrito está vacío. Carrito vacío: mensaje "Toca una talla para agregar artículos a la venta".

### 3. Diálogo de cobro (modal sobre backdrop 50% neutral-900)
Dialog 520px, fondo surface, `.blueprint`. Cuatro pasos:
1. **Métodos**: grid 2×, botones 64px con icono: Efectivo, Tarjeta, Transferencia / QR, Giftcard, Pago mixto. Tarjeta/QR/Giftcard confirman directo (el datáfono real va aquí).
2. **Efectivo**: chips rápidos (Exacto, $50.000, $100.000, $200.000 — solo los ≥ total), input "Recibido" 52px numérico, línea Cambio (Barlow Condensed 22px). Confirmar deshabilitado si recibido < total.
3. **Pago mixto**: lista de pagos parciales agregados (método + monto + "quitar"), selector de método (Efectivo/Tarjeta/QR/Giftcard) + input monto + "Agregar" (el monto se recorta al restante), línea Restante. Confirmar habilitado solo con restante $0.
4. **Éxito**: check sobre cuadrado de acento 56px, "Venta registrada", ticket + total + método, "Cambio a entregar" si aplica, botones "Imprimir ticket" y "Nueva venta" (limpia carrito, clienta y descuento). Tickets consecutivos T-NNNNN.

### 4. Diálogo de clienta
- **Buscar**: input numérico "Buscar por número de identificación" (filtra solo por dígitos del documento), lista de resultados 48px (nombre + "CC 1.037.601.884 · N compras"). Sin resultados: aviso "Sin resultados para esa identificación. Crea la clienta abajo."
- **Crear** (botón "+ Crear clienta"; oculta buscador y lista): tipo de documento en `<select>` (Cédula de ciudadanía / Pasaporte / Cédula de extranjería) + número de identificación en la misma fila (180px + 1fr); nombre completo; teléfono; correo electrónico con helper "A este correo llega la factura electrónica". Todos obligatorios. "Guardar y asignar" crea y asigna a la venta. Link "Volver a la lista". Acción secundaria siempre visible: "Venta sin registrar".

### 5. Devoluciones y cambios
- Input "Número de ticket, ej. T-10471" + botón "Buscar ticket". Estado vacío con hint.
- Card `.blueprint` del ticket: número, fecha, cajera; lista de artículos seleccionables (checkbox cuadrado 20px, ✓ en accent-800 sobre tinte; seleccionado: borde acento + fondo accent-100); chips de Motivo (Talla / Defecto / No le gustó / Cambio de modelo) y Reembolso (Efectivo / Método original / Crédito tienda), 40px.
- Footer: "Total a devolver" + botón primario "Procesar devolución" (deshabilitado sin artículos, motivo o método). Éxito: card con check, resumen y "Nueva devolución".

### 6. Inventario
- Input filtro 44px + tags "{N} referencias" y "{N} con stock bajo".
- Tabla `.table`: Ref (monospace) / Producto / Categoría / Precio / T24 / T26 / T28 / T30 / T32 / Total / Estado. Estado como tag: OK (neutral), "Stock bajo" ≤8 uds o "Agotado" (accent). Umbral configurable.

### 7. Cierre de caja
Grid 2 columnas (máx 900px):
- **Resumen del turno** (`.blueprint`): transacciones, ventas brutas, devoluciones (negativo, accent-700), ventas netas (separador + 18px), desglose por método de pago.
- **Arqueo de efectivo** (`.blueprint`): base de caja + efectivo en ventas = efectivo esperado; input "Efectivo contado" 48px numérico; línea Diferencia (+/−; negativa en accent-900; cero en accent-700); botón primario CERRAR CAJA 52px. Éxito: "Caja cerrada" con resumen y nota de envío del reporte Z.

### 8. Panel de ventas (dashboard)
- 4 KPI cards `.blueprint`: Ventas hoy, Transacciones (+ ticket promedio), Unidades, Devoluciones. Kicker 10px uppercase en accent-700, valor Barlow Condensed 700 28px.
- **Ventas por hora**: barras CSS 10h–20h, alto proporcional, accent-200 (pico en accent-400), radio superior 2px, labels 10px.
- **Más vendidos hoy**: top 5 con posición 01-05 (Condensed, accent-700), nombre, unidades y valor.

## Interactions & Behavior
- Navegación por estado (sin router): `screen: 'login' | 'venta' | 'dev' | 'inv' | 'cierre' | 'dash'`. Logout vuelve a login y limpia cajera/PIN.
- Agregar al carrito: si ya existe misma ref+talla, incrementa qty; stepper − a 0 elimina la línea.
- Hovers: tinte accent-100 y/o borde acento en todo elemento interactivo; pressed accent-200; focus-visible ring 2px acento. Disabled al 45% de opacidad (viene del stylesheet).
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
Sin imágenes ni assets binarios. Iconos: Lucide (stroke 1.5) — en el prototipo están como paths SVG inline; en producción usar el paquete lucide del framework. Fuentes: Google Fonts Barlow + Barlow Condensed.

## Screenshots
En `screenshots/`: 01-login, 02-login-pin, 03-venta, 04-venta-carrito, 05-cobro-metodos, 06-cobro-efectivo, 07-cobro-efectivo-exacto, 08-venta-exitosa, 09-devoluciones, 10-inventario, 11-cierre-caja, 12-panel-ventas. Son referencia visual del prototipo renderizado.

## Files
- `POS Male Denim.dc.html` — todas las vistas y la lógica de referencia
- `styles.css` — tokens y clases base (fuente de verdad del estilo)
