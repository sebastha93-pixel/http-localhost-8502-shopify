# Plan de Implementación — Módulo Personal

MALE DENIM OS · Estado: **Fase 1 completa, esperando aprobación**

---

## Prerrequisitos (bloquean la Fase 2)

### P1 — Sincronizar el repositorio local

El checkout local está **126 commits detrás de `origin/main`**. Módulos completos
que existen en producción y no aquí: `fiscal_logic.py`, `postventa_fiscal.py`,
`salud.py`, `drive_sheet.py`, `lavado_render.py`.
`backend/services/produccion.py` difiere en **2.510 líneas**.

Escribir código sobre este árbol produciría conflictos masivos.

### P2 — Aterrizar `timeutils` en producción

`backend/core/timeutils.py` + sus 25 tests existen **solo sin commitear**, y ya
hay 22 call sites cableados en 9 módulos. No están en `origin/main`.

Resuelven que Postgres recorta la fracción de segundo y que
`datetime.fromisoformat` de **Python 3.10** —el que corre Railway— revienta con
fracciones de 1, 2, 4 o 5 dígitos.

Un módulo de asistencia es puro timestamp. Sin esto, hereda un bug que vacía
datos en silencio. **Es el prerrequisito técnico más importante.**

---

## Fases

### Fase 2 — Base del módulo

Feature flags con helper unificado · migración SQL · servicios base · RBAC ·
auditoría de módulo · seeds de configuración (sedes, áreas, tipos de permiso,
festivos colombianos, reglas por defecto).

*Cierra cuando:* la migración está aplicada, el módulo aparece en el menú detrás
del flag, y `test_personal_rbac.py` pasa.

### Fase 3 — Eventos y motor ← **el corazón**

Ingesta idempotente · motor puro · detección de incidencias · reprocesamiento ·
recálculo nocturno.

*Cierra cuando:* **los 36 casos de la especificación pasan**, más los 12 tests de
invariantes. Aquí no se acelera: si el motor no es determinista, todo lo demás
hereda datos poco confiables.

### Fase 4 — Permisos y compensaciones

FSM de permisos · doble aprobación · planes y bloques · libro de tiempo ·
validación contra marcaciones reales · horas extras.

*Cierra cuando:* el flujo completo corre end-to-end con datos demo, y los tests
de append-only pasan.

### Fase 5 — Frontend

13 páginas: dashboard, empleados, asistencia, permisos, compensaciones, extras,
incidencias, horarios, turnos, calendario, novedades, dispositivos, reportes,
más el autoservicio `/personal/mi-tiempo`.

*Cierra cuando:* `npx tsc --noEmit` limpio y la UI es indistinguible del resto
del OS.

### Fase 6 — Conector

Mock · CSV · agente local (clon del de impresión) · cola SQLite offline ·
health checks · documentación de instalación.

*Cierra cuando:* el agente corre contra el simulador y sobrevive a una
desconexión de red sin perder ni duplicar eventos.

### Fase 7 — Reportes y nómina

16 reportes exportables · novedades · cierres de periodo · reapertura auditada ·
exportación con registro de usuario y filtros.

*Cierra cuando:* se genera un archivo de novedades descargable con trazabilidad
completa.

### Fase 8 — Seguridad y calidad

Pruebas de seguridad · E2E · rendimiento · revisión de privacidad ·
los 14 documentos finales.

---

## Plan de archivos

### Nuevos — backend (18)

```
backend/api/personal.py                          router principal
backend/services/personal_empleados.py           CRUD, jerarquía, alcance
backend/services/personal_eventos.py             ingesta idempotente
backend/services/personal_motor.py               ★ cálculo puro, sin I/O
backend/services/personal_asistencia.py          orquesta motor + persistencia
backend/services/personal_permisos.py            FSM, aprobaciones
backend/services/personal_compensacion.py        planes, bloques, validación
backend/services/personal_libro.py               libro mayor append-only
backend/services/personal_nomina.py              novedades, cierres, export
backend/services/personal_reglas.py              resolución por especificidad
backend/services/personal_dispositivos.py        salud, tokens, reprocesamiento
backend/services/personal_auditoria.py           registro de módulo
backend/services/personal_notificaciones.py      dedup persistente
backend/core/personal_scheduler.py               cron nocturno
backend/core/flags.py                            helper unificado de flags
backend/integrations/dahua/base.py               AccessControlProvider
backend/integrations/dahua/mock.py               simulador
backend/integrations/dahua/csv_provider.py       importador
backend/integrations/dahua/dahua_placeholder.py  estructura, sin endpoints falsos
```

### Nuevos — SQL (3)

```
SUPABASE_MIGRATION_PERSONAL.sql            ✅ escrito (24 tablas)
SUPABASE_MIGRATION_PERSONAL_SEEDS.sql      solo desarrollo
SUPABASE_MIGRATION_PERSONAL_ROLLBACK.sql   documentado, no automático
```

### Nuevos — frontend (20)

```
frontend/app/personal/page.tsx                    dashboard
frontend/app/personal/mi-tiempo/page.tsx          autoservicio
frontend/app/personal/empleados/page.tsx
frontend/app/personal/empleados/[id]/page.tsx
frontend/app/personal/asistencia/page.tsx
frontend/app/personal/asistencia/[empleadoId]/[fecha]/page.tsx
frontend/app/personal/permisos/page.tsx
frontend/app/personal/permisos/nuevo/page.tsx
frontend/app/personal/permisos/[id]/page.tsx
frontend/app/personal/compensaciones/page.tsx
frontend/app/personal/extras/page.tsx
frontend/app/personal/incidencias/page.tsx
frontend/app/personal/horarios/page.tsx
frontend/app/personal/turnos/page.tsx             planificador de tienda
frontend/app/personal/calendario/page.tsx
frontend/app/personal/nomina/page.tsx
frontend/app/personal/dispositivos/page.tsx
frontend/app/personal/reportes/page.tsx
frontend/components/personal/*.tsx                6 componentes
frontend/lib/personal.ts                          tipos + helpers
```

### Nuevos — conector (7)

```
dahua-connector/conector.py            clon del agente de impresión
dahua-connector/config.example.json
dahua-connector/cola.py                SQLite offline
dahua-connector/Dockerfile
dahua-connector/README.md
dahua-connector/Iniciar_conector.command   Mac
dahua-connector/Iniciar_conector.bat       Windows
```

### Nuevos — tests (8)

```
tests/test_personal_motor.py           ★ los 36 casos
tests/test_personal_invariantes.py     ★ los 12 de blindaje
tests/test_personal_permisos.py        FSM
tests/test_personal_compensacion.py
tests/test_personal_libro.py           append-only
tests/test_personal_rbac.py            aislamiento
tests/test_personal_eventos.py         idempotencia
tests/test_personal_api.py             contratos
```

### Nuevos — documentación (14)

Los 8 restantes de tu lista: `TIME_MANAGEMENT_API.md`,
`TIME_MANAGEMENT_TESTING.md`, `TIME_MANAGEMENT_DEPLOYMENT.md`,
`TIME_MANAGEMENT_ROLLBACK.md`, `BIOMETRIC_DATA_HANDLING.md`,
`SECURITY_TIME_ATTENDANCE.md`, `DAHUA_CONNECTOR_SETUP.md`,
`DAHUA_CONNECTOR_SECURITY.md`, `TIME_MANAGEMENT_USER_GUIDE.md`,
`TIME_MANAGEMENT_HR_GUIDE.md`, `TIME_MANAGEMENT_TECHNICAL_GUIDE.md`.

**Ya escritos (5):** `TIME_MANAGEMENT_ARCHITECTURE.md`,
`TIME_MANAGEMENT_DOMAIN_RULES.md`, `TIME_MANAGEMENT_RBAC.md`,
`DAHUA_INTEGRATION_REQUIREMENTS.md`, `TIME_MANAGEMENT_IMPLEMENTATION_PLAN.md`.

### Modificados — 7, todos aditivos

| Archivo | Cambio | Riesgo |
|---|---|---|
| `backend/main.py` | 1 línea: `include_router` tras el flag | Mínimo |
| `backend/services/usuarios.py` | Grupo `personal` en `MODULOS_GRUPOS` | Bajo — aditivo |
| `backend/core/config.py` | 4 flags | Mínimo |
| `frontend/lib/auth.ts` | Espejo RBAC + labels | Bajo — aditivo |
| `frontend/lib/nav.ts` | Grupo "Personal" | Bajo — aditivo |
| `frontend/app/usuarios/page.tsx` | `SUBMODULOS` de personal | Bajo |
| `requirements.txt` | Sin dependencias nuevas previstas | Ninguno |

**Total: ~70 nuevos, 7 modificados.** Ningún archivo existente cambia de
comportamiento; todo el módulo vive tras `TIME_MANAGEMENT_ENABLED=false`.

---

## Protocolo por fase

Al cerrar cada fase:

1. Resumen de lo construido
2. Lista de archivos creados y modificados
3. `python3 -m pytest tests/ -q` + `npx tsc --noEmit`
4. Reporte de resultados — **incluyendo lo que falle**
5. Decisiones de diseño documentadas
6. Commit en rama propia

Línea base a mantener: **56 tests en verde, typecheck limpio.** Si una fase baja
ese número, no cierra.

---

## Rollback

| Nivel | Acción | Reversible |
|---|---|---|
| 1 | `TIME_MANAGEMENT_ENABLED=false` | Inmediato, sin deploy |
| 2 | Revertir el commit | Sí |
| 3 | `DROP TABLE personal_*` | Sí — ninguna tabla existente se toca |

La migración **solo crea**. No altera, no renombra, no borra nada existente.
El único vínculo con lo actual es `personal_empleados.usuario_id`, que es
`ON DELETE SET NULL` — borrar un usuario nunca borra su histórico de asistencia.

---

## Decisiones abiertas

| # | Decisión | Recomendación |
|---|---|---|
| 1 | Formato de exportación a nómina | La integración Siigo existente es **contable, no de nómina** (`siigo_get/post`, documentos soporte). No hay API de nómina. Propongo exportador tras adaptador + Excel genérico, y confirmar el formato de Siigo Nómina en Fase 7 |
| 2 | Estrenar `recharts` para los gráficos | Sí — ya es dependencia con 0 imports; mejor que duplicar SVG a mano por tercera vez |
| 3 | Tipos de permiso a sembrar | Requiere validación de abogado laboral antes del lanzamiento |
| 4 | Quién es supervisor de quién | Se necesita el organigrama real para `supervisor_id` |

## Decisiones cerradas

| Decisión | Valor | Impacto |
|---|---|---|
| Autoservicio | **Todos los empleados con login** | `/personal/mi-tiempo` fuera del RBAC de módulos; 13 páginas + autoservicio |
| Destino de nómina | **Siigo** | La integración actual es contable, no de nómina → exportador tras adaptador |
| Tipos de jornada | **Administración fija · tienda rotativa · producción propia** | Motivó `personal_turnos_planificados` y la resolución en cascada |
| Periodo de nómina | **Quincenal** | Cierres el 15 y el último día del mes. Encaja con el plazo de compensación "hasta cierre de quincena". `personal_periodos.tipo = 'quincenal'` por defecto y el seed genera el calendario del año |
