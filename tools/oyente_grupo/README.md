# Oyente del grupo de producción

Trae al OS lo que el equipo escribe en el grupo de WhatsApp de producción.
**Fase 1: espejo. No interpreta nada y no contesta en el grupo.**

## Por qué no se usa la API oficial

La Groups API de Meta no puede leer el grupo que ya existe:

- exige **Official Business Account** (check verde)
- tope de **8 participantes**
- solo entra a **grupos que ella misma crea** — a uno nacido en el WhatsApp
  normal no hay forma de meterla
- no está disponible para números de la app WhatsApp Business

Así que un **número dedicado** entra al grupo como un participante más y este
proceso, un dispositivo vinculado (como WhatsApp Web), reenvía lo que pasa.

## El costo que hay que aceptar

WhatsApp **no soporta este uso** y el número que escucha puede quedar
bloqueado. Por eso va un número dedicado que no hace nada más: si lo bloquean,
el grupo sigue vivo y solo se calla el oyente.

**Nunca usar acá el número de la WABA del CRM.** Ese está consumido por la API
oficial y no puede ser dispositivo vinculado.

## Instalación (servidor MDS)

1. Copiar esta carpeta a `C:\male-oyente-grupo`
2. PowerShell **como administrador**:
   ```
   cd C:\male-oyente-grupo
   .\instalar.ps1
   ```
   Pide el `GRUPO_WA_SECRET` — está en el archivo del Escritorio del Mac y ya
   quedó puesto en Railway.
3. Vincular el número: `.\arrancar.ps1` y escanear el QR **con el celular del
   número dedicado**.
4. Al conectarse imprime los grupos. Copiar el id del de producción a
   `GRUPO_JID` en `.env`, y activar la tarea:
   ```
   schtasks /Change /TN "MALE Oyente Grupo Produccion" /ENABLE
   schtasks /Run    /TN "MALE Oyente Grupo Produccion"
   ```

## Qué hace y qué no

| Hace | No hace |
|---|---|
| Reenvía texto, autor y hora | Interpretar, deducir estados |
| Filtra: solo el grupo configurado | Leer otros chats del número |
| Encola en disco si el OS no responde | Descargar archivos (fase 1) |
| Reintenta cada 2 min | Contestar en el grupo |

La cola en disco importa: sin ella, un corte de internet de diez minutos
borraría para siempre lo que se escribió en esos diez minutos, y nadie se daría
cuenta — el grupo se ve normal y el OS simplemente queda con un hueco.

El endpoint del OS es idempotente por `wa_message_id`, así que reintentar de
más nunca duplica.

## Si deja de llegar información

- `C:\male-oyente-grupo\oyente.log`
- En el OS: `GET /api/produccion/grupo/estado` dice cuándo llegó el último
  mensaje. Ojo: un grupo callado un domingo se ve igual que un oyente muerto;
  se distingue mirando la hora contra el horario de la fábrica.
- Si el log dice `SESIÓN CERRADA`: borrar la carpeta `sesion` y volver a
  escanear el QR.
