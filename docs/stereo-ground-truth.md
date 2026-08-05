# Stereo depth ground truth from reconstructed scenes

Goal: use our accurate reconstructions as ground truth to train supervised stereo depth networks that deploy on real stereo RGB cameras. Written from working knowledge (early 2026); ⚠ marks claims to spot-check before building.

## Recommended approach

**Render synthetic stereo pairs + perfect disparity from the reconstructed meshes (BlenderProc2 / Blender Python), matched to the real rig's intrinsics and baseline, with aggressive photometric degradation — then fine-tune a pretrained stereo network (RAFT-Stereo or IGEV class) rather than training from scratch.** Keep the ETH3D-style "real images + reconstructed GT" approach as a later, second data source — it's more work but kills the domain gap where it matters.

## 1. How the classic datasets make their GT (and what it teaches)

| Dataset | GT method | Lesson |
|---|---|---|
| Middlebury | Structured light, sub-pixel disparity | GT precision matters; occlusion masks are first-class |
| ETH3D | Terrestrial laser scan + registered real images | **Our exact hardware story**: accurate scan = GT for real photos |
| KITTI | Lidar projection (sparse!) | Sparse GT trains poorly alone; density is a feature |
| FlyingThings3D / SceneFlow | Blender renders, perfect dense disparity | Synthetic-at-scale pretraining works even when unrealistic |
| TartanAir | AirSim (UE) rendered environments | Diverse synthetic scenes transfer surprisingly well to real |
| IRS | UE4 indoor renders | Photorealism + correct lighting helps indoor transfer |
| CREStereo | Blender, deliberately hard materials/lighting | Difficulty curriculum > raw realism |

Takeaways: dense GT with correct occlusion handling; non-lambertian surfaces (glass, metal, water) are where GT and networks both fail — either mask them or deliberately include rendered versions; almost every modern stereo net is pretrained on SceneFlow then fine-tuned, so our data slots in as **fine-tuning data**, which needs thousands—not millions—of pairs.

## 2. Rendering stereo pairs + dense GT from our meshes

- **BlenderProc2** — the default. Procedural Python API over Blender/Cycles: load mesh, script camera trajectories, randomize lighting, and it writes RGB + depth + normals + segmentation to HDF5/COCO. Stereo: model the rig as two cameras with a fixed baseline transform (BlenderProc has stereo/`interocular` support ⚠ verify current API; if absent, two-camera rendering is trivial to script). Disparity from depth: `d = f·B / Z` with our rig's focal length and baseline.
- **Raw Blender Python + Cycles** — same engine, no framework; Blender's native stereoscopy mode renders L/R in one pass. Fallback/complement to BlenderProc.
- **Habitat-Sim** — rasterized, hundreds—thousands of FPS, built for embodied AI; ingests glTF/PLY scenes. Much faster than Cycles but flat-shaded realism; good for *volume*, Cycles for *fidelity*. Meshes must be reasonably clean ⚠ check current photogrammetry-scene import guidance (it ships loaders for scan datasets like MP3D/HM3D, which are photogrammetry-like).
- **Mitsuba 3 / pyrender** — Mitsuba for physically-correct special cases; pyrender/trimeshraycasting for cheap depth-only GT without photorealism. Neither is the backbone.

Practical recipe: **Cycles (via BlenderProc) for a high-fidelity core set + Habitat for a large fast set**; ablate what mix actually helps.

## 3. Gaussian splats as a GT source

Splats trained from the same drone/ground imagery (gsplat / Nerfstudio splatfacto; COLMAP poses we already have) render *photoreal* novel views — better image realism than textured meshes, which attacks the domain gap from the appearance side. Two caveats:

1. **Splat depth ≠ ground truth.** Rendered depth from 3DGS has floaters and soft geometry. The strong hybrid: **render RGB from splats, take depth/disparity from the mesh/scan geometry** aligned in the same frame — photoreal images with survey-grade labels. Our sub-mm Einstar geometry makes this hybrid unusually credible.
2. View-dependent artifacts appear off the training trajectory; keep synthetic camera poses near the capture distribution or filter by artifact heuristics.

The aborted research pass surfaced active 2025-26 work using splats for robot training data (SplatSim et al. — see scan-to-sim doc), so the approach is live, not speculative. ⚠ worth a targeted look for stereo-specific splat-GT papers when we start Phase 2.

## 4. Sim-to-real for stereo

- **Match the real rig exactly**: render at its resolution, intrinsics, and baseline (after calibrating the real rig with OpenCV / Kalibr). Stereo nets are less transferable across baselines than across scene content.
- **Degrade the renders**: sensor noise, motion blur, defocus, exposure/white-balance jitter, JPEG artifacts, slight rectification error. Clean renders transfer worse than dirtied ones — consistent finding across the synthetic-stereo literature.
- **Architectures**: RAFT-Stereo and IGEV-Stereo are the open, well-maintained fine-tuning workhorses; FoundationStereo (NVIDIA, 2025) is the strong zero-shot baseline to beat ⚠ check its license before building on it. Training code for RAFT/IGEV expects SceneFlow-style folder layouts with PFM disparity files — cheap for us to emit, so **PFM + SceneFlow layout is our export format**.
- **Evaluation**: hold out real captured stereo pairs of a scanned scene; project the registered scan into them for a small *real* test set (mini-ETH3D). Metrics: EPE + bad-2.0/bad-1.0.
- Hardware note: the RealSense's stereo pair is IR (with optional projector); for RGB stereo either use its left IR + RGB carefully or build a cheap dual-RGB rig (two global-shutter OAK/ArduCam modules on a bar) — decide when Phase 2 starts.

## 5. The real-capture alternative (ETH3D-style)

Instead of rendering: capture real stereo photos in the scanned scene, localize them against the reconstruction (COLMAP re-localization / hloc), and project the scan geometry into each view for GT. Pros: zero appearance gap. Cons: pose accuracy becomes the GT accuracy bottleneck; occlusion/visibility reasoning needed; more field time. **Position: build the renderer first (it also serves sim), add this as the high-value test/fine-tune set later.**

## Open questions

- Which real stereo camera do we standardize on? (Drives intrinsics/baseline for all rendering.)
- Fine-tune target: general outdoor stereo, or the drone-arm's operating envelope (close-range, downward/oblique)? Scoping this shrinks the needed dataset a lot.
