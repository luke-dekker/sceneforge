# Scan-to-sim: reconstructed scenes in engines and robotics simulators

Goal: drop georeferenced reconstructions into open simulators/game engines — concretely, simulate the FPV drone + 5-axis arm in scans of real spaces.

**Provenance:** merged from a web-research pass (August 2026) and working knowledge. URL-backed claims were read from source by a research agent (single read). ⚠ marks open items; ⚠K marks knowledge-based sections. The drone+manipulator sim-stack angle (PX4/Betaflight SITL, gym-pybullet-drones, aerial manipulation examples) was lost before completing — §5 is knowledge-based pending follow-up.

## Recommended stack

**MuJoCo for physics/policy learning, Godot 4 for visualization + teleop front-ends** (with eyes open about its robotics gaps, below), **Gazebo only if PX4 SITL enters the picture.** One headless mesh-prep pipeline (Blender + CoACD via obj2mjcf) feeds all three. Watch **Genesis** and **Newton** as potential stack-collapsers.

## 1. Simulators & engines — verified state (Aug 2026)

### Robotics simulators
- **MuJoCo** — v3.11.0 (July 2026), Apache-2.0, actively developed ([changelog](https://mujoco.readthedocs.io/en/stable/changelog.html)). Textured OBJ meshes supported; **glTF/DAE import is a known gap** (open issue [#2672](https://github.com/google-deepmind/mujoco/issues/2672)) — our pipeline keeps an OBJ export path for MuJoCo. **obj2mjcf** ([repo](https://github.com/kevinzakka/obj2mjcf)) automates OBJ → MJCF including CoACD collision decomposition. **MuJoCo Warp** (GPU MuJoCo on NVIDIA Warp, Apache-2.0, [repo](https://github.com/google-deepmind/mujoco_warp)) covers massive parallelism later.
- **Gazebo** — current LTS "Jetty" (Sept 2025 → May 2031); Gazebo Classic EOL'd Jan 2025; `gazebo_ros2_control` archived → `gz_ros2_control` ([releases](https://gazebosim.org/docs/latest/releases/)). Textured glTF/FBX import is a documented pain point (common workaround: convert to COLLADA in Blender). Keep only for the PX4 SITL scenario.
- **PyBullet** — 3.2.7 (Jan 2025) but flagged "inactive," issue tracker closed ⚠ ([pypi](https://pypi.org/project/pybullet/)). Confirmed fading; skip.
- **Webots** — R2025a, Apache-2.0, alive, good ROS2 integration; not differentiated for our use.
- **Genesis** — Apache-2.0; "Genesis World 1.0" announced July 30, 2026 with Nyx photorealistic renderer; active repo, now company-backed ([repo](https://github.com/Genesis-Embodied-AI/genesis-world), [blog](https://www.genesis.ai/blog/the-role-of-simulation-in-scalable-robotics-genesis-world-10-and-the-path-forward)). ⚠ Version/date claims in research conflicted and verification never ran — re-evaluate hands-on at Phase 3; highest upside of anything on this list.
- **Newton** — new physics engine from NVIDIA + Google DeepMind + Disney Research on Warp + OpenUSD, contributed to the Linux Foundation Sept 2025, interoperates with MuJoCo/MJWarp ([announcement](https://developer.nvidia.com/blog/announcing-newton-an-open-source-physics-engine-for-robotics-simulation/)); license unconfirmed ⚠. Watch.
- **Isaac Sim/Lab** — nuance: Isaac Sim's GitHub source is Apache-2.0 and Isaac Lab is BSD-3, **but the Omniverse Kit SDK + assets underneath remain proprietary** ([license page](https://isaac-sim.github.io/IsaacLab/main/source/refs/license.html)). Exclusion stands.
- **ManiSkill3** — Apache-2.0 code but CC BY-NC assets, Linux-first, custom-scene import path unclear ⚠; not primary.

### Godot, honestly assessed
- Jolt physics became built-in in 4.4 (Mar 2025, verified) and reportedly default in 4.6 ⚠; MIT license; `--headless` works.
- **Godot RL Agents** ([releases](https://github.com/edbeeching/godot_rl_agents/releases)) — verified alive: v0.8.2 (Feb 2025), SB3/Sample Factory/RLlib/CleanRL support, imitation learning since v0.8.0, ONNX in-engine inference (plus an ncnn-based asset avoiding Mono).
- Verified gotchas: **no established Godot↔ROS2 bridge exists** (the key negative finding); glTF import has a 256-material-per-mesh limit and a reported 50× file-bloat case ([issue](https://github.com/godotengine/godot/issues/71538)); float physics → not strictly deterministic; full OpenUSD won't fit Godot's small-core model ([proposal discussion](https://github.com/godotengine/godot-proposals/discussions/7436)).
- Verdict unchanged but sharpened: Godot = human-facing layer (walkthroughs, teleop UI, demo recording) and *maybe* light RL via Godot RL Agents; contact-rich policy physics lives in MuJoCo.
- Dark horse noted for the record: **O3DE** has the most serious open-source ROS2 story (official ROS2 Gem: lidar/RGB-D/IMU/GNSS sensors, standardized sim interfaces with Open Robotics; [docs](https://www.docs.o3de.org/docs/user-guide/gems/reference/robotics/ros2sensors/)) — heavier ecosystem, but the fallback if we ever need engine-grade visuals + ROS2 together.

## 2. Mesh preparation (verified toolchain)

All headless-scriptable, all confirmed current:

1. **Split** terrain vs objects (Blender `--background` bpy; PDAL `filters.csf`/`smrf` for ground extraction on the point cloud side).
2. **Decimate/LOD**: Blender decimate; **meshoptimizer/gltfpack** (MIT) for simplification + quantization + KTX2 + LODs, incl. Nanite-style continuous LOD header ([repo](https://github.com/zeux/meshoptimizer)).
3. **Texture bake**: Blender Cycles bake, scripted.
4. **Collision**: **CoACD** — pip `coacd` v1.0.11 (May 2026), MIT, the confirmed successor to V-HACD (which is inactive) ([repo](https://github.com/SarahWeiii/CoACD)); terrain via decimated collider or MuJoCo heightfield.
5. **Repair/watertight**: **manifold3d** v3.5.2 (Apache-2.0, guaranteed-manifold booleans, [pypi](https://pypi.org/project/manifold3d/)); PyMeshLab 2025.7 (GPL-3 ⚠ license note), PyMeshFix (AGPL ⚠), trimesh 5.x (MIT) for checks.
6. **UVs** when rebaking: xatlas-python (MIT).

## 3. Formats, scale, georeferencing

- **glTF 2.0 = meters, Y-up** (spec-verified); glTF 2.1 in ratification adds multi-file composed scenes. MJCF is MKS; SDF supports a `//world/spherical_coordinates` lat/lon origin natively.
- **Float32 precision forces local origins**: ~1 m precision loss near 10⁶ m coordinates (UTM-scale numbers) — always rebase to a site-local origin and keep the georeference in a sidecar. Our convention: each scene ships `scene.json` with CRS, local-ENU origin (lat/lon/h), and engine-frame transform (incl. Y-up/Z-up). OGC **GeoPose 1.0** is the ratified standard for exactly this pose-anchoring exchange ([spec](https://docs.ogc.org/is/21-056r11/21-056r11.html)) — worth matching its form.
- **3D Tiles 1.1** (OGC community standard, direct glTF content) is the streaming format for big scenes; **ODM exports 3D Tiles natively** and Obj2Tiles converts OBJ ([blog](https://cesium.com/blog/2024/10/15/create-3d-tiles-from-opendronemap-in-webodm/)). **Cesium-class support for Godot exists**: "3D Tiles for Godot" by Battle Road, Apache-2.0, Cesium ecosystem grant, released May 2025 ([repo](https://github.com/Battle-Road-Labs/3D-Tiles-For-Godot)) — the whole georeferenced-streaming story works in our preferred engine.
- **KHR_gaussian_splatting**: glTF extension for splats reached release candidate Feb 2026, ratification targeted Q2 2026, adopters incl. CesiumJS/ArcGIS/Scaniverse ([Khronos press](https://www.khronos.org/news/press/gltf-gaussian-splatting-press-release)) — splats-in-glTF is becoming a standard pipeline, not a hack.

## 4. Gaussian splats in engines & robot sims (verified — this space matured fast)

- **Godot has three MIT splat plugins**: **GDGS** (ReconWorldLab, v3.3.0 July 2026 — relighting, shadows, compute+raster backends; most production-ready; [repo](https://github.com/ReconWorldLab/godot-gaussian-splatting)); 2Retr0/GodotGaussianSplatting (compute rasterizer, ~108 FPS on RTX 3060 Ti); klausi3D/godotGS (alpha). Bevy has **bevy_gaussian_splatting** (active, [repo](https://github.com/mosure/bevy_gaussian_splatting)).
- **Splat-rendered robot sims are a real, active category**: **Habitat-GS** (ECCV 2026, zju3dv — 129 GS scenes, NavMesh + nav-task training, MIT, [repo](https://github.com/zju3dv/habitat-gs)); **GSWorld** (ICRA 2026 — closed-loop photoreal manipulation, COLMAP+ArUco real2sim scaling, [repo](https://github.com/luccachiang/GSWorld)); **RoboGSim** (real2sim2real, [arXiv 2411.11839](https://arxiv.org/abs/2411.11839)).
- **Hybrid splat-visuals + mesh-physics** is the emerging standard pattern (SuGaR extracts usable meshes from splats when needed, [repo](https://github.com/Anttwo/SuGaR)) — and it's exactly our asset situation: co-registered splats and survey-grade meshes of the same scenes.

## 5. Drone + manipulator simulation (⚠K — research angle lost, knowledge-based)

- Build the quad + 5-axis arm as one MuJoCo MJCF (free joint base, rotor thrust actuators, arm joints) — base/arm dynamic coupling is the whole point, and MuJoCo handles it cleanly. gym-pybullet-drones is API-shape prior art ⚠K.
- Firmware-in-the-loop: PX4 SITL + Gazebo is the standard; **Betaflight SITL** exists but maturity unverified ⚠ — relevant because our FPV stack is Betaflight/ELRS-flavored.
- Directly relevant verified prior art from the splat/real2sim survey: **SOUS VIDE** (Stanford, [arXiv 2412.16346](https://arxiv.org/html/2412.16346)) — FiGS couples simplified drone dynamics with splat rendering (~130 fps), trains a visuomotor policy on 100k–300k expert MPC pairs, zero-shot transfers with robustness to 30% mass change and wind; **FalconGym 2.0** (98.6% zero-shot gate navigation in 3DGS-reconstructed tracks ⚠). Flying a learned policy through a splat of *our own field site* is a legitimately reachable goal.

## 6. Real2Sim prior art (validated pattern)

- **SplatSim** (ICRA 2025, [arXiv 2409.10161](https://arxiv.org/abs/2409.10161)): splat rendering over a physics sim for RGB manipulation policies — **86.25% zero-shot real-world success**.
- **RialTo** (MIT CSAIL): phone scan → sim + joint annotation → RL fine-tuning, +67% over IL baselines ⚠.
- **URDFormer** ([repo](https://github.com/urdformer/urdformer)) and Real2Code ⚠: articulated-object URDF recovery from images.
- Re³Sim, Vid2Sim, ReBot (IROS 2025, [repo](https://github.com/yuffish/rebot)), GWM (ICCV 2025) — the pipeline pattern is everywhere now.
- Field synthesis (from research pass): 3DGS is the dominant Real2Sim photorealism method; the main unsolved gap is automated **physics-parameter recovery** (mass/friction/contact) — our survey-grade geometry doesn't solve that either; expect manual tuning.

## Open questions

- Genesis hands-on evaluation (could collapse MuJoCo+renderer into one stack).
- Betaflight SITL vs PX4 SITL for firmware-realistic flight.
- Which Godot splat plugin to build the teleop viewer on (start with GDGS).
- Physics-parameter estimation strategy for scanned objects (manual first).
