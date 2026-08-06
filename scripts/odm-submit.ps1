# Submit a folder of images (plus optional GCP file) to NodeODM as a new task.
# Usage: .\scripts\odm-submit.ps1 -ImagesDir data\aukerman\images -Name my-run
#        .\scripts\odm-submit.ps1 -ImagesDir <dir> -Name <name> -GcpFile <gcp_list.txt> -OptionsJson '[{"name":"dsm","value":true}]'
param(
    [Parameter(Mandatory = $true)][string]$ImagesDir,
    [string]$Name = ("run-" + (Get-Date -Format yyyyMMdd-HHmmss)),
    [string]$GcpFile,
    [string]$OptionsJson
)

$imgs = Get-ChildItem $ImagesDir -File | Where-Object { $_.Extension -match "^\.(jpe?g|png|tiff?)$" }
if (-not $imgs) { Write-Error "No images found in $ImagesDir"; exit 1 }

$curlArgs = @("-s", "-X", "POST", "http://localhost:3000/task/new", "-F", "name=$Name")
# PS 5.1 strips embedded quotes when passing args to native exes; escape for curl
if ($OptionsJson) { $curlArgs += @("-F", "options=$($OptionsJson.Replace('"','\"'))") }
foreach ($f in $imgs) { $curlArgs += @("-F", "images=@$($f.FullName)") }
if ($GcpFile) { $curlArgs += @("-F", "images=@$((Get-Item $GcpFile).FullName)") }

$resp = & curl.exe @curlArgs | ConvertFrom-Json
if (-not $resp.uuid) { Write-Error "Submission failed: $($resp | ConvertTo-Json)"; exit 1 }
Write-Output ("Task {0} submitted: {1} images{2}" -f $resp.uuid, $imgs.Count, $(if ($GcpFile) { " + GCP file" } else { "" }))
Write-Output "Watch progress: http://localhost:3000  |  API: http://localhost:3000/task/$($resp.uuid)/info"
