@echo off
REM =========================================================================
REM  Clic derecho -> "Ejecutar como administrador"
REM  Instala el agente como tarea de Windows que:
REM    - arranca SOLO al prender el servidor (aunque nadie inicie sesion)
REM    - corre oculto, como SYSTEM
REM    - SIN limite de tiempo (antes Windows lo mataba a los 3 dias)
REM    - se AUTO-REINICIA si el proceso se cae (cada 1 min, hasta 999 veces)
REM  Y lo deja corriendo desde ya.
REM =========================================================================
setlocal
set "PS1=%~dp0agente_impresion.ps1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { $act=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%PS1%\"'); $trg=New-ScheduledTaskTrigger -AtStartup; $prn=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest; $set=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew; Register-ScheduledTask -TaskName 'AgenteImpresionMaleDenim' -Action $act -Trigger $trg -Principal $prn -Settings $set -Force | Out-Null; Start-ScheduledTask -TaskName 'AgenteImpresionMaleDenim'; Write-Host '[OK] Agente instalado y corriendo (sin limite de tiempo, con auto-reinicio).' } catch { Write-Host ('[X] Error: ' + $_.Exception.Message); Write-Host '    (Asegurate de ejecutarlo como ADMINISTRADOR)'; exit 1 }"

echo.
echo    Log del agente: %~dp0agente.log
echo    En la app: Produccion -^> Impresion muestra "Agente en linea".
pause
