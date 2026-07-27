# RBAC — Módulo Personal

Integración con el sistema de permisos existente de MALE DENIM OS.
**Cambio aditivo**: ningún permiso actual cambia de significado.

---

## 1. Cómo funciona el RBAC hoy (contexto)

- **Roles** (`backend/services/usuarios.py`): `admin`, `lector`, `user`
  (+ legacy `operador` → `user`, `lectura` → `lector`).
- **Acciones**: `ver`, `modificar`, `borrar`.
- **Permisos**: JSON en `usuarios.permisos`, asignados por **grupo**
  (`{"produccion": ["ver","modificar"]}`), resueltos módulo → grupo.
- **Enforcement**: `require_permission(modulo, accion)` en el backend, espejo
  manual en `frontend/lib/auth.ts` para el menú.
- `admin` siempre pasa. `lector` solo `ver`.

---

## 2. Grupo nuevo: `personal`

```python
# backend/services/usuarios.py — MODULOS_GRUPOS
"personal": ["personal", "personal_asistencia", "personal_permisos",
             "personal_dispositivos", "personal_nomina", "personal_config"],
```

| Módulo | Cubre |
|---|---|
| `personal` | Dashboard, empleados, calendario, reportes |
| `personal_asistencia` | Jornadas, incidencias, correcciones, recálculo |
| `personal_permisos` | Solicitudes, aprobaciones, compensaciones, extras |
| `personal_dispositivos` | Dahua, conector, reprocesamiento, datos técnicos |
| `personal_nomina` | Novedades, exportación, cierres de periodo |
| `personal_config` | Reglas laborales, horarios, turnos, tipos de permiso |

### Autoservicio: fuera del RBAC de módulos

`/personal/mi-tiempo` **no** requiere permiso de módulo. Todo usuario
autenticado que esté enlazado a un empleado
(`personal_empleados.usuario_id = user.id`) lo tiene.

*Por qué:* si el autoservicio dependiera de un permiso, habría que asignárselo
uno por uno a 25 personas y mantenerlo. Y un permiso de módulo tiende a leerse
como "puede ver asistencia" en general — exactamente lo que no queremos.

El aislamiento es por dato, no por rol: `empleado_id` se deriva **siempre** del
JWT. Nunca de un parámetro del request.

---

## 3. Matriz de permisos por perfil

| Perfil | Permisos asignados |
|---|---|
| **Empleado** | *(ninguno — solo autoservicio)* |
| **Jefe inmediato** | `personal_permisos: [ver, modificar]`, `personal_asistencia: [ver]` |
| **Talento Humano** | `personal: [ver, modificar]`, `personal_asistencia: [ver, modificar]`, `personal_permisos: [ver, modificar]`, `personal_config: [ver, modificar]` |
| **Nómina** | `personal_nomina: [ver, modificar]`, `personal: [ver]` |
| **Admin técnico** | `personal_dispositivos: [ver, modificar]` |
| **Gerencia** | `personal: [ver]`, `personal_asistencia: [ver]`, `personal_nomina: [ver]` |

### Capacidades detalladas

**Empleado** (autoservicio) — ver su asistencia, sus permisos, su saldo, sus
incidencias; solicitar permiso; adjuntar soporte; proponer compensación;
solicitar corrección; cancelar solicitudes en estado cancelable.

**Jefe inmediato** — todo lo del empleado, más: ver a su equipo
(`supervisor_id = su empleado_id`), aprobar/rechazar permisos, evaluar cobertura
operativa, aprobar compensaciones, revisar incidencias del equipo, aprobar horas
extras.

**Talento Humano** — clasificar permisos, validar soportes, resolver incidencias,
ajustar horarios y turnos, preparar novedades, configurar reglas laborales.

**Nómina** — revisar novedades aprobadas, marcar como exportadas, generar el
archivo, consultar trazabilidad. **No** puede aprobar permisos ni editar jornadas.

**Admin técnico** — configurar dispositivos, ver estado del conector, reprocesar
eventos, gestionar mapeos, rotar credenciales. **No** ve datos de nómina ni
aprueba permisos.

**Gerencia** — solo lectura: dashboard global, indicadores por área y sede,
ausentismo, horas pendientes, incidencias, tendencias.

---

## 4. Reglas especiales

### 4.1 Alcance del jefe: filtrado por dato, no por rol

`personal_permisos:ver` no significa "ver todos los permisos". Un jefe ve los de
su equipo; TH ve todos.

Se resuelve con un helper análogo a `_es_solo_cortador()`
([produccion.py:700](../backend/api/produccion.py:700)):

```python
def _alcance_empleados(user: CurrentUser) -> Optional[list[str]]:
    """None = todos (TH/admin). Lista = solo esos empleados (jefe)."""
```

Regla: si tiene `personal:ver` o `personal_asistencia:modificar` → alcance total.
Si solo tiene `personal_permisos` → alcance = su equipo + él mismo.

### 4.2 Datos técnicos: degradación, no rechazo

Serial, IP y `configuracion_json` del dispositivo se devuelven **enmascarados**
salvo a `personal_dispositivos:ver`. Se sigue el patrón existente de
`tiene_permiso_costos()` ([security.py:271](../backend/core/security.py:271)):
la respuesta se degrada, no se rechaza.

```python
if not tiene_permiso(user, "personal_dispositivos", "ver"):
    d["ip_local"]     = _enmascarar_ip(d["ip_local"])       # 192.168.x.x
    d["numero_serie"] = _enmascarar_serie(d["numero_serie"]) # ABC…XY9
    d.pop("configuracion_json", None)
```

### 4.3 Acciones que exigen permiso explícito

Con `require_permission_estricto` (sin herencia de roles legacy):

| Acción | Permiso |
|---|---|
| Reabrir un periodo cerrado | `personal_nomina:borrar` |
| Ajuste manual en el libro de tiempo | `personal_asistencia:borrar` |
| Rotar token del conector | `personal_dispositivos:borrar` |
| Reprocesar eventos masivamente | `personal_dispositivos:modificar` |

*Por qué `borrar`:* la acción existe en el sistema y casi no se usa (3 endpoints
hoy). Es el nivel más alto disponible, y estas cuatro operaciones pueden alterar
histórico. No requieren esquema nuevo.

### 4.4 Separación de funciones

Quien **aprueba** un permiso no debería ser quien **lo exporta a nómina**.
Roles distintos por diseño: `personal_permisos` ≠ `personal_nomina`.

El sistema no lo impide por código (un admin tiene todo), pero la separación
existe en la configuración recomendada y queda registrada en auditoría.

---

## 5. Puntos de toque de la implementación

Los 7 lugares, ya mapeados en la auditoría de Fase 0:

| # | Archivo | Cambio |
|---|---|---|
| 1 | `backend/services/usuarios.py` | Grupo `personal` en `MODULOS_GRUPOS` |
| 2 | `frontend/lib/auth.ts` | Espejo en `GRUPOS_PERMISOS` |
| 3 | `frontend/lib/auth.ts` | `GRUPO_LABEL["personal"] = "Personal"` |
| 4 | `frontend/lib/auth.ts` | 6 entradas en `MODULO_LABEL` |
| 5 | `frontend/lib/nav.ts` | Grupo "Personal" en `NAV_GROUPS` |
| 6 | `frontend/app/usuarios/page.tsx` | `SUBMODULOS` para desglose fino |
| 7 | endpoints | `Depends(require_permission("personal_*", accion))` |

Sin cambios de SQL: `usuarios.permisos` es JSON libre.

> **Deuda conocida.** La lógica de permisos está duplicada manualmente entre
> backend y frontend, por diseño del proyecto (comentado en
> `frontend/lib/auth.ts:179`). Existe `GET /api/auth/usuarios/catalogo` que
> serviría como fuente única, pero el frontend no lo consume. Unificarlo excede
> este módulo; se deja anotado.

---

## 6. Menú

```typescript
{
  title: "Personal",
  items: [
    { label: "Mi tiempo",     href: "/personal/mi-tiempo" },  // sin permiso
    { label: "Dashboard",     href: "/personal",             permiso: "personal" },
    { label: "Empleados",     href: "/personal/empleados",   permiso: "personal" },
    { label: "Asistencia",    href: "/personal/asistencia",  permiso: "personal_asistencia" },
    { label: "Permisos",      href: "/personal/permisos",    permiso: "personal_permisos" },
    { label: "Compensaciones",href: "/personal/compensaciones", permiso: "personal_permisos" },
    { label: "Horas extras",  href: "/personal/extras",      permiso: "personal_permisos" },
    { label: "Incidencias",   href: "/personal/incidencias", permiso: "personal_asistencia" },
    { label: "Horarios",      href: "/personal/horarios",    permiso: "personal_config" },
    { label: "Calendario",    href: "/personal/calendario",  permiso: "personal|personal_permisos" },
    { label: "Novedades",     href: "/personal/nomina",      permiso: "personal_nomina" },
    { label: "Dispositivos",  href: "/personal/dispositivos",permiso: "personal_dispositivos" },
    { label: "Reportes",      href: "/personal/reportes",    permiso: "personal" },
  ],
}
```

`gruposVisibles()` oculta el grupo entero si no queda ningún item visible, así
que un empleado sin permisos de módulo ve solo "Mi tiempo".

> **Nota.** El menú actual tiene 3 links a rutas inexistentes (`/facturacion`,
> `/inteligencia`, `/reportes`) que devuelven 404. No los toco — es un problema
> preexistente, ajeno a este módulo. Vale la pena arreglarlo aparte.

---

## 7. Pruebas de autorización

| Test | Verifica |
|---|---|
| `test_empleado_no_ve_asistencia_ajena` | Aislamiento por dato |
| `test_jefe_solo_ve_su_equipo` | `_alcance_empleados` |
| `test_nomina_no_puede_aprobar_permiso` | Separación de funciones |
| `test_tecnico_no_ve_novedades_nomina` | Aislamiento por módulo |
| `test_ip_enmascarada_sin_permiso` | Degradación §4.2 |
| `test_reabrir_periodo_requiere_estricto` | §4.3 |
| `test_usuario_sin_permisos_recibe_403` | Caso 29 de la spec |
