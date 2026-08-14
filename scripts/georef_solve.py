"""Georeference an SfM solve from ground control: similarity solve + apply.

Triangulates every constraint GCP from its pixel tags in the solve frame
(sfm_io), then fits a 7-DOF similarity (Umeyama: scale, rotation,
translation) mapping solve-frame points onto the surveyed coordinates minus
a local origin offset (raw UTM magnitudes are numerically hostile — same
lesson as gcp_to_micmac). Held-out checkpoints are excluded from the fit and
reported after transformation: that number is the honest accuracy.

Optionally applies the transform to one or more meshes, writing
<stem>_geo.glb plus the georef sidecar json ({proj4, utm_offset}) that
prep_godot / true_ortho consume.

Usage:
  python scripts/georef_solve.py <odm run dir | cameras.sfm> \
      --gcp data/site/gcp_list.txt --checkpoints gcp05 gcp06 \
      [--apply runs/site/texturing/mesh.glb] [-o runs/site/georef]
"""
import argparse
import json
from pathlib import Path

import numpy as np

from sfm_io import load_solve, parse_gcp_list, triangulate_tags


def umeyama(src, dst):
    """Least-squares similarity: dst ~= s * R @ src + t."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    sc, dc = src - mu_s, dst - mu_d
    cov = dc.T @ sc / len(src)
    U, S, Vt = np.linalg.svd(cov)
    d = np.sign(np.linalg.det(U) * np.linalg.det(Vt))
    D = np.diag([1.0, 1.0, d])
    R = U @ D @ Vt
    var_s = (sc ** 2).sum() / len(src)
    s = float(np.trace(np.diag(S) @ D) / var_s)
    t = mu_d - s * R @ mu_s
    return s, R, t


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("solve", type=Path, help="ODM run dir or AliceVision .sfm/.json")
    ap.add_argument("--gcp", type=Path, required=True, help="gcp_list.txt (proj4 header + rows)")
    ap.add_argument("--checkpoints", nargs="*", default=[],
                    help="GCP names held out of the fit, reported as accuracy")
    ap.add_argument("--max-ray-miss", type=float, default=0.5,
                    help="drop GCPs whose tags disagree by more than this (m)")
    ap.add_argument("--offset", nargs=2, type=float, metavar=("E", "N"),
                    help="local origin (default: auto, floor of min corner to 100m)")
    ap.add_argument("--no-offset", action="store_true", help="keep raw ground coordinates")
    ap.add_argument("--apply", nargs="*", type=Path, default=[],
                    help="meshes to transform into the georeferenced local frame")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output dir (default: <solve dir>/georef)")
    args = ap.parse_args()

    out_dir = args.out or (args.solve if args.solve.is_dir() else args.solve.parent) / "georef"
    out_dir.mkdir(parents=True, exist_ok=True)

    proj4, tags = parse_gcp_list(args.gcp)
    points = triangulate_tags(load_solve(args.solve), tags)

    surveyed_all = np.array([p["surveyed"] for p in points.values()])
    if args.no_offset:
        offset = np.zeros(3)
    elif args.offset:
        offset = np.array([args.offset[0], args.offset[1], 0.0])
    else:
        offset = np.array([float(int(surveyed_all[:, k].min() // 100) * 100)
                           for k in range(2)] + [0.0])

    bad = [n for n, p in points.items() if max(p["ray_miss_m"]) > args.max_ray_miss]
    fit_names = [n for n in sorted(points)
                 if n not in args.checkpoints and n not in bad]
    if len(fit_names) < 3:
        raise SystemExit(f"need >=3 clean constraint GCPs to fit, have {len(fit_names)}")

    src = np.array([points[n]["est"] for n in fit_names])
    dst = np.array([points[n]["surveyed"] - offset for n in fit_names])
    s, R, t = umeyama(src, dst)

    def residuals(names):
        rows = {}
        for n in names:
            d = (s * R @ points[n]["est"] + t) - (points[n]["surveyed"] - offset)
            rows[n] = {"dE": d[0], "dN": d[1], "dZ": d[2],
                       "horiz": float(np.hypot(d[0], d[1]))}
        return rows

    fit_res = residuals(fit_names)
    chk_res = residuals([n for n in sorted(points)
                         if n in args.checkpoints and n not in bad])

    def rmse(rows):
        return float(np.sqrt(np.mean([r["horiz"] ** 2 for r in rows.values()]))) if rows else None

    print(f"similarity fit on {len(fit_names)} GCPs: scale {s:.6f}, "
          f"rotation {np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))):.3f} deg, "
          f"|t| {np.linalg.norm(t):.2f} m")
    for label, rows in (("constraint", fit_res), ("checkpoint", chk_res)):
        for n, r in rows.items():
            print(f"  {n:8} {label:10} dE {r['dE']:7.3f}  dN {r['dN']:7.3f}  "
                  f"dZ {r['dZ']:7.3f}  horiz {r['horiz']:.3f}")
        if rows:
            print(f"{label} horizontal RMSE: {rmse(rows):.3f} m  (n={len(rows)})")
    if bad:
        print(f"excluded for inconsistent tags (ray miss > {args.max_ray_miss} m): {', '.join(bad)}")

    transform = {
        "scale": s,
        "rotation": R.tolist(),
        "translation": t.tolist(),
        "maps": "geo_local = scale * rotation @ solve_frame + translation",
        "proj4": proj4,
        "utm_offset": [offset[0], offset[1]],
        "fit_gcps": fit_names,
        "constraint_residuals": fit_res,
        "checkpoint_residuals": chk_res,
        "constraint_rmse_h": rmse(fit_res),
        "checkpoint_rmse_h": rmse(chk_res),
        "excluded_bad_tags": bad,
    }
    tf_path = out_dir / "georef_transform.json"
    tf_path.write_text(json.dumps(transform, indent=2))
    print(f"wrote {tf_path}")

    for mesh_path in args.apply:
        import trimesh
        loaded = trimesh.load(str(mesh_path))
        meshes = loaded.geometry.values() if isinstance(loaded, trimesh.Scene) else [loaded]
        for m in meshes:
            m.vertices = (s * (R @ m.vertices.T)).T + t
        out_mesh = out_dir / f"{mesh_path.stem}_geo.glb"
        loaded.export(str(out_mesh))
        sidecar = out_mesh.with_suffix(".json")
        sidecar.write_text(json.dumps(
            {"proj4": proj4, "utm_offset": [offset[0], offset[1]]}, indent=2))
        print(f"wrote {out_mesh} + {sidecar.name}")


if __name__ == "__main__":
    main()
