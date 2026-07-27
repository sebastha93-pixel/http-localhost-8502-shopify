# =========================================================================
#  INSTALADOR DEL AGENTE DE IMPRESION MALE'DENIM   (una sola linea)
#
#  Uso en el PC del servidor MDS (PowerShell NORMAL, sin elevar):
#     irm https://backend-production-21f0.up.railway.app/api/produccion/agente/instalar.ps1 | iex
#
#  Que hace:
#   1. Si no es administrador -> se ELEVA solo (sale el aviso de Windows).
#      Si el usuario lo rechaza / no puede -> instala en MODO SIN ADMIN
#      (tarea del usuario que arranca al iniciar sesion).
#   2. Encuentra la carpeta del agente (busca en los escritorios).
#   3. Baja la ultima version de agente_impresion.ps1.
#   4. MATA el agente viejo (evita que dos agentes impriman doble).
#   5. Registra la tarea: arranca al prender el PC, oculta, SIN limite de
#      tiempo y con auto-reinicio si el proceso se cae.
#   6. La arranca y VERIFICA que quedo corriendo.
# =========================================================================

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Base   = 'https://backend-production-21f0.up.railway.app'
$UrlYo  = "$Base/api/produccion/agente/instalar.ps1"
$UrlPs1 = "$Base/api/produccion/agente/agente_impresion.ps1"
$Tarea  = 'AgenteImpresionMaleDenim'

function Di([string]$m) { Write-Host $m }

# ── 1. ¿Somos administrador? ─────────────────────────────────────────────
$esAdmin = $false
try {
    $esAdmin = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { $esAdmin = $false }

$seguir     = $true
$modoUsuario = $false

if (-not $esAdmin) {
    Di ""
    Di "  Necesito permiso de administrador."
    Di "  >>> Va a salir un aviso de Windows: dale  Si  <<<"
    Di ""
    try {
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -ErrorAction Stop `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit',
                            '-Command', "irm '$UrlYo' | iex")
        Di "  [OK] Se abrio una ventana de ADMINISTRADOR."
        Di "       Mira ESA ventana: ahi termina la instalacion."
        $seguir = $false
    } catch {
        Di "  [!] No se pudo elevar ($($_.Exception.Message))."
        Di "      Instalo en MODO SIN ADMIN (arranca al iniciar sesion)."
        $modoUsuario = $true
    }
}

if ($seguir) {

    # ── 2. Buscar la carpeta del agente ─────────────────────────────────
    Di "  Buscando la carpeta del agente..."
    $cands = @()
    try {
        foreach ($u in (Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue)) {
            foreach ($sub in @('Desktop', 'Escritorio', 'OneDrive\Desktop', 'OneDrive\Escritorio')) {
                $p = Join-Path $u.FullName $sub
                if (Test-Path $p) { $cands += $p }
            }
        }
    } catch {}
    if ($env:PUBLIC) { $cands += (Join-Path $env:PUBLIC 'Desktop') }

    $dir = $null
    foreach ($c in $cands) {
        $f = Get-ChildItem -Path $c -Recurse -Filter 'agente_impresion.ps1' `
                -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($f) { $dir = $f.DirectoryName; break }
    }
    if (-not $dir) {
        # Ultimo recurso: barrer todo C:\Users
        $f = Get-ChildItem -Path 'C:\Users' -Recurse -Filter 'agente_impresion.ps1' `
                -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($f) { $dir = $f.DirectoryName }
    }
    if (-not $dir) {
        Di ""
        Di "  [X] No encontre la carpeta del agente (agente_impresion.ps1)."
        Di "      Copia la carpeta AGENTE_IMPRESION_MALEDENIM al Escritorio y repite."
        Di ""
    }
    else {
        $ps1 = Join-Path $dir 'agente_impresion.ps1'
        $cfg = Join-Path $dir 'config.json'
        Di "  Carpeta: $dir"
        if (-not (Test-Path $cfg)) {
            Di "  [X] Falta config.json en esa carpeta (trae las impresoras y la clave)."
            Di "      Sin ese archivo el agente no puede arrancar."
        }
        else {
            # ── 3. Bajar la ultima version del agente ───────────────────
            try {
                $tmp = "$ps1.nuevo"
                Invoke-WebRequest -UseBasicParsing -Uri $UrlPs1 -OutFile $tmp -TimeoutSec 60
                if ((Get-Item $tmp).Length -gt 1000) {
                    Move-Item -Force $tmp $ps1
                    Di "  [OK] Agente actualizado a la ultima version."
                } else {
                    Remove-Item $tmp -ErrorAction SilentlyContinue
                    Di "  [!] La descarga vino vacia: sigo con la version que ya tenias."
                }
            } catch {
                Di "  [!] No pude bajar la ultima version ($($_.Exception.Message))."
                Di "      Sigo con la version que ya esta en el PC."
            }

            # Cuenta los agentes vivos (excluye este instalador).
            function Agentes {
                try {
                    return @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
                             Where-Object { $_.CommandLine -and
                                            $_.CommandLine -like '*agente_impresion.ps1*' -and
                                            $_.ProcessId -ne $PID })
                } catch { return @() }
            }

            # ── 4. REGISTRAR la tarea PRIMERO (paso NO destructivo) ──────
            # ORDEN IMPORTANTE: si primero matamos al agente y despues falla
            # el registro (ej. 0x80070005 por no estar elevado), el PC queda
            # SIN agente y SIN tarea, y nadie se entera hasta que no sale una
            # remision. Registrando primero, si algo falla el agente que ya
            # estaba imprimiendo sigue intacto.
            $act = New-ScheduledTaskAction -Execute 'powershell.exe' `
                     -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ps1 + '"')

            $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                     -DontStopIfGoingOnBatteries -StartWhenAvailable `
                     -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
                     -MultipleInstances IgnoreNew
            # Sin limite de tiempo: por defecto Windows mata la tarea a los 3 dias.
            $set.ExecutionTimeLimit = 'PT0S'

            $modo = ""
            try {
                if ($modoUsuario) {
                    $trg = New-ScheduledTaskTrigger -AtLogOn
                    Register-ScheduledTask -TaskName $Tarea -Action $act -Trigger $trg `
                        -Settings $set -Force -ErrorAction Stop | Out-Null
                    $modo = "SIN ADMIN (arranca al iniciar sesion)"
                } else {
                    $trg = New-ScheduledTaskTrigger -AtStartup
                    $prn = New-ScheduledTaskPrincipal -UserId 'SYSTEM' `
                             -LogonType ServiceAccount -RunLevel Highest
                    Register-ScheduledTask -TaskName $Tarea -Action $act -Trigger $trg `
                        -Principal $prn -Settings $set -Force -ErrorAction Stop | Out-Null
                    $modo = "SYSTEM (arranca al prender el PC, aunque nadie inicie sesion)"
                }
                Di "  [OK] Tarea registrada: $modo"
            } catch {
                $modo = ""
                $sobreviven = @(Agentes).Count
                Di ""
                Di "  [X] No pude registrar la tarea: $($_.Exception.Message)"
                if ($sobreviven -gt 0) {
                    Di "      TRANQUILO: no toque el agente que ya estaba corriendo."
                    Di "      La impresion SIGUE viva ($sobreviven agente(s))."
                } else {
                    Di "      OJO: no hay ningun agente corriendo en este momento."
                }
                Di "      Para dejarlo automatico, abre PowerShell COMO ADMINISTRADOR"
                Di "      (clic derecho en el boton de Inicio -> 'Windows PowerShell"
                Di "      (Administrador)') y pega otra vez:"
                Di "         irm $UrlYo | iex"
                Di ""
            }

            # ── 5. Ya hay tarea: AHORA si retiro los agentes viejos ──────
            if ($modo) {
                # Paro por el MOTOR de tareas: asi el auto-reinicio no revive
                # al que voy a matar.
                try { Stop-ScheduledTask -TaskName $Tarea -ErrorAction SilentlyContinue } catch {}

                $muertos = 0
                foreach ($p in (Agentes)) {
                    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; $muertos++ } catch {}
                }
                if ($muertos -gt 0) { Di "  [OK] Cerre $muertos agente(s) viejo(s) (evita imprimir doble)." }

                # ── 6. Arrancar y verificar DE VERDAD ────────────────────
                # No basta con "existe un proceso": eso puede ser un agente
                # viejo que no murio. La prueba real es que el LOG crezca.
                $log = Join-Path $dir 'agente.log'
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
                            if ($nuevo -match 'Sesion iniciada' -or $nuevo -match 'blindado') {
                                $vivo = $true; break
                            }
                        }
                    } catch {}
                }
                Di ""
                if ($vivo) {
                    Di "  ============================================="
                    Di "   [OK] AGENTE INSTALADO Y CORRIENDO"
                    Di "        Modo: $modo"
                    Di "        Log : $dir\agente.log"
                    Di "        En la app: Produccion -> Impresion"
                    Di "                   debe decir 'Agente en linea'."
                    Di "  ============================================="
                } else {
                    # PLAN B: no dejar el PC sin imprimir. Solo si NO quedo
                    # ningun agente vivo (si hay uno, arrancar otro imprimiria
                    # DOBLE — y el candado del agente lo cerraria de todos modos).
                    $procs = @(Agentes)
                    if ($procs.Count -gt 0) {
                        Di "  [!] La tarea quedo registrada y veo $($procs.Count) proceso(s) del agente,"
                        Di "      pero el log no crecio en 40s. NO arranco otro (evito doble impresion)."
                    } else {
                        Di "  [!] La tarea no arranco. Lanzo el agente a mano como respaldo..."
                        try {
                            Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ErrorAction Stop `
                                -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ps1)
                            Di "      [OK] Agente lanzado a mano: la impresion queda funcionando YA."
                            Di "           (al reiniciar el PC arranca la tarea)"
                        } catch {
                            Di "      [X] Tampoco pude lanzarlo a mano: $($_.Exception.Message)"
                        }
                    }
                    Di "      Revisa el log: $dir\agente.log"
                    try {
                        $inf = Get-ScheduledTaskInfo -TaskName $Tarea -ErrorAction SilentlyContinue
                        if ($inf) { Di "      Ultimo resultado de la tarea: $($inf.LastTaskResult)" }
                    } catch {}
                }
                Di ""
            }
        }
    }
}
