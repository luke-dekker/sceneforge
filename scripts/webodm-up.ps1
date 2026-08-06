# Start the full local ODM stack: podman machine + NodeODM (odm-up.ps1) plus
# the WebODM browser UI (repo at C:\Users\lucas\WebODM) on localhost:8000.
# WebODM talks to our NodeODM at host.docker.internal:3000 (pre-registered).
# Usage: .\scripts\webodm-up.ps1

& "$PSScriptRoot\odm-up.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Docker Desktop's CLI defaults to its own (stopped) engine; aim it at podman.
$env:DOCKER_HOST = 'npipe:////./pipe/docker_engine'
& bash -lc "cd /c/Users/lucas/WebODM && ./webodm.sh start --default-nodes 0 --detached"

$deadline = (Get-Date).AddSeconds(180)
while ((Get-Date) -lt $deadline) {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 http://localhost:8000 | Out-Null
        Write-Output "WebODM ready at http://localhost:8000 (NodeODM API at :3000)"
        exit 0
    } catch { Start-Sleep -Seconds 5 }
}
Write-Error "WebODM did not respond on http://localhost:8000 within 180s"
