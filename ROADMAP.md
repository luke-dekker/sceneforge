# Roadmap

## Phase 0 — Research (current)

Survey open tooling for each pipeline stage; publish findings in `docs/`. Output: a chosen stack per stage and an honest list of gaps.

## Phase 1 — Reconstruction pipeline

- GCP survey workflow with RTK rover (targets, occupation, CRS handling)
- Photogrammetry runs with GCP constraint + held-out checkpoint reporting
- Einstar scan registration into the georeferenced frame
- Per-run accuracy report (checkpoint RMSE, cloud-to-cloud residuals)
- Everything headless: one command from image/scan folder to georeferenced assets

## Phase 2 — First dataset: stereo depth ground truth

- Render calibrated stereo RGB + dense disparity/depth from reconstructed scenes
- Match a real stereo rig's intrinsics/baseline; add realistic degradation
- Export in formats stereo training codebases consume
- Baseline experiment: fine-tune an open stereo network, evaluate on real captures

## Phase 3 — Scan-to-sim (Godot first)

**North-star milestone: a GCP-fixed, ground-truth-aligned scene of a real place, walkable in Godot.**

- Mesh prep: decimation/LOD (gltfpack), collision decomposition (CoACD), terrain/object split
- Godot import: glTF at real scale, local-ENU origin, `scene.json` georef sidecar; large scenes via 3D Tiles for Godot
- Visualization layer: fly-through/walkthrough of the scene next to its own accuracy data; VR via Godot's built-in OpenXR (mesh first — splat rendering in VR is a stretch goal)
- Splat twin: same scene as Gaussian splats in Godot (GDGS plugin) for photoreal desktop viewing
- Robot training: drone + arm physics in MuJoCo using the same collision geometry; Godot as teleop/observation front-end; evaluate Godot RL Agents for in-engine learning

## Phase 4 — Automation & integration

- Wrap stages as composable nodes (node-graph tooling)
- Capture-to-dataset runs as reproducible, one-command pipelines
