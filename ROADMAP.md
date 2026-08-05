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

## Phase 3 — Scan-to-sim

- Mesh prep: decimation/LOD, collision decomposition, terrain/object split
- Import into chosen simulator(s); real-scale, georeferenced scene composition
- Target application: drone + manipulator simulation in reconstructed real spaces

## Phase 4 — Automation & integration

- Wrap stages as composable nodes (node-graph tooling)
- Capture-to-dataset runs as reproducible, one-command pipelines
