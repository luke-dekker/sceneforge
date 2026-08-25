# Meshroom recipe: drone photos → georeferenced scene for ArcGIS / Godot

The open Drone2Map path. Everything below is two PowerShell scripts around the
CLI tools in `scripts/`; nothing needs the Meshroom GUI, and every step can be
rerun by hand with the command the scripts print.

```
images ──► meshroom_run.ps1 -Build ──► <run>/<name>.mg          (graph + intrinsics check)
       ──► meshroom_run.ps1 -Compute                             (features … depth maps, GPU)
       ──► meshroom_run.ps1 -Compute -ToNode Texturing_1         (meshing … texturing, RAM)
       ──► meshroom_postrun.ps1                                  (georef, Godot, ortho/DSM, ArcGIS)
```

Worked example: the Evergreen farm, 2026-08-24 (`runs/farm2026-meshroom`):
130 images from two drones → 87 localized → 3.85 M-face mesh → RTK georef
3.5 cm / 1.2 cm RMSE → ortho, DSM, Godot scene, ArcGIS OBJ. ~3 h on a 16 GB /
RTX 4050 laptop, of which post-processing was 3 minutes.

## 0. Data prep

- One folder per camera is the safe layout; images with full EXIF group into
  intrinsics by make/model/focal/size anyway. DJI Mavic 3 Multispectral
  captures write a 20 MP RGB `_D.JPG` next to the four `_MS_*.TIF` bands —
  use only the `_D.JPG`s for the mesh.
- OneDrive folders are often *online-only placeholders* (0 bytes on disk,
  `attrib` shows `O`). Copy them out (the copy hydrates them) before pointing
  Meshroom at them.
- Check the camera is in AliceVision's sensor database
  (`Meshroom-2025.1.0\aliceVision\share\aliceVision\cameraSensors.db`,
  `Make;Model;SensorWidthMm;source`). `meshroom_run.ps1 -Build` warns if not;
  add a line. Known additions: `DJI;M3M;17.3`, `DJI;FC3682;9.6` (Mini 3).
  Without it the solve starts from a 45° FOV guess and multi-camera sets go
  wrong.
- Read the XMP before trusting it: DJI RTK models write `RtkFlag=50`
  (fixed) and `AltitudeType=RtkAlt` (WGS84 ellipsoid); a Mini 3 writes
  gimbal pitch as `0` and a GPS altitude that is garbage.

## 1. Build the graph

```powershell
.\scripts\meshroom_run.ps1 -Build -Run runs\<site> -Images data\<site>\camA,data\<site>\camB
```

Builds `<run>/<site>.mg` from the stock `photogrammetry` template with the
cache next to it, computes nothing, and prints the intrinsics it detected:
one line per camera with sensor width, focal and distortion model
(`radialk3` expected). Fix the sensor DB and rebuild if anything looks off.

Defaults trim Meshing to 30 M input / 4 M output points and Texturing to
4096 px atlases so it fits a 16 GB laptop; override with `-ParamOverrides`.
`-Pipeline meshroom-plugin\pipelines\sceneforgePhotogrammetry.mg` swaps in
the template that chains MeshConvert → GodotScenePrep → BlenderScene as
graph nodes instead of running `meshroom_postrun.ps1`.

## 2. Compute in two stages

```powershell
.\scripts\meshroom_run.ps1 -Compute -Run runs\<site>                        # → DepthMapFilter_1
.\scripts\meshroom_run.ps1 -Compute -Run runs\<site> -ToNode Texturing_1    # → textured mesh
```

Stage 1 is GPU-bound and light on RAM (feature extraction ~1.4 GB, depth
maps ~2 GB). Stage 2's Meshing max-flow step is the RAM peak — ~5 GB
resident for 90 images — and the process exits silently when the Windows
commit limit is hit. Close browsers first; an auto-managed pagefile will
absorb an overshoot, slowly.

Progress: `MeshroomCache\<Node>\<hash>\log`. Stage timings on the laptop for
130 × 20 MP images: features 65 min (CPU), matching + SfM 15 min, depth
maps 20 min, meshing 35 min, texturing 60 min.

**Check the SfM before spending stage 2:** the SfM log ends with
`# poses: N`. If N is well below the image count, see *Troubleshooting*.

## 3. Post-process

```powershell
.\scripts\meshroom_postrun.ps1 -Run runs\<site>                               # RTK camera positions
.\scripts\meshroom_postrun.ps1 -Run runs\<site> -Gcp data\<site>\gcp_list.txt -Checkpoints gcp05,gcp09
```

| Step | Script | Output |
|---|---|---|
| convert | `mesh_convert.py` | `<run>/engine/<site>.glb` — welded, simplified (`-Ratio`), sRGB JPG textures |
| georef | `georef_solve.py` | `<run>/georef/<site>_geo.glb` + `.json` sidecar (`proj4`, `utm_offset`, vertical datum) and `georef_transform.json` with per-camera / per-GCP residuals |
| godot | `prep_godot.py` | `godot/scenes/<site>/` (+ `dist/scenes/<site>/` for the standalone walker) |
| ortho | `true_ortho.py` | `<run>/ortho/<site>.tif`, `<site>_dsm.tif` — GeoTIFFs in the site's UTM zone |
| arcgis | `export_arcgis_obj.py` | `<run>/arcgis/<site>.obj` + `.mtl` + JPGs, absolute UTM coordinates |

### Georef without ground control

`--camera-gps` fits a 7-DOF similarity (Umeyama) between the solve's camera
centres and their EXIF/XMP positions. It fits only on views flagged RTK-fixed
(DJI `RtkFlag=50`) when any exist and reports every other view as a
checkpoint. Numbers to expect:

| | constraints (M3M RTK, n=61) | checkpoints (Mini 3, n=26) |
|---|---|---|
| horizontal RMSE | 0.035 m | 0.41 m (consumer GPS) |
| vertical RMSE | 0.012 m | 37 m (Mini 3 altitude tag is meaningless) |

The fit anchors *pose*, not *shape*: self-calibration doming is not fixed by
georeferencing (see `doming-investigation.md`). The cure is capture, below.

Heights are ellipsoidal when the source is DJI RTK. NAVD88 at Olympia is
~22 m higher. The sidecar says which.

### Cropping

Meshroom reconstructs a fringe far outside the flight and a "skirt" below
flat ground. `-CropMargin 40 -CropZDepth 8` (defaults) removes faces outside
the camera bounding box + 40 m and faces more than 8 m below the median Z;
on the farm that dropped 22 % of faces and every below-ground artifact. Pass
`-1` to disable either.

## 4. Into ArcGIS Online (story map)

ArcGIS Pro → *Import 3D Files*:
- Input Files: `<run>/arcgis/<site>.obj` (OBJ is supported; GLB is not)
- Output Feature Class: **in a file geodatabase** (shapefiles drop textures)
- Spatial Reference: the EPSG in `<site>.arcgis.json` (farm: WGS 84 / UTM 10N, 32610), vertical = ellipsoid
- *Y is up*: **unchecked** (the OBJ is Z-up)
- No placement points — coordinates inside the file are used directly

Then *Share As Web Layer* (scene layer) → add to a web scene → embed in the
StoryMap. Add `ortho/<site>.tif` and `_dsm.tif` as hosted tile/imagery
layers for the 2-D pages. Not yet exercised on Pro by us — report back.

## Capture doctrine (what makes the next flight better)

- **Nadir alone dooms flat sites** (doming). Fly cross-grid + at least one
  oblique (−45°) pass; RTK on the aircraft gives cm georef for free.
- **Ladders must overlap.** Orbits at 4 / 9 / 21 m looking at walls do not
  match a 67 m nadir grid looking at roofs — the farm's low orbits (43
  images) formed an island with zero matches to the main model. Fly the
  tiers so each one sees both roofs and walls: ~10 / 20 / 40 / 70 m, all at
  ~45° pitch, each tier ≤ 2× the scale of the next.
- Mixed cameras are fine (M3M + Mini 3 solved as two intrinsics) as long as
  both are in the sensor DB and the scale/viewpoint chain is continuous.
- Shoot 4:3, not 16:9: the crop throws away a third of the sensor.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `meshroom_batch`: "Nothing to compute. You need to set --input" | it refuses `-p file.mg` without `-i`; use `meshroom_compute` on the saved graph (what `-Compute` does) |
| `# poses` ≪ images; a whole flight missing | match-graph island. Diagnose with the FeatureMatching `*.matches.txt` counts; islands with 0 matches to localized views need capture, not settings. Bridge views failing resection off a single weak view (58 matches) → try `FeatureExtraction describerPreset=high` + `FeatureMatching guidedMatching=True`, rerun from SfM |
| Meshing process disappears, no error | Windows commit limit; free RAM, or lower `Meshing_1.maxInputPoints` |
| true ortho renders black tiles | Meshroom UDIM UVs (u offset per tile) — fixed in `true_ortho.py` (wraps) and `export_arcgis_obj.py` (normalizes) |
| Godot can't load the glb | Draco-compressed input (ODM) — `prep_godot.py` decodes via gltf-transform |
| Walker spawns in the void / falls forever, mesh looks upside down | you were under the mesh: the spawn point (engine 0,0) was outside the footprint. `prep_godot.py` now recentres the origin on the mesh footprint and folds the shift into `utm_offset` (`--no-center` restores the old behaviour); re-run step 3 |
| Mini 3 checkpoints 30–40 m off vertically | expected; never `--fit-views` on non-RTK altitude |
