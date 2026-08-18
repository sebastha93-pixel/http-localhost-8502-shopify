# ═══════════════════════════════════════════════════════════════════════════
#  OYENTE DEL GRUPO DE PRODUCCION — instalador para el servidor MDS
# ═══════════════════════════════════════════════════════════════════════════
#  Corre en la MISMA maquina que el agente de impresion, con el mismo patron:
#  una tarea de Windows que arranca sola y se queda viva.
#
#  Ejecutar en PowerShell COMO ADMINISTRADOR:
#      cd C:\male-oyente-grupo
#      .\instalar.ps1
# ═══════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
$carpeta = "C:\male-oyente-grupo"

Write-Host "== Oyente del grupo de produccion ==" -ForegroundColor Cyan

# 1 · Node. Sin Node no hay nada que instalar.
try { $v = (node --version) } catch { $v = $null }
if (-not $v) {
  Write-Host "Node no esta instalado. Instalalo desde https://nodejs.org (LTS) y vuelve a correr esto." -ForegroundColor Red
  exit 1
}
Write-Host "Node $v detectado" -ForegroundColor Green

# 2 · Dependencias
Set-Location $carpeta
Write-Host "Instalando dependencias (tarda un par de minutos)..."
npm install --omit=dev --silent

# 3 · Configuracion. Se pide aca y NO se deja en el codigo: el secreto no va
#     a GitHub.
if (-not (Test-Path "$carpeta\.env")) {
  $osUrl  = Read-Host "URL del backend (enter para la de produccion)"
  if ([string]::IsNullOrWhiteSpace($osUrl)) {
    $osUrl = "https://backend-production-21f0.up.railway.app"
  }
  $secreto = Read-Host "GRUPO_WA_SECRET (el mismo valor que esta en Railway)"
  @"
OS_URL=$osUrl
GRUPO_WA_SECRET=$secreto
GRUPO_JID=
"@ | Set-Content "$carpeta\.env" -Encoding UTF8
  Write-Host "Configuracion guardada en .env" -ForegroundColor Green
}

# 4 · Lanzador que carga el .env y arranca el oyente
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

# 5 · Tarea de Windows: arranca con la maquina, sin limite de tiempo, y se
#     reinicia sola si el proceso muere.
$nombre = "MALE Oyente Grupo Produccion"
schtasks /Delete /TN $nombre /F 2>$null | Out-Null
$accion = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$carpeta\arrancar.ps1`""
schtasks /Create /TN $nombre /TR $accion /SC ONSTART /RU SYSTEM /RL HIGHEST /F | Out-Null
schtasks /Change /TN $nombre /DISABLE 2>$null | Out-Null

Write-Host ""
Write-Host "Instalado. FALTAN DOS PASOS QUE SOLO PUEDES HACER TU:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1) Vincular el numero dedicado. Corre esto y escanea el QR" -ForegroundColor Yellow
Write-Host "     con el celular de ESE numero (no con el tuyo):" -ForegroundColor Yellow
Write-Host "        cd C:\male-oyente-grupo ; .\arrancar.ps1" -ForegroundColor White
Write-Host ""
Write-Host "  2) Al conectarse, lista los grupos. Copia el id del grupo de" -ForegroundColor Yellow
Write-Host "     produccion, pegalo en GRUPO_JID dentro de .env, y activa la tarea:" -ForegroundColor Yellow
Write-Host "        schtasks /Change /TN `"$nombre`" /ENABLE" -ForegroundColor White
Write-Host "        schtasks /Run /TN `"$nombre`"" -ForegroundColor White
Write-Host ""
Write-Host "Log: C:\male-oyente-grupo\oyente.log" -ForegroundColor Gray
