# =========================================================================
#  INSTALADOR Y ACTUALIZADOR DEL AGENTE DE IMPRESION MALE'DENIM   (v3)
#
#  Auditoria de seguridad 2026-11, informe 15 #26. Antes se instalaba con
#  "irm ... | iex": corria como administrador lo que entregara el backend, y
#  la tarea SYSTEM ejecutaba un .ps1 guardado en un Escritorio. Tomar el
#  backend de Railway equivalia a tomar este PC. Ahora:
#
#   - Solo se instala un agente FIRMADO con la llave del dueno. La llave
#     publica va escrita aqui abajo; la privada vive solo en su Mac (nunca en
#     GitHub ni en Railway).
#   - Todo vive en C:\ProgramData\MaleDenim\AgenteImpresion, donde solo
#     escriben Administradores y SYSTEM. Ya no se buscan escritorios.
#   - Este mismo archivo queda copiado alli como actualizar.ps1. Para
#     actualizar, en PowerShell COMO ADMINISTRADOR:
#        & 'C:\ProgramData\MaleDenim\AgenteImpresion\actualizar.ps1'
#     Esa copia local es la que confia en la llave: aunque alguien tome el
#     backend, lo que baje sin la firma correcta no se instala.
#
#  PRIMERA VEZ (o para pasar desde la version vieja del Escritorio), en
#  PowerShell COMO ADMINISTRADOR:
#     cd $env:TEMP
#     irm https://backend-production-21f0.up.railway.app/api/produccion/agente/instalar.ps1 -OutFile instalar.ps1
#     Get-FileHash .\instalar.ps1    # comparar con la huella que dio el dueno
#     powershell -NoProfile -ExecutionPolicy Bypass -File .\instalar.ps1
#  NO usar "| iex": el instalador necesita ser un archivo para copiarse.
# =========================================================================

param([switch]$SoloCargar)   # para las pruebas: carga las funciones y no instala

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Base       = 'https://backend-production-21f0.up.railway.app'
$UrlDist    = "$Base/api/produccion/agente"
$Tarea      = 'AgenteImpresionMaleDenim'
$ProgData   = if ($env:ProgramData) { $env:ProgramData } else { 'C:\ProgramData' }
$Destino    = "$ProgData\MaleDenim\AgenteImpresion"

# Llave publica del dueno (RSA 3072). Cambiarla exige reinstalar a mano con
# este archivo verificado por fuera: un actualizar.ps1 viejo no acepta otra.
$LlavePublica = '<RSAKeyValue><Modulus>xCD3/J8JttDmmoP9sjmfiRR01bsJ9UXA5nbRIP+zekvUx9sR7d9b9Pf4IfRD01udoBUbBwNBirlEw53EnNJp33kDZ0DzlLCtkPmelfW7epITmKORmtZT61jcl++QfeP5RuwptMxL8PPS19CjBYEpNvB6G69TLppivaAvv0o2qPNELohQOLPvwC1vVqbhG+GqagNM8SLzcb1/Dh8Q1I9hk7KPUVeiX9HqIEkF2TqH6N64Kq8iXR+b2q88lwm0AecL1nP6o6E8m+p47SbKimm4gZ7LLLBp2odd3cwZC5EjvDzTaajxiOVPajOEXVDVqjaU7M8HukAGjUzAHkZ32ruNfVF1/OLtEYmkqcTm+WW9m7xoKTZGhIjDSsNxcL3DfeLF9i2e9NiR7t2hxoUcafH1RaQGyEJmExCzljNi+i6mpFvGLYvyaCUvHegBBrR4UR1N3yTutzFL96LNx0UqPt5mJYdwwkhKL34dH4zFJFkAr4vseg7HyO8Rj8fOAkoZSJG1</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>'

function Di([string]$m) { Write-Host $m }

# -- Verificar una firma --------------------------------------------------
# RSA PKCS#1 v1.5 sobre SHA-256: es lo que produce
# `openssl dgst -sha256 -sign` en tools/firmar_agente.sh.
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

# Baja un archivo y su .firma. Devuelve los bytes SOLO si la firma vale.
# Se baja con -OutFile y se leen los BYTES: `.Content` devuelve texto que
# PowerShell 5.1 puede recodificar, y entonces la firma no coincidiria.
function Get-Firmado([string]$Nombre) {
    $tmp = [IO.Path]::GetTempFileName()
    $tmpF = [IO.Path]::GetTempFileName()
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "$UrlDist/$Nombre" -OutFile $tmp -TimeoutSec 60
        Invoke-WebRequest -UseBasicParsing -Uri "$UrlDist/$Nombre.firma" -OutFile $tmpF -TimeoutSec 60
        $datos = [IO.File]::ReadAllBytes($tmp)
        $firma = [IO.File]::ReadAllText($tmpF)
    } finally {
        Remove-Item -Force $tmp, $tmpF -ErrorAction SilentlyContinue
    }
    if (-not (Test-Firma $datos $firma)) {
        throw "La firma de $Nombre NO es valida. No se instala nada."
    }
    return ,$datos
}

# -- Carpeta solo para Administradores y SYSTEM ---------------------------
# Por SID y no por nombre: en un Windows en espanol se llaman distinto.
function Set-CarpetaBlindada([string]$Ruta) {
    if (Test-Path $Ruta) {
        $item = Get-Item -Force $Ruta
        # Un usuario sin privilegios puede crear carpetas en ProgramData. Si
        # dejo un enlace (junction) aqui, se seguiria hacia donde el quiera.
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "$Ruta es un enlace, no una carpeta. Borralo y vuelve a correr el instalador."
        }
    } else {
        New-Item -ItemType Directory -Force -Path $Ruta | Out-Null
    }
    $admins = New-Object System.Security.Principal.SecurityIdentifier 'S-1-5-32-544'
    $system = New-Object System.Security.Principal.SecurityIdentifier 'S-1-5-18'
    $herencia = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)   # sin heredar de ProgramData
    $acl.SetOwner($admins)
    foreach ($sid in @($admins, $system)) {
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, 'FullControl', $herencia, 'None', 'Allow')))
    }
    Set-Acl -Path $Ruta -AclObject $acl
    # Lo que ya hubiera adentro vuelve a heredar SOLO de esta carpeta.
    Get-ChildItem -Force -Recurse $Ruta -ErrorAction SilentlyContinue | ForEach-Object {
        $a = Get-Acl $_.FullName
        $a.SetAccessRuleProtection($false, $false)
        foreach ($r in @($a.Access | Where-Object { -not $_.IsInherited })) { [void]$a.RemoveAccessRule($r) }
        $a.SetOwner($admins)
        Set-Acl -Path $_.FullName -AclObject $a
    }
}

# Carpeta del agente viejo, sacada de la tarea que ya existe (no de buscar en
# los escritorios: alli cualquiera puede plantar un agente_impresion.ps1).
function Get-CarpetaVieja {
    try {
        $t = Get-ScheduledTask -TaskName $Tarea -ErrorAction Stop
        foreach ($a in $t.Actions) {
            if ($a.Arguments -match '-File\s+"([^"]+)"') {
                $d = Split-Path -Parent $Matches[1]
                if ($d -and ($d -ne $Destino) -and (Test-Path (Join-Path $d 'config.json'))) { return $d }
            }
        }
    } catch {}
    return $null
}

if ($SoloCargar) { return }

# =========================================================================
# 1. Administrador, y como archivo
# =========================================================================
$esAdmin = $false
try {
    $esAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
               ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch {}
if (-not $esAdmin) {
    Di ""
    Di "  [X] Hay que correrlo en PowerShell COMO ADMINISTRADOR"
    Di "      (clic derecho en Inicio -> 'Windows PowerShell (Administrador)')."
    Di ""
    return
}
if (-not $PSCommandPath) {
    Di ""
    Di "  [X] Este instalador ya no se corre con '| iex'. Bajalo como archivo:"
    Di "      irm $UrlDist/instalar.ps1 -OutFile instalar.ps1"
    Di "      powershell -NoProfile -ExecutionPolicy Bypass -File .\instalar.ps1"
    Di ""
    return
}

# =========================================================================
# 2. Carpeta blindada y descarga verificada
# =========================================================================
Set-CarpetaBlindada $Destino
$ps1  = Join-Path $Destino 'agente_impresion.ps1'
$cfg  = Join-Path $Destino 'config.json'
$log  = Join-Path $Destino 'agente.log'
$act1 = Join-Path $Destino 'actualizar.ps1'
Di "  Carpeta: $Destino (solo Administradores y SYSTEM)"

try {
    $agente      = Get-Firmado 'agente_impresion.ps1'
    $instalador  = Get-Firmado 'instalar.ps1'
} catch {
    Di ""
    Di "  [X] $($_.Exception.Message)"
    Di "      El agente que ya estaba corriendo NO se toco."
    Di ""
    return
}
Di "  [OK] Firma del agente y del instalador verificadas."

# =========================================================================
# 3. config.json: si es la primera vez, se trae de la carpeta vieja
# =========================================================================
$vieja = $null
if (-not (Test-Path $cfg)) {
    $vieja = Get-CarpetaVieja
    if (-not $vieja) {
        Di "  No encontre la instalacion anterior por la tarea de Windows."
        $r = Read-Host "  Escribe la carpeta donde esta el config.json del agente (o Enter para cancelar)"
        if ($r -and (Test-Path (Join-Path $r 'config.json'))) { $vieja = $r.TrimEnd('\') }
    }
    if (-not $vieja) {
        Di "  [X] Sin config.json no hay impresoras ni clave: el agente no puede arrancar."
        return
    }
    Copy-Item -Force (Join-Path $vieja 'config.json') $cfg
    Di "  [OK] config.json copiado desde $vieja"
}

[IO.File]::WriteAllBytes($ps1, $agente)
[IO.File]::WriteAllBytes($act1, $instalador)
Set-CarpetaBlindada $Destino   # los archivos nuevos quedan con los mismos permisos
Di "  [OK] Agente y actualizar.ps1 escritos."

# Cuenta los agentes vivos (excluye este instalador).
function Agentes {
    try {
        return @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
                 Where-Object { $_.CommandLine -and
                                $_.CommandLine -like '*agente_impresion.ps1*' -and
                                $_.ProcessId -ne $PID })
    } catch { return @() }
}

# =========================================================================
# 4. Registrar la tarea PRIMERO (paso no destructivo)
# =========================================================================
# Si primero se mata al agente y luego falla el registro, el PC queda sin
# agente y sin tarea. Registrando primero, el que imprime sigue intacto.
$act = New-ScheduledTaskAction -Execute 'powershell.exe' `
         -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ps1 + '"')
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
         -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
         -MultipleInstances IgnoreNew
$set.ExecutionTimeLimit = 'PT0S'   # sin limite: por defecto Windows la mata a los 3 dias
$trg = New-ScheduledTaskTrigger -AtStartup
$prn = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
try {
    Register-ScheduledTask -TaskName $Tarea -Action $act -Trigger $trg -Principal $prn `
        -Settings $set -Force -ErrorAction Stop | Out-Null
    Di "  [OK] Tarea registrada como SYSTEM, apuntando a $ps1"
} catch {
    Di "  [X] No pude registrar la tarea: $($_.Exception.Message)"
    Di "      No toque el agente que ya estaba corriendo."
    return
}

# =========================================================================
# 5. Retirar los agentes viejos y terminar la mudanza
# =========================================================================
try { Stop-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue } catch {}
$muertos = 0
foreach ($p in (Agentes)) {
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; $muertos++ } catch {}
}
if ($muertos -gt 0) { Di "  [OK] Cerre $muertos agente(s) viejo(s) (evita imprimir doble)." }

if ($vieja) {
    # La lista de lo ya impreso se copia DESPUES de parar al viejo: asi trae
    # hasta lo ultimo que imprimio y el nuevo no repite ninguna remision.
    $impresos = Join-Path $vieja 'ya_impresos.txt'
    if (Test-Path $impresos) { Copy-Item -Force $impresos (Join-Path $Destino 'ya_impresos.txt') }
    # La clave del usuario de servicio no se queda en un Escritorio.
    Remove-Item -Force (Join-Path $vieja 'config.json') -ErrorAction SilentlyContinue
    Set-CarpetaBlindada $Destino
    Di "  [OK] Mudanza lista. En $vieja ya no queda config.json (la clave)."
    Di "       Esa carpeta vieja se puede borrar."
}

# =========================================================================
# 6. Arrancar y verificar DE VERDAD (que el log crezca)
# =========================================================================
$antes = 0
try { if (Test-Path $log) { $antes = (Get-Item $log).Length } } catch {}
try { Start-ScheduledTask -TaskName $Tarea -ErrorAction Stop } catch {
    Di "  [!] No pude lanzar la tarea ahora: $($_.Exception.Message)"
}
Di "  Arrancando y verificando (hasta 40s)..."
$vivo = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    try {
        if ((Test-Path $log) -and ((Get-Item $log).Length -gt $antes)) {
            $nuevo = Get-Content $log -Tail 25 -ErrorAction SilentlyContinue
            if ($nuevo -match 'Sesion iniciada' -or $nuevo -match 'blindado') { $vivo = $true; break }
        }
    } catch {}
}
Di ""
if ($vivo) {
    Di "  ============================================="
    Di "   [OK] AGENTE INSTALADO Y CORRIENDO"
    Di "        Log : $log"
    Di "        En la app: Produccion -> Impresion debe decir 'Agente en linea'."
    Di "        Para actualizar despues (como administrador):"
    Di "          & '$act1'"
    Di "  ============================================="
} else {
    Di "  [!] La tarea quedo registrada pero el log no crecio en 40s."
    Di "      Revisa: $log"
    try {
        $inf = Get-ScheduledTaskInfo -TaskName $Tarea -ErrorAction SilentlyContinue
        if ($inf) { Di "      Ultimo resultado de la tarea: $($inf.LastTaskResult)" }
    } catch {}
}
Di ""
