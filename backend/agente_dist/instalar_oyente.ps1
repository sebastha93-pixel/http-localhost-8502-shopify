# ═══════════════════════════════════════════════════════════════════════════
#  OYENTE DEL GRUPO DE PRODUCCION — instalador de una linea
# ═══════════════════════════════════════════════════════════════════════════
#  En el servidor MDS, PowerShell COMO ADMINISTRADOR (ya NO con "| iex"):
#
#      cd $env:TEMP
#      irm https://backend-production-21f0.up.railway.app/api/produccion/agente/instalar_oyente.ps1 -OutFile instalar_oyente.ps1
#      Get-FileHash .\instalar_oyente.ps1   # comparar con la huella que dio el dueno
#      powershell -NoProfile -ExecutionPolicy Bypass -File .\instalar_oyente.ps1
#
#  Descarga el oyente, instala dependencias, deja una tarea de Windows que
#  arranca con la maquina, y pide el codigo de pareo para vincular el numero.
#
#  AUDITORIA 2026-11 (informe 15 #26): oyente.js y package.json solo se
#  instalan con una firma valida de la llave del dueno (la misma del agente de
#  impresion), y la carpeta queda solo para Administradores y SYSTEM.
#
#  NO pregunta por el grupo: eso se elige desde el OS y el oyente lo consulta
#  en cada latido. Asi no hay que volver a esta maquina para cambiarlo.
# ═══════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
# Este servidor tiene la ejecucion de scripts DESHABILITADA (Restricted). Solo
# para ESTE proceso se levanta: no cambia la politica de la maquina, y sin esto
# no corre ni el shim de npm.
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force } catch { }
$BASE    = "https://backend-production-21f0.up.railway.app"
$LlavePublica = '<RSAKeyValue><Modulus>xCD3/J8JttDmmoP9sjmfiRR01bsJ9UXA5nbRIP+zekvUx9sR7d9b9Pf4IfRD01udoBUbBwNBirlEw53EnNJp33kDZ0DzlLCtkPmelfW7epITmKORmtZT61jcl++QfeP5RuwptMxL8PPS19CjBYEpNvB6G69TLppivaAvv0o2qPNELohQOLPvwC1vVqbhG+GqagNM8SLzcb1/Dh8Q1I9hk7KPUVeiX9HqIEkF2TqH6N64Kq8iXR+b2q88lwm0AecL1nP6o6E8m+p47SbKimm4gZ7LLLBp2odd3cwZC5EjvDzTaajxiOVPajOEXVDVqjaU7M8HukAGjUzAHkZ32ruNfVF1/OLtEYmkqcTm+WW9m7xoKTZGhIjDSsNxcL3DfeLF9i2e9NiR7t2hxoUcafH1RaQGyEJmExCzljNi+i6mpFvGLYvyaCUvHegBBrR4UR1N3yTutzFL96LNx0UqPt5mJYdwwkhKL34dH4zFJFkAr4vseg7HyO8Rj8fOAkoZSJG1</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>'

# RSA PKCS#1 v1.5 sobre SHA-256, como en instalar.ps1 (tools/firmar_agente.sh).
function Test-Firma([byte[]]$Datos, [string]$FirmaB64) {
  try {
    $rsa = New-Object System.Security.Cryptography.RSACryptoServiceProvider
    $rsa.FromXmlString($LlavePublica)
    $firma = [Convert]::FromBase64String($FirmaB64.Trim())
    return [bool]$rsa.VerifyData($Datos, $firma,
      [System.Security.Cryptography.HashAlgorithmName]::SHA256,
      [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
  } catch { return $false }
}
$carpeta = "C:\male-oyente-grupo"
$tarea   = "MALE Oyente Grupo Produccion"

Write-Host ""
Write-Host "=== Oyente del grupo de produccion ===" -ForegroundColor Cyan

# 1 · Node
try { $v = (node --version) } catch { $v = $null }
if (-not $v) {
  # Intentar con winget antes de rendirse: mandar a alguien a descargar un
  # instalador a mano a mitad de camino es como se abandonan estas cosas.
  Write-Host "Node no esta instalado. Intento instalarlo con winget..." -ForegroundColor Yellow
  $tieneWinget = $false
  try { winget --version | Out-Null; $tieneWinget = $true } catch { }
  if ($tieneWinget) {
    winget install --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
    # winget no refresca el PATH de la sesion actual: hay que releerlo o el
    # 'node --version' de abajo seguiria fallando aunque quedo instalado.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
    try { $v = (node --version) } catch { $v = $null }
  }
  if (-not $v) {
    Write-Host "No pude instalar Node automaticamente." -ForegroundColor Red
    Write-Host "Instalalo desde https://nodejs.org (version LTS) y vuelve a correr esta linea." -ForegroundColor Red
    return
  }
}
Write-Host "Node $v" -ForegroundColor Green

# 1b · git. npm lo NECESITA aqui: Baileys arrastra una dependencia que se baja
#      desde GitHub (libsignal), y sin git el install muere con
#      "ENOENT spawn git" aunque Node y npm esten perfectos. Paso exactamente
#      eso en el MDS.
try { $g = (git --version) } catch { $g = $null }
if (-not $g) {
  Write-Host "git no esta instalado (npm lo necesita). Instalando con winget..." -ForegroundColor Yellow
  try {
    winget install --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    # Igual que con Node: winget no refresca el PATH de esta sesion.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
    try { $g = (git --version) } catch { $g = $null }
  } catch { }
  if (-not $g) {
    Write-Host "No pude instalar git. Instalalo desde https://git-scm.com y reintenta." -ForegroundColor Red
    return
  }
}
Write-Host "$g" -ForegroundColor Green

# 2 · Carpeta solo para Administradores y SYSTEM, y archivos FIRMADOS
#     Antes heredaba los permisos de C:\ (cualquier usuario modifica): quien
#     escribiera aqui corria como SYSTEM y leia el .env con el secreto.
if ((Test-Path $carpeta) -and ((Get-Item -Force $carpeta).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
  Write-Host "$carpeta es un enlace, no una carpeta. Borralo y reintenta." -ForegroundColor Red
  return
}
New-Item -ItemType Directory -Force -Path $carpeta | Out-Null
& icacls $carpeta /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' /remove:g '*S-1-1-0' '*S-1-5-11' '*S-1-5-32-545' /Q | Out-Null
& icacls $carpeta /setowner '*S-1-5-32-544' /T /C /Q | Out-Null
Set-Location $carpeta
foreach ($f in @("oyente.js", "package.json")) {
  $tmp  = "$carpeta\$f.descarga"
  $tmpF = "$carpeta\$f.firma"
  Invoke-WebRequest -Uri "$BASE/api/produccion/agente/$f" -OutFile $tmp -UseBasicParsing
  Invoke-WebRequest -Uri "$BASE/api/produccion/agente/$f.firma" -OutFile $tmpF -UseBasicParsing
  $ok = Test-Firma ([IO.File]::ReadAllBytes($tmp)) ([IO.File]::ReadAllText($tmpF))
  Remove-Item -Force $tmpF -ErrorAction SilentlyContinue
  if (-not $ok) {
    Remove-Item -Force $tmp -ErrorAction SilentlyContinue
    Write-Host "La firma de $f NO es valida. No se instala nada." -ForegroundColor Red
    return
  }
  Move-Item -Force $tmp "$carpeta\$f"
  Write-Host "bajado $f (firma verificada)" -ForegroundColor Green
}

# 3 · Dependencias
Write-Host "Instalando dependencias (un par de minutos)..."
# npm.cmd y NO npm: en PowerShell `npm` resuelve a npm.ps1, y en una maquina con
# ExecutionPolicy Restricted eso falla con PSSecurityException aunque npm este
# perfectamente instalado. Fue exactamente lo que paso en el MDS. El .cmd no
# pasa por PowerShell, asi que funciona sin tocar la politica del sistema.
$npm = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
if (-not (Test-Path $npm)) { $npm = "npm.cmd" }   # por si Node quedo en otra ruta
& $npm install --omit=dev --silent
if ($LASTEXITCODE -ne 0) {
  Write-Host "npm install fallo (codigo $LASTEXITCODE). Revisa la conexion y reintenta." -ForegroundColor Red
  return
}
Write-Host "dependencias listas" -ForegroundColor Green

# 4 · Configuracion. El secreto y el numero se piden aca y quedan SOLO en este
#     archivo: nunca en un script publico ni en GitHub.
if (-not (Test-Path "$carpeta\.env")) {
  Write-Host ""
  Write-Host "Configuracion (una sola vez):" -ForegroundColor Cyan
  $secreto = Read-Host "  GRUPO_WA_SECRET"
  Write-Host "  (si la linea dedicada todavia no existe, deja el numero VACIO:" -ForegroundColor Gray
  Write-Host "   se instala todo y se vincula despues)" -ForegroundColor Gray
  $numero  = Read-Host "  Numero dedicado, sin + (ej. 573001234567) o vacio"
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
# ErrorActionPreference vuelve a Continue SOLO aca. `schtasks /Delete` de una
# tarea que no existe escribe en stderr, y con Stop puesto PowerShell convierte
# ese ruido en un error FATAL que aborta el instalador justo antes de crear la
# tarea. Paso exactamente eso en el MDS en la primera instalacion.
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
schtasks /Delete /TN $tarea /F 2>&1 | Out-Null
$accion = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$carpeta\arrancar.ps1`""
schtasks /Create /TN $tarea /TR $accion /SC ONSTART /RU SYSTEM /RL HIGHEST /F 2>&1 | Out-Null
$codigoTarea = $LASTEXITCODE
$ErrorActionPreference = $prev
if ($codigoTarea -ne 0) {
  Write-Host "No pude crear la tarea de Windows (codigo $codigoTarea)." -ForegroundColor Red
  Write-Host "El oyente sirve igual arrancandolo a mano con .\arrancar.ps1," -ForegroundColor Yellow
  Write-Host "pero no revivira solo al reiniciar el servidor." -ForegroundColor Yellow
} else {
  Write-Host "tarea de Windows creada" -ForegroundColor Green
}

# 7 · Vinculacion. Solo si hay numero: pedirle a WhatsApp un codigo de pareo
#     para una linea que no existe termina en error y parece que algo se rompio.
Get-Content "$carpeta\.env" | ForEach-Object {
  if ($_ -match "^\s*([^#=]+)=(.*)$") {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
  }
}
$numeroCfg = [Environment]::GetEnvironmentVariable("NUMERO_DEDICADO", "Process")

if ([string]::IsNullOrWhiteSpace($numeroCfg)) {
  Write-Host ""
  Write-Host "=== INSTALADO, FALTA VINCULAR ===" -ForegroundColor Cyan
  Write-Host "Todo quedo listo en $carpeta (Node, dependencias, tarea de Windows)." -ForegroundColor Green
  Write-Host ""
  Write-Host "Cuando la linea dedicada tenga WhatsApp activo:" -ForegroundColor Yellow
  Write-Host "  1) Escribe el numero en NUMERO_DEDICADO dentro de $carpeta\.env" -ForegroundColor White
  Write-Host "  2) cd $carpeta ; .\arrancar.ps1" -ForegroundColor White
  Write-Host "  3) Teclea el codigo de 8 caracteres en ese WhatsApp:" -ForegroundColor White
  Write-Host "     Ajustes -> Dispositivos vinculados -> Vincular con numero de telefono" -ForegroundColor White
  Write-Host "  4) Cuando diga 'conectado', Ctrl+C y: schtasks /Run /TN `"$tarea`"" -ForegroundColor White
  Write-Host ""
  Write-Host "Log: $carpeta\oyente.log" -ForegroundColor Gray
  return
}

Write-Host ""
Write-Host "Vinculando. En unos segundos aparece un CODIGO DE 8 CARACTERES." -ForegroundColor Yellow
Write-Host "Tecléalo en el WhatsApp de ese numero:" -ForegroundColor Yellow
Write-Host "   Ajustes -> Dispositivos vinculados -> Vincular con numero de telefono" -ForegroundColor White
Write-Host "(el codigo tambien queda en el OS, por si esta consola se cierra)" -ForegroundColor Gray
Write-Host ""
Write-Host "Cuando diga 'conectado a WhatsApp', cierra con Ctrl+C y corre:" -ForegroundColor Yellow
Write-Host "   schtasks /Run /TN `"$tarea`"" -ForegroundColor White
Write-Host ""

node oyente.js
