"""Checkpoint residuals for a photogrammetry solve.

ODM has no native GCP holdout (issue #1302), so we grade runs ourselves:
run the solve with a constraint-only gcp_list, then triangulate every GCP in
the full list from its pixel tags using the solved camera poses and compare
against the surveyed coordinates. Constraining GCPs double as a sanity check
on the projection math — they were in the solve, so their residuals must be
small.

The solve can be an ODM run dir (cameras.json + odm_report/shots.geojson) or
an AliceVision sfmData json (Meshroom cameras.sfm) — see sfm_io.load_solve.

Usage:
  python scripts/gcp_residuals.py runs/copr-gcp --gcp data/copr/gcp_list.txt \
      --checkpoints gcp05 gcp06
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from sfm_io import load_solve, triangulate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("solve", type=Path,
                    help="ODM run dir or AliceVision .sfm/.json")
    ap.add_argument("--gcp", type=Path, required=True, help="full gcp_list.txt (all tags)")
    ap.add_argument("--checkpoints", nargs="*", default=[], help="held-out GCP names")
    ap.add_argument("--max-ray-miss", type=float, default=0.5,
                    help="flag GCPs whose tags disagree by more than this (m) and drop from RMSE")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output json (default: <solve dir>/gcp_residuals.json)")
    args = ap.parse_args()

    shots = load_solve(args.solve)

    tags = defaultdict(list)   # gcp name -> [(surveyed xyz, image, px, py)]
    for line in args.gcp.read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        gx, gy, gz, px, py = map(float, parts[:5])
        image, name = parts[5], (parts[6] if len(parts) > 6 else f"gcp@{parts[0]},{parts[1]}")
        tags[name].append(((gx, gy, gz), image, px, py))

    rows = []
    for name in sorted(tags):
        surveyed = np.array(tags[name][0][0])
        origins, dirs, skipped = [], [], 0
        for _, image, px, py in tags[name]:
            shot = shots.get(image)
            if shot is None:
                skipped += 1
                continue
            origins.append(shot.origin)
            dirs.append(shot.ray(px, py))
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

    out = args.out or (args.solve if args.solve.is_dir() else args.solve.parent) / "gcp_residuals.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
