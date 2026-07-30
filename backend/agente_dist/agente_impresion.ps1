# =========================================================================
#  AGENTE DE IMPRESION MALE'DENIM  (version PowerShell para el servidor MDS)
#  Sin dependencias: corre con el PowerShell que trae Windows.
#
#  Que imprime y por donde:
#   1) Remisiones pendientes      -> RICOH, PWG-Raster por IPP (puerto 631)
#   2) Etiquetas ZPL pendientes   -> Honeywell (stickers) / SAT (lavado), RAW 9100
#   3) Paginas de PRUEBA          -> cualquiera de las tres
#  Lee config.json en la MISMA carpeta (backend, credenciales, impresoras).
#
#  v2.4 (2026-07-30): ARREGLO DE LA RICOH — antes marcaba "impresa" sin papel.
#   Esa maquina declara "CMD:JBGRD,URF": no interpreta PDF, y su puerto 9100
#   acepta la conexion y DESCARTA todo (se probo con PDF, PWG y URF, mirando la
#   cola interna de la impresora: no registraba ni un trabajo). Ahora la
#   remision se pide ya rasterizada (/pwg) y se manda por IPP, que ademas
#   responde si acepto o rechazo — antes el socket "tenia exito" siempre.
#   Las termicas NO cambian: esas si hablan ZPL/TSPL nativo por el 9100.
#   No hace falta tocar config.json: la RICOH va por IPP por defecto.
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

# --- Envio RAW a IP:9100 (impresoras termicas: hablan ZPL/TSPL nativo) ---
function ImprimirRaw([byte[]]$datos, $impresora) {
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

# --- Envio por IPP al puerto 631 (la RICOH) ------------------------------
# POR QUE (verificado 2026-07-30 contra la maquina, mirando su cola interna):
# la RICOH M 320F declara "CMD:JBGRD,URF" — NO entiende PDF. Su puerto 9100
# acepta la conexion y DESCARTA todo (PDF, PWG y URF por igual), asi que el
# agente marcaba "impresa" sin que saliera papel. El unico camino que imprime
# es PWG-Raster por IPP en el 631. El backend ya entrega el raster listo.
# OJO PowerShell: una funcion que "devuelve" un byte[] lo DESENROLLA en el
# stream de salida y el llamador recibe Object[], con lo que List[byte].AddRange
# revienta ("Cannot convert argument"). Por eso el atributo se AGREGA a la lista
# que se recibe, en vez de devolverse.
function AgregarAtributoIPP($lista, [byte]$tag, [string]$nombre, [string]$valor) {
    $n = [Text.Encoding]::UTF8.GetBytes($nombre)
    $v = [Text.Encoding]::UTF8.GetBytes($valor)
    $lista.Add($tag)
    $lista.Add([byte](($n.Length -shr 8) -band 0xFF))
    $lista.Add([byte]($n.Length -band 0xFF))
    foreach ($x in $n) { $lista.Add($x) }
    $lista.Add([byte](($v.Length -shr 8) -band 0xFF))
    $lista.Add([byte]($v.Length -band 0xFF))
    foreach ($x in $v) { $lista.Add($x) }
}

function ImprimirIPP([byte[]]$datos, $impresora, [string]$titulo, [string]$formato) {
    $puerto = 631; if ($impresora.ipp_port) { $puerto = [int]$impresora.ipp_port }
    $uriImpresora = "ipp://$($impresora.ip)/ipp/print"
    if (-not $formato) { $formato = "image/pwg-raster" }
    if (-not $titulo)  { $titulo  = "MALE DENIM" }

    $req = New-Object 'System.Collections.Generic.List[byte]'
    foreach ($x in [byte[]](0x02, 0x00)) { $req.Add($x) }            # IPP 2.0
    foreach ($x in [byte[]](0x00, 0x02)) { $req.Add($x) }            # Print-Job
    foreach ($x in [byte[]](0x00, 0x00, 0x00, 0x01)) { $req.Add($x) } # request-id
    $req.Add([byte]0x01)                         # operation-attributes-tag
    AgregarAtributoIPP $req 0x47 "attributes-charset" "utf-8"
    AgregarAtributoIPP $req 0x48 "attributes-natural-language" "en"
    AgregarAtributoIPP $req 0x45 "printer-uri" $uriImpresora
    AgregarAtributoIPP $req 0x42 "requesting-user-name" "maledenim"
    AgregarAtributoIPP $req 0x42 "job-name" $titulo
    AgregarAtributoIPP $req 0x49 "document-format" $formato
    $req.Add([byte]0x03)                         # end-of-attributes-tag
    $req.AddRange($datos)                        # $datos ya es [byte[]] tipado
    $cuerpo = $req.ToArray()

    $http = [Net.HttpWebRequest]::Create("http://$($impresora.ip):$puerto/ipp/print")
    $http.Method = "POST"
    $http.ContentType = "application/ipp"
    $http.ContentLength = $cuerpo.Length
    $http.Timeout = 120000
    $http.ReadWriteTimeout = 120000
    $flujo = $http.GetRequestStream()
    try { $flujo.Write($cuerpo, 0, $cuerpo.Length) } finally { $flujo.Close() }

    $resp = $http.GetResponse()
    try {
        $ms = New-Object IO.MemoryStream
        $resp.GetResponseStream().CopyTo($ms)
        $r = $ms.ToArray()
    } finally { $resp.Close() }

    # La respuesta IPP trae el status-code en los bytes 2-3. Todo lo que sea
    # >= 0x0100 es error: hay que LANZAR para que el trabajo NO se marque como
    # impreso y se reintente. (Aun asi, "aceptado" no garantiza papel: con el
    # formato equivocado la maquina acepta y tira la hoja. De ahi que el
    # formato lo fije el backend y no se improvise aca.)
    if ($r.Length -lt 4) { throw "IPP: respuesta vacia de $($impresora.ip)" }
    $estado = ([int]$r[2] * 256) + [int]$r[3]
    if ($estado -ge 0x0100) {
        throw ("IPP: la impresora rechazo el trabajo (status 0x{0:X4})" -f $estado)
    }
}

# --- Despacho: cada impresora por donde entiende --------------------------
function UsaIPP([string]$nombre, $impresora) {
    if ($impresora.modo) { return ($impresora.modo -eq "ipp") }
    # Sin 'modo' en el config.json (el caso del servidor MDS hoy): la RICOH va
    # por IPP porque su 9100 no imprime nada. Las termicas siguen por RAW.
    return ($nombre -eq "ricoh")
}

function Imprimir([byte[]]$datos, $impresora, [string]$nombre, [string]$titulo) {
    if (UsaIPP $nombre $impresora) {
        ImprimirIPP $datos $impresora $titulo "image/pwg-raster"
    } else {
        ImprimirRaw $datos $impresora
    }
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
                        # /pwg y no /pdf: la RICOH no interpreta PDF. El backend
                        # entrega la remision ya rasterizada. Ver ImprimirIPP.
                        $hoja = ApiBytes ("/api/produccion/remisiones/" + $rid + "/pwg")
                        Imprimir $hoja $Conf.printers.ricoh "ricoh" ("Remision " + $etq)
                        MarcarSalio $rid          # <- ANTES de confirmar
                        ApiJson "POST" ("/api/produccion/impresion/" + $rid + "/impresa") | Out-Null
                        Log ("  [OK] Impresa {0} ({1} KB) -> ricoh" -f $etq, [int]($hoja.Length / 1024))
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
                    Imprimir $contenido $imp.Value $destino $etq
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
