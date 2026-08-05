# Reconstruction & accuracy pipeline

Capture → georeferenced, metrically honest 3D assets. Written from working knowledge (early 2026); items marked ⚠ deserve a quick check against current docs before we build on them.

## Recommended stack

| Stage | Tool | Why |
|---|---|---|
| Photogrammetry | **OpenDroneMap (ODM via Docker, NodeODM API)** | Purpose-built for drone mapping: GCP support, georeferenced outputs, accuracy report, fully headless REST API |
| Research-grade alternative | **COLMAP + OpenMVS** | Finer control over SfM/MVS when ODM's pipeline is limiting; also produces the poses needed for splat training |
| PPK | **RTKLIB (rtklibexplorer/demo5 fork)** | The maintained fork tuned for low-cost receivers; post-processes drone/rover logs against our own base RINEX |
| Geotag injection | **ExifTool** | Rewrite image EXIF GPS from PPK solutions before photogrammetry |
| Registration & QC | **CloudCompare (GUI + CLI)** + **Open3D** | Coarse+ICP alignment of scanner data into the georeferenced frame; cloud-to-cloud distance QC |
| Point cloud plumbing | **PDAL** | JSON-defined pipelines: CRS reprojection, filtering, LAS/LAZ/COPC output — ideal for node-graph automation |

## 1. Photogrammetry engines

- **ODM / WebODM / NodeODM** — the direct open replacement for Drone2Map. Consumes a `gcp_list.txt`, produces orthomosaic, DSM/DTM, textured mesh, georeferenced point cloud, and a processing report with GCP residuals. NodeODM exposes everything over REST; WebODM is the friendly front-end. Runs best in Docker (fine on Windows 11 + WSL2).
- **COLMAP + OpenMVS** — best-in-class sparse SfM plus dense reconstruction/texturing. More accurate camera calibration control; no native GCP/georeferencing workflow (georeferencing is bolted on via similarity transform from known points). Keep in the toolbox: COLMAP poses are also the input for Gaussian splat training.
- **Meshroom (AliceVision)** — node-graph UI (aesthetically on-brand), decent quality, weaker geo workflow and slower; not the primary.
- **MicMac (IGN)** — arguably the most rigorous photogrammetric accuracy of the open options, but a steep, idiosyncratic CLI; revisit only if we hit an accuracy wall. ⚠ maintenance cadence worth checking.

**Choice: ODM primary.** It covers the GCP→report loop out of the box and its API matches our "every stage headless" principle.

## 2. RTK / PPK and ground control

Two complementary accuracy inputs:

1. **PPK on the drone** (if the drone logs raw GNSS — many consumer drones don't; if ours doesn't, skip and rely on GCPs alone):
   - Convert base + rover logs to RINEX, post-process with RTKLIB demo5 (`rnx2rtkp`), get fixed-solution positions per exposure event, write back into EXIF with ExifTool.
2. **GCPs surveyed with the RTK rover** against our own base:
   - Targets: high-contrast checkerboard or iron-cross mats, sized so they span ≥10–20 px in imagery at flight altitude.
   - Occupation: ~30 s fixed-solution average per point is plenty when the baseline is short.
   - Distribute GCPs around the perimeter + center; **hold 2–3 out as checkpoints** — they don't constrain the solution, they grade it. Checkpoint RMSE is the honest accuracy number we publish per run.
   - Coordinate systems: survey in the base's frame, work in a projected CRS (e.g. the local UTM zone, EPSG code pinned per site). Heights: RTK gives ellipsoidal; if we ever need orthometric, apply a geoid model (e.g. GEOID18 via PROJ grids). For ML/sim use, staying ellipsoidal + local ENU is simpler and self-consistent.
   - One subtlety worth a plan: our base's own coordinates define absolute accuracy. Average the base position long-term or OPUS/PPP-correct it once ⚠ (verify current free PPP services), then never move it.

**ODM GCP format** — `gcp_list.txt`: first line is the CRS (e.g. `EPSG:32610`), then one line per observation: `geo_x geo_y geo_z pixel_x pixel_y image_name` (a GCP appears once per image it's visible in, ≥3 images each). ⚠ verify exact current format/flags before first run. WebODM has a built-in GCP tagging interface, which beats hand-tagging.

## 3. Einstar scans → georeferenced frame

The Einstar's strength is sub-mm relative accuracy and correct metric scale; it knows nothing about where it is in the world. Registration strategy:

1. Export PLY/OBJ from the (proprietary, unavoidable) capture software.
2. **Coarse align** to the photogrammetry model: manual point-pair picking in CloudCompare, or automated global registration (Open3D FPFH + RANSAC) when geometry is distinctive.
3. **Fine align** with ICP — point-to-plane, scale *locked* (the scanner's scale is more trustworthy than photogrammetry's; if there's a scale disagreement, that's a finding about our photogrammetry, not something to absorb silently).
4. **QC**: cloud-to-cloud distance between the registered scan and the photogrammetry surface. Report median + 95th percentile. This doubles as an independent check on the whole chain.

Automation: CloudCompare has a capable CLI (`-ICP`, `-C2C_DIST`, transforms, format conversion) but coarse alignment is the weak point headlessly. Practical split: **Open3D (Python) for coarse+fine registration in scripts; CloudCompare for interactive inspection**. `small_gicp` is a faster modern ICP library if Open3D's becomes a bottleneck. (TEASER++ exists for robust global registration; overkill until proven needed.)

## 4. Point cloud plumbing & QC

- **PDAL** pipelines (JSON) handle: reprojection (`filters.reprojection`), cropping, outlier removal (`filters.outlier`), ground classification (`filters.smrf`), thinning, and writing LAS/LAZ/**COPC** (cloud-optimized, streamable — good archive format).
- **Per-run accuracy report** (the pipeline should emit this automatically):
  - GCP residuals + held-out checkpoint RMSE (from ODM report)
  - PPK fix rate, if used
  - Scanner registration ICP RMSE + C2C distance stats
  - Point density map
- Open3D covers mesh sampling, normals, and any custom metrics in Python.

## 5. Notes from prior-art scan (partial)

The aborted web-research pass surfaced (unverified beyond snippets ⚠): the standard published pattern for UAV + terrestrial fusion is exactly the above — GNSS-controlled photogrammetry as the georeferenced skeleton, close-range scans ICP-registered into it, with error budgets dominated by GCP survey quality and image network geometry. Nothing surfaced contradicts the recommended stack.

## Open questions

- Does our drone log raw GNSS / expose exposure events? Determines whether PPK is on the table or GCP-only.
- Base station absolute position: has it been PPP/long-average corrected, and is the value pinned somewhere version-controlled?
- Einstar export: confirm PLY with vertex colors (helps coarse registration visually and any learned features later).
