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
| `dahua_http` · `dss_express` | El equipo real | ⏳ faltan datos |

Lo que falta para el equipo real: **modelo exacto, firmware y protocolo**. Ver
`docs/DAHUA_INTEGRATION_REQUIREMENTS.md`. Mientras tanto el módulo se
desarrolla y se prueba completo con `mock`.

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
