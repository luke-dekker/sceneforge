<#
.SYNOPSIS
  Build and run a Meshroom 2025.1 photogrammetry graph headless, in RAM-safe stages.

.DESCRIPTION
  Front half of the sceneforge Meshroom recipe (docs/meshroom-recipe.md).
  Back half (georef / ortho / Godot / ArcGIS) is scripts\meshroom_postrun.ps1.

  -Build   : meshroom_batch builds <Run>\<Name>.mg from the image folders WITHOUT
             computing, with the graph-dir cache, and prints the detected camera
             intrinsics so you can sanity-check sensor widths before burning hours.
  -Compute : meshroom_compute runs the saved graph up to -ToNode. Default stops
             at DepthMapFilter_1 (GPU-bound, low RAM). Run again with
             -ToNode Texturing_1 for Meshing->Texturing once RAM is free:
             Meshing peaks ~5 GB resident for ~90 images; the commit limit
             (RAM + pagefile) is what matters, but free RAM < ~4 GB will crawl.
  Both     : -Build then -Compute.

  Gotchas this script encodes (see memory/docs for the war stories):
    * meshroom_batch refuses "-p file.mg" without -i, and "-p file.mg" ignores
      --cache. We build once with -s/--cache, then only ever use meshroom_compute,
      which re-invokes itself per node using the cache next to the .mg.
    * Cameras missing from AliceVision's cameraSensors.db get a 45-degree FOV
      guess. Add "Make;Model;SensorWidthMm;usercontribution" lines (the script
      warns if your images' models are absent). Known: DJI;M3M;17.3  DJI;FC3682;9.6
    * The frozen Meshroom exports PYTHONHOME/PYTHONPATH; plugin nodes that spawn
      python scrub them (handled in the plugin pack, not here).

.PARAMETER Images
  One or more image folders (each folder = one camera by default; images with
  full EXIF group by make/model/focal/size regardless of folder).
.PARAMETER Run
  Run directory, e.g. runs\farm2026-meshroom. Created if missing.
.PARAMETER Name
  Graph name (default: leaf of -Run). Produces <Run>\<Name>.mg.
.PARAMETER Pipeline
  Meshroom template: "photogrammetry" (stock, default) or a .mg path such as
  meshroom-plugin\pipelines\sceneforgePhotogrammetry.mg.
.PARAMETER ParamOverrides
  Extra meshroom_batch --paramOverrides entries. Defaults trim Meshing to
  30M/4M points and Texturing to 4096px atlases, which fit a 16 GB laptop.
.PARAMETER ToNode
  Node to compute up to (default DepthMapFilter_1).
.PARAMETER Wait
  With -Compute: block until meshroom_compute exits (default: detach and
  return; logs land in <Run>\compute-<ToNode>.log/.err).

.EXAMPLE
  .\scripts\meshroom_run.ps1 -Build -Images data\farm2026\m3m_nadir_raw,data\farm2026\mini3_obliques -Run runs\farm2026-meshroom
  .\scripts\meshroom_run.ps1 -Compute -Run runs\farm2026-meshroom                      # stage 1 (detached)
  .\scripts\meshroom_run.ps1 -Compute -Run runs\farm2026-meshroom -ToNode Texturing_1  # stage 2
#>
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$Compute,
    [string[]]$Images,
    [Parameter(Mandatory = $true)][string]$Run,
    [string]$Name,
    [string]$Pipeline = "photogrammetry",
    [string[]]$ParamOverrides = @(
        "Meshing_1.maxInputPoints=30000000",
        "Meshing_1.maxPoints=4000000",
        "Texturing_1.textureSide=4096",
        "Texturing_1.downscale=2"),
    [string]$ToNode = "DepthMapFilter_1",
    [switch]$Wait,
    [string]$MeshroomDir = "C:\Users\lucas\tools\photogrammetry\Meshroom-2025.1.0"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if (-not $Build -and -not $Compute) { $Build = $true; $Compute = $true }

$Run = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Run))
if (-not $Name) { $Name = Split-Path -Leaf $Run }
$graph = Join-Path $Run "$Name.mg"
$cache = Join-Path $Run "MeshroomCache"
New-Item -ItemType Directory -Force $Run | Out-Null

# plugin pack + templates, same as tools\photogrammetry\meshroom-2025.ps1
$env:MESHROOM_PLUGINS_PATH = Join-Path $repo "meshroom-plugin\sceneforgeGeo"
$env:MESHROOM_PIPELINE_TEMPLATES_PATH = Join-Path $repo "meshroom-plugin\pipelines"

function Test-SensorDb([string[]]$folders) {
    $db = Join-Path $MeshroomDir "aliceVision\share\aliceVision\cameraSensors.db"
    $known = (Get-Content $db) | ForEach-Object { ($_ -split ";")[1] }
    $models = @{}
    foreach ($f in $folders) {
        $first = Get-ChildItem $f -File | Where-Object { $_.Extension -match "\.(jpe?g|tiff?|png|dng)$" } | Select-Object -First 1
        if (-not $first) { continue }
        $model = & python -c "from PIL import Image; from PIL.ExifTags import TAGS; e=Image.open(r'$($first.FullName)')._getexif() or {}; print({TAGS.get(k):v for k,v in e.items()}.get('Model','').strip('\x00 '))"
        if ($model) { $models[$model] = $first.Name }
    }
    foreach ($m in $models.Keys) {
        if ($known -contains $m) { "  sensor db: $m OK" }
        else { Write-Warning "camera model '$m' ($($models[$m])) is NOT in $db - add 'Make;$m;<sensor width mm>;usercontribution' or intrinsics start from a 45-degree FOV guess" }
    }
}

if ($Build) {
    if (-not $Images) { throw "-Build needs -Images <folder>[,<folder>...]" }
    $abs = $Images | ForEach-Object { [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $_)) }
    "== build $graph"
    Test-SensorDb $abs
    $ov = @(); if ($ParamOverrides) { $ov = @("--paramOverrides") + $ParamOverrides }
    # PS 5.1 turns native stderr into terminating errors under 2>&1 + Stop;
    # Meshroom prints a harmless DeprecationWarning there, so relax for this call.
    $ErrorActionPreference = "Continue"
    & (Join-Path $MeshroomDir "meshroom_batch.exe") -i ($abs -join ";") -p $Pipeline -s $graph --cache $cache --compute no @ov 2>&1 |
        ForEach-Object { "$_" } |
        Where-Object { $_ -notmatch "DeprecationWarning|distutils" -and $_ -match "Intrinsics|saved|Overrides|views|WARNING|Error" }
    $ErrorActionPreference = "Stop"
    if (-not (Test-Path $graph)) { throw "graph not written" }
    & python (Join-Path $PSScriptRoot "meshroom_graph_info.py") $graph
}

if ($Compute) {
    if (-not (Test-Path $graph)) { throw "no graph at $graph - run with -Build first" }
    $os = Get-CimInstance Win32_OperatingSystem
    $freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    "== compute $Name -> $ToNode  (free RAM $freeGB GB)"
    if ($ToNode -match "Meshing|MeshFiltering|Texturing|Publish" -and $freeGB -lt 4) {
        Write-Warning "only $freeGB GB free: Meshing peaks ~5 GB resident; close browsers or expect heavy paging"
    }
    $log = Join-Path $Run "compute-$ToNode.log"
    $err = Join-Path $Run "compute-$ToNode.err"
    $p = Start-Process -FilePath (Join-Path $MeshroomDir "meshroom_compute.exe") `
        -ArgumentList @("`"$graph`"", "--toNode", $ToNode) -WorkingDirectory $Run `
        -RedirectStandardOutput $log -RedirectStandardError $err -PassThru -WindowStyle Hidden
    "  pid $($p.Id)  logs: $log / $err"
    "  node logs: $cache\<Node>\<hash>\log   (meshroom_compute forks one child per node)"
    if ($Wait) { $p.WaitForExit(); "  exited $($p.ExitCode) at $(Get-Date -Format HH:mm)" }
    else { "  detached; poll with: Get-ChildItem $cache -Directory | % Name" }
}
