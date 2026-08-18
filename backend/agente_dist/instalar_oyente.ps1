# ═══════════════════════════════════════════════════════════════════════════
#  OYENTE DEL GRUPO DE PRODUCCION — instalador de una linea
# ═══════════════════════════════════════════════════════════════════════════
#  En el servidor MDS, PowerShell COMO ADMINISTRADOR:
#
#      irm https://backend-production-21f0.up.railway.app/api/produccion/agente/instalar_oyente.ps1 | iex
#
#  Descarga el oyente, instala dependencias, deja una tarea de Windows que
#  arranca con la maquina, y pide el codigo de pareo para vincular el numero.
#
#  NO pregunta por el grupo: eso se elige desde el OS y el oyente lo consulta
#  en cada latido. Asi no hay que volver a esta maquina para cambiarlo.
# ═══════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
$BASE    = "https://backend-production-21f0.up.railway.app"
$carpeta = "C:\male-oyente-grupo"
$tarea   = "MALE Oyente Grupo Produccion"

Write-Host ""
Write-Host "=== Oyente del grupo de produccion ===" -ForegroundColor Cyan

# 1 · Node
try { $v = (node --version) } catch { $v = $null }
if (-not $v) {
  Write-Host "Node no esta instalado." -ForegroundColor Red
  Write-Host "Instalalo desde https://nodejs.org (version LTS) y vuelve a correr esta linea." -ForegroundColor Red
  return
}
Write-Host "Node $v" -ForegroundColor Green

# 2 · Carpeta y archivos, bajados del backend (misma via que el agente de impresion)
New-Item -ItemType Directory -Force -Path $carpeta | Out-Null
Set-Location $carpeta
foreach ($f in @("oyente.js", "package.json")) {
  Invoke-WebRequest -Uri "$BASE/api/produccion/agente/$f" -OutFile "$carpeta\$f" -UseBasicParsing
  Write-Host "bajado $f" -ForegroundColor Green
}

# 3 · Dependencias
Write-Host "Instalando dependencias (un par de minutos)..."
npm install --omit=dev --silent
Write-Host "dependencias listas" -ForegroundColor Green

# 4 · Configuracion. El secreto y el numero se piden aca y quedan SOLO en este
#     archivo: nunca en un script publico ni en GitHub.
if (-not (Test-Path "$carpeta\.env")) {
  Write-Host ""
  Write-Host "Configuracion (una sola vez):" -ForegroundColor Cyan
  $secreto = Read-Host "  GRUPO_WA_SECRET"
  $numero  = Read-Host "  Numero dedicado, formato internacional sin + (ej. 573001234567)"
  $numero  = ($numero -replace '[^0-9]', '')
  @"
OS_URL=$BASE
GRUPO_WA_SECRET=$secreto
NUMERO_DEDICADO=$numero
GRUPO_JID=
"@ | Set-Content "$carpeta\.env" -Encoding UTF8
  Write-Host "  guardado en $carpeta\.env" -ForegroundColor Green
}

# 5 · Lanzador
@'
$env:NODE_NO_WARNINGS = "1"
Get-Content "C:\male-oyente-grupo\.env" | ForEach-Object {
  if ($_ -match "^\s*([^#=]+)=(.*)$") {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
  }
}
Set-Location "C:\male-oyente-grupo"
node oyente.js *>> "C:\male-oyente-grupo\oyente.log"
'@ | Set-Content "$carpeta\arrancar.ps1" -Encoding UTF8

# 6 · Tarea de Windows: arranca con la maquina, como SYSTEM, sin limite de
#     tiempo. Mismo patron que el agente de impresion.
schtasks /Delete /TN $tarea /F 2>$null | Out-Null
$accion = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$carpeta\arrancar.ps1`""
schtasks /Create /TN $tarea /TR $accion /SC ONSTART /RU SYSTEM /RL HIGHEST /F | Out-Null
Write-Host "tarea de Windows creada" -ForegroundColor Green

# 7 · Vinculacion. Se arranca en primer plano UNA vez para que salga el codigo.
Write-Host ""
Write-Host "Vinculando el numero. En unos segundos aparece un CODIGO DE 8 CARACTERES." -ForegroundColor Yellow
Write-Host "Tecléalo en el WhatsApp de ese numero:" -ForegroundColor Yellow
Write-Host "   Ajustes -> Dispositivos vinculados -> Vincular con numero de telefono" -ForegroundColor White
Write-Host "(el codigo tambien queda en el OS, por si esta consola se cierra)" -ForegroundColor Gray
Write-Host ""
Write-Host "Cuando diga 'conectado a WhatsApp', cierra con Ctrl+C y corre:" -ForegroundColor Yellow
Write-Host "   schtasks /Run /TN `"$tarea`"" -ForegroundColor White
Write-Host ""

Get-Content "$carpeta\.env" | ForEach-Object {
  if ($_ -match "^\s*([^#=]+)=(.*)$") {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
  }
}
node oyente.js
