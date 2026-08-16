"""Build a Blender project (and optional flythrough render) from a sceneforge
scene, by driving Blender headless with blender/sceneforge_blend.py.

Usage: python scripts/blender_scene.py --scene-json <scene.json> --out <dir> \
           [--render] [--datetime "YYYY-MM-DD HH:MM"] [--utc-offset -7] \
           [--seconds 12] [--fps 24] [--res 1920x1080] [--samples 32] \
           [--blender <blender.exe>]
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BLEND_SCRIPT = Path(__file__).resolve().parents[1] / "blender" / "sceneforge_blend.py"


def find_blender(explicit):
    if explicit:
        return explicit
    candidates = []
    for base in (Path(r"C:\Program Files\Blender Foundation"),
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Blender Foundation"):
        if base.is_dir():
            candidates += sorted(base.glob("Blender */blender.exe"), reverse=True)
    if candidates:
        return str(candidates[0])
    return "blender"  # hope it's on PATH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-json", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--name", type=str, default=None,
                    help="output basename (default: scene name from json)")
    ap.add_argument("--render", action="store_true",
                    help="also render an orbit flythrough mp4")
    ap.add_argument("--datetime", type=str, default=None)
    ap.add_argument("--utc-offset", type=float, default=-7.0)
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--res", type=str, default="1920x1080")
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--orbit-degrees", type=float, default=300.0)
    ap.add_argument("--blender", type=str, default=None,
                    help="path to blender.exe (default: newest install found)")
    args = ap.parse_args()

    import json
    name = args.name or json.loads(
        args.scene_json.read_text(encoding="utf-8-sig"))["name"]
    args.out.mkdir(parents=True, exist_ok=True)
    out_blend = args.out / f"{name}.blend"

    cmd = [find_blender(args.blender), "--background",
           "--python", str(BLEND_SCRIPT), "--",
           "--scene-json", str(args.scene_json),
           "--out-blend", str(out_blend),
           "--utc-offset", str(args.utc_offset),
           "--seconds", str(args.seconds), "--fps", str(args.fps),
           "--res", args.res, "--samples", str(args.samples),
           "--orbit-degrees", str(args.orbit_degrees)]
    if args.datetime:
        cmd += ["--datetime", args.datetime]
    if args.render:
        cmd += ["--render", str(args.out / f"{name}-flythrough.mp4")]

    print("run:", " ".join(cmd))
    proc = subprocess.run(cmd)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
