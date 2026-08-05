# Start the local ODM stack: podman machine + NodeODM container on localhost:3000
# Usage: .\scripts\odm-up.ps1

$podman = "C:\Program Files\RedHat\Podman\podman.exe"
if (-not (Test-Path $podman)) { $podman = (Get-Command podman -ErrorAction Stop).Source }

& $podman machine start 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -notmatch "bogus" }

$existing = & $podman ps -a --filter name=nodeodm --format "{{.Names}} {{.Status}}"
if (-not $existing) {
    & $podman run -d --name nodeodm -p 3000:3000 docker.io/opendronemap/nodeodm
} elseif ($existing -notmatch "^nodeodm Up") {
    & $podman start nodeodm
}

$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    try {
        $info = Invoke-RestMethod http://localhost:3000/info -TimeoutSec 3
        Write-Output ("NodeODM {0} (engine {1} {2}) ready at http://localhost:3000 - {3} cores, {4:N1} GB RAM" -f `
            $info.version, $info.engine, $info.engineVersion, $info.cpuCores, ($info.totalMemory / 1GB))
        exit 0
    } catch { Start-Sleep -Seconds 2 }
}
Write-Error "NodeODM did not respond on http://localhost:3000 within 60s"
