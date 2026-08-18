# Conector Dahua → MALE DENIM OS

Corre en un equipo **dentro de la red de la empresa**, lee las marcaciones del
control de acceso y las envía al sistema.

```
Dahua (LAN privada) ──► conector ──► cola SQLite ──HTTPS──► MALE DENIM OS
```

El Dahua **nunca se expone a internet**: solo hay tráfico *saliente* del
conector hacia el sistema. No hay puertos abiertos ni redirección.

Es el mismo patrón del agente de impresión que ya opera en la oficina: Python
sin librerías externas, `config.json`, bucle con reintento.

## Instalación

1. Copia esta carpeta al equipo. Necesita **Python 3.8+** y nada más.
2. Crea `config.json` a partir de `config.example.json`.
3. Arranca:
   ```
   python3 conector.py
   ```

**Arranque automático:** en Mac, un LaunchAgent (igual que el agente de
impresión). En Windows, un acceso directo al `.bat` en `shell:startup`.

## Configuración

| Campo | Qué es |
|---|---|
| `backend_url` | URL del sistema en Railway |
| `dispositivo_id` | UUID que da la pantalla de Dispositivos |
| `device_token` | Token del dispositivo, también de esa pantalla |
| `proveedor` | `mock`, `csv`, o el del Dahua real cuando esté |
| `poll_seconds` | Cada cuánto consulta. 60 s es suficiente |

> `config.json` **no se commitea**: trae el token. Está en `.gitignore`.

## Proveedores

| Proveedor | Para qué | Estado |
|---|---|---|
| `mock` | Probar el conector sin tocar el equipo | ✅ |
| `csv` | Cargar una exportación del Dahua o de SmartPSS | ✅ |
| `dahua_http` | El equipo real | ⏳ falta muestra de datos |

## El equipo: DHI-ASI6213S

Ya está identificado y sondeado (28-jul-2026):

- **HTTPS puerto 443** con **autenticación Digest MD5** — el puerto 80 cerrado
- **Puerto 37777 CERRADO**: el SDK nativo no aplica. El camino es la API CGI,
  que `urllib` maneja de fábrica

Falta confirmar **qué endpoints responde y con qué forma vienen los datos**.
Para eso:

```
python3 descubrir.py 10.30.1.4
```

Te pide la clave del equipo, la usa solo en memoria y te imprime el resultado.
No la guarda, no la muestra y no sale de tu equipo. Pásame esa salida y ajusto
el conector a lo que este aparato entrega de verdad.

## Qué garantiza

**Sin pérdida.** Los eventos van a una cola SQLite local y solo se borran
cuando el servidor confirma que los recibió. Si se cae internet un fin de
semana, al volver se envía todo.

**Sin duplicados.** Cada evento lleva clave de idempotencia; el servidor tiene
índice único. Reenviar el mismo lote no duplica nada — de hecho la respuesta
dice cuántos eran duplicados, y eso es señal de que funciona.

**Tolera caídas.** Sin conexión, espera cada vez más (hasta 10 min) en vez de
martillar la red.

Ambas garantías están probadas: se encolan eventos sin servidor, se levanta el
servidor, y se verifica que llegan todos exactamente una vez.

## Día a día

- El conector manda un **latido** en cada ciclo. Si deja de llegar, la pantalla
  de Dispositivos lo marca como desconectado.
- Un evento de alguien **sin mapear** no se descarta: se guarda y levanta
  incidencia. Al crear el mapeo se reprocesa y se recupera.
- El log queda en `conector.log`, al lado del script.

## Si el conector estuvo caído

Exporta los eventos del periodo desde SmartPSS y cárgalos:

1. `"proveedor": "csv"` y `"csv": {"ruta": "eventos.csv"}` en `config.json`
2. Corre el conector una vez
3. Devuelve `"proveedor"` a lo que estaba

Los que ya habían entrado se detectan como duplicados y no se cargan dos veces.

---

## Conexión al equipo real (verificado 2026-08-18)

El proveedor `dahua_http` ya está implementado y probado contra el
**DHI-ASI6213S** de la oficina. Para usarlo:

```json
{
  "dahua_host": "10.30.1.4",
  "dahua_usuario": "admin",
  "dahua_password": "…",
  "proveedor": "dahua_http",
  "poll_seconds": 60,
  "lote": 100
}
```

`config.json` está en `.gitignore` y debe quedar con permisos `600`:

```bash
chmod 600 config.json
```

### Qué revisar antes de dar por bueno un arranque

1. **El desfase de reloj.** `salud()` lo reporta. Un reloj corrido no produce
   ningún error: produce horas mal. El equipo tiene NTP activo contra
   `time.windows.com` con zona Bogotá; hoy va con 0 s de desfase.
2. **El cuadre.** `emitidos + excluidos` tiene que dar el total de registros
   del equipo. Si no, la paginación se cortó — y una carga incompleta se lee
   igual que una completa.
3. **Los excluidos.** El conector deja fuera a propósito las aperturas sin
   lector y los intentos fallidos, pero **siempre los cuenta**. Si el número de
   fallidos crece, hay alguien cuya cara el equipo dejó de reconocer.

### Lo que este equipo NO hace

- **No filtra por fecha.** `condition.StartTime/EndTime` se ignoran.
- **No distingue entrada de salida.** Todo llega como `Entry`.
- **No avisa de duplicados.** Registra la misma cara dos veces en segundos.

Los tres están medidos y compensados en `proveedores/dahua_http.py`, con la
evidencia anotada en el encabezado del archivo.
