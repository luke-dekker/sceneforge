"""Checkpoint residuals for an ODM run.

ODM has no native GCP holdout (issue #1302), so we grade runs ourselves:
run ODM with a constraint-only gcp_list, then triangulate every GCP in the
full list from its pixel tags using the solved camera poses
(odm_report/shots.geojson + cameras.json) and compare against the surveyed
coordinates. Constraining GCPs double as a sanity check on this script's
projection math — they were in the solve, so their residuals must be small.

Usage:
  python scripts/gcp_residuals.py runs/copr-gcp --gcp data/copr/gcp_list.txt \
      --checkpoints gcp05 gcp06
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def rodrigues(rvec):
    theta = np.linalg.norm(rvec)
    if theta < 1e-12:
        return np.eye(3)
    k = rvec / theta
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * K @ K


def undistort_brown(xd, yd, cam, iters=20):
    """Invert the Brown model by fixed-point iteration (opensfm convention)."""
    k1, k2, k3 = cam.get("k1", 0), cam.get("k2", 0), cam.get("k3", 0)
    p1, p2 = cam.get("p1", 0), cam.get("p2", 0)
    x, y = xd, yd
    for _ in range(iters):
        r2 = x * x + y * y
        radial = 1 + r2 * (k1 + r2 * (k2 + r2 * k3))
        dx = 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
        dy = p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
        x = (xd - dx) / radial
        y = (yd - dy) / radial
    return x, y


def pixel_bearing(px, py, cam):
    """Pixel -> unit ray in camera frame (opensfm normalized coordinates)."""
    size = max(cam["width"], cam["height"])
    xn = (px - (cam["width"] - 1) / 2.0) / size
    yn = (py - (cam["height"] - 1) / 2.0) / size
    xd = (xn - cam.get("c_x", 0)) / cam["focal_x"]
    yd = (yn - cam.get("c_y", 0)) / cam.get("focal_y", cam["focal_x"])
    x, y = undistort_brown(xd, yd, cam)
    b = np.array([x, y, 1.0])
    return b / np.linalg.norm(b)


def triangulate(origins, dirs):
    """Least-squares point closest to all rays."""
    A = np.zeros((3, 3))
    b = np.zeros(3)
    for o, d in zip(origins, dirs):
        P = np.eye(3) - np.outer(d, d)
        A += P
        b += P @ o
    return np.linalg.solve(A, b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--gcp", type=Path, required=True, help="full gcp_list.txt (all tags)")
    ap.add_argument("--checkpoints", nargs="*", default=[], help="held-out GCP names")
    ap.add_argument("--max-ray-miss", type=float, default=0.5,
                    help="flag GCPs whose tags disagree by more than this (m) and drop from RMSE")
    args = ap.parse_args()

    cameras = json.load(open(args.run_dir / "cameras.json"))
    shots = {f["properties"]["filename"]: f["properties"]
             for f in json.load(open(args.run_dir / "odm_report" / "shots.geojson"))["features"]}

    tags = defaultdict(list)   # gcp name -> [(surveyed xyz, image, px, py)]
    for line in args.gcp.read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        gx, gy, gz, px, py = map(float, parts[:5])
        image, name = parts[5], (parts[6] if len(parts) > 6 else f"gcp@{parts[0]},{parts[1]}")
        tags[name].append(((gx, gy, gz), image, px, py))

    def cam_for(shot):
        key = shot["camera"].removeprefix("v2 ")
        return cameras[key]

    rows = []
    for name in sorted(tags):
        surveyed = np.array(tags[name][0][0])
        origins, dirs, skipped = [], [], 0
        for _, image, px, py in tags[name]:
            shot = shots.get(image)
            if shot is None:
                skipped += 1
                continue
            R = rodrigues(np.array(shot["rotation"]))  # world -> camera
            origins.append(np.array(shot["translation"]))
            dirs.append(R.T @ pixel_bearing(px, py, cam_for(shot)))
        if len(origins) < 2:
            print(f"{name}: <2 usable rays ({skipped} images missing from solve), skipped")
            continue
        est = triangulate(origins, dirs)
        d = est - surveyed
        # Distance from the triangulated point to each ray: mutually consistent
        # tags give small misses; one large miss = that image's tag is bad.
        misses = [float(np.linalg.norm((np.eye(3) - np.outer(dr, dr)) @ (est - o)))
                  for o, dr in zip(origins, dirs)]
        role = "checkpoint" if name in args.checkpoints else "constraint"
        if max(misses) > args.max_ray_miss:
            role += " BAD-TAGS"
        rows.append({"name": name, "role": role,
                     "rays": len(origins), "dE": d[0], "dN": d[1], "dZ": d[2],
                     "horiz": float(np.hypot(d[0], d[1])),
                     "ray_miss_m": [round(m, 2) for m in misses]})

    print(f"{'name':8} {'role':10} {'rays':4}  {'dE m':>8} {'dN m':>8} {'dZ m':>8} {'horiz m':>8}  ray-miss m")
    for r in rows:
        print(f"{r['name']:8} {r['role']:10} {r['rays']:4}  "
              f"{r['dE']:8.3f} {r['dN']:8.3f} {r['dZ']:8.3f} {r['horiz']:8.3f}  {r['ray_miss_m']}")
    for role in ("constraint", "checkpoint"):
        sub = [r for r in rows if r["role"] == role]  # BAD-TAGS rows excluded
        if sub:
            rmse_h = float(np.sqrt(np.mean([r["horiz"] ** 2 for r in sub])))
            print(f"{role} horizontal RMSE: {rmse_h:.3f} m  (n={len(sub)})")
    bad = [r["name"] for r in rows if "BAD-TAGS" in r["role"]]
    if bad:
        print(f"excluded for inconsistent tags (ray miss > {args.max_ray_miss} m): {', '.join(bad)}")

    out = args.run_dir / "gcp_residuals.json"
    out.write_text(json.dumps(rows, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
