"""Camera-solve I/O shared by the geo tools (gcp_residuals, georef_solve).

Loads solved camera poses + intrinsics from either pipeline:
  - ODM run dir: cameras.json + odm_report/shots.geojson (OpenSfM conventions)
  - AliceVision sfmData json: cameras.sfm from StructureFromMotion or
    ConvertSfMFormat (Meshroom)

Shot convention: `R` is world->camera, `origin` is the camera center in world
coordinates, so the world-space viewing ray through a pixel is
`shot.ray(px, py) = R.T @ bearing(px, py)`.

The ODM path is validated against known runs (copr gradings). The AliceVision
path follows the 2025.1 sfmData format (string-encoded numerics, pose stored
as X_cam = R @ (X - center)) but has not yet been checked against a native
Meshroom solve — verify residuals on the first real run before trusting it.
"""
import json
from pathlib import Path

import numpy as np


def rodrigues(rvec):
    theta = np.linalg.norm(rvec)
    if theta < 1e-12:
        return np.eye(3)
    k = rvec / theta
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * K @ K


def undistort_iterative(xd, yd, radial, tangential=(0.0, 0.0), iters=20):
    """Invert a polynomial radial(+tangential) model by fixed-point iteration."""
    k1, k2, k3 = (list(radial) + [0.0, 0.0, 0.0])[:3]
    p1, p2 = tangential
    x, y = xd, yd
    for _ in range(iters):
        r2 = x * x + y * y
        rad = 1 + r2 * (k1 + r2 * (k2 + r2 * k3))
        dx = 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
        dy = p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
        x = (xd - dx) / rad
        y = (yd - dy) / rad
    return x, y


def triangulate(origins, dirs):
    """Least-squares point closest to all rays."""
    A = np.zeros((3, 3))
    b = np.zeros(3)
    for o, d in zip(origins, dirs):
        P = np.eye(3) - np.outer(d, d)
        A += P
        b += P @ o
    return np.linalg.solve(A, b)


def parse_gcp_list(path):
    """ODM gcp_list.txt -> (proj4 header, {name: [(surveyed xyz, image, px, py)]})."""
    lines = Path(path).read_text().splitlines()
    proj4 = lines[0].strip()
    tags = {}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        gx, gy, gz, px, py = map(float, parts[:5])
        image = parts[5]
        name = parts[6] if len(parts) > 6 else f"gcp@{parts[0]},{parts[1]}"
        tags.setdefault(name, []).append(((gx, gy, gz), image, px, py))
    return proj4, tags


def triangulate_tags(shots, tags):
    """Triangulate each tagged GCP from its pixel tags in the solve frame.

    Returns {name: {"est": xyz, "surveyed": xyz, "rays": n, "ray_miss_m": [...]}},
    skipping points with fewer than two usable rays. A large ray miss on one
    image means that image's tag is bad.
    """
    out = {}
    for name, entries in tags.items():
        origins, dirs = [], []
        for _, image, px, py in entries:
            shot = shots.get(image)
            if shot is None:
                continue
            origins.append(shot.origin)
            dirs.append(shot.ray(px, py))
        if len(origins) < 2:
            continue
        est = triangulate(origins, dirs)
        misses = [float(np.linalg.norm((np.eye(3) - np.outer(d, d)) @ (est - o)))
                  for o, d in zip(origins, dirs)]
        out[name] = {"est": est, "surveyed": np.array(entries[0][0]),
                     "rays": len(origins), "ray_miss_m": misses}
    return out


class Shot:
    def __init__(self, origin, R, bearing):
        self.origin = np.asarray(origin, dtype=float)
        self.R = R                  # world -> camera
        self._bearing = bearing     # (px, py) -> unit ray, camera frame

    def ray(self, px, py):
        """World-frame unit direction through pixel (px, py)."""
        return self.R.T @ self._bearing(px, py)


def load_solve(source):
    """Return {image filename: Shot} from an ODM run dir or AliceVision .sfm."""
    p = Path(source)
    if p.is_dir():
        return _load_odm(p)
    return _load_alicevision(p)


# --- ODM (OpenSfM conventions: normalized coords, brown model) ---

def _opensfm_bearing(cam):
    def bearing(px, py):
        size = max(cam["width"], cam["height"])
        xn = (px - (cam["width"] - 1) / 2.0) / size
        yn = (py - (cam["height"] - 1) / 2.0) / size
        xd = (xn - cam.get("c_x", 0)) / cam["focal_x"]
        yd = (yn - cam.get("c_y", 0)) / cam.get("focal_y", cam["focal_x"])
        x, y = undistort_iterative(
            xd, yd,
            radial=(cam.get("k1", 0), cam.get("k2", 0), cam.get("k3", 0)),
            tangential=(cam.get("p1", 0), cam.get("p2", 0)))
        b = np.array([x, y, 1.0])
        return b / np.linalg.norm(b)
    return bearing


def _load_odm(run_dir):
    cameras = json.load(open(run_dir / "cameras.json"))
    feats = json.load(open(run_dir / "odm_report" / "shots.geojson"))["features"]
    shots = {}
    for f in feats:
        props = f["properties"]
        cam = cameras[props["camera"].removeprefix("v2 ")]
        shots[props["filename"]] = Shot(
            origin=props["translation"],   # shots.geojson stores the optical center
            R=rodrigues(np.array(props["rotation"])),
            bearing=_opensfm_bearing(cam))
    return shots


# --- AliceVision sfmData (pixel coords, unit-focal-plane distortion) ---

def _f(v):
    """AliceVision json encodes numbers as strings."""
    if isinstance(v, (list, tuple)):
        return [float(x) for x in v]
    return float(v)


def _alicevision_bearing(intr):
    width, height = _f(intr["width"]), _f(intr["height"])
    if "pxFocalLength" in intr:
        fpx = _f(intr["pxFocalLength"])
        fx, fy = (fpx if isinstance(fpx, list) else [fpx, fpx])[:2]
    else:
        fx = fy = _f(intr["focalLength"]) * width / _f(intr["sensorWidth"])
    ppx, ppy = _f(intr.get("principalPoint", [0.0, 0.0]))
    # Newer sfmData stores the principal point as an offset from the image
    # center; very old files stored it absolute. Disambiguate by magnitude.
    if abs(ppx) > width / 4 or abs(ppy) > height / 4:
        cx, cy = ppx, ppy
    else:
        cx, cy = width / 2.0 + ppx, height / 2.0 + ppy
    dist = _f(intr.get("distortionParams", []) or [])
    model = intr.get("type", "pinhole")
    if model.startswith("brown"):
        radial, tangential = dist[:3], (dist + [0, 0, 0, 0, 0])[3:5]
    else:                       # radial1 / radial3 / pinhole
        radial, tangential = dist[:3], (0.0, 0.0)

    def bearing(px, py):
        xd = (px - cx) / fx
        yd = (py - cy) / fy
        x, y = undistort_iterative(xd, yd, radial, tangential)
        b = np.array([x, y, 1.0])
        return b / np.linalg.norm(b)
    return bearing


def _dms(s, ref):
    """'47, 4, 9.702' + 'N' -> signed decimal degrees (also accepts a plain float)."""
    parts = [float(x) for x in str(s).replace(",", " ").split()]
    val = parts[0] + (parts[1] if len(parts) > 1 else 0) / 60 + (parts[2] if len(parts) > 2 else 0) / 3600
    return -val if ref in ("S", "W") else val


def load_view_gps(source):
    """Return {image filename: {lat, lon, alt, rtk}} for every view carrying GPS.

    AliceVision keeps the EXIF/XMP block per view (cameraInit.sfm / sfm.json);
    ODM exposes images.json. `rtk` is DJI's RtkFlag (50 = fixed) or None for
    cameras without RTK. Altitude is whatever the camera wrote (DJI RTK models:
    WGS84 ellipsoid); AltitudeRef 1 (below sea level) is honoured by negating.
    """
    p = Path(source)
    out = {}
    if p.is_dir():
        for im in json.load(open(p / "images.json")):
            if im.get("latitude") is None:
                continue
            out[im["filename"]] = {"lat": float(im["latitude"]), "lon": float(im["longitude"]),
                                   "alt": float(im.get("altitude") or 0.0), "rtk": None}
        return out
    for v in json.load(open(p))["views"]:
        md = v.get("metadata", {})
        if "GPS:Latitude" not in md or "GPS:Longitude" not in md:
            continue
        alt = float(md.get("GPS:Altitude", 0) or 0)
        if str(md.get("GPS:AltitudeRef", "0")) == "1":
            alt = -alt
        rtk = md.get("drone-dji:RtkFlag")
        out[Path(v["path"]).name] = {
            "lat": _dms(md["GPS:Latitude"], md.get("GPS:LatitudeRef", "N")),
            "lon": _dms(md["GPS:Longitude"], md.get("GPS:LongitudeRef", "E")),
            "alt": alt,
            "rtk": int(float(rtk)) if rtk not in (None, "") else None,
        }
    return out


def _load_alicevision(sfm_path):
    data = json.load(open(sfm_path))
    intrinsics = {i["intrinsicId"]: _alicevision_bearing(i)
                  for i in data["intrinsics"]}
    poses = {}
    for p in data.get("poses", []):
        t = p["pose"]["transform"]
        poses[p["poseId"]] = (
            np.array(_f(t["rotation"])).reshape(3, 3),  # world -> camera
            np.array(_f(t["center"])))
    shots = {}
    for v in data["views"]:
        pose = poses.get(v.get("poseId"))
        if pose is None:
            continue                                    # view not localized
        R, center = pose
        shots[Path(v["path"]).name] = Shot(
            origin=center, R=R, bearing=intrinsics[v["intrinsicId"]])
    return shots
