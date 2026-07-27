# =========================================================================
#  AGENTE DE IMPRESION MALE'DENIM  (version PowerShell para el servidor MDS)
#  Sin dependencias: corre con el PowerShell que trae Windows.
#
#  Hace lo mismo que el agente Python del Mac:
#   1) Remisiones PDF pendientes  -> RICOH   (PDF Direct Print, IP:9100)
#   2) Etiquetas ZPL pendientes   -> Honeywell (stickers) / SAT (lavado)
#   3) Paginas PDF de PRUEBA      -> cualquier impresora (destino=ricoh, etc.)
#  Lee config.json en la MISMA carpeta (backend, credenciales, impresoras).
#
#  v2.3 BLINDADO (2026-07-27): nunca se apaga por un error.
#   - Login inicial con reintento infinito (aguanta que la red no este lista).
#   - El bucle atrapa CUALQUIER error, lo loggea y sigue (backoff).
#   - Pensado para correr como tarea ONSTART sin limite de tiempo.
# =========================================================================

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$Conf = Get-Content -Raw -Path (Join-Path $Carpeta "config.json") | ConvertFrom-Json
$Base = $Conf.backend_url.TrimEnd("/")
$PollSeg = [int]($Conf.poll_seconds); if ($PollSeg -lt 5) { $PollSeg = 12 }
$LogFile = Join-Path $Carpeta "agente.log"

function Log([string]$msg) {
    $linea = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $linea
    try { Add-Content -Path $LogFile -Value $linea -Encoding UTF8 } catch {}
}

# --- API con token (re-login automatico en 401) --------------------------
$script:Token = ""

function Login {
    $cuerpo = @{ email = $Conf.email; password = $Conf.password } | ConvertTo-Json
    $r = Invoke-RestMethod -Method Post -Uri "$Base/api/auth/login" `
        -ContentType "application/json" -Body $cuerpo -TimeoutSec 30
    $script:Token = $r.access_token
    Log "[OK] Sesion iniciada en el sistema."
}

function EsError401($e) {
    try { return ([int]$e.Exception.Response.StatusCode -eq 401) } catch { return $false }
}

function ApiJson([string]$metodo, [string]$ruta) {
    try {
        return Invoke-RestMethod -Method $metodo -Uri ($Base + $ruta) `
            -Headers @{ Authorization = "Bearer $script:Token" } -TimeoutSec 60
    } catch {
        if (EsError401 $_) { Login; return Invoke-RestMethod -Method $metodo -Uri ($Base + $ruta) -Headers @{ Authorization = "Bearer $script:Token" } -TimeoutSec 60 }
        throw
    }
}

function ApiBytes([string]$ruta) {
    $tmp = [IO.Path]::GetTempFileName()
    try {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri ($Base + $ruta) `
                -Headers @{ Authorization = "Bearer $script:Token" } -OutFile $tmp -TimeoutSec 90
        } catch {
            if (EsError401 $_) {
                Login
                Invoke-WebRequest -UseBasicParsing -Uri ($Base + $ruta) `
                    -Headers @{ Authorization = "Bearer $script:Token" } -OutFile $tmp -TimeoutSec 90
            } else { throw }
        }
        return [IO.File]::ReadAllBytes($tmp)
    } finally {
        Remove-Item -Path $tmp -ErrorAction SilentlyContinue
    }
}

# --- Envio RAW a IP:9100 -------------------------------------------------
function Imprimir([byte[]]$datos, $impresora) {
    $puerto = 9100; if ($impresora.port) { $puerto = [int]$impresora.port }
    $cliente = New-Object System.Net.Sockets.TcpClient
    $cliente.SendTimeout = 30000; $cliente.ReceiveTimeout = 30000
    $cliente.Connect($impresora.ip, $puerto)
    try {
        $flujo = $cliente.GetStream()
        $flujo.Write($datos, 0, $datos.Length)
        $flujo.Flush()
    } finally { $cliente.Close() }
}

# --- CANDADO DE INSTANCIA UNICA -----------------------------------------
# Dos agentes vivos a la vez pueden bajar el MISMO trabajo de la cola e
# imprimir DOBLE (papel/etiquetas reales, no se puede deshacer). Este mutex
# global garantiza que solo uno corra, sin importar como se lance (tarea
# programada, Iniciar_agente.bat, doble clic, otra sesion de Windows).
$script:Candado = $null
try {
    $script:Candado = New-Object System.Threading.Mutex($false, 'Global\MaleDenimAgenteImpresion')
    if (-not $script:Candado.WaitOne(0)) {
        Log "[!] Ya hay OTRO agente corriendo. Me cierro para no imprimir doble."
        exit
    }
} catch {
    # OJO: New-Object envuelve el error en MethodInvocationException, por eso
    # hay que bajar por InnerException en vez de usar 'catch [Tipo]'.
    $err = $_.Exception
    while ($err.InnerException) { $err = $err.InnerException }
    if ($err -is [System.UnauthorizedAccessException]) {
        # El mutex ya existe pero lo creo otra cuenta (ej. la tarea como SYSTEM).
        Log "[!] Ya hay otro agente corriendo (de otra cuenta). Me cierro para no imprimir doble."
        exit
    }
    # Cualquier otra cosa: seguimos. Es mejor imprimir que no imprimir.
    Log ("[!] No pude crear el candado de instancia unica: " + $err.Message)
}

# --- Arranque ------------------------------------------------------------
Log "Agente de impresion MALE'DENIM (MDS / PowerShell) v2.3 blindado"
Log ("  Sistema : " + $Base)
foreach ($p in $Conf.printers.PSObject.Properties) {
    Log ("  {0,-9}: {1}:{2}" -f $p.Name, $p.Value.ip, $p.Value.port)
}
Log ("  Chequeo : cada " + $PollSeg + "s")

# Login inicial RESILIENTE: reintenta para siempre. Si el servidor acaba de
# prender y la red/DNS todavia no responde, NO se rinde (antes se apagaba).
while (-not $script:Token) {
    try { Login }
    catch {
        Log ("[!] Login fallo (¿red no lista aun?): " + $_.Exception.Message + ". Reintento en 15s...")
        Start-Sleep -Seconds 15
    }
}

$Fallidas = @{}
function Intento([string]$clave, [string]$etiqueta, [scriptblock]$accion) {
    try {
        & $accion
        $Fallidas.Remove($clave) | Out-Null
    } catch {
        $n = 1; if ($Fallidas.ContainsKey($clave)) { $n = $Fallidas[$clave] + 1 }
        $Fallidas[$clave] = $n
        if ($n -le 3 -or ($n % 10) -eq 0) {
            Log ("  [X] {0} fallo (intento {1}): {2}" -f $etiqueta, $n, $_.Exception.Message)
        }
    }
}

# --- MEMORIA "YA SALIO PAPEL" (anti impresion doble) --------------------
# Mandar el archivo a la impresora y confirmarle al sistema son DOS pasos.
# Si el papel YA salio y la confirmacion falla (corte de red, backend
# reiniciando), el trabajo sigue "pendiente" y en la vuelta siguiente se
# imprimiria OTRA VEZ. Esta marca en disco recuerda lo que ya salio
# fisicamente, para reintentar SOLO la confirmacion. Sobrevive reinicios.
$ArchivoImpresos = Join-Path $Carpeta "ya_impresos.txt"
$script:Impresos = New-Object 'System.Collections.Generic.HashSet[string]'
try {
    if (Test-Path $ArchivoImpresos) {
        foreach ($l in (Get-Content $ArchivoImpresos -ErrorAction SilentlyContinue)) {
            $t = ("" + $l).Trim()
            if ($t) { [void]$script:Impresos.Add($t) }
        }
    }
} catch {}

function YaSalio([string]$id) {
    if (-not $id) { return $false }
    return $script:Impresos.Contains($id)
}

function MarcarSalio([string]$id) {
    if (-not $id) { return }
    [void]$script:Impresos.Add($id)
    try { Add-Content -Path $ArchivoImpresos -Value $id -Encoding UTF8 } catch {}
    # Poda: que el archivo no crezca para siempre.
    try {
        if ($script:Impresos.Count -gt 3000) {
            $ultimos = @(Get-Content $ArchivoImpresos -Tail 1000 -ErrorAction SilentlyContinue)
            Set-Content -Path $ArchivoImpresos -Value $ultimos -Encoding UTF8
            $script:Impresos.Clear()
            foreach ($l in $ultimos) {
                $t = ("" + $l).Trim()
                if ($t) { [void]$script:Impresos.Add($t) }
            }
        }
    } catch {}
}

# --- Bucle principal (nunca sale por un error) ---------------------------
while ($true) {
    try {
        # 1) Remisiones PDF -> RICOH
        if ($Conf.printers.ricoh) {
            $pend = (ApiJson "GET" "/api/produccion/impresion/pendientes").pendientes
            foreach ($rem in @($pend)) {
                if (-not $rem) { continue }
                $rid = $rem.id
                $etq = $rem.consecutivo; if (-not $etq) { $etq = $rid.Substring(0, 8) }
                Intento $rid ("remision " + $etq) {
                    if (YaSalio $rid) {
                        # El papel YA salio antes; solo faltaba confirmarlo.
                        ApiJson "POST" ("/api/produccion/impresion/" + $rid + "/impresa") | Out-Null
                        Log ("  [OK] Confirmada {0} (ya habia salido impresa)" -f $etq)
                    } else {
                        $pdf = ApiBytes ("/api/produccion/remisiones/" + $rid + "/pdf")
                        Imprimir $pdf $Conf.printers.ricoh
                        MarcarSalio $rid          # <- ANTES de confirmar
                        ApiJson "POST" ("/api/produccion/impresion/" + $rid + "/impresa") | Out-Null
                        Log ("  [OK] Impresa {0} ({1} KB) -> ricoh" -f $etq, [int]($pdf.Length / 1024))
                    }
                }.GetNewClosure()
            }
        }

        # 2) Etiquetas termicas / PDF de prueba -> honeywell / sat / ricoh
        $trabajos = (ApiJson "GET" "/api/produccion/impresion/trabajos").trabajos
        foreach ($t in @($trabajos)) {
            if (-not $t) { continue }
            $destino = $t.destino
            $imp = $null
            if ($destino) { $imp = $Conf.printers.PSObject.Properties[$destino] }
            if (-not $imp) { continue }   # lo atiende otro agente
            $tid = $t.id
            $cod = $null; if ($t.payload) { $cod = $t.payload.codigo_referencia }
            if (-not $cod) { $cod = $tid.Substring(0, 8) }
            $etq = "{0} {1}" -f $t.tipo, $cod
            Intento $tid $etq {
                if (YaSalio $tid) {
                    # Las etiquetas YA salieron antes; solo faltaba confirmar.
                    ApiJson "POST" ("/api/produccion/impresion/trabajos/" + $tid + "/impreso") | Out-Null
                    Log ("  [OK] Confirmado {0} (ya habia salido impreso)" -f $etq)
                } else {
                    $contenido = ApiBytes ("/api/produccion/impresion/trabajos/" + $tid + "/contenido")
                    Imprimir $contenido $imp.Value
                    MarcarSalio $tid              # <- ANTES de confirmar
                    ApiJson "POST" ("/api/produccion/impresion/trabajos/" + $tid + "/impreso") | Out-Null
                    Log ("  [OK] Impreso {0} -> {1}" -f $etq, $destino)
                }
            }.GetNewClosure()
        }
    } catch {
        # Cualquier error (red caida, backend reiniciando, token vencido raro):
        # se loggea y el agente SIGUE VIVO. La proxima vuelta reintenta.
        Log ("[!] Sin conexion o error: " + $_.Exception.Message + ". Reintento...")
    }
    Start-Sleep -Seconds $PollSeg
}
