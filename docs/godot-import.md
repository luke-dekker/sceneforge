# Godot import plan (Phase 3, first slice)

Target: the north-star milestone rehearsed on the Aukerman test scene — a georeferenced ODM
reconstruction, walkable in Godot at true scale, with its georef carried in a `scene.json`
sidecar. Real GCP-fixed site scans reuse this path unchanged.

## Step 0 — Collect + inspect the ODM output (blocked on the running smoke test)

- Download `http://localhost:3000/task/<uuid>/download/all.zip` → extract to `runs/aukerman-smoke/`.
- Expected assets (gltf/cog/pc-ept were enabled): `odm_texturing/odm_textured_model_geo.glb`,
  `odm_georeferencing/odm_georeferenced_model.laz` + `coords.txt` (proj string + UTM offset),
  `odm_orthophoto/odm_orthophoto.tif` (COG), `entwine_pointcloud/`.
- ⚠ Verify on the real output, not docs: which frame the .glb is actually in (expected:
  UTM-minus-offset local frame, Z-up, meters) and whether textures came through in the glb.

## Step 1 — Rebase + sidecar: `scripts/prep_godot.py`

- Parse `coords.txt` → CRS + offset; convert offset to lat/lon/h with pyproj → that is the
  local-ENU origin.
- Write `scene.json` next to the mesh: CRS, origin (lat/lon/h), source run id, and the
  engine-frame transform — following OGC GeoPose's shape (per docs/scan-to-sim.md §3).
- Convert Z-up (ODM/geo) → Y-up (glTF spec) so the scene stands upright in Godot. Smoke path:
  trimesh or pygltflib rotation; Blender `--background` is the fallback if materials get mangled.
- Optional `--pack` flag: gltfpack decimation/quantization/KTX2. Skip for the first import —
  see the raw mesh before optimizing it.

## Step 2 — Godot project: `godot/` in this repo

- Godot 4.4+ (Jolt physics built in), minimal project, no addons yet. Local editor found:
  `Downloads\Godot_v4.4.1-stable_win64.exe` (consider moving somewhere permanent).
- Import the .glb at real scale (no scene-scale fudge factors, ever — fix the asset instead).
- `scene_loader.gd`: load mesh + `scene.json`, apply transform, HUD showing CRS/origin/run id.
- Walkable: CharacterBody3D walk controller + free-fly camera toggle; collision from
  `create_trimesh_collision()` on the terrain mesh (CoACD comes later, for MuJoCo, not for this).
- WorldEnvironment + directional sun; orient so geographic north matches the ortho.

### Verification (what "imported correctly" means)

1. Scale: measure a feature in the orthophoto (GSD-known) vs Godot's ruler — must agree.
2. Orientation: north in-engine matches north in the ortho; Z-up→Y-up didn't mirror the scene.
3. Walkable: controller stands on the terrain, no fall-through, textures visible.
4. Georef round-trip: pick a point in Godot, transform back through scene.json → sane lat/lon.

### Known Godot gotchas to watch (from docs/scan-to-sim.md)

- 256-materials-per-mesh import limit — ODM texturing emits multiple texture atlases; if the
  smoke mesh exceeds it, merge atlases in the prep script.
- Reported glTF import file-bloat case; check `.godot/imported/` size after first import.

## Step 3 — Make the rehearsal GCP-fixed

Aukerman ships **no** GCP file (verified against upstream, 2026-08-06). ODM sample datasets
that do: `odm_data_bellus` and `odm_data_copr` (root `gcp_list.txt`), `odm_data_helenenschacht`
(`GCP/gcp_list.txt`). Pick the smaller one, run with `odm-submit.ps1 -GcpFile`, hold out 2–3
GCPs as checkpoints (Phase 1 accuracy report). Then the *entire* milestone — GCP-fixed,
ground-truth-aligned, walkable in Godot — is proven on rehearsal data before the Mini 3 ever
flies a site. (The real path stays Luke's own RTK-surveyed GCPs from the rtk-base setup.)

## Explicitly deferred

3D Tiles for Godot (only when scenes outgrow a single glb) · GDGS splat twin · VR/OpenXR ·
sharing collision geometry with MuJoCo (Phase 3 robot-training slice).
