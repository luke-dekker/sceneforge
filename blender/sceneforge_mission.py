"""Mission rig + trajectory sampler for sceneforge scenes (runs INSIDE Blender).

Rig convention (author by hand in the GUI or generate with --demo):
  - object "aircraft":      animated empty/object; its world position per frame
                            is the flight path (any animation method works —
                            Follow Path on a curve, direct keyframes, ...)
  - object "gimbal_target": animated empty; where the camera looks each frame

Sampling reads world positions per frame, so constraints, curves, and parents
all resolve. Coordinates are Blender's = local ENU meters (X east, Y north,
Z up, ground near 0); the georef lives in the scene's scene.json.

Usage (demo mission over a scene + export):
  blender --background --python sceneforge_mission.py -- \
      --scene-json <scene.json> --demo --out <traj.json> [--hz 5]
Usage (export a hand-authored rig from a .blend):
  blender --background <mission.blend> --python sceneforge_mission.py -- \
      --out <traj.json> [--hz 5]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-json", default=None,
                    help="import this scene first (fresh file + demo rig)")
    ap.add_argument("--demo", action="store_true",
                    help="generate a demo mission rig sized to the scene")
    ap.add_argument("--out", required=True, help="trajectory json path")
    ap.add_argument("--hz", type=float, default=5.0, help="sample rate")
    ap.add_argument("--seconds", type=float, default=60.0,
                    help="demo mission duration")
    ap.add_argument("--save-blend", default=None,
                    help="also save the rigged .blend here")
    return ap.parse_args(argv)


def scene_bounds():
    lo = Vector((1e18, 1e18, 1e18))
    hi = -lo
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def build_demo_rig(seconds, fps):
    """S-shaped survey-to-cine pass sized to the scene: enter high from the SW,
    sweep across descending while the gimbal tracks the scene center, exit NE
    climbing. Positions are keyframed directly; a hand-authored rig would more
    likely use a curve + Follow Path — the sampler treats both the same."""
    lo, hi = scene_bounds()
    center = (lo + hi) / 2
    ex, ey = hi.x - lo.x, hi.y - lo.y
    frames = int(seconds * fps)
    scn = bpy.context.scene
    scn.frame_start, scn.frame_end = 1, frames
    scn.render.fps = int(fps)

    aircraft = bpy.data.objects.new("aircraft", None)
    gimbal = bpy.data.objects.new("gimbal_target", None)
    for o in (aircraft, gimbal):
        scn.collection.objects.link(o)

    for f in range(1, frames + 1, 4):
        t = (f - 1) / (frames - 1)
        # S-curve across the long axis, altitude 40 -> 22 -> 45 m
        y = center.y + 0.35 * ey * math.sin(2 * math.pi * t)
        z = 40 - 18 * math.sin(math.pi * t) + 5 * t
        aircraft.location = (lo.x - 30 + (ex + 60) * t, y, z)
        aircraft.keyframe_insert("location", frame=f)
        # Gimbal: track center for the middle, lead ahead on entry/exit
        lead = Vector((aircraft.location[0] + 40, center.y, 0))
        w = min(1.0, 3.0 * t * (1 - t) * 2)  # 0 at ends, 1 mid-pass
        tgt = Vector(center) * w + lead * (1 - w)
        gimbal.location = (tgt.x, tgt.y, lo.z + 2)
        gimbal.keyframe_insert("location", frame=f)
    return aircraft, gimbal


def sample(out_path, hz, scene_name):
    scn = bpy.context.scene
    aircraft = bpy.data.objects.get("aircraft")
    gimbal = bpy.data.objects.get("gimbal_target")
    if aircraft is None:
        raise RuntimeError('no object named "aircraft" in this file')
    fps = scn.render.fps
    step = max(1, round(fps / hz))
    samples = []
    prev = None
    for f in range(scn.frame_start, scn.frame_end + 1, step):
        scn.frame_set(f)
        t = (f - scn.frame_start) / fps
        pos = list(aircraft.matrix_world.translation)
        entry = {"t": round(t, 3),
                 "aircraft": {"pos": [round(v, 3) for v in pos]}}
        if prev is not None:
            dt = t - prev["t"]
            d = Vector(pos) - Vector(prev["aircraft"]["pos"])
            if dt > 0:
                entry["aircraft"]["speed_mps"] = round(d.length / dt, 2)
                if d.xy.length > 0.1:
                    # ENU yaw: 0 = north, clockwise positive (compass)
                    entry["aircraft"]["yaw_deg"] = round(
                        math.degrees(math.atan2(d.x, d.y)) % 360, 1)
        if gimbal is not None:
            entry["gimbal"] = {"target": [
                round(v, 3) for v in gimbal.matrix_world.translation]}
        samples.append(entry)
        prev = entry
    traj = {"scene": scene_name, "frame": "enu",
            "units": "meters, local ENU (X east, Y north, Z up); georef via scene.json",
            "samples": samples}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(traj, indent=1))
    print(f"wrote {out_path} ({len(samples)} samples, "
          f"{samples[-1]['t']:.0f}s)")


def main():
    args = parse_args()
    scene_name = "scene"
    if args.scene_json:
        import sceneforge_import as sf
        bpy.ops.wm.read_factory_settings(use_empty=True)
        root, _ = sf.load_scene(args.scene_json)
        scene_name = root.name
    if args.demo:
        build_demo_rig(args.seconds, 24)
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=args.save_blend)
    sample(args.out, args.hz, scene_name)


if __name__ == "__main__":
    main()
