#!/bin/bash
# Doble-clic en Mac para arrancar el agente de impresión.
# Debe estar en la MISMA carpeta que agente_impresion_ricoh.py y config.json.
cd "$(dirname "$0")" || exit 1
echo "Iniciando agente de impresión MALE'DENIM…  (cierra esta ventana para detenerlo)"
exec python3 agente_impresion_ricoh.py
