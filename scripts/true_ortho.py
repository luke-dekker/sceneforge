"""True orthophoto + DSM from a textured, georeferenced mesh.

Rasterizes the mesh straight down with a per-pixel z-buffer, so buildings and
trees keep their footprints instead of smearing — a true ortho by
construction, from whatever mesh you consider final (e.g. after GeorefSolve).
Also emits the matching DSM from the same z-buffer.

The mesh is local metres, Z-up; its georef sidecar json ({proj4, utm_offset},
default <mesh>.json) places the output in the CRS. Both GeoTIFFs carry full
CRS coordinates and open directly in QGIS.

Untextured meshes fall back to a hillshade render so the ortho stays
readable.

Usage:
  python scripts/true_ortho.py runs/site/mesh_geo.glb --gsd 0.10 -o runs/site/ortho/site
"""
import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
import trimesh


def load_meshes(path):
    loaded = trimesh.load(str(path))
    if isinstance(loaded, trimesh.Scene):
        return list(loaded.dump())
    return [loaded]


def texture_sampler(mesh):
    """Return (uv array or None, sample(u, v) -> RGB uint8)."""
    vis = mesh.visual
    if (hasattr(vis, "uv") and vis.uv is not None and vis.uv.shape[0] == len(mesh.vertices)
            and getattr(vis, "material", None) is not None):
        img = getattr(vis.material, "baseColorTexture", None) or getattr(vis.material, "image", None)
        if img is not None:
            tex = np.asarray(img.convert("RGB"))
            th, tw = tex.shape[:2]

            def sample(u, v):
                # trimesh UV origin is bottom-left; wrap so Meshroom's UDIM
                # tiles (u offset by tile index, one texture per material) sample
                # their own atlas instead of clamping to the edge pixel
                u, v = u - np.floor(u), v - np.floor(v)
                col = np.clip((u * (tw - 1)).astype(int), 0, tw - 1)
                row = np.clip(((1.0 - v) * (th - 1)).astype(int), 0, th - 1)
                return tex[row, col]
            return np.asarray(vis.uv, float), sample
    return None, None


def rasterize(meshes, gsd, max_dim):
    all_v = np.vstack([m.vertices for m in meshes])
    xmin, ymin = all_v[:, 0].min(), all_v[:, 1].min()
    xmax, ymax = all_v[:, 0].max(), all_v[:, 1].max()
    w = int(np.ceil((xmax - xmin) / gsd))
    h = int(np.ceil((ymax - ymin) / gsd))
    if max(w, h) > max_dim:
        raise SystemExit(f"raster {w}x{h} exceeds --max-dim {max_dim}; raise --gsd")

    zbuf = np.full((h, w), -np.inf, dtype=np.float64)
    rgb = np.zeros((h, w, 3), dtype=np.uint8)

    for mesh in meshes:
        V = np.asarray(mesh.vertices, float)
        F = np.asarray(mesh.faces)
        uv, sample = texture_sampler(mesh)
        if sample is None:
            # Hillshade fallback: light from the NW, classic relief look.
            n = mesh.vertex_normals
            light = np.array([-0.5, 0.5, 0.707])
            shade = np.clip(n @ light, 0.15, 1.0)
        # Pixel coords: col from x, row from y (row 0 = north/ymax).
        px = (V[:, 0] - xmin) / gsd
        py = (ymax - V[:, 1]) / gsd
        for f in F:
            tx, ty, tz = px[f], py[f], V[f, 2]
            c0 = max(int(np.floor(tx.min())), 0)
            c1 = min(int(np.ceil(tx.max())) + 1, w)
            r0 = max(int(np.floor(ty.min())), 0)
            r1 = min(int(np.ceil(ty.max())) + 1, h)
            if c0 >= c1 or r0 >= r1:
                continue
            denom = (ty[1] - ty[2]) * (tx[0] - tx[2]) + (tx[2] - tx[1]) * (ty[0] - ty[2])
            if abs(denom) < 1e-12:
                continue
            cc, rr = np.meshgrid(np.arange(c0, c1) + 0.5, np.arange(r0, r1) + 0.5)
            w0 = ((ty[1] - ty[2]) * (cc - tx[2]) + (tx[2] - tx[1]) * (rr - ty[2])) / denom
            w1 = ((ty[2] - ty[0]) * (cc - tx[2]) + (tx[0] - tx[2]) * (rr - ty[2])) / denom
            w2 = 1.0 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            z = w0 * tz[0] + w1 * tz[1] + w2 * tz[2]
            block = zbuf[r0:r1, c0:c1]
            upd = inside & (z > block)
            if not upd.any():
                continue
            block[upd] = z[upd]
            if sample is not None:
                tuv = uv[f]
                u = w0 * tuv[0, 0] + w1 * tuv[1, 0] + w2 * tuv[2, 0]
                v = w0 * tuv[0, 1] + w1 * tuv[1, 1] + w2 * tuv[2, 1]
                rgb[r0:r1, c0:c1][upd] = sample(u[upd], v[upd])
            else:
                s = shade[f]
                g = ((w0 * s[0] + w1 * s[1] + w2 * s[2]) * 255).astype(np.uint8)
                rgb[r0:r1, c0:c1][upd] = g[upd, None]
    return rgb, zbuf, (xmin, ymax)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mesh", type=Path, help="textured mesh, local metres, Z-up (glb/obj, non-Draco)")
    ap.add_argument("--sidecar", type=Path, default=None,
                    help="georef sidecar json (default: <mesh>.json)")
    ap.add_argument("--gsd", type=float, default=0.10, help="ground sample distance m/px (default 0.10)")
    ap.add_argument("--max-dim", type=int, default=16384, help="raster dimension cap")
    ap.add_argument("-o", "--out", required=True, help="output stem, e.g. runs/site/ortho/site")
    args = ap.parse_args()

    sidecar = args.sidecar or args.mesh.with_suffix(".json")
    if not sidecar.exists():
        raise SystemExit(f"no georef sidecar at {sidecar} (need {{proj4, utm_offset}})")
    sc = json.loads(sidecar.read_text())
    proj4, (e0, n0) = sc["proj4"], sc["utm_offset"]

    meshes = load_meshes(args.mesh)
    ntris = sum(len(m.faces) for m in meshes)
    print(f"rasterizing {ntris:,} triangles at {args.gsd} m/px ...")
    rgb, zbuf, (xmin, ymax) = rasterize(meshes, args.gsd, args.max_dim)
    h, w = zbuf.shape
    hit = np.isfinite(zbuf)
    print(f"{w}x{h} px, {hit.mean() * 100:.1f}% covered")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    crs = rasterio.crs.CRS.from_proj4(proj4)
    transform = from_origin(xmin + e0, ymax + n0, args.gsd, args.gsd)

    alpha = np.where(hit, 255, 0).astype(np.uint8)
    with rasterio.open(out.with_suffix(".tif"), "w", driver="GTiff", width=w, height=h,
                       count=4, dtype="uint8", crs=crs, transform=transform,
                       photometric="RGB", alpha="yes", compress="deflate") as dst:
        for i in range(3):
            dst.write(rgb[:, :, i], i + 1)
        dst.write(alpha, 4)

    dsm = np.where(hit, zbuf, -9999.0).astype(np.float32)
    with rasterio.open(out.parent / f"{out.name}_dsm.tif", "w", driver="GTiff",
                       width=w, height=h, count=1, dtype="float32", crs=crs,
                       transform=transform, nodata=-9999.0, compress="deflate") as dst:
        dst.write(dsm, 1)

    out.with_suffix(".json").write_text(json.dumps({
        "proj4": proj4, "gsd_m": args.gsd,
        "origin_e_n": [xmin + e0, ymax + n0], "size_px": [w, h],
        "elevation_range_m": [float(zbuf[hit].min()), float(zbuf[hit].max())] if hit.any() else None,
    }, indent=2))
    print(f"wrote {out.with_suffix('.tif')}")
    print(f"wrote {out.parent / (out.name + '_dsm.tif')}")


if __name__ == "__main__":
    main()
