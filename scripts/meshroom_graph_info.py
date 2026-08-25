"""Summarize a Meshroom .mg graph: views per intrinsic, sensor/focal/distortion.

Run after building a graph and before computing — a wrong sensor width or a
camera split into several intrinsics shows up here, not three hours later.

Usage: python scripts/meshroom_graph_info.py runs/site/site.mg
"""
import collections
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    g = json.load(open(Path(sys.argv[1])))
    ci = g["graph"]["CameraInit_1"]["inputs"]
    views, intr = ci["viewpoints"], ci["intrinsics"]
    by = collections.Counter(v["intrinsicId"] for v in views)
    print(f"  {len(views)} views, {len(intr)} intrinsics")
    for i in intr:
        print(f"    {by[i['intrinsicId']]:4d} views  {i['width']}x{i['height']}  "
              f"sensor {i['sensorWidth']} mm  focal {i['focalLength']} mm  "
              f"{i['type']}/{i.get('distortionType', '?')}  init={i.get('initializationMode')}")
    if any(i["initializationMode"] not in ("estimated", "calibrated") for i in intr):
        print("  WARNING: an intrinsic is not initialized from metadata — check the sensor DB")


if __name__ == "__main__":
    main()
