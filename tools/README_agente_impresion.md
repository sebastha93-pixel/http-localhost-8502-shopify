# Agente de impresión — remisiones → RICOH por IP

Imprime **automáticamente** cada remisión nueva (corte + insumos) en la RICOH
de la red local de MALE'DENIM, apenas se guarda en el sistema.

## ¿Por qué un agente?

El backend del sistema vive en la **nube** (Railway). Una impresora en tu **red
local** solo es visible dentro de esa red (IP tipo `192.168.x.x`), así que la
nube no puede hablarle directo. Este agente corre en un PC de tu red y hace de
puente: le pregunta a la nube qué imprimir y se lo manda a la RICOH por su IP.

```
Sistema (nube)  ──►  Agente (PC en tu red)  ──►  RICOH (192.168.x.x:9100)
   remisión nueva        baja el PDF                imprime
```

## Requisitos

1. Un **PC siempre encendido** en la misma red que la RICOH (Windows o Mac).
2. **Python 3.8+** instalado (no hace falta instalar librerías).
3. En la **RICOH**: activar **PDF Direct Print** (impresión PDF directa por el
   puerto **9100 / RAW / JetDirect**). Es estándar en las RICOH MP/IM; en el
   panel suele estar en *Ajustes de red → Impresión* o vía Web Image Monitor.

## Instalación (una sola vez)

1. Copia la carpeta `tools/` a ese PC.
2. Duplica `config.example.json` como **`config.json`** y llénalo:
   - `backend_url`: la URL del sistema (Railway).
   - `email` / `password`: un usuario del sistema con permiso de remisiones
     (recomendado crear uno dedicado, ej. `impresion@maledenim.com`).
   - `printer_ip`: la IP de la RICOH (la ves en el panel de la impresora o en
     Web Image Monitor).
   - `printer_port`: normalmente `9100`.
3. Arráncalo:

   ```bash
   python3 agente_impresion_ricoh.py
   ```

   Verás algo como:
   ```
   [10:32:01] ✓ Sesión iniciada en el sistema.
   [10:32:01] Agente de impresión MALE'DENIM
   [10:32:13] → 1 remisión(es) pendiente(s) de imprimir.
   [10:32:14]   ✓ Impresa REM-2026-000045 (38 KB) → RICOH
   ```

## Cómo funciona el día a día

- Cada **12 s** el agente revisa si hay remisiones nuevas y las imprime.
- Si la impresora está apagada o sin papel, **reintenta** hasta lograrlo (no
  pierde la remisión ni la imprime dos veces).
- Las remisiones que ya existían **antes** de instalar el agente NO se imprimen
  (solo las nuevas).

## Que arranque solo al prender el PC (opcional)

- **Windows**: crea un acceso directo a `python3 agente_impresion_ricoh.py` en
  la carpeta *Inicio* (`shell:startup`).
- **Mac**: un `launchd` plist, o *Ítems de inicio de sesión* con un `.command`
  que ejecute el script.

## Reimprimir una remisión

Si necesitas reimprimir una, desde el sistema se puede volver a encolar
(endpoint `POST /api/produccion/impresion/{id}/reimprimir`, permiso de
remisiones). El agente la tomará en el siguiente ciclo.
