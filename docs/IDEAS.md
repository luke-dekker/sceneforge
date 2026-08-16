# Ideas backlog

Running capture of directions worth pursuing — promoted to ROADMAP.md when
they become committed work. Date-stamped on entry.

## Meshroom plugin: sceneforge-geo node pack (2026-08-13)
Thin Meshroom 2025.1 nodes (mrHelloWorld pattern) over the existing CLI
scripts — logic stays GUI-free per the plugin/GUI separation rule:
- **GcpConvert** — wraps `gcp_to_micmac.py` (ODM GCP list → MicMac XML + holdout)
- **UtmExport** — wraps `rtl_to_utm_geotiff.py` (RTL products → UTM GeoTIFF)
- **HeightfieldScene** — wraps `heightfield_glb.py` + `prep_godot.py` (DSM+ortho → walkable GLB)
2023.3 stays quarantined as a MicMacRoom-compat box until COCORICO ports it.

## Capture doctrine: add low-oblique orbits (2026-08-13)
Nadir-only grids are weak exactly where the farm scene failed: vertical
surfaces, tree sides, and self-calibration (flat scene + single altitude =
focal/Z degeneracy — see the copr dome). One 20–45° off-nadir orbit added to
each flight gives convergent rays → solvable focal, sharper DSM edges, less
ortho smear at buildings, real side-of-canopy geometry. Cost: ~5 min of
battery per site. Adopt as standard for all future class flights.

## Canopy correlation failure → melty/plateau trees (2026-08-13)
Wind moves foliage between exposures; stereo correlation dies on canopy, the
mask blanks it, fills go flat (the "uniform 11m columns" in the farm walk).
Refinement ladder: (1) erode mask + floor-fill outliers, (2) MicMac Pims2Mnt
per-pair fusion instead of single Malt, (3) full dense mesh (C3DC → TiPunch →
Tequila), (4) obliques per above, (5) learned MVS (mrDepthEstimation /
mrRomatch) which degrades gracefully on vegetation.

## PPK georeferencing without GCPs (2026-08-12)
M3M writes _PPKOBS.obs/_PPKRAW.bin/_Timestamp.MRK. Post-process against the
home RTK base (RTKLIB) → cm-grade camera centers → Campari EmGPS at 0.05m.
Would demo survey-grade output with zero GCPs. Needs: RTKLIB run, MRK
timestamp interpolation, lever-arm handling.

## Virtual production: Meshroom + Godot for film (2026-08-13)
Meshroom's VFX heritage is real (MPC uses it; camera-tracking pipelines are
stock templates). Pipeline sketch: track live footage in Meshroom → export
solved camera → Godot as the 3D stage (photogrammetry sets from our own
flights) → Godot Movie Maker mode for deterministic offline renders →
composite CG over plates in Blender or Natron. Meshroom is NOT an editor —
it's the tracker/processor; editing lives in Kdenlive or Blender VSE,
node compositing in Natron. All-open stack end to end.

## Meshroom as a footage-processing graph (2026-08-13)
Not an NLE, but per-shot batch passes fit its DAG model well: image-sequence
in → segmentation/matting (mrSegmentation), monocular depth (mrDepthEstimation),
stabilization, LUTs → sequence out. Could carry our own trained models as
nodes (node-tool runnable export → Meshroom node wrapper).

## Spatial audio / ambisonics (2026-08-13)
Goal: scenes that sound like the place, not just look like it. Capture:
fieldrec + DIY first-order tetrahedral mic (B-format). Playback: Godot has
positional 3D audio but no native ambisonics; options are a GDExtension
around an HRTF/ambisonic decoder (Resonance Audio is Apache-licensed) or
baking binaural per-camera-path for film work. Ardour (GPL) covers the DAW
side. Parked until a project needs it — ties into the embodied-AI multimodal
tensor vision (audio in scene = training signal, not just polish).

## Godot scene polish (2026-08-13)
- Walker spawn robustness: derive spawn height from mesh raycast at origin,
  not scene metadata (falling-through bug class).
- True-3D trees eventually via dense mesh; heightfield stays the fast path.
- Carry full CRS + vertical datum in scene.json (done: utm_offset + z_offset).
