# Agente de impresión — remisiones → RICOH

Imprime **automáticamente** cada remisión nueva (corte + insumos) en la RICOH,
apenas se guarda en el sistema.

## ¿Por qué un agente?

El backend del sistema vive en la **nube** (Railway) y no puede hablarle a una
impresora de la **red local**. Este agente corre en un equipo que SÍ ve la
impresora (el Mac donde está instalada) y hace de puente: le pregunta a la nube
qué imprimir y lo manda a la impresora.

```
Sistema (nube)  ──►  Agente (equipo con la impresora)  ──►  RICOH
   remisión nueva        baja el PDF                        imprime
```

## Dos formas de imprimir

1. **Cola del sistema (`lp`) — RECOMENDADO.** Para impresoras instaladas por
   **AirPrint/IPP** (como la RICOH M 320F de MALE'DENIM). El agente usa la cola
   que el equipo ya tiene configurada. No necesita IP ni puerto. Config:
   `"printer_queue": "RICOH_M_320F__88a84d_"`.
   (El nombre exacto de la cola se ve con `lpstat -p`.)
2. **RAW por IP:9100.** Para impresoras con "PDF Direct Print". Config:
   `"printer_ip": "192.168.x.x"`, `"printer_port": 9100`.

## Requisitos

1. Un equipo **encendido** que tenga acceso a la impresora (idealmente el mismo
   Mac donde está instalada la RICOH).
2. **Python 3.8+** (no hace falta instalar librerías).

## Instalación

1. Copia esta carpeta `tools/` al equipo.
2. Duplica `config.example.json` como **`config.json`** y llénalo (email/clave de
   un usuario del sistema con permiso de remisiones; el `printer_queue` ya viene).
3. Arráncalo: doble-clic en **`Iniciar_agente_impresion.command`** (Mac) o
   `.bat` (Windows), o en terminal `python3 agente_impresion_ricoh.py`.

Verás:
```
[10:32:01] ✓ Sesión iniciada en el sistema.
[10:32:13] → 1 remisión(es) pendiente(s) de imprimir.
[10:32:14]   ✓ Impresa REM-2026-000045 (38 KB) → RICOH
```

## Día a día

- Cada **12 s** revisa remisiones nuevas y las imprime.
- Si la impresora está apagada / sin tóner, **reintenta** (no pierde ni duplica).
- Las remisiones creadas **antes** de instalar el agente NO se imprimen.

## Arranque automático (opcional)

- **Mac**: un LaunchAgent (`~/Library/LaunchAgents/…plist`) para que arranque al
  iniciar sesión y se mantenga vivo.
- **Windows**: acceso directo al `.bat` en la carpeta *Inicio* (`shell:startup`).

## Reimprimir

`POST /api/produccion/impresion/{id}/reimprimir` (permiso de remisiones) vuelve
a encolar una remisión; el agente la toma en el siguiente ciclo.
