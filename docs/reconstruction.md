# Reconstruction & accuracy pipeline

Capture → georeferenced, metrically honest 3D assets.

**Provenance:** merged from a web-research pass (August 2026) and working knowledge. Claims with a URL were read from that source by a research agent (single read, not independently double-checked). ⚠ marks claims still needing verification. Two research angles were lost before completing — the photogrammetry engine comparison and the scanner-registration tooling survey — so those sections are knowledge-based (marked ⚠K) pending a targeted follow-up.

## Recommended stack

| Stage | Tool | Why |
|---|---|---|
| Photogrammetry | **OpenDroneMap (ODM via Docker, NodeODM API)** | Purpose-built for drone mapping: GCP support, georeferenced outputs, accuracy stats, fully headless REST API |
| Research-grade alternative | **COLMAP + OpenMVS** | Finer SfM/MVS control; COLMAP poses also feed Gaussian splat training |
| PPK | **RTKLIB (rtklibexplorer fork)** | Maintained fork tuned for low-cost receivers |
| Geotag injection | **ExifTool** | Rewrite EXIF GPS from PPK solutions before photogrammetry |
| Registration & QC | **CloudCompare (+ M3C2 plugin)** + **Open3D**; **ASP pc_align** as alternative | Alignment of scanner data into the georeferenced frame; distance-based QC |
| Point cloud plumbing | **PDAL** (2.10.x) | JSON pipelines: CRS reprojection, filtering, LAS/LAZ/COPC — ideal for node-graph automation |

## 1. Photogrammetry engines (⚠K — comparison survey lost, knowledge-based)

- **ODM / WebODM / NodeODM** — the direct open replacement for Drone2Map: orthomosaic, DSM/DTM, textured mesh, georeferenced point cloud, processing report. NodeODM exposes everything over REST; Docker on Windows 11/WSL2. Verified accuracy expectations from official docs: without GCPs, relative accuracy 1–3× GSD but absolute horizontal error 2–6 m; with GCPs ~2.5× GSD horizontal / 4× vertical ([docs.opendronemap.org/map-accuracy](https://docs.opendronemap.org/map-accuracy/)). ODM 3.5.6 (July 2025) exports OGC 3D Tiles directly ([docs](https://docs.opendronemap.org/arguments/3d-tiles/)).
- **COLMAP + OpenMVS** — best-in-class sparse SfM + dense reconstruction; no native GCP workflow (similarity transform bolted on). Keep for splat training poses and fine calibration control. ⚠K
- **Meshroom (AliceVision)**, **MicMac** — secondary options; MicMac is the accuracy heavyweight with a brutal CLI. ⚠K

## 2. RTK / PPK and ground control

### RTKLIB — verified state of the project
- Original RTKLIB (tomojitakasu) last released v2.4.2 in 2013; 2.4.2+ is BSD-2-clause with two extra clauses ([github](https://github.com/tomojitakasu/RTKLIB)).
- The **rtklibexplorer "demo5" branch was retired July 26, 2025 — all future activity is on that repo's main branch** (RTKLIB-EX 2.5.1, June 2024, ships rnx2rtkp, rtkpost, convbin, str2str) ([releases](https://github.com/rtklibexplorer/RTKLIB/releases)). Latest Windows binaries: b34 series at [rtkexplorer.com](https://rtkexplorer.com/downloads/rtklib-code/). The fork targets low-cost single/dual-frequency receivers, especially u-blox — exactly our hardware class.

### PPK workflow (verified against rtklibexplorer's own writeup)
- Flow: RTKCONV converts raw logs (.ubx) → RINEX; RTKPOST post-processes with forward/backward/**combined** filter — combined runs the Kalman filter both directions, "two chances to find a fix" plus false-fix detection ([rtklibexplorer blog](https://rtklibexplorer.wordpress.com/2017/08/21/ppk-vs-rtk-a-look-at-rtklib-for-post-processing-solutions/)).
- PPK beats RTK for remote/obstructed sites — no radio link to drop. Centimeter-level achievable with short baselines and good geometry.
- **Reality check for our drone (DJI Mini 3):** DJI's consumer line does not log raw GNSS observations — PPK requires enterprise-class hardware (e.g. Phantom 4 RTK) or an added GNSS logger ([hiredronepilot.uk](https://hiredronepilot.uk/blog/what-is-ppk-post-processing-kinematic-for-drones/)). Standard consumer GNSS ≈ 2 m before correction. **So our accuracy comes from GCPs, not PPK.** The RTKLIB/ExifTool material above stays documented for a future logger or different aircraft; it's not on the Phase 1 path.

### Geotag injection with ExifTool (verified from official docs)
- `exiftool -geotag=track.log <images>` — supports 15+ track formats plus CSV (GPSDateTime, GPSLatitude, GPSLongitude columns); `-geosync` handles camera↔GPS clock offset; interpolation window defaults 1800 s ([exiftool geotag docs](https://exiftool.sourceforge.net/geotag.html)).
- Direct per-image write: `exiftool -GPSLatitude=... -GPSLongitude=... -GPSLatitudeRef=N -GPSLongitudeRef=E img.jpg`.

### ODM GCP file (verified from official docs)
- `gcp_list.txt` header = a PROJ string (e.g. `+proj=utm +zone=10 +ellps=WGS84 +datum=WGS84 +units=m +no_defs`), an EPSG code, or `WGS84 UTM` (auto zone). Rows: `geo_x geo_y geo_z im_x im_y image_name [gcp_name]`. Each GCP should appear in ≥3 images; ~15 data rows minimum (5 points × 3 images); avoid NaN elevations ([docs.opendronemap.org/gcp](https://docs.opendronemap.org/gcp/)). WebODM has a GCP tagging UI.
- **Checkpoints — verified: ODM has no native mechanism.** There is no syntax or flag to mark an individual GCP as validation-only; the feature request is [ODM issue #1302](https://github.com/OpenDroneMap/ODM/issues/1302), still open (community confirmed "no support yet," Sept 2025). The only built-in workaround is all-or-nothing: with `--force-gps`, georeferencing comes from RTK EXIF and *all* supplied GCPs act as checkpoints reported in the quality report ([community thread](https://community.opendronemap.org/t/using-the-new-checkpoint-feature-with-odd-z-axis-results/25519)). **Our plan:** constrain with GCPs in the main run, then compute checkpoint residuals ourselves by comparing the surveyed checkpoint coordinates against the output cloud/orthophoto — a small script that belongs in our accuracy-report stage anyway.

### GCP surveying practice
- Targets ≥5× GSD (durable targets 15–25× GSD); common size ~30–60 cm checkerboard/iron-cross ([skyebrowse guide](https://www.skyebrowse.com/news/posts/ground-control-points-guide)). RTK rover ±1–2 cm horizontal; GCP-constrained photogrammetry 2.5–5 cm typical. Distribute perimeter + center; hold 2–3 points out as checkpoints — they grade the run instead of constraining it.
- Occupation: ~30 s of fixed-solution averaging per point is fine on short baselines (the 30–40 min figures in survey guides are for static GNSS, not RTK-fixed rovers).
- Heights: RTK gives ellipsoidal. If orthometric is ever needed: h = H + N; EGM96 = EPSG:5773, EGM2008 = EPSG:3855; GDAL/PROJ converts via `+geoidgrids=egm96_15.gtx`/`egm08_25.gtx` ([worked example](https://spatialthoughts.com/2019/10/26/convert-between-orthometric-and-ellipsoidal-elevations-using-gdal/)). For ML/sim use, staying ellipsoidal + local ENU is simpler and self-consistent.
- Base station absolute position defines absolute accuracy: long-average or PPP-correct it once ⚠, pin the value in version control, never move it.
- Our base already broadcasts RTCM over NTRIP; RTKLIB's `str2str` can relay/convert streams (serial/TCP/NTRIP in/out, RTCM3 message filtering) if we need to bridge anything ([reference](https://community.gpswebshop.com/2023/11/26/setting-up-a-free-ntrip-server-with-rtklibs-strsvr/)).

## 3. Einstar scans → georeferenced frame (⚠K — tooling survey lost, knowledge-based)

Strategy unchanged: export PLY/OBJ → coarse align (manual point pairs, or Open3D FPFH+RANSAC) → fine ICP (point-to-plane, **scale locked** — the scanner's metric scale outranks photogrammetry's; a scale disagreement is a finding, not something to absorb) → QC via cloud-to-cloud distances.

Two verified additions from the research pass:
- **CloudCompare's M3C2 plugin** is the right QC tool, not plain C2C: cylinder-based *signed* distances along locally-estimated normals, with uncertainty estimation and statistical significance testing; the M3C2-PM variant consumes photogrammetric precision maps ([CloudCompare wiki](https://www.cloudcompare.org/doc/wiki/index.php/M3C2_(plugin))).
- **NASA Ames Stereo Pipeline `pc_align`** is a strong scriptable registration alternative: ICP point-to-plane default plus point-to-point, Nuth & Kääb, and Fast Global Registration; feature-based initialization for large offsets; reads LAS/LAZ/COPC/DEM/CSV ([docs](https://stereopipeline.readthedocs.io/en/latest/tools/pc_align.html)).
- **CloudCompare CLI — verified fully headless-capable** ([command line mode wiki](https://www.cloudcompare.org/doc/wiki/index.php?title=Command_line_mode)): `-SILENT` for headless, `-ICP` (with `-ADJUST_SCALE` — we keep it OFF to lock scanner scale — `-OVERLAP`, iteration/sampling controls), `-C2C_DIST`, and **`-M3C2 <params_file>`** (create the params file once in the GUI, reuse forever). The whole registration+QC stage can be CloudCompare CLI if Open3D scripting ever disappoints.
- ⚠K still to survey: Open3D vs small_gicp performance, whether TEASER++ is ever needed.

## 4. Point cloud plumbing & QC

- **PDAL 2.10.2** (June 2024 — a search snippet claiming a 2026 release was corrected against GitHub) ([releases](https://github.com/PDAL/PDAL/releases)). Filters of interest: `reprojection` (supports compound CRS like `EPSG:4326+3855` and geoidgrids), `smrf` (ground classification, Pingel 2013), `outlier`, `csf` (cloth simulation ground extraction), `crop`, `hexbin` (density/boundary); COPC read/write. Most per-filter details came from snippets (pdal.io blocked the fetcher) — ⚠ spot-check exact stage options at build time. Python bindings: `conda install -c conda-forge python-pdal`.
- Formats: **COPC** (LAZ 1.4 + embedded octree, HTTP range-readable) as archive/streaming format; LASzip is Apache-2.0, 7–20% of original size; `untwine` builds COPC/EPT (GPLv3 ⚠ note if we ship it); QGIS 3.32+ renders COPC natively; Potree for web viewing.
- **Per-run accuracy report** (pipeline must emit automatically): GCP residuals + checkpoint RMSE, PPK fix rate if used, ICP registration RMSE, M3C2 distance stats, density map. ASPRS Positional Accuracy Standards Ed. 2 (2023/2024) now uses RMSE as the single accuracy measure — report to that convention ⚠ (official PDF unread). No off-the-shelf open "accuracy report generator" exists — confirmed gap, we build our own (good; it's a natural node).
- **Open3D 0.19** for Python-side mesh/cloud ops (downsampling, outlier removal, RANSAC planes, headless).
- Full salvaged claim list (55 items with per-claim confidence): [appendix-point-cloud-claims.md](appendix-point-cloud-claims.md).

## 5. Prior art — combined UAV + close-range + GNSS

- **Oniga et al. 2024** (ISPRS Archives XLVIII-2/W4): Sony ZV1 + Emlid Reach RS2/M2, direct georeferencing with lever-arm estimation, no GCPs, cm-level, validated against mobile laser scanning ([paper](https://isprs-archives.copernicus.org/articles/XLVIII-2-W4-2024/333/2024/)) — the one fully-verified source.
- UAV + handheld structured-light fusion for concrete inspection: UAV for global mm-resolution coverage, structured light for µm hotspots, coarse-to-fine feature registration; notes photogrammetry scale drift vs structured-light metric stability — exactly our Einstar logic ([abstract](https://www.researchgate.net/publication/381877445)) ⚠.
- TLS + UAV heritage-church fusion: cloud agreement within 1.7 cm, ~40% coverage improvement; TLS blind on roofs, UAV weak on facade detail; common targets needed ⚠.
- Notable gaps found: no published Einstar+UAV academic study, no ODM+TLS workflow write-ups, no per-step error-budget templates. Publishing ours would be a genuine contribution.

## Open questions

- ~~Does our drone log raw GNSS?~~ Answered: the drone is a DJI Mini 3 → no raw logging, GCP-only accuracy. (A strap-on GNSS logger remains a future option.)
- Base station: PPP/long-average corrected? Value pinned where?
- Einstar export: PLY with vertex colors confirmed?
