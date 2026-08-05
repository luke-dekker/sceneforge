# Scan-to-sim: reconstructed scenes in engines and robotics simulators

Goal: drop our georeferenced reconstructions into open simulators/game engines — concretely, simulate the FPV drone + 5-axis arm in scans of real spaces. Written from working knowledge (early 2026); ⚠ marks claims to verify. Items marked ◆ came from the partial web-research pass (surfaced but not fully verified).

## Recommended stack

**MuJoCo for physics/policy learning, Godot 4 for visualization + teleop front-ends, Gazebo only if/when PX4 SITL enters the picture.** One mesh-prep pipeline (Blender + CoACD, headless Python) feeds all three.

## 1. Engine / simulator comparison

| | Physics for drone+arm | Mesh ingestion | Sensors (RGB/depth/IMU) | Python/RL | License |
|---|---|---|---|---|---|
| **MuJoCo** | Excellent articulated dynamics; quad models well-trodden | OBJ/STL into MJCF; textures OK; heavy meshes need decimation | Offscreen RGB/depth rendering; fast | First-class (incl. MJX/GPU) | Apache-2.0 |
| **Godot 4** | Game-grade (Jolt); fine for teleop, not for contact-rich learning | glTF native, great | Viewport cameras; roll-your-own sensor realism | Godot RL Agents (⚠ check status) | MIT |
| **Gazebo (gz-sim)** | Good; the PX4 SITL standard | Meshes via SDF; medium friction | Mature sensor suite | ROS2-centric | Apache-2.0 |
| PyBullet | OK, aging | OBJ | Basic | Mature but fading | zlib |
| Genesis | GPU-parallel, promising | ⚠ | ⚠ | Python-native | Apache-2.0 ⚠ verify maturity 2026 |
| Webots / O3DE | Capable but heavier ecosystems | — | — | — | Apache-2.0 |
| Isaac Sim/Lab | Excellent | — | — | — | **Proprietary — out** (per project principles) |

Division of labor: **MuJoCo** is where learned policies train (drone + arm as one MJCF articulation; MJX if we ever want massive parallelism). **Godot** is where Luke's existing experience pays off: scene walkthroughs, teleop UI, demo recording — the human-facing layer. **Genesis** is the one to re-evaluate at Phase 3 kickoff; if it matured, it could collapse the stack.

## 2. Mesh preparation (the unglamorous 80%)

Photogrammetry meshes are huge, non-manifold, and have baked-in lighting. Headless pipeline, all scriptable:

1. **Split** terrain vs objects of interest (Blender Python; or keep Einstar-scanned objects as separate assets placed into the terrain).
2. **Decimate / LOD**: Blender decimate modifier scripted, or `meshoptimizer`/`gltfpack` for fast simplification + compressed glTF output.
3. **Texture bake**: re-bake high-res texture onto the decimated mesh (Blender bake, scripted).
4. **Collision geometry**: never simulate against render meshes. **CoACD** (current best convex decomposition, better than V-HACD on organic shapes ⚠ benchmark on our data) for objects; for terrain, a decimated trimesh collider or heightfield (MuJoCo supports hfield — natural fit for drone-over-terrain).
5. **Repair**: watertight fixes where needed (Blender 3D-Print toolbox / `manifold` library).

## 3. Formats, scale, and georeferencing

- **glTF/GLB** as the interchange format for visual meshes (native in Godot, fine everywhere); **MJCF** for MuJoCo scenes; **SDF** only for Gazebo.
- Real-world scale flows through automatically if we never rescale after reconstruction. Keep the georeference by convention: **each scene ships a `scene.json` sidecar** with the CRS, the local-ENU origin (lat/lon/h), and the transform from local frame to engine frame (+ Y-up vs Z-up flip). Engines get small local coordinates; the sidecar preserves the map link.
- Large-area streaming (3D Tiles / Cesium-style): Cesium for Godot exists ◆⚠; irrelevant until scenes exceed single-load size — punt.

## 4. Gaussian splats in engines (2026)

The partial research pass confirmed this space is active ◆:

- Multiple **Godot 3DGS plugins** exist ◆ (names/maturity unverified — first thing to check in Phase 3), plus `bevy_gaussian_splatting` for Rust/Bevy ◆, and a **KHR glTF extension for Gaussian splats in release-candidate stage** ◆ — meaning splats-in-glTF may become a standard pipeline rather than per-engine hacks.
- The hybrid pattern for robot sim: **splat renders for photoreal camera observations + collision meshes from the same reconstruction for physics.** This is exactly our asset situation (splats and survey-grade meshes of the same scenes, already co-registered).

## 5. Drone + manipulator simulation

- **Policy training**: build the quad + 5-axis arm as a single MuJoCo MJCF (free joint base + rotor thrust actuators + arm joints). Aerial manipulation couples base and arm dynamics — that coupling is the whole point of simulating it, and MuJoCo handles it cleanly. `gym-pybullet-drones` is prior art for the drone-env API shape even if we don't use PyBullet.
- **Firmware-in-the-loop**: PX4 SITL + Gazebo is the standard when we care about autopilot behavior; **Betaflight SITL exists** ⚠ (our FPV stack is Betaflight-flavored — check its state) but is less turnkey. Custom worlds from our meshes drop into Gazebo via SDF.
- **Prior art surfaced by the research pass** ◆ (to read properly in Phase 3): **SplatSim** (splat-rendered sim for manipulation policy transfer), **RialTo** (real-to-sim-to-real for robust policies), **FalconGym** (drone flight in photoreal reconstructed scenes), **SOUS VIDE** (splat-based drone learning). The real2sim-for-robot-learning direction is validated and active — we're not inventing the pattern, we're applying it with better survey control than most.

## Open questions

- Godot RL Agents maturity vs plain MuJoCo+Gymnasium for the first learning experiments.
- Genesis: production-ready in 2026 or still demo-grade?
- Betaflight SITL vs PX4 SITL for firmware-realistic drone sim (our hardware is FPV/ELRS-flavored).
- Which Godot 3DGS plugin (if any) is solid enough to build the teleop viewer on.
