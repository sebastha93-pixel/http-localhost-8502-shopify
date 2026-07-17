@echo off
REM Doble-clic en Windows para arrancar el agente de impresion.
REM Debe estar en la MISMA carpeta que agente_impresion_ricoh.py y config.json.
cd /d "%~dp0"
echo Iniciando agente de impresion MALE'DENIM...  (cierra esta ventana para detenerlo)
python agente_impresion_ricoh.py
pause
