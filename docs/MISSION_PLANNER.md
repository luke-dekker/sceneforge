# Twin-planned drone missions → buttery cinematic shots

Goal: plan a flight as a **3D spline + keyframes inside the georeferenced
digital twin** — aircraft speed/attitude and independent gimbal aim on separate
tracks — then fly it for real, ending at long, smooth, repeatable cinematic
moves no waypoint mission can produce. Mapping and remote-sensing missions fall
out of the same machinery with a different capture trigger.

The gap this fills: QGC/Mission Planner solve survey grids; Skydio KeyFrame /
UgCS / Litchi do keyframed cine but are proprietary and plan against bare maps.
Nothing open plans keyframed flight inside a photorealistic reconstruction of
the actual site. We have every ingredient: georeferenced twins (scene.json
GeoPose), a Blender bridge with real scale + accurate sun, an RTK base, and an
open flight stack.

**The loop:** first flight is a dumb grid → Meshroom → twin; every later
flight over that site is planned inside the twin (obliques to fix melted spots,
cine passes, sensor sweeps). The map improves the flying, the flying improves
the map. A planned-then-flown mission with the same camera track in both
worlds is the **match cut** — and yields paired real/rendered frames with pose
ground truth (sim2real data) for free.

## Hardware (status 2026-08-15)

- 10" heavy-lift frame: **assembled**. Pixhawk 4 arriving 2026-08-16.
- Flight stack: **ArduPilot Copter** (not Betaflight) — waypoint/spline
  missions, MAVLink gimbal protocol, RTK GPS injection, SITL simulator,
  offboard guided mode. Open source, standard buses.
- RC: ELRS (existing ecosystem). RTK: home base already live (rtk-base:2101,
  RTCM3); drone gets an F9P-class rover later for cm-repeatable paths.
- Gimbal: fixed mount first → 3-axis MAVLink-controllable gimbal for the
  independent camera track.

## Trajectory format (the keystone)

One small format, many consumers (Blender animates it, Godot walker plays it,
SITL/drone flies it, renderers preview it). Sketch — refine when implementing:

```json
{
  "scene": "farm-meshroom",            // binds to scene.json georef
  "frame": "engine",                    // engine coords; georef via scene.json
  "samples": [
    { "t": 0.0,
      "aircraft": {"pos": [x, y, z], "yaw_deg": 0, "speed_mps": 4.0},
      "gimbal":   {"target": [x, y, z]} },   // or quaternion, TBD
    ...
  ],
  "capture": {"mode": "video"}          // or {"mode": "photo", "trigger_m": 12}
}
```

Two tracks by design: the aircraft does not need to point where the camera
points. That separation is the whole trick.

## Phases

### Phase 0 — software only (no drone needed, start anytime)
1. **Blender mission rig**: helper that adds a flight-path curve + speed
   keyframes (Follow Path) and a separate keyframed gimbal-target empty
   (Track To). The flythrough camera in `sceneforge_blend.py` is the seed.
2. **`scripts/mission_export.py`**: sample the Blender animation → trajectory
   json → transform through scene.json → **QGC `.plan`** (SPLINE_WAYPOINT,
   DO_CHANGE_SPEED, DO_SET_ROI / gimbal commands, CAM_TRIGG_DIST for mapping).
   Waypoint missions quantize the spline — accepted for this phase.
3. **SITL loop**: fly the exported mission in ArduPilot SITL, log telemetry,
   replay the flown path back into Blender/Godot next to the planned one.
   Whole chain proven with nothing airborne.
4. Shot preview is free: render the mission camera in Eevee with the sun set
   to planned flight time. Preview the video before the props spin.

### Phase 1 — bringup (Pixhawk 4 + 10" frame)
1. ArduPilot Copter flash, frame/ESC/motor config, sensor + RC (ELRS) cal,
   failsafes (RTL on link loss, battery). Bench test props-off.
2. Hover, then AltHold/Loiter, then autotune. Get boringly reliable first.
3. GPS bringup with stock GNSS; add RTK rover + RTCM injection from the home
   base when available. RTK is what makes planned paths *repeatable*.

### Phase 2 — first mapping mission
QGC survey grid over a site → sceneforgePhotogrammetry pipeline → twin.
This is the twin that Phase 3 plans against. Oblique-orbit second pass per the
capture doctrine where the mesh melts.

### Phase 3 — twin-planned waypoint cine
Plan in Blender over the Phase 2 twin → mission_export → fly (RTK) → compare
flown vs planned in the twin. Gimbal aim via DO_SET_ROI at first (aircraft yaw
+ gimbal pitch), full independent aim once the 3-axis gimbal exists.
**First match-cut attempt lives here.** Prereq: real georef on the twin
(GeorefSolve — the template ships a placeholder).

### Phase 4 — buttery (true keyframe playback)
Waypoint missions can't do long smooth ramps. Add a companion computer
(Pi-class) on the drone streaming **offboard guided setpoints** (MAVSDK or
pymavlink, 10–50 Hz) that follow the trajectory json exactly: position +
velocity feed-forward + yaw, gimbal quaternion in lockstep. This is the same
player the Godot walker and Blender use — the drone becomes just another
consumer of the format. Rehearse in SITL first, always.

## Guardrails

- Don't rebuild survey grids — QGC does them. Build only the twin-planned
  cine layer.
- Every mission flies in SITL before it flies in air.
- Clearance check planned paths against the twin mesh (real trees, real
  buildings), with margin for GPS/mesh error — the twin is accurate, not exact.
- Keep formats open + json; keep flight code in ArduPilot's vocabulary, no
  proprietary link protocols.
