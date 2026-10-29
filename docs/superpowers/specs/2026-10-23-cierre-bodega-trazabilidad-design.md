# Cierre de bodega: trazabilidad de prendas por proceso (MALE DENIM OS)

Fecha: 2026-10-23
Autor: Sebastián Hurtado (fundador) + Claude
Estado: borrador para aprobación (HARD GATE de brainstorming — no se construye hasta aprobación)

## Intención y el porqué

En producción las prendas se pierden **en confección** y hoy eso solo se detecta
**al final**, en el cierre de terminación (cuando la mercancía entra a bodega). La
pérdida viaja escondida desde confección: nadie sabe en qué paso ni qué tallas se
fueron, y cuando se descubre ya no hay a quién reclamarle con precisión.

Queremos que **lo cortado sea igual a lo que llega a bodega**, y que **cada vez que
un lote pasa de un proceso a otro y falta algo, salte una alerta inmediata** que
diga EN QUÉ PASO, CUÁL taller y QUÉ TALLAS faltan — no un total al final.

Sebastián: no-técnico, quiere soluciones **simples y operativas**. El conteo real
viene de las **remisiones que cada taller entrega y fotografía en el grupo de
WhatsApp** (su modelo mental: "todos entregan una remisión que tú estás leyendo").
Confirmado por él: esas remisiones **traen la cantidad escrita y por talla**.

## Estado actual (verificado en código)

- **El motor ya existe, pero solo para la pata de lavandería.**
  - `backend/services/remision_ocr.py::leer_remision_lavanderia` lee la foto de la
    remisión de lavandería con visión (Claude Haiku 4.5) y saca cantidad.
  - `backend/services/lavanderia_chase.py::remision_por_whatsapp` recibe la foto,
    `capturar_cantidad_remision` (línea ~1548) la OCR-ea y guarda
    `hoja_ruta_lote.lav_cantidad_remision`, cruza contra lo cortado
    (`cruce_cantidades`, ~1606) y dispara alerta de campanita si no cuadra
    (`_avisar_os`, ~1052).
  - `cruce_cantidades` ya calcula diffs: cortadas → remisión(lavandería) →
    recibidas → entregadas → terminación. **Pero salta confección** (no existe
    `dif_cortadas_vs_confeccion`).
- **El webhook de WhatsApp (`backend/api/meta.py`, ~242-267) manda CUALQUIER foto de
  proveedor al lector de lavandería**, asumiendo que es la remisión de lavandería.
  No clasifica por paso.
- **Las remisiones de confección, terminación y bodega NO se leen ni se cuentan.**
  Caen al espejo del grupo (el proveedor queda marcado, `meta.py` ~219) pero su
  cantidad nunca entra al cruce. No existe `conf_cantidad_*` en ninguna parte.
- **Los conteos de después de corte son totales, no por talla.** Solo
  `ordenes_corte.unidades_cortadas` (y `orden_corte_referencias.unidades_cortadas`)
  están por talla (jsonb). `lav_cantidad_*` y `term_cantidad_*` son enteros totales.
- **`term_cantidad_terminada` se lee pero nunca se escribe** (no hay setter).
- **Columnas fuera del repo:** `lav_cantidad_remision`, `lav_cantidad_remision_origen`,
  `term_cantidad_recibida`, `term_cantidad_terminada` se aplicaron directo en Supabase
  y **no están en ninguna migración versionada**.
- **Alertas (campanita):** sistema limpio y reutilizable —
  `backend/services/notificaciones.py` (tabla `notificaciones`, `crear` /
  `crear_para_modulo`) + política en `backend/services/avisos_produccion.py`
  (`avisar_corte_creado/cerrado/avanzo`). API `backend/api/notificaciones.py`
  (el front sondea ~20s). Ya hay precedente de alerta de faltante (lavandería).
- **Hoja de ruta (máquina de estados):** `hoja_ruta_lote` (1 fila por
  `orden_corte_id`), `etapa` ∈ `ETAPAS_RUTA` (`produccion.py:5798`):
  asignado → aceptado → en_confeccion → lavanderia → terminacion_recibida →
  terminacion_terminada → despachado. Lavandería se puede **omitir** por lote
  (`etapas_omitidas`, congelado desde el precosteo).
- **Proveedores:** `confeccionistas` (una tabla, discriminada por `tipo` ∈
  confeccion/terminacion/lavanderia/otros). Un lote se liga por
  `hoja_ruta_lote.confeccionista_id` / `lavanderia_id` / `terminacion_id`.

## Meta (goals)

1. Leer por WhatsApp la remisión **de cada paso** (confección, lavandería,
   terminación, entrada a bodega), con visión, extrayendo cantidad **por talla**.
2. En cada entrega, **cruzar por talla** lo que salió del paso anterior contra lo
   que entra al siguiente, respetando los pasos omitidos del lote.
3. Cuando falte algo, **alerta inmediata** (campanita + a quien corresponda) que
   nombre: paso, taller, y las tallas/cantidades faltantes; con enlace a la vista.
4. **Vista "Cierre de bodega / Cuadre del lote":** toda la cadena corte →
   confección → lavandería → terminación → bodega, con el conteo de cada paso y el
   faltante **marcado en rojo donde se perdió**.
5. Un lote queda **"cerrado limpio"** solo cuando la entrada a bodega cuadra con lo
   cortado, o el faltante quedó **justificado** por alguien autorizado.
6. Reutilizar al máximo el motor existente (OCR de remisión + cruce + alerta de
   lavandería); extenderlo, no reescribirlo.

## No-goals

- No cambiar cómo se **crean** físicamente las remisiones ni el flujo del taller.
- No rehacer la persecución de lavandería (`lavanderia_chase`); se generaliza.
- No construir un escáner/pistola nuevo ni inventario físico diario de bodega.
- No rehacer el frontend de "lote por referencia" (pendiente aparte); el cuadre
  opera a nivel de orden de corte (sumando tallas), con nota de refinamiento futuro.

## Anti-goals (qué sería un fracaso aunque "funcione")

- **Alertas falsas por OCR malo.** Si la visión lee mal una talla y dispara "faltan"
  cuando no faltan, el equipo deja de confiar en la campanita. → Todo conteo OCR
  entra como **"por confirmar"** y alguien lo valida/corrige antes de que cuadre o
  dispare alerta en firme. (Sebastián: confirmar este punto.)
- Enterrar la alerta en un correo que nadie lee (va a la campanita, que ya se usa).
- Que el lote se pueda "cerrar" tapando un faltante sin dejar rastro de quién y por
  qué lo justificó.

## El cómo — decisiones tomadas

### Datos (migraciones versionadas, con GRANT a service_role)

- Añadir, por paso, el conteo **por talla** como `jsonb` en `hoja_ruta_lote`
  (misma forma que `unidades_cortadas`: `{ "T12": 10, "T14": 8, ... }`):
  - `conf_unidades` (entregado por confección)
  - `lav_unidades` (recibido/leído de la remisión de lavandería — generaliza lo que
    hoy es `lav_cantidad_remision`)
  - `term_unidades` (recibido en terminación)
  - `bodega_unidades` (entrada final a bodega)
  - Opcionalmente, versión por talla de recibido/entregado de lavandería si se
    necesita el cruce interno de esa pata.
  Se mantiene el total entero existente por compatibilidad, derivándolo del jsonb.
- Migración que **versiona las columnas huérfanas** actuales
  (`lav_cantidad_remision`, `*_origen`, `term_cantidad_recibida`,
  `term_cantidad_terminada`) con su `ADD COLUMN IF NOT EXISTS` + GRANT.
- Campos de cuadre por paso: estado del cruce (`cuadra` / `faltan` / `sobran` /
  `por_confirmar` / `justificado`), `justificado_por`, `justificado_motivo`,
  `justificado_at`. (Nueva tabla `cuadre_lote_proceso` por `(orden_corte_id, paso)`,
  o columnas en `hoja_ruta_lote`; lo decide el builder — ver "Para el builder").

### Lectura de la remisión por paso

- Generalizar el lector: `remision_ocr.leer_remision_proceso(bytes, mime)` (o
  extender `leer_remision_lavanderia`) para devolver **cantidades por talla** +
  (si aparece) el paso/consecutivo. Prompt de visión ajustado a la remisión de
  taller (tabla de tallas), no a la de textilera.
- **Clasificar la foto por el taller que la manda:** en `meta.py`, resolver el
  `wa_id` del remitente → proveedor → su `tipo`/rol **en ese lote** vía
  `hoja_ruta_lote` (`confeccionista_id`/`lavanderia_id`/`terminacion_id`). Así la
  foto de confección se guarda como conteo de confección, no de lavandería (hoy todo
  va a lavandería). Si es ambiguo, cae al flujo conservador actual (no adivinar).
- **Entrada manual de respaldo:** en el OS, poder teclear/corregir el conteo por
  talla de cada paso cuando no hay foto o el OCR falla. El conteo queda
  "confirmado" por quien lo digita.

### Cruce y alerta

- Generalizar `cruce_cantidades` a toda la cadena, **por talla**, saltando los pasos
  omitidos del lote (`etapas_omitidas`). Encadenado:
  cortadas → confección → (lavandería) → terminación → bodega.
- Al **confirmarse** el conteo de un paso, comparar por talla contra el paso anterior
  disponible. Si faltan (en cualquier talla), disparar alerta **en firme**
  (`avisos_produccion`, nuevo `tipo` p. ej. `faltante_proceso`) a la campanita del
  módulo `produccion_cortador` + al creador del lote, con enlace a la vista. (Default;
  Sebastián ajusta destinatarios.)
- Escalamiento opcional (correo Resend / Slack) ya existe si se quiere, apagado por
  defecto.

### Vista "Cierre de bodega"

- Nueva vista (o pestaña en `produccion/rutas/`) que lista lotes y, por lote, la
  cadena completa con el conteo **por talla** de cada paso y el **faltante en rojo**
  en el punto donde se perdió. Acción para **confirmar** un conteo OCR y para
  **justificar** un faltante (motivo: dañadas/2das/re-conteo). Un lote se marca
  **"cerrado limpio"** cuando `bodega_unidades` cuadra con `unidades_cortadas` por
  talla, o todos los faltantes de la cadena están justificados.
- La alerta de campanita hace deep-link a esta vista, al lote y paso con el faltante.

## Para el builder (lo que queda a criterio)

- **Modelo del cuadre:** tabla nueva `cuadre_lote_proceso` vs columnas en
  `hoja_ruta_lote`. Preferencia: tabla nueva (un renglón por paso, más limpio para
  estado/justificación/auditoría), con su GRANT.
- **Granularidad multi-referencia:** hoy `hoja_ruta_lote` es por `orden_corte_id`. El
  cruce inicial opera a ese nivel (sumando tallas de las referencias). Si el negocio
  necesita el cuadre por referencia, es un refinamiento posterior (depende del
  frontend de "lote por referencia", pendiente).
- **Umbral de alerta:** ¿alerta ante cualquier faltante ≥1, o con una tolerancia?
  Default: cualquier faltante ≥1 unidad en cualquier talla.
- **Modelo/plan de verificación** (tests, next build, guardián) según los estándares
  del repo.

## Decisiones que necesitan a Sebastián (pila "theirs")

Se consultarán en un solo mensaje tras el builder-check. Candidatas:
1. Confirmar el paso de **"conteo OCR por confirmar"** antes de alertar en firme
   (anti-alertas-falsas), o si prefiere que alerte apenas lee.
2. **Quién recibe** cada alerta de faltante (default: cortadores + creador del lote +
   escalar a Sebastián).
3. **Quién puede justificar** un faltante para cerrar el lote (default: admin /
   supervisor de producción).

## Defaults fijados ("dale con los defaults", Sebastián, 2026-10-23)

Sebastián delegó las decisiones abiertas. Se fijan estos defaults (puede vetarlos);
todo se diseña **defensivo**: una suposición equivocada NO dispara alerta en firme
ni corrompe el cierre — a lo sumo deja un conteo "por confirmar".

- **Q1 — qué representa cada papel / mapeo de campos.** El papel que hoy el OS llama
  "remisión de lavandería" lo manda el **confeccionista** cuando el lote SALE de
  confección → se trata como el **conteo de salida de confección** (`conf_unidades`).
  Es el primer conteo después de corte y el que **cruza contra lo cortado para cazar
  la pérdida de confección** (el dolor declarado). Lavandería recibido/entregado
  (`lav_cantidad_recibida`/`entregada`, portal) y terminación recibido
  (`term_cantidad_recibida`, portal) se mantienen como están.
- **Q2 — "entrada a bodega" / "cerrado limpio".** No se inventa un paso ni proveedor
  "bodega". La entrada a bodega **es el cierre de terminación** (palabras de
  Sebastián: "el cierre de terminación es con el que se envía la mercancía a
  bodega"). El conteo final = el del cierre de terminación. "Cerrado limpio" = ese
  conteo final cuadra por talla con `unidades_cortadas`, o los faltantes de la cadena
  están justificados.
- **Q3 — de qué paso es cada foto.** Clasificar por el **remitente** (su rol en ESE
  lote: `confeccionista_id`/`lavanderia_id`/`terminacion_id`) + la **etapa actual**
  del lote para desambiguar. Si queda ambiguo → NO se adivina: entra "por confirmar"
  para clasificar/teclear a mano en el OS, sin disparar alerta en firme.
- **Q4 — por talla vs total.** Se lee **por talla cuando el papel trae las tallas**;
  si un papel solo trae total, se guarda el total y ese paso reporta "faltan N" sin
  desglose de tallas (degradación elegante, nunca se rompe el cruce).
- **Q5 — pasos sin papel / internos.** Se respetan los `etapas_omitidas` del lote.
  Un paso que ocurre pero no genera papel deja su conteo como **"desconocido"**, que
  **no** dispara "faltan" (solo bloquea el "cerrado limpio" hasta tener el dato).
- **Gate anti-alertas-falsas (ON).** Todo conteo leído por OCR entra como **"por
  confirmar"**; alguien lo valida/corrige en el OS y solo ahí el cruce queda en firme
  y, si falta, dispara la alerta. Entrada manual por talla como respaldo cuando no
  hay foto o el OCR falla.
- **Destinatarios de la alerta.** Campanita al módulo `produccion_cortador` + al
  creador del lote (diseño), con escalamiento a Sebastián.
- **Quién justifica un faltante.** Admin / usuarios con autorización de producción
  (patrón Sebastián / María Alejandra).
- **Orden de entrega (por valor).** 1º el **eslabón de confección** (leer el conteo
  de salida de confección → cruzar vs lo cortado por talla → alertar), que resuelve
  el dolor declarado; luego la **vista de cierre de bodega** con toda la cadena; el
  resto (terminación por talla, afinar bodega) encima de esa base.

## Fase 2 (2026-10-29) — cadena completa y conteo final

Decisión de Sebastián: el conteo final se hace en una **pantalla del OS**
("Cierre de bodega", Producción). Lo digita quien recibe en bodega (insumos)
desde la remisión de terminación. Hallazgo que la motivó: ningún lote había
pasado de lavandería en el OS (12 asignado, 11 en confección, 7 lavandería);
el conteo final se hacía por fuera.

- Cuadre **por lote** (corte + referencia), nunca la suma del corte. Base =
  lo cortado de esa referencia → en corte de una sola referencia, lo cortado
  del padre → último recurso la curva, marcada "programado" (nunca "cerrado
  limpio" sobre lo programado).
- Paso `bodega` por talla con el mismo gate (por confirmar → confirmar →
  justificar). Confirmar = ingreso a bodega (`despachado`), aunque falte; el
  faltante queda abierto hasta justificarse y avisa a remisiones + creador.
- "Marcar ingreso a bodega" sin conteo queda **bloqueado** en el backend.
- Lavandería y terminación siguen en totales (sin trabajo extra para los
  talleres); la cadena compara cada paso contra el anterior con dato y marca
  dónde se perdió la prenda.
- Las etiquetas de terminación de un corte de una sola referencia ahora salen
  con lo cortado, no con la curva programada (mismo criterio de base).
