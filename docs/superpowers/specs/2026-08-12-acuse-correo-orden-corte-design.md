# MALE DENIM OS — Acuse de envío y entrega del correo de orden de corte · Spec de diseño

- **Fecha:** 2026-08-12
- **Módulo:** Producción → Orden de corte
- **Estado:** borrador para aprobación

---

## 1. Qué pasó

El 6 de julio, la orden de corte **2607-0017** se autorizó con el destinatario
`barreto.corte@hotmail.com`. El correo del cortador responsable (JHON JAIRO BARRETO)
es `johnj2397@hotmail.com`. El diseñador se equivocó al escribir la dirección.

Nadie se enteró. El sistema no avisó antes de mandar, no registró el resultado del
envío, y la pantalla dijo "Orden autorizada" igual que siempre.

Al revisar el código salieron dos defectos que hacen que este error —y cualquier otro
fallo de correo— sea invisible:

### Defecto 1 · El fallo de Resend se traga en silencio

En `autorizar_orden_corte()` (`backend/services/produccion.py:3061`):

```python
except Exception as e:
    print(f"[corte.autorizar] Resend falló, fallback a mailto: {e}")
```

Cuando Resend rechaza el envío, el error se imprime a stdout y la función cae al
fallback `mailto`. El frontend entonces hace
(`frontend/app/produccion/corte/[id]/page.tsx:602`):

```js
setMsg("Orden autorizada. Abriendo tu cliente de correo…");
window.location.href = c.mailto_url;
```

Si el navegador no tiene cliente de correo configurado —lo normal en Chrome con
Gmail web— eso no hace nada. Sin error, sin alerta. El diseñador lee "Orden
autorizada", ve la orden autorizada en la app, y sigue. El correo nunca salió.

### Defecto 2 · No hay registro de ningún envío

Verificado contra `information_schema`: la tabla `ordenes_corte` **no tiene ninguna
columna** que registre el envío. Ni `enviado_por`, ni fecha, ni id de Resend. El
resultado solo viaja en la respuesta HTTP al navegador y se pierde ahí.

Consecuencia operativa: **hoy es imposible saber, desde el sistema, qué correos
salieron.** Las 21 órdenes autorizadas hasta la fecha no tienen rastro.

## 2. Objetivo

Que el diseñador pueda ver, en la orden, si el correo salió, si llegó, o si falló —
y que pueda reenviarlo a otra dirección cuando se equivocó.

## 3. Alcance

| Incluye | No incluye |
|---|---|
| Registro de cada intento de envío | Reconstruir el historial de las 21 órdenes ya enviadas (no hay datos) |
| Estado de entrega consultado a Resend | Webhooks de Resend (se evaluó; se eligió consulta bajo demanda) |
| Fin del fallback silencioso a `mailto` | Cambiar el proveedor de correo |
| Aviso cuando el destinatario no cuadra | Bloquear el envío a un destinatario desconocido |
| Reenvío manual a otra dirección | Reenviar una orden ya `cortada` |

## 4. Modelo de datos

Tabla nueva **`correos_orden_corte`**, una fila por intento de envío.

Se descartó agregar columnas planas a `ordenes_corte`: el reenvío ya existe hoy
(`actualizar_indicaciones_corte`, `produccion.py:2038`, remanda el correo cuando
cambian las indicaciones), así que columnas planas se pisarían en el segundo envío y
perderían justo la historia que hace falta.

```sql
CREATE TABLE correos_orden_corte (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  orden_corte_id        uuid NOT NULL REFERENCES ordenes_corte(id) ON DELETE CASCADE,
  destinatarios         text[] NOT NULL,
  asunto                text,
  motivo                text NOT NULL,   -- autorizacion | reenvio_indicaciones | reenvio_manual
  resend_id             text,            -- id que devuelve Resend; NULL si ni se intentó
  estado                text NOT NULL,   -- ver tabla de estados
  error                 text,            -- texto verbatim del error de Resend
  enviado_por           text NOT NULL,   -- email del usuario que disparó el envío
  created_at            timestamptz NOT NULL DEFAULT now(),
  estado_actualizado_at timestamptz
);

CREATE INDEX idx_correos_oc_orden ON correos_orden_corte(orden_corte_id, created_at DESC);
```

Con esto, la orden 2607-0017 se leería:

```
1º  barreto.corte@hotmail.com   rebotado    6 jul 10:14
2º  johnj2397@hotmail.com       entregado   6 jul 10:31
```

## 5. Estados

Mapeo desde `last_event` de Resend. Valores confirmados contra la documentación de
Resend (`/docs/dashboard/webhooks/event-types`), no supuestos.

| `last_event` de Resend | `estado` interno | Se ve como |
|---|---|---|
| `sent` | `enviado` | 🕐 Enviado, esperando confirmación |
| `delivered` | `entregado` | ✅ Entregado |
| `bounced` | `rebotado` | ⚠️ Rebotó — la dirección no existe |
| `complained` | `spam` | ⚠️ Marcado como spam |
| `delivery_delayed` | `demorado` | 🕐 Demorado, reintentando |
| `failed` | `fallido` | ❌ No se entregó |
| `suppressed` | `suprimido` | ❌ Bloqueado por Resend |
| (no aplica) | `error_envio` | ❌ No se pudo enviar: *«error de Resend»* |

`error_envio` es el estado cuando Resend rechaza la petición y nunca llega a crear el
correo. Es el caso que hoy desaparece en silencio.

**Estados definitivos** (no se vuelven a consultar): `entregado`, `rebotado`, `spam`,
`suprimido`, `fallido`, `error_envio`.
**Estados en curso** (se reconsultan): `enviado`, `demorado`.

Resend también emite `opened` y `clicked`. Se ignoran a propósito: dependen de que el
cliente de correo cargue imágenes y no son fiables. Aquí importa si el correo llegó,
no si lo leyeron.

## 6. Consulta del estado de entrega

Se eligió **consultar bajo demanda** en vez de webhooks: cero infraestructura nueva,
cero configuración externa, y reusa el mismo patrón `httpx` que ya tiene el código.
El volumen lo permite (~1-2 órdenes al día).

`GET https://api.resend.com/emails/{resend_id}` devuelve `last_event`. Confirmado
contra la documentación de Resend (`/docs/api-reference/emails/retrieve-email`).

Regla: al abrir la orden (o el tablero), para cada envío **en curso** se consulta el
estado y se persiste. Los definitivos no se consultan. Sin `resend_id` no hay
consulta.

## 7. Envío: fin del fallback silencioso

Cambio en `autorizar_orden_corte()`:

1. Éxito → guardar fila con `estado='enviado'` y el `resend_id` de la respuesta.
2. Fallo de Resend → guardar fila con `estado='error_envio'` y el error **textual**.
   **No** se cae a `mailto` automáticamente.
3. Sin `RESEND_API_KEY` o sin destinatarios → `estado='error_envio'` con el motivo.

El `mailto` deja de ser un redirect automático que aparenta funcionar y pasa a ser un
botón explícito ("abrir en mi correo") disponible cuando el envío falló.

## 8. Reenvío a otra dirección

**Endpoint nuevo:** `POST /api/produccion/corte/{oc_id}/reenviar-correo`

```json
{ "destinatarios": ["johnj2397@hotmail.com"], "mensaje_extra": null }
```

Reusa `autorizar_orden_corte(..., solo_reenviar=True)`, que ya existe
(`produccion.py:2950`). Eso garantiza que el reenvío:

- **No** toca `estado`, `autorizada_por` ni `fecha_autorizacion`.
- **Sí** actualiza `destinatarios_correo` — la corrección queda guardada.
- Deja fila nueva con `motivo='reenvio_manual'`.

Permiso: `produccion_corte / modificar`, igual que autorizar.

Una orden ya `cortada` no se puede reenviar — `autorizar_orden_corte` ya lo rechaza y
se conserva ese comportamiento (si ya la cortaron, la información llegó de algún modo).

## 9. Aviso de destinatario que no cuadra

Al autorizar o reenviar, si algún destinatario no coincide con el `responsable_email`
de la orden **ni** con el email de algún usuario registrado, se pide confirmación:

> Vas a enviar a `barreto.corte@hotmail.com`, que no es el correo de JHON JAIRO
> BARRETO (`johnj2397@hotmail.com`). ¿Seguro?

**Es aviso, no bloqueo.** Se puede continuar. La razón: mandar a un correo externo es
un caso legítimo y raro; el objetivo es que sea deliberado, no impedirlo.

Se resuelve en el frontend, que ya carga `/usuarios-correo` y ya tiene la orden con
`responsable_email`. No requiere cambio de backend.

Por qué esto además del acuse: un correo mal escrito que **no existe** rebota y el
acuse lo atrapa. Pero si la dirección equivocada **sí existe** —le llegó a otra
persona real— Resend reporta `delivered` sin más. El acuse cubre "no llegó"; el aviso
cubre "llegó al lugar equivocado".

## 10. Interfaz

**Detalle de la orden** — bajo los destinatarios, el estado del último envío y el
historial si hubo más de uno:

```
✅ Entregado a johnj2397@hotmail.com · 11 ago 3:23 p.m.

⚠️ Rebotó en barreto.corte@hotmail.com — la dirección no existe   [Reenviar]

❌ No se pudo enviar: domain is not verified                       [Reintentar]  [Abrir en mi correo]
```

El botón **Reenviar** abre el campo de destinatario editable, precargado con el correo
registrado del cortador — no con el que falló. Corregir es un clic; insistir en el
equivocado exige escribirlo a propósito.

**Tablero / lista de órdenes** — un badge por orden con el mismo estado, para barrer de
un vistazo sin entrar a cada una.

**Órdenes anteriores al cambio** — muestran "sin registro de envío". Es la verdad: no
hay datos que mostrar. Para esas, la consulta sigue siendo manual en el panel de Resend.

## 11. Pruebas

1. **Mapeo de estados** — cada `last_event` de Resend cae en el `estado` correcto.
   Fixture con los 7 valores documentados.
2. **Fallo de Resend se registra como fallo** — un 403 de Resend deja
   `estado='error_envio'` con el texto del error, y la respuesta **no** reporta éxito.
   Es la prueba que fija el Defecto 1.
3. **El reenvío no pisa** — reenviar crea fila nueva, conserva la anterior, y no
   modifica `fecha_autorizacion`.
4. **Estados definitivos no se reconsultan** — abrir una orden ya `entregada` no hace
   ninguna llamada a Resend.

## 12. Archivos afectados

| Archivo | Cambio |
|---|---|
| `SUPABASE_MIGRATION_CORREOS_ORDEN_CORTE.sql` | nuevo — tabla e índice |
| `backend/services/produccion.py` | registrar envío, mapear estado, quitar fallback silencioso |
| `backend/api/produccion.py` | endpoint `reenviar-correo`; exponer estado en el detalle |
| `frontend/app/produccion/corte/[id]/page.tsx` | estado, historial, botón reenviar, aviso destinatario |
| `frontend/app/produccion/corte/page.tsx` | badge por orden en la lista de cortes |
| `tests/` | las 4 pruebas de §11 |

## 13. Riesgos

- **Una llamada extra a Resend por apertura de orden.** Acotada: solo para envíos en
  curso, y los estados definitivos no se consultan. En la práctica, una o dos llamadas
  los primeros minutos tras autorizar y ninguna después.
- **Resend puede tardar en reportar `delivered`.** Entre autorizar y ver el ✅ pueden
  pasar segundos o minutos. Por eso `enviado` se muestra como "esperando confirmación"
  y no como éxito.
- **El aviso de destinatario se puede ignorar.** Es deliberado. Si en la práctica el
  error se repite, el siguiente paso es quitar el campo de texto libre y obligar a
  elegir de la lista.
