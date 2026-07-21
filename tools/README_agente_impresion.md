# Agente de impresión MALE'DENIM

Imprime **automáticamente** lo que el sistema encola:

| Documento | Cuándo se encola | Impresora | Formato |
|---|---|---|---|
| Remisión (corte + insumos) | al guardar cualquier remisión | **RICOH** | PDF |
| Stickers de código de barras (1 por prenda, ref+talla) | al crear remisión de **terminación** | **Honeywell** | ZPL |
| Instrucciones de lavado (por tela/referencia) | al crear remisión de **terminación** | **SAT** | ZPL |

## Arquitectura

El backend vive en la nube y no alcanza impresoras locales. Cada **agente**
corre en un equipo que sí las ve, y puede haber **varios agentes en redes
distintas** — cada uno imprime SOLO las impresoras de su `config.json`:

```
                          ┌── Agente Mac (oficina) ──► RICOH        (PDF remisiones)
Sistema (nube) ── cola ───┤
                          └── Agente Windows (taller) ─► Honeywell  (stickers ZPL)
                                                      └► SAT        (lavado ZPL)
```

## Instalación de un agente

1. Copia esta carpeta al equipo (necesita **Python 3.8+**, sin librerías).
2. Crea `config.json` desde el ejemplo:
   - **Mac oficina (RICOH):** `config.example.json` — usa la cola del sistema
     (`lpstat -p` muestra el nombre).
   - **PC Windows del taller (térmicas):** `config.example.taller.json` — pon
     las **IP** de la Honeywell y la SAT (se ven en el menú/config de cada
     impresora o imprimiendo su página de configuración).
3. Arranca: doble-clic a `Iniciar_agente_impresion.command` (Mac) o
   `Iniciar_agente_impresion.bat` (Windows), o `python3 agente_impresion_ricoh.py`.

Arranque automático: Mac → LaunchAgent (ya montado en el Mac de la oficina);
Windows → acceso directo al `.bat` en `shell:startup`.

## Térmicas (Honeywell / SAT)

- Se les envía **ZPL crudo al puerto 9100** (RAW). Ambas marcas lo emulan de
  fábrica en la mayoría de modelos; si algún modelo no habla ZPL, se cambia la
  plantilla en el backend (una función), no el agente.
- Medidas de etiqueta: definidas en el backend
  (`ZPL_STICKER_*` / `ZPL_LAVADO_*` en `backend/services/produccion.py`,
  203 dpi ≈ 8 dots/mm). Ajustar ahí si el medio real es de otro tamaño.
- Las **instrucciones de lavado** salen del campo *Instrucciones de lavado* del
  precosteo de cada referencia (editable en el detalle del precosteo). Si está
  vacío se imprime un texto genérico de cuidado.

## Día a día

- Poll cada 12 s. Si una impresora está apagada/sin papel, **reintenta** sin
  perder ni duplicar (cada trabajo se marca impreso solo cuando salió).
- Un agente ignora los trabajos de impresoras que no atiende (los toma el otro).
- Reimprimir una remisión: `POST /api/produccion/impresion/{id}/reimprimir`.
