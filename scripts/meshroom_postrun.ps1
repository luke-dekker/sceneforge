<#
.SYNOPSIS
  Turn a finished Meshroom run into georeferenced deliverables:
  engine glb -> RTK/GCP georef (+crop) -> Godot scene -> true ortho + DSM -> ArcGIS OBJ.

.DESCRIPTION
  Back half of the sceneforge Meshroom recipe (docs/meshroom-recipe.md); the
  front half is scripts\meshroom_run.ps1. Every step is a CLI script in
  scripts\ - this file only sequences them and stops at the first failure, so
  you can rerun any single step by hand with the printed command.

  Steps (each skippable):
    1. mesh_convert.py     Meshroom OBJ (+linear EXR) -> welded/simplified glb, sRGB JPG textures
    2. georef_solve.py     similarity solve (scale/rotation/translation) onto the real world:
                           default --camera-gps fits on RTK-fixed camera positions (DJI RtkFlag 50),
                           non-RTK views are graded as checkpoints; -Gcp <gcp_list.txt> uses ground
                           control instead. Crops reconstruction fringe + below-ground skirt.
    3. prep_godot.py       Y-up glb + scene.json GeoPose into godot\scenes\<Name> (+ dist\scenes mirror
                           for the standalone walker)
    4. true_ortho.py       z-buffer true orthophoto + DSM GeoTIFFs (EPSG from the sidecar)
    5. export_arcgis_obj.py absolute-UTM OBJ + MTL + JPG for ArcGIS Pro "Import 3D Files"

  Heights are whatever the georef source used: DJI RTK = WGS84 ellipsoid
  (Olympia: ~22 m below NAVD88). The sidecars record this.

.PARAMETER Run
  Meshroom run directory holding MeshroomCache (from meshroom_run.ps1).
.PARAMETER Name
  Scene name (default: leaf of -Run). Used for every output file/folder.
.PARAMETER Gcp
  gcp_list.txt for GCP-based georef instead of camera GPS. Use -Checkpoints to hold out points.
.PARAMETER FitViews
  camera-gps only: regex on filenames to fit on (default: RtkFlag==50 views, else all).
.PARAMETER Ratio
  gltf-transform simplification ratio for the engine glb (default 0.35).
.PARAMETER Gsd
  Ortho/DSM ground sample distance in metres (default 0.05).
.PARAMETER CropMargin / CropZDepth
  Drop faces outside the camera/GCP bounding box grown by CropMargin metres (default 40),
  and faces more than CropZDepth metres below the median Z (default 8). Pass -1 to disable.
.PARAMETER SkipConvert / SkipGodot / SkipOrtho / SkipArcgis
  Skip steps (georef always runs; it is what everything downstream consumes).

.EXAMPLE
  .\scripts\meshroom_postrun.ps1 -Run runs\farm2026-meshroom
  .\scripts\meshroom_postrun.ps1 -Run runs\site -Gcp data\site\gcp_list.txt -Checkpoints gcp05,gcp09 -Gsd 0.1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Run,
    [string]$Name,
    [string]$Gcp,
    [string[]]$Checkpoints = @(),
    [string]$FitViews,
    [double]$Ratio = 0.35,
    [double]$Gsd = 0.05,
    [double]$CropMargin = 40,
    [double]$CropZDepth = 8,
    [switch]$SkipConvert,
    [switch]$SkipGodot,
    [switch]$SkipOrtho,
    [switch]$SkipArcgis
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$Run = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Run))
if (-not $Name) { $Name = Split-Path -Leaf $Run }
Set-Location $repo

function Step([string]$title, [string[]]$cmd) {
    "`n== $title"
    "   python $($cmd -join ' ')"
    & python @cmd
    if ($LASTEXITCODE -ne 0) { throw "$title failed (exit $LASTEXITCODE) - fix and rerun the command above" }
}

$tex = Get-ChildItem "$Run\MeshroomCache\Texturing\*\texturedMesh.obj" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
$sfm = Get-ChildItem "$Run\MeshroomCache\StructureFromMotion\*\cameras.sfm" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $sfm) { throw "no StructureFromMotion\*\cameras.sfm under $Run\MeshroomCache" }
if (-not $tex -and -not $SkipConvert) { throw "no Texturing\*\texturedMesh.obj under $Run\MeshroomCache (run meshroom_run.ps1 -Compute -ToNode Texturing_1)" }
"scene $Name"; "solve  $($sfm.FullName)"; if ($tex) { "mesh   $($tex.FullName)" }

$engine = "$Run\engine\$Name.glb"
if (-not $SkipConvert) {
    Step "1. mesh_convert" @("scripts\mesh_convert.py", "--mesh", $tex.FullName, "--out", "$Run\engine", "--name", $Name, "--ratio", $Ratio)
}
if (-not (Test-Path $engine)) { throw "engine glb missing: $engine" }

$geo = @("scripts\georef_solve.py", $sfm.FullName, "--apply", $engine, "-o", "$Run\georef")
if ($Gcp) { $geo += @("--gcp", $Gcp); if ($Checkpoints) { $geo += @("--checkpoints") + $Checkpoints } }
else { $geo += "--camera-gps"; if ($FitViews) { $geo += @("--fit-views", $FitViews) } }
if ($CropMargin -ge 0) { $geo += @("--crop-margin", $CropMargin) }
if ($CropZDepth -ge 0) { $geo += @("--crop-z-depth", $CropZDepth) }
Step "2. georef_solve ($(if ($Gcp) { 'GCPs' } else { 'camera GPS' }))" $geo
$geoGlb = "$Run\georef\$Name`_geo.glb"

if (-not $SkipGodot) {
    Step "3. prep_godot" @("scripts\prep_godot.py", "--mesh", $geoGlb, "--name", $Name, "-o", "$repo\godot\scenes\$Name")
    if (Test-Path "$repo\dist\scenes") {
        New-Item -ItemType Directory -Force "$repo\dist\scenes\$Name" | Out-Null
        Copy-Item "$repo\godot\scenes\$Name\*" "$repo\dist\scenes\$Name\" -Force
        "   mirrored to dist\scenes\$Name (standalone walker: Tab cycles scenes alphabetically)"
    }
}
if (-not $SkipOrtho) {
    Step "4. true_ortho" @("scripts\true_ortho.py", $geoGlb, "--gsd", $Gsd, "-o", "$Run\ortho\$Name")
}
if (-not $SkipArcgis) {
    Step "5. export_arcgis_obj" @("scripts\export_arcgis_obj.py", $geoGlb, "-o", "$Run\arcgis\$Name")
}

"`n== done $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
"   accuracy      $Run\georef\georef_transform.json"
"   engine glb    $engine"
"   geo glb       $geoGlb (+ .json sidecar)"
if (-not $SkipGodot)  { "   godot scene   godot\scenes\$Name" }
if (-not $SkipOrtho)  { "   ortho / dsm   $Run\ortho\$Name.tif / $Name`_dsm.tif" }
if (-not $SkipArcgis) { "   arcgis obj    $Run\arcgis\$Name.obj  (Import 3D Files, EPSG in $Name.arcgis.json, Y-is-up UNCHECKED)" }
