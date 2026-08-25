# sceneforge-geo — Meshroom 2025.1 plugin pack

Thin Meshroom nodes over the sceneforge CLI scripts (`scripts/`). All logic
lives in the scripts — the nodes just build a command line and run it in a
subprocess, so everything works identically from the shell, from Meshroom, or
from any other frontend.

## Nodes (category "SceneForge")

| Node | Wraps | Purpose |
|---|---|---|
| `AccuracyReport` | `gcp_residuals.py` | grade a solve against ground control: per-GCP residuals, checkpoint RMSE, bad-tag flags |
| `GeorefSolve` | `georef_solve.py` | GCP similarity solve (Umeyama) + optional mesh apply; checkpoints report honest accuracy |
| `TrueOrtho` | `true_ortho.py` | z-buffer render of the final mesh → true orthophoto + DSM GeoTIFFs |
| `CollisionPrep` | `collision_prep.py` | CoACD convex hulls for physics (Godot glb + MuJoCo objs + manifest) |
| `HeightfieldScene` | `heightfield_glb.py` | DSM + ortho GeoTIFF → walkable terrain GLB + georef sidecar |
| `GodotScenePrep` | `prep_godot.py` | georeferenced mesh → Godot scene folder (Y-up glb + scene.json GeoPose) |
| `RtlToUtmGeotiff` | `rtl_to_utm_geotiff.py` | MicMac RTL raster → UTM GeoTIFF + sidecar |
| `GcpConvertMicMac` | `gcp_to_micmac.py` | ODM gcp_list.txt → MicMac GCP XML + checkpoint holdout |
| `MeshConvert` | `mesh_convert.py` | Meshroom textured OBJ → engine-ready glb (EXR→sRGB JPG, weld+simplify) |
| `BlenderScene` | `blender_scene.py` | sceneforge scene → .blend (real scale, georef props, accurate sun) + optional orbit flythrough mp4 |

Solve inputs (`AccuracyReport`, `GeorefSolve`) accept an ODM run dir or an
AliceVision `cameras.sfm` (see `scripts/sfm_io.py`; the AliceVision reader was
validated 2026-08-24 against native Meshroom farm solves — RTK camera-GPS fit
3.5 cm RMSE; `GeorefSolve` also accepts `--camera-gps` for GCP-free georef; check the
constraint residuals on the first real run).

Georeference travels between nodes as a sidecar json (`{"proj4": ..., "utm_offset": [E, N]}`)
— the same convention `rtl_to_utm_geotiff.py` established. `HeightfieldScene.sidecar`
wires straight into `GodotScenePrep.sidecar`.

## Loading

Each entry in `MESHROOM_PLUGINS_PATH` names **one plugin root** (the folder
containing `meshroom/`), pathsep-separated — not a folder of plugins:

```powershell
$env:MESHROOM_PLUGINS_PATH = "C:\Users\lucas\sceneforge\meshroom-plugin\sceneforgeGeo"
```

`tools\photogrammetry\meshroom-2025.ps1` sets this and launches the GUI.

## Pipeline template

`pipelines/sceneforgePhotogrammetry.mg` = stock photogrammetry chain +
`MeshConvert → GodotScenePrep → BlenderScene`: images in, Godot scene folder +
ready-to-open .blend (and optional flythrough mp4) out. The launcher exports
`MESHROOM_PIPELINE_TEMPLATES_PATH` so it appears in the GUI's pipeline list;
headless: `meshroom_batch -i <images> -p pipelines/sceneforgePhotogrammetry.mg`.
⚠ The template ships a **placeholder georef** (UTM zone 10, offset 0,0 = local
frame); set the real proj/offset on `GodotScenePrep`, or wire a `GeorefSolve`
sidecar, for true geolocation.

## Gotchas

- Nodes run the scripts with the **system Python** (`pythonBin` param, default
  `python` from PATH) — it needs the sceneforge deps (rasterio, trimesh, scipy,
  pygltflib, pyproj). Meshroom's frozen runtime exports `PYTHONHOME`/`PYTHONPATH`
  pointing at its own stdlib; the nodes scrub both before spawning, or the child
  Python dies with `bad magic number in 'encodings'`.
- Headless test: `meshroom_compute graph.mg --toNode <node> --inCurrentEnv`
  (with `MESHROOM_PLUGINS_PATH` set). Note it re-invokes itself per node with
  the graph-file-relative default cache (`<graph dir>/MeshroomCache`), ignoring
  a parent `--cache` override.
