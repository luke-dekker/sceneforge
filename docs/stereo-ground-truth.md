# Stereo depth ground truth from reconstructed scenes

Goal: use our accurate reconstructions as ground truth to train supervised stereo depth networks that deploy on real stereo RGB cameras.

**Provenance:** merged from a web-research pass (August 2026) and working knowledge. URL-backed claims were read from source by a research agent (single read). ⚠ marks open items. The camera-hardware-specs angle was partially lost; what survived is in §7.

## Recommended approach

1. **Fine-tune, don't train from scratch.** Every modern stereo net pretrains on SceneFlow-class synthetic data; our data slots in as fine-tuning material — thousands of pairs, not millions. CREStereo's authors observed performance plateauing around ~10k samples ([arXiv 2504.16930](https://arxiv.org/html/2504.16930)).
2. **Render from meshes for labels; consider splats for photorealism** — with depth always taken from geometry, never from vanilla splat renders (§4).
3. **Match the real rig exactly** (intrinsics, baseline, resolution) and degrade the renders; baseline diversity is a first-order generalization lever (StereoCarla ablations, [arXiv 2509.12683](https://arxiv.org/abs/2509.12683) ⚠abstract).
4. Strongest tooling candidates: **InfinigenStereo** (purpose-built stereo data generator) and **BlenderProc2** (our-scenes renderer) — see §3.

## 1. How existing datasets make GT (verified highlights)

| Dataset | GT method | Takeaway |
|---|---|---|
| Middlebury 2014 | Structured light, ~0.2 px disparity accuracy incl. half-occlusions | GT precision and occlusion masks are first-class ⚠ |
| ETH3D | Faro laser scanner + registered real images | Our exact hardware story — accurate scan = GT for real photos |
| KITTI 2012/2015 | Accumulated LiDAR (sparse) + CAD fitting for cars ⚠ | Sparse GT alone trains poorly |
| DrivingStereo | LiDAR multi-frame fusion; disparity as uint16 PNG ([site](https://drivingstereo-dataset.github.io/)) | Format precedent |
| SceneFlow/FlyingThings3D | Modified Blender, ~39k pairs | Unrealistic-but-dense works for pretraining; known disparity-distribution bias ⚠ |
| TartanAir v1/v2 | AirSim/UE; v2: 74 scenes, panoramic multimodal ⚠ | Scene diversity transfers |
| CREStereo | Blender, 200k frames, hard materials/lighting ⚠ | Difficulty > realism; plateaus ~10k samples |
| **FoundationStereo FSD** | ~1M pairs, Omniverse RTX path tracing, randomized baseline/focal/lighting, **automatic self-curation** (rejects samples where BP-2 > 60%) ([arXiv 2501.09898](https://arxiv.org/html/2501.09898v2), [repo](https://github.com/NVlabs/FoundationStereo)) | Self-curation is worth copying; still weak on transparency |
| Dynamic Replica | 145k stereo frames, animated agents in scanned environments ⚠ | Scanned-env precedent |
| UE5-Forest | 5,520 pairs matched to a ZED Mini rig, PFM disparity + validity masks ⚠ | Small rig-matched sets are a recognized pattern — ours can look like this |

Consistent lessons: dense GT with occlusion handling; non-Lambertian surfaces are where everything fails (mask them or deliberately render them); rig-matched fine-tuning sets are small.

## 2. Rendering stereo + dense GT from our meshes

- **InfinigenStereo** (Princeton, [repo](https://github.com/princeton-vl/InfinigenStereo), [arXiv 2504.16930](https://arxiv.org/abs/2504.16930)) — a purpose-built procedural stereo data generator on Infinigen/Cycles: outputs disparity, occlusion masks, sky masks, stereo calibration. Their ablation: dense floating-object clutter (200 objects/frame) cut Middlebury error from 12.52% → 6.60%, and models trained *only* on their data beat prior zero-shot checkpoints. Unix-first ⚠ (WSL2 for us). Procedural scenes, not our scans — so it's the *pretraining/augmentation* arm, while our scenes are the *rig- and domain-matched* arm.
- **BlenderProc2** ([repo](https://github.com/DLR-RM/BlenderProc)) — renders our actual scenes. **Native stereo verified**: `set_stereo_parameters()` with interocular distance, convergence distance, OFF-AXIS/PARALLEL/TOE modes ([API docs](https://dlr-rm.github.io/BlenderProc/blenderproc.api.camera.html)). Loads OBJ/PLY/GLTF/BLEND; outputs RGB/depth/normals/segmentation; official Docker image with GPU support. One trap flagged in research: BlenderProc also ships an *SGM stereo-matching* post-processor — that is simulated-imperfect depth, not GT; the Z-pass is the exact ground truth.
- **Habitat-Sim** — ⚠ **status change vs. our first draft: the repo states it is no longer under official active development by Meta** (community activity continues; Habitat-Lab tagged a release May 2026) ([repo](https://github.com/facebookresearch/habitat-sim)). Stereo = two `CameraSensorSpec`s at offset positions ([docs](https://aihabitat.org/docs/habitat-sim/stereo-agent.html)); no native Windows. Demoted from "volume renderer" to "optional, if we need 1000+ FPS rasterized volume and accept the maintenance risk."
- **Open3D `RaycastingScene`** — exact per-ray geometric depth (no z-buffer nonlinearity), headless Python ([docs](https://www.open3d.org/docs/release/python_api/open3d.t.geometry.RaycastingScene.html)). The cheapest correct way to bake disparity GT against our meshes — pairs well with *any* RGB renderer.
- **Mitsuba 3** — verified Windows support, CUDA/OptiX backends, active EPFL maintenance ([repo](https://github.com/mitsuba-renderer/mitsuba3)); for physically-correct special cases. **pyrender** — headless glTF renderer but effectively unmaintained since ~2021 ([repo](https://github.com/mmatl/pyrender)). **Kubric** — active, but no stereo support documented ([repo](https://github.com/google-research/kubric)). **AI2-THOR** — no stereo, no Windows; skip.

Disparity math: `d = f·B / Z` at the rig's calibrated focal length and baseline; export **PFM + SceneFlow folder layout** (what RAFT-Stereo-class training code consumes, §5).

## 3. Gaussian splats as a GT source

- **gsplat** (nerfstudio-project) is the engine of choice: depth render modes (RGB+D/ED), LiDAR rasterization, multiple camera models, 4× less training memory than reference 3DGS, active ([docs](https://docs.gsplat.studio/main/), [repo](https://github.com/nerfstudio-project/gsplat)).
- **Vanilla 3DGS depth is not GT** — alpha-blended expected depth ≠ surface, floaters, bad edges (verified via [RaDe-GS paper](https://arxiv.org/abs/2406.01467) and survey lit). Geometry-accurate variants exist and are quantified on DTU (Chamfer): 2DGS 0.80 mm, Unbiased 2DGS 0.63 mm, RaDe-GS ≈ neural-SDF-level at real-time speed. If splat geometry is ever needed, use those — but our mesh/scan geometry is still better.
- **The validated production pattern is GS2Mesh** (ECCV 2024, [arXiv 2404.01810](https://arxiv.org/abs/2404.01810)): render stereo-aligned pairs from the splat → run a pretrained stereo matcher → fused depth → mesh. And **NeRF-Supervised Deep Stereo** (CVPR 2023, [repo](https://github.com/fabiotosi92/NeRF-Supervised-Deep-Stereo)) proved the whole concept end-to-end: handheld capture → radiance field → stereo triplets + disparity labels at *arbitrary baselines* → trained stereo nets. Our version upgrades their GT with survey-grade geometry: **splat-rendered RGB + mesh/scan-raycast depth in the same registered frame.**
- Keep synthetic camera poses near the capture trajectory; off-trajectory splat artifacts are real.

## 4. Sim-to-real

- **Architectures** (all verified active): **RAFT-Stereo** ([repo](https://github.com/princeton-vl/RAFT-Stereo)) — trained on SceneFlow alone it generalizes zero-shot; loaders expect SceneFlow PFM / KITTI 16-bit PNG / Middlebury+ETH3D PFM. **IGEV / IGEV++** (TPAMI 2025, bfloat16 training, [repo](https://github.com/gangweix/IGEV)). **StereoAnywhere** (CVPR 2025, [repo](https://github.com/bartn8/stereoanywhere)) — fuses Depth Anything V2 monocular priors for textureless/non-Lambertian regions, directly relevant to our failure modes. **FoundationStereo** is the zero-shot baseline to beat; ⚠ license/training-code status unresolved — check before building on it.
- **Degradation modeling**: physics-grounded sensor simulation beats naive noise injection — verified line of work: [active-stereo sensor sim](https://angli66.github.io/active-sensor-sim/), [simsense](https://github.com/angli66/simsense) (GPU depth-sensor simulator), DREDS (ECCV 2022, [paper](https://arxiv.org/pdf/2208.03792)), RaSim ([paper](https://arxiv.org/pdf/2404.03962)). RealSense D435 noise decomposes into axial + shadow + structural components, material/illumination-dependent.
- Mixed-dataset fine-tuning for robustness is standard (RVC 2022 winner used 7 datasets, [paper](https://arxiv.org/pdf/2210.12785)).
- Evaluation: hold out real stereo captures of a scanned scene; metrics EPE + bad-2.0/bad-1.0.

## 5. Real-capture GT (ETH3D-style) — more tractable than we assumed

**The entire ETH3D GT pipeline is open source (BSD)** with named tools for every step: ICPScanAligner (scan registration), ImageRegistrator (pose refinement), SplatCreator/GroundTruthCreator (occlusion-aware GT projection) — the workflow is SfM init → scale estimation → point-to-plane ICP → surface reconstruction for occlusion handling → joint pose/intrinsics optimization ([repo](https://github.com/ETH3D/dataset-pipeline)). We don't have to invent the mini-ETH3D test set; we can run their pipeline with our Einstar/photogrammetry geometry.

Supporting tools, verified: COLMAP registers new images into an existing reconstruction (`mapper --input_path`, PnP against existing points); **hloc** ([repo](https://github.com/cvg/Hierarchical-Localization)) for learned-feature localization (SuperPoint+LightGlue et al.); COLMAP has no built-in mesh-depth renderer — raycast with Open3D at COLMAP poses. **Booster** (CVPR 2022, [paper](https://arxiv.org/pdf/2206.04671)) documents deep space-time stereo GT for specular/transparent surfaces (paint + projected texture + temporal accumulation) if we ever need hard-material GT.

Position unchanged: renderer first (serves sim too), real-capture GT as the high-value test/fine-tune set second — but the ETH3D pipeline discovery lowers the cost of step two a lot.

## 6. Sequencing (proposed)

1. Calibrate the chosen rig (OpenCV) → 2. Raycast GT vs mesh at rig intrinsics + BlenderProc RGB → first rig-matched fine-tune set → 3. Fine-tune RAFT-Stereo/IGEV; eval vs FoundationStereo zero-shot → 4. Add splat-RGB hybrid + InfinigenStereo augmentation → 5. ETH3D-pipeline real test set.

## 7. Camera hardware (partially verified 2026-08)

- **librealsense is Apache-2.0**, actively maintained; org migrating IntelRealSense → realsenseai post-spinout (old URLs may rot). **D455: 95 mm baseline, global shutter.** ([repo](https://github.com/IntelRealSense/librealsense))
- **Luxonis DepthAI SDK is MIT**; OAK 4 platform announced Jan 2026 ([org](https://github.com/luxonis)).
- **Stereolabs ZED SDK is proprietary** + NVIDIA-GPU-required — out, per project principles ([repo](https://github.com/stereolabs/zed-sdk)).
- Still unverified ⚠: D435 ~50 mm baseline, OAK-D 75 mm baseline, per-model shutter types, IR-projector-off and Y8 raw modes.

## Open questions

- Which rig do we standardize on? (OAK-class global-shutter RGB pair vs RealSense left-IR workarounds.)
- FoundationStereo license (gates whether it's a baseline only or a fine-tune base).
- Operating envelope for the first fine-tune: general outdoor vs the drone-arm's close-range oblique regime.
