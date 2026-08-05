# sceneforge

**Real places → survey-grade 3D assets → machine learning data.**

sceneforge is an open-source pipeline (in progress) for turning drone photogrammetry and handheld 3D scans into georeferenced, metrically accurate 3D scenes — and then using those scenes as a factory for machine learning training data and robotics simulation environments.

## Why

A reconstructed scene with centimeter-level ground control isn't just a pretty model — it's reusable ground truth. One good capture can produce:

- **Supervised stereo depth data** — rendered calibrated stereo RGB pairs with perfect dense disparity/depth, for training networks that run on real stereo cameras.
- **Robotics sim environments** — real-world geometry imported into open simulators/game engines for drone and manipulator policy development.
- **Point cloud datasets** — segmentation/classification sets sampled from accurate geometry.

## Capture stack (hardware)

| Layer | Hardware |
|---|---|
| Aerial | DJI Mini 3 (photogrammetry) |
| Close range | Shining3D Einstar handheld scanner (sub-mm, exports PLY/OBJ) |
| Control | Self-hosted RTK base (NTRIP/RTCM) + rover-surveyed ground control points |

Ground control points constrain the reconstruction; held-out checkpoints measure it honestly. Everything downstream inherits that accuracy.

## Principles

- **Open source end to end.** The one unavoidable proprietary step is the Einstar's capture software; everything after ingest is open tooling.
- **Headless and scriptable.** Every stage must run without a GUI so the pipeline can be automated and composed (eventually as nodes in a node-graph tool).
- **Measured, not assumed.** Each run should report its own error budget (checkpoint RMSE, registration residuals).

## Status

🔬 **Research phase.** The tooling survey for each stage is drafted in [`docs/`](docs/) — recommended stacks chosen, with ⚠ flags on the specific claims to verify against current upstream docs before building on them:

- `docs/reconstruction.md` — photogrammetry engines, RTK/PPK, GCP workflow, scanner registration, point cloud QC
- `docs/stereo-ground-truth.md` — generating supervised stereo depth training data from reconstructed scenes
- `docs/scan-to-sim.md` — importing reconstructions into game engines and robotics simulators

See [`ROADMAP.md`](ROADMAP.md) for where this is headed.

## License

MIT
