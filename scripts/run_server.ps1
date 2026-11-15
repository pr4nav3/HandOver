# Start the HandOver server on Windows (the Windows twin of scripts/run_server.sh):
#   http  on 0.0.0.0:8000 (laptop UI, replay script, glasses app)
#   https on 0.0.0.0:8443 when certs\cert.pem and certs\key.pem exist (the iPhone camera page needs HTTPS)
# Both ports share one learn session. Make certs with mkcert (see README.md, Run (Windows)). Ctrl+C stops the server.
# Env passes through, for example:  $env:HANDOVER_CHECK = "mock"; scripts\run_server.ps1
# Ports can be changed with HANDOVER_PORT and HANDOVER_HTTPS_PORT. ffmpeg must be on PATH.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "No .venv found. From the repo root run:  py -3.12 -m venv .venv; .venv\Scripts\pip install -r server\requirements.lock"
    exit 1
}

$HttpPort = if ($env:HANDOVER_PORT) { $env:HANDOVER_PORT } else { "8000" }
$HttpsPort = if ($env:HANDOVER_HTTPS_PORT) { $env:HANDOVER_HTTPS_PORT } else { "8443" }
$Certs = if ($env:HANDOVER_CERTS) { $env:HANDOVER_CERTS } else { Join-Path $Root "certs" }

# Same trick as server.main lan_ip(): connecting a UDP socket sends no packet, it only picks the outward interface.
$Ip = $null
try {
    $udp = New-Object System.Net.Sockets.UdpClient
    $udp.Connect("10.255.255.255", 1)
    $Ip = $udp.Client.LocalEndPoint.Address.ToString()
    $udp.Close()
    if ($Ip.StartsWith("127.")) { $Ip = $null }
} catch { $Ip = $null }
$Shown = if ($Ip) { $Ip } else { "<laptop IP>" }

Write-Host "Hub: http://localhost:$HttpPort/   LAN: http://${Shown}:$HttpPort/"
if ((Test-Path (Join-Path $Certs "cert.pem")) -and (Test-Path (Join-Path $Certs "key.pem"))) {
    Write-Host "Phone camera page: https://${Shown}:$HttpsPort/capture"
} else {
    Write-Host "No certs found: http only, so no phone camera page. See README.md, Run (Windows)."
}

# Python logs to stderr; under "Stop" Windows PowerShell 5.1 would turn a redirected stderr line into an error.
$ErrorActionPreference = "Continue"
& $Python -m server.main @args
exit $LASTEXITCODE
