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

from sfm_io import load_solve, load_view_gps, parse_gcp_list, triangulate_tags


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


def camera_gps_points(args):
    """Camera centres as pseudo-GCPs: est = solve-frame centre, surveyed = projected GPS.

    Returns (proj4, points, checkpoint_names). Fit set = --fit-views regex, else
    RTK-fixed views (DJI RtkFlag 50), else all views; everything else is a
    checkpoint so a non-RTK second camera (e.g. a Mini 3) still gets graded
    against its own GPS (metre-grade horizontally, altitude often garbage).
    """
    import re
    from pyproj import Transformer

    shots = load_solve(args.solve)
    gps = load_view_gps(args.solve)
    common = sorted(n for n in shots if n in gps)
    if len(common) < 3:
        raise SystemExit(f"need >=3 localized views with GPS, have {len(common)}")
    lon0 = float(np.mean([gps[n]["lon"] for n in common]))
    lat0 = float(np.mean([gps[n]["lat"] for n in common]))
    proj4 = args.proj or (f"+proj=utm +zone={int((lon0 + 180) // 6) + 1} "
                          f"{'+south ' if lat0 < 0 else ''}+datum=WGS84 +units=m +no_defs")
    tf = Transformer.from_crs("EPSG:4326", proj4, always_xy=True)
    if args.fit_views:
        rx = re.compile(args.fit_views)
        fit = [n for n in common if rx.search(n)]
    else:
        fit = [n for n in common if gps[n]["rtk"] == 50] or list(common)
    points = {}
    for n in common:
        e, nn = tf.transform(gps[n]["lon"], gps[n]["lat"])
        points[n] = {"est": shots[n].origin, "surveyed": np.array([e, nn, gps[n]["alt"]]),
                     "rays": 1, "ray_miss_m": [0.0]}
    print(f"camera-gps mode: {len(common)} localized views with GPS, fitting on {len(fit)} "
          f"({'RTK-fixed' if not args.fit_views and any(gps[n]['rtk'] == 50 for n in fit) else 'selected'}), "
          f"{len(common) - len(fit)} checkpoints; frame {proj4}")
    return proj4, points, [n for n in common if n not in fit]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("solve", type=Path, help="ODM run dir or AliceVision .sfm/.json")
    ap.add_argument("--gcp", type=Path, default=None, help="gcp_list.txt (proj4 header + rows)")
    ap.add_argument("--camera-gps", action="store_true",
                    help="no GCPs: fit on the solve's camera centres vs their EXIF/XMP GPS "
                         "(RTK-fixed drones = cm-grade georef; non-RTK views become checkpoints)")
    ap.add_argument("--fit-views", type=str, default=None,
                    help="camera-gps: regex on filenames to fit on (default: DJI RtkFlag==50 "
                         "views if any, else every view with GPS)")
    ap.add_argument("--proj", type=str, default=None,
                    help="camera-gps: proj4 of the ground frame (default: WGS84 UTM zone of the site)")
    ap.add_argument("--checkpoints", nargs="*", default=[],
                    help="GCP names held out of the fit, reported as accuracy")
    ap.add_argument("--max-ray-miss", type=float, default=0.5,
                    help="drop GCPs whose tags disagree by more than this (m)")
    ap.add_argument("--offset", nargs=2, type=float, metavar=("E", "N"),
                    help="local origin (default: auto, floor of min corner to 100m)")
    ap.add_argument("--no-offset", action="store_true", help="keep raw ground coordinates")
    ap.add_argument("--apply", nargs="*", type=Path, default=[],
                    help="meshes to transform into the georeferenced local frame")
    ap.add_argument("--crop-margin", type=float, default=None, metavar="M",
                    help="on --apply: drop faces outside the constraint/checkpoint E/N bounding "
                         "box grown by M metres (kills reconstruction fringe)")
    ap.add_argument("--crop-z-depth", type=float, default=None, metavar="D",
                    help="on --apply: drop faces more than D metres below the mesh's median Z "
                         "(kills the below-ground skirt Meshroom leaves under flat sites)")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output dir (default: <solve dir>/georef)")
    args = ap.parse_args()

    out_dir = args.out or (args.solve if args.solve.is_dir() else args.solve.parent) / "georef"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.camera_gps:
        proj4, points, args.checkpoints = camera_gps_points(args)
        method = "camera_gps"
    elif args.gcp:
        proj4, tags = parse_gcp_list(args.gcp)
        points = triangulate_tags(load_solve(args.solve), tags)
        method = "gcp"
    else:
        raise SystemExit("need --gcp <gcp_list.txt> or --camera-gps")

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
    def rmse_z(rows):
        return float(np.sqrt(np.mean([r["dZ"] ** 2 for r in rows.values()]))) if rows else None

    for label, rows in (("constraint", fit_res), ("checkpoint", chk_res)):
        shown = rows if len(rows) <= 20 else dict(
            sorted(rows.items(), key=lambda kv: -kv[1]["horiz"])[:5])
        if len(rows) > 20:
            print(f"  ({label}: {len(rows)} rows, showing 5 worst horizontal)")
        for n, r in shown.items():
            print(f"  {n:32} {label:10} dE {r['dE']:7.3f}  dN {r['dN']:7.3f}  "
                  f"dZ {r['dZ']:7.3f}  horiz {r['horiz']:.3f}")
        if rows:
            print(f"{label} horizontal RMSE: {rmse(rows):.3f} m, vertical RMSE: "
                  f"{rmse_z(rows):.3f} m  (n={len(rows)})")
    if bad:
        print(f"excluded for inconsistent tags (ray miss > {args.max_ray_miss} m): {', '.join(bad)}")

    transform = {
        "method": method,
        "vertical_datum": ("as written by the camera (DJI RTK: WGS84 ellipsoid)"
                           if method == "camera_gps" else "as surveyed in gcp_list"),
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
        geo_pts = np.array([points[n]["surveyed"] - offset for n in points])
        for m in meshes:
            m.vertices = (s * (R @ m.vertices.T)).T + t
            keep = np.ones(len(m.faces), bool)
            fv = m.vertices[m.faces]                      # (F, 3, 3)
            if args.crop_margin is not None:
                lo, hi = geo_pts[:, :2].min(0) - args.crop_margin, geo_pts[:, :2].max(0) + args.crop_margin
                inside = ((fv[:, :, 0] >= lo[0]) & (fv[:, :, 0] <= hi[0]) &
                          (fv[:, :, 1] >= lo[1]) & (fv[:, :, 1] <= hi[1]))
                keep &= inside.any(1)
            if args.crop_z_depth is not None:
                floor = float(np.median(m.vertices[:, 2])) - args.crop_z_depth
                keep &= (fv[:, :, 2] >= floor).all(1)
            if not keep.all():
                before = len(m.faces)
                m.update_faces(keep)
                m.remove_unreferenced_vertices()
                print(f"  cropped {before - len(m.faces):,} of {before:,} faces "
                      f"(margin={args.crop_margin}, z_depth={args.crop_z_depth})")
            # Meshroom's OBJ comes out wound inside-out (~90% of face normals
            # point into the ground); engines with backface culling then show
            # the underside. The ground frame is Z-up, so a terrain mesh whose
            # normals mostly point down is flipped: invert winding globally.
            frac_up = float((m.face_normals[:, 2] > 0).mean())
            if frac_up < 0.5:
                m.invert()
                print(f"  inverted winding ({frac_up:.0%} of faces pointed down)")
        out_mesh = out_dir / f"{mesh_path.stem}_geo.glb"
        loaded.export(str(out_mesh))
        sidecar = out_mesh.with_suffix(".json")
        sidecar.write_text(json.dumps(
            {"proj4": proj4, "utm_offset": [offset[0], offset[1]],
             "vertical_datum": transform["vertical_datum"], "georef_method": method},
            indent=2))
        print(f"wrote {out_mesh} + {sidecar.name}")


if __name__ == "__main__":
    main()
